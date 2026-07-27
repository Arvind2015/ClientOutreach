"""
Unit tests for src/stream2/get-kyc-profile (Task 2.5).

Covers retrieval success, cache hit/miss, and failure escalation paths.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from _helpers import load_handler_module, FakeTable

os.environ["KYC_PROFILE_CACHE_TABLE"] = "KycProfileCache"
os.environ["AUDIT_EVENT_BUS_NAME"] = "kyc-outreach-audit"


def _make_module():
    fake_cache_table = FakeTable(key_fields=("client_id",))

    with patch("boto3.resource") as mock_resource:
        mock_resource.return_value.Table.return_value = fake_cache_table
        module = load_handler_module("stream2_get_kyc_profile", "get-kyc-profile")

    module.emit_audit_event = lambda *a, **k: "test-event-id"
    return module, fake_cache_table


class GetKycProfileTests(unittest.TestCase):
    def setUp(self):
        self.module, self.cache_table = _make_module()

    def test_retrieval_success_normalizes_and_caches(self):
        result = self.module.handler({"case_id": "case-1", "client_id": "client-1"}, None)

        self.assertEqual(result["client_id"], "client-1")
        self.assertEqual(result["client_type"], "CORPORATE")
        self.assertIn("retrieved_at", result)
        cached = self.cache_table.get_item(Key={"client_id": "client-1"})["Item"]
        self.assertEqual(cached["profile"]["client_id"], "client-1")

    def test_cache_hit_skips_source_fetch(self):
        self.module._fetch_from_kyc_source = unittest.mock.Mock(
            side_effect=AssertionError("should not be called on cache hit")
        )
        self.cache_table.put_item(Item={
            "client_id": "client-2",
            "profile": {"client_id": "client-2", "client_type": "INDIVIDUAL"},
            "ttl": int(time.time()) + 3600,
        })

        result = self.module.handler({"case_id": "case-2", "client_id": "client-2"}, None)

        self.assertEqual(result["client_type"], "INDIVIDUAL")

    def test_expired_cache_entry_is_ignored(self):
        self.cache_table.put_item(Item={
            "client_id": "client-3",
            "profile": {"client_id": "client-3", "client_type": "STALE"},
            "ttl": int(time.time()) - 10,  # already expired
        })

        result = self.module.handler({"case_id": "case-3", "client_id": "client-3"}, None)

        # Falls through to the (stubbed) source fetch, not the stale cache entry
        self.assertEqual(result["client_type"], "CORPORATE")

    def test_failure_escalation_raises_after_retries(self):
        self.module.MAX_RETRIES = 2
        self.module.RETRY_BACKOFF_SECONDS = 0
        self.module._fetch_from_kyc_source = unittest.mock.Mock(
            side_effect=Exception("source down")
        )

        with self.assertRaises(self.module.KycSourceUnavailableError):
            self.module.handler({"case_id": "case-4", "client_id": "client-4"}, None)

        self.assertEqual(self.module._fetch_from_kyc_source.call_count, 2)


if __name__ == "__main__":
    unittest.main()
