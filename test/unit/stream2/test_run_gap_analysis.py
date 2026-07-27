"""
Unit tests for src/stream2/run-gap-analysis (Task 3.5).

Covers rule resolution, DEFAULT_BASELINE fallback behavior, and gap-matching
edge cases (expired doc, partial/incomplete field, no gaps).
"""

import os
import sys
import json
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from _helpers import load_handler_module, FakeTable

os.environ["CHECKLIST_RULES_TABLE"] = "ChecklistRules"
os.environ["CASES_TABLE"] = "Cases"
os.environ["AUDIT_EVENT_BUS_NAME"] = "kyc-outreach-audit"

FIXTURES_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "fixtures", "stream2", "kyc_profiles.json"
))

RULE_CORPORATE_UK_HIGH = {
    "client_type": "CORPORATE",
    "rule_key": "UK#HIGH",
    "rule_id": "rule-corporate-uk-high",
    "version": 1,
    "required": [
        {"requirement_type": "CERTIFICATE_OF_INCORPORATION", "validity_window_days": 1825, "mandatory": True},
        {"requirement_type": "PROOF_OF_ADDRESS", "validity_window_days": 90, "mandatory": True},
        {"requirement_type": "BENEFICIAL_OWNERSHIP_DECLARATION", "validity_window_days": 365, "mandatory": True},
    ],
}

RULE_CORPORATE_UK_MEDIUM = {
    "client_type": "CORPORATE",
    "rule_key": "UK#MEDIUM",
    "rule_id": "rule-corporate-uk-medium",
    "version": 1,
    "required": [
        {"requirement_type": "CERTIFICATE_OF_INCORPORATION", "validity_window_days": 1825, "mandatory": True},
    ],
}

RULE_INDIVIDUAL_UK_LOW = {
    "client_type": "INDIVIDUAL",
    "rule_key": "UK#LOW",
    "rule_id": "rule-individual-uk-low",
    "version": 1,
    "required": [
        {"requirement_type": "PASSPORT", "validity_window_days": 3650, "mandatory": True},
        {"requirement_type": "REGISTERED_NAME", "validity_window_days": 3650, "mandatory": True},
    ],
}

RULE_DEFAULT_BASELINE = {
    "client_type": "DEFAULT_BASELINE",
    "rule_key": "DEFAULT_BASELINE#DEFAULT_BASELINE",
    "rule_id": "rule-default-baseline",
    "version": 1,
    "required": [
        {"requirement_type": "PROOF_OF_IDENTITY", "validity_window_days": 3650, "mandatory": True},
    ],
}


def _load_fixture(name):
    with open(FIXTURES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)[name]


def _make_module(rules):
    fake_rules_table = FakeTable(key_fields=("client_type", "rule_key"))
    fake_cases_table = FakeTable(key_fields=("case_id",))
    for rule in rules:
        fake_rules_table.put_item(Item=rule)

    with patch("boto3.resource") as mock_resource:
        tables = {"ChecklistRules": fake_rules_table, "Cases": fake_cases_table}
        mock_resource.return_value.Table.side_effect = lambda name: tables[name]
        module = load_handler_module("stream2_run_gap_analysis", "run-gap-analysis")

    module.emit_audit_event = lambda *a, **k: "test-event-id"
    return module, fake_rules_table, fake_cases_table


class RunGapAnalysisTests(unittest.TestCase):
    def test_no_gaps_when_all_requirements_satisfied(self):
        module, _, _ = _make_module([RULE_CORPORATE_UK_HIGH])
        profile = _load_fixture("complete_corporate")

        result = module.handler(
            {"case_id": "case-1", "client_id": profile["client_id"], "kyc_profile": profile}, None
        )

        self.assertFalse(result["has_gaps"])
        self.assertEqual(result["outstanding"], [])

    def test_expired_document_is_treated_as_missing(self):
        module, _, _ = _make_module([RULE_CORPORATE_UK_MEDIUM])
        profile = _load_fixture("expired_document_corporate")

        result = module.handler(
            {"case_id": "case-2", "client_id": profile["client_id"], "kyc_profile": profile}, None
        )

        self.assertTrue(result["has_gaps"])
        self.assertEqual(result["outstanding"], [
            {"requirement_type": "CERTIFICATE_OF_INCORPORATION", "reason": "EXPIRED"}
        ])

    def test_missing_document_and_field_reported(self):
        module, _, _ = _make_module([RULE_INDIVIDUAL_UK_LOW])
        profile = _load_fixture("missing_document_individual")

        result = module.handler(
            {"case_id": "case-3", "client_id": profile["client_id"], "kyc_profile": profile}, None
        )

        self.assertTrue(result["has_gaps"])
        reasons = {o["requirement_type"]: o["reason"] for o in result["outstanding"]}
        self.assertEqual(reasons["PASSPORT"], "MISSING")
        self.assertEqual(reasons["REGISTERED_NAME"], "MISSING")

    def test_incomplete_field_reported_when_value_empty(self):
        module, _, _ = _make_module([RULE_INDIVIDUAL_UK_LOW])
        profile = dict(_load_fixture("missing_document_individual"))
        profile["fields"] = {"REGISTERED_NAME": {"value": "", "source": "test", "updated_at": ""}}

        result = module.handler(
            {"case_id": "case-3b", "client_id": profile["client_id"], "kyc_profile": profile}, None
        )

        reasons = {o["requirement_type"]: o["reason"] for o in result["outstanding"]}
        self.assertEqual(reasons["REGISTERED_NAME"], "INCOMPLETE")

    def test_no_matching_rule_falls_back_to_baseline_and_flags_review(self):
        module, _, cases_table = _make_module([RULE_DEFAULT_BASELINE])
        profile = _load_fixture("unmatched_client_type")

        result = module.handler(
            {"case_id": "case-4", "client_id": profile["client_id"], "kyc_profile": profile}, None
        )

        self.assertTrue(result["has_gaps"])
        self.assertEqual(result["outstanding"], [
            {"requirement_type": "PROOF_OF_IDENTITY", "reason": "MISSING"}
        ])
        case_item = cases_table.get_item(Key={"case_id": "case-4"})["Item"]
        self.assertIn("NEEDS_RULE_REVIEW", case_item["risk_flags"])

    def test_no_matching_rule_and_no_baseline_raises(self):
        module, _, _ = _make_module([])
        profile = _load_fixture("unmatched_client_type")

        with self.assertRaises(module.ChecklistRuleNotFoundError):
            module.handler(
                {"case_id": "case-5", "client_id": profile["client_id"], "kyc_profile": profile}, None
            )

    def test_handles_wrapped_kyc_profile_from_state_machine_result_path(self):
        module, _, _ = _make_module([RULE_CORPORATE_UK_HIGH])
        profile = _load_fixture("complete_corporate")

        # State machine's ResultSelector wraps the payload as {"kyc_profile": {...}}
        result = module.handler(
            {"case_id": "case-6", "client_id": profile["client_id"],
             "kyc_profile": {"kyc_profile": profile}}, None
        )

        self.assertFalse(result["has_gaps"])


if __name__ == "__main__":
    unittest.main()
