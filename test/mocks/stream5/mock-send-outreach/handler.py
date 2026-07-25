"""
Mock — Send Outreach Email (stub for Stream 3 dependency)

Simulates a successful SES send without actually sending anything.
"""

from datetime import datetime, timezone


def handler(event, context):
    return {
        "case_id": event.get("case_id", "mock-case-001"),
        "email_id": event.get("outreach", {}).get("email_id", "mock-email-001"),
        "delivery_status": "SENT",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "_mock": True,
    }
