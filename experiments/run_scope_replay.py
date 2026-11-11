"""C3: one Hypothesize replay per provider on the same saved aspirin frame."""
import json
from pathlib import Path

from inquiry import moves
from inquiry.replay_move import reconstruct_pre_move
from inquiry.state import Inquiry
from experiments.tonight3 import make_llm


def main():
    root = Path("experiments/C3")
    root.mkdir(exist_ok=True)
    paths = ["E6/sonnet", "E6/sol", "E6-generalisation/energy", "E6-generalisation/genai"]
    audit = {}
    for folder in paths:
        raw = json.loads((Path("experiments") / folder / "inquiry.json").read_text(encoding="utf-8"))
        migrated = Inquiry.model_validate(raw)
        audit[folder] = [{"claim_id": c["id"], "stored": c.get("answers_issue", True),
                          "derived": migrated.graph.claim(c["id"]).answers_issue,
                          "scope": migrated.graph.claim(c["id"]).scope.model_dump()}
                         for c in raw["graph"]["claims"]
                         if c.get("answers_issue", True) != migrated.graph.claim(c["id"]).answers_issue]
    (root / "legacy-answerhood-audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    saved = Inquiry.model_validate_json(Path("experiments/E6/sonnet/inquiry.json").read_text(encoding="utf-8"))
    for name, spec in (("sonnet", "anthropic:claude-sonnet-5-5"), ("sol", "openai:gpt-6.1-sol")):
        destination = root / f"{name}.json"
        if destination.exists():
            raise FileExistsError(destination)
        inq, _ = reconstruct_pre_move(saved, "hypothesize")
        llm = make_llm(spec)
        out = llm.complete_json(moves.skill_text("hypothesize"), moves.hypothesize_view(inq), moves.HypothesizeOutput)
        result = moves.apply_hypothesize(inq, out)
        fields_filled = all(c.scope and all(getattr(c.scope, f) for f in ("population", "outcome", "period")) for c in out.claims)
        data = {"provider": spec, "fields_filled": fields_filled, "output": out.model_dump(), "apply": result,
                "claims": [c.model_dump() for c in inq.graph.claims],
                "cost_usd": sum(c["cost_usd"] or 0 for c in llm.calls)}
        destination.write_text(json.dumps(data, indent=2), encoding="utf-8")
        (root / f"{name}-responses.json").write_text(json.dumps(llm.calls, indent=2), encoding="utf-8")
        print(json.dumps({"provider": spec, "fields_filled": fields_filled, "cost_usd": data["cost_usd"]}), flush=True)


if __name__ == "__main__":
    main()
