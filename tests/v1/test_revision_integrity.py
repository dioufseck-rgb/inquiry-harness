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


def test_omission_does_not_withdraw_a_previously_recorded_argument():
    previous = challenged_record()
    proposed = previous.model_copy(deep=True)
    proposed.arguments.clear()
    changed = _snapshot_revision(previous, proposed, "proposer:fixture")
    assert changed.arguments["a1"] == previous.arguments["a1"]
    assert not changed.arguments["a1"].withdrawn
    assert changed.attacks["x1"] == previous.attacks["x1"]
    assert previous.revision == 4 and changed.revision == 5


def test_explicit_argument_withdrawal_preserves_its_history_and_challenge():
    previous = challenged_record()
    proposed = previous.model_copy(deep=True)
    proposed.arguments["a1"].withdrawn = True
    changed = _snapshot_revision(previous, proposed, "proposer:fixture")
    assert changed.arguments["a1"].withdrawn
    assert changed.arguments["a1"].revision == 5
    assert changed.attacks["x1"] == previous.attacks["x1"]
    assert not previous.arguments["a1"].withdrawn


def test_initial_revision_and_actor_claims_are_controller_owned():
    proposed = challenged_record()
    proposed.revision = 999
    proposed.conditions["k1"].performer = "imaginary-independent-checker"
    proposed.conditions["k1"].performer_kind = "human"
    proposed.conditions["k1"].revision = 998
    proposed.arguments["a1"].revision = 998
    proposed.attacks["x1"].raised_revision = 997
    proposed.attacks["x1"].challenged_revision = 998
    proposed.attacks["x1"].reply_revision = 999
    changed = _snapshot_revision(None, proposed, "proposer:fixture")
    assert changed.revision == changed.conditions["k1"].revision == changed.arguments["a1"].revision == 1
    assert changed.conditions["k1"].performer == "proposer:fixture"
    assert changed.conditions["k1"].performer_kind == "model"
    assert changed.attacks["x1"].raised_revision == changed.attacks["x1"].challenged_revision == 1
    assert changed.attacks["x1"].reply_revision is None


def test_an_active_inquiry_cannot_be_renamed_to_reset_its_history():
    previous = challenged_record()
    proposed = previous.model_copy(deep=True)
    proposed.id = "unrelated-new-record"
    with pytest.raises(ValueError, match="inquiry ID is immutable"):
        _snapshot_revision(previous, proposed, "proposer:fixture")
