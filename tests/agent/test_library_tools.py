"""The verbs over Petrophys (src/petroharness/agent/library.py): the library's catalog read as
the menus, the calls checked against it, the steps a change carries into, and, on a sample well (data), calculate,
estimate and what_if as the model would call them.

    .venv/bin/python -m pytest tests/agent/test_library_tools.py -q
"""
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src")]
from petroharness.agent import library as L
from petroharness.agent import schemas
from petroharness.agent.engine import ToolError

SAMPLES = Path(os.environ.get("PETROHARNESS_SAMPLE_LAS", "sample_las"))   # a folder of sample wells; tests skip without it


# --- the catalog ----------------------------------------------------------------------------------------------------

def test_the_methods_come_from_the_librarys_catalog():
    sat = dict(L.choices("saturation"))["model"]
    names = [n for n, _ in sat]
    assert {"archie", "simandoux", "indonesia", "dual_water", "waxman_smits"} <= set(names)
    assert dict(sat)["simandoux"] == ["rcl"] and "rwb" in dict(sat)["dual_water"]
    assert "timur" in [n for n, _ in L.choices("permeability")["method"]]


def test_properties_by_their_usual_names():
    assert L.kind_of("water saturation") == L.kind_of("SW") == L.kind_of("saturation") == "saturation"
    assert L.kind_of("vsh") == "clay_volume" and L.kind_of("rw") == "formation_water" and L.kind_of("cutoffs") == "net_pay"
    with pytest.raises(ToolError, match="no property 'magic'; properties: clay_volume"):
        L.kind_of("magic")


def test_a_call_is_checked_against_the_catalog():
    assert L._changes("saturation", "Simandoux", {"rcl": "4.2"}) == {"rcl": 4.2, "model": "simandoux"}
    assert L._changes("permeability", "timur", None) == {"method": "timur"}
    with pytest.raises(ToolError, match="no method 'magic'; methods: model: archie, simandoux"):
        L._changes("saturation", "magic", None)
    with pytest.raises(ToolError, match="saturation takes model, a, m, n.*not porosity_cutoff"):
        L._changes("saturation", None, {"porosity_cutoff": 0.1})


def test_a_change_carries_into_the_steps_that_read_its_outputs():
    assert L.downstream("saturation", ["SW", "SXO"]) == ["bvw", "mhi", "net_pay"]
    chain = L.downstream("clay_volume", ["VCL"])
    assert chain[:2] == ["porosity", "saturation"] and "net_pay" in chain and "bvw" in chain
    assert L.downstream("net_pay", ["NET_PAY"]) == []
    assert L.downstream("temperature", ["TEMP"])[:1] == ["formation_water"]


def test_labels_name_the_new_curves():
    assert L._label(None, {"model": "simandoux"}) == "SIMANDOUX"
    assert L._label("rw 0.03", {}) == "RW_0_03" and L._label(None, {"m": 2.2}) == "ALT"
    assert L._label("2x", {}) == "X2X"


def test_the_verbs_are_shown_with_the_lookups():
    names = [t["function"]["name"] for t in schemas.named()]
    assert set(schemas.LIBRARY_NAMES) == {"calculate", "estimate", "what_if", "check", "classify", "summarize",
                                          "calibrate"}
    assert set(schemas.LIBRARY_NAMES) < set(names) and "stats" in names
    shown = {t["function"]["name"]: t for t in schemas.named() if t["function"]["name"] in schemas.LIBRARY_NAMES}
    shown = [shown[n] for n in ("calculate", "estimate", "what_if", "check", "classify", "summarize", "calibrate")]
    calc = shown[0]["function"]["description"]
    assert "saturation: model: archie | simandoux" in calc and "net_pay:" in calc


# --- on a sample well (data) ----------------------------------------------------------------------------------------

def _session(las: Path, tops: Path = None, formation: str = None):
    import petroharness.ask as A
    from petroharness.agent.loop import Session
    from petroharness.config import DataPaths, HarnessConfig, ResourcePaths, given_settings
    from petroharness.tasks import Task
    tmp = tempfile.mkdtemp()
    held = os.environ.pop("PETROHARNESS_DATA", None)      # a data settings file set in the shell is not this well's
    try:
        data, _ = A._settings(las, None, None, None, Path(tmp), ResourcePaths().policy_file)
    finally:
        if held is not None:
            os.environ["PETROHARNESS_DATA"] = held
    span = A._interval(las, formation, tops, None, None, None, data)
    data.setdefault("depth_unit", "las")
    task = Task(task_id="a" + hashlib.sha256(str(las).encode()).hexdigest()[:10], question="q", well=las.stem,
                formation=span["name"], las_path=las, top=span["top"], base=span["base"],
                depth_unit=None if span["top"] is None else "las", base_closed=span["closed"], formation_lithology=None)
    with given_settings({"data": data, "eval": {}}):
        return Session.build(task, HarnessConfig(data=DataPaths(**data), eval=None)).f


@pytest.fixture(scope="module")
def topeka():
    las, tops = SAMPLES / "1046123714.las", SAMPLES / "1046123714_formation_tops.csv"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    return _session(las, tops, "Topeka")


@pytest.mark.data
def test_simandoux_saturation_then_its_statistics(topeka):
    f = topeka
    r = schemas.call(f, "calculate", {"property": "saturation", "method": "simandoux"})
    assert "model simandoux (asked)" in r.text and re.search(r"rcl 3\.39\d* \(record\)", r.text)
    assert "vsh_exp" not in r.text.split("\n")[0]                    # North Sea's input, not Simandoux's
    assert "the baseline reproduces the record's SW (100.0%" in r.text
    assert "SW_SIMANDOUX" in f.inv.curves and "written: SW_SIMANDOUX, SXO_SIMANDOUX, BVW_SIMANDOUX" in r.text
    assert "mhi: Needs RMF" in r.text                                 # the library's own reason, said back
    s = schemas.call(f, "stats", {"curves": ["SW_SIMANDOUX"]})
    assert "on request" in s.text and "zones pooled, SW_SIMANDOUX: n 65 of 65" in s.text
    assert r.numbers and all(np.isfinite(r.numbers))


@pytest.mark.data
def test_a_model_the_well_cannot_feed_is_refused_in_the_librarys_words(topeka):
    with pytest.raises(ToolError, match="dual_water' needs rwb"):
        schemas.call(topeka, "calculate", {"property": "saturation", "method": "dual_water"})


@pytest.mark.data
def test_a_changed_matrix_sets_its_own_densities(topeka):
    r = schemas.call(topeka, "calculate", {"property": "porosity", "parameters": {"matrix": "limestone"},
                                           "downstream": False, "label": "LS"})
    assert "matrix limestone (asked)" in r.text
    assert "matrix_density from the asked choice (the record's 2.65 not used)" in r.text
    m = re.search(r"PHIE: mean ([\d.]+) -> ([\d.]+) \(\+", r.text)      # against the baseline run, as reported
    assert m and float(m.group(2)) > float(m.group(1)) and "the baseline differs from the record's PHIE" in r.text


@pytest.mark.data
def test_what_if_cutoffs_and_models(topeka):
    r = schemas.call(topeka, "what_if", {"property": "net_pay", "parameter": "sw_cutoff", "values": [0.4, 0.5, 0.6]})
    pooled = [float(ln.split(": ")[1].split(" pooled")[0]) for ln in r.text.splitlines() if ln.strip().startswith("sw_cutoff")]
    assert pooled == sorted(pooled) and len(pooled) == 3                 # a looser SW cutoff never shrinks pay
    m = schemas.call(topeka, "what_if", {"property": "saturation", "parameter": "model",
                                         "values": ["archie", "simandoux"]})
    assert "model archie:" in m.text and "model simandoux:" in m.text and "baseline (record's parameters)" in m.text


@pytest.mark.data
def test_estimate_rw_against_the_records(topeka):
    f = _session(SAMPLES / "1046123714.las")
    r = schemas.call(f, "estimate", {"parameter": "rw"})
    assert "clean, porous samples (VCL < 0.3, PHIE > 0.05)" in r.text and "rwa_clean_wet_p5" in r.text
    assert "RWA" in f.inv.curves
    with pytest.raises(ToolError, match="estimates: rw"):
        schemas.call(f, "estimate", {"parameter": "magic"})


# --- estimate: GR endpoints, the apparent matrix, temperature, Rw from the SP (data) --------------------------------

@pytest.mark.data
def test_gr_endpoints_reproduce_the_records_rule():
    f = _session(SAMPLES / "1046123714.las") if (SAMPLES / "1046123714.las").exists() else pytest.skip("no sample wells")
    r = schemas.call(f, "estimate", {"parameter": "gr_endpoints"})
    whole = next(ln for ln in r.text.splitlines() if "over the whole well" in ln)
    rec = next(ln for ln in r.text.splitlines() if ln.strip().startswith("the record's"))
    p5, p95 = re.search(r"P5 ([\d.]+), P95 ([\d.]+)", whole).groups()
    assert f"gr_min {p5}" in rec and f"gr_max {p95}" in rec                  # the rule, as the record picked
    assert "bounded_gr_baselines" in r.text and "clean 20" in whole


@pytest.mark.data
def test_apparent_matrix(topeka):
    r = schemas.call(topeka, "estimate", {"parameter": "matrix"})
    assert "apparent_matrix_density" in r.text and "RHOMAA" in topeka.inv.curves
    assert "no PEF here" in r.text and "calcite 2.71 g/cc" in r.text and "matrix density 2.65" in r.text


@pytest.mark.data
def test_temperature_from_the_record_and_from_a_given_bht(topeka):
    r = schemas.call(topeka, "estimate", {"parameter": "temperature"})
    assert "fallback_geothermal_gradient" in r.text and "give bht_f (degF) and td" in r.text
    g = estimate_kw(topeka, "temperature", bht_f=150, td=4695.5)
    assert "gradient from BHT 150 F at TD 4695.5 ft (given; Petrophys estimate_gradient_from_bht)" in g.text


@pytest.mark.data
def test_rw_from_the_sp_needs_the_filtrate(topeka):
    with pytest.raises(ToolError, match="give rmf \\(ohm.m\\) and rmf_temp_f"):
        schemas.call(topeka, "estimate", {"parameter": "rw", "method": "sp"})
    r = estimate_kw(topeka, "rw", "sp", rmf=0.5, rmf_temp_f=75)
    assert "Petrophys sp_rw_in_window" in r.text and "SSP" in r.text and "(given)" in r.text


def estimate_kw(f, parameter, method=None, **kw):
    return L.estimate(f, parameter, method, **kw)


def test_the_estimates_listed():
    assert set(L.ESTIMATES) == {"rw", "archie_m", "clay_point", "gr_endpoints", "matrix", "temperature"}
    assert L.ESTIMATES["rw"] == ["rwa", "pickett", "sp"]
