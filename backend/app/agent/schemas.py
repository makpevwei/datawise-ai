"""Agent-facing schemas: the structured shape of an agentic answer.

EvidenceLabel is the Phase 3 verification vocabulary -- Phase 2's
SourceLabel plus DOCUMENT_EVIDENCE for RAG-grounded claims. Every Finding
in an AgentAnswer must carry one; the verification pass (app/agent/
verification.py) can downgrade a claimed label but never upgrade one.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceLabel(StrEnum):
    VERIFIED_FROM_DATA = "VERIFIED_FROM_DATA"
    CALCULATED = "CALCULATED"
    DERIVED = "DERIVED"
    # DataWise's name for what Phase 4's spec calls VERIFIED_FROM_DOCUMENT --
    # same semantics (a claim grounded in a cited, retrieved document
    # excerpt, verified by verify_document_grounding), kept as its
    # original Phase 3 wire value rather than renamed, since it's already
    # load-bearing across the backend, frontend, and existing tests.
    DOCUMENT_EVIDENCE = "DOCUMENT_EVIDENCE"
    VERIFIED_FROM_WEB = "VERIFIED_FROM_WEB"
    AI_INTERPRETATION = "AI_INTERPRETATION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    # A general business/conceptual answer (e.g. "what is customer churn?")
    # that isn't grounded in the user's own uploaded data or documents at
    # all -- never a data claim, so never subject to numeric verification
    # (see NUMERIC_LABELS in app/agent/verification.py) and never shown
    # with the same styling as a data-backed finding.
    GENERAL_ANSWER = "GENERAL_ANSWER"


class CrossCheckLabel(StrEnum):
    SUPPORTED_BY_DATA = "SUPPORTED_BY_DATA"
    DOCUMENT_CLAIM = "DOCUMENT_CLAIM"
    NOT_VERIFIED_BY_DATA = "NOT_VERIFIED_BY_DATA"
    CONTRADICTED_BY_DATA = "CONTRADICTED_BY_DATA"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ToolInvocation(BaseModel):
    """One explicit, inspectable tool call -- the unit the agent trace is built from."""

    id: str
    tool_name: str
    input: dict[str, Any]
    output_summary: str
    succeeded: bool
    duration_ms: int


TraceStage = Literal[
    "understanding_question",
    "routing",
    "datasets",
    "documents",
    "relationships",
    "analysis",
    "document_research",
    "web_research",
    "verification",
    "answer",
]


class TraceStep(BaseModel):
    stage: TraceStage
    label: str
    detail: str


class Citation(BaseModel):
    document_id: str
    document_name: str
    chunk_id: str
    location: dict[str, Any]
    excerpt: str
    relevance_score: float
    # "document" (default, Phase 3 behavior) or "web" (Phase 4). A web
    # citation has document_id/chunk_id="" and document_name holding the
    # result's title -- see app/agent/planner._resolve_web_citation.
    source_type: Literal["document", "web"] = "document"
    url: str | None = None


class Finding(BaseModel):
    text: str
    label: EvidenceLabel
    verification_note: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class ClaimComparison(BaseModel):
    document_claim: str
    citation: Citation | None = None
    data_finding: str | None = None
    label: CrossCheckLabel
    explanation: str


class LLMMetadata(BaseModel):
    """Non-secret facts about how the answer's LLM calls were actually
    served -- safe to show in the UI (e.g. "Answered by OpenAI ·
    gpt-4o-mini", "Fallback used: Gemini"). Never carries credentials."""

    provider: str
    model: str
    fallback_used: bool
    attempt_count: int
    latency_ms: int


class AgentAnswer(BaseModel):
    question: str
    session_id: str
    configured: bool
    executive_summary: str | None = None
    key_findings: list[Finding] = Field(default_factory=list)
    risks: list[Finding] = Field(default_factory=list)
    recommendations: list[Finding] = Field(default_factory=list)
    claim_comparisons: list[ClaimComparison] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    tool_invocations: list[ToolInvocation] = Field(default_factory=list)
    raw_answer_text: str | None = None
    error: str | None = None
    llm_metadata: LLMMetadata | None = None
    created_at: datetime
    # Set by the API layer after persisting this turn (app/api/agent.py) --
    # the id of its Message row, used by POST /reports to export a
    # specific historical answer without needing to resend the whole
    # AgentAnswer body. None only if persistence is somehow unavailable.
    message_id: str | None = None


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None
    dataset_ids: list[str] | None = None
    document_ids: list[str] | None = None
