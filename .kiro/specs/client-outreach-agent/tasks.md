# Implementation Plan

> **Stream mapping:** Each task group below corresponds to one or more streams in `team-task-breakdown.md`.
> Task 1 → Stream 1 | Tasks 2–3 → Stream 2 | Task 4 → Stream 3 | Tasks 5–6 (partial) → Stream 4 |
> Tasks 6 (partial)–7 → Stream 5 | Task 8 → Stream 6 | Tasks 9–10 → All streams.

- [ ] 1. Set up project foundation and shared data model
  - [ ] 1.1 Provision core AWS infrastructure (DynamoDB tables: Cases, ChecklistRules, KycProfileCache; S3 buckets: documents, templates, raw-email; EventBridge bus; SQS approval queue) as IaC (CDK/Terraform)
    - _Requirements: 1.4, 2.1, 10.2_
  - [ ] 1.2 Define canonical data model types/schemas (KycProfile, ChecklistRule, GapAnalysisResult, Case, OutreachEmail, InboundMessage, AuditEvent) as shared code module
    - _Requirements: 1.3_
  - [ ] 1.3 Implement audit event bus + append-only persistence (EventBridge → DynamoDB stream → S3/Glacier) and a helper library for emitting audit events from any component
    - _Requirements: 10.1, 10.2_

- [ ] 2. Build KYC Retrieval Agent
  - [ ] 2.1 Implement `get_kyc_profile` adapter/tool against the KYC system of record (mock/stub interface first if source system access is pending)
    - _Requirements: 1.1_
  - [ ] 2.2 Implement normalization into canonical KycProfile schema
    - _Requirements: 1.3_
  - [ ] 2.3 Implement 24h TTL cache read/write in DynamoDB
    - _Requirements: 1.4_
  - [ ] 2.4 Implement failure handling: retry policy, then case-blocking + analyst notification on exhaustion
    - _Requirements: 1.2_
  - [ ] 2.5 Write unit tests covering retrieval success, cache hit/miss, and failure escalation paths

- [ ] 3. Build Checklist Rules Engine and Matching Engine
  - [ ] 3.1 Design and implement ChecklistRules table schema and versioned write path (create/update with `updated_by`/`updated_at`)
    - _Requirements: 2.1, 2.2, 2.4_
  - [ ] 3.2 Implement rule resolution by (client_type, jurisdiction, risk_rating) with baseline fallback + `NEEDS_RULE_REVIEW` flagging
    - _Requirements: 2.3_
  - [ ] 3.3 Implement Matching Engine: diff KycProfile against resolved checklist, treat expired documents as missing, produce GapAnalysisResult
    - _Requirements: 3.1, 3.2, 3.3_
  - [ ] 3.4 Implement case auto-close path when no outstanding requirements are found
    - _Requirements: 3.4_
  - [ ] 3.5 Write unit tests for rule resolution, fallback behavior, and gap-matching edge cases (expired doc, partial field, no gaps)

- [ ] 4. Build Outreach Drafting Agent and dispatch pipeline
  - [ ] 4.1 Build approved template library (S3/DynamoDB) with variable slots; coordinate compliance sign-off on template content
    - _Requirements: 4.3_
  - [ ] 4.2 Implement `render_template` tool: populate template variables (client name, itemized requirements, deadline, submission instructions) from GapAnalysisResult + KycProfile
    - _Requirements: 4.1, 4.4_
  - [ ] 4.3 Implement unique case reference generation and embedding (subject token + `X-Case-Ref` header)
    - _Requirements: 4.2_
  - [ ] 4.4 Implement deterministic standard-case classifier (risk rating, follow-up count, template match) producing AUTO_SEND / NEEDS_APPROVAL
    - _Requirements: 5.1, 5.2_
  - [ ] 4.5 Implement SES send path for AUTO_SEND, including delivery status tracking (sent/bounced/failed)
    - _Requirements: 5.1, 5.5_
  - [ ] 4.6 Implement SQS approval queue write path for NEEDS_APPROVAL, and approve/reject/edit handling with audit logging of approver identity
    - _Requirements: 5.2, 5.3, 5.4_
  - [ ] 4.7 Implement minimum re-contact interval enforcement per client
    - _Requirements: 12.2_
  - [ ] 4.8 Write unit/integration tests for template rendering, dispatch routing decisions, and approval flow

- [ ] 5. Build Inbound Analysis Agent
  - [ ] 5.1 Configure SES receiving + S3 storage of raw inbound email, triggering Lambda via EventBridge
    - _Requirements: 6.1_
  - [ ] 5.2 Implement case correlation logic (case ref header/subject token/sender match) with ManualTriageQueue fallback
    - _Requirements: 6.2, 6.3_
  - [ ] 5.3 Implement attachment safety gate: file-type allowlist, size limit, malware scan, quarantine path
    - _Requirements: 6.7, 11.4_
  - [ ] 5.4 Implement attachment classification against outstanding requirement types (Bedrock multimodal)
    - _Requirements: 6.4_
  - [ ] 5.5 Implement data/field extraction from classified attachments (OCR/Textract) with confidence scoring
    - _Requirements: 6.5_
  - [ ] 5.6 Implement confidence-threshold gate routing low-confidence items to analyst review
    - _Requirements: 6.6_
  - [ ] 5.6a Store classification and extraction confidence thresholds as runtime-configurable parameters (e.g., SSM Parameter Store or a `Config` DynamoDB table entry), not as code constants. Provide separate threshold keys for classification confidence and extraction confidence so they can be tuned independently during the shadow-mode pilot (task 10.1) without a code deployment.
    - _Requirements: 6.6, 10.1_
  - [ ] 5.7 Write tests using a golden set of sample emails/attachments (valid docs, expired docs, wrong type, poor scan quality, unsupported/malicious file types)

- [ ] 6. Build Validation & Update Agent and follow-up loop
  - [ ] 6.1 Implement deterministic validation of extracted fields against checklist requirement (expiry, name match, completeness)
    - _Requirements: 6.5, 8.1_
  - [ ] 6.2 Implement KYC system-of-record update adapter, retaining original document + structured data
    - _Requirements: 8.1, 8.2_
  - [ ] 6.3 Implement update-failure retry policy and analyst alerting on exhaustion
    - _Requirements: 8.3_
  - [ ] 6.4 Implement re-run of Matching Engine post-update to compute remaining gaps
    - _Requirements: 7.1_
  - [ ] 6.5 Implement follow-up email generation reusing Outreach Drafting Agent, with tightening escalation rules per cycle
    - _Requirements: 7.2_
  - [ ] 6.6 Implement max follow-up cycle enforcement and forced escalation on limit
    - _Requirements: 7.4_
  - [ ] 6.7 Implement case closure on full compliance
    - _Requirements: 3.4, 7.3_
  - [ ] 6.8 Write integration tests for the multi-cycle follow-up loop (partial response → follow-up → resolution; max-cycle escalation)

- [ ] 7. Build Case Orchestrator (Step Functions state machine)
  - [ ] 7.1 Define state machine covering full case lifecycle (NEW → ... → CLOSED/ESCALATED) wiring together Agents from tasks 2–6
    - _Requirements: 1.1, 12.1_
  - [ ] 7.2 Implement EventBridge triggers: scheduled sweep, inbound-mail event, manual analyst trigger
    - _Requirements: 6.1_
  - [ ] 7.3 Implement SLA timers and forced escalation on breach
    - _Requirements: 12.3_
  - [ ] 7.4 Implement uniform escalation handling (status update, escalation_reason, SNS notification) used by all failure/exception paths
    - _Requirements: 12.1_
  - [ ] 7.5 Write end-to-end integration test simulating a full case lifecycle against mocked KYC source and sandbox mailbox

- [ ] 8. Build Analyst Insights View (lightweight — script/notebook/simple read-only page; no auth system for v1)
  - [ ] 8.1 Implement case list + detail view (profile, checklist, gap analysis, outreach history, inbound responses, confidence scores, status, escalation reason), filterable by status and risk rating
    - _Requirements: 9.1, 9.2, 9.4_
  - [ ] 8.2 Implement approve/edit/reject action for queued outreach emails (same lightweight view/script)
    - _Requirements: 5.3, 5.4_
  - [ ] 8.3 Implement analyst notification: provision an SNS topic and subscribe the shared analyst mailbox (e.g., `kyc-outreach-alerts@<bank-domain>`) to it. Publish to this topic whenever a case transitions to `PENDING_APPROVAL`, `NEEDS_ANALYST_REVIEW`, `ESCALATED`, or `BLOCKED`. SNS topic ARN to be created in task 1.1 infrastructure and passed as an environment variable to all publishing components. In-app/browser notifications and per-analyst routing are deferred to future production dashboard work.
    - _Requirements: 9.3_
  - [ ] 8.4 Implement audit trail export (per-case) for review
    - _Requirements: 10.3_
  - [ ] 8.5 (Future / out of v1 scope) Production dashboard: Cognito + bank IdP auth, role-based multi-analyst access, checklist rule management UI
    - _Requirements: 2.2, 2.4, 11.2_

- [ ] 9. Security hardening pass
  - [ ] 9.1 Verify encryption at rest (KMS) and in transit (TLS) across all data stores and integrations
    - _Requirements: 11.1_
  - [ ] 9.2 Apply least-privilege IAM roles per Lambda/agent, review against actual access patterns
    - _Requirements: 11.2_
  - [ ] 9.3 Confirm and document approved Bedrock model boundary for PII workloads with model-risk/compliance
    - _Requirements: 11.3_
  - [ ] 9.4 Penetration-test/review attachment handling pipeline (malware scan bypass attempts, oversized/malformed files)
    - _Requirements: 11.4_

- [ ] 9.5 Load-test concurrent case processing (volume spike simulation) and validate inbound-triage latency target; confirm capacity alerting fires before throttling causes silent backlog
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

- [ ] 10. Pilot rollout
  - [ ] 10.1 Run shadow-mode pilot: agent drafts and classifies but all sends/updates require analyst approval, to calibrate standard-case criteria and confidence thresholds
    - _Requirements: 5.1, 6.6_
  - [ ] 10.2 Conduct compliance sign-off on template library and standard-case auto-send criteria
    - _Requirements: 4.3, 5.1_
  - [ ] 10.3 Enable AUTO_SEND for calibrated standard cases in production, with monitoring/rollback plan
    - _Requirements: 5.1_
