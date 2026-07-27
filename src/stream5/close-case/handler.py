"""
Stream 5 — Close Case (Tasks 6.7, 3.4)

Marks a case as CLOSED — all KYC requirements have been satisfied.
Called from two paths in the state machine:
  1. CheckForGaps → CloseCase: no gaps found on the initial pass (case was
     already compliant when first checked — no outreach needed at all).
  2. CheckFollowUpDecision → CloseCase: all gaps resolved after one or more
     outreach/response cycles.

Inputs (from Step Functions):
  - case_id: str

Outputs:
  - case_id: str
  - status: "CLOSED"
  - closed_at: str (ISO 8601)
"""

import os
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

dynamodb = boto3.resource("dynamodb")
cases_table = dynamodb.Table(os.environ["CASES_TABLE"])


def handler(event, context):
    case_id = event["case_id"]
    closed_at = datetime.now(timezone.utc).isoformat()

    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression="SET #s = :s, closed_at = :ca, updated_at = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "CLOSED",
            ":ca": closed_at,
            ":ts": closed_at,
        },
    )

    emit_audit_event(case_id, actor="close-case", action="CASE_CLOSED")

    return {
        "case_id": case_id,
        "status": "CLOSED",
        "closed_at": closed_at,
    }
