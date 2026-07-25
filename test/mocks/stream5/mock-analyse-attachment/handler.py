"""
Mock — Inbound Analysis Agent (stub for Stream 4 dependency)

Returns a synthetic inbound analysis result: one attachment classified with
high confidence as a Certificate of Incorporation, fields extracted.
"""


def handler(event, context):
    return {
        "case_id": event.get("case_id", "mock-case-001"),
        "message_id": "mock-message-001",
        "correlation_status": "MATCHED",
        "attachments": [
            {
                "attachment_id": "att-001",
                "s3_ref": "s3://mock/attachments/mock-case-001/att-001.pdf",
                "classification": "CERTIFICATE_OF_INCORPORATION",
                "classification_confidence": 0.95,
                "extracted_fields": {
                    "registered_name": "Acme Corp Ltd",
                    "registration_number": "12345678",
                    "issued_at": "2026-01-01",
                    "expires_at": "2031-01-01",
                },
                "extraction_confidence": 0.92,
                "validation_result": None,  # set by validate-and-update
            }
        ],
        "_mock": True,
    }
