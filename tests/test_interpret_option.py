"""data.interpret: petrophys.interpret interprets the LAS (e.g. with a context profile), its step record (every
calculation, in order) is the well's, the analyzers run with the calculations the well was interpreted with, and a well
the interpretation reports in another depth unit is read in that unit.

petrophys.interpret is replaced by a stand-in here: these tests are about what the harness does with its result.
"""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import petrophys
from petroharness.well.calculations import calculations
from petroharness.well.view import _converted_depths
from petroharness.well.prepare import PreparedWell, _read, prepare_well

LAS = """~Version
VERS. 2.0 :
WRAP. NO :
~Well
STRT.{u} 1000.0 :
STOP.{u} 1002.0 :
STEP.{u} 0.5 :
NULL. -999.25 :
WELL. TESTWELL :
~Curve
DEPT.{u} : depth
GR.API : gamma ray
RHOB.G/C3 : bulk density
~A
1000.0 50 2.40
1000.5 60 2.42
1001.0 70 2.45
1001.5 80 2.50
1002.0 90 2.55
"""

STEPS = [   # name, to_dict fields: a profile's preparation, the workflow, the context's QC and recomputation
    ("preparation_input_reading", {"method": "input reading", "output_curves": ["GR"], "curves_removed": ["GR_RAW"],
                                   "decisions": ["GR_RAW renamed GR."],
                                   "parameters": {"calculation_steps": [{"step": "vclay", "parameters": {}}]}}),
    ("vclay", {"method": "linear GR", "input_curves": ["GR"], "output_curves": ["VCL"], "parameters": {"gr_min": 20}}),
    ("net_pay", {"method": "cutoffs", "parameters": {"vcl_cutoff": 0.4}, "output_curves": ["NET_PAY"],
                 "also_written": ["PRIME_OIL_TARGET"], "curves_removed": []}),
    ("context_value_range_qc", {"method": "context value-range rules", "output_curves": ["VCL"], "parameters": {
        "changes": [{"curve": "VCL", "low": 0.0, "high": 0.5, "action": "nan", "changed": 2, "below": 0, "above": 2},
                    {"curve": "GR", "low": 0.0, "high": 500.0, "action": "nan", "changed": 0, "below": 0, "above": 0}]}}),
]


def _step(name, **d):
    return SimpleNamespace(step=name, to_dict=lambda: {"step": name, **d})


@pytest.fixture
def las(tmp_path):
    path = tmp_path / "TESTWELL.las"
    path.write_text(LAS.format(u="M"))
    return path


@pytest.fixture
def interpret(monkeypatch):
    """A stand-in for petrophys.interpret: the LAS read, VCL added, a step record; the calls it got."""
    calls = []

    def fake(path, **options):
        calls.append((Path(path), options))
        well = _read(path)
        well.add_curve("VCL", np.array([0.1, 0.2, 0.3, np.nan, np.nan]), "v/v", "VCL")
        return SimpleNamespace(well=well, errors=calls[0][1].get("_errors", []), has_usable_interpretation=True,
                               status="interpreted", steps_executed=[_step(n, **d) for n, d in STEPS],
                               _context_run=SimpleNamespace(well=_read(path)))        # the workflow's own well

    monkeypatch.setattr(petrophys, "interpret", fake)
    return calls


def test_petrophys_interprets_with_the_options_and_its_well_is_the_well(las, interpret):
    prep = prepare_well(las, {"name": "p", "cutoffs": {"vcl_max": 0.4}}, interpret={"context_profile": "costa"})
    assert interpret == [(las, {"context_profile": "costa"})]
    assert prep.input_curves == ["GR", "RHOB"] and prep.derived_curves == ["VCL"]
    assert prep.context_profile == "costa"
    assert np.isfinite(prep.curve("VCL")).sum() == 3
    assert sorted(prep.workflow_well.curves) == ["GR", "RHOB"]                 # the workflow's own well


def test_with_no_engine_petrophys_interprets_with_the_library_settings_and_the_policys_cutoffs(las, interpret):
    """A policy naming no engine (or "installed"), and neither data.interpret nor data.interpreter: petrophys.interpret
    with the library's settings and the policy's net-pay cutoffs, the options `petroharness ask` gives it."""
    for policy in ({"name": "p", "cutoffs": {"vcl_max": 0.4}},
                   {"name": "p", "engine": "installed", "cutoffs": {"vcl_max": 0.4}}):
        prep = prepare_well(las, policy)
        assert interpret[-1] == (las, {"vcl_cutoff": 0.4})
        assert prep.policy_adjustments == {"interpret": {"vcl_cutoff": 0.4}} and prep.derived_curves == ["VCL"]


def test_default_options_are_the_policys_cutoffs_under_the_given_ones():
    from petroharness.well.prepare import default_interpret
    policy = {"cutoffs": {"vcl_max": 0.4, "sw_max": 0.6, "phie_min_clastic": 0.08}}
    assert default_interpret(policy) == {"vcl_cutoff": 0.4, "sw_cutoff": 0.6}
    assert default_interpret(policy, {"sw_cutoff": 0.5}) == {"vcl_cutoff": 0.4, "sw_cutoff": 0.5}
    assert default_interpret(policy, {"context_profile": "costa"}) == {"context_profile": "costa"}   # a profile's own
    assert default_interpret({}) == {}


def test_the_step_record_is_every_recorded_calculation_in_order(las, interpret):
    prep = prepare_well(las, {"name": "p"}, interpret={"context_profile": "costa"})
    assert list(prep.steps) == ["preparation_input_reading", "vclay", "net_pay", "context_value_range_qc"]
    assert prep.steps["vclay"] == {"method": "linear GR", "parameters": {"gr_min": 20}, "decisions": [],
                                   "inputs": ["GR"], "outputs": ["VCL"], "stage": "workflow"}
    assert [e["stage"] for e in prep.steps.values()] == ["preparation", "workflow", "workflow", "after"]
    assert prep.steps["preparation_input_reading"]["removed"] == ["GR_RAW"]        # curves a step removed
    assert prep.steps["preparation_input_reading"]["parameters"] == {"calculation_steps": ["vclay"]}   # names only
    assert prep.steps["net_pay"]["outputs"] == ["NET_PAY", "PRIME_OIL_TARGET"]    # also written: outputs too
    assert "removed" not in prep.steps["net_pay"]
    assert prep.value_qc["rules"] == {"VCL": {"low": 0.0, "high": 0.5, "action": "nan"}}     # the rules that changed
    assert "changed" not in prep.value_qc            # the workflow's well (stand-in) has no VCL: no per-sample record
    assert prep.steps["context_value_range_qc"]["decisions"] == [
        "VCL: 2 samples of the well outside 0.0 to 0.5 (0 below, 2 above) set to NaN"]     # one line per curve changed
    assert "changes" not in prep.steps["context_value_range_qc"]["parameters"]


def test_a_step_name_recorded_twice_keeps_both(las, interpret, monkeypatch):
    monkeypatch.setitem(globals(), "STEPS", STEPS + [("vclay", {"method": "again"})])
    prep = prepare_well(las, {"name": "p"}, interpret={"context_profile": "costa"})
    assert prep.steps["vclay"]["method"] == "linear GR" and prep.steps["vclay_2"]["method"] == "again"


def test_the_step_record_cutoffs_must_be_the_policy_cutoffs(las, interpret):
    with pytest.raises(RuntimeError, match="cutoffs"):
        prepare_well(las, {"name": "p", "cutoffs": {"vcl_max": 0.5}}, interpret={"context_profile": "costa"})


def test_interpret_and_interpreter_together_are_refused(las, interpret):
    with pytest.raises(ValueError, match="both data.interpreter and data.interpret"):
        prepare_well(las, {"name": "p"}, interpreter="m:f", interpret={})


def test_an_interpretation_with_errors_is_refused(las, interpret):
    with pytest.raises(RuntimeError, match="gave no interpretation"):
        prepare_well(las, {"name": "p"}, interpret={"_errors": ["no porosity input"]})


def test_a_setting_petrophys_does_not_have_is_named_and_refused(las):
    """The real petrophys.interpret: it refuses the unknown setting; the harness says which, as WHAT / FIX."""
    with pytest.raises(ValueError, match="WHAT: data.interpret names settings Petrophys does not have: bogus_option"):
        prepare_well(las, {"name": "p"}, interpret={"bogus_option": 1, "m": 2.0})


def test_the_cache_keeps_interpretations_with_other_options_apart(las, interpret, tmp_path):
    a = prepare_well(las, {"name": "p"}, cache_dir=tmp_path / "c", interpret={"context_profile": "costa"})
    b = prepare_well(las, {"name": "p"}, cache_dir=tmp_path / "c", interpret={"context_profile": "danish"})
    prepare_well(las, {"name": "p"}, cache_dir=tmp_path / "c", interpret={"context_profile": "costa"})
    assert len(interpret) == 2 and a.context_profile == "costa" and b.context_profile == "danish"


# --- the calculations the analyzers run with ----------------------------------------------------------------------

def test_the_analyzers_get_the_profile_calculations_only_for_a_profile_well():
    from petrophys._internal.benchmark import reproducing_benchmark
    with calculations(None):
        assert not reproducing_benchmark()
    for profile in ("geolink", "costa", "danish"):
        with calculations(profile):
            assert reproducing_benchmark()
        assert not reproducing_benchmark()                                   # restored after the block
    assert PreparedWell("w", "p", "full_well", None, [], [], {}, {}).context_profile is None


# --- a well reported in another depth unit ---------------------------------------------------------------------------

def test_depths_converted_by_the_interpretation_are_accepted_a_misread_unit_is_not(las):
    m = _read(las)
    converted = SimpleNamespace(depth=np.asarray(m.depth, float) / 0.3048)      # metres reported in feet
    assert _converted_depths(las, converted, "M", 0.3048)
    relabelled = SimpleNamespace(depth=np.asarray(m.depth, float))              # metres under the name of feet
    assert not _converted_depths(las, relabelled, "M", 0.3048)
    assert not _converted_depths(las, converted, "", 0.3048)                    # a LAS that states no unit


# --- a zone of a context-profile interpretation ----------------------------------------------------------------------

def test_a_zone_is_built_as_the_package_builds_a_group(las):
    """The workflow's samples, the interpretation's QC rules, the recomputation from the zone's own inputs."""
    from petroharness.well.view import FormationView
    nan = np.nan
    workflow = _read(las)                                                     # before the QC and recomputation
    workflow.add_curve("PHIE", np.array([nan, nan, 0.0, 0.2, 0.6]), "v/v", "PHIE")
    workflow.add_curve("PERM", np.array([nan, nan, 1.0, 10.0, 20.0]), "mD", "PERM")
    workflow.add_curve("RQI", np.array([0.5, 0.6, 0.7, 0.8, 0.9]), "um", "RQI")
    well = _read(las)                                                         # after: PHIE QC'd, RQI recomputed
    well.add_curve("PHIE", np.array([nan, nan, 0.0, 0.2, nan]), "v/v", "PHIE")
    well.add_curve("PERM", np.array([nan, nan, 1.0, 10.0, 20.0]), "mD", "PERM")
    well.add_curve("RQI", np.array([nan, nan, nan, 0.0314 * np.sqrt(50.0), nan]), "um", "RQI")
    well.add_curve("PHI_NORM", np.array([nan, nan, nan, 0.25, nan]), "v/v", "PHI_NORM")
    v = object.__new__(FormationView)
    v.prep = PreparedWell("w", "p", "full_well", well, ["GR", "RHOB"], ["PERM", "PHIE", "PHI_NORM", "RQI"], {}, {},
                          policy_adjustments={"interpret": {"context_profile": "geolink"}},
                          value_qc={"rules": {"PHIE": {"low": 0.0, "high": 0.45, "action": "nan"}}},
                          workflow_well=workflow)
    v.mask, v.depth_scale = np.ones(5, dtype=bool), 1.0
    without, shale, porous = (SimpleNamespace(indices=np.array(i)) for i in ([0, 1], [2], [3, 4]))
    z = v.zone_well(without)                                 # no porosity or permeability:
    assert "PHI_NORM" not in z.curves                        #   nothing recomputed or added,
    assert np.allclose(z.get("RQI").data, [0.5, 0.6])        #   the workflow's values kept
    z = v.zone_well(shale)                                   # inputs present, porosity 0: a curve with no value
    assert "PHI_NORM" in z.curves and np.isnan(z.get("PHI_NORM").data).all()
    z = v.zone_well(porous)                                  # the QC rule, then the recomputation
    assert np.isnan(z.get("PHIE").data[1]) and np.allclose(z.get("PHI_NORM").data[:1], [0.25])
    assert np.allclose(z.get("RQI").data[:1], [0.0314 * np.sqrt(50.0)]) and np.isnan(z.get("RQI").data[1])
    assert np.isfinite(workflow.get("PHIE").data).sum() == 3  # neither well is changed
    assert "PHI_NORM" in well.curves
    v.prep.workflow_well = None                              # any other interpretation: a part of the well
    assert np.isnan(v.zone_well(without).get("RQI").data).all()


def test_the_qc_record_says_which_samples_the_rules_changed(las, interpret, monkeypatch):
    """With the workflow's own well, the samples a rule changed are where its value and the interpreted value differ."""
    def workflow(path):
        w = _read(path)
        w.add_curve("VCL", np.array([0.1, 0.2, 0.3, 0.7, 0.9]), "v/v", "VCL")      # before the QC: two above 0.5
        return w
    real = petrophys.interpret
    monkeypatch.setattr(petrophys, "interpret", lambda path, **o: SimpleNamespace(
        **{**vars(real(path, **o)), "_context_run": SimpleNamespace(well=workflow(path))}))
    prep = prepare_well(las, {"name": "p"}, interpret={"context_profile": "costa"})
    assert prep.value_qc["changed"]["VCL"].tolist() == [False, False, False, True, True]


# --- stages: which step made a curve, and the compact compartments of the map ----------------------------------------

def test_a_curve_is_made_by_its_workflow_step_not_by_a_preparation_or_the_qc():
    from petroharness.record.card import producer
    steps = {"preparation_input_reading": {"outputs": ["RHOB"], "stage": "preparation"},
             "porosity": {"outputs": ["PHIE"], "inputs": ["RHOB"], "stage": "workflow"},
             "context_value_range_qc": {"outputs": ["PHIE", "RHOB"], "stage": "after"},
             "context_dependent_curve_recompute": {"outputs": ["PHI_NORM"], "inputs": ["PHIE"], "stage": "after"}}
    assert producer(steps, "PHIE") == ("porosity", ["RHOB"])              # the QC that screened it did not make it
    assert producer(steps, "PHI_NORM") == ("context_dependent_curve_recompute", ["PHIE"])   # only it made it
    assert producer({"a": {"outputs": ["X"]}, "b": {"outputs": ["X"]}}, "X")[0] == "b"     # no stages: the last step that writes it


def test_the_qc_compartment_line_counts_this_interval():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from petroharness.agent.map import _compact
    qc = {"PHIT": {"rule": {"low": 0.0, "high": 0.45, "action": "nan"}, "changed": 2},
          "NPHI": {"rule": {"low": -0.15, "high": 0.6, "action": "nan"}, "changed": 0},
          "PERM": {"rule": {"low": 0.0001, "high": 20000, "action": "nan"}, "changed": None}}
    m = SimpleNamespace(step="context_value_range_qc", method="context value-range rules", outputs=["NPHI", "PHIT", "PERM"])
    line, = _compact([m], {}, None, SimpleNamespace(value_qc=qc))
    assert line == ("    step context_value_range_qc: method context value-range rules; in this interval PHIT 2 set to "
                    "NaN outside 0 to 0.45")                                 # unknown counts (PERM) are not claimed
    qc["PHIT"]["changed"] = 0
    line, = _compact([m], {}, None, SimpleNamespace(value_qc=qc))
    assert line.endswith("; in this interval no sample changed")
