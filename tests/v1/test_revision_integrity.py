"""Controller regressions for preserving a live challenge across record edits."""

import pytest

from inquiry.v1.models import Argument, InquiryGraph
from inquiry.v1.runtime import _snapshot_revision


def challenged_record():
    return InquiryGraph.model_validate({
        "id": "revision_fixture", "revision": 4,
        "claims": {"c1": {"id": "c1", "text": "A scoped event occurred.",
                          "scope": {"location": "district", "period": "day_1"}}},
        "evidence": {
            "e1": {"id": "e1", "source_id": "source_1", "source_version": "1",
                   "locator": "p1", "quote": "First account."},
            "e2": {"id": "e2", "source_id": "source_2", "source_version": "1",
                   "locator": "p2", "quote": "Second account."},
        },
        "conditions": {
            "k1": {"id": "k1", "text": "The records support the event claim.", "status": "met",
                   "evidence_ids": ["e1", "e2"], "revision": 1},
            "k2": {"id": "k2", "text": "The records apply at this scope.", "status": "met",
                   "evidence_ids": ["e1", "e2"], "revision": 1},
        },
        "arguments": {"a1": {"id": "a1", "claim_id": "c1", "pattern": "document_record",
                             "premise_ids": ["e1", "e2"],
                             "conditions": {"record_warrant": "k1", "applicability": "k2"},
                             "scope": {"location": "district", "period": "day_1"}, "revision": 1}},
        "attacks": {"x1": {"id": "x1", "target_id": "a1", "kind": "undercut",
                           "grounds": "The second record challenges the claimed applicability.",
                           "evidence_ids": ["e2"], "condition_id": "k2", "basis": "answer_inadequate",
                           "performer": "critic:fixture", "challenged_revision": 1, "raised_revision": 4}},
    })


@pytest.mark.parametrize("retain_original", [False, True])
def test_renamed_duplicate_cannot_evade_a_live_challenge(retain_original):
    previous = challenged_record()
    proposed = previous.model_copy(deep=True)
    renamed = proposed.arguments["a1"].model_dump()
    renamed.update(id="a_new", revision=99, withdrawn=False,
                   premise_ids=["e2", "e1"],
                   conditions={"applicability": "k2", "record_warrant": "k1"})
    if not retain_original:
        proposed.arguments.clear()
    proposed.arguments["a_new"] = Argument.model_validate(renamed)
    with pytest.raises(ValueError, match=r"duplicates.*retain its ID"):
        _snapshot_revision(previous, proposed, "proposer:fixture")


def test_reply_uses_original_argument_identity_and_retains_challenge():
    previous = challenged_record()
    proposed = previous.model_copy(deep=True)
    proposed.arguments["a1"].revision = 99
    proposed.attacks["x1"].reply_reason = "The proponent offers a reply for examination."
    proposed.attacks["x1"].reply_evidence_ids = ["e1"]
    changed = _snapshot_revision(previous, proposed, "proposer:fixture")
    assert changed.attacks["x1"].grounds == previous.attacks["x1"].grounds
    assert changed.attacks["x1"].target_id == "a1"
    assert changed.attacks["x1"].reply_revision == changed.revision == 5
    assert changed.attacks["x1"].disposition == "open"
