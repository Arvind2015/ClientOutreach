"""
Mock — Outreach Drafting Agent (stub for Stream 3 dependency)

Returns a synthetic drafted email with AUTO_SEND dispatch mode.
"""


def handler(event, context):
    return {
        "case_id": event.get("case_id", "mock-case-001"),
        "email_id": "mock-email-001",
        "subject": "[Mock] KYC Information Required — Case mock-case-001",
        "rendered_body_ref": "s3://mock/outreach-emails/mock-case-001/mock-email-001.html",
        "dispatch_mode": "AUTO_SEND",
        "case_ref_token": "CASEREF-mock-case-001",
        "_mock": True,
    }
