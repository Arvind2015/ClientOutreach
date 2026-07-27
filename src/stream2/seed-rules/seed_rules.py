"""
Stream 2 — ChecklistRules versioned write path (Task 3.1)

Admin script: reads checklist rules from the versioned source file
(checklist-rules.json, in this same folder) and writes them to the
ChecklistRules DynamoDB table, auto-incrementing `version` per rule and
setting `updated_by`/`updated_at` on every write (Req 2.2).

This is the SOLE supported mechanism for loading/updating checklist rules in
v1 — no direct table edits (see team-task-breakdown.md Stream 2 runbook and
src/stream2/README.md).

Usage:
    python seed_rules.py --updated-by "person.b@bank.example"
    python seed_rules.py --updated-by "person.b@bank.example" --source my-rules.json --table ChecklistRules --region eu-central-1

Runbook:
    1. Edit checklist-rules.json (this folder) with the new/changed rule(s).
    2. Run this script.
    3. Verify the write via a dry-run query, e.g.:
         aws dynamodb get-item --table-name ChecklistRules --region eu-central-1 \
           --key "{\\"client_type\\": {\\"S\\": \\"CORPORATE\\"}, \\"rule_key\\": {\\"S\\": \\"UK#HIGH\\"}}"
    4. Confirm the change with the Compliance Owner before it's relied on for live outreach.
"""

import argparse
import json
import os
from datetime import datetime, timezone

import boto3


def _rule_key(jurisdiction, risk_rating):
    return f"{jurisdiction}#{risk_rating}"


def _load_rules(source_path):
    with open(source_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _next_version(table, client_type, rule_key):
    response = table.get_item(Key={"client_type": client_type, "rule_key": rule_key})
    existing = response.get("Item")
    return (existing.get("version", 0) + 1) if existing else 1


def seed_rules(source_path, updated_by, table_name, region=None):
    dynamodb = boto3.resource("dynamodb", region_name=region) if region else boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    rules = _load_rules(source_path)
    now = datetime.now(timezone.utc).isoformat()
    written = []

    for rule in rules:
        client_type = rule["client_type"]
        jurisdiction = rule["jurisdiction"]
        risk_rating = rule["risk_rating"]
        rule_key = _rule_key(jurisdiction, risk_rating)
        version = _next_version(table, client_type, rule_key)

        item = {
            "client_type": client_type,
            "rule_key": rule_key,
            "rule_id": rule["rule_id"],
            "version": version,
            "jurisdiction": jurisdiction,
            "risk_rating": risk_rating,
            "required": rule["required"],
            "updated_by": updated_by,
            "updated_at": now,
        }
        table.put_item(Item=item)
        written.append({"client_type": client_type, "rule_key": rule_key, "version": version})
        print(f"Wrote {client_type} / {rule_key} (version {version})")

    return written


def main():
    parser = argparse.ArgumentParser(
        description="Seed/update the ChecklistRules table from a versioned source file."
    )
    parser.add_argument(
        "--source",
        default=os.path.join(os.path.dirname(__file__), "checklist-rules.json"),
        help="Path to the versioned checklist rules JSON file",
    )
    parser.add_argument(
        "--updated-by", required=True,
        help="Identity of the person running this update (recorded on every rule for audit)",
    )
    parser.add_argument("--table", default=os.environ.get("CHECKLIST_RULES_TABLE", "ChecklistRules"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION"))
    args = parser.parse_args()

    seed_rules(args.source, args.updated_by, args.table, args.region)


if __name__ == "__main__":
    main()
