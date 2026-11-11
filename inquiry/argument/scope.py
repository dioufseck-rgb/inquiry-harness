"""Small deterministic scope vocabulary; never asks a model to compare scopes."""
from __future__ import annotations

import re
from typing import Literal
from pydantic import BaseModel, Field

Relation = Literal["reduces", "increases", "no_effect", "is", "differs", "recommends_against", "recommends_for", "unknown"]


class Magnitude(BaseModel):
    low: float
    high: float
    unit: str


class Scope(BaseModel):
    population: str = ""
    comparison: str = ""
    outcome: str = ""
    period: str = ""
    relation: Relation = "unknown"
    magnitude: Magnitude | None = None
    narrower_than: list[Literal["population", "period", "outcome", "comparison"]] = Field(default_factory=list)
    parent_scope: dict[str, str] = Field(default_factory=dict)

    def summary(self) -> str:
        return "; ".join(f"{k}={getattr(self, k)}" for k in ("population", "comparison", "outcome", "period")
                         if getattr(self, k)) or "issue scope"


def canonical(value: str) -> str:
    value = value.casefold().replace("–", "-")
    value = re.sub(r"\b(?:aged?|years?|or|and)\b", " ", value)
    value = re.sub(r"\b(?:older|over)\b", "+", value)
    return " ".join(re.findall(r"[a-z0-9.+-]+", value))


def age_range(value: str) -> tuple[int, int] | None:
    m = re.search(r"\b(\d{2,3})\s*(?:\+|(?:years?\s*)?(?:and|or)\s*(?:older|over))", value, re.I)
    if m:
        return int(m[1]), 200
    m = re.search(r"\b(\d{2,3})\s*[-–]\s*(\d{2,3})\b", value)
    return (int(m[1]), int(m[2])) if m else None


def within(a: Scope, b: Scope, field: str) -> bool:
    left, right = canonical(getattr(a, field)), canonical(getattr(b, field))
    if left == right:
        return True
    if not left or not right:
        return False
    if field == "population":
        ar, br = age_range(a.population), age_range(b.population)
        if ar and br:
            # Match the non-age qualifiers too: ages alone cannot establish geography.
            strip = lambda x: re.sub(r"\d+|\+|\b(?:adults?|people|participants?|patients?)\b", "", canonical(x)).strip()
            return br[0] <= ar[0] <= ar[1] <= br[1] and (not strip(b.population) or strip(b.population) in strip(a.population))
    # Explicit declarations cannot override a contradictory numeric age range.
    # They are bound to one parent value rather than a global license.
    if field in a.narrower_than and canonical(a.parent_scope.get(field, "")) == right:
        return True
    return right in left


def sub_scope(a, b) -> bool:
    a, b = getattr(a, "scope", a), getattr(b, "scope", b)
    return (canonical(a.outcome) == canonical(b.outcome)
            and (b.relation == "unknown" or a.relation == b.relation)
            and canonical(a.comparison) == canonical(b.comparison)
            and within(a, b, "population") and within(a, b, "period"))


def answers_scope(a: Scope, b: Scope) -> bool:
    return sub_scope(a, b) and all(canonical(getattr(a, k)) == canonical(getattr(b, k))
                                 for k in ("population", "period"))


def infer_issue_scope(text: str) -> Scope:
    """Conservative legacy migration; new frames supply explicit fields."""
    age = age_range(text)
    population = f"adults {age[0]}+" if age and age[1] == 200 else text.strip()
    period = re.search(r"\bthrough\s+\d{4}\b", text, re.I)
    return Scope(population=population, outcome=text.strip(), period=period[0] if period else "source-reported follow-up")
