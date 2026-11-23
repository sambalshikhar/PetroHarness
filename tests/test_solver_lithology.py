"""Lithology zones from Petrophys's mineral solver (petroharness.well.formation.solver_lithology, the view and the well
plot): a well with no lithology log is zoned by the lithology code curve Petrophys's lithology step wrote, read with
the labels Petrophys keeps on it, and the page says how; a lithology log in the LAS still comes first, and the solved
curve is never called a log."""
from types import SimpleNamespace

import numpy as np

from petroharness.ui import wellplot as W
from petroharness.well.formation import MISSING_LITHOLOGY, solver_lithology


def _curve(data, labels=None):
    return SimpleNamespace(data=np.asarray(data, dtype=float), metadata=SimpleNamespace(custom={"category_labels": labels} if labels else {}))


LABELS = {1: "sandstone", 2: "limestone", 4: "shale", 0: "unknown"}


def _well(**curves):
    return SimpleNamespace(get=lambda name: curves.get(name))


def _steps(written=True, outputs=("VQUAR", "VCALC", "LITHO"), **params):
    return {"lithology": {"method": "canonical_multi_mineral_solver", "inputs": ["RHOB", "NPHI", "VCL"],
                          "outputs": list(outputs), "decisions": ["No lithology curve ... -> inferred LITHO from mineral volumes"],
                          "parameters": {"lithology_curve_written": written, "multi_mineral_solved_samples": 9,
                                         "multi_mineral_total_samples": 10, **params}},
            "net_pay": {"parameters": {"lithology": "carbonate"}}}


def test_the_solved_lithology_and_how_it_was_made():
    well = _well(VQUAR=_curve([0.5] * 3), LITHO=_curve([1, 4, 0], LABELS))
    got = solver_lithology(_steps(lithology_domain="clastic"), well)
    assert got["curve"] == "LITHO" and got["domain"] == "clastic" and got["method"] == "canonical_multi_mineral_solver"
    assert got["table"] == {1: "SANDSTONE", 2: "LIMESTONE", 4: "SHALE", 0: MISSING_LITHOLOGY}    # unknown: no lithology
    assert got["inputs"] == ["RHOB", "NPHI", "VCL"] and got["solved"] == 9 and got["samples"] == 10 and got["decisions"]


def test_the_domain_from_the_net_pay_step_when_the_lithology_step_does_not_record_it():
    well = _well(LITHO=_curve([2, 2], LABELS))
    assert solver_lithology(_steps(), well)["domain"] == "carbonate"


def test_no_solved_lithology():
    labelled = _well(LITHO=_curve([1, 4], LABELS))
    assert solver_lithology(_steps(written=False), labelled) is None          # the step kept an input lithology
    assert solver_lithology({}, labelled) is None                              # no lithology step
    assert solver_lithology(_steps(), _well(LITHO=_curve([1, 4]))) is None     # a code curve without labels
    assert solver_lithology(_steps(), _well(LITHO=_curve([np.nan, np.nan], LABELS))) is None   # no value


def _view(**kw):
    base = dict(prep=SimpleNamespace(policy_adjustments={"interpret": {"vcl_cutoff": 0.3}},
                                     steps={"vclay": {"method": "linear", "stage": "workflow"},
                                            "lithology": {"stage": "workflow"}, "context_x": {"stage": "after"}}),
                lithology_curve=None, solver_curve=None, solver_record={}, vcl_bands=None, code_table={},
                policy={"zones": {"min_thickness_m": 1.0}}, m_per_unit=0.3048, zone_layout="lithology_runs",
                user_zones=[], zones_source=None)
    return SimpleNamespace(**{**base, **kw})


def test_the_page_says_how_the_lithology_zones_were_made():
    solved = W.made(_view(solver_curve="LITHO", solver_record={"curve": "LITHO", "domain": "clastic"}))
    assert solved["run"] == {"kind": "dynamic workflow"} and solved["steps"] == ["vclay", "lithology"]
    assert solved["lithology"] == {"source": "mineral solver", "curve": "LITHO", "domain": "clastic"}
    assert solved["zone_rule"]["min_thickness"] == round(1.0 / 0.3048, 4)          # in the reporting unit (ft here)
    logged = W.made(_view(lithology_curve="LITHOLOGY_GEOLINK", code_table={1: "SAND", 2: "SHALE"}))
    assert logged["lithology"] == {"source": "lithology log", "curve": "LITHOLOGY_GEOLINK", "codes": 2}
    banded = W.made(_view(vcl_bands=(0.3, 0.6)))
    assert banded["lithology"] == {"source": "shale-volume bands", "bands": [0.3, 0.6], "method": "linear"}
    profile = W.made(_view(prep=SimpleNamespace(policy_adjustments={"interpret": {"context_profile": "costa"}}, steps={})))
    assert profile["run"] == {"kind": "context profile", "name": "costa"} and profile["lithology"] == {"source": "none"}
