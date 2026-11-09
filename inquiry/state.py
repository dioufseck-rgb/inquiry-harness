"""
Inquiry state: a question, its framing, the argument graph that holds the
reasoning, and the bookkeeping of the cycle (reflections, stop assessments,
conclusion). The graph is the primary state; everything else is thin.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .argument.graph import ArgumentGraph, QuestionType, now_iso  # noqa: F401  (now_iso re-exported)

Phase = Literal["new", "framed", "hypothesized", "inquiring", "concluded"]
Move = Literal["frame", "hypothesize", "plan", "gather", "argue", "critique", "evaluate", "reflect", "stop", "conclude"]


class Framing(BaseModel):
    restatement: str = ""
    question_type: QuestionType = "mixed"
    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    presuppositions: list[str] = Field(default_factory=list)
    answerhood: str = Field(default="", description="What a complete answer to the main question contains.")
    standard_override: Optional[str] = Field(
        default=None, description="Proof standard set at framing for all claims on the main issue, if any."
    )


class PlannedTest(BaseModel):
    """Evidence that would discriminate between claims, and how to look for it."""
    id: str
    claim_ids: list[str]
    observation: str
    expected_if: dict[str, str] = Field(default_factory=dict, description="claim id -> what we would see if true.")
    diagnosticity: Literal["high", "medium", "low"] = "medium"
    queries: list[str] = Field(default_factory=list)
    status: Literal["planned", "run", "unobtainable"] = "planned"
    round: int = 0


class Reflection(BaseModel):
    round: int
    established: list[str] = Field(default_factory=list)
    assumed: list[str] = Field(default_factory=list)
    load_bearing_node_ids: list[str] = Field(default_factory=list)
    framing_drift: Optional[str] = None
    directive: str = ""


class StopAssessment(BaseModel):
    round: int
    decision: Literal["continue", "stop"]
    reason: str
    undecided_on_path: list[str] = Field(default_factory=list, description="Undecided node ids on the path to the main claim.")
    obtainable: list[str] = Field(default_factory=list, description="Planned test ids that could still move those nodes.")


class Judgement(BaseModel):
    text: str
    confidence: Literal["high", "moderate", "low"]
    rests_on: str
    claim_ids: list[str] = Field(default_factory=list)


class Conclusion(BaseModel):
    round: int
    answer: str
    judgements: list[Judgement] = Field(default_factory=list)
    what_would_change_this: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class Inquiry(BaseModel):
    id: str
    question: str
    created_at: str = Field(default_factory=now_iso)
    phase: Phase = "new"
    round: int = 0
    framing: Framing = Field(default_factory=Framing)
    graph: ArgumentGraph = Field(default_factory=ArgumentGraph)
    tests: list[PlannedTest] = Field(default_factory=list)
    reflections: list[Reflection] = Field(default_factory=list)
    stop_assessments: list[StopAssessment] = Field(default_factory=list)
    conclusion: Optional[Conclusion] = None
    notes: list[str] = Field(default_factory=list)

    def main_claims(self):
        if not self.graph.main_issue_id:
            return []
        return self.graph.claims_for_issue(self.graph.main_issue_id)

    def next_test_id(self) -> str:
        return f"T{len(self.tests) + 1}"
