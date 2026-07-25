# Stream 5 — Mock Dependencies

These are **temporary stub Lambda functions** used for local and integration
testing of the Stream 5 orchestration only. They are **NOT deployed** to any
environment — the deploy workflow only packages `src/` and will never pick
these up.

## Purpose

Stream 5 (Case Orchestrator) depends on Lambdas owned by Streams 2, 3, and 4
that may not be ready yet. These mocks return realistic hardcoded responses so
the Stream 5 state machine can be tested end-to-end before those streams deliver
their real implementations.

## What each mock replaces

| Mock folder | Replaces (real Lambda) | Owner stream | Owner |
|---|---|---|---|
| `mock-get-kyc-profile/` | `src/stream2/get-kyc-profile` | Stream 2 | Person B |
| `mock-run-gap-analysis/` | `src/stream2/run-gap-analysis` | Stream 2 | Person B |
| `mock-draft-outreach/` | `src/stream3/draft-outreach-email` | Stream 3 | Person C |
| `mock-send-outreach/` | `src/stream3/send-outreach-email` | Stream 3 | Person C |
| `mock-analyse-attachment/` | `src/stream4/analyse-attachment` | Stream 4 | Person D |
| `mock-validate-and-update/` | `src/stream5/validate-and-update` | Stream 5 | Person E |

## How to use

Deploy a mock manually for testing only (not via the CI/CD deploy workflow):

```bash
zip -r mock-get-kyc-profile.zip mock-get-kyc-profile/
aws lambda create-function \
  --function-name mock-get-kyc-profile \
  --runtime python3.12 \
  --handler handler.handler \
  --zip-file fileb://mock-get-kyc-profile.zip \
  --role <test-execution-role-arn>
```

Update the state machine ARN placeholders in
`src/stream5/state-machine/state-machine.json` to point to the mock function
ARNs during testing.

## Disposal

When a real implementation from the owning stream is deployed:

1. Update the corresponding `${...Arn}` placeholder in `state-machine.json`
   to the real Lambda ARN
2. Delete the corresponding mock folder from this directory
3. Once **all** mocks are replaced, delete this entire `test/mocks/stream5/`
   folder and raise a PR to confirm the cleanup

## Important

- Do **not** add mock handlers to `src/` — that folder is production deployables only
- Do **not** commit mock function ARNs to the state machine JSON — use the
  `${placeholder}` pattern and resolve at deploy time via infra-config
