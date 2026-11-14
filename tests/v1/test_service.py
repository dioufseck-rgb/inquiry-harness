"""Controlled integration checks of the service boundary, not model accuracy."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from inquiry.v1.contracts import InquiryRequest
from inquiry.v1.kernel import PATTERN_REQUIREMENTS
from inquiry.v1.runtime import Budget
from inquiry.v1.service import InquiryService
from inquiry.v1.workers import RecordedWorker


EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "v1"


def request(name="equipment_temperature"):
    return json.loads((EXAMPLES / (name + ".json")).read_text())


def supported_reply(public):
    """A prescribed trace supplies no evidence about a live model's ability."""
    q = public["question"]
    source = public["corpus"]["documents"][0]
    block = source["reading_blocks"][0]
    pattern = "attribution" if q["target"]["form"] == "source_reports" else "document_record"
    conditions = {"K_" + key: {"id": "K_" + key, "text": "Examine " + key,
                              "answer": "The supplied located record supports this explicitly scoped test claim.",
                              "status": "met", "evidence_ids": ["E"]}
                  for key in PATTERN_REQUIREMENTS[pattern]}
    return {"operation": "finish", "graph": {
        "id": "inquiry", "revision": 1,
        "claims": {"C": {"id": "C", "text": block["text"], **q["target"],
                         "scope": deepcopy(q["scope"]), "target_question_id": q["id"]}},
        "evidence": {"E": {"id": "E", "source_id": source["id"], "source_version": source["version"],
                           "locator": block["locator"], "quote": block["text"], "worker_id": "proposer"}},
        "conditions": conditions,
        "arguments": {"A": {"id": "A", "claim_id": "C", "pattern": pattern, "premise_ids": ["E"],
                            "conditions": {key: "K_" + key for key in PATTERN_REQUIREMENTS[pattern]},
                            "scope": deepcopy(q["scope"])}}, "attacks": {},
    }, "response": {"target_claim_id": "C", "inquiry_completed": True,
                     "assessment": "The located record supports the scoped finding.",
                     "information_needs": [], "caveats": ["Scripted service integration check."]}}


@pytest.mark.parametrize("name,status", [("equipment_temperature", "established"),
                                       ("research_attribution", "reported"),
                                       ("household_meter", "established")])
def test_same_service_handles_unrelated_domains_and_replays(name, status, tmp_path):
    public = request(name)
    original = deepcopy(public)
    service = InquiryService(lambda: RecordedWorker([supported_reply(public)]), record_root=tmp_path)
    out = service.inquire(public, mode="supplied", include_record=True)
    assert out["execution_status"] == "complete"
    assert out["response"]["inquiry_completed"] is True
    assert out["response"]["findings"][0]["status"] == status
    assert {"next_action", "deliverable", "task_completed", "decision"}.isdisjoint(out["response"])
    assert "task_completed" not in out["evaluation"]
    assert public == original
    assert out["record_ref"] == "inquiry://records/" + out["inquiry_id"]
    assert service.read_record(out["inquiry_id"]) == out["record"]
    assert service.replay(out["inquiry_id"])["evaluation_reproduced"] is True
    assert "Inquiry completed: True" in (tmp_path / out["inquiry_id"] / "report.md").read_text()


def test_host_budget_rejected_before_worker_construction():
    called = []
    service = InquiryService(lambda: called.append(True), max_budget=Budget(max_model_calls=3))
    with pytest.raises(ValueError, match="host ceiling"):
        service.inquire(request(), budget={"max_model_calls": 4})
    assert called == []


@pytest.mark.parametrize("field,value", [("max_depth", 100), ("max_derivations", 1000000),
                                       ("max_evaluation_steps", 1000000)])
def test_kernel_work_is_bounded_before_worker_construction(field, value):
    called = []
    public = request()
    public["question"]["profile"]["kernel"][field] = value
    service = InquiryService(lambda: called.append(True))
    with pytest.raises(ValueError, match="kernel work exceeds"):
        service.inquire(public)
    assert called == []


@pytest.mark.parametrize("change", ["oracle", "business_role", "oversize", "unknown_budget", "bad_mode"])
def test_bad_request_does_not_construct_worker(change):
    called = []
    public = request()
    service = InquiryService(lambda: called.append(True), max_request_bytes=10000)
    kwargs = {}
    if change == "oracle": public["shared_context"]["hidden_world"] = {"answer": True}
    if change == "business_role": public["corpus"]["current_policy"] = {"document_id": "s", "version": "1"}
    if change == "oversize": public["shared_context"]["padding"] = "a" * 10001
    if change == "unknown_budget": kwargs["budget"] = {"unbounded": True}
    if change == "bad_mode": kwargs["mode"] = "act"
    with pytest.raises((TypeError, ValueError)):
        service.inquire(public, **kwargs)
    assert called == []


def test_focused_check_keeps_profile_and_reduces_budget():
    public = request()
    public["question"]["profile"]["kernel"] = {"min_origins": 2}
    service = InquiryService(lambda: RecordedWorker([supported_reply(public)]))
    out = service.check(public, include_record=True)
    assert out["profile"]["min_origins"] == 2
    assert out["response"]["findings"][0]["status"] == "not_established"
    limits = out["record"]["manifest"]["budget"]
    assert limits["max_model_calls"] == 4
    assert limits["max_total_tokens"] == 32000
    assert out["operation"] == "check"


def test_same_claim_different_profiles_is_not_a_domain_branch():
    public = request()
    strong = deepcopy(public)
    strong["question"]["profile"]["id"] = "two-origins"
    strong["question"]["profile"]["kernel"] = {"min_origins": 2}
    service = InquiryService(lambda: RecordedWorker([supported_reply(public)]))
    one = service.check(public)
    two = service.check(strong)
    assert one["response"]["findings"][0]["status"] == "established"
    assert two["response"]["findings"][0]["status"] == "not_established"


def test_each_call_gets_fresh_workers_and_evidence(tmp_path):
    public = request()
    workers = []
    def factory():
        worker = RecordedWorker([supported_reply(public)])
        workers.append(worker)
        return worker
    service = InquiryService(factory, record_root=tmp_path)
    a = service.check(public, include_record=True)
    b = service.check(InquiryRequest.model_validate(public), include_record=True)
    assert len(workers) == 2 and workers[0] is not workers[1]
    assert a["inquiry_id"] != b["inquiry_id"]
    assert a["usage"]["model_calls"] == b["usage"]["model_calls"] == 1
    a["response"]["findings"][0]["scope"]["changed"] = True
    assert "changed" not in b["response"]["findings"][0]["scope"]
    assert service.read_record(b["inquiry_id"])["graph"] == b["graph"]


def test_one_service_does_not_mix_different_callers_evidence(tmp_path):
    requests = [request("equipment_temperature"), request("household_meter")]
    queue = iter(requests)
    workers = []
    def factory():
        worker = RecordedWorker([supported_reply(next(queue))])
        workers.append(worker)
        return worker
    service = InquiryService(factory, record_root=tmp_path)
    first = service.check(requests[0], include_record=True)
    second = service.check(requests[1], include_record=True)
    first_source = requests[0]["corpus"]["documents"][0]["id"]
    second_source = requests[1]["corpus"]["documents"][0]["id"]
    assert first_source in json.dumps(workers[0].calls)
    assert first_source not in json.dumps(workers[1].calls)
    assert first_source not in json.dumps(second["record"])
    assert second_source not in json.dumps(first["record"])
    assert service.read_record(second["inquiry_id"])["response"] == second["response"]


def test_review_is_separate_and_cannot_execute_business_action():
    public = request()
    review = {"observations": ["The source matches this controlled claim."], "attacks": {},
              "evidence": {}, "evidence_requests": []}
    service = InquiryService(lambda: RecordedWorker([supported_reply(public)]),
                             critic_factory=lambda: RecordedWorker([review]))
    out = service.check(public)
    assert out["response"]["review_completed"] is True
    assert out["usage"]["model_calls"] == 2
    assert out["execution_status"] == "complete"


@pytest.mark.parametrize("inquiry_id", ["../outside", "/tmp/a", "A" * 32, "f" * 31])
def test_record_access_is_host_bound(inquiry_id, tmp_path):
    service = InquiryService(lambda: None, record_root=tmp_path)
    with pytest.raises(ValueError, match="Invalid inquiry ID"):
        service.read_record(inquiry_id)


def test_symlink_cannot_select_another_store(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    (root / ("a" * 32)).symlink_to(outside, target_is_directory=True)
    service = InquiryService(lambda: None, record_root=root)
    with pytest.raises(ValueError, match="outside"):
        service.read_record("a" * 32)


def test_capabilities_are_epistemic_and_explicit_about_current_limits():
    service = InquiryService(lambda: None)
    caps = service.capabilities()
    assert caps["epistemic_only"] is True
    assert caps["operations"] == ["inquire", "check", "replay"]
    assert caps["request_schema"]["properties"]["corpus"]["required"] == ["documents", "current_versions"]
    assert "process_trace" in caps["patterns"]
    assert "universal" in caps["representable_target_forms"]
    assert "universal" in caps["forms_without_proof_pattern"]
    assert caps["persistent_records"] is False


def test_mcp_surface_contains_only_inquiry_tools():
    pytest.importorskip("mcp")
    import asyncio
    from inquiry.v1.mcp_server import create_server
    service = InquiryService(lambda: RecordedWorker([supported_reply(request())]))
    server = create_server(service)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {"capabilities", "inquire", "check", "replay"}
    result = asyncio.run(server.call_tool("capabilities", {}))
    assert result
    checked = asyncio.run(server.call_tool("check", {"request": request()}))
    assert checked[1]["response"]["inquiry_completed"] is True
    assert checked[1]["response"]["findings"][0]["status"] == "established"


def test_mcp_stdio_client_can_discover_and_call_service():
    pytest.importorskip("mcp")
    import asyncio
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    public = request()
    reply = supported_reply(public)
    script = ("from inquiry.v1.mcp_server import create_server\n"
              "from inquiry.v1.service import InquiryService\n"
              "from inquiry.v1.workers import RecordedWorker\n"
              f"reply = {reply!r}\n"
              "create_server(InquiryService(lambda: RecordedWorker([reply]))).run(transport='stdio')\n")
    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-c", script])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {"capabilities", "inquire", "check", "replay"}
                result = await session.call_tool("check", {"request": public})
                assert not result.isError
                assert result.structuredContent["response"]["inquiry_completed"] is True
                assert result.structuredContent["response"]["findings"][0]["status"] == "established"
    asyncio.run(asyncio.wait_for(exercise(), timeout=20))
