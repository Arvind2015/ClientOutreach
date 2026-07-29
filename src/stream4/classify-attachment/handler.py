"""
Stream 4 — Classify Attachment (Task 5.4)

Uses Amazon Bedrock (Nova Pro via Converse API) to classify each safe
attachment against the set of outstanding KYC requirement types for the case.
Determines which requirement each document satisfies (e.g., passport, proof
of address, certificate of incorporation).

The classifier produces:
  - classification: the requirement_type this document satisfies
  - classification_confidence: 0.0–1.0 score

Inputs (from attachment-safety-gate output):
  - message_id: str
  - case_id: str
  - client_id: str
  - safe_attachments: list[dict]  # [{attachment_id, filename, content_type, s3_ref, size_bytes}]

Outputs:
  - message_id: str
  - case_id: str
  - client_id: str
  - classified_attachments: list[dict]  # [{attachment_id, s3_ref, classification, classification_confidence, ...}]
"""

import os
import json
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

s3 = boto3.client("s3")
bedrock_runtime = boto3.client("bedrock-runtime")
dynamodb = boto3.resource("dynamodb")

DOCUMENTS_BUCKET = os.environ["DOCUMENTS_BUCKET"]
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")
CASES_TABLE = os.environ["CASES_TABLE"]
cases_table = dynamodb.Table(CASES_TABLE)

# Known requirement types the classifier can assign
REQUIREMENT_TYPES = [
    "PASSPORT",
    "NATIONAL_ID",
    "PROOF_OF_ADDRESS",
    "CERTIFICATE_OF_INCORPORATION",
    "CERTIFICATE_OF_GOOD_STANDING",
    "SOURCE_OF_FUNDS_DECLARATION",
    "BANK_STATEMENT",
    "TAX_CERTIFICATE",
    "BENEFICIAL_OWNERSHIP_DECLARATION",
    "POWER_OF_ATTORNEY",
    "OTHER",
]


def handler(event, context):
    message_id = event["message_id"]
    case_id = event["case_id"]
    client_id = event["client_id"]
    safe_attachments = event.get("safe_attachments", [])

    # Fetch outstanding requirements for context (improves classification accuracy)
    outstanding = _get_outstanding_requirements(case_id)

    classified_attachments = []

    for attachment in safe_attachments:
        classification_result = _classify(attachment, outstanding)
        classified_attachments.append({
            "attachment_id": attachment["attachment_id"],
            "filename": attachment.get("filename", ""),
            "content_type": attachment.get("content_type", ""),
            "s3_ref": attachment["s3_ref"],
            "size_bytes": attachment.get("size_bytes", 0),
            "classification": classification_result["classification"],
            "classification_confidence": classification_result["confidence"],
        })

    emit_audit_event(
        case_id=case_id,
        actor="classify-attachment",
        action=f"ATTACHMENTS_CLASSIFIED: {len(classified_attachments)}",
        input_ref=message_id,
    )

    return {
        "message_id": message_id,
        "case_id": case_id,
        "client_id": client_id,
        "classified_attachments": classified_attachments,
    }


def _get_outstanding_requirements(case_id):
    """
    Retrieve outstanding requirement types for the case to provide context
    to the classifier (e.g., if we only need a passport, bias classification
    toward passport-like documents).
    """
    response = cases_table.get_item(Key={"case_id": case_id})
    case = response.get("Item", {})
    # Outstanding requirements stored during gap analysis phase
    return case.get("outstanding_requirements", [])


def _classify(attachment, outstanding_requirements):
    """
    Invoke Bedrock to classify the attachment as a document type.

    For PDFs and images, sends the document content to the model.
    Returns {"classification": str, "confidence": float}
    """
    s3_ref = attachment["s3_ref"]
    content_type = attachment.get("content_type", "")
    filename = attachment.get("filename", "")

    # Fetch document bytes from S3
    doc_bytes = _fetch_from_s3(s3_ref)

    # Build classification prompt
    outstanding_str = ", ".join(outstanding_requirements) if outstanding_requirements else "unknown"
    prompt = _build_classification_prompt(filename, content_type, outstanding_str)

    try:
        response = _invoke_bedrock(prompt, doc_bytes, content_type)
        return _parse_classification_response(response)
    except Exception as e:
        print(f"[CLASSIFY] Bedrock invocation failed for {attachment['attachment_id']}: {e}")
        return {"classification": "OTHER", "confidence": 0.0}


def _build_classification_prompt(filename, content_type, outstanding_requirements):
    """Build the system + user prompt for document classification."""
    return (
        "You are a document classifier for a KYC (Know Your Customer) compliance system. "
        "Classify the attached document into exactly one of these categories:\n"
        f"{json.dumps(REQUIREMENT_TYPES, indent=2)}\n\n"
        f"The client currently has these outstanding requirements: {outstanding_requirements}\n\n"
        f"The file is named '{filename}' with content type '{content_type}'.\n\n"
        "Respond with ONLY a JSON object in this exact format:\n"
        '{"classification": "<REQUIREMENT_TYPE>", "confidence": <0.0-1.0>}\n\n'
        "Base your confidence on how clearly the document matches the category. "
        "Use 'OTHER' with low confidence if you cannot determine the document type."
    )


def _fetch_from_s3(s3_ref):
    """Download document bytes from S3 reference."""
    # Parse s3://bucket/key format
    path = s3_ref.replace("s3://", "")
    bucket = path.split("/", 1)[0]
    key = path.split("/", 1)[1]
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _invoke_bedrock(prompt, doc_bytes, content_type):
    """
    Call Bedrock with the document for classification.
    Uses the Converse API for multimodal input.

    Nova Pro requires:
      - image/jpeg, image/png → image content block
      - application/pdf, docx  → document content block
    """
    content_block = _build_content_block(doc_bytes, content_type)

    messages = [
        {
            "role": "user",
            "content": [
                content_block,
                {"text": prompt},
            ],
        }
    ]

    response = bedrock_runtime.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=messages,
        inferenceConfig={"maxTokens": 256, "temperature": 0.0},
    )

    return response["output"]["message"]["content"][0]["text"]


def _build_content_block(doc_bytes, content_type):
    """
    Build the appropriate Bedrock Converse API content block based on MIME type.
    Nova Pro uses image blocks for JPEG/PNG, document blocks for PDF/DOCX.
    """
    if content_type in ("image/jpeg", "image/png"):
        return {
            "image": {
                "format": _bedrock_image_format(content_type),
                "source": {"bytes": doc_bytes},
            }
        }
    else:
        return {
            "document": {
                "format": _bedrock_document_format(content_type),
                "name": "attachment",
                "source": {"bytes": doc_bytes},
            }
        }


def _bedrock_image_format(content_type):
    """Map image MIME types to Nova Pro image format strings."""
    mapping = {
        "image/jpeg": "jpeg",
        "image/png": "png",
    }
    return mapping.get(content_type, "jpeg")


def _bedrock_document_format(content_type):
    """Map document MIME types to Nova Pro document format strings."""
    mapping = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    }
    return mapping.get(content_type, "pdf")


def _parse_classification_response(response_text):
    """Parse the JSON classification response from Bedrock."""
    try:
        # Strip markdown code fences if present
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        result = json.loads(cleaned)
        classification = result.get("classification", "OTHER")
        confidence = float(result.get("confidence", 0.0))

        # Validate classification is in known types
        if classification not in REQUIREMENT_TYPES:
            classification = "OTHER"
            confidence = min(confidence, 0.3)

        return {"classification": classification, "confidence": confidence}
    except (json.JSONDecodeError, ValueError, KeyError):
        return {"classification": "OTHER", "confidence": 0.0}
