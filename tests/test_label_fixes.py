"""Labels and map texts that misled the model (the names, reach, traces and advice audits of 2026-11-18, "for the
morning"), each checked against the well's own record or its raw arrays.

    .venv/bin/python -m pytest tests/test_label_fixes.py -q -n 4
"""
import re

import numpy as np
import pytest

from _wells import CASES, formation_of

pytestmark = pytest.mark.data


def _map(case):
    from petroharness.agent.map import render
    f = formation_of(CASES[case])
    return f, render(f.inv)


# --- names 13: a value the record keeps a unit beside ------------------------------------------------------------------

@pytest.mark.parametrize("case, unit", [("tuhua", "m"), ("hw3", "ft")])
def test_td_is_shown_with_the_unit_the_record_keeps_beside_it(case, unit):
    f, text = _map(case)
    td = (f.view.prep.steps["temperature"]["parameters"])["td"]
    from petroharness.agent.map import num
    assert f"td {num(td)} {unit};" in text


# --- names 1 and 6: one rule for a curve that holds one value; the kind from the values ------------------------------

def test_swirr_app_per_sample_is_a_model_output_not_a_parameter():
    from petroharness.agent import engine as E
    f = formation_of(CASES["tuhua"])
    x = np.asarray(f.view.well_values("SWIRR_APP"), dtype=float)
    assert np.unique(x[np.isfinite(x)]).size > 100                       # Buckles, per sample
    st = E.status(f, "SWIRR_APP")
    assert st.startswith("model output of the permeability step") and "one value" not in st
    assert "a parameter" not in f.inv.curves["SWIRR_APP"].catalog


@pytest.mark.parametrize("case, c, step, value", [("1671", "SWIRR_APP", "permeability", "0.2"),
                                                   ("tuhua", "VANHY", "lithology", "0")])
def test_a_curve_that_holds_one_value_is_said_to_by_one_rule(case, c, step, value):
    """Whatever set it (16/7-1: the default swirr 0.2 its step lists; tuhua: VANHY 0, no setting), one label, no name
    matching; the step's record says how."""
    from petroharness.agent import engine as E
    f, text = _map(case)
    x = np.asarray(f.view.prep.curve(c), dtype=float)
    x = x[np.isfinite(x)]
    assert x.size > 1 and x.min() == x.max() == float(value)
    assert f"{c} {value}: one value over the whole well as the {step} step wrote it (" in text
    assert "a parameter of the" not in text and "not one of its settings" not in text
    assert E.tagged(f, c) == f"{c} (one value)"


# --- names 3: the resistivity pair the record names ---------------------------------------------------------------------

@pytest.mark.parametrize("case, shallow, deep, medium", [("tuhua", "RESM", "RESD", True), ("cheal", "RESS", "RESD", False),
                                                         ("teapot", "SFL", "ILD", False), ("brent", "RSHA", "RDEP", False)])
def test_the_invasion_ratio_names_the_pair_it_is_here(case, shallow, deep, medium):
    f, text = _map(case)
    r, s, d = (np.asarray(f.view.values(c), dtype=float) for c in ("INVASION_RATIO", shallow, deep))
    ok = np.isfinite(r) & np.isfinite(s) & np.isfinite(d) & (d > 0)
    assert ok.sum() > 50 and np.allclose(r[ok], s[ok] / d[ok], rtol=1e-3)      # the pair, from the raw arrays
    line = next(ln for ln in text.splitlines() if "in this interval INVASION_RATIO =" in ln)
    assert f"INVASION_RATIO = {shallow}/{deep} at {int(ok.sum())} samples" in line
    assert ("(a medium resistivity, where no shallow log is)" in line) == medium
    assert ("no medium resistivity stands in for a shallow one here" in line) == (not medium)


def test_an_analyzer_ratio_that_holds_the_workflow_ratio_says_so():
    f, text = _map("tuhua")
    a, w = (np.asarray(v, dtype=float) for v in (f.view.well_values("RXO_RDEP_RATIO"), f.view.prep.curve("INVASION_RATIO")))
    both = np.isfinite(a) & np.isfinite(w)
    assert both.sum() > 50 and np.allclose(a[both], w[both])
    line = next(ln for ln in text.splitlines() if ln.strip().startswith("RXO_RDEP_RATIO ="))
    assert "(same values as INVASION_RATIO)" in line and "flushed-to-deep" not in line.split("(this run")[0]


# --- names 4: what this run computed -------------------------------------------------------------------------------------

def test_the_runs_own_description_is_shown_where_it_says_how():
    """S_V: the catalog's general line, and this run's description (general mode: from the datum)."""
    f, text = _map("brent")
    line = next(ln for ln in text.splitlines() if ln.strip().startswith("S_V ="))
    assert "(this run: Overburden stress from the datum" in line
    assert "increment from the top of the analysed interval" not in line
    assert f.inv.curves["GR_GRAD"].run_said == ""                         # a label only: not shown


# --- names 5: LITHO's codes --------------------------------------------------------------------------------------------

def test_litho_codes_are_named_from_petrophys_code_table():
    from petrophys.interpretation.lithology.lithology_module import LithologyModule
    from petroharness.agent import schemas
    f = formation_of(CASES["tuhua"])
    names = {v: k for k, v in LithologyModule.LITHOLOGY_CODES.items()}
    x = np.asarray(f.view.values("LITHO"), dtype=float)
    present = sorted({int(v) for v in x[np.isfinite(x)]})
    t = schemas.call(f, "stats", {"curves": ["LITHO"]}).text
    for code in present:
        assert re.search(rf"class {code} \({names[code]}\)", t), code


# --- names 7: what NET_RES leaves out ----------------------------------------------------------------------------------

def test_net_exclusion_records_the_kind_that_left_each_sample_out():
    """Petrophys's NET_EXCLUSION (its codes in the curve's metadata): every sample coded bad hole has BAD_HOLE set,
    and on tuhua the 8 samples that are NET_ROCK but not NET_RES (PHIE above the cutoff) are all coded bad hole."""
    from petroharness.well.summary import code_labels
    f = formation_of(CASES["tuhua"])
    v = f.view
    kinds = code_labels(v, "NET_EXCLUSION")
    ex, rock, res, bh, phie = (np.asarray(v.values(c), dtype=float)
                               for c in ("NET_EXCLUSION", "NET_ROCK", "NET_RES", "BAD_HOLE", "PHIE"))
    hole = next(k for k, name in kinds.items() if name == "bad_hole")
    assert (bh[ex == hole] > 0.5).all() and not (res[ex > 0] > 0.5).any()     # left out of NET_RES, whatever else
    gap = (rock > 0.5) & ~(res > 0.5)
    assert gap.sum() == 8 and (ex[gap] == hole).all() and (phie[gap] > 0.08).all()


@pytest.mark.parametrize("case", ["tuhua", "brent", "1671"])
def test_pay_summary_splits_what_is_not_net_res_by_each_recorded_exclusion(case):
    """Each kind with its share of the rock passing the clay cutoff, the rest the porosity cutoff; the shares from the
    curves (1671: most of it evaporite, which the porosity cutoff was blamed for)."""
    from petroharness.record.catalog import pay_summary
    from petroharness.well.view import fmt_pct
    from petroharness.well.summary import code_labels
    f = formation_of(CASES[case])
    v = f.view
    ex, rock, res = (np.asarray(v.values(c), dtype=float) for c in ("NET_EXCLUSION", "NET_ROCK", "NET_RES"))
    gap, tested = (rock > 0.5) & ~(res > 0.5), int((rock > 0.5).sum())
    fact = next(x for x in pay_summary(v)["facts"] if x.startswith("cutoffs in order"))
    for code, kind in code_labels(v, "NET_EXCLUSION").items():
        k = int((gap & (ex == code)).sum())
        if not k:
            continue
        pct = fmt_pct(100 * k / tested)
        assert (f"{pct} fails the porosity cutoff" if not code else
                f"{pct} is left out as {kind.replace('_', ' ')} (whatever its porosity)") in fact, (case, kind, fact)


# --- names 8: VCL as the record combined it ----------------------------------------------------------------------------

@pytest.mark.parametrize("case, rule, left", [("tuhua", "min(GR, ND)", True), ("1671", "VCL_GR", True),
                                              ("hw3", "min(GR, ND)", False)])
def test_the_vcl_note_states_the_records_rule(case, rule, left):
    from petroharness.record.card import last_step, vcl_fact
    f = formation_of(CASES[case])
    st = last_step(f.view.prep.steps, "vclay")
    assert st["parameters"]["vcl_rule"] == rule                           # Petrophys records it as data
    assert any(f"Final VCL = {rule} at each depth" in d for d in st["decisions"])
    text = vcl_fact(st, {})
    assert text.startswith(f"VCL: {rule} at each depth, as the record states it")
    assert ("VCL_SP computed but left out of VCL" in text) == left
    assert "combination rule not recorded" not in text


# --- names 11, 12: what a value is where its name misleads -------------------------------------------------------------

def test_the_rwa_check_on_another_rw_route_is_labelled():
    f, text = _map("hw3")
    assert f.view.prep.steps["rw"]["method"] != "rwa_clean_wet_p5"
    notes = f.view.prep.steps["rw"]["notes"]                              # Petrophys's notes on its parameters
    assert notes["rwa_median_over_rw"].startswith("a check of the Rw in use, on any Rw route")
    assert re.search(r"rwa_median_over_rw 98\.978\d? \(a check of the Rw in use, on any Rw route", text)
    assert "RWA" not in f.inv.curves                                        # Rwa is no curve here


def test_kh_is_not_horizontal_permeability():
    f = formation_of(CASES["brent"])
    assert "not the horizontal permeability KH_CORE holds" in f.inv.curves["KH"].catalog


# --- reach 10: where the temperature comes from ------------------------------------------------------------------------

@pytest.mark.parametrize("case, said", [
    ("tuhua", "the measured temperature log at 100.0% of the well's samples; where the log has no value, a default "
              "gradient 1.6459 degF/100ft from a surface 68 degF (no bottom-hole temperature anchors it), at 0 samples"),
    ("1671", "fallback_geothermal_gradient: a default gradient 1.6459 degF/100ft from a surface 68 degF (no bottom-hole "
             "temperature anchors it)"),
    ("brent", "linear_gradient_from_BHT: the gradient 1.6354 degF/100ft from a surface 68 degF to the bottom-hole 258.8 degF")])
def test_the_temperature_estimate_says_where_its_gradient_comes_from(case, said):
    from petroharness.agent import schemas
    f = formation_of(CASES[case])
    assert said in schemas.call(f, "estimate", {"parameter": "temperature"}).text


def test_a_curve_held_at_one_value_is_said_for_any_curve():
    """engine.limits, which every curve's card line reads: tuhua's TEMP holds one value over most zoned samples; the
    temperature estimate says it by the same check."""
    from petroharness.agent import engine as E, schemas
    f = formation_of(CASES["tuhua"])
    idx = np.unique(np.concatenate([np.asarray(z.indices) for z in f.view.zones]))
    x = np.asarray(f.view.values("TEMP"), dtype=float)[idx]
    x = x[np.isfinite(x)]
    vals, counts = np.unique(x, return_counts=True)
    v, share = float(vals[counts.argmax()]), 100 * counts.max() / x.size
    assert share > 50 and x.min() < v < x.max()
    said = f"one value, {E.num(v)}, in {share:.1f}% of the zoned samples (a held or padded reading)"
    assert said in E.limits(f, "TEMP") and said in E.provenance(f, ["TEMP"])
    assert f"TEMP {said}" in schemas.call(f, "estimate", {"parameter": "temperature"}).text
    assert not any("one value," in x for x in E.limits(f, "GR"))


# --- traces 7: a derived quantity Petrophys may compute -----------------------------------------------------------------

def test_an_absent_derived_quantity_names_the_functions_that_may_compute_it():
    from petroharness.agent import vocabulary
    from petroharness.agent.loop import Session
    f = formation_of(CASES["tuhua"])
    assert not f.view.available("MHI")
    s = Session.__new__(Session)
    s.f, s.reading = f, {"named": ["moveable hydrocarbon index"]}
    s.task = type("T", (), {"question": "Is there moveable hydrocarbon?"})()
    note = vocabulary.note(s)
    assert "moveable hydrocarbon index (MHI; Petrophys may compute it: classify calculate_mhi)" in note


# --- traces 10: the core beside the core-calibrated curves ---------------------------------------------------------------

def test_the_core_calibrated_note_names_the_plugs():
    f = formation_of(CASES["brent"])
    note = next(n for n in f.inv.notes if n.startswith("Core-calibrated curves"))
    for c in ("PHIC", "KH_CORE", "SWC"):
        n = int(np.isfinite(np.asarray(f.view.values(c), dtype=float)).sum())
        assert f"{c} ({n} plugs)" in note
    assert "log curves fitted to the core, not the core" in note


# --- advice a5: Petrophys's advice as tool calls ------------------------------------------------------------------------

def test_petrophys_advice_is_given_as_the_tool_calls_that_take_its_inputs():
    """The inputs come as data (Petrophys Advice.inputs, collected at the call door), not from the sentence."""
    from petroharness.agent.library import advice_calls
    said = advice_calls(["rmf", "rmf_temp_f", "train_wells"], kind="saturation")
    assert said == ('as tool calls: {"calculate": {"property": "mud_filtrate_resistivity", "parameters": {"rmf": ..., '
                    '"rmf_temp_f": ...}}}; train_wells: no tool here takes it')
    assert advice_calls(["rcl", "m"], kind="saturation") == \
        'as tool calls: {"calculate": {"property": "saturation", "parameters": {"rcl": ..., "m": ...}}}'
    assert advice_calls(["zones", "rcl"], takes=["zones", "where"]) == \
        'as tool calls: zones: an argument of this call; {"calculate": {"property": "saturation", "parameters": {"rcl": ...}}}'
    assert advice_calls([]) == ""


def test_the_call_door_gives_the_calls_petrophys_advice_names_for_any_tool():
    """At the call door, on every tool's result and refusal that quotes Petrophys: tuhua, calculate Simandoux."""
    from petroharness.agent import schemas
    f = formation_of(CASES["tuhua"])
    r = schemas.call(f, "calculate", {"property": "saturation", "method": "simandoux"})
    lines = r.text.splitlines()
    assert any("Petrophys did not run:" in ln and "steps.mud_filtrate(rmf=..., rmf_temp_f=...)" in ln for ln in lines)
    want = 'as tool calls: {"calculate": {"property": "mud_filtrate_resistivity", "parameters": {"rmf": ..., "rmf_temp_f": ...}}}'
    assert lines[-1].strip() == want and r.rows[-1][0].strip() == want      # in the result, and kept for its get
    plain = schemas.call(f, "stats", {"curves": ["GR"]}).text
    assert "as tool calls" not in plain


# --- question suite F4: measured logs the workflow renamed or standardized -------------------------------------------

@pytest.mark.parametrize("case, c, said", [
    ("teapot", "RDEP", "measurement: the input ILD under the workflow's name (the normalization step)"),
    ("tuhua", "RHOB", "measurement: the input DENS under the workflow's name (the normalization step)"),
    ("brent", "GR", "measurement, as the normalization step standardized it"),
    ("tuhua", "DENS", "measurement"), ("tuhua", "VCL", "model output of the vclay step")])
def test_a_measured_log_the_workflow_renamed_or_standardized_is_a_measurement(case, c, said):
    """The suite (B03, K01, P01, R01): RDEP, NPHI, RSHA, GR were 'model output of the normalization step', and the writer
    cautioned 'trust is limited to the workflow's normalization choices'. A copy of a measured input, or a measured
    log a step reads and writes, is a measurement; a computed curve stays a model output."""
    from petroharness.agent import engine as E
    f = formation_of(CASES[case])
    st = E.status(f, c)
    assert st.split(";")[0] == said, st
    if c == "RHOB":                                  # its values are the LAS's DENS
        a, b = (np.asarray(f.view.prep.curve(x), dtype=float) for x in ("RHOB", "DENS"))
        assert np.allclose(np.nan_to_num(a, nan=-1), np.nan_to_num(b, nan=-1))


def test_the_las_own_curves_are_the_maps_raw_input():
    """tuhua's LAS holds DENS, NEUT and RESD; the map listed them nowhere as input (the loaded well's names are the
    library's aliases) and RESD read 'copy of RDEP'."""
    from petroharness.agent import engine as E
    f, text = _map("tuhua")
    raw = next(l for l in text.splitlines() if l.startswith("  curves: "))
    for c in ("DENS", "NEUT", "RESD"):
        assert f"{c} = " in raw and not E.status(f, c).startswith("copy of"), (c, E.status(f, c))
