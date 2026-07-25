"""
Audit event helper — used by all stream components to emit structured
audit events to the EventBridge audit bus.

Usage:
    from audit import emit_audit_event

    emit_audit_event(
        case_id="case-123",
        actor="validate-and-update",
        action="VALIDATION_PASSED",
        input_ref="s3://docs/case-123/att-001.pdf",
        output_ref=None,
    )
"""

import os
import uuid
import boto3
import json
from datetime import datetime, timezone

events_client = boto3.client("events")

EVENT_BUS_NAME = os.environ.get("AUDIT_EVENT_BUS_NAME", "kyc-outreach-audit")
EVENT_SOURCE   = "kyc.outreach.agent"
DETAIL_TYPE    = "AuditEvent"


def emit_audit_event(case_id: str, actor: str, action: str,
                     input_ref: str = None, output_ref: str = None) -> str:
    """
    Emit a structured audit event to the EventBridge audit bus.

    Returns the event_id for reference.
    Logs a warning and continues if the publish fails — audit failure must
    never block the main case flow.
    """
    event_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    detail = {
        "event_id":   event_id,
        "case_id":    case_id,
        "actor":      actor,
        "action":     action,
        "timestamp":  timestamp,
        "input_ref":  input_ref,
        "output_ref": output_ref,
    }

    try:
        events_client.put_events(
            Entries=[
                {
                    "Source":       EVENT_SOURCE,
                    "DetailType":   DETAIL_TYPE,
                    "Detail":       json.dumps(detail),
                    "EventBusName": EVENT_BUS_NAME,
                }
            ]
        )
    except Exception as e:
        # Non-fatal — log but do not raise
        print(f"[AUDIT WARNING] Failed to emit audit event for case {case_id}: {e}")

    return event_id
