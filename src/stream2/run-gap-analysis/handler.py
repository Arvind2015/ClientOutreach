"""
Stream 2 — Checklist Rules Engine and Matching Engine (Tasks 3.1-3.4)

Resolves the applicable ChecklistRule for a client (by client_type,
jurisdiction, risk_rating), falling back to a DEFAULT_BASELINE ruleset and
flagging the case NEEDS_RULE_REVIEW when nothing matches (Req 2.3). Then
diffs the resolved checklist against the client's KycProfile to produce a
GapAnalysisResult, treating expired documents as missing (Req 3.2).

ChecklistRules table key convention (see src/stream2/README.md):
  - client_type (HASH)
  - rule_key (RANGE) = "{jurisdiction}#{risk_rating}"
  - DEFAULT_BASELINE sentinel: client_type="DEFAULT_BASELINE",
    rule_key="DEFAULT_BASELINE#DEFAULT_BASELINE"

Task 3.4 (auto-close when no outstanding requirements) is enacted by the
Case Orchestrator's CheckForGaps state, not here — this Lambda's only
responsibility toward 3.4 is reporting `has_gaps` correctly.

Inputs (from Step Functions RunGapAnalysis state):
  - case_id: str
  - client_id: str
  - kyc_profile: the wrapped result of the RetrieveKycProfile state, i.e.
    {"kyc_profile": <KycProfile dict>} per the state machine's
    ResultSelector/ResultPath chaining.

Output: a flat dict matching the canonical GapAnalysisResult schema (see
src/shared/common-layer/models.py).
"""

import os
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

dynamodb = boto3.resource("dynamodb")
checklist_rules_table = dynamodb.Table(os.environ["CHECKLIST_RULES_TABLE"])
cases_table = dynamodb.Table(os.environ["CASES_TABLE"])

DEFAULT_BASELINE = "DEFAULT_BASELINE"


class ChecklistRuleNotFoundError(Exception):
    """Raised when neither a specific rule nor the DEFAULT_BASELINE rule exists."""


def handler(event, context):
    case_id = event["case_id"]
    client_id = event["client_id"]
    kyc_profile = _extract_kyc_profile(event)

    client_type = kyc_profile.get("client_type", "UNKNOWN")
    jurisdiction = kyc_profile.get("jurisdiction", "UNKNOWN")
    risk_rating = kyc_profile.get("risk_rating", "UNKNOWN")

    rule, is_baseline = _resolve_checklist_rule(client_type, jurisdiction, risk_rating)
    if is_baseline:
        _flag_needs_rule_review(case_id)
        emit_audit_event(case_id, actor="run-gap-analysis", action="NEEDS_RULE_REVIEW_FLAGGED")

    outstanding = _compute_gaps(kyc_profile, rule)
    has_gaps = len(outstanding) > 0

    emit_audit_event(
        case_id, actor="run-gap-analysis",
        action="GAP_ANALYSIS_COMPLETED" if has_gaps else "GAP_ANALYSIS_NO_GAPS",
    )

    return {
        "case_id": case_id,
        "client_id": client_id,
        "has_gaps": has_gaps,
        "outstanding": outstanding,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _extract_kyc_profile(event):
    kyc_profile = event.get("kyc_profile")
    if isinstance(kyc_profile, dict) and "kyc_profile" in kyc_profile:
        return kyc_profile["kyc_profile"]
    return kyc_profile or {}


def _rule_key(jurisdiction, risk_rating):
    return f"{jurisdiction}#{risk_rating}"


def _resolve_checklist_rule(client_type, jurisdiction, risk_rating):
    response = checklist_rules_table.get_item(
        Key={"client_type": client_type, "rule_key": _rule_key(jurisdiction, risk_rating)}
    )
    item = response.get("Item")
    if item:
        return item, False

    baseline_response = checklist_rules_table.get_item(
        Key={"client_type": DEFAULT_BASELINE, "rule_key": _rule_key(DEFAULT_BASELINE, DEFAULT_BASELINE)}
    )
    baseline_item = baseline_response.get("Item")
    if not baseline_item:
        raise ChecklistRuleNotFoundError(
            f"No checklist rule for ({client_type}, {jurisdiction}, {risk_rating}) "
            f"and no {DEFAULT_BASELINE} rule is configured"
        )
    return baseline_item, True


def _flag_needs_rule_review(case_id):
    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression=(
            "SET risk_flags = list_append(if_not_exists(risk_flags, :empty), :flag), "
            "updated_at = :ts"
        ),
        ExpressionAttributeValues={
            ":empty": [],
            ":flag": ["NEEDS_RULE_REVIEW"],
            ":ts": datetime.now(timezone.utc).isoformat(),
        },
    )


def _compute_gaps(kyc_profile, rule):
    """
    Matching Engine (Task 3.3): diffs KycProfile.documents/fields against the
    resolved checklist's required list. A requirement is satisfied by either
    a valid (non-expired) document of that type, or a non-empty field of that
    name — documents are checked first since most requirement_types are
    document-shaped.
    """
    required_specs = rule.get("required", [])
    fields = kyc_profile.get("fields", {}) or {}
    documents = kyc_profile.get("documents", []) or []

    docs_by_type = {}
    for doc in documents:
        docs_by_type.setdefault(doc["doc_type"], []).append(doc)

    now = datetime.now(timezone.utc)
    outstanding = []

    for spec in required_specs:
        req_type = spec["requirement_type"]
        if not spec.get("mandatory", True):
            continue

        matching_docs = docs_by_type.get(req_type)
        if matching_docs:
            if _has_valid_document(matching_docs, now):
                continue
            outstanding.append({"requirement_type": req_type, "reason": "EXPIRED"})
            continue

        if req_type in fields:
            if fields[req_type].get("value"):
                continue
            outstanding.append({"requirement_type": req_type, "reason": "INCOMPLETE"})
            continue

        outstanding.append({"requirement_type": req_type, "reason": "MISSING"})

    return outstanding


def _has_valid_document(docs, now):
    for doc in docs:
        expires_at = doc.get("expires_at")
        if not expires_at:
            return True  # no expiry recorded = treated as perpetually valid
        try:
            expiry_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        if expiry_dt > now:
            return True
    return False
