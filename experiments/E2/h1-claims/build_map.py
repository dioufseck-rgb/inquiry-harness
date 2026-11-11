"""Reproduce the explicitly reviewed E2(c) directions; no ordinal mapping.

All 160 saved evidence texts were read against the 17 selected claim texts.
The ID lists below are editorial annotations, not automatic text inference.
"""
import json
from pathlib import Path

root = Path(__file__).parent
template = json.loads((root / "input/mapping-template.json").read_text(encoding="utf-8"))
directions = {e["id"]: {} for e in template["evidence"]}
rationale = {e["id"]: [] for e in template["evidence"]}


def mark(numbers, claims, stance, why):
    for number in numbers:
        eid = f"E{number}"
        for cid in claims:
            old = directions[eid].get(cid)
            if old and old != "neutral" and stance != "neutral" and old != stance:
                raise ValueError(f"explicit review needed for conflicting {eid}/{cid}")
            if old is None or stance != "neutral":
                directions[eid][cid] = stance
        rationale[eid].append(why)


net = ["C1", "C2", "C3", "C4"]
clinical = [f"C{n}" for n in (1, 2, 3, 9, 10, 11, 12, 13, 14, 15, 16, 17)]
design = [1,2,5,6,7,8,12,14,15,23,24,25,38,39,40,43,44,45,46,47,48,54,59,60,61,62,63,64,66,68,69,72,74,75,76,77,78,79,80,81,82,83,84,85,86,87,96,100,109,110,111,115,119,120,123,125,127,136,141,142,145,146,147]
mark(design, net, "neutral", "Design, population, follow-up or endpoint context; no standalone net-effect direction.")
mark([1,14,15,38,63,68,74,75,76,78,79,84,85,86,87,96,100,109,110,111,115,119,120,123,125,136,141,145,146,147], clinical, "neutral", "Internal-validity/transport context. Scope and selection limitations remain for CQs.")
mark([2,5,13,21,22,26,40,43,44,48,64,66,69,72,80,81,108,127,142,158,160], ["C4"], "for", "Sources use different definitions/severity valuations or identify their importance; does not establish a sign reversal.")
mark([2,5,13,26,40,43,44,48,64,66,69,80,81,127,142,158], ["C8"], "for", "Distinct observed outcome constructions support definitional plurality, not a universal claim that no standard exists.")
mark([13,21,22,26,108,158,160], ["C6"], "for", "Severity weighting or severity differences can alter the numeric balance; no demonstrated reversal is assumed.")
mark([13,21,22,26,72,108,158,160], ["C7"], "neutral", "No comparative robustness result establishes invariance or a particular reversal under alternative values.")

# Cardiovascular components: significant reductions are partial support with
# population/endpoint transport still unresolved. Nonsignificance is neutral.
mark([9,18,28,34,93,153], ["C9"], "for", "MI reduction; pooled age/regimen differences and instrument uncertainty remain explicit.")
mark([9,18,130,138,153], ["C10"], "for", "Stroke reduction; mixed/all-stroke endpoints are only partial support for ischemic stroke.")
mark([9,18,28,34,93,130,138,153], ["C12"], "against", "Detected component reductions weigh against an unqualified no-effect conjunction; transport is not certified.")
mark([3,19,27,29,35,37,41,49,50,51,52,58,90,97,101,102,103,107,112,116,121,126,128,129,131,135,137,143,148,149,154,155], ["C9","C10","C11","C12"], "neutral", "Nonsignificant, composite, heterogeneous or indirect estimates do not establish a component effect or true zero.")
mark([65,70,88,124,128,130,135,138,153], net, "neutral", "A cardiovascular benefit alone does not determine the net balance with harms and valuation.")

intracranial = [30,33,55,94,98,105,106,113,117,118,122,156]
extracranial = [20,31,36,53,67,92,95,114,156]
bleeding = [4,10,20,30,31,33,36,42,53,55,56,67,71,89,94,95,98,105,106,113,114,117,118,122,124,132,139,156]
mark(intracranial, ["C13"], "for", "Intracranial/hemorrhagic-stroke excess; subtype, precision and transport limitations remain.")
mark(extracranial, ["C14"], "for", "Major extracranial/GI excess partially supports nonfatal extracranial harm; fatal composition and exact endpoint need checking.")
mark(bleeding, ["C17"], "against", "A bleeding excess weighs against the no-increase conjunction; no assumption of target-population equivalence.")
mark(extracranial, ["C5"], "for", "Including an additional excess harm makes the balance less favorable, conditional on the source's endpoint and population.")
mark(bleeding, ["C1","C2","C3"], "neutral", "Bleeding is one side of the net balance; it alone cannot establish total net harm, benefit or equivalence.")
mark([7,25,44,54,66,76,81,86,104,127,140,147,159], ["C13","C14","C15","C16","C17"], "neutral", "Bleeding definition, mechanism, selection or precision context.")
mark([57,104,105], ["C15"], "neutral", "Fatal-bleeding estimates are imprecise; neither an increase nor a true-zero effect is established.")
mark([91,99,133,140,144,150], ["C13","C14","C15","C17"], "neutral", "Imprecise subtype estimates or mostly mild/unclassified GI bleeding cannot establish the full claimed major/fatal effects.")
mark([152,157], ["C16"], "for", "Age-related absolute bleeding incidence and harm; baseline-risk treatment interaction is not established.")
mark([73,76,86,103,107,109,119,125,136,145,147,155], ["C16"], "neutral", "Subgroup or transport context does not quantify the complete age-and-baseline-risk absolute-excess claim.")
mark([11,17], ["C1"], "for", "Positive weighted net-benefit point estimate; CI spans harm and the target population is not directly isolated.")
mark([11,16,17,32,73,106,118,124,134,151,158], net, "neutral", "Mixed, near-null, partial or model-dependent balances do not establish exact zero or a uniform net direction at 60+.")
mark([151], ["C1"], "against", "The USPSTF no-net-benefit assessment weighs against unqualified net benefit, without asserting that it means net harm or equivalence.")
mark([151,158], ["C4"], "for", "The guideline/model distinguishes endpoint and age/risk balances, supporting qualification of the net answer.")
for eid in directions:
    if not rationale[eid]:
        rationale[eid] = ["Reviewed: no directional binding to these claims beyond the assigned items."]
data = {k: template[k] for k in ("claims_sha256", "claims")}
data.update(reviewed=True, reviewed_by="Codex manual review of all 160 evidence texts and the 17 H1 claims",
            policy="Partial directional relevance, not entailment. No ordinal reuse. Nonsignificance is not equivalence; component evidence alone does not determine a net endpoint.",
            directions=directions, rationale=rationale)
(root / "evidence-map.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Reviewed {len(directions)} items and {sum(map(len, directions.values()))} bindings")
