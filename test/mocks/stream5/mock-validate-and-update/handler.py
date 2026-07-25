"""
Mock — Validate & Update Agent

Returns a hardcoded PASS result matching the real handler's output shape:
  - overall_status: PASS | PARTIAL | NEEDS_ANALYST_REVIEW
  - validation_results: list of per-attachment outcomes

Used by other streams to test integrations before the real handler is ready.
"""


def handler(event, context):
    inbound_result = event.get("inbound_result", {})
    attachments = inbound_result.get("attachments", [])

    # Return one PASS result per attachment in the input
    validation_results = [
        {
            "attachment_id": att.get("attachment_id", f"mock-att-{i}"),
            "requirement_type": att.get("classification", "UNKNOWN"),
            "status": "PASS",
            "failure_reason": None,
        }
        for i, att in enumerate(attachments)
    ] or [
        {
            "attachment_id": "mock-att-001",
            "requirement_type": "CERTIFICATE_OF_INCORPORATION",
            "status": "PASS",
            "failure_reason": None,
        }
    ]

    return {
        "case_id": event.get("case_id"),
        "overall_status": "PASS",
        "validation_results": validation_results,
        "_mock": True,
    }
