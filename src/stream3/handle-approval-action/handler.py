"""
Stream 3 -- Handle Approval Action (Task 4.7)

Processes analyst approve/edit/reject decisions from the SQS approval queue.
This Lambda is triggered by the SQS queue consumer (or directly by the
analyst insights view).

On APPROVE: calls sfn:SendTaskSuccess with the approval result so the
state machine can proceed to SendOutreachEmail.

On REJECT: calls sfn:SendTaskSuccess with rejection, state machine routes
to CloseCase.

On EDIT: updates the rendered email body in S3 with the analyst's edits,
then approves (same as APPROVE path with updated content).

Inputs (from SQS message or analyst action):
  - case_id: str
  - decision: APPROVED | REJECTED | EDITED
  - analyst_id: str
  - edited_body: str (optional, only for EDITED)
  - task_token: str (Step Functions task token from WaitForApproval state)

Outputs:
  - case_id: str
  - decision: str
  - resumed: bool
"""

import os
import json
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

sfn = boto3.client("stepfunctions")
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

cases_table = dynamodb.Table(os.environ["CASES_TABLE"])
DOCUMENTS_BUCKET = os.environ["DOCUMENTS_BUCKET"]


def handler(event, context):
    # Handle SQS batch (records) or direct invocation
    records = event.get("Records", [event])

    results = []
    for record in records:
        if "body" in record:
            # SQS message
            body = json.loads(record["body"])
        else:
            body = record

        result = _process_decision(body)
        results.append(result)

    return {"results": results}


def _process_decision(body):
    case_id = body["case_id"]
    decision = body["decision"]
    analyst_id = body.get("analyst_id", "unknown")
    task_token = body["task_token"]
    edited_body = body.get("edited_body")

    if decision == "EDITED" and edited_body:
        # Store edited content and update the rendered_body_ref on the case
        edited_s3_key = _store_edited_body(case_id, edited_body)
        _update_rendered_body_ref(case_id, edited_s3_key)
        decision = "APPROVED"

    # Update case with approval info
    _update_case_approval(case_id, decision, analyst_id)

    # Resume the Step Functions state machine
    resumed = _resume_state_machine(task_token, decision)

    emit_audit_event(
        case_id, actor=f"analyst:{analyst_id}",
        action=f"OUTREACH_{decision}",
    )

    return {
        "case_id": case_id,
        "decision": decision,
        "analyst_id": analyst_id,
        "resumed": resumed,
    }


def _store_edited_body(case_id, edited_body):
    """Store analyst-edited email body to S3. Returns the new S3 key."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    s3_key = f"outreach-emails/{case_id}/outreach-edited-{timestamp}.html"
    s3.put_object(
        Bucket=DOCUMENTS_BUCKET,
        Key=s3_key,
        Body=edited_body.encode("utf-8"),
        ContentType="text/html",
    )
    return s3_key


def _update_rendered_body_ref(case_id, s3_key):
    """Update the case record with the new rendered_body_ref after analyst edit."""
    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression="SET rendered_body_ref = :ref, updated_at = :ts",
        ExpressionAttributeValues={
            ":ref": f"s3://{DOCUMENTS_BUCKET}/{s3_key}",
            ":ts": datetime.now(timezone.utc).isoformat(),
        },
    )


def _update_case_approval(case_id, decision, analyst_id):
    """Update case record with approval decision."""
    now = datetime.now(timezone.utc).isoformat()

    if decision == "APPROVED":
        status = "PENDING_APPROVAL"  # Will transition to AWAITING_RESPONSE after send
        update_expr = (
            "SET #s = :s, approved_by = :ab, approved_at = :ts, updated_at = :ts"
        )
        expr_values = {":s": status, ":ab": analyst_id, ":ts": now}
    else:
        status = "REJECTED"
        update_expr = (
            "SET #s = :s, rejected_by = :rb, rejected_at = :ts, updated_at = :ts"
        )
        expr_values = {":s": status, ":rb": analyst_id, ":ts": now}

    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=expr_values,
    )


def _resume_state_machine(task_token, decision):
    """Resume the Step Functions WaitForApproval state."""
    try:
        sfn.send_task_success(
            taskToken=task_token,
            output=json.dumps({"decision": decision}),
        )
        return True
    except Exception as e:
        print(f"[APPROVAL] Failed to resume state machine: {e}")
        return False
