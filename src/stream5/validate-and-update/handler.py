"""
Stream 5 — Validation & Update Agent (Tasks 6.1–6.3)

Validates extracted fields from inbound attachments against the checklist
requirement, then writes the validated data back to the KYC system of record.

Inputs (from Step Functions AwaitClientResponse result, passed as inbound_result):
  - case_id: str
  - client_id: str
  - inbound_result: dict with shape:
      {
        "attachments": [
          {
            "attachment_id": str,
            "classification": str,        # requirement_type this satisfies
            "extracted_fields": dict,
            "classification_confidence": float,
            "extraction_confidence": float,
            "s3_ref": str
          }
        ]
      }

Outputs:
  - case_id: str
  - validation_results: list of per-attachment outcomes
  - overall_status: PASS | PARTIAL | NEEDS_ANALYST_REVIEW
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
    client_id = event["client_id"]
    inbound_result = event["inbound_result"]

    attachments = inbound_result.get("attachments", [])
    results = []

    for attachment in attachments:
        requirement_type = attachment["classification"]
        extracted_fields = attachment.get("extracted_fields", {})

        outcome = _validate(extracted_fields, requirement_type, client_id)
        results.append({
            "attachment_id": attachment["attachment_id"],
            "requirement_type": requirement_type,
            "status": outcome["status"],
            "failure_reason": outcome.get("reason"),
        })

        if outcome["status"] == "PASS":
            # TODO: write validated data to KYC system of record adapter
            _write_to_kyc_system(case_id, requirement_type, extracted_fields,
                                 attachment.get("s3_ref"))

    # Overall status: PASS only if every attachment passed
    any_review = any(r["status"] == "NEEDS_ANALYST_REVIEW" for r in results)
    any_fail = any(r["status"] == "FAIL" for r in results)
    all_pass = all(r["status"] == "PASS" for r in results)

    if all_pass:
        overall = "PASS"
        _update_case_status(case_id, "RESPONSE_RECEIVED")
        emit_audit_event(case_id, actor="validate-and-update",
                         action="VALIDATION_PASSED")
    elif any_review:
        overall = "NEEDS_ANALYST_REVIEW"
        _update_case_status(case_id, "NEEDS_ANALYST_REVIEW",
                            reason="One or more attachments require analyst review")
        emit_audit_event(case_id, actor="validate-and-update",
                         action="VALIDATION_NEEDS_ANALYST_REVIEW")
    else:
        overall = "FAIL"
        _update_case_status(case_id, "NEEDS_ANALYST_REVIEW",
                            reason="Validation failed for one or more attachments")
        emit_audit_event(case_id, actor="validate-and-update",
                         action="VALIDATION_FAILED")

    return {
        "case_id": case_id,
        "overall_status": overall,
        "validation_results": results,
    }


def _validate(extracted_fields, requirement_type, client_id):
    """
    Deterministic validation logic per requirement type.
    Returns {"status": "PASS"|"FAIL"|"NEEDS_ANALYST_REVIEW", "reason": str}
    """
    # TODO: implement per-requirement-type validation rules:
    #   - Check expiry date is in the future
    #   - Check name matches client record
    #   - Check all required fields are present and non-empty
    raise NotImplementedError("Validation logic not yet implemented")


def _write_to_kyc_system(case_id, requirement_type, fields, s3_ref):
    """
    Adapter call to write validated fields to the KYC system of record.
    Retains original document S3 reference alongside structured data.
    """
    # TODO: implement KYC system of record adapter (coordinate with Stream 2)
    raise NotImplementedError("KYC system adapter not yet implemented")


def _update_case_status(case_id, status, reason=None):
    update_expr = "SET #s = :s, updated_at = :ts"
    expr_names = {"#s": "status"}
    expr_values = {
        ":s": status,
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
