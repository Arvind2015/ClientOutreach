"""
Stream 4 — Resume Workflow (Tasks 5.6–5.7)

Final step in the inbound processing pipeline. Applies confidence thresholds
and either:
  1. Resumes the Step Functions state machine (via sfn:SendTaskSuccess) with
     the processed inbound result — if all attachments meet confidence thresholds.
  2. Routes to analyst review queue — if any attachment is below the confidence
     threshold.
  3. Escalates — if the case has no task token (unexpected state).

This is the critical integration point between Stream 4 and Stream 5's
state machine, which has been paused at StoreTaskTokenAndAwait.

Inputs (from extract-data output):
  - message_id: str
  - case_id: str
  - client_id: str
  - sfn_task_token: str          # from correlate-case
  - extracted_attachments: list  # [{attachment_id, s3_ref, classification,
                                 #   classification_confidence, extracted_fields,
                                 #   extraction_confidence}]

Outputs (on success):
  Calls sfn:SendTaskSuccess with the InboundMessage payload, resuming
  the state machine at ValidateAndUpdate.

  Returns:
  - message_id: str
  - case_id: str
  - action_taken: "RESUMED_WORKFLOW" | "SENT_TO_ANALYST_REVIEW" | "ESCALATED"
"""

import os
import json
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

sfn = boto3.client("stepfunctions")
sqs = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")

CASES_TABLE = os.environ["CASES_TABLE"]
cases_table = dynamodb.Table(CASES_TABLE)
ANALYST_REVIEW_QUEUE_URL = os.environ.get("ANALYST_REVIEW_QUEUE_URL", "")

# Confidence thresholds — configurable via env vars
CLASSIFICATION_CONFIDENCE_THRESHOLD = float(
    os.environ.get("CLASSIFICATION_CONFIDENCE_THRESHOLD", "0.75")
)
EXTRACTION_CONFIDENCE_THRESHOLD = float(
    os.environ.get("EXTRACTION_CONFIDENCE_THRESHOLD", "0.70")
)


def handler(event, context):
    message_id = event["message_id"]
    case_id = event["case_id"]
    client_id = event["client_id"]
    extracted_attachments = event.get("extracted_attachments", [])

    # Get task token — either passed through from correlate-case or fetch from DB
    sfn_task_token = event.get("sfn_task_token")
    if not sfn_task_token:
        sfn_task_token = _get_task_token(case_id)

    if not sfn_task_token:
        # No task token — the state machine isn't waiting for this case
        emit_audit_event(
            case_id=case_id,
            actor="resume-workflow",
            action="NO_TASK_TOKEN_FOUND",
            input_ref=message_id,
        )
        return {
            "message_id": message_id,
            "case_id": case_id,
            "action_taken": "ESCALATED",
            "reason": "No Step Functions task token found for case",
        }

    # Apply confidence thresholds
    low_confidence_items = _check_confidence(extracted_attachments)

    if low_confidence_items:
        # Route to analyst review instead of auto-accepting
        _send_to_analyst_review(case_id, message_id, extracted_attachments,
                                low_confidence_items)
        emit_audit_event(
            case_id=case_id,
            actor="resume-workflow",
            action=f"SENT_TO_ANALYST_REVIEW: {len(low_confidence_items)} low-confidence items",
            input_ref=message_id,
        )
        return {
            "message_id": message_id,
            "case_id": case_id,
            "action_taken": "SENT_TO_ANALYST_REVIEW",
            "low_confidence_items": low_confidence_items,
        }

    # All attachments pass confidence thresholds — resume the state machine
    inbound_result = _build_inbound_result(case_id, message_id, extracted_attachments)
    _resume_state_machine(sfn_task_token, inbound_result)

    # Clear the task token from the case (it's been consumed)
    _clear_task_token(case_id)

    emit_audit_event(
        case_id=case_id,
        actor="resume-workflow",
        action="WORKFLOW_RESUMED_VIA_SEND_TASK_SUCCESS",
        input_ref=message_id,
    )

    return {
        "message_id": message_id,
        "case_id": case_id,
        "action_taken": "RESUMED_WORKFLOW",
    }


def _check_confidence(extracted_attachments):
    """
    Check each attachment against confidence thresholds.
    Returns a list of items that fail the threshold check.
    """
    low_confidence = []

    for att in extracted_attachments:
        reasons = []
        classification_conf = att.get("classification_confidence", 0.0)
        extraction_conf = att.get("extraction_confidence", 0.0)

        if classification_conf < CLASSIFICATION_CONFIDENCE_THRESHOLD:
            reasons.append(
                f"classification_confidence {classification_conf:.2f} "
                f"< threshold {CLASSIFICATION_CONFIDENCE_THRESHOLD}"
            )
        if extraction_conf < EXTRACTION_CONFIDENCE_THRESHOLD:
            reasons.append(
                f"extraction_confidence {extraction_conf:.2f} "
                f"< threshold {EXTRACTION_CONFIDENCE_THRESHOLD}"
            )

        if reasons:
            low_confidence.append({
                "attachment_id": att["attachment_id"],
                "classification": att.get("classification"),
                "reasons": reasons,
            })

    return low_confidence


def _build_inbound_result(case_id, message_id, extracted_attachments):
    """
    Build the payload that the state machine expects at ValidateAndUpdate.
    Must match the contract defined in the mock-analyse-attachment mock
    and consumed by src/stream5/validate-and-update/handler.py.
    """
    attachments = []
    for att in extracted_attachments:
        attachments.append({
            "attachment_id": att["attachment_id"],
            "s3_ref": att["s3_ref"],
            "classification": att["classification"],
            "classification_confidence": att["classification_confidence"],
            "extracted_fields": att.get("extracted_fields", {}),
            "extraction_confidence": att["extraction_confidence"],
            "validation_result": None,  # set by validate-and-update
        })

    return {
        "case_id": case_id,
        "message_id": message_id,
        "correlation_status": "MATCHED",
        "attachments": attachments,
    }


def _resume_state_machine(task_token, inbound_result):
    """Call sfn:SendTaskSuccess to resume the paused state machine execution."""
    sfn.send_task_success(
        taskToken=task_token,
        output=json.dumps(inbound_result),
    )


def _get_task_token(case_id):
    """Fetch the Step Functions task token from the Cases table."""
    response = cases_table.get_item(Key={"case_id": case_id})
    item = response.get("Item", {})
    return item.get("sfn_task_token")


def _clear_task_token(case_id):
    """Remove consumed task token from the case record."""
    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression="REMOVE sfn_task_token SET updated_at = :ts",
        ExpressionAttributeValues={
            ":ts": datetime.now(timezone.utc).isoformat(),
        },
    )


def _send_to_analyst_review(case_id, message_id, extracted_attachments,
                            low_confidence_items):
    """Route low-confidence results to the analyst review queue."""
    if not ANALYST_REVIEW_QUEUE_URL:
        print(f"[RESUME] No ANALYST_REVIEW_QUEUE_URL configured — skipping queue send")
        return

    sqs.send_message(
        QueueUrl=ANALYST_REVIEW_QUEUE_URL,
        MessageBody=json.dumps({
            "case_id": case_id,
            "message_id": message_id,
            "reason": "Low confidence on one or more attachments",
            "low_confidence_items": low_confidence_items,
            "extracted_attachments": extracted_attachments,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }),
    )
