"""
Stream 3 -- Outreach Drafting Agent (Tasks 4.1-4.5, 4.8)

Generates a customer-facing outreach email listing exactly what KYC items
are missing or expired, using an approved template from the template library.

Key responsibilities:
  - Select and render an approved template with case-specific variables
  - Generate and embed a unique case reference (subject + X-Case-Ref header)
  - Classify dispatch mode: AUTO_SEND vs NEEDS_APPROVAL (deterministic rule)
  - Enforce minimum re-contact interval per client (Req 12.2)

Inputs (from Step Functions DraftOutreach state):
  - case_id: str
  - client_id: str
  - gap_analysis: dict (GapAnalysisResult shape from Stream 2)

Outputs:
  - case_id: str
  - client_id: str
  - email_id: str
  - template_id: str
  - rendered_body_ref: str (S3 key of rendered HTML)
  - dispatch_mode: AUTO_SEND | NEEDS_APPROVAL
  - case_ref: str
  - subject: str
"""

import os
import json
import uuid
import hashlib
import boto3
from datetime import datetime, timezone, timedelta

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")

cases_table = dynamodb.Table(os.environ["CASES_TABLE"])
DOCUMENTS_BUCKET = os.environ["DOCUMENTS_BUCKET"]
TEMPLATES_BUCKET = os.environ.get("TEMPLATES_BUCKET", os.environ.get("DEPLOY_BUCKET", "kyc-outreach-deployments"))
TEMPLATES_PREFIX = os.environ.get("TEMPLATES_PREFIX", "stream3/templates/")

# Minimum re-contact interval (default 5 business days = 7 calendar days as approximation)
MIN_RECONTACT_INTERVAL_DAYS = int(os.environ.get("MIN_RECONTACT_INTERVAL_DAYS", "7"))

# Standard-case auto-send criteria (deterministic, not LLM)
AUTO_SEND_MAX_RISK = os.environ.get("AUTO_SEND_MAX_RISK", "MEDIUM")  # LOW, MEDIUM allowed
AUTO_SEND_MAX_FOLLOW_UP_COUNT = int(os.environ.get("AUTO_SEND_MAX_FOLLOW_UP_COUNT", "2"))

RISK_LEVELS = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def handler(event, context):
    case_id = event["case_id"]
    client_id = event["client_id"]
    gap_analysis_wrapper = event.get("gap_analysis", {})

    # Unwrap -- state machine passes {"gap_analysis": {...}, ...}
    gap_analysis = gap_analysis_wrapper.get("gap_analysis", gap_analysis_wrapper)

    case = _get_case(case_id)
    outstanding = gap_analysis.get("outstanding", [])

    # Enforce minimum re-contact interval (Req 12.2)
    # If within interval, force NEEDS_APPROVAL so an analyst decides whether to override
    last_contacted = case.get("last_contacted_at")
    recontact_blocked = False
    if last_contacted and _within_recontact_interval(last_contacted):
        recontact_blocked = True
        emit_audit_event(case_id, actor="draft-outreach-email",
                         action="RECONTACT_INTERVAL_NOT_MET")

    # Generate unique case reference
    case_ref = _generate_case_ref(case_id)

    # Select and render template
    follow_up_count = case.get("follow_up_count", 0)
    template_id = _select_template(follow_up_count)
    rendered_body, template_compliance_status = _render_template(
        template_id, client_id, case_ref, outstanding, case
    )
    rendered_body_ref = _store_rendered_email(case_id, rendered_body)

    # Determine dispatch mode (deterministic rule -- Req 5.1, 5.2)
    # If template is not signed off, force NEEDS_APPROVAL (task 10.2 hard gate)
    template_unsigned = (template_compliance_status != "SIGNED_OFF")
    risk_rating = case.get("risk_rating", gap_analysis.get("risk_rating", "MEDIUM"))
    dispatch_mode = _classify_dispatch_mode(
        risk_rating, follow_up_count, case, recontact_blocked, template_unsigned
    )

    # Build subject line with embedded case reference
    subject = f"KYC Information Required - {case_ref}"

    # Generate email record
    email_id = f"email-{uuid.uuid4().hex[:12]}"

    # Update case with outreach metadata
    _update_case_outreach(case_id, email_id, dispatch_mode, case_ref)

    emit_audit_event(
        case_id, actor="draft-outreach-email",
        action=f"OUTREACH_DRAFTED:{dispatch_mode}",
        output_ref=rendered_body_ref,
    )

    return {
        "case_id": case_id,
        "client_id": client_id,
        "email_id": email_id,
        "template_id": template_id,
        "rendered_body_ref": rendered_body_ref,
        "dispatch_mode": dispatch_mode,
        "case_ref": case_ref,
        "subject": subject,
        "outstanding_count": len(outstanding),
    }


def _get_case(case_id):
    response = cases_table.get_item(Key={"case_id": case_id})
    return response.get("Item", {})


def _within_recontact_interval(last_contacted_at):
    """Check if the last contact was within the minimum re-contact interval."""
    try:
        last_dt = datetime.fromisoformat(last_contacted_at.replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=MIN_RECONTACT_INTERVAL_DAYS)
        return last_dt > cutoff
    except (ValueError, TypeError):
        return False


def _generate_case_ref(case_id):
    """Generate a unique, human-readable case reference token for email correlation."""
    short_hash = hashlib.sha256(case_id.encode()).hexdigest()[:8].upper()
    return f"CASEREF-{short_hash}"


def _select_template(follow_up_count):
    """Select the appropriate template based on follow-up cycle."""
    if follow_up_count == 0:
        return "standard-outreach"
    elif follow_up_count <= 2:
        return "follow-up-reminder"
    else:
        return "escalation-notice"


def _render_template(template_id, client_id, case_ref, outstanding, case):
    """
    Load template from S3 and populate variables.
    Templates use {{variable_name}} placeholder syntax.
    Returns (rendered_body, compliance_status).
    """
    template_content, compliance_status = _load_template(template_id)

    # Build requirement list as formatted text
    requirements_list = "\n".join(
        f"  - {item['requirement_type']} ({item.get('reason', 'MISSING')})"
        for item in outstanding
    )

    # Populate template variables
    variables = {
        "client_name": case.get("client_name", "Valued Customer"),
        "case_ref": case_ref,
        "requirements_list": requirements_list,
        "requirements_count": str(len(outstanding)),
        "deadline_days": "14",
        "bank_name": "KYC Compliance Team",
        "submission_instructions": "Please reply to this email with the requested documents attached.",
        "follow_up_count": str(case.get("follow_up_count", 0)),
    }

    rendered = template_content
    for key, value in variables.items():
        rendered = rendered.replace("{{" + key + "}}", value)

    return rendered, compliance_status


def _load_template(template_id):
    """Load template content from S3. Returns (body, compliance_status)."""
    key = f"{TEMPLATES_PREFIX}{template_id}.json"
    try:
        response = s3.get_object(Bucket=TEMPLATES_BUCKET, Key=key)
        template_data = json.loads(response["Body"].read().decode("utf-8"))
        return template_data.get("body", ""), template_data.get("compliance_status", "PENDING_SIGNOFF")
    except Exception as e:
        print(f"[DRAFT] Failed to load template {template_id}: {e}")
        # Fallback inline template -- always PENDING_SIGNOFF
        return (
            "Dear {{client_name}},\n\n"
            "We are writing regarding your KYC compliance requirements (Reference: {{case_ref}}).\n\n"
            "The following items are outstanding:\n{{requirements_list}}\n\n"
            "{{submission_instructions}}\n\n"
            "Please provide these within {{deadline_days}} days.\n\n"
            "Regards,\n{{bank_name}}"
        ), "PENDING_SIGNOFF"


def _store_rendered_email(case_id, rendered_body):
    """Store rendered email body to S3 and return the key."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    s3_key = f"outreach-emails/{case_id}/outreach-{timestamp}.html"
    s3.put_object(
        Bucket=DOCUMENTS_BUCKET,
        Key=s3_key,
        Body=rendered_body.encode("utf-8"),
        ContentType="text/html",
    )
    return f"s3://{DOCUMENTS_BUCKET}/{s3_key}"


def _classify_dispatch_mode(risk_rating, follow_up_count, case,
                            recontact_blocked=False, template_unsigned=False):
    """
    Deterministic standard-case classifier (Req 5.1, 5.2).
    AUTO_SEND if ALL of:
      - risk rating <= configured max (default MEDIUM)
      - follow-up count <= configured max (default 2)
      - no risk flags requiring review
      - not within re-contact interval
      - template compliance_status is SIGNED_OFF (task 10.2 hard gate)
    Otherwise NEEDS_APPROVAL.
    """
    if recontact_blocked:
        return "NEEDS_APPROVAL"

    if template_unsigned:
        return "NEEDS_APPROVAL"

    risk_level = RISK_LEVELS.get(risk_rating, 2)
    max_risk_level = RISK_LEVELS.get(AUTO_SEND_MAX_RISK, 1)

    if risk_level > max_risk_level:
        return "NEEDS_APPROVAL"

    if follow_up_count > AUTO_SEND_MAX_FOLLOW_UP_COUNT:
        return "NEEDS_APPROVAL"

    risk_flags = case.get("risk_flags", [])
    review_flags = {"NEEDS_RULE_REVIEW", "NEEDS_ANALYST_REVIEW", "HIGH_RISK_CLIENT"}
    if set(risk_flags) & review_flags:
        return "NEEDS_APPROVAL"

    return "AUTO_SEND"


def _update_case_outreach(case_id, email_id, dispatch_mode, case_ref):
    """Update case record with outreach metadata."""
    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression=(
            "SET #s = :s, last_email_id = :eid, case_ref = :cr, updated_at = :ts"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "OUTREACH_DRAFTED",
            ":eid": email_id,
            ":cr": case_ref,
            ":ts": datetime.now(timezone.utc).isoformat(),
        },
    )
