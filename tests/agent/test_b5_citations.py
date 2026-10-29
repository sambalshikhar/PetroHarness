"""The loop's checks L6 and L7: the citation bookkeeping (autocite) and the lookups-per-step limit (loop.ACTIONS),
on stub items and the real prompt texts.

    .venv/bin/python -m pytest tests/agent/test_b5_citations.py -q
"""
import re
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from test_b6_claims import MAPTEXT, StubLedger, item  # noqa: E402
from petroharness.agent import options  # noqa: E402
from petroharness.agent.claims import Claims  # noqa: E402

E1 = item("E1", "stats", ["SW [v/v] = water saturation (computed)", "  Z1 SAND 1950-1975 m: n 50 of 50, mean 0.4567"])
E2 = item("E2", "stats", ["RDEP [ohm.m] = deep resistivity (input)", "  Z2 SAND 1975-2000 m: n 40 of 40, mean 8.402"])
E3 = item("E3", "stats", ["PHIE [v/v] = effective porosity (computed)", "  Z2 SAND 1975-2000 m: n 30 of 30, mean 0.2311",
                          "  pooled: mean 0.3417"])
E4 = item("E4", "stats", ["PHIT [v/v] = total porosity (computed)", "  pooled: mean 0.3417"])
E5 = item("E5", "profile", ["PHID [v/v]", "  pooled: mean 0.3417"])
E6 = item("E6", "stats", ["PHIN [v/v]", "  pooled: mean 0.3417", "  Z2 SAND: mean 0.231"])


def flags_and_ev(text, ev, on, items=(E1, E2, E3, E4, E5, E6)):
    c = Claims(["p1"], StubLedger(list(items)), MAPTEXT, "What is the porosity?", None, ("35/11-6",))
    c.apply([{"op": "add", "point": 1, "text": text, "ev": list(ev), "grade": "moderate",
              "means": "so the porosity answer rests on these values", "weak": ""}])
    cl = c.claims["C1"]
    return [f for f in cl.flags if f.startswith("K3")], cl.ev


@pytest.mark.parametrize("text, ev, on, cited, flagged", [
    # a 4-digit number one item holds, its sentence naming nothing the line names: cited (autocite)
    ("The mean is 0.4567 overall.", ["E2"], True, {"E1"}, False),
    # a 4-digit number three items hold (E3 E4 E5 hold 0.3417; E6 too, so four): four holders stay flagged
    ("Pooled porosity mean 0.3417.", ["E2"], True, set(), True),
    # a 3-digit number with its context (Z2; E6 shows 0.231, E3 shows 0.2311, which is not 0.231 written as shown)
    ("Z2 mean 0.231 v/v.", ["E2"], True, {"E6"}, False),
    # a number no item shows stays flagged
    ("The mean is 0.5123 overall.", ["E2"], True, set(), True),
])
def test_l6_autocite(text, ev, on, cited, flagged):
    k3, got = flags_and_ev(text, ev, on)
    assert set(got) - set(ev) == cited, (got, k3)
    assert bool(k3) is flagged, k3


def test_l6_autocite_three_holders():
    items = (E1, E2, E3, E4, E5)                                   # 0.3417 in E3, E4, E5: three holders
    k3, got = flags_and_ev("Pooled porosity mean 0.3417.", ["E2"], True, items)
    assert set(got) == {"E2", "E3", "E4", "E5"} and not k3


@pytest.mark.parametrize('n', [6])
def test_l7_the_prompt_states_the_limit_the_loop_applies(n):
    from petroharness.agent.loop import brief, step1 as step1_text
    b = brief()
    step1 = step1_text()                                            # the plugged library's
    assert "{ACTIONS}" not in b and "{ACTIONS}" not in step1
    assert f"run at most {n} actions" in b and f"- next: at most {n} actions to run now" in b
    assert f"do not count toward the {n} actions" in b and f"beside the {n} actions" in step1
    assert "up to 2 a step" in b and "(up to 3 a step; they do not count" in b                # guides, calcs unchanged
    assert not re.search(r"\b3 actions\b", b) or n == 3
