"""Small v1 interchange records, not the complete v1.1 design catalogue.

Drafts may contain unresolved references, unrecognized patterns, and open
conditions. The kernel reports their admission failures instead of treating a
syntactically valid record as a justified finding. Actor identity and graph
revision history are supplied by the controller, not authenticated here.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Record(BaseModel):
    # Preserve unfamiliar draft fields for inspection instead of silently
    # deleting them. They cannot add inference rules or change kernel policy.
    model_config = ConfigDict(extra="allow")


class Scope(RootModel[dict[str, Any]]):
    """Explicit semantic fields; v1 only supports exact scope equality."""

    root: dict[str, Any] = Field(default_factory=dict)


class Claim(Record):
    id: str
    text: str
    kind: str = "substantive"
    form: str = "assertion"
    scope: Scope = Field(default_factory=Scope)
    issue_id: str | None = None
    # Declared orientation to an active question is checked by the controller;
    # these tags neither license an inference nor adjudicate natural language.
    target_relation: Literal["direct", "negated", "record_non_establishment"] = "direct"
    target_question_id: str | None = None
    revision: int = 1
    supersedes: str | None = None
    conditions: list[str] = Field(default_factory=list)
    # Required for the explicit conjunction fragment. Members retain their
    # own forms: a conjunction of reports is not a conjunction of world facts.
    components: list[str] = Field(default_factory=list)


class Evidence(Record):
    id: str
    source_id: str
    source_version: str
    locator: str
    quote: str
    origin_ids: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    worker_id: str = "proposer"


class Condition(Record):
    id: str
    # Keep the question/obligation stable while its assessed answer evolves.
    text: str
    answer: str = ""
    status: Literal["met", "open", "assumed", "reopened"] = "open"
    evidence_ids: list[str] = Field(default_factory=list)
    performer: str | None = None
    performer_kind: str = "unknown"
    assumption_kind: str | None = None
    context_id: str | None = None
    revision: int = 1


class Argument(Record):
    id: str
    claim_id: str
    pattern: str
    premise_ids: list[str] = Field(default_factory=list)
    # Maps a fixed method-condition key to a Condition record ID.
    conditions: dict[str, str] = Field(default_factory=dict)
    scope: Scope = Field(default_factory=Scope)
    withdrawn: bool = False
    revision: int = 1


class Attack(Record):
    id: str
    target_id: str
    kind: str = "undercut"
    grounds: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    # Optional founded argument supplying the challenge's support. Attacks
    # depending on opposed arguments then participate in grounded cycles.
    support_argument_id: str | None = None
    condition_id: str | None = None
    scope: Scope | None = None
    basis: str = "presence"
    coverage_condition_id: str | None = None
    performer: str | None = None
    performer_kind: str = "model"
    raised_revision: int = 1
    challenged_revision: int | None = None
    disposition: str = "open"
    withdrawal_reason: str = ""
    reply_evidence_ids: list[str] = Field(default_factory=list)
    reply_condition_id: str | None = None
    reply_revision: int | None = None
    reply_reason: str = ""


class Profile(Record):
    id: str
    version: str = "1.0"
    authority: str = ""
    min_origins: int = 1
    # None applies the same requirement to claim-premise uses. A caller can
    # explicitly supply a different structural premise-use requirement.
    premise_min_origins: int | None = None
    allowed_claim_kinds: list[str] = Field(default_factory=list)
    allowed_patterns: list[str] = Field(default_factory=list)
    allow_conditional: bool = False
    allow_historical_sources: bool = False
    required_scope_fields: list[str] = Field(default_factory=list)
    allowed_performer_kinds: list[str] = Field(
        default_factory=lambda: ["model", "human", "tool", "system"]
    )
    # If provided, the controller's actor registry prevents a proposal from
    # claiming a different performer role. Empty means identities are logged,
    # not authenticated by this kernel.
    trusted_performers: dict[str, str] = Field(default_factory=dict)
    require_independent_reply: bool = False
    max_derivations: int = 2000
    max_depth: int = 32
    max_evaluation_steps: int = 10000


class InquiryGraph(Record):
    id: str = "inquiry"
    revision: int = 1
    claims: dict[str, Claim] = Field(default_factory=dict)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    conditions: dict[str, Condition] = Field(default_factory=dict)
    arguments: dict[str, Argument] = Field(default_factory=dict)
    attacks: dict[str, Attack] = Field(default_factory=dict)
    current_source_versions: dict[str, str] = Field(default_factory=dict)
    # Maps an issue to the explicit proposition that its presupposition fails.
    # The mapping alone cannot make an issue ill-posed.
    issue_presupposition_failures: dict[str, str] = Field(default_factory=dict)


FindingStatus = Literal[
    "established", "reported", "conditional", "contested", "not_established"
]


class ClaimFinding(Record):
    claim_id: str
    target_relation: Literal["direct", "negated", "record_non_establishment"] = "direct"
    target_question_id: str | None = None
    status: FindingStatus = "not_established"
    reasons: list[str] = Field(default_factory=list)
    open_conditions: list[str] = Field(default_factory=list)
    condition_texts: list[str] = Field(default_factory=list)
    assumption_contexts: list[str] = Field(default_factory=list)
    origins: list[str] = Field(default_factory=list)
    support_origins: list[str] = Field(default_factory=list)
    argument_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    form: str = "assertion"
    components: list[str] = Field(default_factory=list)


class Evaluation(Record):
    graph_id: str
    graph_revision: int
    profile_id: str
    profile_version: str
    evaluator_version: str = "v1-founded-grounded-1"
    evaluation_status: Literal["complete", "incomplete", "failed"] = "complete"
    findings: dict[str, ClaimFinding] = Field(default_factory=dict)
    argument_labels: dict[str, str] = Field(default_factory=dict)
    derivation_labels: dict[str, str] = Field(default_factory=dict)
    attack_labels: dict[str, str] = Field(default_factory=dict)
    issue_statuses: dict[str, str] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    current_source_versions: dict[str, str] = Field(default_factory=dict)
    # A kernel finding does not decide whether the requested task is complete.
    task_completed: bool = False
    last_complete_evaluation: dict[str, Any] | None = None
