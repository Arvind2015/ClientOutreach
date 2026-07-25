"""
Mock — Gap Analysis / Matching Engine (stub for Stream 2 dependency)

Returns a synthetic gap result with one expired document outstanding.
"""


def handler(event, context):
    return {
        "case_id": event.get("case_id", "mock-case-001"),
        "client_id": event.get("client_id", "mock-client-001"),
        "has_gaps": True,
        "outstanding": [
            {
                "requirement_type": "CERTIFICATE_OF_INCORPORATION",
                "reason": "EXPIRED",
            }
        ],
        "computed_at": "2026-07-25T00:00:00Z",
        "_mock": True,
    }
