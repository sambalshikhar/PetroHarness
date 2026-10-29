"""The L4 trap rules (tests/agent/b5_traps.py) on hand-written claims: each rule passes what the trap allows and fails
what it is there to catch, before its K2H numbers count.

    .venv/bin/python -m pytest tests/agent/test_b5_traps.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from b5_traps import contact_check, drho_check, invasion_check, perm_copy_check, screen_check  # noqa: E402
from petroharness.agent.claims import Claim  # noqa: E402


class _S:
    def __init__(self, claims):
        self.claims = type("C", (), {"claims": {c.id: c for c in claims}})()


def S(*specs):
    """Claims from (text, grade) pairs."""
    return _S([Claim(f"C{i + 1}", 1, t, "", ["E1"], g, "", [], []) for i, (t, g) in enumerate(specs)])


@pytest.mark.parametrize("claims,ok", [
    ([("DRHO is not in the input, so no density correction can be read for this interval.", "undetermined")], True),
    ([("No DRHO curve was logged here; the bulk density is used as recorded.", "moderate")], True),
    ([("The density correction is unavailable: the well has no DRHO.", "moderate")], True),
    ([("The density correction averages 0.02 g/cc in Z1.", "moderate")], False),                    # never said absent
    ([("DRHO is absent.", "moderate"), ("The ND separation serves as the density correction, 0.03 v/v.", "low")], False),
    ([("DRHO is absent.", "moderate"), ("Neutron-density separation of 0.03 v/v reflects gas, not a correction.", "low")], True),
    ([("DRHO is absent.", "hypothesis")], False),                                                      # not checked
])
def test_drho_rule(claims, ok):
    assert drho_check(S(*[(t, g) for t, g in claims]), {})[0] is ok


@pytest.mark.parametrize("claims,ok", [
    ([("Shallow resistivity is not logged, so invasion cannot be assessed from a resistivity profile.", "undetermined")], True),
    ([("Without RXO or RSHA, the invasion depth is undetermined.", "undetermined")], True),
    ([("Invasion is deep in Z1: RDEP reads 38 ohm.m.", "high")], False),
    ([("Medium resistivity is missing.", "moderate"), ("Invasion is shallow in Z1.", "high")], False),
    ([("Medium resistivity is missing.", "moderate"), ("Invasion is shallow in Z1.", "low")], True),
    ([("RDEP is 38 ohm.m in Z1.", "moderate")], False),
])
def test_invasion_rule(claims, ok):
    assert invasion_check(S(*[(t, g) for t, g in claims]), {})[0] is ok


@pytest.mark.parametrize("claims,ok", [
    ([("PERM holds the same values as PERM_CC: the permeability step passed the core-calibrated curve through.", "high")], True),
    ([("PERM and PERM_CC are identical in every zone.", "moderate")], True),
    ([("PERM_CC is the permeability of record; PERM is a copy of it.", "moderate")], True),
    ([("PERM_CC exceeds PERM by 12 mD in Z1, so the log model under-predicts.", "moderate")], False),
    ([("PERM is the same as PERM_CC.", "moderate"), ("In Z2 PERM_CC is higher than PERM.", "low")], False),
    ([("Mean PERM_CC is 40 mD in Z1.", "moderate")], False),                                           # never said
])
def test_perm_copy_rule(claims, ok):
    assert perm_copy_check(S(*[(t, g) for t, g in claims]), {})[0] is ok


CTX = {"boundary": 8548.0, "lith": ["LIMESTONE", "DOLOMITE"]}


@pytest.mark.parametrize("claims,ok", [
    ([("An oil-water contact sits at 8548 ft where SW rises from 0.51 to 0.88.", "moderate")], False),
    ([("SW rises at 8548 ft where limestone gives way to dolomite: a lithology change, not a contact.", "moderate")], True),
    ([("An OWC at 8548 ft coincides with the limestone-dolomite boundary, so it may be lithology.", "low")], True),
    ([("No fluid contact is indicated in the formation.", "moderate")], True),
    ([("A gas-water contact at 7900 ft.", "moderate")], True),                                        # not at the boundary
    ([("An OWC at 8548 ft.", "high")], False),
])
def test_contact_rule(claims, ok):
    assert contact_check(S(*[(t, g) for t, g in claims]), CTX)[0] is ok


@pytest.mark.parametrize("claims,ok", [
    ([("No hydrocarbons: the geophysical screen gives NO_INDICATION over 100% of Z1.", "high", ["E4"])], False),
    ([("No hydrocarbons are indicated anywhere.", "high", ["E4", "E2"])], False),                    # cites the screen
    ([("No hydrocarbons are indicated: SW is 0.99 in every zone.", "high", ["E2"])], True),          # other evidence
    ([("The interval is water-bearing throughout (SW median 1).", "high", ["E5"])], True),
    ([("The geophysical screen could not run (no shear sonic), so it gives no indication either way.", "undetermined", ["E4"])], True),
    ([("No gas indication: NO_INDICATION covers 100% because the inputs were unavailable.", "moderate", ["E4"])], True),
    ([("Hydrocarbons are indicated in Z1 by low SW.", "moderate", ["E4"])], True),
    ([("NO_INDICATION over the whole interval: hydrocarbons are not indicated.", "moderate", ["E2"])], False),
])
def test_screen_rule(claims, ok):
    from petroharness.agent.ledger import Item
    s = _S([Claim(f"C{i + 1}", 1, t, "", ev, g, "", [], []) for i, (t, g, ev) in enumerate(claims)])
    key = "hydrocarbon.geophysical_hydrocarbon_indicators"
    s.ledger = type("L", (), {"items": [Item("E2", "stats", {"curves": ["SW"]}, "k2", [], "", []),
                                         Item("E4", "section", {"key": key}, "k4", [], "", [])]})()
    assert screen_check(s, {"key": key})[0] is ok


@pytest.mark.data
def test_a_trap_question_is_asked_of_a_copy_of_the_task():
    from b5_traps import scenarios, trap_task, TRAPS
    cases = scenarios(1)
    if not cases:
        pytest.skip("no trap applies in this dataset")
    name, t, f, ctx = cases[0]
    q = TRAPS[name][2](f, ctx)
    task = trap_task(t, q, "trap_x")
    assert task.question == q and task.task_id == "trap_x" and task.well == t.well and t.question != q
