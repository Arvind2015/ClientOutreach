"""
Stream 2 — KYC Retrieval Agent (Tasks 2.1-2.4)

Adapter/tool for the Case Orchestrator's RetrieveKycProfile state. Fetches a
client's KYC profile from the KYC system of record, normalizes it into the
canonical KycProfile schema, and caches it in DynamoDB with a 24h TTL so
repeated invocations within a case lifecycle don't re-hit the source system.

The identity/API contract of the real KYC system of record is not yet
finalised (design.md Open Item #1), so `_fetch_from_kyc_source` is a stub per
task 2.1's explicit allowance ("mock/stub interface first if source system
access is pending"). Swap that function's body for the real adapter call once
the source system is confirmed — everything else (normalization, caching,
retry/escalation) is the real implementation.

Inputs (from Step Functions RetrieveKycProfile state):
  - case_id: str
  - client_id: str

Output: a flat dict matching the canonical KycProfile schema (see
src/shared/common-layer/models.py).

On unrecoverable KYC source failure, raises KycSourceUnavailableError so the
state machine's Catch block routes to escalation (Req 1.2) — this Lambda does
not call the escalation handler directly.
"""

import os
import time
import boto3
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/opt/python")  # Lambda layer path
from audit import emit_audit_event

dynamodb = boto3.resource("dynamodb")
cache_table = dynamodb.Table(os.environ["KYC_PROFILE_CACHE_TABLE"])

CACHE_TTL_SECONDS = int(os.environ.get("KYC_PROFILE_CACHE_TTL_SECONDS", str(24 * 3600)))
MAX_RETRIES = int(os.environ.get("KYC_SOURCE_MAX_RETRIES", "3"))
RETRY_BACKOFF_SECONDS = float(os.environ.get("KYC_SOURCE_RETRY_BACKOFF_SECONDS", "1"))


class KycSourceUnavailableError(Exception):
    """Raised when the KYC system of record can't be reached after retries (Req 1.2)."""


def handler(event, context):
    case_id = event["case_id"]
    client_id = event["client_id"]

    cached = _get_cached_profile(client_id)
    if cached is not None:
        emit_audit_event(case_id, actor="get-kyc-profile", action="KYC_PROFILE_CACHE_HIT")
        return cached

    try:
        raw_profile = _fetch_from_kyc_source_with_retry(client_id)
    except KycSourceUnavailableError:
        emit_audit_event(case_id, actor="get-kyc-profile", action="KYC_PROFILE_RETRIEVAL_FAILED")
        raise

    profile = _normalize(client_id, raw_profile)
    _write_cache(client_id, profile)
    emit_audit_event(case_id, actor="get-kyc-profile", action="KYC_PROFILE_RETRIEVED")
    return profile


def _get_cached_profile(client_id):
    response = cache_table.get_item(Key={"client_id": client_id})
    item = response.get("Item")
    if not item:
        return None
    # Belt-and-braces freshness check: DynamoDB's TTL deletion is asynchronous
    # (can lag up to 48h), so don't trust a stale item just because it's still there.
    if item.get("ttl", 0) < int(time.time()):
        return None
    return item.get("profile")


def _write_cache(client_id, profile):
    expires_at = int(time.time()) + CACHE_TTL_SECONDS
    cache_table.put_item(Item={
        "client_id": client_id,
        "profile": profile,
        "ttl": expires_at,
    })


def _fetch_from_kyc_source_with_retry(client_id):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _fetch_from_kyc_source(client_id)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise KycSourceUnavailableError(
        f"KYC system of record unavailable for client {client_id} "
        f"after {MAX_RETRIES} attempts: {last_error}"
    )


def _fetch_from_kyc_source(client_id):
    """
    Adapter call to the KYC system of record. Stubbed pending confirmation of
    the real source system (design.md Open Item #1) — returns synthetic data
    so normalization, caching, and the Matching Engine can be built and tested
    against a realistic shape now.
    """
    # TODO: replace with the real KYC system of record adapter call
    return {
        "client_type": "CORPORATE",
        "jurisdiction": "UK",
        "risk_rating": "MEDIUM",
        "fields": {
            "registered_name": {
                "value": "Acme Corp Ltd",
                "source": "kyc-source",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        },
        "documents": [],
        "preferred_language": "en",
        "preferred_channel": "EMAIL",
    }


def _normalize(client_id, raw):
    """Normalize the raw source response into the canonical KycProfile schema (Req 1.3)."""
    return {
        "client_id": client_id,
        "client_type": raw.get("client_type", "UNKNOWN"),
        "jurisdiction": raw.get("jurisdiction", "UNKNOWN"),
        "risk_rating": raw.get("risk_rating", "UNKNOWN"),
        "fields": raw.get("fields", {}),
        "documents": raw.get("documents", []),
        "preferred_language": raw.get("preferred_language", "en"),
        "preferred_channel": raw.get("preferred_channel", "EMAIL"),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
