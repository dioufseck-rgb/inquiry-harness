from inquiry import moves
from inquiry.llm import FakeLLM
from inquiry.state import Inquiry


def test_quote_membership_allows_layout_whitespace_but_rejects_splicing():
    text = "First result.\n Second result."
    assert not moves.source_quote_errors("FIRST result. Second result.", text)
    assert moves.source_quote_errors("First ... Second result.", text)
    assert moves.source_quote_errors("", text)
    assert moves.source_quote_errors("x" * 301, "x" * 400)


def test_appraise_repairs_once_and_drops_remaining_unverified_quotes():
    inq = Inquiry(id="quote", question="What happened?")
    src = inq.graph.add_source(url="https://example.test")
    replies = iter([
        {"kind": "primary", "evidence": [{"text": "A", "quote": "Alpha."}, {"text": "B", "quote": "invented"}]},
        {"evidence": [{"text": "B", "quote": "Beta."}, {"text": "C", "quote": "still invented"}]},
    ])
    llm = FakeLLM({"appraise": lambda _: next(replies)})
    result = moves.appraise(inq, llm, src, "Alpha. Beta.")
    assert len(llm.calls) == 2 and "Rejected quotations" in llm.calls[1][1]
    assert [e.quote for e in inq.graph.evidence] == ["Alpha.", "Beta."]
    assert len(result["rejected_quotes"]) == 2 and src.kind == "primary"


def test_apply_appraise_checks_quotes_when_source_text_is_supplied():
    inq = Inquiry(id="apply", question="q")
    src = inq.graph.add_source(url="https://example.test")
    result = moves.apply_appraise(inq, src, moves.AppraiseOutput(evidence=[
        moves.EvidenceProposal(text="Invented", quote="not there")]), source_text="Actual source")
    assert not result["evidence"] and result["rejected_quotes"]
