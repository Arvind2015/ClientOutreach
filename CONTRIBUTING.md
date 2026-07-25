# Contributing Guide — KYC Client Outreach Agent

Quick reference for all six stream owners. Read before writing code.

---

## Folder structure

```
src/
  shared/
    common-layer/          ← shared data models, audit helper, common utils
                             packaged as a Lambda layer, used by ALL streams
  stream1/                 ← Infrastructure CLI scripts (Person A)
  stream2/                 ← KYC retrieval + gap analysis (Person B)
  stream3/                 ← Outreach drafting + sending (Person C)
  stream4/                 ← Inbound email + attachment analysis (Person D)
  stream5/                 ← Case orchestration + follow-up (Person E)
  stream6/                 ← Analyst insights view (Person F)

test/
  mocks/
    stream5/               ← Temporary stub Lambdas for stream5 integration tests
                             NOT deployed — see test/mocks/stream5/README.md
  unit/
    stream2/               ← Unit tests mirror src/ structure (add as you build)
    stream3/
    ...
  integration/             ← Cross-stream end-to-end tests
```

---

## Rules

### src/shared/ — shared code goes here, not in stream folders

If a class or function is used by more than one stream, it belongs in
`src/shared/common-layer/`, not copied into each stream folder.

Currently shared:
- `models.py` — canonical data model dataclasses (`KycProfile`, `Case`, `AuditEvent`, etc.)
- `audit.py` — `emit_audit_event()` helper used by all components
- `requirements.txt` — shared third-party dependencies

To use in your Lambda, declare the common layer ARN in your Lambda config
(Stream 1 provisions this and publishes the ARN to `config/infra-config.json`).

### src/streamN/ — one folder per stream, one Lambda per subfolder

Each Lambda function lives in its own subfolder:
```
src/stream2/
  get-kyc-profile/
    handler.py          ← entry point: handler.handler
    requirements.txt    ← Lambda-specific dependencies only
  run-gap-analysis/
    handler.py
    requirements.txt
```

The deploy pipeline (`deploy.yml`) detects changes per stream folder and
packages only what changed. **Do not put code outside your stream folder**
or the change detection breaks.

### test/ — mirrors src/ structure

```
test/mocks/stream5/      ← stub Lambdas (already exists, see README there)
test/unit/streamN/       ← unit tests for your stream's Lambdas
test/integration/        ← cross-stream tests (added during integration phase)
```

### Branch naming

All branches follow: `feature/Arvind-<description>` (replace Arvind with your name).

Examples:
- `feature/Arvind-stream5-case-flow-and-orchestration`
- `feature/BobStream2-kyc-retrieval`
- `feature/Carol-stream3-outreach-drafting`

---

## Dependency on other streams

Stream 5's state machine calls Lambdas from Streams 2, 3, and 4.
While those aren't ready yet, `test/mocks/stream5/` provides stubs.

When your real Lambda is deployed, tell Person E (Stream 5) so the ARN
can be swapped in `src/stream5/state-machine/state-machine.json` and the
corresponding mock deleted.

See `test/mocks/stream5/README.md` for the full ownership table.

---

## infra-config.json

Stream 1 (Person A) produces `config/infra-config.json` containing all
resource ARNs and names (DynamoDB tables, S3 buckets, Lambda ARNs, SNS topics,
SQS queues). All other streams read from this file — do not hardcode ARNs.

---

## Commit message format

```
feat: <Name>: short description

- bullet point details
```

Examples:
- `feat: Arvind: scaffold stream5 Lambda handlers and state machine`
- `fix: Arvind: fix DynamoDB waitForTaskToken in state machine`
- `feat: Bob: implement get-kyc-profile Lambda with DynamoDB cache`
