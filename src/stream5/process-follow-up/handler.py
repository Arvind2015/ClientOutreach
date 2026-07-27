"""
Stream 5 — Follow-Up Loop (Tasks 6.4–6.7)

After a validation pass, re-runs the Matching Engine (Stream 2) to compute
remaining gaps. Returns the updated GapAnalysisResult in the same shape that
RunGapAnalysis produces, plus next_action and follow_up_count — so the state
machine's DraftOutreach state can consume $.gap_analysis unchanged on every
loop iteration.

Enforces max follow-up cycle limit and forces escalation on breach.

Inputs (from Step Functions):
  - case_id: str
  - client_id: str

Outputs (written to $.gap_analysis by ResultPath in the state machine):
  - gap_analysis: dict   # full GapAnalysisResult shape {case_id, client_id, has_gaps, outstanding, computed_at}
  - next_action: CLOSE | FOLLOW_UP | ESCALATE
  - follow_up_count: int
"""

import os
import json
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")

cases_table = dynamodb.Table(os.environ["CASES_TABLE"])
GAP_ANALYSIS_FUNCTION_ARN = os.environ["RUN_GAP_ANALYSIS_FUNCTION_ARN"]
GET_KYC_PROFILE_FUNCTION_ARN = os.environ["GET_KYC_PROFILE_FUNCTION_ARN"]

# Configurable — matches design.md default of 3 cycles
MAX_FOLLOW_UP_CYCLES = int(os.environ.get("MAX_FOLLOW_UP_CYCLES", "3"))


def handler(event, context):
    case_id = event["case_id"]
    client_id = event["client_id"]

    case = _get_case(case_id)
    follow_up_count = case.get("follow_up_count", 0)

    # Re-run Stream 2's Retrieval Agent then Matching Engine to get current gap state
    # Note: get-kyc-profile has a 24h cache, so a document that validate-and-update
    # just wrote back (via the still-stubbed _write_to_kyc_system) won't appear in
    # the cached profile until TTL expires. Acceptable known gap while the KYC system
    # of record adapter remains a stub — once real writes land, the cache invalidation
    # strategy will need revisiting.
    kyc_profile = _invoke_get_kyc_profile(case_id, client_id)
    gap_analysis = _invoke_gap_analysis(case_id, client_id, kyc_profile)
    has_gaps = gap_analysis.get("has_gaps", False)

    if not has_gaps:
        _update_case(case_id, status="COMPLIANT", follow_up_count=follow_up_count)
        emit_audit_event(case_id, actor="process-follow-up", action="CASE_COMPLIANT")
        return {
            "gap_analysis": gap_analysis,
            "next_action": "CLOSE",
            "follow_up_count": follow_up_count,
        }

    if follow_up_count >= MAX_FOLLOW_UP_CYCLES:
        _update_case(case_id, status="ESCALATED", follow_up_count=follow_up_count,
                     reason=f"Max follow-up cycles ({MAX_FOLLOW_UP_CYCLES}) reached")
        emit_audit_event(case_id, actor="process-follow-up",
                         action="MAX_FOLLOW_UP_CYCLES_REACHED")
        return {
            "gap_analysis": gap_analysis,
            "next_action": "ESCALATE",
            "follow_up_count": follow_up_count,
        }

    new_count = follow_up_count + 1
    _update_case(case_id, status="FOLLOW_UP_NEEDED", follow_up_count=new_count)
    emit_audit_event(case_id, actor="process-follow-up",
                     action=f"FOLLOW_UP_TRIGGERED_CYCLE_{new_count}")

    return {
        "gap_analysis": gap_analysis,
        "next_action": "FOLLOW_UP",
        "follow_up_count": new_count,
    }


def _get_case(case_id):
    response = cases_table.get_item(Key={"case_id": case_id})
    return response.get("Item", {})


def _invoke_get_kyc_profile(case_id, client_id):
    """
    Invoke Stream 2's get-kyc-profile Lambda to retrieve the full normalised
    KycProfile (client_type, jurisdiction, risk_rating, fields, documents).
    """
    payload = {"case_id": case_id, "client_id": client_id}

    response = lambda_client.invoke(
        FunctionName=GET_KYC_PROFILE_FUNCTION_ARN,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )

    response_payload = json.loads(response["Payload"].read())

    if "FunctionError" in response:
        error_msg = response_payload.get("errorMessage", "Unknown error")
        raise RuntimeError(
            f"get-kyc-profile invocation failed for case {case_id}: {error_msg}"
        )

    return response_payload


def _invoke_gap_analysis(case_id, client_id, kyc_profile):
    """
    Invoke Stream 2's run-gap-analysis Lambda to get a fresh GapAnalysisResult.
    Passes the real KycProfile so rule resolution and document/field diffing work correctly.
    Returns the full result dict: {case_id, client_id, has_gaps, outstanding, computed_at}
    """
    payload = {
        "case_id": case_id,
        "client_id": client_id,
        "kyc_profile": kyc_profile,
    }

    response = lambda_client.invoke(
        FunctionName=GAP_ANALYSIS_FUNCTION_ARN,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )

    response_payload = json.loads(response["Payload"].read())

    # Handle Lambda invocation errors
    if "FunctionError" in response:
        error_msg = response_payload.get("errorMessage", "Unknown error")
        raise RuntimeError(
            f"run-gap-analysis invocation failed for case {case_id}: {error_msg}"
        )

    return response_payload


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
