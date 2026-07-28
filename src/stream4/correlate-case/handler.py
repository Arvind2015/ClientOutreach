"""
Stream 4 — Correlate Case (Task 5.2)

Matches an inbound email to the originating outreach case using the embedded
case reference token (X-Case-Ref header, subject line pattern, or body token).

If correlation succeeds:
  - Updates the InboundMessage record with the matched case_id.
  - Returns the case_id and task token for downstream processing.

If correlation fails:
  - Routes the message to the ManualTriageQueue (SQS) for analyst review.
  - Updates the InboundMessage record with status UNMATCHED.

Inputs (from receive-inbound-email output):
  - message_id: str
  - sender: str
  - subject: str
  - headers: dict       # contains x_case_ref, in_reply_to, references
  - attachments: list

Outputs:
  - message_id: str
  - case_id: str | None
  - client_id: str | None
  - correlation_status: "MATCHED" | "UNMATCHED"
  - sfn_task_token: str | None   # needed by resume-workflow to resume state machine
  - attachments: list            # passed through for downstream steps
"""

import os
import re
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

dynamodb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")

cases_table = dynamodb.Table(os.environ["CASES_TABLE"])
INBOUND_TABLE = os.environ.get("INBOUND_TABLE", "InboundMessages")
inbound_table = dynamodb.Table(INBOUND_TABLE)
MANUAL_TRIAGE_QUEUE_URL = os.environ["MANUAL_TRIAGE_QUEUE_URL"]

# Pattern for case reference token embedded in outreach emails
# Format: CASEREF-<case_id>  (set by Stream 3 outreach generation)
CASE_REF_PATTERN = re.compile(r"CASEREF-([A-Za-z0-9\-_]+)")


def handler(event, context):
    message_id = event["message_id"]
    sender = event.get("sender", "")
    subject = event.get("subject", "")
    headers = event.get("headers", {})
    attachments = event.get("attachments", [])

    # Attempt correlation in priority order
    case_id = _extract_case_id(headers, subject)

    if case_id:
        case = _lookup_case(case_id)
        if case:
            # Successful match
            _update_inbound_record(message_id, case_id, "MATCHED")
            emit_audit_event(
                case_id=case_id,
                actor="correlate-case",
                action="INBOUND_CORRELATED",
                input_ref=message_id,
            )
            return {
                "message_id": message_id,
                "case_id": case_id,
                "client_id": case.get("client_id"),
                "correlation_status": "MATCHED",
                "sfn_task_token": case.get("sfn_task_token"),
                "attachments": attachments,
            }

    # Correlation failed — route to manual triage
    _update_inbound_record(message_id, None, "UNMATCHED")
    _send_to_triage_queue(message_id, sender, subject)
    emit_audit_event(
        case_id="UNMATCHED",
        actor="correlate-case",
        action="INBOUND_UNMATCHED_SENT_TO_TRIAGE",
        input_ref=message_id,
    )

    return {
        "message_id": message_id,
        "case_id": None,
        "client_id": None,
        "correlation_status": "UNMATCHED",
        "sfn_task_token": None,
        "attachments": attachments,
    }


def _extract_case_id(headers, subject):
    """
    Try to extract case_id from multiple sources in priority order:
      1. X-Case-Ref header (most reliable — set by outbound email)
      2. Subject line (contains CASEREF-xxx)
      3. In-Reply-To / References headers (match against known email_ids)
    """
    # 1. Explicit X-Case-Ref header
    x_case_ref = headers.get("x_case_ref", "")
    match = CASE_REF_PATTERN.search(x_case_ref)
    if match:
        return match.group(1)

    # 2. Subject line
    match = CASE_REF_PATTERN.search(subject)
    if match:
        return match.group(1)

    # 3. In-Reply-To / References (would require lookup table of sent email Message-IDs)
    # TODO: implement Message-ID → case_id reverse lookup for edge cases
    return None


def _lookup_case(case_id):
    """Fetch case record to verify it exists and get the task token."""
    response = cases_table.get_item(Key={"case_id": case_id})
    item = response.get("Item")
    if item and item.get("status") == "AWAITING_RESPONSE":
        return item
    # Case exists but not in AWAITING_RESPONSE state — still return it
    # but downstream must handle gracefully
    return item


def _update_inbound_record(message_id, case_id, status):
    """Update the InboundMessages table with correlation result."""
    update_expr = "SET correlation_status = :s, updated_at = :ts"
    expr_values = {
        ":s": status,
        ":ts": datetime.now(timezone.utc).isoformat(),
    }
    if case_id:
        update_expr += ", case_id = :cid"
        expr_values[":cid"] = case_id

    inbound_table.update_item(
        Key={"message_id": message_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )


def _send_to_triage_queue(message_id, sender, subject):
    """Route unmatched message to analyst manual triage queue."""
    import json
    sqs.send_message(
        QueueUrl=MANUAL_TRIAGE_QUEUE_URL,
        MessageBody=json.dumps({
            "message_id": message_id,
            "sender": sender,
            "subject": subject,
            "reason": "Unable to correlate inbound email to any active case",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }),
    )
