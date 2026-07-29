"""
Stream 3 -- Send Outreach Email (Task 4.6)

Sends a drafted outreach email via Amazon SES. Handles delivery status
tracking (sent/bounced/failed) and updates the case record.

Only invoked for AUTO_SEND cases. NEEDS_APPROVAL cases go through the
approval queue first, then reach here after analyst approval.

Inputs (from Step Functions SendOutreachEmail state):
  - case_id: str
  - outreach: dict containing:
      - email_id: str
      - client_id: str
      - rendered_body_ref: str (S3 key)
      - case_ref: str
      - subject: str

Outputs:
  - case_id: str
  - email_id: str
  - delivery_status: SENT | FAILED
  - message_id: str (SES message ID)
"""

import os
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

ses = boto3.client("ses")
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

cases_table = dynamodb.Table(os.environ["CASES_TABLE"])
DOCUMENTS_BUCKET = os.environ["DOCUMENTS_BUCKET"]
SENDER_EMAIL = os.environ["SENDER_EMAIL"]  # Verified SES sender identity


def handler(event, context):
    case_id = event["case_id"]
    outreach = event.get("outreach", {})

    # Unwrap -- state machine may nest as {"outreach": {...}}
    if "outreach" in outreach:
        outreach = outreach["outreach"]

    email_id = outreach["email_id"]
    client_id = outreach["client_id"]
    case_ref = outreach["case_ref"]
    subject = outreach["subject"]

    # Get case record — used for recipient email AND rendered_body_ref
    # (analyst edit path writes updated ref to Cases table, not to $.outreach)
    case = _get_case(case_id)
    rendered_body_ref = case.get("rendered_body_ref", outreach["rendered_body_ref"])
    recipient_email = case.get("client_email")

    # Fetch rendered email body from S3
    body_html = _fetch_rendered_body(rendered_body_ref)

    if not recipient_email:
        emit_audit_event(case_id, actor="send-outreach-email",
                         action="SEND_FAILED:NO_RECIPIENT_EMAIL")
        return {
            "case_id": case_id,
            "email_id": email_id,
            "delivery_status": "FAILED",
            "reason": "No recipient email address on case record",
        }

    # Send via SES
    try:
        ses_response = ses.send_email(
            Source=SENDER_EMAIL,
            Destination={"ToAddresses": [recipient_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                    "Text": {"Data": _html_to_plain(body_html), "Charset": "UTF-8"},
                },
            },
            Tags=[
                {"Name": "case_id", "Value": case_id},
                {"Name": "case_ref", "Value": case_ref},
            ],
            # Note: X-Case-Ref custom header not supported on SES v1 send_email.
            # Correlation relies on subject-line CASEREF pattern (already embedded).
            # TODO: migrate to sesv2 client for custom header support as fast-follow.
        )
        message_id = ses_response.get("MessageId", "unknown")
        delivery_status = "SENT"

    except Exception as e:
        print(f"[SEND] SES send failed for case {case_id}: {e}")
        message_id = ""
        delivery_status = "FAILED"

    # Update case record
    _update_case_sent(case_id, delivery_status, message_id)

    emit_audit_event(
        case_id, actor="send-outreach-email",
        action=f"EMAIL_{delivery_status}",
        output_ref=message_id,
    )

    return {
        "case_id": case_id,
        "email_id": email_id,
        "delivery_status": delivery_status,
        "message_id": message_id,
    }


def _get_case(case_id):
    response = cases_table.get_item(Key={"case_id": case_id})
    return response.get("Item", {})


def _fetch_rendered_body(rendered_body_ref):
    """Download rendered email HTML from S3."""
    # Parse s3://bucket/key format
    ref = rendered_body_ref.replace("s3://", "")
    bucket = ref.split("/", 1)[0]
    key = ref.split("/", 1)[1]
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


def _html_to_plain(html_body):
    """Simple HTML-to-plaintext fallback (strip tags)."""
    import re
    text = re.sub(r"<[^>]+>", "", html_body)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _update_case_sent(case_id, delivery_status, message_id):
    """Update case record after email send attempt."""
    now = datetime.now(timezone.utc).isoformat()

    if delivery_status == "SENT":
        status = "AUTO_SENT"
        update_expr = (
            "SET #s = :s, last_contacted_at = :ts, "
            "last_ses_message_id = :mid, updated_at = :ts"
        )
        expr_values = {":s": status, ":ts": now, ":mid": message_id}
    else:
        status = "SEND_FAILED"
        update_expr = "SET #s = :s, updated_at = :ts"
        expr_values = {":s": status, ":ts": now}

    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=expr_values,
    )
