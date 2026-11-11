import pytest
from experiments.run_fixed_cycle import require_gate


def allowed():
    return {"full_run_allowed": True, "e1_pass": True, "e2_pass": True,
            "n1_review_recorded": True, "n2_committed": True, "n3_committed": True,
            "human_review_completed": False, "review_kind": "agent_provisional_user_authorized"}


def test_full_cycle_requires_recorded_preconditions_and_explicit_provisional_authority():
    require_gate(allowed(), {"split": "held_in"})
    gate = allowed()
    gate["n2_committed"] = False
    with pytest.raises(ValueError, match="preconditions"):
        require_gate(gate, {"split": "held_in"})
    gate = allowed()
    gate["review_kind"] = "unknown"
    with pytest.raises(ValueError, match="authority"):
        require_gate(gate, {"split": "held_in"})


def test_full_cycle_refuses_held_out_even_with_an_open_gate():
    with pytest.raises(ValueError, match="held-out"):
        require_gate(allowed(), {"split": "held_out"})
