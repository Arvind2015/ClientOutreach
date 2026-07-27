"""
Stream 5 — Follow-Up Loop (Tasks 6.4–6.7)

After a validation pass, re-runs the Matching Engine to compute remaining gaps.
If gaps remain, generates a follow-up outreach email via the Outreach Drafting
Agent. Enforces max follow-up cycle limit and forces escalation on breach.

Inputs (from Step Functions):
  - case_id: str
  - client_id: str

Outputs:
  - next_action: CLOSE | FOLLOW_UP | ESCALATE
  - follow_up_count: int
  - remaining_gaps: list[str]   # requirement_type codes still outstanding
"""

import os
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

dynamodb = boto3.resource("dynamodb")
cases_table = dynamodb.Table(os.environ["CASES_TABLE"])

# Configurable — matches design.md default of 3 cycles
MAX_FOLLOW_UP_CYCLES = int(os.environ.get("MAX_FOLLOW_UP_CYCLES", "3"))


def handler(event, context):
    case_id = event["case_id"]
    client_id = event["client_id"]

    case = _get_case(case_id)
    follow_up_count = case.get("follow_up_count", 0)

    # TODO: invoke Matching Engine (Stream 2) to get updated gap analysis
    remaining_gaps = _run_gap_analysis(client_id)

    if not remaining_gaps:
        _update_case(case_id, status="COMPLIANT", follow_up_count=follow_up_count)
        emit_audit_event(case_id, actor="process-follow-up", action="CASE_COMPLIANT")
        return {"case_id": case_id, "next_action": "CLOSE", "remaining_gaps": []}

    if follow_up_count >= MAX_FOLLOW_UP_CYCLES:
        _update_case(case_id, status="ESCALATED", follow_up_count=follow_up_count,
                     reason=f"Max follow-up cycles ({MAX_FOLLOW_UP_CYCLES}) reached")
        emit_audit_event(case_id, actor="process-follow-up",
                         action="MAX_FOLLOW_UP_CYCLES_REACHED")
        return {"case_id": case_id, "next_action": "ESCALATE",
                "remaining_gaps": remaining_gaps}

    new_count = follow_up_count + 1
    _update_case(case_id, status="FOLLOW_UP_NEEDED", follow_up_count=new_count)
    emit_audit_event(case_id, actor="process-follow-up",
                     action=f"FOLLOW_UP_TRIGGERED_CYCLE_{new_count}")

    # TODO: invoke Outreach Drafting Agent (Stream 3) via AgentCore Gateway
    # Pass tightening escalation context based on cycle number
    _trigger_follow_up_outreach(case_id, client_id, remaining_gaps, new_count)

    return {
        "case_id": case_id,
        "next_action": "FOLLOW_UP",
        "follow_up_count": new_count,
        "remaining_gaps": remaining_gaps,
    }


def _get_case(case_id):
    response = cases_table.get_item(Key={"case_id": case_id})
    return response.get("Item", {})


def _run_gap_analysis(client_id):
    """
    Invokes the Matching Engine Lambda (Stream 2) and returns list of
    outstanding requirement_type codes.
    """
    # TODO: invoke stream2/run-gap-analysis Lambda
    raise NotImplementedError("Gap analysis invocation not yet implemented")


def _trigger_follow_up_outreach(case_id, client_id, remaining_gaps, cycle):
    """
    Invokes the Outreach Drafting Agent (Stream 3) via AgentCore Gateway.
    Passes cycle number so tone can tighten on later follow-ups.
    """
    # TODO: invoke stream3/draft-outreach-email via AgentCore Gateway
    raise NotImplementedError("Follow-up outreach trigger not yet implemented")


def _update_case(case_id, status, follow_up_count, reason=None):
    update_expr = "SET #s = :s, follow_up_count = :fc, updated_at = :ts"
    expr_names = {"#s": "status"}
    expr_values = {
        ":s": status,
        ":fc": follow_up_count,
        ":ts": datetime.now(timezone.utc).isoformat(),
    }
    if reason:
        update_expr += ", escalation_reason = :r"
        expr_values[":r"] = reason

    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
