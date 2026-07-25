# Shared Common Layer

This Lambda layer is packaged by the deploy pipeline from `src/shared/common-layer/`
and uploaded to `s3://<bucket>/shared/common-layer/latest/common-layer.zip`.

Every stream's Lambda functions should declare this layer as a dependency so shared
code is never duplicated across stream folders.

## What belongs here

- **Canonical data model schemas** (`models.py`) — `KycProfile`, `ChecklistRule`,
  `GapAnalysisResult`, `Case`, `OutreachEmail`, `InboundMessage`, `AuditEvent`
- **Audit event helper** (`audit.py`) — single `emit_audit_event()` function used
  by all components to write structured events to the audit bus
- **Common utilities** (`utils.py`) — shared helpers (e.g. ISO timestamp generation,
  DynamoDB serialization, error classes)

## What does NOT belong here

- Stream-specific business logic — keep that in `src/streamN/`
- Large third-party packages — add those to the individual Lambda's `requirements.txt`

## Rule

If you find yourself copying a class or function from one stream folder into another,
it belongs here instead. Raise a PR to add it to the common layer.
