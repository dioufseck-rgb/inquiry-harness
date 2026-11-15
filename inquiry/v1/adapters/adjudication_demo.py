"""A scripted test instrument for the source-adjudication fixture family.

It reads only the public input and the tool observations passed to complete();
it never loads fixtures, expectations or source files. It is plumbing for the
kernel checks, not a model and not evidence about one. Its judgments are
keyword rules: a block that names the unit and says "completed" is a report of
completion; a block that says "not completed" is an opposed report; a relay
marker ("told me", "did not attend") means the source was not placed to know.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from ..kernel import PATTERN_REQUIREMENTS

ADJUDICATION = PATTERN_REQUIREMENTS["source_adjudication"]
ATTRIBUTION = PATTERN_REQUIREMENTS["attribution"]
RELAY_MARKERS = ("told me", "informed by", "did not attend", "according to the contractor")
RESOLVERS = {
    "positioning": ("source", "a record from a source placed to observe the inspection, such as the inspector's own log or the test-rig export"),
    "independence": ("source", "a report from an origin other than the contractor, such as the inspector's log or the test-rig export"),
    "opposition": ("person", "the inspector who made the opposing entry, to state which unit and work order it concerns"),
}
QUESTIONS = {
    "positioning": "Was each relied-on source placed to observe or know whether the inspection was completed?",
    "interest": "Is each relied-on source's stake in the inspection identified and weighed?",
    "independence": "Do the relied-on reports rest on different origins?",
    "opposition": "Is every opposed report in the exposed evidence identified and answered?",
    "inference_validity": "Do the relied-on reports, taken together, support the assertion about the inspection?",
    "applicability": "Do the reports concern the unit, work order and date in the question?",
}


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")


class AdjudicationWorker:
    """Scripted worker for the adjudication family. Zero-cost usage records are explicit fixtures."""

    provider = "scripted"
    model = "scripted-adjudication"
    name = "scripted-adjudication"
    is_test_instrument = True

    def __init__(self) -> None:
        self.usage: list[dict[str, Any]] = []

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        payload = json.loads(user)
        self.usage.append({"provider": self.provider, "model": self.model, "input_tokens": 0, "output_tokens": 0,
                           "cost_usd": 0.0, "test_instrument": True})
        if "Review the record for material flaws" in system:
            return json.dumps({"observations": ["The scripted adjudication instrument performs no independent critique; "
                                                "this empty attack set is not a correctness certificate."], "attacks": {}})
        initial = payload["initial"]
        documents, acquisition = self._read_available(initial, payload.get("observations", []))
        if acquisition is not None:
            return json.dumps(acquisition)
        harness = "target_contract" in payload
        current = payload.get("graph")
        graph, response = self._draft(initial, documents, answer=(not harness) or current is not None)
        if not harness:
            return json.dumps({"operation": "finish", "graph": graph, "response": response,
                               "rationale": "A scripted adjudication of the supplied reports; no semantic performance claim."}, ensure_ascii=False)
        if current is None:
            return json.dumps({"operation": "submit", "graph": graph, "response": response,
                               "rationale": "Record the reports, the adjudication and any opposed report before answering it."}, ensure_ascii=False)
        pending = [key for key, attack in current.get("attacks", {}).items()
                   if not attack.get("reply_condition_id") and graph["attacks"].get(key, {}).get("reply_condition_id")]
        if pending:
            return json.dumps({"operation": "submit", "graph": graph, "response": response,
                               "rationale": "Answer the recorded opposition with a located reply from a later revision."}, ensure_ascii=False)
        return json.dumps({"operation": "finish", "response": response,
                           "rationale": "Finish with the recorded adjudication and its remaining open conditions."}, ensure_ascii=False)

    @staticmethod
    def _read_available(initial: dict, observations: list[dict]) -> tuple[list[dict], dict | None]:
        if "corpus" in initial:
            corpus = initial["corpus"]
            bindings = corpus["current_versions"]
            superseded = {(d["supersedes"]["document_id"], d["supersedes"]["version"]) for d in corpus["documents"] if "supersedes" in d}
            by_key = {(d["id"], d["version"]): d for d in corpus["documents"]}
            documents = []
            for d in corpus["documents"]:
                if (d["id"], d["version"]) in superseded or bindings.get(d["id"], d["version"]) != d["version"]:
                    continue
                origins = [d["origin_id"]]
                for ref in d.get("derived_from", []):
                    parent = by_key.get((ref["document_id"], ref["version"]))
                    if parent is not None:
                        origins = [parent["origin_id"]]  # declared lineage resolves to the root origin
                documents.append({"id": d["id"], "version": d["version"], "title": d["title"], "issuer_id": d["issuer_id"],
                                  "issuer_interest": d.get("issuer_interest"), "origin_ids": origins,
                                  "reading_blocks": deepcopy(d["reading_blocks"])})
            return documents, None
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
            unit = initial["question"]["scope"]["unit"].replace("-", " ")
            return [], {"operation": "search", "arguments": {"query": f"{unit} inspection completed", "limit": 100},
                        "rationale": "Find the current records that mention the unit's inspection."}
        documents: dict[tuple[str, str], dict] = {}
        for observation in observations:
            if (observation.get("tool") != "open" or not observation.get("coverage", {}).get("complete_document")
                    or not observation.get("is_current", True)):
                continue
            key = (observation["source_id"], observation["version"])
            meta = candidates.get(key, {})
            documents[key] = {"id": key[0], "version": key[1], "title": observation.get("title", ""),
                              "issuer_id": meta.get("issuer_id", ""), "issuer_interest": observation.get("issuer_interest"),
                              "origin_ids": list(observation.get("origin_ids", [])),
                              "reading_blocks": [{"locator": s["locator"], "text": s["text"]}
                                                 for s in observation["segments"] if s["kind"] == "reading_block"]}
        for key in sorted(candidates):
            if key not in documents:
                return [], {"operation": "open", "arguments": {"source_id": key[0], "version": key[1]},
                            "rationale": "Read the complete current source, keeping exact locators."}
        return list(documents.values()), None

    def _draft(self, initial: dict, documents: list[dict], *, answer: bool) -> tuple[dict, dict]:
        question = initial["question"]
        scope = deepcopy(question["scope"])
        unit = scope["unit"].replace("-", " ")
        label = unit.casefold()
        graph: dict[str, Any] = {"id": "adjudication_inquiry", "revision": 1, "claims": {}, "evidence": {},
                                 "conditions": {}, "arguments": {}, "attacks": {}}

        def evidence(doc: dict, block: dict) -> str:
            eid = f"E_{_slug(doc['id'])}_{_slug(block['locator'])}"
            graph["evidence"][eid] = {"id": eid, "source_id": doc["id"], "source_version": doc["version"],
                                      "locator": block["locator"], "quote": block["text"], "worker_id": "proposer",
                                      "qualifications": ["Supplied fictional record; faithful quotation is not validation of its content."]}
            return eid

        def condition(cid: str, text: str, answer_text: str, evidence_ids: list[str], status: str = "met") -> str:
            graph["conditions"][cid] = {"id": cid, "text": text, "answer": answer_text if status == "met" else "",
                                        "status": status, "evidence_ids": list(evidence_ids) if status == "met" else [],
                                        "performer": self.name, "performer_kind": "model", "revision": 1}
            return cid

        def attribution(doc: dict, block: dict) -> tuple[str, str, str]:
            slug = _slug(doc["id"])
            cid, aid = f"R_{slug}", f"AR_{slug}"
            eid = evidence(doc, block)
            graph["claims"][cid] = {"id": cid, "text": f"{doc['title']} reports: {block['text']}", "kind": "attribution",
                                    "form": "source_reports", "scope": deepcopy(scope)}
            mapping = {key: condition(f"KA_{slug}_{key}", f"Assess {key} of the report in {doc['title']}.",
                                      "The quoted block is a located, current record of the stated issuer at the question's scope.", [eid])
                       for key in ATTRIBUTION}
            graph["arguments"][aid] = {"id": aid, "claim_id": cid, "pattern": "attribution", "premise_ids": [eid],
                                       "conditions": mapping, "scope": deepcopy(scope)}
            return cid, aid, eid

        supporting: list[tuple[dict, dict, bool]] = []
        opposed: list[tuple[dict, dict, dict | None]] = []
        for doc in documents:
            blocks = doc["reading_blocks"]
            clarifier = next((b for b in blocks if f"not {label}" in b["text"].casefold()), None)
            for block in blocks:
                if block is clarifier:
                    continue
                text = block["text"].casefold()
                if "not completed" in text:
                    opposed.append((doc, block, clarifier))
                elif label in text and "completed" in text:
                    supporting.append((doc, block, any(marker in text for marker in RELAY_MARKERS)))
        positioned = [item for item in supporting if not item[2]]
        relied = positioned if len(positioned) >= 2 else supporting
        premises: list[tuple[dict, dict, bool]] = []
        seen: set[str] = set()
        for doc, block, relay in relied:
            if doc["id"] not in seen:
                seen.add(doc["id"])
                premises.append((doc, block, relay))

        premise_ids, premise_evidence = [], []
        for doc, block, _ in premises:
            cid, _, eid = attribution(doc, block)
            premise_ids.append(cid)
            premise_evidence.append(eid)
        origins = {origin for doc, _, _ in premises for origin in doc["origin_ids"]}
        positioning_open = any(relay for _, _, relay in premises)
        independence_open = len(premises) >= 2 and len(origins) < 2

        standing: list[dict] = []
        for doc, block, clarifier in opposed:
            _, raid, _ = attribution(doc, block)
            xid = f"X_{_slug(doc['id'])}"
            attack = {"id": xid, "target_id": "C_target", "kind": "rebut", "support_argument_id": raid, "evidence_ids": [],
                      "grounds": f"{doc['title']} reports: {block['text']}", "scope": deepcopy(scope)}
            if answer and clarifier is not None:
                reid = evidence(doc, clarifier)
                kid = condition(f"K_reply_{_slug(doc['id'])}", f"Does the opposing entry in {doc['title']} concern {unit}?",
                                f"The located entry names another unit: {clarifier['text']}", [reid])
                attack.update(reply_condition_id=kid, reply_evidence_ids=[reid],
                              reply_reason=f"The opposing entry concerns another unit, shown by its located text: {clarifier['text']}")
            else:
                standing.append(doc)
            graph["attacks"][xid] = attack
        opposition_open = bool(standing)

        target_text = (f"The required post-overhaul inspection of {unit} ({scope.get('work_order', '')}) was completed "
                       f"before the unit returned to service on {scope.get('returned_to_service', '')}.")
        graph["claims"]["C_target"] = {"id": "C_target", "text": target_text, "kind": question["target"]["kind"],
                                       "form": question["target"]["form"], "scope": deepcopy(scope),
                                       "target_question_id": question["id"], "target_relation": "direct"}
        interest = "; ".join(f"{doc['title']} ({doc['issuer_id'] or 'issuer per manifest'}): {doc.get('issuer_interest') or 'no declared interest'}"
                             for doc, _, _ in premises)
        answers = {
            "positioning": "Each relied-on source performed, attended or automatically recorded the inspection.",
            "interest": "Declared interests, weighed: " + (interest or "none") + ". An interested report is corroborated by an uninterested origin.",
            "independence": f"The relied-on reports rest on {len(origins)} distinct origins: {', '.join(sorted(origins))}.",
            "opposition": ("No current record reports the inspection as not completed." if not opposed
                           else "Each opposed entry is recorded as a rebut and answered by a located reply."),
            "inference_validity": "Independent reports of completion from placed sources support the assertion; no stronger proposition is drawn.",
            "applicability": "The reports name the unit and work order in the question and precede the return-to-service date.",
        }
        open_keys = {key for key, flag in (("positioning", positioning_open), ("independence", independence_open),
                                           ("opposition", opposition_open)) if flag}
        mapping = {key: condition(f"K_{key}", QUESTIONS[key], answers[key], premise_evidence,
                                  status="open" if key in open_keys else "met") for key in ADJUDICATION}
        if len(premise_ids) >= 2:
            graph["arguments"]["A_target"] = {"id": "A_target", "claim_id": "C_target", "pattern": "source_adjudication",
                                              "premise_ids": premise_ids, "conditions": mapping, "scope": deepcopy(scope)}
        else:
            graph["conditions"]["K_reports"] = {"id": "K_reports", "text": "At least two attributed reports about the inspection are needed.",
                                                "answer": "", "status": "open", "evidence_ids": [], "performer": self.name,
                                                "performer_kind": "model", "revision": 1}
            graph["claims"]["C_target"]["conditions"] = ["K_reports"]
            open_keys.add("reports")

        if standing or open_keys:
            status = "not_established"
        elif len(premises) >= 2 and len(origins) >= 2:
            status = "established"
        else:
            status = "not_established"
        needs = []
        for key in sorted(open_keys):
            kind, hint = RESOLVERS.get(key, ("source", "a further attributed report about the inspection"))
            needs.append({"condition_id": f"K_{key}", "question": QUESTIONS.get(key, graph["conditions"][f"K_{key}"]["text"]),
                          "what_would_resolve": hint[0].upper() + hint[1:] + ".", "resolver_kind": kind, "resolver_hint": hint})
        citations = [{"source_id": e["source_id"], "version": e["source_version"], "locator": e["locator"], "quote": e["quote"]}
                     for e in graph["evidence"].values()]
        text = (f"{status.replace('_', ' ').capitalize()}: {target_text}"
                + (" Opposed report(s) stand unanswered: " + ", ".join(d["title"] for d in standing) + "." if standing else ""))
        response = {"text": text, "assessment": "Scripted adjudication of the supplied reports by keyword rules; not a model judgment.",
                    "target_claim_id": "C_target",
                    "findings": [{"claim_id": "C_target", "text": target_text, "kind": question["target"]["kind"],
                                  "form": question["target"]["form"], "target_question_id": question["id"], "status": status,
                                  "scope": deepcopy(scope), "conditions": [n["question"] for n in needs], "citations": citations}],
                    "information_needs": needs, "inquiry_completed": not standing, "target_scope_answered": True,
                    "caveats": ["Scripted test instrument; not an independent model evaluation or substantive adjudication.",
                                "All findings remain limited to the supplied fictional records and active profile."]}
        return graph, response
