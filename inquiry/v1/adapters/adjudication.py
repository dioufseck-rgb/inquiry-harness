"""The source-adjudication fixture family: twelve public requests, expectations held apart.

``cases.json`` holds the public requests and nothing else; ``expectations.json``
holds the expected statuses and completion expectations under the keys the
categorical scorer supports. A request is validated, including the forbidden
private keys, before any worker sees it.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Sequence

from ..experiments import ExperimentCase

FAMILY_ID = "adjudication"
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "adjudication"
CASES_PATH = DATA_DIR / "cases.json"
EXPECTATIONS_PATH = DATA_DIR / "expectations.json"
CASE_TYPES = ("corroborated", "interested_only", "opposed_unanswered", "opposed_answered", "superseded", "hearsay")
VARIANTS = ("pump", "compressor")
LIMITATION = "Passing these categories is not a substantive outcome score or warrant judgment."


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_adjudication_cases(case_ids: Sequence[str] | None = None) -> list[ExperimentCase]:
    """Build the runner's cases; the expectation file is read here and nowhere in a worker's path."""
    cases = _read(CASES_PATH)
    expectations = _read(EXPECTATIONS_PATH)
    if set(cases) != set(expectations["cases"]):
        raise ValueError("The adjudication cases and expectations do not name the same case set.")
    selected = list(case_ids) if case_ids else list(cases)
    unknown = [case_id for case_id in selected if case_id not in cases]
    if unknown:
        raise ValueError(f"Unknown adjudication cases: {unknown}")
    version = expectations["oracle_version"]
    result = []
    for case_id in selected:
        public = deepcopy(cases[case_id])
        private = expectations["cases"][case_id]
        smoke = {"oracle_version": version, "author": "model_authored", "human_adjudicated": False,
                 "kind": "categorical_regression_assertion", "question_id": public["question"]["id"],
                 "variant_id": private["variant"], **deepcopy(private["smoke"]), "limitation": LIMITATION}
        oracle = {"oracle_version": version, "case_type": private["case_type"], "variant": private["variant"],
                  "expected_mechanism": private["expected_mechanism"]}
        result.append(ExperimentCase(case_id=case_id, family_id=FAMILY_ID, public_case=public, oracle=oracle,
                                     question_id=public["question"]["id"], variant_id=private["variant"],
                                     smoke_expectation=smoke))
    return result


def adjudication_case(case_id: str) -> ExperimentCase:
    return load_adjudication_cases([case_id])[0]
