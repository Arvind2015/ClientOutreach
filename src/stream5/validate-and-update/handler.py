"""
Stream 5 — Validation & Update Agent (Tasks 6.1–6.3)

Validates extracted fields from inbound attachments against the checklist
requirement, then writes the validated data back to the KYC system of record.

Validation rules (deterministic, no LLM):
  - Expiry date is in the future
  - Client name matches on-file record (fuzzy, threshold configurable)
  - All required fields for the requirement_type are present and non-empty

Inputs (from Step Functions ValidateAndUpdate state):
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

# Required fields per requirement_type — extend as new document types are added
REQUIRED_FIELDS_MAP = {
    "PASSPORT": ["full_name", "document_number", "expiry_date", "nationality"],
    "PROOF_OF_ADDRESS": ["full_name", "address", "document_date"],
    "CERTIFICATE_OF_INCORPORATION": ["company_name", "registration_number", "incorporation_date"],
    "BENEFICIAL_OWNERSHIP_DECLARATION": ["company_name", "beneficial_owners"],
    "PROOF_OF_IDENTITY": ["full_name", "document_number", "expiry_date"],
}

# Name similarity threshold (simple ratio, 0.0–1.0)
NAME_MATCH_THRESHOLD = float(os.environ.get("NAME_MATCH_THRESHOLD", "0.8"))


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
            "failure_reasons": outcome.get("reasons", []),
        })

        if outcome["status"] == "PASS":
            _write_to_kyc_system(case_id, requirement_type, extracted_fields,
                                 attachment.get("s3_ref"))

    # Overall status: PASS only if every attachment passed
    any_review = any(r["status"] == "NEEDS_ANALYST_REVIEW" for r in results)
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
        overall = "PARTIAL"
        _update_case_status(case_id, "NEEDS_ANALYST_REVIEW",
                            reason="Validation failed for one or more attachments")
        emit_audit_event(case_id, actor="validate-and-update",
                         action="VALIDATION_PARTIAL_FAILURE")

    return {
        "case_id": case_id,
        "overall_status": overall,
        "validation_results": results,
    }


def _validate(extracted_fields, requirement_type, client_id):
    """
    Deterministic validation logic per requirement type.
    Returns {"status": "PASS"|"NEEDS_ANALYST_REVIEW", "reasons": [str]}

    Three checks applied in order:
      1. Required fields present and non-empty
      2. Expiry date (if applicable) is in the future
      3. Name field matches on-file client name (fuzzy match)
    """
    reasons = []

    # 1. Required fields check
    required_fields = REQUIRED_FIELDS_MAP.get(requirement_type, [])
    missing_fields = []
    for field_name in required_fields:
        value = extracted_fields.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing_fields.append(field_name)

    if missing_fields:
        reasons.append(f"Missing required fields: {', '.join(missing_fields)}")

    # 2. Expiry date check — must be in the future
    expiry_date_str = extracted_fields.get("expiry_date")
    if expiry_date_str:
        try:
            expiry_dt = datetime.fromisoformat(
                expiry_date_str.replace("Z", "+00:00")
            )
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            if expiry_dt <= datetime.now(timezone.utc):
                reasons.append(f"Document expired: {expiry_date_str}")
        except (ValueError, TypeError):
            reasons.append(f"Unparseable expiry date: {expiry_date_str}")

    # 3. Name match check — compare extracted name against on-file client name
    extracted_name = (
        extracted_fields.get("full_name")
        or extracted_fields.get("company_name")
        or ""
    )
    if extracted_name:
        on_file_name = _get_client_name_on_file(client_id)
        if on_file_name and not _names_match(extracted_name, on_file_name):
            reasons.append(
                f"Name mismatch: extracted '{extracted_name}' vs on-file '{on_file_name}'"
            )

    if reasons:
        return {"status": "NEEDS_ANALYST_REVIEW", "reasons": reasons}

    return {"status": "PASS", "reasons": []}


def _get_client_name_on_file(client_id):
    """
    Retrieve the client's on-file name from the Cases table (or KYC profile cache).
    Returns None if unavailable — validation proceeds without name check in that case.
    """
    # In production, this would query the KycProfileCache table. For now, we
    # read from the Cases table where the client_id maps to a known profile.
    # TODO: once KYC system of record is confirmed, read from the authoritative source.
    try:
        response = cases_table.get_item(Key={"case_id": client_id})
        item = response.get("Item")
        if item:
            return item.get("client_name")
    except Exception:
        pass
    return None


def _names_match(extracted, on_file):
    """
    Simple case-insensitive similarity check. Uses character overlap ratio.
    A proper implementation would use Levenshtein distance or a dedicated
    fuzzy-matching library, but this covers the common cases for the pilot.
    """
    a = extracted.strip().lower()
    b = on_file.strip().lower()

    if a == b:
        return True

    # Character-level similarity ratio (Sorensen-Dice coefficient on bigrams)
    bigrams_a = set(_bigrams(a))
    bigrams_b = set(_bigrams(b))

    if not bigrams_a or not bigrams_b:
        return a == b

    overlap = len(bigrams_a & bigrams_b)
    similarity = (2.0 * overlap) / (len(bigrams_a) + len(bigrams_b))

    return similarity >= NAME_MATCH_THRESHOLD


def _bigrams(s):
    return [s[i:i+2] for i in range(len(s) - 1)]


def _write_to_kyc_system(case_id, requirement_type, fields, s3_ref):
    """
    Adapter call to write validated fields to the KYC system of record.
    Retains original document S3 reference alongside structured data.

    Stubbed pending real system-of-record confirmation (design.md Open Item #1).
    Logs the write and returns success — same pattern as Stream 2's KYC source stub.
    """
    print(
        f"[KYC WRITE STUB] case={case_id} requirement_type={requirement_type} "
        f"s3_ref={s3_ref} fields_count={len(fields)}"
    )
    emit_audit_event(
        case_id, actor="validate-and-update",
        action=f"KYC_RECORD_UPDATED_STUB:{requirement_type}",
        input_ref=s3_ref,
    )
    # In production: call KYC system of record API, handle retry on failure (Task 6.3)
    return True


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
