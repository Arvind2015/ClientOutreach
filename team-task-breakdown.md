# Client Outreach Agent — High-Level Task Distribution (Team of 6)

This is the high-level split only, for assigning owners. Detailed step-by-step
implementation plans and scripts will follow separately per stream.

Rough order: Stream 1 should start first since everyone else depends on the
tables/buckets/permissions it creates. Streams 2-6 can then run in parallel.
Stream 5 (orchestration) naturally finishes last since it wires everyone
else's pieces together. Stream 6 (dashboard) can build UI against fake/stub
data while backend streams are still in progress.

## Stream ↔ tasks.md Cross-Reference

Each stream maps to specific numbered tasks in `.kiro/specs/client-outreach-agent/tasks.md`.
Use this table to find the detailed step-by-step sub-tasks for your stream.

| Stream | Owner | tasks.md sections |
|--------|-------|-------------------|
| Stream 1 — Infrastructure & Environment | Person A | Task 1 (1.1, 1.2, 1.3) |
| Stream 2 — KYC Data & Checklist Rules | Person B | Task 2 (2.1–2.5), Task 3 (3.1–3.5) |
| Stream 3 — Outreach Generation & Sending | Person C | Task 4 (4.1–4.8) |
| Stream 4 — Inbound Email & Document Reading | Person D | Task 5 (5.1–5.7), Task 6 (6.1–6.3) |
| Stream 5 — Case Flow & Follow-Up Logic | Person E | Task 6 (6.4–6.8), Task 7 (7.1–7.5) |
| Stream 6 — Analyst Insights View | Person F | Task 8 (8.1–8.5) |
| All streams | Everyone | Tasks 9 (security hardening) and 10 (pilot rollout) |

---

## Stream 1 — Infrastructure & Environment (Owner: Person A)
Everything the rest of the team needs to exist before they can build/test.
- Create DynamoDB tables (ChecklistRules, KycProfiles, Cases)
- Create S3 buckets (documents, templates, raw-emails)
- Set up IAM role/permissions for Lambda to access DynamoDB, S3, Bedrock, SES
- Enable Bedrock model access
- Verify sender email/domain in SES
- Hand off connection details + setup scripts to the rest of the team

## Stream 2 — KYC Data & Checklist Rules (Owner: Person B)
The "what does this client need" logic.
- Define test checklist rules (by client type / jurisdiction / risk rating)
- Build dummy test KYC client profiles (some complete, some missing docs, some expired)
- Build the retrieval function (fetch a client's KYC profile)
- Build the matching/gap-analysis function (compare profile vs checklist, list what's missing)
- **Rule update mechanism (Person B owns delivery; Compliance Owner approves content):**
  - Deliver a `seed_rules.py` admin script (or equivalent CDK/Lambda invoke) that reads checklist rules from a versioned JSON/YAML file in the repo and writes them to the `ChecklistRules` DynamoDB table via the versioned write path (sets `updated_by` / `updated_at` on every write).
  - Document the update runbook in the repo README: edit the source JSON/YAML → run the script → verify via a dry-run query → confirm with Compliance Owner before enabling on live data.
  - This is the sole supported mechanism for loading and updating rules in v1 — no direct table edits. A rule-management UI is deferred (see design.md Open Items).

## Stream 3 — Outreach Generation & Sending (Owner: Person C)
The "ask the customer for it" logic.
- Build a small library of email templates
- Build the drafting logic that fills a template using the AI model, based on what's missing
- Generate and embed a unique case reference in each outgoing email (needed by Stream 4 to match replies back to the case)
- Build the send logic (via SES)
- Build the auto-send vs needs-approval decision, and the approval queue
- Enforce a minimum interval between contacts to the same customer (avoid double-messaging)
- **Template authoring and compliance sign-off (Person C owns delivery; Compliance Owner signs off on content):**
  - Person C authors the initial template set (covering standard outreach, follow-up reminders, and escalation notices) in the approved template format, stored in S3/DynamoDB as per the template library design.
  - Templates must be reviewed and explicitly signed off by the Compliance Owner before any AUTO_SEND path is enabled — this is a hard gate on task 10.2 (pilot rollout).
  - Person C coordinates the review cycle: share draft templates → collect feedback → revise → obtain written sign-off → load into the template library via the same seed/admin script pattern used for checklist rules.
  - Until sign-off is obtained, all outreach runs in NEEDS_APPROVAL mode regardless of case risk rating.

## Stream 4 — Inbound Email & Document Reading (Owner: Person D)
The "read what the customer sent back" logic.
- Build inbound email handling (receive + match to the right case)
- Route replies that can't be matched to any case into a manual triage queue (don't drop/misfile them)
- Build attachment safety checks (file type, size, basic scan)
- Build attachment classification (which document is this) using the AI model
- Build data extraction from the document (OCR/AI) and basic validation
- Flag low-confidence classification/extraction results for analyst review instead of auto-accepting them

## Stream 5 — Case Flow & Follow-Up Logic (Owner: Person E)
The "glue" that ties everything into one process per client.
- Build the case lifecycle (new -> waiting -> follow-up -> closed/escalated)
- Write validated customer-submitted data back to the KYC system of record
- Build the follow-up loop (re-request if still missing something, cap the number of tries)
- Build escalation rules (when something needs a human)
- Build the audit log (record every automated decision), and support exporting a case's audit trail on request

## Stream 6 — Analyst Insights View (Owner: Person F)
A lightweight "human view" into the system — a script, notebook, or simple read-only page is enough; no login/auth system needed for this project. A full production dashboard (SSO, multi-analyst roles) is future work, not part of this build.
- Case list + detail view (status, what's missing, history, why it was escalated)
- Simple approve/edit/reject action for a drafted email (can be the same view/script)
- Basic notifications when a case needs attention
- **Notification channel (v1 — Person F owns wiring):** SNS topic → email subscription to a shared analyst mailbox (e.g., `kyc-outreach-alerts@<bank-domain>`). Every case that transitions to `PENDING_APPROVAL`, `NEEDS_ANALYST_REVIEW`, `ESCALATED`, or `BLOCKED` publishes to this topic. Person F provisions the SNS topic and email subscription as part of their stream (coordinate with Stream 1 for the topic ARN to be created alongside other infrastructure). Per-analyst routing and in-app/browser notifications are deferred to the production dashboard.

---

## Shared final phase (everyone)
- Wire all 6 streams together end-to-end
- Run through test cases together (a client with a gap -> outreach -> reply -> resolution)
- Fix integration issues
- Walkthrough/demo prep
