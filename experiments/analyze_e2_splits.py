"""N3: backfill original/scoped counts from saved Argue summaries, with no calls."""
import json
from pathlib import Path

from inquiry.argument.evaluate import evaluate
from inquiry.metrics import argument_split_metrics
from inquiry.replay_move import aggregate, fingerprint, load_run


def analyze():
    root = Path("experiments/E2")
    cells = []
    for path in sorted(root.glob("*/*/*/moves.json")):
        native = json.loads(path.read_text(encoding="utf-8"))
        if native.get("move") != "argue":
            continue
        for sample in native["samples"]:
            graph = path.parent / sample["graph"]
            assert fingerprint(json.loads(graph.read_text(encoding="utf-8"))) == sample["graph_sha256"]
            inq, _ = load_run(graph)
            scoped = set(sample["move_summary"].get("scoped_claims", []))
            split = argument_split_metrics(inq, evaluate(inq.graph), scoped)
            assert split["supporting_original"] + split["supporting_scoped"] == sample["metrics"]["supporting_args"]
            assert split["applicable_original"] + split["applicable_scoped"] == sample["metrics"]["applicable_args"]
            sample["metrics"].update(split)
        native["aggregate"] = aggregate(native["samples"])
        native.setdefault("metrics_extensions", {})["N3"] = {
            "provenance": "Saved move_summary.scoped_claims, not revision_of alone; raw graphs unchanged",
            "model_calls": 0}
        path.write_text(json.dumps(native, indent=2) + "\n", encoding="utf-8")
        cells.append({"version": path.parent.parent.parent.name, "claims": path.parent.parent.name,
                      "provider": native["provider"], "model": native["model"], "effort": native["effort"],
                      "aggregate": native["aggregate"], "samples": native["samples"]})
    analysis_path = root / "analysis.json"
    old = json.loads(analysis_path.read_text(encoding="utf-8"))
    for c in old["cells"]:
        match = next(x for x in cells if (x["version"], x["claims"], x["provider"]) == (c["version"], c["claims"], c["provider"]))
        c.update(aggregate=match["aggregate"], samples=match["samples"])
    old.setdefault("metrics_extensions", []).append("N3: original/scoped counts recovered from saved Argue summaries")
    old["metrics_extensions"] = list(dict.fromkeys(old["metrics_extensions"]))
    analysis_path.write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")
    lines = ["## N3: original claims versus Argue-created scoped claims", "",
        "Zero model calls. Counts retain the existing active-support totals and split them using the recorded Argue scoped-claim IDs. A revision made by another move is not automatically labelled Argue-scoped. New graphs persist created_by_move=argue across rounds, so a scoped claim does not become original in round two.", "",
        "| Version | Claims | Provider:model (medium) | Support total | Original | Scoped | Applicable total | Original applicable | Scoped applicable | Main original IN |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for c in cells:
        a = c["aggregate"]
        keys = ("supporting_args", "supporting_original", "supporting_scoped", "applicable_args", "applicable_original", "applicable_scoped", "main_supporting_in_original")
        lines.append(f"| {c['version']} | {c['claims']} | {c['provider']}:{c['model']} | " + " | ".join(f"{a[k]['mean']:.2f}" for k in keys) + " |")
    lines += ["", "Sol's H1 after-H2 gain is predominantly support for claims it narrowed itself; those are often honest component/source findings, as N1's provisional review shows, but are not coverage of the original main question. Sonnet mostly builds arguments for the original claims and leaves population/outcome mismatches explicit. The counts must remain separate: high applicable_scoped cannot establish that a composed main answer exists.", ""]
    report = root / "report.md"
    prior = report.read_text(encoding="utf-8").split("\n## N3:", 1)[0].rstrip()
    report.write_text(prior + "\n\n" + "\n".join(lines), encoding="utf-8")
    print(json.dumps({"cells": len(cells), "model_calls": 0, "h1_after": [{k:v for k,v in c.items() if k != 'samples'} for c in cells if c['claims']=='h1-claims' and c['version']=='after']}))


if __name__ == "__main__":
    analyze()
