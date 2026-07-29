"""
Local test script for Stream 4 -- Inbound Email & Document Reading.

Calls each handler in pipeline order with synthetic test data, printing
results at each stage. No AWS credentials required -- all external calls
are patched with simple mocks.

Usage:
    python test/test_stream4_local.py
"""

import sys
import os
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# Add shared layer to path (mimics Lambda layer)
SHARED_LAYER = os.path.join(os.path.dirname(__file__), "..", "src", "shared", "common-layer")
sys.path.insert(0, os.path.abspath(SHARED_LAYER))

# Patch environment variables before importing handlers
os.environ["DOCUMENTS_BUCKET"] = "test-bucket"
os.environ["INBOUND_TABLE"] = "InboundMessages"
os.environ["CASES_TABLE"] = "Cases"
os.environ["MANUAL_TRIAGE_QUEUE_URL"] = "https://sqs.eu-central-1.amazonaws.com/123456789/ManualTriageQueue"
os.environ["ANALYST_REVIEW_QUEUE_URL"] = "https://sqs.eu-central-1.amazonaws.com/123456789/AnalystReviewQueue"
os.environ["AUDIT_EVENT_BUS_NAME"] = "test-audit-bus"
os.environ["BEDROCK_MODEL_ID"] = "amazon.nova-pro-v1:0"
os.environ["MIN_FILE_SIZE_BYTES"] = "1024"
os.environ["MAX_FILE_SIZE_BYTES"] = str(4 * 1024 * 1024)
os.environ["CLASSIFICATION_CONFIDENCE_THRESHOLD"] = "0.75"
os.environ["EXTRACTION_CONFIDENCE_THRESHOLD"] = "0.70"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def divider(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_result(result):
    print(json.dumps(result, indent=2, default=str))


# ---------------------------------------------------------------------------
# Build a fake raw email (.eml) for testing
# ---------------------------------------------------------------------------

def build_test_email():
    """Create a minimal MIME email with one PDF and one JPEG attachment."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from email.mime.image import MIMEImage

    msg = MIMEMultipart()
    msg["From"] = "client@example.com"
    msg["To"] = "kyc-inbox@bank.com"
    msg["Subject"] = "Re: KYC Information Required - CASEREF-case-001"
    msg["Message-ID"] = "<test-msg-001@example.com>"
    msg["In-Reply-To"] = "<outbound-001@bank.com>"
    msg["X-Case-Ref"] = "CASEREF-case-001"

    # Text body
    body = MIMEText("Please find attached my certificate of incorporation and passport scan.", "plain")
    msg.attach(body)

    # Fake PDF attachment (2 KB of dummy bytes -- above MIN_FILE_SIZE_BYTES)
    fake_pdf = b"%PDF-1.4 " + b"x" * 2048
    attachment_pdf = MIMEApplication(fake_pdf, _subtype="pdf")
    attachment_pdf.add_header("Content-Disposition", "attachment", filename="cert_of_inc.pdf")
    msg.attach(attachment_pdf)

    # Fake JPEG attachment (2 KB of dummy bytes -- tests image content block path)
    fake_jpeg = b"\xff\xd8\xff\xe0" + b"x" * 2048  # JPEG magic bytes + padding
    attachment_jpeg = MIMEImage(fake_jpeg, _subtype="jpeg")
    attachment_jpeg.add_header("Content-Disposition", "attachment", filename="passport_scan.jpg")
    msg.attach(attachment_jpeg)

    return msg.as_bytes()


# ---------------------------------------------------------------------------
# Mock AWS clients
# ---------------------------------------------------------------------------

def create_mock_s3():
    mock = MagicMock()
    mock.get_object.return_value = {"Body": MagicMock(read=lambda: build_test_email())}
    mock.put_object.return_value = {}
    mock.copy_object.return_value = {}
    return mock


def create_mock_dynamodb():
    mock_table = MagicMock()
    mock_table.put_item.return_value = {}
    mock_table.update_item.return_value = {}
    mock_table.get_item.return_value = {
        "Item": {
            "case_id": "case-001",
            "client_id": "client-001",
            "status": "AWAITING_RESPONSE",
            "sfn_task_token": "arn:aws:states:eu-central-1:123:task-token-abc123",
            "outstanding_requirements": ["CERTIFICATE_OF_INCORPORATION"],
        }
    }

    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    return mock_resource


def create_mock_events():
    mock = MagicMock()
    mock.put_events.return_value = {}
    return mock


def create_mock_sqs():
    mock = MagicMock()
    mock.send_message.return_value = {}
    return mock


def create_mock_sfn():
    mock = MagicMock()
    mock.send_task_success.return_value = {}
    return mock


def create_mock_bedrock():
    """Returns a mock that simulates Bedrock classification and extraction.
    Also validates that the content block shape is correct for the content type:
      - image/jpeg, image/png → must use 'image' block
      - application/pdf, docx → must use 'document' block
    """
    mock = MagicMock()

    def converse_side_effect(**kwargs):
        messages = kwargs.get("messages", [])
        prompt_text = ""
        content_block = None
        for msg in messages:
            for content in msg.get("content", []):
                if "text" in content:
                    prompt_text = content["text"]
                elif "image" in content:
                    content_block = "image"
                elif "document" in content:
                    content_block = "document"

        # Validate content block type matches Nova Pro requirements
        if content_block == "image":
            print(f"    [MOCK BEDROCK] [OK] Received image content block (correct for JPEG/PNG)")
        elif content_block == "document":
            print(f"    [MOCK BEDROCK] [OK] Received document content block (correct for PDF/DOCX)")
        else:
            print(f"    [MOCK BEDROCK] [WARN] No content block detected -- unexpected")

        if "classifier" in prompt_text.lower() or "classify" in prompt_text.lower():
            # Return different classification based on content block type
            if content_block == "image":
                response_text = json.dumps({
                    "classification": "PASSPORT",
                    "confidence": 0.89,
                })
            else:
                response_text = json.dumps({
                    "classification": "CERTIFICATE_OF_INCORPORATION",
                    "confidence": 0.93,
                })
        else:
            if content_block == "image":
                response_text = json.dumps({
                    "fields": {
                        "full_name": "John Smith",
                        "date_of_birth": "1985-03-22",
                        "nationality": "British",
                        "passport_number": "123456789",
                        "issued_at": "2022-06-01",
                        "expires_at": "2032-06-01",
                        "issuing_country": "UK",
                    },
                    "confidence": 0.88,
                    "notes": "Passport scan, slightly angled but legible",
                })
            else:
                response_text = json.dumps({
                    "fields": {
                        "registered_name": "Acme Corp Ltd",
                        "registration_number": "12345678",
                        "jurisdiction": "UK",
                        "issued_at": "2026-01-15",
                        "expires_at": "2031-01-15",
                        "registered_address": "123 Business St, London EC1A 1BB",
                    },
                    "confidence": 0.91,
                    "notes": "Clear document, all fields legible",
                })

        return {
            "output": {
                "message": {
                    "content": [{"text": response_text}]
                }
            }
        }

    mock.converse.side_effect = converse_side_effect
    return mock


# ---------------------------------------------------------------------------
# Run the pipeline
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 70)
    print("  STREAM 4 LOCAL TEST -- Inbound Email & Document Reading Pipeline")
    print("=" * 70)

    mock_s3 = create_mock_s3()
    mock_dynamodb = create_mock_dynamodb()
    mock_events = create_mock_events()
    mock_sqs = create_mock_sqs()
    mock_sfn = create_mock_sfn()
    mock_bedrock = create_mock_bedrock()

    # Patch boto3 globally for all handler imports
    with patch("boto3.client") as mock_client, \
         patch("boto3.resource") as mock_resource:

        def client_factory(service, **kwargs):
            return {
                "s3": mock_s3,
                "events": mock_events,
                "sqs": mock_sqs,
                "stepfunctions": mock_sfn,
                "bedrock-runtime": mock_bedrock,
            }.get(service, MagicMock())

        mock_client.side_effect = client_factory
        mock_resource.return_value = mock_dynamodb

        # --- Step 1: Receive Inbound Email ---
        divider("Step 1: receive-inbound-email")
        sys.path.insert(0, os.path.abspath("src/stream4/receive-inbound-email"))
        from importlib import import_module
        receive_mod = import_module("handler")

        receive_result = receive_mod.handler(
            {"bucket": "test-bucket", "key": "inbound-emails/raw/test-msg-001.eml"},
            None,
        )
        print_result(receive_result)

        # --- Step 2: Correlate Case ---
        divider("Step 2: correlate-case")
        sys.path.insert(0, os.path.abspath("src/stream4/correlate-case"))
        # Need to reload to pick up mocks
        if "handler" in sys.modules:
            del sys.modules["handler"]
        correlate_mod = import_module("handler")

        correlate_input = {
            "message_id": receive_result["message_id"],
            "sender": receive_result["sender"],
            "subject": receive_result["subject"],
            "headers": receive_result["headers"],
            "attachments": receive_result["attachments"],
        }
        correlate_result = correlate_mod.handler(correlate_input, None)
        print_result(correlate_result)

        # --- Step 3: Attachment Safety Gate ---
        divider("Step 3: attachment-safety-gate")
        sys.path.insert(0, os.path.abspath("src/stream4/attachment-safety-gate"))
        if "handler" in sys.modules:
            del sys.modules["handler"]
        safety_mod = import_module("handler")

        safety_input = {
            "message_id": correlate_result["message_id"],
            "case_id": correlate_result["case_id"],
            "client_id": correlate_result["client_id"],
            "attachments": correlate_result["attachments"],
        }
        safety_result = safety_mod.handler(safety_input, None)
        print_result(safety_result)

        # --- Step 4: Classify Attachment ---
        divider("Step 4: classify-attachment")
        sys.path.insert(0, os.path.abspath("src/stream4/classify-attachment"))
        if "handler" in sys.modules:
            del sys.modules["handler"]
        classify_mod = import_module("handler")

        classify_input = {
            "message_id": safety_result["message_id"],
            "case_id": safety_result["case_id"],
            "client_id": safety_result["client_id"],
            "safe_attachments": safety_result["safe_attachments"],
        }
        classify_result = classify_mod.handler(classify_input, None)
        print_result(classify_result)

        # --- Step 5: Extract Data ---
        divider("Step 5: extract-data")
        sys.path.insert(0, os.path.abspath("src/stream4/extract-data"))
        if "handler" in sys.modules:
            del sys.modules["handler"]
        extract_mod = import_module("handler")

        extract_input = {
            "message_id": classify_result["message_id"],
            "case_id": classify_result["case_id"],
            "client_id": classify_result["client_id"],
            "classified_attachments": classify_result["classified_attachments"],
        }
        extract_result = extract_mod.handler(extract_input, None)
        print_result(extract_result)

        # --- Step 6: Resume Workflow ---
        divider("Step 6: resume-workflow")
        sys.path.insert(0, os.path.abspath("src/stream4/resume-workflow"))
        if "handler" in sys.modules:
            del sys.modules["handler"]
        resume_mod = import_module("handler")

        resume_input = {
            "message_id": extract_result["message_id"],
            "case_id": extract_result["case_id"],
            "client_id": extract_result["client_id"],
            "sfn_task_token": correlate_result["sfn_task_token"],
            "extracted_attachments": extract_result["extracted_attachments"],
        }
        resume_result = resume_mod.handler(resume_input, None)
        print_result(resume_result)

    # --- Summary ---
    divider("PIPELINE SUMMARY")
    print(f"  Email from:        {receive_result['sender']}")
    print(f"  Subject:           {receive_result['subject']}")
    print(f"  Attachments found: {len(receive_result['attachments'])}")
    print(f"  Correlation:       {correlate_result['correlation_status']} -> case {correlate_result['case_id']}")
    print(f"  Safety gate:       {len(safety_result['safe_attachments'])} safe, {len(safety_result['quarantined_attachments'])} quarantined")
    for i, att in enumerate(classify_result.get("classified_attachments", [])):
        print(f"  Classification[{i}]: {att['classification']} (confidence: {att['classification_confidence']})")
    for i, att in enumerate(extract_result.get("extracted_attachments", [])):
        print(f"  Extraction[{i}]:     {len(att.get('extracted_fields', {}))} fields (confidence: {att['extraction_confidence']})")
    print(f"  Final action:      {resume_result['action_taken']}")
    print()


if __name__ == "__main__":
    main()
