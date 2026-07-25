"""
Mock — KYC Profile Retrieval (stub for Stream 2 dependency)

Returns a synthetic KYC profile with one expired document and one missing field
so Stream 5 integration tests have a realistic gap to work with.
"""

from datetime import datetime, timezone


def handler(event, context):
    return {
        "client_id": event.get("client_id", "mock-client-001"),
        "client_type": "CORPORATE",
        "jurisdiction": "UK",
        "risk_rating": "MEDIUM",
        "fields": {
            "registered_name": {"value": "Acme Corp Ltd", "source": "mock"},
            "registration_number": {"value": "12345678", "source": "mock"},
        },
        "documents": [
            {
                "doc_type": "CERTIFICATE_OF_INCORPORATION",
                "doc_id": "doc-001",
                "issued_at": "2020-01-01",
                "expires_at": "2023-01-01",  # expired
                "s3_ref": "s3://mock/doc-001.pdf",
            }
        ],
        "preferred_language": "en",
        "preferred_channel": "EMAIL",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "_mock": True,
    }
