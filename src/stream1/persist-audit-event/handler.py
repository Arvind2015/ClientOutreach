"""
Stream 1 -- Persist Audit Event (Task 1.3)

Triggered by EventBridge whenever any component calls emit_audit_event()
(src/shared/common-layer/audit.py). Writes the event as a durable record
into the Audit table, so export-audit-trail and any future analyst
dashboard have real data to read instead of an empty table.

Input (EventBridge Lambda target envelope -- only `detail` is used):
  - detail: dict matching emit_audit_event()'s shape:
      {event_id, case_id, actor, action, timestamp, input_ref, output_ref}

Output:
  - {status, case_id, event_id}
"""

import os
import boto3

dynamodb = boto3.resource("dynamodb")
audit_table = dynamodb.Table(os.environ["AUDIT_TABLE"])


def handler(event, context):
    detail = event["detail"]

    item = {
        "case_id": detail["case_id"],
        "event_id": detail["event_id"],
        "actor": detail["actor"],
        "action": detail["action"],
        "timestamp": detail["timestamp"],
    }
    if detail.get("input_ref") is not None:
        item["input_ref"] = detail["input_ref"]
    if detail.get("output_ref") is not None:
        item["output_ref"] = detail["output_ref"]

    audit_table.put_item(Item=item)

    return {"status": "persisted", "case_id": item["case_id"], "event_id": item["event_id"]}
