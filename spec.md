# Client Outreach Agent — Specification

## 1. Problem Statement

Many organizations need to periodically check that the information they hold on each customer is complete and up to date — identity documents, proof of address, source of funds, ownership details, and similar records (commonly known as KYC, or "Know Your Customer," checks). When something is missing, incomplete, or expired, someone has to notice the gap, reach out to the customer, and process whatever comes back.

Today that work is manual: a person reads through case files, writes emails by hand, watches an inbox, and checks each attachment one at a time. It's slow, easy to get wrong, and doesn't scale as the number of customers grows.

## 2. Objectives

- Automatically spot which customers are missing, or have expired, required information.
- Automatically write and send emails asking customers for exactly what's missing.
- Automatically read customer replies, including understanding attached documents.
- Keep a person in charge of anything unclear, high-risk, or out of the ordinary.
- Keep a full record of what happened and why, so it can be reviewed later.

## 3. Scope

### In Scope
- Reaching out to existing customers by email when something is missing from their record.
- A checklist that defines what's required, which can vary by customer type, region, and risk level.
- AI-assisted drafting of outreach emails, built from pre-approved templates.
- AI-assisted reading and sorting of incoming emails and attachments (PDF, JPEG, PNG, DOCX).
- Automatic follow-up emails when a reply only partly answers what was asked, up to a set number of tries.
- A review-and-approve step for anything non-standard or high-risk.
- A dashboard so staff can see case status, approve items, and manage the rules.
- A record of every automated decision and action, kept for later review.

### Out of Scope (v1)
- Ways to reach customers other than email (text message, phone, portal upload) — a possible future addition.
- Verifying a brand-new customer for the first time — this covers refreshing records for existing customers only.
- Making the final compliance decision or filing anything with a regulator — the agent prepares and updates records, but formal sign-off stays with the organization's existing process.
- Real-time identity checks (e.g., a live selfie/liveness check) — assumed to be handled by other tools, if used at all.

## 4. Actors / Personas

| Actor | Role |
|---|---|
| **Customer** | Receives outreach emails, replies with documents/information. |
| **Reviewer** | Reviews queued or flagged cases, approves or edits outreach, resolves exceptions. |
| **Program Owner** | Defines and maintains the checklist rules, and approves email templates. |
| **Client Outreach Agent (system)** | Automates finding gaps, drafting and sending emails, and reading replies. |

## 5. Functional Requirements

**Data & Checklist**
1. The system shall look up a customer's current record (documents, fields, risk level, region, customer type) on demand.
2. The system shall support a configurable checklist defining what's required, based on customer type, region, and risk level.
3. The system shall treat an expired document as if it were missing.
4. The system shall work out exactly what's missing for a customer by comparing their record against the checklist.

**Outreach Generation & Dispatch**
5. The system shall generate a customer-facing email listing exactly what's missing or expired, using an approved template.
6. The system shall include a unique reference in each outreach email so replies can be matched back to the right case.
7. The system shall send outreach emails automatically for standard, low-risk cases.
8. The system shall send non-standard or high-risk outreach to a reviewer for approval before it goes out.
9. The system shall avoid contacting the same customer more than once within a minimum time window.

**Inbound Processing**
10. The system shall watch a dedicated mailbox for customer replies.
11. The system shall automatically match an inbound reply to the case it belongs to.
12. The system shall send any reply it can't match to a manual triage queue.
13. The system shall identify and sort attachment types (e.g., passport, proof of address) against what's outstanding.
14. The system shall pull relevant information out of attachments and check it against the checklist rules.
15. The system shall flag anything it's not confident about for a person to review, rather than accepting it automatically.
16. The system shall reject or quarantine attachment types it doesn't support or that look unsafe.

**Follow-Up & Record Update**
17. The system shall automatically send a follow-up request if a reply still leaves something outstanding.
18. The system shall cap the number of automatic follow-ups and hand the case to a reviewer once that limit is hit.
19. The system shall update the customer's record once a submitted item passes its checks.
20. The system shall automatically close a case once everything required has been provided.

**Reviewer Experience**
21. The system shall provide a dashboard showing status, history, and outstanding items for every case.
22. The system shall clearly explain why a case was escalated or queued for approval.
23. The system shall notify the responsible reviewer when a case needs their attention.
24. The system shall let reviewers approve, edit, or reject queued outreach emails.

**Audit & Compliance**
25. The system shall log every automated decision and action, with a timestamp and who/what performed it.
26. The system shall keep an unchangeable record per case that can be exported on request.

## 6. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Security | Customer information and documents are encrypted at rest and in transit; access is limited to what each role actually needs. |
| Privacy | No customer personal information is sent to AI services that haven't been explicitly approved. |
| Reliability | If something fails (source system down, low AI confidence, a check doesn't pass), automation stops for that case and it's escalated — nothing fails silently. |
| Auditability | Every decision can be traced: what happened, when, and by whom (the system or a person). |
| Scalability | Must handle many cases at once without one case interfering with another. |
| Performance | An inbound email should be triaged and matched within minutes of arriving (target — to be tuned during the pilot). |
| Usability | A reviewer should be able to understand a case's status, reason, and history without needing to check another system. |
| Compliance | Outbound emails are limited to pre-approved templates, not freely generated text. |

## 7. Data Entities

- **Customer Record** — customer attributes, documents on file, data fields, risk level.
- **Checklist Rule** — what's required, based on customer type, region, and risk level; versioned over time.
- **Case** — one remediation workflow for one customer, with its own status and history.
- **Outreach Email** — a generated/sent message tied to a case.
- **Inbound Message / Attachment** — a customer reply and whatever was extracted and checked from it.
- **Audit Event** — an unchangeable record of one decision or action.

## 8. Integration Points

- **System of record** — where customer data lives and where validated updates get written back. *(Specific system to be named — currently an open item.)*
- **Email service** — for sending and receiving outreach correspondence.
- **Document/OCR processing** — for pulling structured data out of attachment images/PDFs.
- **AI/LLM service** — for email drafting and document classification/extraction.
- **Notification channel** — for alerting reviewers (email, in-app, or both).

## 9. Assumptions & Constraints

- Customers already have an established relationship with the organization (this is about refreshing records, not signing up new customers).
- An approved set of email templates will be written and signed off before go-live.
- The checklist rules are configurable data, not logic hardcoded into the system.
- A person must approve anything that falls outside clearly defined "standard case" criteria — and those criteria themselves need sign-off before automation is turned on.
- The exact system of record, the approved AI/LLM provider, and how long records must be retained are all still to be confirmed (see design.md → Open Items).

## 10. Success Metrics (indicative)

- % of cases resolved without a reviewer needing to step in (standard-case automation rate).
- Average time from spotting a gap to closing the case.
- Reduction in manual processing time per case.
- How often cases get escalated/flagged (should go down as rules/templates are tuned).
- Customer response rate to automated outreach vs. the old manual process.

## 11. Glossary

- **KYC** — "Know Your Customer": the practice of verifying who a customer is and assessing risk, most familiar from banking/financial regulation but applicable anywhere an organization must keep verified customer records.
- **Remediation** — the process of closing gaps in an existing customer's record (as opposed to verifying someone for the first time).
- **Standard case** — an outreach scenario that meets predefined low-risk criteria, so it can be sent automatically without a reviewer's approval.

---
*This document is the plain-language specification. See `.kiro/specs/client-outreach-agent/requirements.md` for detailed acceptance criteria, `design.md` for architecture, and `tasks.md` for the implementation plan.*
