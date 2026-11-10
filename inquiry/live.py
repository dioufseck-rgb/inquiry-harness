"""
The cycle, and a CLI to run it.

    python -m inquiry.live "question" [--rounds N] [--max-sources 8] [--interactive]

Round 0: frame → hypothesize. Each round: plan → gather → argue → critique →
evaluate → reflect → stop? Then conclude. The macro-cycle is fixed; the
model chooses within each move. After every move the state is saved and a
hash-chained ledger event is appended.

The Harness takes its collaborators by injection (two LLMs, a search, a
fetcher) so the whole cycle runs under test with fakes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Callable, Optional

from . import moves
from .argument.evaluate import Evaluation, load_bearing
from .argument.render import summary, toulmin, wigmore
from .llm import LLM, llm_from_env
from .metrics import metrics, one_line
from .state import Inquiry
from .store import InquiryStore
from .tools.fetch import Fetcher
from .tools.search import Search


def title_key(title: str) -> str:
    """Normalised prefix of a title, for spotting one document hosted at two URLs."""
    t = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t[:40]


def slug_for(question: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:40].rstrip("-")
    digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:6]
    return f"{base or 'inquiry'}-{digest}"


class Harness:
    def __init__(
        self,
        inq: Inquiry,
        store: InquiryStore,
        proposer: LLM,
        critic: LLM,
        search: Search,
        fetcher: Fetcher,
        *,
        max_sources: int = 8,
        queries_per_round: int = 6,
        hits_per_query: int = 5,
        interactive: bool = False,
        min_chars: int = 300,
        read_parts: int = 36,
        log: Optional[Callable[[str], None]] = None,
        ask: Optional[Callable[[str], str]] = None,
    ):
        self.min_chars = min_chars
        self.read_parts = read_parts  # appraisal windows of ~12k chars per primary document (36 ≈ 400k chars)
        self.inq = inq
        self.store = store
        self.proposer = proposer
        self.critic = critic
        self.search = search
        self.fetcher = fetcher
        self.max_sources = max_sources
        self.queries_per_round = queries_per_round
        self.hits_per_query = hits_per_query
        self.interactive = interactive
        self.log = log or (lambda s: print(s, file=sys.stderr))
        self.ask = ask or input
        self.pending_queries: list[str] = []
        self._repairs_seen: dict[int, int] = {}

    # -- bookkeeping -------------------------------------------------------------

    def _record(self, move: str, summary_: dict) -> None:
        # contract repairs since the last move are part of the record: they explain thin or odd outputs
        for llm in (self.proposer, self.critic):
            seen = self._repairs_seen.setdefault(id(llm), 0)
            for r in getattr(llm, "repairs", [])[seen:]:
                self.inq.notes.append(f"contract repair in {move} ({r['skill']}): {r['error'][:160]}")
            self._repairs_seen[id(llm)] = len(getattr(llm, "repairs", []))
            summary_ = {**summary_, "contract_repairs": len(getattr(llm, "repairs", []))} if getattr(llm, "repairs", []) else summary_
        self.store.save(self.inq)
        self.store.append_event(move, self.inq, summary_)
        short = {k: (v if not isinstance(v, list) else len(v)) for k, v in summary_.items()}
        self.log(f"[round {self.inq.round}] {move}: {short}")

    # -- gather ------------------------------------------------------------------

    def gather(self) -> dict:
        inq, g = self.inq, self.inq.graph
        known_urls = {s.url for s in g.sources}
        known_titles = {title_key(s.title): s.id for s in g.sources if len(title_key(s.title)) >= 25}
        new_sources: list[str] = []
        new_evidence: list[str] = []
        skipped: list[str] = []
        located: list[str] = []
        queries_run = 0

        # targeted reads first: places in documents we already hold that the plan or the critic named
        for sid, loc in moves.locate_requests(inq):
            src = g.source(sid)
            text = self.store.read_source_text(sid)
            if src is None or not text:
                continue
            try:
                out = moves.appraise_full(inq, self.proposer, src, text, None, max_parts=self.read_parts,
                                          text_complete=src.read_fully, locate=loc)
            except Exception as e:  # noqa: BLE001
                skipped.append(f"{sid} {loc}: targeted read failed: {type(e).__name__}")
                continue
            inq.notes.append(f"located: {sid} {loc}")
            located.append(f"{sid} {loc}: {len(out['evidence'])} items from {out['parts']} window(s)")
            new_evidence.extend(out["evidence"])
        for t in [t for t in inq.tests if t.status == "planned"]:
            found = False
            for q in t.queries:
                if queries_run >= self.queries_per_round or len(new_sources) >= self.max_sources:
                    break
                queries_run += 1
                try:
                    hits = self.search.search(q, k=self.hits_per_query)
                except Exception as e:  # noqa: BLE001 — a failed query is not a failed round
                    skipped.append(f"search {q!r}: {type(e).__name__}: {e}")
                    continue
                for h in hits:
                    if len(new_sources) >= self.max_sources:
                        break
                    if not h.url or h.url in known_urls:
                        continue
                    known_urls.add(h.url)
                    f = self.fetcher.fetch(h.url)
                    if len(f.text.strip()) < self.min_chars:
                        skipped.append(f"{h.url}: {f.error or f'only {len(f.text.strip())} chars of text'}")
                        continue
                    title = h.title or f.title
                    key = title_key(title)
                    if len(key) >= 25 and key in known_titles:
                        # the same document at another host is the same origin, not a second source
                        skipped.append(f"{h.url}: same document as {known_titles[key]} by title")
                        continue
                    src = g.add_source(url=h.url, title=title, query=q, date=h.date)
                    if len(key) >= 25:
                        known_titles[key] = src.id
                    src.text_path = self.store.write_source_text(src.id, f.text)
                    try:
                        out = moves.appraise_full(inq, self.proposer, src, f.text, t, max_parts=self.read_parts,
                                                  text_complete=not f.truncated)
                    except Exception as e:  # noqa: BLE001 — a model or network failure on one source is not a failed round
                        partial = [x for x in g.evidence if x.source_id == src.id]
                        if partial:
                            out = {"evidence": [x.id for x in partial]}
                            src.read_fully = False
                            skipped.append(f"{h.url}: appraisal interrupted after {len(partial)} items: {type(e).__name__}")
                        else:
                            g.sources.remove(src)
                            (self.store.dir / src.text_path).unlink(missing_ok=True)
                            skipped.append(f"{h.url}: appraisal failed: {type(e).__name__}: {str(e)[:80]}")
                            self.store.save(inq)
                            continue
                    if not out["evidence"]:
                        # nothing to the point: do not keep a source that grounds nothing
                        g.sources.remove(src)
                        (self.store.dir / src.text_path).unlink(missing_ok=True)
                        skipped.append(f"{h.url}: appraised, no evidence bearing on the claims")
                        continue
                    new_sources.append(src.id)
                    new_evidence.extend(out["evidence"])
                    found = True
                    # one hop to a primary article's supplementary material: same origin, read in full
                    if src.kind == "primary" and f.links:
                        for link in f.links[:2]:
                            if link in known_urls:
                                continue
                            known_urls.add(link)
                            sf = self.fetcher.fetch(link)
                            if len(sf.text.strip()) < self.min_chars:
                                skipped.append(f"{link}: supplementary, {sf.error or 'too short'}")
                                continue
                            supp = g.add_source(url=link, title=f"{src.title} (supplementary)", kind="primary",
                                                derived_from=src.id, query=q)
                            supp.text_path = self.store.write_source_text(supp.id, sf.text)
                            try:
                                so = moves.appraise_full(inq, self.proposer, supp, sf.text, t, max_parts=self.read_parts,
                                                         text_complete=not sf.truncated)
                            except Exception as e:  # noqa: BLE001
                                g.sources.remove(supp)
                                skipped.append(f"{link}: supplementary appraisal failed: {type(e).__name__}")
                                continue
                            supp.kind, supp.derived_from = "primary", src.id  # the appraisal must not detach it
                            new_sources.append(supp.id)
                            new_evidence.extend(so["evidence"])
            if queries_run >= self.queries_per_round or len(new_sources) >= self.max_sources:
                if not found:
                    continue  # leave it planned for the next round
            t.status = "run" if found else "unobtainable"
        return {"queries": queries_run, "sources": new_sources, "evidence": new_evidence, "skipped": skipped,
                "located": located}

    # -- human review --------------------------------------------------------------

    def human_review(self) -> dict:
        """Prompt for objections as `target_id type text`; blank line ends."""
        g = self.inq.graph
        ev = self.inq.evaluation or moves.evaluate_move(self.inq)
        print(summary(g, ev))
        print("Objections as: <target_id> <undermine|undercut|rebut> <text>. Blank line to finish.")
        added: list[str] = []
        while True:
            try:
                line = self.ask("> ").strip()
            except EOFError:
                break
            if not line:
                break
            parts = line.split(maxsplit=2)
            if len(parts) < 2:
                print("need at least a target id and an attack type")
                continue
            target, type_ = parts[0], parts[1]
            text = parts[2] if len(parts) > 2 else ""
            if type_ not in ("undermine", "undercut", "rebut"):
                print("type must be undermine, undercut or rebut")
                continue
            try:
                a = g.add_attack(target, type_, origin="human", note=text, round=self.inq.round)  # type: ignore[arg-type]
            except (KeyError, ValueError) as e:
                print(f"rejected: {e}")
                continue
            added.append(a.id)
            print(f"recorded {a.id}")
        if added:
            moves.evaluate_move(self.inq)
        return {"attacks": added}

    # -- the cycle -------------------------------------------------------------------

    def run(self, rounds: int = 2) -> Inquiry:
        inq = self.inq
        if inq.phase == "new":
            self._record("frame", moves.frame(inq, self.proposer))
        if inq.phase == "framed":
            self._record("hypothesize", moves.hypothesize(inq, self.proposer))
            if not inq.main_claims():
                # nothing to inquire into; try once more, then stop rather than conclude on an empty graph
                inq.notes.append("hypothesize: no claims on the main issue; retrying once")
                inq.phase = "framed"
                self._record("hypothesize", moves.hypothesize(inq, self.proposer))
                if not inq.main_claims():
                    raise RuntimeError("hypothesize produced no claims on the main issue twice; "
                                       "see the hypothesize skill and the model's reply")
        if inq.phase == "hypothesized":
            inq.phase = "inquiring"

        ev: Evaluation = moves.evaluate_move(inq)
        while inq.phase == "inquiring":
            pending = [t for t in inq.tests if t.status == "planned" and t.round == inq.round]
            if pending and inq.round > 0:
                # resuming a round that was planned but not gathered: continue it rather than start a new one
                self.log(f"[round {inq.round}] resume: {len(pending)} planned tests pending; skipping plan")
            else:
                inq.round += 1
                self._record("plan", moves.plan(inq, self.proposer, self.pending_queries or None))
            rounds_left = rounds - inq.round
            self.pending_queries = []
            gathered = self.gather()
            self._record("gather", gathered)
            computed = moves.compute(inq, self.proposer)
            if computed is not None:
                self._record("compute", computed)
            self._record("argue", moves.argue(inq, self.proposer))
            ev = moves.evaluate_move(inq)  # the critic sees evaluated arguments
            crit = moves.critique(inq, self.critic)
            self._record("critique", crit)
            for q in crit["needed_evidence"]:
                inq.notes.append(f"critic needs: {q}")
            self.pending_queries = list(crit["needed_evidence"])
            ev = moves.evaluate_move(inq)  # the proposer sees which attacks stand
            self._record("respond", moves.respond(inq, self.proposer))
            ev = moves.evaluate_move(inq)
            self._record("evaluate", {
                "accepted": {k: v for k, v in ev.issues.items() if v},
                "flags": [f.code for f in ev.flags if f.code != "inapplicable_argument"],
            })
            r = moves.reflect(inq, ev)
            self._record("reflect", {"established": r.established, "assumed": r.assumed,
                                     "load_bearing": r.load_bearing_node_ids, "directive": r.directive})
            if self.interactive:
                self._record("human_review", self.human_review())
                ev = inq.evaluation or ev
            sa = moves.stop(inq, ev, rounds_left, len(gathered["evidence"]))
            self._record("stop", {"decision": sa.decision, "reason": sa.reason})
            if sa.decision == "stop":
                break

        self._record("conclude", moves.conclude(inq, self.proposer))
        self.write_report()
        m = metrics(inq, inq.evaluation or moves.evaluate_move(inq))
        (self.store.dir / "metrics.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
        self.log(one_line(m))
        return inq

    # -- report -----------------------------------------------------------------------

    def write_report(self) -> Path:
        inq, g = self.inq, self.inq.graph
        ev = inq.evaluation or moves.evaluate_move(inq)
        lines = [f"# {inq.question}", ""]
        if inq.conclusion:
            c = inq.conclusion
            lines += [c.answer, "", "## Key judgements", ""]
            for j in c.judgements:
                ids = f" ({', '.join(j.claim_ids)})" if j.claim_ids else ""
                lines.append(f"- **{j.confidence}** {j.text}{ids}  \n  rests on: {j.rests_on}")
            if c.what_would_change_this:
                lines += ["", "## What would change this", ""] + [f"- {x}" for x in c.what_would_change_this]
            if c.unresolved:
                lines += ["", "## Unresolved", ""] + [f"- {x}" for x in c.unresolved]
            lines.append("")
        lb, seen = [], set()
        for cl in inq.main_claims():
            for x in load_bearing(g, cl.id):
                if (x.node_id, x.effect) not in seen:
                    seen.add((x.node_id, x.effect))
                    lb.append(x)
        lines += ["## Argument graph", "", summary(g, ev, lb)]
        in_args = [a for a in g.arguments if ev.labels.get(a.id) == "in" and not a.is_attack]
        if in_args:
            lines += ["## Surviving arguments", ""]
            for a in in_args:
                lines += [toulmin(g, a.id, ev), ""]
        if g.sources:
            lines += ["## Sources", ""]
            for s in g.sources:
                lines.append(f"- {s.id} [{s.kind}] {s.title or s.url} <{s.url}>")
        path = self.store.dir / "report.md"
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        (self.store.dir / "chart.mmd").write_text(wigmore(g, ev), encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path.cwd() / ".env")  # explicit path: find_dotenv() needs a caller frame
    except ImportError:
        pass


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="inquiry", description="Run an inquiry on a question.")
    p.add_argument("question", nargs="?", help="The question. Omit with --id to resume a run.")
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--max-sources", type=int, default=8, help="New sources per round.")
    p.add_argument("--queries", type=int, default=6, help="Queries per round.")
    p.add_argument("--hits", type=int, default=5, help="Hits per query.")
    p.add_argument("--read-parts", type=int, default=36,
                   help="Appraisal windows (~12k chars each) to read per primary document; others are sampled.")
    p.add_argument("--interactive", action="store_true", help="Prompt for human objections after each critique.")
    p.add_argument("--id", help="Inquiry id under --root; resumes if it exists.")
    p.add_argument("--root", default="runs")
    args = p.parse_args(argv)

    _load_env()
    inquiry_id = args.id or (slug_for(args.question) if args.question else None)
    if inquiry_id is None:
        p.error("a question or --id is required")
    if InquiryStore.exists(args.root, inquiry_id):
        store = InquiryStore(args.root, inquiry_id)
        inq = store.load()
        print(f"resuming {inquiry_id} at phase {inq.phase}, round {inq.round}", file=sys.stderr)
    else:
        if not args.question:
            p.error(f"no run named {inquiry_id!r} under {args.root}; give a question")
        store = InquiryStore(args.root, inquiry_id)
        inq = Inquiry(id=inquiry_id, question=args.question)

    from .tools.fetch import HttpFetcher
    from .tools.search import SerperSearch

    harness = Harness(
        inq, store, llm_from_env("proposer"), llm_from_env("critic"), SerperSearch(), HttpFetcher(),
        max_sources=args.max_sources, queries_per_round=args.queries, hits_per_query=args.hits,
        interactive=args.interactive, read_parts=args.read_parts,
    )
    harness.run(rounds=args.rounds)
    print(f"\nwrote {store.dir / 'report.md'}; ledger ok = {store.verify_ledger()}", file=sys.stderr)
    if inq.conclusion:
        print(inq.conclusion.answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
