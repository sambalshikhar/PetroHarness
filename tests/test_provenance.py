"""Where a curve comes from, read from the step record and the LAS, never assumed (card.curve_origin and the card
lines built on it), and V4 judging a core-calibration denial where it speaks (verify.availability_issues).

    PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_provenance.py -q
"""

from types import SimpleNamespace

import numpy as np
import pytest

from petroharness.record.card import (_same_values, curve_origin, input_text, producer, readers, saturation_fact,
                               unmodelled_fact)
from petroharness.registry import load as load_registry
from petroharness.agent.checks import availability_issues

REG = load_registry()
N = 40


def step(inputs, outputs, decisions=()):
    return {"method": "m", "parameters": {}, "decisions": list(decisions), "inputs": list(inputs), "outputs": list(outputs)}


def stand_in(steps, inputs=(), curves=None, zones=()):
    curves = curves or {}
    prep = SimpleNamespace(steps=steps, input_curves=list(inputs), curve=lambda c: curves.get(c))
    return SimpleNamespace(prep=prep, reg=REG, zones=list(zones),
                           available=lambda c: c in curves and bool(np.isfinite(curves[c]).any()),
                           values=lambda c: curves.get(c),
                           zone_values=lambda z, c: None if curves.get(c) is None else curves[c][z.indices],
                           task=SimpleNamespace(las_path=None))


BASE = np.linspace(0.01, 80.0, N)


# --- curve_origin ----------------------------------------------------------------------------------------------------

def test_a_recorded_step_wins_over_the_las():
    view = stand_in({"saturation": step(["RDEP", "PHIE"], ["SW"])}, inputs=["SW", "RDEP"], curves={"SW": np.ones(N)})
    assert curve_origin(view, "SW") == ("step", "saturation", ["RDEP", "PHIE"])


def test_supplied_when_the_las_carries_it_and_no_step_wrote_it():
    view = stand_in({"bvw": step(["PHIE_CC", "SW"], ["BVW"])}, inputs=["PHIE_CC"], curves={"PHIE_CC": np.ones(N)})
    assert curve_origin(view, "PHIE_CC") == ("supplied",)
    assert curve_origin(view, "phie_cc".upper()) == ("supplied",)


def test_a_copy_of_a_supplied_curve():
    view = stand_in({"bvw": step([], ["BVW"])}, inputs=["PERM_CC"], curves={"PERM": BASE.copy(), "PERM_CC": BASE})
    assert curve_origin(view, "PERM") == ("copy", "PERM_CC")


def test_a_copy_survives_a_few_samples_removed_by_qc_but_not_many():
    few, many = BASE.copy(), BASE.copy()
    few[:1] = np.nan                                           # 1 of 40 removed: still the same values
    many[:5] = np.nan                                          # 5 of 40: defined at other depths, not a copy
    for perm, want in ((few, ("copy", "PERM_CC")), (many, ("unrecorded",))):
        view = stand_in({"bvw": step([], ["BVW"])}, inputs=["PERM_CC"], curves={"PERM": perm, "PERM_CC": BASE})
        assert curve_origin(view, "PERM") == want


@pytest.mark.parametrize("perm", [BASE * (1 + 1e-6), BASE[::-1].copy(), BASE[:-1].copy(), np.full(N, np.nan)])
def test_close_reordered_shorter_or_empty_values_are_not_a_copy(perm):
    view = stand_in({"bvw": step([], ["BVW"])}, inputs=["PERM_CC"], curves={"PERM": perm, "PERM_CC": BASE})
    assert curve_origin(view, "PERM") == ("unrecorded",)


def test_a_record_without_input_output_lists_says_only_what_the_las_shows():
    """Without output lists a step may have written PERM, so no copy is claimed; a curve the LAS carries is supplied
    whatever the record's format (the harness adapts to that input)."""
    view = stand_in({"permeability": {"method": "m", "parameters": {}, "decisions": []}}, inputs=["PERM_CC"],
                    curves={"PERM": BASE.copy(), "PERM_CC": BASE})
    assert curve_origin(view, "PERM") is None and unmodelled_fact(view, "PERM") is None
    assert curve_origin(view, "PERM_CC") == ("supplied",)


def test_same_values_needs_overlap_both_ways():
    a, b = BASE.copy(), BASE.copy()
    b[10:] = np.nan
    assert not _same_values(a, b) and not _same_values(b, a)
    assert _same_values(a, a.copy()) and not _same_values(a, None) and not _same_values(None, None)


# --- record helpers ---------------------------------------------------------------------------------------------------

def test_producer_takes_the_last_step_that_wrote_the_curve():
    steps = {"saturation": step(["RDEP", "PHIE"], ["SW"]), "saturation_final": step(["RDEP", "PHIE_CC"], ["SW", "SO"])}
    assert producer(steps, "SW") == ("saturation_final", ["RDEP", "PHIE_CC"])
    assert producer(steps, "BVW") is None and producer({}, "SW") is None and producer(None, "SW") is None


@pytest.mark.parametrize("name, text", [("PHIE_CC+PHIE", "(PHIE_CC where present, otherwise PHIE)"), ("RDEP", "RDEP"),
                                        ("A+B+C", "(A where present, otherwise B where present, otherwise C)"),
                                        ("SWIRR/SW", "(SWIRR where present, otherwise SW)")])
def test_input_text(name, text):
    assert input_text(name) == text


def test_readers_see_composite_inputs_and_list_what_they_wrote():
    steps = {"saturation": step(["RDEP", "PHIE_CC+PHIE", "VCL"], ["SW", "SO", "SXO"]),
             "net_pay": step(["VCL", "PHIE_CC", "SW"], ["NET_ROCK", "NET_RES", "NET_PAY", "RESFLAG", "SEALFLAG"]),
             "porosity": step(["RHOB", "NPHI"], ["PHIT", "PHIE"]), "temperature": step([], ["TEMP"])}
    got = readers(steps, ["PHIE_CC"])
    assert got == ["saturation (SW, SO, SXO)", "net_pay (NET_ROCK, NET_RES, NET_PAY, RESFLAG, ...)"]
    assert readers(steps, ["PERM_CC"]) == [] and readers({}, ["PHIE_CC"]) == []


def test_saturation_fact_names_what_the_step_read_only_when_recorded():
    sat = {"method": "archie", "parameters": {"sw_model": "archie", "a": 1.0, "m": 2.0, "n": 2.0}, "decisions": []}
    names = REG.curves.get("method_names", {})
    without = saturation_fact(sat, names, {})
    with_inputs = saturation_fact(sat | {"inputs": ["RDEP", "PHIE_CC+PHIE", "VCL"]}, names, {})
    assert "computed from" not in without
    assert with_inputs == without + "; computed from RDEP, (PHIE_CC where present, otherwise PHIE), VCL"


@pytest.mark.parametrize("origin_steps, inputs, curves, want", [
    ({"bvw": step([], ["BVW"])}, ["PERM_CC"], {"PERM": BASE.copy(), "PERM_CC": BASE},
     "PERM: the same values as PERM_CC (no model in the record), so the PERM of record is the supplied PERM_CC"),
    ({"bvw": step([], ["BVW"])}, ["PERM"], {"PERM": BASE}, "PERM: supplied in the LAS; no model in the record"),
    ({"bvw": step([], ["BVW"])}, [], {"PERM": BASE}, "PERM: method not recorded"),
    ({"permeability": step(["PHIE"], ["PERM"])}, [], {"PERM": BASE}, None),            # the PERM line covers it
    ({"bvw": step([], ["BVW"])}, [], {}, None),                                         # no PERM in the interval
])
def test_unmodelled_fact(origin_steps, inputs, curves, want):
    assert unmodelled_fact(stand_in(origin_steps, inputs, curves), "PERM") == want


# --- V4: a denial judged where it speaks ------------------------------------------------------------------------------

def zone(zid, a, b):
    return SimpleNamespace(zone_id=zid, indices=np.arange(a, b))


PART = np.full(N, np.nan)
PART[:20] = 10.0                                       # PERM_CC only in Z1 (samples 0-19)
ZONES = [zone("Z1", 0, 20), zone("Z2", 20, 40)]
COSTA_LIKE = stand_in({"bvw": step([], ["BVW"])}, inputs=["PHIE_CC", "PERM_CC"],
                      curves={"PHIE_CC": np.full(N, 0.2), "PERM_CC": PART}, zones=ZONES)
NO_CORE = stand_in({}, curves={"PHIE": np.full(N, 0.2)}, zones=ZONES)


@pytest.mark.parametrize("text", [
    "Core-calibrated porosity is not available in this interval.",
    "No core calibration of permeability exists.",
    "PERM_CC is unavailable in Z1.",
    "In Z1 the permeability has no core calibration.",
])
def test_denials_of_curves_that_exist_where_said_are_flagged(text):
    issues = availability_issues(text, COSTA_LIKE, REG)
    assert len(issues) == 1 and "supplied in the LAS as core-corrected values" in issues[0]


@pytest.mark.parametrize("text", [
    "PERM_CC is absent in Z2, so RQI has no value there.",                               # true: no PERM_CC in Z2
    "In Z1 PERM_CC is 10 mD; in Z2, PERM_CC is missing.",                                # per clause
    "PHIE_CC-PERM consistency cannot be tested: PERM_CC is missing entirely from Z2.",   # per clause, named curve
    "BVW uses PHIE_CC where present, falling back to PHIE where PHIE_CC is missing.",    # coverage, not denial
    "If PERM_CC were unavailable, PERM would be the only estimate.",                     # hypothetical
    "| Z2 | PERM_CC | missing |\n| Z1 | PERM_CC | 10 |",                                  # a table row on its own
])
def test_true_partial_and_conditional_statements_are_not_flagged(text):
    assert availability_issues(text, COSTA_LIKE, REG) == []


def test_citing_core_curves_that_do_not_exist_is_flagged_and_their_absence_is_not():
    assert availability_issues("PERM_CC averages 12 mD.", NO_CORE, REG)
    assert availability_issues("No PERM_CC or PHIE_CC exists in this interval.", NO_CORE, REG) == []


def test_at_most_one_message():
    text = "Core calibration is not available. PERM_CC is unavailable. PHIE_CC is missing."
    assert len(availability_issues(text, COSTA_LIKE, REG)) == 1
