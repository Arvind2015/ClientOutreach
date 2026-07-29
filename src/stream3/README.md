# Stream 3 -- Outreach Generation & Sending

Implements Task 4 (Outreach Drafting Agent and dispatch pipeline) from
`.kiro/specs/client-outreach-agent/tasks.md`.

## Functions

| Folder | Purpose | Tasks |
|---|---|---|
| `draft-outreach-email/` | Select template, render with case variables, classify AUTO_SEND/NEEDS_APPROVAL | 4.1-4.5, 4.8 |
| `send-outreach-email/` | Send via SES, track delivery status | 4.6 |
| `handle-approval-action/` | Process analyst approve/edit/reject from SQS queue, resume state machine | 4.7 |
| `templates/` | Approved email templates (JSON with variable slots) | 4.1 |

## Environment Variables

### draft-outreach-email
- `CASES_TABLE` -- DynamoDB Cases table name
- `DOCUMENTS_BUCKET` -- S3 bucket for rendered email storage
- `TEMPLATES_BUCKET` -- S3 bucket where templates live (defaults to deploy bucket)
- `TEMPLATES_PREFIX` -- S3 prefix for templates (default: `stream3/templates/`)
- `MIN_RECONTACT_INTERVAL_DAYS` -- Minimum days between contacts (default: 7)
- `AUTO_SEND_MAX_RISK` -- Maximum risk rating for auto-send (default: MEDIUM)
- `AUTO_SEND_MAX_FOLLOW_UP_COUNT` -- Max follow-ups before requiring approval (default: 2)
- `AUDIT_EVENT_BUS_NAME` -- EventBridge audit bus name

### send-outreach-email
- `CASES_TABLE` -- DynamoDB Cases table name
- `DOCUMENTS_BUCKET` -- S3 bucket for rendered email retrieval
- `SENDER_EMAIL` -- Verified SES sender identity
- `AUDIT_EVENT_BUS_NAME` -- EventBridge audit bus name

### handle-approval-action
- `CASES_TABLE` -- DynamoDB Cases table name
- `DOCUMENTS_BUCKET` -- S3 bucket for edited email storage
- `AUDIT_EVENT_BUS_NAME` -- EventBridge audit bus name

## Templates

Templates use `{{variable_name}}` placeholder syntax. Available variables:
- `{{client_name}}` -- Client's display name
- `{{case_ref}}` -- Unique case reference (e.g., CASEREF-A1B2C3D4)
- `{{requirements_list}}` -- Formatted list of outstanding items
- `{{requirements_count}}` -- Number of outstanding items
- `{{deadline_days}}` -- Days until expected response
- `{{bank_name}}` -- Bank/team name for sign-off
- `{{submission_instructions}}` -- How to submit documents
- `{{follow_up_count}}` -- Current follow-up cycle number

### Template compliance status

All templates have `compliance_status: PENDING_SIGNOFF`. Per the spec,
AUTO_SEND is not enabled until templates receive written sign-off from the
Compliance Owner (hard gate on task 10.2). Until then, all outreach runs
in NEEDS_APPROVAL mode regardless of the standard-case classifier output.

## Dispatch Mode Logic (Deterministic)

AUTO_SEND requires ALL of:
1. Risk rating <= configured max (default: MEDIUM)
2. Follow-up count <= configured max (default: 2)
3. No risk flags requiring review (NEEDS_RULE_REVIEW, NEEDS_ANALYST_REVIEW, HIGH_RISK_CLIENT)

Otherwise: NEEDS_APPROVAL (routed to analyst queue).
