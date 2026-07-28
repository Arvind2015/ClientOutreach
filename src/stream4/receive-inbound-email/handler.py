"""
Stream 4 — Receive Inbound Email (Task 5.1)

Triggered by an S3 event (via EventBridge or S3 notification) when SES deposits
a raw .eml file into the inbound-emails prefix of the documents bucket.

Responsibilities:
  1. Fetch the raw email from S3.
  2. Parse MIME structure — extract headers, plain-text/HTML body, and attachments.
  3. Store each attachment in S3 under a structured key.
  4. Write an InboundMessage record to DynamoDB with status PENDING.
  5. Return parsed metadata for the next step (correlate-case).

Inputs (from S3 event / Step Functions):
  - bucket: str
  - key: str          # S3 key of the raw .eml file

Outputs:
  - message_id: str
  - sender: str
  - subject: str
  - received_at: str
  - raw_ref: str
  - attachments: list[dict]   # [{attachment_id, filename, content_type, s3_ref, size_bytes}]
  - headers: dict             # selected headers relevant to correlation
"""

import os
import uuid
import email
import email.policy
from datetime import datetime, timezone

import boto3

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

DOCUMENTS_BUCKET = os.environ["DOCUMENTS_BUCKET"]
INBOUND_TABLE = os.environ.get("INBOUND_TABLE", "InboundMessages")
inbound_table = dynamodb.Table(INBOUND_TABLE)


def handler(event, context):
    bucket = event["bucket"]
    key = event["key"]

    # 1. Fetch raw email from S3
    raw_email_bytes = _fetch_raw_email(bucket, key)

    # 2. Parse MIME message
    msg = email.message_from_bytes(raw_email_bytes, policy=email.policy.default)

    sender = msg.get("From", "unknown")
    subject = msg.get("Subject", "")
    date_header = msg.get("Date", "")
    message_id = msg.get("Message-ID", str(uuid.uuid4()))
    # Normalise message_id — strip angle brackets if present
    message_id = message_id.strip("<>") or str(uuid.uuid4())

    # Extract headers useful for case correlation
    headers = {
        "from": sender,
        "subject": subject,
        "date": date_header,
        "in_reply_to": msg.get("In-Reply-To", ""),
        "references": msg.get("References", ""),
        "x_case_ref": msg.get("X-Case-Ref", ""),
    }

    received_at = datetime.now(timezone.utc).isoformat()

    # 3. Extract and store attachments
    attachments = _extract_attachments(msg, message_id)

    # 4. Write InboundMessage record
    record = {
        "message_id": message_id,
        "sender": sender,
        "subject": subject,
        "received_at": received_at,
        "raw_ref": f"s3://{bucket}/{key}",
        "correlation_status": "PENDING",
        "attachment_count": len(attachments),
        "headers": headers,
    }
    inbound_table.put_item(Item=record)

    # 5. Audit
    emit_audit_event(
        case_id="UNMATCHED",  # not yet correlated
        actor="receive-inbound-email",
        action="INBOUND_EMAIL_RECEIVED",
        input_ref=f"s3://{bucket}/{key}",
    )

    return {
        "message_id": message_id,
        "sender": sender,
        "subject": subject,
        "received_at": received_at,
        "raw_ref": f"s3://{bucket}/{key}",
        "attachments": attachments,
        "headers": headers,
    }


def _fetch_raw_email(bucket, key):
    """Download raw .eml bytes from S3."""
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _extract_attachments(msg, message_id):
    """
    Walk MIME parts, upload each attachment to S3 under a structured prefix,
    and return metadata list.
    """
    attachments = []

    for part in msg.walk():
        content_disposition = part.get("Content-Disposition", "")
        if "attachment" not in content_disposition and part.get_content_maintype() == "multipart":
            continue

        filename = part.get_filename()
        if not filename:
            continue

        content_type = part.get_content_type()
        payload = part.get_payload(decode=True)
        if payload is None:
            continue

        attachment_id = str(uuid.uuid4())
        s3_key = f"inbound-attachments/{message_id}/{attachment_id}/{filename}"

        # Upload attachment to S3
        s3.put_object(
            Bucket=DOCUMENTS_BUCKET,
            Key=s3_key,
            Body=payload,
            ContentType=content_type,
        )

        attachments.append({
            "attachment_id": attachment_id,
            "filename": filename,
            "content_type": content_type,
            "s3_ref": f"s3://{DOCUMENTS_BUCKET}/{s3_key}",
            "size_bytes": len(payload),
        })

    return attachments
