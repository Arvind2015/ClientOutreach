"""
Canonical data model schemas for the KYC Client Outreach Agent.

All streams import from this module — do NOT copy these classes into
individual stream folders. Add this layer to your Lambda's layer config.

These are plain dataclasses (no ORM dependency) so they work in any Lambda
without extra packages.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


# ---------------------------------------------------------------------------
# KYC Profile
# ---------------------------------------------------------------------------

@dataclass
class KycDocument:
    doc_type: str
    doc_id: str
    issued_at: str          # ISO 8601 date string
    expires_at: str         # ISO 8601 date string
    s3_ref: str
    source: str = "unknown"


@dataclass
class KycField:
    value: str
    source: str
    updated_at: str         # ISO 8601 datetime string


@dataclass
class KycProfile:
    client_id: str
    client_type: str        # e.g. CORPORATE, INDIVIDUAL
    jurisdiction: str       # e.g. UK, DE
    risk_rating: str        # e.g. LOW, MEDIUM, HIGH
    fields: dict            # field_name -> KycField
    documents: list         # list of KycDocument
    preferred_language: str = "en"
    preferred_channel: str  = "EMAIL"
    retrieved_at: str       = ""


# ---------------------------------------------------------------------------
# Checklist Rules
# ---------------------------------------------------------------------------

@dataclass
class RequirementSpec:
    requirement_type: str
    validity_window_days: int
    mandatory: bool = True


@dataclass
class ChecklistRule:
    rule_id: str
    version: int
    client_type: str
    jurisdiction: str
    risk_rating: str
    required: list          # list of RequirementSpec
    updated_by: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# Gap Analysis
# ---------------------------------------------------------------------------

@dataclass
class OutstandingRequirement:
    requirement_type: str
    reason: str             # MISSING | EXPIRED | INCOMPLETE


@dataclass
class GapAnalysisResult:
    case_id: str
    client_id: str
    has_gaps: bool
    outstanding: list       # list of OutstandingRequirement
    computed_at: str        # ISO 8601 datetime string


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------

@dataclass
class Case:
    case_id: str
    client_id: str
    status: str             # state machine value
    follow_up_count: int    = 0
    risk_flags: list        = field(default_factory=list)
    escalation_reason: Optional[str] = None
    sfn_task_token: Optional[str]    = None   # set when AWAITING_RESPONSE
    created_at: str         = ""
    updated_at: str         = ""
    sla_due_at: str         = ""
    closed_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Outreach Email
# ---------------------------------------------------------------------------

@dataclass
class OutreachEmail:
    email_id: str
    case_id: str
    template_id: str
    rendered_body_ref: str  # S3 key of rendered HTML
    dispatch_mode: str      # AUTO_SEND | NEEDS_APPROVAL
    approved_by: Optional[str] = None
    sent_at: Optional[str]     = None
    delivery_status: str        = "PENDING"


# ---------------------------------------------------------------------------
# Inbound Message
# ---------------------------------------------------------------------------

@dataclass
class AttachmentResult:
    attachment_id: str
    s3_ref: str
    classification: str
    classification_confidence: float
    extracted_fields: dict
    extraction_confidence: float
    validation_result: Optional[str] = None  # set by validate-and-update


@dataclass
class InboundMessage:
    message_id: str
    case_id: Optional[str]      # None until correlated
    sender: str
    received_at: str
    raw_ref: str                 # S3 key of raw .eml
    attachments: list            # list of AttachmentResult
    correlation_status: str = "PENDING"  # MATCHED | UNMATCHED


# ---------------------------------------------------------------------------
# Audit Event
# ---------------------------------------------------------------------------

@dataclass
class AuditEvent:
    event_id: str
    case_id: str
    actor: str              # agent_name or analyst_id
    action: str
    timestamp: str          # ISO 8601 datetime string
    input_ref: Optional[str]  = None   # S3 key or DynamoDB ref
    output_ref: Optional[str] = None
