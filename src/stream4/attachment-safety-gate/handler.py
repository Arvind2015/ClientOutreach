"""
Stream 4 — Attachment Safety Gate (Task 5.3)

Validates each attachment against safety rules before allowing it to proceed
to AI classification. Enforces:
  - Allowed file types: JPG, JPEG, PNG, PDF only
  - Minimum file size (configurable, default 1 KB — reject empty/corrupt files)
  - Maximum file size (configurable, default 10 MB)
  - Basic content-type vs extension consistency check
  - Blocked dangerous extensions
  - Rejects/quarantines anything that fails

Attachments that pass are forwarded to classify-attachment.
Attachments that fail are moved to a quarantine prefix in S3 and flagged.

Inputs (from correlate-case output):
  - message_id: str
  - case_id: str
  - client_id: str
  - attachments: list[dict]   # [{attachment_id, filename, content_type, s3_ref, size_bytes}]

Outputs:
  - message_id: str
  - case_id: str
  - client_id: str
  - safe_attachments: list[dict]       # attachments that passed safety checks
  - quarantined_attachments: list[dict] # attachments that failed (with rejection reason)
"""

import os
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

s3 = boto3.client("s3")

DOCUMENTS_BUCKET = os.environ["DOCUMENTS_BUCKET"]

# Configurable safety thresholds
MIN_FILE_SIZE_BYTES = int(os.environ.get("MIN_FILE_SIZE_BYTES", str(1024)))              # 1 KB
MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_BYTES", str(4 * 1024 * 1024)))   # 4 MB

# Allowed MIME types mapped to their expected extensions
# Accepted formats: JPG, JPEG, PNG, PDF
ALLOWED_TYPES = {
    "application/pdf": [".pdf"],
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
}

# Dangerous extensions that should never be processed regardless of content-type
BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".ps1", ".vbs",
    ".js", ".jar", ".sh", ".dll", ".sys", ".inf", ".reg",
}


def handler(event, context):
    message_id = event["message_id"]
    case_id = event["case_id"]
    client_id = event["client_id"]
    attachments = event.get("attachments", [])

    safe_attachments = []
    quarantined_attachments = []

    for attachment in attachments:
        result = _check_attachment(attachment)
        if result["safe"]:
            safe_attachments.append(attachment)
        else:
            attachment["rejection_reason"] = result["reason"]
            quarantined_attachments.append(attachment)
            _quarantine(attachment)

    # Audit the results
    if quarantined_attachments:
        emit_audit_event(
            case_id=case_id,
            actor="attachment-safety-gate",
            action=f"ATTACHMENTS_QUARANTINED: {len(quarantined_attachments)} of {len(attachments)}",
            input_ref=message_id,
        )

    if safe_attachments:
        emit_audit_event(
            case_id=case_id,
            actor="attachment-safety-gate",
            action=f"ATTACHMENTS_CLEARED: {len(safe_attachments)} of {len(attachments)}",
            input_ref=message_id,
        )

    return {
        "message_id": message_id,
        "case_id": case_id,
        "client_id": client_id,
        "safe_attachments": safe_attachments,
        "quarantined_attachments": quarantined_attachments,
    }


def _check_attachment(attachment):
    """
    Run safety checks on a single attachment.
    Returns {"safe": bool, "reason": str | None}
    """
    filename = attachment.get("filename", "")
    content_type = attachment.get("content_type", "")
    size_bytes = attachment.get("size_bytes", 0)

    # Check 1: Maximum file size
    if size_bytes > MAX_FILE_SIZE_BYTES:
        return {
            "safe": False,
            "reason": f"File size {size_bytes} bytes exceeds maximum {MAX_FILE_SIZE_BYTES} bytes",
        }

    # Check 2: Minimum file size (reject empty or corrupt files)
    if size_bytes < MIN_FILE_SIZE_BYTES:
        return {
            "safe": False,
            "reason": f"File size {size_bytes} bytes below minimum {MIN_FILE_SIZE_BYTES} bytes",
        }

    # Check 3: Blocked extensions
    extension = _get_extension(filename).lower()
    if extension in BLOCKED_EXTENSIONS:
        return {
            "safe": False,
            "reason": f"Blocked file extension: {extension}",
        }

    # Check 4: Allowed content type (JPG, JPEG, PNG, PDF only)
    if content_type not in ALLOWED_TYPES:
        return {
            "safe": False,
            "reason": (
                f"Unsupported file type: {content_type}. "
                f"Accepted types: JPG, JPEG, PNG, PDF"
            ),
        }

    # Check 5: Extension matches content type
    allowed_extensions = ALLOWED_TYPES[content_type]
    if extension and extension not in allowed_extensions:
        return {
            "safe": False,
            "reason": (
                f"Extension mismatch: {extension} not consistent with "
                f"content type {content_type} (expected {allowed_extensions})"
            ),
        }

    return {"safe": True, "reason": None}


def _get_extension(filename):
    """Extract file extension including the dot."""
    if "." in filename:
        return "." + filename.rsplit(".", 1)[-1]
    return ""


def _quarantine(attachment):
    """
    Move the attachment to a quarantine prefix in S3.
    Original is kept (copy + tag) so it can be reviewed by analysts.
    """
    s3_ref = attachment.get("s3_ref", "")
    if not s3_ref.startswith(f"s3://{DOCUMENTS_BUCKET}/"):
        return

    original_key = s3_ref.replace(f"s3://{DOCUMENTS_BUCKET}/", "")
    quarantine_key = f"quarantine/{original_key}"

    try:
        s3.copy_object(
            Bucket=DOCUMENTS_BUCKET,
            Key=quarantine_key,
            CopySource={"Bucket": DOCUMENTS_BUCKET, "Key": original_key},
            Tagging=f"quarantine_reason={attachment.get('rejection_reason', 'unknown')}",
            TaggingDirective="REPLACE",
        )
    except Exception as e:
        # Log but don't fail the gate — the original is still in place
        print(f"[SAFETY GATE] Failed to quarantine {original_key}: {e}")
