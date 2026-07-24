# Client Outreach Agent — Specification

## 1. Problem Statement

Banks must periodically verify and refresh KYC (Know Your Customer) information for every client — identity documents, proof of address, source of funds, beneficial ownership, etc. When information is missing, incomplete, or expired, an analyst must identify the gap, contact the customer, and process whatever the customer sends back. Today this is manual: analysts read case files, write emails by hand, monitor inboxes, and manually inspect attachments. It is slow, inconsistent, and doesn't scale with client volume.

## 2. Objectives

- Automate identification of missing/incomplete/expired KYC requirements per client.
- Automate generation and sending of outreach emails requesting exactly what's missing.
- Automate reading of customer replies, including interpreting document attachments.
- Keep a human analyst in control of anything ambiguous, high-risk, or non-standard.
- Produce a full audit trail suitable for regulatory review.

## 3. Scope

### In Scope
- Single-channel (email) outreach to existing bank customers with an identified KYC gap.
- Checklist-driven determination of required documents/data, configurable by client type, jurisdiction, and risk rating.
- AI-assisted drafting of outreach emails from approved templates.
- AI-assisted reading and classification of inbound emails and attachments (PDF, JPEG, PNG, DOCX).
- Automatic follow-up requests when a response is partial, up to a capped number of cycles.
- Human approval workflow for non-standard/high-risk cases.
- Analyst dashboard for case visibility, approvals, and rule management.
- Audit logging of every automated decision and action.

### Out of Scope (v1)
- Channels other than email (SMS, phone, portal upload) — noted as future extension.
- New-customer onboarding KYC (this covers existing-client *remediation/refresh* only).
- Automated final compliance sign-off / regulatory filing — the agent prepares and updates records; formal compliance decisions remain with the bank's existing processes.
- Real-time identity verification (e.g., biometric liveness checks) — assumed handled by existing tooling if applicable.

## 4. Actors / Personas

| Actor | Role |
|---|---|
| **Customer** | Receives outreach emails, replies with documents/data. |
| **KYC Analyst** | Reviews escalated/queued cases, approves or edits outreach, resolves exceptions. |
| **Compliance Owner** | Defines/maintains checklist rules and approves email templates. |
| **Client Outreach Agent (system)** | Automates retrieval, matching, drafting, dispatch, and inbound analysis. |

## 5. Functional Requirements

**Data & Checklist**
1. The system shall retrieve a client's current KYC profile (documents, fields, risk rating, jurisdiction, client type) on demand.
2. The system shall support a configurable checklist defining required documents/data by client type, jurisdiction, and risk rating.
3. The system shall treat expired documents as missing when determining requirement gaps.
4. The system shall determine the exact set of outstanding requirements for a client by comparing their profile against the applicable checklist.

**Outreach Generation & Dispatch**
5. The system shall generate a customer-facing outreach email listing the specific missing/expired requirements, using an approved template.
6. The system shall embed a unique case reference in each outreach email to correlate future replies.
7. The system shall automatically send outreach emails for standard, low-risk cases.
8. The system shall route non-standard or high-risk outreach to a KYC analyst for approval before sending.
9. The system shall avoid contacting the same customer more than once within a minimum interval.

**Inbound Processing**
10. The system shall monitor a dedicated mailbox for customer replies.
11. The system shall match an inbound reply to its corresponding case automatically.
12. The system shall route unmatched replies to a manual triage queue.
13. The system shall identify and classify attachment types (e.g., passport, proof of address) against outstanding requirements.
14. The system shall extract relevant data/fields from attachments and validate them against checklist rules.
15. The system shall flag low-confidence classification or extraction results for analyst review instead of auto-accepting them.
16. The system shall reject or quarantine unsupported or unsafe attachment types.

**Follow-Up & Record Update**
17. The system shall automatically generate a follow-up request if a reply leaves any requirement still outstanding.
18. The system shall cap the number of automatic follow-up cycles and escalate to an analyst once the cap is reached.
19. The system shall update the client's KYC record once a submitted item passes validation.
20. The system shall close a case automatically once all requirements are satisfied.

**Analyst Experience**
21. The system shall provide a dashboard showing case status, history, and outstanding items for every case.
22. The system shall clearly state the reason whenever a case is escalated or queued for approval.
23. The system shall notify the responsible analyst when a case needs their action.
24. The system shall allow analysts to approve, edit, or reject queued outreach emails.

**Audit & Compliance**
25. The system shall log every automated decision and action with timestamp and actor.
26. The system shall retain an immutable audit trail per case, exportable on request.

## 6. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Security | Customer PII and documents encrypted at rest and in transit; least-privilege access control. |
| Privacy | No customer PII sent to non-approved external/third-party AI services. |
| Reliability | Failures (source system down, low AI confidence, validation errors) halt automation for that case and escalate — no silent failure. |
| Auditability | Every decision traceable: what happened, when, by whom (agent or analyst). |
| Scalability | Must handle concurrent processing of many client cases without cross-case interference. |
| Performance | Inbound email should be triaged/correlated within minutes of receipt (target, tune per pilot). |
| Usability | Analyst dashboard must let a case be understood (status, reason, history) without consulting another system. |
| Compliance | Outbound email content constrained to compliance-approved templates, not free-form AI generation. |

## 7. Data Entities

- **Client / KYC Profile** — client attributes, on-file documents, data fields, risk rating.
- **Checklist Rule** — required documents/data by client type, jurisdiction, risk rating; versioned.
- **Case** — a single remediation workflow instance for one client, with status/history.
- **Outreach Email** — a generated/sent message tied to a case.
- **Inbound Message / Attachment** — a customer reply and its extracted, validated content.
- **Audit Event** — an immutable record of a decision or action.

## 8. Integration Points

- **KYC system of record** — source of client profile data and destination for validated updates. *(System to be named — currently an open item.)*
- **Email service** — sending and receiving outreach correspondence.
- **Document/OCR processing** — extracting structured data from attachment images/PDFs.
- **AI/LLM service** — email drafting and document classification/extraction.
- **Notification channel** — alerting analysts (email, in-app, or both).

## 9. Assumptions & Constraints

- Customers already have an established relationship with the bank (this is remediation, not onboarding).
- An approved library of email templates will be produced and signed off by compliance before go-live.
- The checklist rules are configurable business data, not hardcoded logic.
- Human approval is required for anything outside explicitly defined "standard case" criteria; those criteria themselves require compliance sign-off before automation is enabled.
- Exact source-of-record system, approved AI/LLM provider, and audit-retention standard are to be confirmed (see design.md → Open Items).

## 10. Success Metrics (indicative)

- % of KYC cases resolved without analyst intervention (standard-case automation rate).
- Average time from gap identification to case closure.
- Reduction in analyst manual-processing time per case.
- Escalation/exception rate (should decrease as rules/templates are tuned).
- Customer response rate to automated outreach vs. prior manual baseline.

## 11. Glossary

- **KYC** — Know Your Customer: identity/risk verification information banks must maintain on clients.
- **AML** — Anti-Money Laundering: the regulatory regime KYC supports.
- **Remediation** — the process of closing gaps in existing clients' KYC files (as opposed to onboarding new clients).
- **Standard case** — an outreach scenario meeting predefined low-risk criteria, eligible for automatic send without analyst approval.

---
*This document is the business-facing specification. See `.kiro/specs/client-outreach-agent/requirements.md` for EARS-format acceptance criteria, `design.md` for architecture, and `tasks.md` for the implementation plan.*
