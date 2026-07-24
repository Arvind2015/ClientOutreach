# Client Outreach Agent — Stream & Task Dependency Chart

This document maps dependencies between the 6 streams and their key tasks.
Use it to understand what must be done before you can start your work,
and what other streams are blocked on you.

---

## Stream-Level Dependency Overview

```
Stream 1 (Infrastructure)
    │
    ├──► Stream 2 (KYC Data & Checklist Rules)
    │         │
    │         ├──► Stream 3 (Outreach Generation & Sending)
    │         │         │
    │         │         └──────────────────────────────────────┐
    │         │                                                 │
    │         └──► Stream 5 (Case Flow & Follow-Up Logic) ◄────┤
    │                   │                                       │
    │                   └──► Stream 6 (Analyst Insights View)       │
    │                                                           │
    └──► Stream 4 (Inbound Email & Document Reading) ───────────┘
```

### Summary Table

| Stream | Depends On | Blocks |
|--------|-----------|--------|
| Stream 1 — Infrastructure | — (start here) | All other streams |
| Stream 2 — KYC Data & Checklist | Stream 1 | Streams 3, 5 |
| Stream 3 — Outreach Generation | Streams 1, 2 | Stream 5 |
| Stream 4 — Inbound Email & Docs | Stream 1 | Stream 5 |
| Stream 5 — Case Flow & Follow-Up | Streams 1, 2, 3, 4 | Stream 6 (live data) |
| Stream 6 — Analyst Insights View | Stream 1 (stub data); Stream 5 (live data) | — |

---

## PERT-Style Task Dependency Detail

Each node is a task group. Arrows show "must complete before" relationships.
Numbers in brackets reference tasks in `tasks.md`.

```
[1.1 Provision AWS infra]
    │
    ├──[1.2 Define shared data schemas]
    │       │
    │       ├──[2.1 KYC profile retrieval adapter]
    │       │       │
    │       │       └──[2.2 Profile normalisation]
    │       │               │
    │       │               ├──[2.3 24h TTL cache]
    │       │               │
    │       │               └──[3.1 ChecklistRules table + versioned write]
    │       │                       │
    │       │                       ├──[3.2 Rule resolution + baseline fallback]
    │       │                       │       │
    │       │                       │       └──[3.3 Matching Engine → GapAnalysisResult]
    │       │                       │               │
    │       │                       │               ├──[3.4 Auto-close: no gaps found]
    │       │                       │               │
    │       │                       │               └──[4.1 Template library + compliance sign-off]
    │       │                       │                       │
    │       │                       │                       ├──[4.2 render_template tool]
    │       │                       │                       │       │
    │       │                       │                       │       └──[4.3 Case reference generation]
    │       │                       │                       │               │
    │       │                       │                       │               ├──[4.4 Standard-case classifier]
    │       │                       │                       │               │       │
    │       │                       │                       │               │       ├──[4.5 SES AUTO_SEND path]
    │       │                       │                       │               │       │       │
    │       │                       │                       │               │       └──[4.6 SQS approval queue]
    │       │                       │                       │               │               │
    │       │                       │                       │               └──[4.7 Min re-contact interval]
    │       │                       │                       │
    │       │                       └──[5.1 SES inbound receive → S3 → EventBridge]
    │       │                               │
    │       │                               └──[5.2 Case correlation + ManualTriageQueue]
    │       │                                       │
    │       │                                       ├──[5.3 Attachment safety gate]
    │       │                                       │       │
    │       │                                       │       └──[5.4 Attachment classification (Bedrock)]
    │       │                                       │               │
    │       │                                       │               └──[5.5 Data extraction + confidence scoring]
    │       │                                       │                       │
    │       │                                       │                       └──[5.6 Confidence-threshold gate]
    │       │                                       │                               │
    │       │                                       │                               └──[6.1 Deterministic validation]
    │       │                                       │                                       │
    │       │                                       │                                       ├──[6.2 KYC record update adapter]
    │       │                                       │                                       │       │
    │       │                                       │                                       │       └──[6.3 Update-failure retry + alert]
    │       │                                       │                                       │
    │       │                                       │                                       └──[6.4 Re-run Matching Engine post-update]
    │       │                                       │                                               │
    │       │                                       │                                               ├──[6.5 Follow-up email generation]
    │       │                                       │                                               │       │
    │       │                                       │                                               │       └──[6.6 Max follow-up enforcement + escalation]
    │       │                                       │                                               │
    │       │                                       │                                               └──[6.7 Case closure on full compliance]
    │       │
    │       └──[1.3 Audit event bus + append-only persistence]
    │               │
    │               └──(consumed by all components — no single downstream dependency)
    │
    └──(All tasks above feed into)
            │
            ▼
    [7.1 Step Functions state machine — full lifecycle]
            │
            ├──[7.2 EventBridge triggers (schedule, inbound, manual)]
            │
            ├──[7.3 SLA timers + forced escalation]
            │
            └──[7.4 Uniform escalation handler]
                    │
                    ▼
    [8.1–8.4 Analyst Insights View]
    (can start with stub data from Stream 1 onwards;
     goes live once Task 7 is complete)
```

---

## Critical Path

The longest chain of sequential dependencies — this is what determines the
earliest possible go-live date:

```
1.1 → 1.2 → 2.1 → 2.2 → 3.1 → 3.2 → 3.3 → 4.1 → 4.2 → 4.3 → 4.4 → 4.5
                                                                         │
                              5.1 → 5.2 → 5.3 → 5.4 → 5.5 → 5.6 → 6.1 → 6.4
                                                                         │
                                                                    7.1 → 7.2 → 7.3 → 7.4
                                                                         │
                                                                    8.1 → 8.4
```

Anything on this path has **zero float** — a delay here delays the whole project.
The approval-queue path (4.6) and manual triage path (5.2 fallback) are off the
critical path and can slip slightly without delaying go-live.

---

## What Each Stream Can Start Immediately vs. Must Wait For

### Stream 1 (Person A)
- **Start immediately:** All of it. No dependencies.
- **Deliver first:** Task 1.1 (tables, buckets, IAM) — everything else gates on this.

### Stream 2 (Person B)
- **Can start:** Designing the ChecklistRules schema and writing test data (no AWS needed yet).
- **Must wait for:** Task 1.1 before deploying anything to AWS.

### Stream 3 (Person C)
- **Can start:** Drafting email templates and beginning compliance review process (no AWS needed).
- **Must wait for:** Task 1.1 (to deploy), and Task 3.3 (GapAnalysisResult schema from Stream 2) before building the render logic.

### Stream 4 (Person D)
- **Can start:** Designing the correlation logic and writing the safety gate rules locally.
- **Must wait for:** Task 1.1 (SES inbound config, S3 bucket), Task 4.3 (case reference format from Stream 3).

### Stream 5 (Person E)
- **Can start:** Sketching the Step Functions state machine definition and escalation logic (no AWS needed).
- **Must wait for:** Tasks 1.1, 3.3, 4.5/4.6 (outreach send paths), and 5.6/6.1 (inbound processing chain) before the full state machine can be wired and tested end-to-end.
- **Note:** This stream finishes last by design — it's the integrator.

### Stream 6 (Person F)
- **Can start immediately:** Build the views against hardcoded/stub case data.
- **Must wait for:** Task 7.1 (state machine) before connecting to live case state.
- **SNS notification wiring:** Coordinate with Person A to get the SNS topic ARN provisioned in Task 1.1.

---

## Interface Contracts Between Streams

These are the handoff points where one stream's output becomes another's input.
Agreeing on these early avoids integration surprises.

| Producer | Consumer | Contract |
|----------|----------|----------|
| Stream 1 | All | DynamoDB table names, S3 bucket names, IAM role ARNs, SNS topic ARN, SES identity |
| Stream 2 | Stream 3 | `GapAnalysisResult` schema (list of outstanding requirement types) |
| Stream 2 | Stream 5 | `KycProfile` + `ChecklistRule` schemas; `get_kyc_profile` and `run_gap_analysis` Lambda function names/ARNs |
| Stream 3 | Stream 4 | `X-Case-Ref` header format and `case_ref` token pattern (needed for inbound correlation) |
| Stream 3 | Stream 5 | `OutreachEmail` schema; SES send Lambda ARN; SQS approval queue URL |
| Stream 4 | Stream 5 | `InboundMessage` + `Attachment` schemas; Inbound Analysis Lambda ARN; Step Functions `SendTaskSuccess` call |
| Stream 5 | Stream 6 | `Case` DynamoDB table schema + GSI definitions for status/risk-rating filtering |
