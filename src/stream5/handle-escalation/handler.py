"""
Stream 5 — Escalation Handler (Task 7.4)

Uniform escalation handler used by all failure and exception paths across
the state machine. Sets case status to ESCALATED, writes the escalation reason,
and fires an SNS notification to the analyst mailbox.

All escalation paths converge here — KYC retrieval failure, max follow-up
cycles, SLA breach, low-confidence items, unrecoverable update failures.

Inputs (from Step Functions Catch or direct invocation):
  - case_id: str
  - escalation_reason: str   # human-readable reason for escalation
  - source: str              # which component triggered escalation

Outputs:
  - case_id: str
  - status: "ESCALATED"
  - notified: bool
"""

import os
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")

cases_table = dynamodb.Table(os.environ["CASES_TABLE"])
SNS_TOPIC_ARN = os.environ["ANALYST_SNS_TOPIC_ARN"]


def handler(event, context):
    case_id = event["case_id"]
    escalation_reason = event.get("escalation_reason", "Unspecified")
    source = event.get("source", "unknown")

    # 1. Update case status to ESCALATED with reason
    _escalate_case(case_id, escalation_reason)

    # 2. Emit audit event (Req 10.1)
    emit_audit_event(case_id, actor=source,
                     action=f"CASE_ESCALATED: {escalation_reason}")

    # 3. Fire SNS notification to analyst mailbox
    notified = _notify_analyst(case_id, escalation_reason, source)

    return {
        "case_id": case_id,
        "status": "ESCALATED",
        "escalation_reason": escalation_reason,
        "notified": notified,
    }


def _escalate_case(case_id, reason):
    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression="SET #s = :s, escalation_reason = :r, updated_at = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "ESCALATED",
            ":r": reason,
            ":ts": datetime.now(timezone.utc).isoformat(),
        },
    )


def _notify_analyst(case_id, reason, source):
    try:
        message = (
            f"Case {case_id} has been escalated.\n"
            f"Reason: {reason}\n"
            f"Source: {source}\n"
            f"Time: {datetime.now(timezone.utc).isoformat()}\n"
            f"Action required: review case in the analyst insights view."
        )
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"[KYC Outreach] Case {case_id} escalated",
            Message=message,
        )
        return True
    except Exception as e:
        # Log but do not fail the escalation itself if SNS publish fails
        print(f"SNS notification failed for case {case_id}: {e}")
        return False
