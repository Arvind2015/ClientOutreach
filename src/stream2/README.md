# Stream 2 — KYC Data & Checklist Rules

Implements Task 2 (KYC Retrieval Agent) and Task 3 (Checklist Rules Engine +
Matching Engine) from `.kiro/specs/client-outreach-agent/tasks.md`.

## Functions

| Folder | Replaces mock | Tasks |
|---|---|---|
| `get-kyc-profile/` | `test/mocks/stream5/mock-get-kyc-profile` | 2.1–2.4 |
| `run-gap-analysis/` | `test/mocks/stream5/mock-run-gap-analysis` | 3.1–3.4 |
| `seed-rules/` | — (not a Lambda; a local admin script) | 3.1 (write path) |

Once these are deployed, delete the two corresponding mock folders in
`test/mocks/stream5/` per that folder's own disposal instructions.

### get-kyc-profile

Fetches a client's KYC profile, normalizes it into the canonical `KycProfile`
schema, and caches it in `KycProfileCache` (24h TTL, attribute `ttl`, epoch
seconds). The actual KYC system of record integration is stubbed
(`_fetch_from_kyc_source`) pending confirmation of which system that is
(design.md Open Item #1) — task 2.1 explicitly allows this. On unrecoverable
source failure it raises `KycSourceUnavailableError`; the state machine's
`Catch` block (not this Lambda) routes that to the escalation handler.

Env vars: `KYC_PROFILE_CACHE_TABLE`, `AUDIT_EVENT_BUS_NAME`, optionally
`KYC_PROFILE_CACHE_TTL_SECONDS`, `KYC_SOURCE_MAX_RETRIES`,
`KYC_SOURCE_RETRY_BACKOFF_SECONDS`.

### run-gap-analysis

Resolves the applicable `ChecklistRule` and diffs it against the client's
`KycProfile` to produce a `GapAnalysisResult`. Expired documents count as
missing (Req 3.2). If no rule matches, falls back to the `DEFAULT_BASELINE`
rule and flags the case's `risk_flags` with `NEEDS_RULE_REVIEW` (Req 2.3) —
outreach still proceeds against the baseline checklist rather than blocking.

Case auto-close on zero gaps (Task 3.4) is enacted by the Case Orchestrator's
`CheckForGaps` state (already implemented in Stream 5's `state-machine.json`)
— this Lambda's only responsibility is reporting `has_gaps` correctly.

Env vars: `CHECKLIST_RULES_TABLE`, `CASES_TABLE`, `AUDIT_EVENT_BUS_NAME`.

## ChecklistRules table key convention

- **PK** `client_type` (S)
- **SK** `rule_key` (S) = `"{jurisdiction}#{risk_rating}"`
- Baseline sentinel: `client_type="DEFAULT_BASELINE"`,
  `rule_key="DEFAULT_BASELINE#DEFAULT_BASELINE"`

Non-key attributes: `rule_id`, `version`, `jurisdiction`, `risk_rating`,
`required` (list of `{requirement_type, validity_window_days, mandatory}`),
`updated_by`, `updated_at`.

## Updating checklist rules (seed-rules runbook)

No direct table edits — `seed-rules/seed_rules.py` is the only supported
write path in v1 (Person B owns delivery; Compliance Owner approves content):

1. Edit `seed-rules/checklist-rules.json` with the new/changed rule(s).
2. Run `python seed_rules.py --updated-by "<you>"` (see script docstring for
   full args).
3. Verify the write via a dry-run query against the table.
4. Confirm the change with the Compliance Owner before it's relied on for
   live outreach.

`checklist-rules.json` as committed contains **test/sample rules only**,
pending Compliance Owner sign-off — same gate Stream 3 applies to its
template library.
