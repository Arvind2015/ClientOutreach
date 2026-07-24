# Client Outreach Agent — High-Level Task Distribution (Team of 6)

This is the high-level split only, for assigning owners. Detailed step-by-step
implementation plans and scripts will follow separately per stream.

Rough order: Stream 1 should start first since everyone else depends on the
tables/buckets/permissions it creates. Streams 2-6 can then run in parallel.
Stream 5 (orchestration) naturally finishes last since it wires everyone
else's pieces together. Stream 6 (dashboard) can build UI against fake/stub
data while backend streams are still in progress.

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

## Stream 3 — Outreach Generation & Sending (Owner: Person C)
The "ask the customer for it" logic.
- Build a small library of email templates
- Build the drafting logic that fills a template using the AI model, based on what's missing
- Generate and embed a unique case reference in each outgoing email (needed by Stream 4 to match replies back to the case)
- Build the send logic (via SES)
- Build the auto-send vs needs-approval decision, and the approval queue
- Enforce a minimum interval between contacts to the same customer (avoid double-messaging)

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

## Stream 6 — Analyst Dashboard (Owner: Person F)
The "human view" into the system.
- Case list view (status, who's assigned, how old)
- Case detail view (what's missing, history, why it was escalated)
- Approval queue screen (approve/edit/reject a drafted email)
- Basic notifications when a case needs attention

---

## Shared final phase (everyone)
- Wire all 6 streams together end-to-end
- Run through test cases together (a client with a gap -> outreach -> reply -> resolution)
- Fix integration issues
- Walkthrough/demo prep
