"""
Stream 4 — Extract Data (Task 5.5)

Extracts structured fields from classified attachments using Amazon Bedrock
(multimodal LLM) for document understanding. Each document type has specific
fields to extract based on checklist requirements.

Produces extraction results with per-field confidence scores.

Inputs (from classify-attachment output):
  - message_id: str
  - case_id: str
  - client_id: str
  - classified_attachments: list[dict]
      [{attachment_id, s3_ref, classification, classification_confidence, ...}]

Outputs:
  - message_id: str
  - case_id: str
  - client_id: str
  - extracted_attachments: list[dict]
      [{attachment_id, s3_ref, classification, classification_confidence,
        extracted_fields, extraction_confidence}]
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

DOCUMENTS_BUCKET = os.environ["DOCUMENTS_BUCKET"]
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")

# Fields to extract per requirement type
EXTRACTION_SCHEMAS = {
    "PASSPORT": {
        "fields": ["full_name", "date_of_birth", "nationality", "passport_number",
                   "issued_at", "expires_at", "issuing_country"],
        "description": "Identity passport document",
    },
    "NATIONAL_ID": {
        "fields": ["full_name", "date_of_birth", "id_number", "issued_at", "expires_at"],
        "description": "National identity card",
    },
    "PROOF_OF_ADDRESS": {
        "fields": ["full_name", "address_line_1", "address_line_2", "city",
                   "postal_code", "country", "document_date"],
        "description": "Utility bill, bank statement, or official letter showing address",
    },
    "CERTIFICATE_OF_INCORPORATION": {
        "fields": ["registered_name", "registration_number", "jurisdiction",
                   "issued_at", "expires_at", "registered_address"],
        "description": "Company registration/incorporation certificate",
    },
    "CERTIFICATE_OF_GOOD_STANDING": {
        "fields": ["company_name", "registration_number", "jurisdiction",
                   "issued_at", "valid_until"],
        "description": "Certificate confirming the company is in good standing",
    },
    "SOURCE_OF_FUNDS_DECLARATION": {
        "fields": ["declarant_name", "source_description", "declared_amount",
                   "currency", "declaration_date", "signed"],
        "description": "Declaration of source of funds/wealth",
    },
    "BANK_STATEMENT": {
        "fields": ["account_holder_name", "bank_name", "account_number_last4",
                   "statement_period_start", "statement_period_end", "currency"],
        "description": "Bank account statement",
    },
    "TAX_CERTIFICATE": {
        "fields": ["taxpayer_name", "tax_id", "jurisdiction", "tax_year",
                   "issued_at"],
        "description": "Tax residency or clearance certificate",
    },
    "BENEFICIAL_OWNERSHIP_DECLARATION": {
        "fields": ["company_name", "beneficial_owners", "ownership_percentages",
                   "declaration_date", "signed"],
        "description": "Declaration of beneficial ownership structure",
    },
    "POWER_OF_ATTORNEY": {
        "fields": ["grantor_name", "attorney_name", "scope", "issued_at",
                   "expires_at", "notarised"],
        "description": "Legal power of attorney document",
    },
}


def handler(event, context):
    message_id = event["message_id"]
    case_id = event["case_id"]
    client_id = event["client_id"]
    classified_attachments = event.get("classified_attachments", [])

    extracted_attachments = []

    for attachment in classified_attachments:
        classification = attachment["classification"]
        extraction_result = _extract_fields(attachment, classification)

        extracted_attachments.append({
            "attachment_id": attachment["attachment_id"],
            "filename": attachment.get("filename", ""),
            "content_type": attachment.get("content_type", ""),
            "s3_ref": attachment["s3_ref"],
            "classification": classification,
            "classification_confidence": attachment["classification_confidence"],
            "extracted_fields": extraction_result["fields"],
            "extraction_confidence": extraction_result["confidence"],
        })

    emit_audit_event(
        case_id=case_id,
        actor="extract-data",
        action=f"DATA_EXTRACTED: {len(extracted_attachments)} attachments",
        input_ref=message_id,
    )

    return {
        "message_id": message_id,
        "case_id": case_id,
        "client_id": client_id,
        "extracted_attachments": extracted_attachments,
    }


def _extract_fields(attachment, classification):
    """
    Invoke Bedrock to extract structured fields from the document
    based on its classification type.

    Returns {"fields": dict, "confidence": float}
    """
    schema = EXTRACTION_SCHEMAS.get(classification)
    if not schema:
        # Unknown type — attempt generic extraction
        schema = {
            "fields": ["document_type", "issuer", "date", "name"],
            "description": "Unknown document type",
        }

    # Fetch document bytes
    doc_bytes = _fetch_from_s3(attachment["s3_ref"])
    content_type = attachment.get("content_type", "application/pdf")

    prompt = _build_extraction_prompt(schema, classification)

    try:
        response = _invoke_bedrock(prompt, doc_bytes, content_type)
        return _parse_extraction_response(response, schema["fields"])
    except Exception as e:
        print(f"[EXTRACT] Bedrock extraction failed for {attachment['attachment_id']}: {e}")
        return {"fields": {}, "confidence": 0.0}


def _build_extraction_prompt(schema, classification):
    """Build the extraction prompt with the expected field schema."""
    fields_list = json.dumps(schema["fields"])
    return (
        "You are a document data extraction system for KYC compliance. "
        f"This document has been classified as: {classification} "
        f"({schema['description']}).\n\n"
        f"Extract EXACTLY these fields from the document: {fields_list}\n\n"
        "Respond with ONLY a JSON object in this format:\n"
        "{\n"
        '  "fields": {"field_name": "extracted_value", ...},\n'
        '  "confidence": <0.0-1.0>,\n'
        '  "notes": "any issues or uncertainties"\n'
        "}\n\n"
        "Rules:\n"
        "- Use null for any field you cannot find in the document.\n"
        "- Use ISO 8601 format for all dates (YYYY-MM-DD).\n"
        "- Set confidence based on document clarity and extraction certainty.\n"
        "- Lower confidence if the document is blurry, partially obscured, or ambiguous.\n"
        "- If the document does not appear to match the stated classification, "
        "set confidence below 0.3 and note the discrepancy."
    )


def _fetch_from_s3(s3_ref):
    """Download document bytes from S3 reference."""
    path = s3_ref.replace("s3://", "")
    bucket = path.split("/", 1)[0]
    key = path.split("/", 1)[1]
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _invoke_bedrock(prompt, doc_bytes, content_type):
    """Call Bedrock with document for field extraction."""
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "document": {
                        "format": _bedrock_format(content_type),
                        "name": "attachment",
                        "source": {"bytes": doc_bytes},
                    }
                },
                {"text": prompt},
            ],
        }
    ]

    response = bedrock_runtime.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=messages,
        inferenceConfig={"maxTokens": 1024, "temperature": 0.0},
    )

    return response["output"]["message"]["content"][0]["text"]


def _bedrock_format(content_type):
    """Map MIME type to Bedrock document format string."""
    mapping = {
        "application/pdf": "pdf",
        "image/jpeg": "jpeg",
        "image/png": "png",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    }
    return mapping.get(content_type, "pdf")


def _parse_extraction_response(response_text, expected_fields):
    """Parse the JSON extraction response from Bedrock."""
    try:
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        result = json.loads(cleaned)

        fields = result.get("fields", {})
        confidence = float(result.get("confidence", 0.0))

        # Calculate coverage — how many expected fields were actually extracted
        non_null_fields = sum(1 for f in expected_fields if fields.get(f) is not None)
        coverage = non_null_fields / len(expected_fields) if expected_fields else 0.0

        # Adjust confidence by coverage (penalise missing fields)
        adjusted_confidence = confidence * (0.5 + 0.5 * coverage)

        return {"fields": fields, "confidence": round(adjusted_confidence, 3)}
    except (json.JSONDecodeError, ValueError, KeyError):
        return {"fields": {}, "confidence": 0.0}
