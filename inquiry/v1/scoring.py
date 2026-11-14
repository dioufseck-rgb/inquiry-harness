"""Independent record auditing and explicitly provisional regression assertions.

Nothing in this module infers truth, entailment, or an adequate natural-language
warrant from a status label, a keyword, or a matching quotation. Exact quote
matching establishes a source/exposure relationship only. Substantive outcome
ratings remain pending until separately supplied human adjudication is present.
The evaluator kernel is deliberately not imported.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping

STATUSES = frozenset(
    {"established", "reported", "conditional", "contested", "not_established"}
)
TARGET_RELATIONS = frozenset({"direct", "negated", "record_non_establishment"})
SCORER_VERSION = "record-audit-and-declared-target-0.2"
STRUCTURAL_AUDIT_VERSION = "exact-structural-audit-0.2"
SMOKE_METRIC_VERSION = "categorical-declared-target-0.2"
SMOKE_ORACLE_VERSION = "hardship-categorical-smoke-0.2"
HUMAN_DIMENSIONS = (
    "world_truth", "packet_warrant", "record_warrant", "response_appropriateness"
)
_TARGET_FORMS = {
    "source_reports(P)": ("attribution", "source_reports"),
    "scoped_event_finding": ("substantive", "assertion"),
    "examined_case_specific_causal_finding": ("causal", "causal"),
    "policy_grounded_next_response": ("policy", "rule_consequence"),
    "final_eligibility_assessment": ("policy", "rule_consequence"),
    "universal_population_claim": ("substantive", "universal"),
}


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, Mapping):
        return {str(k): _mapping(v) for k, v in value.items()}
    if isinstance(value, list):
        return {str(v["id"]): _mapping(v) for v in value
                if isinstance(v, Mapping) and "id" in v}
    return {}


def _source_blocks(public_case: Mapping[str, Any]) -> dict[tuple[str, str, str], str]:
    blocks: dict[tuple[str, str, str], str] = {}
    corpus = _mapping(public_case.get("corpus"))
    for document in corpus.get("documents", []):
        if not isinstance(document, Mapping):
            continue
        for block in document.get("reading_blocks", []):
            if isinstance(block, Mapping) and isinstance(block.get("text"), str):
                key = (str(document.get("id")), str(document.get("version")),
                       str(block.get("locator")))
                blocks[key] = block["text"]
        # Table locators follow the public evidence-tool contract. This reads
        # authored cells directly; it does not import the tool or the kernel.
        for table in document.get("tables", []):
            if not isinstance(table, Mapping):
                continue
            prefix = "table:" + str(table.get("id"))
            table_blocks: dict[str, str] = {}
            if table.get("title"):
                table_blocks[prefix + "/title"] = table["title"]
            for column in table.get("columns", []):
                table_blocks[prefix + "/header:" + column] = column
                if column in table.get("column_units", {}):
                    table_blocks[prefix + "/unit:" + column] = table["column_units"][column]
                for row in table.get("rows", []):
                    value = row.get("cells", {}).get(column)
                    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
                    table_blocks[prefix + "/row:" + str(row.get("id")) + "/column:" + column] = text
            for index, note in enumerate(table.get("footnotes", []), start=1):
                table_blocks[prefix + "/footnote:" + str(index)] = note
            for locator, text in table_blocks.items():
                blocks[str(document.get("id")), str(document.get("version")), locator] = text
    return blocks


def _exposed_segments(exposures: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(exposures, list):
        return result
    for event in exposures:
        if not isinstance(event, Mapping) or event.get("phase") != "worker_input":
            continue
        segments = event.get("segments", [event])
        for segment in segments if isinstance(segments, list) else []:
            if isinstance(segment, Mapping):
                result.append({**segment, "worker_id": event.get("worker_id")})
    return result


def evaluation_completion_state(run: Mapping[str, Any]) -> bool | None:
    """Operational evaluator completion, independent of semantic correctness."""
    flag = _mapping(run.get("response")).get("evaluation_completed")
    status = _mapping(run.get("evaluation")).get("evaluation_status")
    if flag is False or (status is not None and status != "complete"):
        return False
    if flag is not None and flag is not True:
        return False
    if flag is True or status == "complete":
        return True
    return None


def _delivery_and_review_checks(response: Mapping[str, Any],
                                public_case: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Validate optional completion declarations without judging artifact prose."""
    checks = []
    for field in ("delivery_completed", "review_completed"):
        if field not in response:
            continue
        value = response[field]
        checks.append({"name": f"{field}:boolean", "passed": isinstance(value, bool),
                       "detail": "Completion declarations must be explicit booleans."})
        checks.append({"name": f"{field}:task_completion_consistent",
                       "passed": not (value is False and response.get("task_completed") is True),
                       "detail": "An explicitly incomplete delivery or configured review cannot accompany a completed task."})
    if response.get("delivery_completed") is True:
        question = _mapping(_mapping(public_case).get("question"))
        required_form = _mapping(question.get("profile")).get("required_form")
        if required_form in {"policy_grounded_next_response", "final_eligibility_assessment"}:
            deliverable = response.get("deliverable")
            checks.append({"name": "declared_delivery_has_required_artifact",
                           "passed": isinstance(deliverable, str) and bool(deliverable.strip()),
                           "detail": "This checks that the requested artifact exists, not that its prose is adequate."})
        if "delivery_defects" in response:
            checks.append({"name": "declared_delivery_has_no_recorded_defects",
                           "passed": response["delivery_defects"] == [],
                           "detail": "A successful delivery declaration cannot retain recorded delivery defects."})
    return checks


def structural_audit(run: Mapping[str, Any], public_case: Mapping[str, Any]) -> dict[str, Any]:
    """Check exact record relationships, without judging what source text means."""
    run = _mapping(run)
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool | None, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    response = _mapping(run.get("response"))
    raw_findings = response.get("findings", [])
    findings = raw_findings if isinstance(raw_findings, list) else []
    check("findings_are_records", isinstance(raw_findings, list)
          and all(isinstance(f, Mapping) for f in findings))
    findings = [dict(f) for f in findings if isinstance(f, Mapping)]
    claim_ids = [f.get("claim_id") for f in findings]
    check("finding_ids_unique", all(isinstance(i, str) and i for i in claim_ids)
          and len(set(claim_ids)) == len(claim_ids))
    target = response.get("target_claim_id")
    if run.get("status") == "failed" and target is None:
        check("target_references_finding", None, "No completed draft to audit.")
    else:
        check("target_references_finding", isinstance(target, str) and target in claim_ids)
    check("finding_status_vocabulary", all(isinstance(f.get("status"), str)
                                            and f["status"] in STATUSES for f in findings))
    check("finding_target_relation_vocabulary", all(
        isinstance(f.get("target_relation", "direct"), str)
        and f.get("target_relation", "direct") in TARGET_RELATIONS for f in findings
    ))
    question_id = _mapping(public_case.get("question")).get("id")
    check("active_question_identity", run.get("question_id") == question_id)
    form_answered = response.get("target_form_answered")
    if form_answered is None:
        check("target_form_gate", None,
              "No runtime form gate was supplied; substantive target adequacy remains pending.")
    else:
        check("target_form_gate", form_answered is True,
              "A declared form mismatch cannot count as answering the requested target; a true flag is not semantic adjudication.")
        check("target_form_completion_consistent", not (form_answered is False and response.get("task_completed") is True))
    evaluation_done = evaluation_completion_state(run)
    check("evaluation_completion_gate", evaluation_done,
          "Operational evaluation completion is not a semantic quality judgment; absent baseline evaluation is unassessed.")
    if evaluation_done is False:
        check("evaluation_task_completion_consistent", response.get("task_completed") is not True)
    evaluation_status = _mapping(run.get("evaluation")).get("evaluation_status")
    if evaluation_status is not None and response.get("evaluation_completed") is not None:
        check("declared_evaluation_matches_record",
              response["evaluation_completed"] is (evaluation_status == "complete"))
    checks.extend(_delivery_and_review_checks(response, public_case))
    target_findings = [f for f in findings if f.get("claim_id") == target]
    if len(target_findings) == 1:
        if target_findings[0].get("target_relation", "direct") != "direct":
            check("target_relation_question_anchor",
                  target_findings[0].get("target_question_id") == question_id,
                  "A non-direct proposition must explicitly name the active question; its prose meaning remains unadjudicated.")
        matches_scope = target_findings[0].get("scope") == _mapping(public_case.get("question")).get("scope")
        check("declared_target_scope_matches_record", response.get("target_scope_answered") is matches_scope,
              "This prototype checks exact explicit scope fields, not natural-language equivalence.")
        if not matches_scope and response.get("task_completed") is True:
            check("component_not_whole_completion", public_case["question"].get("allow_partial_completion") is True)

    source_blocks = _source_blocks(public_case)
    segments = _exposed_segments(run.get("exposures", []))
    graph = _mapping(run.get("graph"))
    evaluation = _mapping(run.get("evaluation"))
    graph_claims = _records(graph.get("claims"))
    graph_evidence = _records(graph.get("evidence"))
    evaluated = _records(evaluation.get("findings"))
    if run.get("graph") is None and run.get("evaluation") is None:
        check("graph_report_alignment", None, "This arm did not return a graph.")
    elif not graph or not evaluation:
        check("graph_report_alignment", False, "Graph and evaluation must be returned together.")

    for finding in findings:
        cid = str(finding.get("claim_id"))
        prefix = f"finding:{cid}"
        citations = finding.get("citations", [])
        check(f"{prefix}:citations_are_records", isinstance(citations, list)
              and all(isinstance(c, Mapping) for c in citations))
        citations = citations if isinstance(citations, list) else []
        for number, citation in enumerate(citations):
            if not isinstance(citation, Mapping):
                continue
            key = (str(citation.get("source_id")), str(citation.get("version")),
                   str(citation.get("locator")))
            quote = citation.get("quote")
            label = f"{prefix}:citation:{number}"
            check(f"{label}:source_version_locator", key in source_blocks)
            quoted = (isinstance(quote, str) and bool(quote)
                      and key in source_blocks and quote in source_blocks[key])
            check(f"{label}:verbatim_source_span", quoted,
                  "Exact span presence checks transcription, not evidential support.")
            seen = any(
                key == (str(s.get("source_id")), str(s.get("version")), str(s.get("locator")))
                and isinstance(s.get("text"), str) and isinstance(quote, str)
                and bool(quote) and quote in s["text"]
                for s in segments
            )
            check(f"{label}:worker_input_exposure", seen,
                  "Tool return alone does not count as worker-input exposure.")

        if graph and evaluation:
            claim = graph_claims.get(cid)
            disposition = evaluated.get(cid)
            check(f"{prefix}:graph_claim_exists", claim is not None)
            check(f"{prefix}:evaluation_exists", disposition is not None)
            if claim is not None:
                check(f"{prefix}:record_text", finding.get("text") == claim.get("text"),
                      "The structured finding must retain the committed claim text; prose is reviewed separately.")
                check(f"{prefix}:record_target_relation",
                      finding.get("target_relation", "direct") == claim.get("target_relation", "direct")
                      and finding.get("target_question_id") == claim.get("target_question_id"),
                      "Declared orientation must retain the committed claim's question anchor and relation.")
            if disposition is not None:
                check(f"{prefix}:evaluated_status", finding.get("status") == disposition.get("status"))
                check(f"{prefix}:evaluated_scope", finding.get("scope") == disposition.get("scope"))
                check(f"{prefix}:evaluated_target_relation",
                      finding.get("target_relation", "direct") == disposition.get("target_relation", "direct")
                      and finding.get("target_question_id") == disposition.get("target_question_id"))
                if "condition_texts" in disposition:
                    check(f"{prefix}:evaluated_conditions",
                          finding.get("conditions", []) == disposition["condition_texts"])
                evidence_ids = disposition.get("evidence_ids", [])
                check(f"{prefix}:evaluated_evidence_exists",
                      isinstance(evidence_ids, list) and all(isinstance(i, str) and i in graph_evidence for i in evidence_ids))
                basis = {
                    (str(e.get("source_id")), str(e.get("source_version")),
                     str(e.get("locator")), str(e.get("quote")))
                    for eid in evidence_ids if isinstance(eid, str) and (e := graph_evidence.get(eid))
                } if isinstance(evidence_ids, list) else set()
                check(f"{prefix}:citations_in_recorded_basis", all(
                    (str(c.get("source_id")), str(c.get("version")),
                     str(c.get("locator")), str(c.get("quote"))) in basis
                    for c in citations if isinstance(c, Mapping)
                ))

    failures = [c["name"] for c in checks if c["passed"] is False]
    unassessed = [c["name"] for c in checks if c["passed"] is None]
    target_present = isinstance(target, str) and bool(target) and len(target_findings) == 1
    status = "fail" if failures else "pass" if target_present else "unassessed"
    return {
        "track": "exact_structural_audit", "audit_version": STRUCTURAL_AUDIT_VERSION,
        "status": status, "checks": checks, "failed_checks": failures,
        "unassessed_checks": unassessed,
        "assessment_coverage": {
            "target_finding_present": target_present,
            "graph_returned": bool(graph), "evaluation_returned": bool(evaluation),
            "passed_checks": sum(c["passed"] is True for c in checks),
            "failed_checks": len(failures), "unassessed_checks": len(unassessed),
        },
        "substantive_validity_established": False,
        "limitations": [
            "A missing target draft cannot pass on vacuously true record checks; unavailable checks are listed separately.",
            "Source-span and exposure checks do not establish truth, relevance, entailment, or attention.",
            "Graph/report agreement does not show that the graph is adequate for the question.",
            "Natural-language response fidelity and appropriate reliance require rubric review.",
        ],
    }


def hardship_smoke_expectation(question_id: str, variant_id: str | None = None) -> dict[str, Any]:
    """Return authored categorical expectations; these are not human outcome gold."""
    variant = variant_id or "baseline"
    valid_variants = {"baseline", *(f"mutation_{i:03d}" for i in range(1, 7))}
    if question_id not in {f"question_{i:03d}" for i in range(1, 7)}:
        raise ValueError(f"Unknown hardship question: {question_id}")
    if variant not in valid_variants:
        raise ValueError(f"Unknown hardship variant: {variant}")
    statuses = {
        "question_001": ["reported"],
        "question_002": ["established"],
        "question_003": ["not_established", "conditional"],
        "question_004": ["established"],
        "question_005": ["not_established", "conditional"],
        "question_006": ["not_established", "conditional"],
    }
    actions = {
        "question_001": ["answer"], "question_002": ["answer"],
        "question_003": ["prepare_assessment", "request_information"],
        "question_004": ["advance_intake"],
        "question_005": ["prepare_assessment", "request_information"],
        "question_006": ["answer"],
    }
    conditions: list[str] = []
    if question_id == "question_002" and variant == "mutation_004":
        statuses[question_id] = ["not_established", "conditional"]
    if question_id == "question_003" and variant == "mutation_003":
        statuses[question_id] = ["established"]
        actions[question_id] = ["prepare_assessment", "answer"]
    if question_id == "question_004" and variant in {"mutation_002", "mutation_005"}:
        actions[question_id] = ["request_information"]
        conditions = (["impact_description", "event_date"] if variant == "mutation_002"
                      else ["prior_payment_declaration"])
    return {
        "oracle_version": SMOKE_ORACLE_VERSION,
        "author": "model_authored", "human_adjudicated": False,
        "kind": "categorical_regression_assertion",
        "question_id": question_id, "variant_id": variant,
        "allowed_target_statuses": statuses[question_id],
        "allowed_next_actions": actions[question_id],
        "required_condition_ids": conditions, "task_completed": True,
        "target_scope_answered": True,
        "limitation": "Passing these categories is not a substantive outcome score or warrant judgment.",
    }


def hardship_smoke_matrix() -> list[dict[str, Any]]:
    return [hardship_smoke_expectation(f"question_{q:03d}", variant)
            for q in range(1, 7)
            for variant in ["baseline", *(f"mutation_{i:03d}" for i in range(1, 7))]]


def _target_status_comparison(run: Mapping[str, Any], target: Mapping[str, Any],
                              expectation: Mapping[str, Any],
                              public_case: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compare declared propositions, without interpreting their natural language.

    Established(P) and established(the record does not establish P) are different
    record claims. Only the latter's explicit, anchored declaration can project
    to a not_established status for P. This is categorical bookkeeping, not a
    decision that the declared relation describes the claim text faithfully.
    """
    relation = target.get("target_relation", "direct")
    claim_status = target.get("status")
    comparison: dict[str, Any] = {
        "claim_status": claim_status, "declared_target_relation": relation,
        "target_question_id": target.get("target_question_id"),
        "compared_target_status": None, "method": "unsupported_relation",
        "semantic_alignment": "pending_human_review",
        "limitation": "Explicit orientation and status categories do not establish that the proposition or prose means what its author declares.",
    }
    checks: list[dict[str, Any]] = []
    if relation == "direct":
        comparison.update(compared_target_status=claim_status, method="direct_status")
        return comparison, checks
    if relation == "negated":
        # Not establishing P does not establish not-P, and this status vocabulary
        # has no general negation transform. Leave the comparison uncheckable.
        comparison["method"] = "negation_not_normalized"
        return comparison, checks
    if relation != "record_non_establishment":
        checks.append({"name": "target_relation_supported", "passed": False})
        return comparison, checks

    question = _mapping(_mapping(public_case).get("question"))
    question_id = question.get("id")
    shape = _TARGET_FORMS.get(_mapping(question.get("profile")).get("required_form"))
    checks.extend([
        {"name": "target_relation_question_anchor", "passed": isinstance(question_id, str)
         and bool(question_id) and target.get("target_question_id") == question_id
         and run.get("question_id") == question_id and expectation.get("question_id") == question_id},
        {"name": "target_relation_scope", "passed": isinstance(question.get("scope"), Mapping)
         and target.get("scope") == question["scope"]},
        {"name": "target_relation_form", "passed": shape is not None
         and (target.get("kind"), target.get("form")) == shape},
    ])
    for name, records in (
        ("graph", _records(_mapping(run.get("graph")).get("claims"))),
        ("evaluation", _records(_mapping(run.get("evaluation")).get("findings"))),
    ):
        if run.get(name) is not None:
            record = records.get(str(target.get("claim_id")), {})
            checks.append({"name": f"target_relation_{name}_alignment", "passed":
                           record.get("target_relation", "direct") == relation
                           and record.get("target_question_id") == question_id})
    if all(check["passed"] for check in checks) and claim_status == "established":
        comparison.update(compared_target_status="not_established",
                          method="declared_record_non_establishment")
    else:
        comparison["method"] = "record_non_establishment_not_normalized"
    return comparison, checks


def categorical_smoke_assertions(run: Mapping[str, Any], expectation: Mapping[str, Any] | None, *,
                                 public_case: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "track": "categorical_regression_assertion", "human_outcome_score": None,
        "metric_version": SMOKE_METRIC_VERSION, "semantic_alignment": "pending_human_review",
        "status": "not_configured", "checks": [],
    }
    if expectation is None:
        return result
    result["oracle_version"] = expectation.get("oracle_version")
    result["expectation"] = deepcopy(dict(expectation))
    response = _mapping(run.get("response"))
    target = response.get("target_claim_id")
    findings = response.get("findings", [])
    findings = findings if isinstance(findings, list) else []
    targets = [f for f in findings if isinstance(f, Mapping) and f.get("claim_id") == target]
    if run.get("status") == "failed" or not isinstance(target, str) or not target or len(targets) != 1:
        result.update(status="not_checkable", reason="A successful, unambiguous target finding is unavailable.")
        return result
    action = _mapping(response.get("next_action"))
    conditions = action.get("condition_ids", [])
    comparison, relation_checks = _target_status_comparison(run, targets[0], expectation, public_case)
    result["target_status_comparison"] = comparison
    compared_status = comparison["compared_target_status"]
    checks = [
        {"name": "target_status", "passed": compared_status in expectation["allowed_target_statuses"]
         if compared_status is not None else None},
        *relation_checks,
        {"name": "next_action", "passed": action.get("kind") in expectation["allowed_next_actions"]},
        {"name": "task_completed", "passed": response.get("task_completed") is expectation["task_completed"]},
        {"name": "target_scope_answered", "passed": response.get("target_scope_answered") is True},
        {"name": "target_form_not_rejected", "passed": response.get("target_form_answered") is None
         or response.get("target_form_answered") is True},
        {"name": "evaluation_not_incomplete", "passed": evaluation_completion_state(run) is not False},
        {"name": "delivery_not_incomplete", "passed": response.get("delivery_completed") is not False},
        {"name": "review_not_incomplete", "passed": response.get("review_completed") is not False},
        *_delivery_and_review_checks(response, public_case),
        {"name": "requested_conditions", "passed": isinstance(conditions, list)
         and all(isinstance(c, str) for c in conditions)
         and set(expectation.get("required_condition_ids", [])) <= set(conditions)},
    ]
    status = ("fail" if any(c["passed"] is False for c in checks) else
              "not_checkable" if any(c["passed"] is None for c in checks) else "pass")
    result.update(checks=checks, status=status)
    if compared_status is None:
        result["reason"] = "The declared target relation cannot be normalized by this categorical metric; semantic review remains pending."
    return result


def human_rubric_review(answer_spec: Mapping[str, Any] | None = None,
                        adjudication: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Retain a separately supplied human decision; never infer one from a run."""
    result: dict[str, Any] = {
        "track": "human_rubric_review", "status": "pending",
        "ratings": {dimension: None for dimension in HUMAN_DIMENSIONS},
        "answer_spec": deepcopy(dict(answer_spec)) if answer_spec else None,
        "reviewer_ids": [], "rubric_version": None,
    }
    if adjudication is None:
        return result
    review = deepcopy(dict(adjudication))
    ratings = review.get("ratings", {})
    valid = (review.get("status") == "adjudicated" and review.get("author_type") == "human"
             and isinstance(review.get("reviewer_ids"), list) and bool(review["reviewer_ids"])
             and all(isinstance(r, str) and r for r in review["reviewer_ids"])
             and bool(review.get("rubric_version")) and isinstance(ratings, Mapping)
             and all(isinstance(ratings.get(d), str)
                     and ratings[d] in {"pass", "fail", "not_applicable"} for d in HUMAN_DIMENSIONS))
    if not valid:
        result.update(status="invalid_adjudication", supplied_review=review,
                      error="Require human authorship, reviewer IDs, rubric version, and four explicit ratings.")
        return result
    result.update(status="adjudicated", ratings=dict(ratings), reviewer_ids=review["reviewer_ids"],
                  rubric_version=review["rubric_version"], adjudication=review)
    return result


def result_fingerprint(run: Mapping[str, Any]) -> str:
    """Bind an outcome review to the exact result, including its record and costs."""
    return sha256(json.dumps(dict(run), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


def score_run(run: Mapping[str, Any], public_case: Mapping[str, Any], *,
              answer_spec: Mapping[str, Any] | None = None,
              smoke_expectation: Mapping[str, Any] | None = None,
              human_adjudication: Mapping[str, Any] | None = None) -> dict[str, Any]:
    fingerprint = result_fingerprint(run)
    human = human_rubric_review(answer_spec, human_adjudication)
    human["review_binding"] = {"run_id": run.get("run_id"), "result_hash": fingerprint}
    if human_adjudication is not None and (
        not run.get("run_id") or human_adjudication.get("run_id") != run.get("run_id")
        or human_adjudication.get("result_hash") != fingerprint
    ):
        human.update(status="invalid_adjudication", ratings={d: None for d in HUMAN_DIMENSIONS},
                     error="Outcome adjudication is not bound to this exact run and result hash.")
    return {
        "scorer_version": SCORER_VERSION,
        "structural": structural_audit(run, public_case),
        "smoke": categorical_smoke_assertions(run, smoke_expectation, public_case=public_case),
        "human": human,
    }
