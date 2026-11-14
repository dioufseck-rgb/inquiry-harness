"""Deterministic founded-argument fragment for the first v1 slice.

This is not the full contract catalogue, ASPIC+, or Carneades. Natural-language
support and applicability are attributed Condition assessments, not deductions
made by this module. Code checks those assessments' records, a fixed catalogue
of obligations, exact scopes, exposed quotations, source versions, founded
support, conditionality, lineage, and a finite grounded defeat graph.

Arguments expand to concrete derivations rather than consulting changing claim
labels. A repeated claim on a support path is excluded; mutual *attacks* remain
valid and can be UNDECIDED. Attack edges are fixed before labelling. Exhaustion
never certifies a truncated graph. All caller-supplied actor/revision metadata
must be protected by the controller if workers are untrusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
import json
from typing import Any

from .models import (
    Argument, Attack, Claim, ClaimFinding, Condition, Evaluation,
    InquiryGraph, Profile, Scope,
)


PATTERN_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "attribution": ("attribution", "applicability"),
    "document_record": ("record_warrant", "applicability"),
    "rule_application": ("authority", "antecedents", "inference_validity", "applicability"),
    "conjunction": ("joint_rule", "inference_validity", "applicability"),
    "composition": ("joint_rule", "inference_validity", "applicability"),
    "bounded_absence": ("coverage", "detection", "absence_strength", "inference_validity", "applicability"),
    "process_trace": ("trace_links", "alternatives", "inference_validity", "applicability"),
}

PATTERN_FORMS: dict[str, tuple[str, ...]] = {
    "attribution": ("source_reports",),
    "document_record": ("assertion", "conditional", "presupposition_failure"),
    "rule_application": ("rule_consequence",),
    "conjunction": ("conjunction",),
    "composition": ("conjunction",),
    "bounded_absence": ("bounded_absence",),
    "process_trace": ("causal",),
}

# These names identify empirical premises that may be explicitly hypothesized.
# Validity, joint rules, authority, actual attribution, and performed coverage
# checks cannot be assumed into existence, even under a permissive profile.
PATTERN_ASSUMABLE: dict[str, tuple[str, ...]] = {
    "attribution": (),
    "document_record": ("record_warrant", "applicability"),
    "rule_application": ("antecedents", "applicability"),
    "conjunction": ("applicability",),
    "composition": ("applicability",),
    "bounded_absence": ("detection",),
    "process_trace": ("trace_links", "applicability"),
}

SUPPORTED_FORMS = {
    "assertion", "source_reports", "rule_consequence", "conjunction",
    "bounded_absence", "causal", "presupposition_failure", "conditional",
}


def _form(claim: Claim) -> str:
    if claim.kind == "attribution" or claim.form == "source_reports":
        return "source_reports"
    if claim.form != "assertion":
        return claim.form
    return {
        "policy": "rule_consequence", "conjunction": "conjunction",
        "absence": "bounded_absence", "causal": "causal",
        "presupposition_failure": "presupposition_failure",
    }.get(claim.kind, "assertion")


def _scope_key(scope: Scope) -> str | None:
    try:
        return json.dumps(scope.root, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return None


def _get(record: Any, name: str, default: Any = None) -> Any:
    return record.get(name, default) if isinstance(record, dict) else getattr(record, name, default)


@dataclass
class _Basis:
    dependencies: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)
    origins: set[str] = field(default_factory=set)
    # Evidence used only to assess a condition is provenance, not an additional
    # independent observation for the profile's minimum-origin guard.
    support_origins: set[str] = field(default_factory=set)
    assumptions: set[str] = field(default_factory=set)
    contexts: set[str] = field(default_factory=set)
    qualifications: set[str] = field(default_factory=set)
    arguments: set[str] = field(default_factory=set)
    claims: set[str] = field(default_factory=set)

    def merge(self, other: _Basis) -> None:
        for key in self.__dataclass_fields__:
            getattr(self, key).update(getattr(other, key))

    def clone(self) -> _Basis:
        copied = _Basis()
        copied.merge(self)
        return copied


@dataclass
class _Node:
    id: str
    kind: str
    record_id: str
    conclusion: str | None
    basis: _Basis


class _LimitReached(Exception):
    pass


class _Evaluator:
    def __init__(self, graph: InquiryGraph, profile: Profile, evidence_context: Any):
        self.graph = graph
        self.profile = profile
        self.env = evidence_context
        self.result = Evaluation(
            graph_id=graph.id, graph_revision=graph.revision,
            profile_id=profile.id, profile_version=profile.version,
            current_source_versions=dict(getattr(evidence_context, "current_versions", {}) or {}),
        )
        self.diagnostic_keys: set[tuple[str, str, str]] = set()
        self.invalid_ids: set[str] = set()
        self.evidence_basis: dict[str, _Basis] = {}
        self.nodes: dict[str, _Node] = {}
        self.node_keys: dict[tuple[Any, ...], str] = {}
        self.by_claim: dict[str, list[str]] = {cid: [] for cid in graph.claims}
        self.argument_nodes: dict[str, list[str]] = {aid: [] for aid in graph.arguments}
        self.attack_nodes: dict[str, list[str]] = {aid: [] for aid in graph.attacks}
        self.arguments_for_claim: dict[str, list[Argument]] = {}
        self.valid_arguments: dict[str, _Basis] = {}
        self.claim_bases: dict[str, _Basis] = {}
        self.superseded: set[str] = set()
        self.work = 0
        self.edges: set[tuple[str, str]] = set()
        self.aliases: dict[str, set[str]] = {}

    def diagnostic(self, code: str, record_id: str, detail: str = "") -> None:
        key = (code, record_id, detail)
        if key not in self.diagnostic_keys:
            self.diagnostic_keys.add(key)
            self.result.diagnostics.append({"code": code, "record_id": record_id, "detail": detail})

    def tick(self) -> None:
        self.work += 1
        if self.work > self.profile.max_evaluation_steps:
            raise _LimitReached("evaluation_work_limit")

    def check_ids(self) -> None:
        seen: set[str] = set()
        for collection in (self.graph.claims, self.graph.evidence, self.graph.conditions,
                           self.graph.arguments, self.graph.attacks):
            for key, record in collection.items():
                if not key.strip() or record.id != key or key in seen:
                    self.invalid_ids.add(key)
                    self.diagnostic("invalid_or_colliding_id", key)
                seen.add(key)

    def validate_evidence(self) -> None:
        versions = self.result.current_source_versions
        lookup = getattr(self.env, "source_lookup", {}) or {}
        verifier = getattr(self.env, "verify_quote", None)
        for eid, evidence in sorted(self.graph.evidence.items()):
            self.tick()
            if eid in self.invalid_ids:
                continue
            if not all((evidence.source_id.strip(), evidence.source_version.strip(),
                        evidence.locator.strip(), evidence.quote.strip(), evidence.worker_id.strip())):
                self.diagnostic("incomplete_evidence_record", eid)
                continue
            source = lookup.get((evidence.source_id, evidence.source_version))
            if source is None:
                source = lookup.get(f"{evidence.source_id}@{evidence.source_version}")
            if source is None or verifier is None:
                self.diagnostic("source_or_verifier_unavailable", eid)
                continue
            try:
                check = verifier(evidence.worker_id, evidence.source_id,
                                 evidence.source_version, evidence.quote, locator=evidence.locator)
            except Exception as exc:  # Failed acquisition must not certify evidence.
                self.diagnostic("quote_verification_failed", eid, type(exc).__name__)
                continue
            if _get(check, "valid") is not True:
                self.diagnostic("quote_not_verified", eid, str(_get(check, "reason", "unknown")))
                continue
            if evidence.source_id not in versions:
                self.diagnostic("current_source_version_unknown", eid)
                continue
            current = versions[evidence.source_id] == evidence.source_version and _get(check, "is_current", True)
            if not current and not self.profile.allow_historical_sources:
                self.diagnostic("superseded_source", eid)
                continue
            actual = _get(source, "root_origin_ids", None)
            if actual is None:
                actual = _get(source, "origin_ids", None)
            if actual is None:
                origin = _get(source, "origin_id", None)
                actual = [origin] if origin else []
            origins = {v for v in actual if isinstance(v, str) and v} if isinstance(actual, (list, tuple, set)) else set()
            if evidence.origin_ids and set(evidence.origin_ids) != origins:
                self.diagnostic("proposed_origin_mismatch", eid, "using source lookup lineage")
            if not origins:
                self.diagnostic("origin_unresolved", eid)
            basis = _Basis(dependencies={eid}, evidence={eid}, origins=origins,
                           support_origins=set(origins), qualifications=set(evidence.qualifications))
            if not current:
                basis.qualifications.add(f"historical source {evidence.source_id}@{evidence.source_version}")
            self.evidence_basis[eid] = basis

    def condition(self, cid: str, *, may_assume: bool) -> _Basis | None:
        condition = self.graph.conditions.get(cid)
        if condition is None or cid in self.invalid_ids:
            self.diagnostic("missing_condition", cid)
            return None
        if not condition.text.strip() or condition.revision < 1 or condition.revision > self.graph.revision:
            self.diagnostic("invalid_condition_record", cid)
            return None
        if condition.status in {"open", "reopened"}:
            self.diagnostic("condition_unresolved", cid, condition.status)
            return None
        if not condition.performer or condition.performer_kind not in self.profile.allowed_performer_kinds:
            self.diagnostic("condition_performer_missing_or_disallowed", cid)
            return None
        if self.profile.trusted_performers and self.profile.trusted_performers.get(condition.performer) != condition.performer_kind:
            self.diagnostic("condition_performer_not_authenticated", cid)
            return None
        basis = _Basis(dependencies={cid})
        if condition.status == "assumed":
            if not (may_assume and self.profile.allow_conditional
                    and condition.assumption_kind in {"conditional_premise", "scenario_input"}
                    and condition.context_id):
                self.diagnostic("assumption_not_permitted", cid)
                return None
            basis.assumptions.add(cid)
            basis.contexts.add(condition.context_id)
        elif condition.assumption_kind:
            self.diagnostic("met_condition_has_assumption_mode", cid)
            return None
        elif not condition.evidence_ids:
            self.diagnostic("condition_without_support", cid)
            return None
        if condition.context_id:
            if not self.profile.allow_conditional:
                self.diagnostic("conditional_context_not_permitted", cid)
                return None
            basis.contexts.add(condition.context_id)
            basis.assumptions.add(cid)
        for eid in condition.evidence_ids:
            if eid not in self.evidence_basis:
                self.diagnostic("condition_evidence_not_admitted", cid, eid)
                return None
            evidence_basis = self.evidence_basis[eid].clone()
            evidence_basis.support_origins.clear()
            basis.merge(evidence_basis)
        return basis

    def validate_claims(self) -> None:
        for cid, claim in sorted(self.graph.claims.items()):
            self.tick()
            if cid in self.invalid_ids:
                continue
            if not claim.text.strip() or claim.revision < 1 or claim.revision > self.graph.revision:
                self.diagnostic("invalid_claim_record", cid)
                continue
            if _form(claim) not in SUPPORTED_FORMS:
                self.diagnostic("unsupported_claim_form", cid, _form(claim))
                continue
            if self.profile.allowed_claim_kinds and claim.kind not in self.profile.allowed_claim_kinds:
                self.diagnostic("claim_kind_not_permitted", cid, claim.kind)
                continue
            if not claim.scope.root or _scope_key(claim.scope) is None:
                self.diagnostic("scope_missing_or_invalid", cid)
                continue
            missing = [key for key in self.profile.required_scope_fields
                       if key not in claim.scope.root or claim.scope.root[key] in (None, "", [], {})]
            if missing:
                self.diagnostic("required_scope_field_missing", cid, ",".join(missing))
                continue
            basis = _Basis(dependencies={cid}, claims={cid})
            good = True
            for condition_id in claim.conditions:
                condition_basis = self.condition(condition_id, may_assume=True)
                if condition_basis is None:
                    good = False
                else:
                    basis.merge(condition_basis)
            if good:
                self.claim_bases[cid] = basis

        # Supersession is recorded separately from evidential success. Invalid
        # reference chains cannot silently erase a usable prior claim.
        for cid, claim in sorted(self.graph.claims.items()):
            if not claim.supersedes or cid not in self.claim_bases:
                continue
            old = self.graph.claims.get(claim.supersedes)
            if old is None or claim.supersedes == cid or old.issue_id != claim.issue_id or claim.revision <= old.revision:
                self.diagnostic("invalid_supersession", cid)
                self.claim_bases.pop(cid, None)
                continue
            cursor = old
            visited = {cid}
            while cursor.supersedes and cursor.supersedes in self.graph.claims:
                if cursor.id in visited:
                    break
                visited.add(cursor.id)
                cursor = self.graph.claims[cursor.supersedes]
            if cursor.id in visited:
                self.diagnostic("supersession_cycle", cid)
                self.claim_bases.pop(cid, None)
            else:
                self.superseded.add(old.id)

    def validate_arguments(self) -> None:
        for aid, argument in sorted(self.graph.arguments.items()):
            self.tick()
            if aid in self.invalid_ids or argument.withdrawn:
                continue
            claim = self.graph.claims.get(argument.claim_id)
            if claim is None or claim.id not in self.claim_bases or claim.id in self.superseded:
                self.diagnostic("argument_claim_not_admitted", aid)
                continue
            required = PATTERN_REQUIREMENTS.get(argument.pattern)
            if required is None or (self.profile.allowed_patterns and argument.pattern not in self.profile.allowed_patterns):
                self.diagnostic("unsupported_pattern", aid, argument.pattern)
                continue
            if _scope_key(argument.scope) != _scope_key(claim.scope):
                self.diagnostic("argument_scope_mismatch", aid)
                continue
            if argument.revision < 1 or argument.revision > self.graph.revision:
                self.diagnostic("invalid_argument_revision", aid)
                continue
            form = _form(claim)
            expected = PATTERN_FORMS[argument.pattern]
            if form not in expected:
                self.diagnostic("pattern_claim_form_mismatch", aid, f"{argument.pattern} cannot conclude {form}")
                continue
            if not argument.premise_ids or len(set(argument.premise_ids)) != len(argument.premise_ids):
                self.diagnostic("premises_missing_or_duplicated", aid)
                continue
            if argument.pattern == "attribution" and not any(pid in self.evidence_basis for pid in argument.premise_ids):
                self.diagnostic("attribution_requires_located_record", aid)
                continue
            if argument.pattern in {"conjunction", "composition"}:
                if (len(argument.premise_ids) < 2 or any(pid not in self.graph.claims for pid in argument.premise_ids)
                        or len(set(claim.components)) != len(claim.components)
                        or set(claim.components) != set(argument.premise_ids)):
                    self.diagnostic("conjunction_members_mismatch", aid)
                    continue
            if argument.pattern == "process_trace" and len(argument.premise_ids) < 2:
                self.diagnostic("process_trace_requires_linked_premises", aid)
                continue
            missing = set(required) - argument.conditions.keys()
            if missing:
                self.diagnostic("required_conditions_missing", aid, ",".join(sorted(missing)))
                continue
            if len({argument.conditions[key] for key in required}) != len(required):
                self.diagnostic("required_conditions_not_distinct", aid)
                continue
            basis = self.claim_bases[claim.id].clone()
            basis.dependencies.add(aid)
            basis.arguments.add(aid)
            good = True
            for key, cid in argument.conditions.items():
                data = self.condition(cid, may_assume=key in PATTERN_ASSUMABLE[argument.pattern])
                if data is None:
                    good = False
                else:
                    basis.merge(data)
            for pid in argument.premise_ids:
                if pid in self.graph.claims:
                    premise = self.graph.claims[pid]
                    if pid not in self.claim_bases or pid in self.superseded:
                        self.diagnostic("premise_claim_not_admitted", aid, pid)
                        good = False
                    elif _scope_key(premise.scope) != _scope_key(argument.scope):
                        self.diagnostic("premise_scope_transfer_unsupported", aid, pid)
                        good = False
                elif pid not in self.evidence_basis:
                    self.diagnostic("premise_not_admitted", aid, pid)
                    good = False
            if good:
                self.valid_arguments[aid] = basis
                self.arguments_for_claim.setdefault(claim.id, []).append(argument)

    def intern(self, kind: str, record_id: str, conclusion: str | None,
               basis: _Basis, children: tuple[str, ...] = ()) -> str | None:
        if len(basis.contexts) > 1:
            self.diagnostic("assumption_contexts_not_aligned", record_id, ",".join(sorted(basis.contexts)))
            return None
        key = (kind, record_id, children, tuple(sorted(basis.dependencies)), tuple(sorted(basis.assumptions)))
        if key in self.node_keys:
            return self.node_keys[key]
        if len(self.nodes) >= self.profile.max_derivations:
            raise _LimitReached("derivation_limit")
        nid = f"node_{len(self.nodes) + 1:06d}"
        self.node_keys[key] = nid
        self.nodes[nid] = _Node(nid, kind, record_id, conclusion, basis)
        if kind == "argument":
            self.argument_nodes[record_id].append(nid)
            self.by_claim[conclusion].append(nid)
        elif kind == "attack":
            self.attack_nodes[record_id].append(nid)
        return nid

    def expand(self, claim_id: str, stack: tuple[str, ...] = ()) -> list[str]:
        self.tick()
        if claim_id in stack:
            self.diagnostic("unsupported_support_cycle", claim_id, " -> ".join(stack + (claim_id,)))
            return []
        if len(stack) >= self.profile.max_depth:
            raise _LimitReached("support_depth_limit")
        nodes = []
        for argument in self.arguments_for_claim.get(claim_id, []):
            choices: list[list[str | None]] = []
            for pid in argument.premise_ids:
                if pid in self.graph.claims:
                    expanded = self.expand(pid, stack + (claim_id,))
                    threshold = (self.profile.min_origins if self.profile.premise_min_origins is None
                                 else self.profile.premise_min_origins)
                    eligible = [nid for nid in expanded if len(self.nodes[nid].basis.support_origins) >= threshold]
                    if expanded and not eligible:
                        self.diagnostic("premise_use_profile_not_met", argument.id, pid)
                    choices.append(eligible)
                else:
                    choices.append([None])
            if any(not options for options in choices):
                continue
            for selected in product(*choices):
                self.tick()
                basis = self.valid_arguments[argument.id].clone()
                children = []
                for pid, nid in zip(argument.premise_ids, selected):
                    if nid is None:
                        basis.merge(self.evidence_basis[pid])
                    else:
                        basis.merge(self.nodes[nid].basis)
                        children.append(nid)
                claim = self.graph.claims[claim_id]
                if claim.form == "conditional" and not basis.contexts:
                    self.diagnostic("conditional_claim_without_context", claim_id)
                    continue
                nid = self.intern("argument", argument.id, claim_id, basis, tuple(children))
                if nid is not None:
                    nodes.append(nid)
        return sorted(set(nodes))

    def attack_basis(self, attack: Attack) -> _Basis | None:
        if not attack.grounds.strip() or not (attack.evidence_ids or attack.support_argument_id):
            self.diagnostic("attack_without_grounds", attack.id)
            return None
        if attack.kind not in {"undercut", "undermine", "rebut", "answer_inadequate"}:
            self.diagnostic("unsupported_attack_kind", attack.id)
            return None
        if attack.target_id == attack.id or attack.raised_revision < 1 or attack.raised_revision > self.graph.revision:
            self.diagnostic("invalid_attack_target_or_revision", attack.id)
            return None
        equivalent_targets = self.aliases.get(attack.target_id, {attack.target_id})
        if equivalent_targets.intersection(attack.evidence_ids) or attack.support_argument_id in equivalent_targets:
            self.diagnostic("attack_grounded_in_own_target", attack.id)
            return None
        if attack.disposition == "withdrawn":
            if attack.withdrawal_reason.strip():
                self.result.attack_labels[attack.id] = "WITHDRAWN"
                return None
            self.diagnostic("unsupported_attack_withdrawal", attack.id)
        target = (self.graph.arguments.get(attack.target_id) or self.graph.claims.get(attack.target_id)
                  or self.graph.evidence.get(attack.target_id) or self.graph.conditions.get(attack.target_id)
                  or self.graph.attacks.get(attack.target_id))
        if target is None or attack.target_id in self.invalid_ids:
            self.diagnostic("attack_target_missing", attack.id)
            return None
        if attack.kind == "rebut" and not isinstance(target, Claim):
            self.diagnostic("rebut_requires_claim_target", attack.id)
            return None
        if isinstance(target, Claim):
            if attack.scope is None or _scope_key(attack.scope) != _scope_key(target.scope):
                self.diagnostic("attack_scope_mismatch", attack.id)
                return None
        elif isinstance(target, Argument) and attack.scope is not None and _scope_key(attack.scope) != _scope_key(target.scope):
            self.diagnostic("attack_scope_mismatch", attack.id)
            return None
        if attack.condition_id:
            if not isinstance(target, Argument) or attack.condition_id not in self.graph.conditions:
                self.diagnostic("attack_condition_not_on_target", attack.id)
                return None
            if attack.condition_id not in target.conditions.values():
                # The controller preserves prior condition records. Renaming
                # the condition in a revised argument is not a grounded reply
                # to an already-recorded challenge of that argument.
                self.diagnostic("challenged_condition_replaced_without_discharge", attack.id)
        if attack.kind == "answer_inadequate" or attack.basis == "answer_inadequate":
            condition = self.graph.conditions.get(attack.condition_id or "")
            if condition is None or attack.challenged_revision is None or not 1 <= attack.challenged_revision <= condition.revision:
                self.diagnostic("challenged_answer_revision_missing", attack.id)
                return None
        basis = _Basis(dependencies={attack.id})
        for eid in attack.evidence_ids:
            if eid not in self.evidence_basis:
                self.diagnostic("attack_evidence_not_admitted", attack.id, eid)
                return None
            basis.merge(self.evidence_basis[eid])
        if attack.basis == "absence":
            coverage = self.condition(attack.coverage_condition_id or "", may_assume=False)
            if coverage is None:
                self.diagnostic("absence_attack_without_coverage", attack.id)
                return None
            basis.merge(coverage)
        return basis

    def compile_attacks(self) -> None:
        self.compile_aliases()
        admitted: dict[str, Attack] = {}
        for aid, attack in sorted(self.graph.attacks.items()):
            self.tick()
            if aid in self.invalid_ids:
                continue
            basis = self.attack_basis(attack)
            if basis is None:
                self.result.attack_labels.setdefault(aid, "NOT_ADMITTED")
                continue
            choices = self.argument_nodes.get(attack.support_argument_id, []) if attack.support_argument_id else [None]
            if not choices:
                self.diagnostic("attack_support_not_founded", aid)
                continue
            for supporter in choices:
                data = basis.clone()
                if supporter:
                    data.merge(self.nodes[supporter].basis)
                self.intern("attack", aid, None, data, (supporter,) if supporter else ())
            admitted[aid] = attack

        # Supported replies are defeaters of attack nodes, not a flag that
        # silently removes the objection. They can themselves be challenged.
        for aid, attack in admitted.items():
            if attack.disposition != "answered" and not attack.reply_condition_id:
                continue
            condition = self.graph.conditions.get(attack.reply_condition_id or "")
            adequate = self.condition(attack.reply_condition_id or "", may_assume=False)
            later = (attack.reply_revision is not None
                     and attack.raised_revision < attack.reply_revision <= self.graph.revision)
            enough = bool(attack.reply_reason.strip() and attack.reply_evidence_ids
                          and all(eid in self.evidence_basis for eid in attack.reply_evidence_ids))
            if condition is not None:
                enough = enough and set(attack.reply_evidence_ids).issubset(condition.evidence_ids)
                if attack.challenged_revision is not None:
                    later = later and condition.revision > attack.challenged_revision
                original = self.graph.conditions.get(attack.condition_id or "")
                if self.profile.require_independent_reply and original and condition.performer == original.performer:
                    enough = False
            if adequate is None or condition is None or condition.status != "met" or not later or not enough:
                self.diagnostic("reply_does_not_discharge", aid)
                continue
            reply = self.intern("reply", aid, None, adequate)
            if reply:
                self.edges.update((reply, attacker) for attacker in self.attack_nodes[aid])

        # Frozen attack targets are expanded to every use of an attacked
        # subargument/premise. This also reaches attacks supported by it.
        for aid, attack in admitted.items():
            target_aliases = self.aliases.get(attack.target_id, {attack.target_id})
            for nid, node in self.nodes.items():
                if target_aliases.intersection(node.basis.dependencies):
                    for attacker in self.attack_nodes[aid]:
                        self.edges.add((attacker, nid))

    def compile_aliases(self) -> None:
        """ID-only cloning cannot evade an objection.

        Compare contract content, including located premise identities and
        assessments, rather than IDs/performer timestamps. This catches exact
        structural aliases, not semantic paraphrases. A changed substantive
        premise or assessment is a different derivation, whose adequacy still
        needs the ordinary checks and any applicable review.
        """
        def evidence_key(eid: str) -> tuple[Any, ...]:
            record = self.graph.evidence.get(eid)
            if record is None:
                return ("missing_evidence", eid)
            return ("evidence", record.source_id, record.source_version, record.locator,
                    record.quote, tuple(sorted(record.qualifications)))

        def condition_key(cid: str) -> tuple[Any, ...]:
            record = self.graph.conditions.get(cid)
            if record is None:
                return ("missing_condition", cid)
            return ("condition", record.text, record.status, record.assumption_kind,
                    record.context_id, tuple(sorted(evidence_key(eid) for eid in record.evidence_ids)))

        def claim_key(cid: str) -> tuple[Any, ...]:
            record = self.graph.claims.get(cid)
            if record is None:
                return ("missing_claim", cid)
            return ("claim", record.text, record.kind, _form(record), _scope_key(record.scope),
                    record.issue_id, tuple(sorted((condition_key(c) for c in record.conditions), key=repr)),
                    tuple(sorted(record.components)))

        groups: dict[str, set[str]] = {}

        def add(rid: str, signature: Any) -> None:
            self.tick()
            key = repr(signature)
            groups.setdefault(key, set()).add(rid)

        for eid in self.graph.evidence:
            add(eid, evidence_key(eid))
        for cid in self.graph.conditions:
            add(cid, condition_key(cid))
        for cid in self.graph.claims:
            add(cid, claim_key(cid))
        for aid, argument in self.graph.arguments.items():
            premises = [(claim_key(pid) if pid in self.graph.claims else evidence_key(pid))
                        for pid in argument.premise_ids]
            add(aid, ("argument", argument.pattern, claim_key(argument.claim_id),
                      _scope_key(argument.scope), tuple(sorted(premises, key=repr)),
                      tuple((key, condition_key(cid)) for key, cid in sorted(argument.conditions.items()))))
        for ids in groups.values():
            for rid in ids:
                self.aliases[rid] = ids

    def grounded(self) -> dict[str, str]:
        labels = {nid: "UNDECIDED" for nid in self.nodes}
        attackers = {nid: set() for nid in self.nodes}
        targets = {nid: set() for nid in self.nodes}
        for src, dst in self.edges:
            attackers[dst].add(src)
            targets[src].add(dst)
        while True:
            self.tick()
            ready = [nid for nid, label in labels.items() if label == "UNDECIDED"
                     and all(labels[a] == "OUT" for a in attackers[nid])]
            if not ready:
                return labels
            for nid in ready:
                labels[nid] = "IN"
            for nid in ready:
                for target in targets[nid]:
                    if labels[target] == "UNDECIDED":
                        labels[target] = "OUT"
                    elif labels[target] == "IN":
                        # Should be unreachable for a fixed graph and this
                        # monotone algorithm. Never publish on an invariant fault.
                        raise RuntimeError("grounded labelling consistency fault")

    @staticmethod
    def aggregate(ids: list[str], labels: dict[str, str]) -> str:
        values = {labels[nid] for nid in ids}
        if "IN" in values:
            return "IN"
        if "UNDECIDED" in values:
            return "UNDECIDED"
        return "OUT" if values else "INAPPLICABLE"

    def render_findings(self, labels: dict[str, str]) -> None:
        self.result.derivation_labels = labels
        self.result.argument_labels = {aid: self.aggregate(ids, labels) for aid, ids in self.argument_nodes.items()}
        for aid, ids in self.attack_nodes.items():
            if ids:
                self.result.attack_labels[aid] = self.aggregate(ids, labels)
            else:
                self.result.attack_labels.setdefault(aid, "NOT_ADMITTED")
        for cid, claim in sorted(self.graph.claims.items()):
            finding = ClaimFinding(claim_id=cid, scope=claim.scope, form=_form(claim), components=claim.components)
            candidates = [self.nodes[nid] for nid in self.by_claim[cid]]
            standing = [node for node in candidates if labels[node.id] == "IN"]
            qualified = [node for node in standing if len(node.basis.support_origins) >= self.profile.min_origins]
            selected: list[_Node] = []
            if cid in self.superseded:
                finding.reasons.append("superseded_claim")
            elif qualified:
                # Prefer an unconditional realization if there is one. Never
                # merge incompatible scenario supports into a new conclusion.
                unconditional = [node for node in qualified if not node.basis.contexts]
                pool = unconditional or qualified
                chosen = min(pool, key=lambda n: (len(n.basis.assumptions), len(n.basis.dependencies), n.id))
                selected = [chosen]
                finding.status = "conditional" if chosen.basis.contexts else ("reported" if _form(claim) == "source_reports" else "established")
                finding.reasons.append("qualifying_founded_derivation")
            elif any(labels[node.id] == "UNDECIDED" for node in candidates):
                finding.status = "contested"
                finding.reasons.append("unresolved_grounded_conflict")
                selected = [node for node in candidates if labels[node.id] == "UNDECIDED"]
            elif standing:
                finding.reasons.append("minimum_support_origins_not_met")
                selected = standing
            elif candidates:
                finding.reasons.append("support_defeated")
                selected = candidates
            else:
                finding.reasons.append("no_admitted_founded_support")
            combined = _Basis()
            for node in selected:
                combined.merge(node.basis)
            related = {cid} | {a.id for a in self.graph.arguments.values() if a.claim_id == cid}
            if qualified and cid not in self.superseded:
                condition_ids = combined.dependencies.intersection(self.graph.conditions)
            else:
                condition_ids = self.reachable_conditions(cid)
            related.update(condition_ids)
            for item in self.result.diagnostics:
                if item["record_id"] in related and item["code"] not in finding.reasons:
                    finding.reasons.append(item["code"])
            unresolved = {key for key in condition_ids if key not in self.graph.conditions
                          or self.graph.conditions[key].status in {"open", "reopened", "assumed"}
                          or self.graph.conditions[key].context_id}
            unresolved.update(combined.assumptions)
            finding.open_conditions = sorted(unresolved)
            finding.condition_texts = [self.graph.conditions[key].text for key in sorted(unresolved) if key in self.graph.conditions]
            finding.assumption_contexts = sorted(combined.contexts)
            finding.origins = sorted(combined.origins)
            finding.support_origins = sorted(combined.support_origins)
            finding.argument_ids = sorted(combined.arguments)
            finding.evidence_ids = sorted(combined.evidence)
            finding.qualifications = sorted(combined.qualifications)
            self.result.findings[cid] = finding
        for issue_id, cid in self.graph.issue_presupposition_failures.items():
            claim = self.graph.claims.get(cid)
            finding = self.result.findings.get(cid)
            if (claim and claim.issue_id == issue_id and _form(claim) == "presupposition_failure"
                    and finding and finding.status == "established" and finding.evidence_ids):
                self.result.issue_statuses[issue_id] = "ill_posed"
            else:
                self.result.issue_statuses[issue_id] = "unresolved"
                self.diagnostic("presupposition_failure_not_established", issue_id, cid)

    def reachable_conditions(self, cid: str) -> set[str]:
        visited: set[str] = set()
        pending = [cid]
        found: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visited or current not in self.graph.claims:
                continue
            visited.add(current)
            found.update(self.graph.claims[current].conditions)
            for argument in self.graph.arguments.values():
                if argument.claim_id == current and not argument.withdrawn:
                    found.update(argument.conditions.values())
                    pending.extend(pid for pid in argument.premise_ids if pid in self.graph.claims)
        return found

    def run(self) -> Evaluation:
        if (not self.profile.authority.strip() or self.profile.min_origins < 0
                or (self.profile.premise_min_origins is not None and self.profile.premise_min_origins < 0)
                or min(self.profile.max_depth, self.profile.max_derivations, self.profile.max_evaluation_steps) < 1
                or self.graph.revision < 1):
            self.result.evaluation_status = "failed"
            self.diagnostic("invalid_profile_or_graph_context", self.graph.id)
            self.unresolved_findings("evaluation_context_invalid")
            return self.result
        try:
            self.check_ids()
            self.validate_evidence()
            self.validate_claims()
            self.validate_arguments()
            for cid in sorted(self.graph.claims):
                if cid in self.claim_bases and cid not in self.superseded:
                    self.expand(cid)
            self.compile_attacks()
            self.render_findings(self.grounded())
        except _LimitReached as exc:
            self.result.evaluation_status = "incomplete"
            self.diagnostic(str(exc), self.graph.id)
            self.unresolved_findings("evaluation_incomplete")
        return self.result

    def unresolved_findings(self, reason: str) -> None:
        self.result.findings = {
            cid: ClaimFinding(claim_id=cid, scope=claim.scope, form=_form(claim),
                              components=claim.components, reasons=[reason])
            for cid, claim in self.graph.claims.items()
        }
        self.result.argument_labels = {}
        self.result.derivation_labels = {}
        self.result.attack_labels = {}
        self.result.issue_statuses = {key: "unresolved" for key in self.graph.issue_presupposition_failures}


def evaluate(
    graph: InquiryGraph,
    profile: Profile,
    *,
    evidence_context: Any,
    previous_evaluation: Evaluation | None = None,
) -> Evaluation:
    """Evaluate one frozen snapshot against the exposure-aware evidence context.

    ``evidence_context`` supplies ``current_versions``, a version-keyed
    ``source_lookup``, and ``verify_quote(worker_id, source_id, version, quote,
    locator=...)`` returning ``valid``, ``reason``, and ``is_current``. Supplied
    source membership is never substituted for the quote verifier's exposure
    check. A complete prior result may be returned as explicitly historical
    context after resource exhaustion, never as findings for the new revision.
    """
    result = _Evaluator(graph, profile, evidence_context).run()
    if (result.evaluation_status != "complete" and previous_evaluation is not None
            and previous_evaluation.evaluation_status == "complete"
            and previous_evaluation.graph_id == graph.id):
        previous = previous_evaluation.model_dump()
        previous["last_complete_evaluation"] = None
        result.last_complete_evaluation = previous
    return result
