"""A narrow, deterministic development instrument for the fictional case.

This is scripted integration plumbing, NOT a model, an independent adjudicator,
or evidence of reasoning performance. It reads only the actual public input and
tool observations passed to complete(). It never loads packets, oracle data,
question-ID outcomes, experiment scores, or source files.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import re
from typing import Any


_REQUIREMENTS = {
    "attribution": ("attribution", "applicability"),
    "document_record": ("record_warrant", "applicability"),
    "rule_application": ("authority", "antecedents", "inference_validity", "applicability"),
    "process_trace": ("trace_links", "alternatives", "inference_validity", "applicability"),
}


class DemoWorker:
    """Scripted smoke-test worker. Zero token/cost records are explicit fixtures."""

    provider = "demo"
    model = "demo"
    name = "demo"
    is_test_instrument = True

    def __init__(self) -> None:
        self.usage: list[dict[str, Any]] = []

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        payload = json.loads(user)
        self.usage.append({"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "test_instrument": True})
        if "Review the record for material flaws" in system:
            return json.dumps({"observations": ["The deterministic demo instrument performs no substantive independent critique; this empty attack set is not a correctness certificate."], "attacks": {}})
        if payload.get("draft_response") is not None:
            return json.dumps({"operation": "finish", "graph": payload.get("graph"), "response": payload["draft_response"], "rationale": "Finish the scripted development run with the recorded draft and its remaining conditions."})
        initial = payload["initial"]
        observations = payload.get("observations", [])
        documents, acquisition = self._read_available(initial, observations)
        if acquisition is not None:
            return json.dumps(acquisition)
        graph, response = self._draft(initial, documents)
        return json.dumps({"operation": "submit", "graph": graph, "response": response, "rationale": "A deterministic, content-based smoke-test draft for the supplied fictional records; no semantic performance claim."}, ensure_ascii=False)

    @staticmethod
    def _read_available(initial: dict, observations: list[dict]) -> tuple[list[dict], dict | None]:
        if "corpus" in initial:
            corpus = initial["corpus"]
            bindings = {ref["document_id"]: ref["version"] for key, ref in corpus.items() if key != "documents" and isinstance(ref, dict) and {"document_id", "version"} <= ref.keys()}
            superseded = {(d["supersedes"]["document_id"], d["supersedes"]["version"]) for d in corpus["documents"] if "supersedes" in d}
            current = [deepcopy(d) for d in corpus["documents"] if (d["id"], d["version"]) not in superseded and bindings.get(d["id"], d["version"]) == d["version"]]
            return current, None
        candidates: dict[tuple[str, str], dict] = {}
        for entry in initial.get("source_manifest", []):
            if entry.get("is_current", True):
                candidates[entry["source_id"], entry["version"]] = entry
        searches = [o for o in observations if o.get("tool") == "search"]
        for search in searches:
            for hit in search.get("hits", []):
                if hit.get("is_current", True):
                    candidates[hit["source_id"], hit["version"]] = hit
        if not candidates and not searches:
            return [], {"operation": "search", "arguments": {"query": "policy application flooding workshop payroll income statement", "limit": 100}, "rationale": "Discover the current supplied records in the deterministic corpus."}
        documents = {}
        for observation in observations:
            if observation.get("tool") != "open" or not observation.get("coverage", {}).get("complete_document") or not observation.get("is_current", True):
                continue
            key = (observation["source_id"], observation["version"])
            documents[key] = {"id": key[0], "version": key[1], "title": observation.get("title", ""), "reading_blocks": [{"locator": s["locator"], "text": s["text"]} for s in observation["segments"] if s["kind"] == "reading_block"]}
        for key in sorted(candidates):
            if key not in documents:
                return [], {"operation": "open", "arguments": {"source_id": key[0], "version": key[1]}, "rationale": "Read the complete current source, retaining exact block locators and qualifications."}
        return list(documents.values()), None

    @staticmethod
    def _draft(initial: dict, documents: list[dict]) -> tuple[dict, dict]:
        question = initial["question"]
        context = initial["shared_context"]
        scope = deepcopy(question["scope"])
        form = question["profile"]["required_form"]
        graph: dict[str, Any] = {"id": "demo_inquiry", "revision": 1, "claims": {}, "evidence": {}, "conditions": {}, "arguments": {}, "attacks": {}, "current_source_versions": {d["id"]: d["version"] for d in documents}}
        by_role = {}
        for document in documents:
            title = document.get("title", "").casefold()
            contents = "\n".join(b["text"] for b in document["reading_blocks"])
            if "response and eligibility policy" in title:
                by_role["policy"] = document
            elif "application statement" in title or "Applicant:" in contents and "Signed declaration:" in contents:
                by_role["account"] = document
            elif "incident bulletin" in title:
                by_role["event"] = document
            elif all(term in contents.casefold() for term in ("roster", "payroll", "site-closure order")):
                by_role["trace"] = document

        def blocks(role: str) -> dict[str, str]:
            return {b["locator"]: b["text"] for b in by_role.get(role, {}).get("reading_blocks", [])}

        def evidence(role: str, locators: list[str] | None = None) -> list[str]:
            document = by_role.get(role)
            if document is None:
                return []
            ids = []
            for block in document["reading_blocks"]:
                if locators is not None and block["locator"] not in locators:
                    continue
                identifier = "E_" + role + "_" + re.sub(r"[^A-Za-z0-9_]", "_", block["locator"])
                graph["evidence"][identifier] = {"id": identifier, "source_id": document["id"], "source_version": document["version"], "locator": block["locator"], "quote": block["text"], "worker_id": "proposer", "qualifications": ["Supplied fictional record; faithful quotation is not independent validation of its content."]}
                ids.append(identifier)
            return ids

        def condition(identifier: str, text: str, evidence_ids: list[str], met: bool = True) -> str:
            graph["conditions"][identifier] = {"id": identifier, "text": text, "status": "met" if met else "open", "evidence_ids": evidence_ids, "performer": "demo", "performer_kind": "model", "revision": 1}
            return identifier

        def argument(pattern: str, evidence_ids: list[str], reasons: dict[str, str], open_keys: set[str] | None = None) -> None:
            open_keys = open_keys or set()
            mapping = {}
            for key in _REQUIREMENTS[pattern]:
                cid = "K_" + key
                mapping[key] = condition(cid, reasons[key], evidence_ids, met=key not in open_keys)
                if key in open_keys:
                    graph["claims"]["C_target"]["conditions"].append(cid)
            graph["arguments"]["A_target"] = {"id": "A_target", "claim_id": "C_target", "pattern": pattern, "premise_ids": evidence_ids, "conditions": mapping, "scope": deepcopy(scope)}

        def target(text: str, kind: str, claim_form: str) -> None:
            graph["claims"]["C_target"] = {"id": "C_target", "text": text, "kind": kind, "form": claim_form, "scope": deepcopy(scope), "conditions": []}

        def gap(identifier: str, text: str, ids: list[str], *, target_dependency: bool = True) -> str:
            condition(identifier, text, ids, met=False)
            if target_dependency:
                graph["claims"]["C_target"]["conditions"].append(identifier)
            return identifier

        account = blocks("account")
        policy = blocks("policy")
        statement = account.get("field_group_2", "")
        declaration = account.get("field_group_3", "")
        event_date = re.search(r"\b(?:on )?(\d{1,2} [A-Za-z]+ \d{4})\b", statement)
        impact_missing = not statement or "description: not provided" in statement.casefold()
        date_missing = event_date is None or "event date for the claimed impact: not provided" in statement.casefold()
        next_action = {"kind": "answer", "description": "Return the scoped analysis; no external action is authorized.", "condition_ids": []}
        status = "not_established"
        answer = ""
        deliverable = ""

        if form == "source_reports(P)":
            ids = evidence("account")
            identity = re.search(r"Applicant:\s*([^(.]+)", account.get("field_group_1", ""))
            name = identity.group(1).strip() if identity else "The applicant"
            if not ids:
                target("The applicant's current financial-impact account is available for an attributed summary.", "attribution", "source_reports")
                gap("K_account", "The current applicant statement must be supplied.", [])
            else:
                text = f"{name}'s current application records: {statement}" if impact_missing else f"{name} reports: {statement}"
                target(text, "attribution", "source_reports")
                argument("attribution", ids, {"attribution": "The quoted current application is the located account; its speaker and reported details are retained.", "applicability": "The summary concerns this applicant's current statement only, without independently establishing the reported causal account."})
                status = "reported"
            answer = graph["claims"]["C_target"]["text"]

        elif form == "scoped_event_finding":
            ids = evidence("event")
            event_text = "\n".join(blocks("event").values())
            area = scope.get("location_name", "the requested area")
            target(f"Street flooding occurred within {area} during {scope.get('period', 'the requested period')}.", "substantive", "assertion")
            observed = re.search(r"recorded street flooding in (.+?),.*?on (\d{1,2} [A-Za-z]+ \d{4}) between (\d{2}:\d{2}) and (\d{2}:\d{2})", event_text, re.IGNORECASE)
            matches = False
            if observed:
                day = datetime.strptime(observed.group(2), "%d %B %Y").date().isoformat()
                expected_period = day + "T" + observed.group(3) + "/" + day + "T" + observed.group(4)
                matches = observed.group(1).casefold() == area.casefold() and scope.get("period") == expected_period
            reason = "The bulletin's observed location and period match the requested bounded occurrence claim." if matches else "The current bulletin does not supply an observation at the requested location and period; a withdrawn or differently located observation does not establish absence there."
            if ids:
                argument("document_record", ids, {"record_warrant": "The supplied source is the current authenticated field bulletin, used under the stated record profile.", "applicability": reason}, set() if matches else {"applicability"})
            else:
                gap("K_event_record", "A relevant current event record is unavailable.", [])
            status = "established" if matches else "not_established"
            answer = graph["claims"]["C_target"]["text"] if matches else reason
            if not matches:
                next_action = {"kind": "answer", "description": "The requested-location finding remains unsupported by the corrected record. A current observation for that location could settle the gap; do not infer that it was dry.", "condition_ids": graph["claims"]["C_target"]["conditions"][:]}

        elif form == "examined_case_specific_causal_finding":
            ids = evidence("account") + evidence("event") + evidence("trace")
            trace_blocks = blocks("trace")
            trace = "\n".join(trace_blocks.values()).casefold()
            required = ("personally inspected flooding", "only approved access route", "no other closure cause is recorded", "site-closure order", "accrued zero credits", "no replacement shift or compensating payment", "not copied from the applicant")
            roster = trace_blocks.get("roster_row_17", "")
            operations = trace_blocks.get("operations_log", "")
            subject, workplace = scope.get("subject_id"), scope.get("workplace_id")
            target_date = datetime.strptime(scope["event_date"], "%Y-%m-%d") if scope.get("event_date") else None
            day_month = f"{target_date.day} {target_date.strftime('%B')}" if target_date else ""
            reported_amount = re.search(r"\b(\d+) programme credits\b", statement)
            trace_amount = re.search(r"\bwould accrue (\d+) credits\b", trace_blocks.get("payroll_row_17", ""))
            matches_target = bool(subject and subject in roster and workplace and workplace in roster and workplace in operations and day_month and day_month in roster and day_month in operations and reported_amount and trace_amount and reported_amount.group(1) == trace_amount.group(1))
            trace_present = all(term in trace for term in required) and matches_target
            target("Flood-related workplace closure caused this applicant to lose the reported scheduled shift and its associated wages, within the specified case and date.", "causal", "causal")
            if len(ids) >= 2:
                argument("process_trace", ids, {"trace_links": "The supplied employer operations, roster and payroll extract independently links the observed access flooding, closure, scheduled shift and foregone wages." if trace_present else "Independent records connecting flooding to closure, closure to this person's scheduled shift, and cancellation to foregone wages are missing.", "alternatives": "The trace records the otherwise-operable workplace, no leave or alternative assignment, and no replacement pay; it does not claim to eliminate every imaginable alternative." if trace_present else "The available applicant account and area bulletin do not independently resolve the individual closure, schedule and wage alternatives.", "inference_validity": "The causal claim is limited to the identified event, person and shift; neither area flooding nor attribution alone is sufficient.", "applicability": "The extracted records are assessed for the applicant, workplace, date and outcome stated in the active question."}, set() if trace_present else {"trace_links", "alternatives"})
            else:
                gap("K_trace", "Independent operational, scheduling and payroll records are required for this requested examination.", ids)
            status = "established" if trace_present else "not_established"
            answer = "The supplied employer trace supports the specified one-shift causal finding." if trace_present else "The applicant reports this loss, but the supplied area bulletin and account do not independently establish the individual causal chain."
            if not trace_present:
                next_action = {"kind": "request_information", "description": "For this independent research use, obtain records connecting closure, the scheduled shift and lost wages; this is not an intake evidence demand.", "condition_ids": graph["claims"]["C_target"]["conditions"][:]}

        elif form == "policy_grounded_next_response":
            ids = evidence("policy") + evidence("account")
            intake_rule = policy.get("section_2", "")
            payment_required = "signed yes-or-no self-declaration" in intake_rule.casefold()
            payment_missing = "prior-payment self-declaration: not supplied" in declaration.casefold()
            needed = []
            if impact_missing:
                needed.append(("impact_description", "personal financial-disruption description"))
            if date_missing:
                needed.append(("event_date", "event date for the claimed impact"))
            if payment_required and payment_missing:
                needed.append(("prior_payment_declaration", "signed yes-or-no self-declaration about previous programme payment for the same event"))
            description = "Acknowledge receipt and request only the missing " + "; ".join(text for _, text in needed) + " before advancing intake." if needed else "Acknowledge the complete signed impact account and advance intake to review of the separate final-eligibility requirements."
            target("The next permitted intake response is: " + description, "policy", "rule_consequence")
            if ids and intake_rule:
                argument("rule_application", ids, {"authority": "The currently bound supplied programme policy governs preparation of this intake response, without granting award or payment authority.", "antecedents": "The current application either supplies the statement fields or explicitly records the missing fields; these facts select the policy's acknowledgment-and-clarification or advance-intake branch.", "inference_validity": "Apply the policy's response rule to those case facts; a request for missing intake information is a complete next-response finding, not a final eligibility decision.", "applicability": "Use the policy version currently supplied for this case's intake stage and as-of date; independent personal-impact proof is not added."})
                status = "established"
            else:
                gap("K_policy", "A current applicable intake policy and application are required.", ids)
            for cid, text in needed:
                gap(cid, "Before advancing intake, obtain the missing " + text + ".", ids, target_dependency=False)
            next_action = {"kind": "request_information" if needed else "advance_intake", "description": description, "condition_ids": [cid for cid, _ in needed]}
            answer = description
            deliverable = ("Thank you for your application. Please provide " + "; ".join(text for _, text in needed)
                           + ". Your own signed statement satisfies the intake impact-evidence requirement. "
                           "We will review the separate final-eligibility requirements after intake is complete."
                           if needed else "Thank you for your complete signed statement. It satisfies the intake impact-evidence requirement. "
                           "Your application can proceed to review of the separate final-eligibility requirements; no award decision has been made.")

        elif form == "final_eligibility_assessment":
            ids = evidence("policy") + evidence("account")
            target("The supplied record establishes final eligibility for this applicant under the current programme policy.", "policy", "rule_consequence")
            missing = []
            for cid, label, marker in (("K_residence", "residence-register extract", "residence-register extract: not supplied"), ("K_household_income", "specified household income statement", "household income statement: not supplied"), ("K_payment_register", "programme payment-register clearance", "programme payment-register clearance: not supplied")):
                if marker in declaration.casefold():
                    missing.append((cid, label))
            if impact_missing or date_missing:
                missing.append(("K_complete_impact_account", "complete signed impact description and event date"))
            if ids:
                argument("rule_application", ids, {"authority": "The current programme policy supplies the final-stage rule and accepted evidence kinds.", "antecedents": "Final eligibility still needs the required " + ", ".join(label for _, label in missing) + "; missing records do not establish failure of their substantive conditions.", "inference_validity": "Final eligibility requires all stated elements; intake sufficiency cannot substitute for the separate required final-stage records.", "applicability": "The rule is examined at the final-eligibility stage for the named case and event date."}, {"antecedents"})
            for cid, label in missing:
                gap(cid, "Obtain and assess the required " + label + ".", ids)
            answer = "Final eligibility remains undetermined because the required final-stage records are not supplied; this is not a finding of ineligibility."
            deliverable = answer + " Missing evidence: " + "; ".join(label for _, label in missing) + ". "
            deliverable += ("The intake impact statement still needs its missing details. " if impact_missing or date_missing
                            else "The policy accepts the supplied signed impact statement for the disruption requirement. ")
            deliverable += "Obtain and assess the outstanding records before a final determination; no award or payment is authorized."
            next_action = {"kind": "request_information", "description": "Obtain and assess the missing final-stage records for review; do not approve, refuse or pay an award.", "condition_ids": [cid for cid, _ in missing]}

        elif form == "universal_population_claim":
            ids = evidence("event") + evidence("account") + evidence("trace")
            target("Every worker in the question's population lost wage income because of the flooding during the specified period.", "substantive", "universal")
            gap("K_population", "The available area and individual records do not supply complete worker-population coverage or a universal rule.", ids)
            answer = "The universal claim is not established. The records concern an area event and one applicant; no particular unaffected worker or refutation is supplied."
            next_action = {"kind": "answer", "description": "Limit publication to supported area or individual findings, or obtain an adequate population-coverage basis; do not assert a hidden counterexample.", "condition_ids": graph["claims"]["C_target"]["conditions"][:]}
        else:
            raise ValueError("The deterministic demo instrument does not support this question form")

        citations = [{"source_id": e["source_id"], "version": e["source_version"], "locator": e["locator"], "quote": e["quote"]} for e in graph["evidence"].values()]
        target_record = graph["claims"]["C_target"]
        open_texts = [graph["conditions"][cid]["text"] for cid in target_record["conditions"]]
        response = {"text": answer, "deliverable": deliverable, "target_claim_id": "C_target", "findings": [{"claim_id": "C_target", "text": target_record["text"], "status": status, "scope": deepcopy(scope), "conditions": open_texts, "citations": citations}], "next_action": next_action, "task_completed": True, "target_scope_answered": True, "caveats": ["Deterministic scripted development instrument; not an independent model evaluation or substantive adjudication.", "All findings remain limited to the supplied fictional records and active profile; execution is not authorized."]}
        return graph, response
