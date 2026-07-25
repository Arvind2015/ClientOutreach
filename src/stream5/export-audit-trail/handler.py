"""
Stream 5 — Audit Trail Export (Task 6.8 / 8.4)

Generates a case-scoped audit trail export (CSV) on demand.
Reads all AuditEvent records for the given case_id and writes
the CSV to S3, returning a pre-signed URL for download.

Inputs:
  - case_id: str
  - format: "csv" (default) | "json"

Outputs:
  - s3_key: str        # where the export was written
  - download_url: str  # pre-signed URL valid for 1 hour
"""

import os
import csv
import io
import json
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")

audit_table = dynamodb.Table(os.environ["AUDIT_TABLE"])
DOCUMENTS_BUCKET = os.environ["DOCUMENTS_BUCKET"]
PRESIGNED_URL_EXPIRY = 3600  # 1 hour


def handler(event, context):
    case_id = event["case_id"]
    export_format = event.get("format", "csv")

    # Fetch all audit events for this case
    events = _fetch_audit_events(case_id)

    if export_format == "json":
        content, content_type, extension = _to_json(events), "application/json", "json"
    else:
        content, content_type, extension = _to_csv(events), "text/csv", "csv"

    # Write to S3
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    s3_key = f"audit-exports/{case_id}/audit-trail-{timestamp}.{extension}"

    s3.put_object(
        Bucket=DOCUMENTS_BUCKET,
        Key=s3_key,
        Body=content.encode("utf-8"),
        ContentType=content_type,
    )

    # Generate pre-signed download URL
    download_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": DOCUMENTS_BUCKET, "Key": s3_key},
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )

    emit_audit_event(case_id, actor="export-audit-trail",
                     action="AUDIT_TRAIL_EXPORTED", output_ref=s3_key)

    return {"case_id": case_id, "s3_key": s3_key, "download_url": download_url}


def _fetch_audit_events(case_id):
    """Query all AuditEvent records for the case, sorted by timestamp."""
    # TODO: update KeyConditionExpression to match actual AuditEvents table schema
    response = audit_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("case_id").eq(case_id)
    )
    items = response.get("Items", [])
    return sorted(items, key=lambda x: x.get("timestamp", ""))


def _to_csv(events):
    if not events:
        return "event_id,case_id,actor,action,timestamp,input_ref,output_ref\n"
    fieldnames = ["event_id", "case_id", "actor", "action",
                  "timestamp", "input_ref", "output_ref"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(events)
    return output.getvalue()


def _to_json(events):
    return json.dumps(events, default=str, indent=2)
