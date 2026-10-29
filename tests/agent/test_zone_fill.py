"""The analyzers' derived curves (petroharness.well.derived) and how the formation view reads them: a curve the well lacks
is a new curve; a well curve with no value in a whole zone reads the analyzer's values there; the interpreted values
always win and the interpreted well is never changed.

    .venv/bin/python -m pytest tests/agent/test_zone_fill.py -q          (+ -m data: real data)
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2])]

from petroharness.well.derived import DerivedCurves, filled  # noqa: E402
from petroharness.well.view import FormationView  # noqa: E402

NAN = np.nan


def _curve(data, unit=""):
    return SimpleNamespace(data=np.asarray(data, dtype=float), unit=unit)


def _well(**curves):
    return SimpleNamespace(get=lambda name: _curve(curves[name]) if name in curves else None)


def _view(prep_curves: dict, fills: dict, mask) -> FormationView:
    v = object.__new__(FormationView)                       # only what values() reads
    v.prep = SimpleNamespace(curve=lambda c: prep_curves.get(c))
    v.analyzer_curves, v.analyzer_fills, v.mask = {}, fills, np.asarray(mask, dtype=bool)
    return v


# DerivedCurves.add: which derived curves are kept, and how

def test_a_curve_the_well_lacks_is_a_new_curve_over_the_zone_samples():
    d = DerivedCurves(6)
    d.add(_well(), np.array([1, 2]), {"CLAY_INDEX": _curve([0.3, 0.4], "v/v")})
    values, unit = d.new["CLAY_INDEX"]
    assert np.array_equal(values, [NAN, 0.3, 0.4, NAN, NAN, NAN], equal_nan=True) and unit == "v/v"
    assert d.fills == {}


def test_a_well_curve_empty_in_the_zone_is_filled_there():
    well = _well(MHI=[0.5, NAN, NAN, 0.7])
    d = DerivedCurves(4)
    d.add(well, np.array([1, 2]), {"MHI": _curve([0.6, 0.65])})
    assert np.array_equal(d.fills["MHI"], [NAN, 0.6, 0.65, NAN], equal_nan=True)
    assert d.new == {}


def test_a_zone_with_any_interpreted_value_keeps_the_interpretation():
    well = _well(MHI=[0.5, NAN, 0.7, NAN])
    d = DerivedCurves(4)
    d.add(well, np.array([1, 2]), {"MHI": _curve([0.6, 0.65])})   # one interpreted value in the zone: no fill
    assert d.fills == {} and d.new == {}


def test_a_derived_curve_without_a_finite_value_is_not_a_curve():
    d = DerivedCurves(3)
    d.add(_well(MHI=[NAN] * 3), np.array([0, 1]), {"MHI": _curve([NAN, NAN]), "X": _curve([NAN, NAN])})
    d.add(_well(), np.array([0]), {"Y": SimpleNamespace(data=["not a number"], unit="")})
    assert d.fills == {} and d.new == {}


def test_zones_fill_their_own_samples_only():
    well = _well(MHI=[NAN, NAN, 0.4, NAN, NAN])
    d = DerivedCurves(5)
    d.add(well, np.array([0, 1]), {"MHI": _curve([0.1, 0.2])})
    d.add(well, np.array([2]), {"MHI": _curve([0.9])})          # this zone has its value: kept
    d.add(well, np.array([3, 4]), {"MHI": _curve([0.3, 0.35])})
    assert np.array_equal(d.fills["MHI"], [0.1, 0.2, NAN, 0.3, 0.35], equal_nan=True)


# filled and FormationView.values: how the view reads the fills

def test_filled_takes_the_fill_only_where_the_curve_has_no_value():
    data, fill = np.array([0.2, NAN, NAN, 0.4]), np.array([9.0, 0.5, NAN, 9.0])
    assert np.array_equal(filled(data, fill), [0.2, 0.5, NAN, 0.4], equal_nan=True)
    assert np.isnan(data[1])                                # the inputs are not changed


def test_values_read_the_fill_and_own_values_leave_it_out():
    own = np.array([0.2, NAN, 0.4])
    v = _view({"MHI": own}, {"MHI": np.array([NAN, 0.5, NAN])}, [True] * 3)
    assert np.array_equal(v.values("MHI"), [0.2, 0.5, 0.4])
    assert np.array_equal(v.own_values("MHI"), own, equal_nan=True)


def test_the_fill_is_read_over_the_interval_mask():
    own = np.array([NAN, NAN, 0.3, NAN])
    v = _view({"MHI": own}, {"MHI": np.array([0.1, 0.2, NAN, 0.4])}, [False, True, True, False])
    assert np.array_equal(v.values("MHI"), [0.2, 0.3])


def test_no_fill_reads_the_interpreted_curve_as_before():
    own = np.array([0.1, NAN, 0.3])
    v = _view({"SW": own}, {}, [True, True, False])
    assert np.array_equal(v.values("SW"), own[:2], equal_nan=True)


# real data: a formation where the interpretation left a well curve empty in a zone

@pytest.mark.data
def test_a_zone_the_workflow_left_empty_reads_the_analyzers_values():
    from petroharness.config import HarnessConfig
    from petroharness.tasks import load_tasks
    from petroharness.record.catalog import zone_results
    from petroharness.record.store import build as build_store
    cfg = HarnessConfig()
    tasks, _ = load_tasks(cfg.eval.questions, cfg.data.las_dir)
    task = next((t for t in tasks if t.well == "34_10-35" and t.formation.startswith("STATFJORD")), None)
    if task is None:
        pytest.skip("the formation this test reads is not in the configured data")
    view = FormationView.build(task, cfg.for_tasks())
    workflow = np.asarray(view.prep.curve("MHI"), dtype=float)[view.mask]
    empty = [z for z in view.zones if not np.isfinite(workflow[z.indices]).any()]
    assert empty                                             # the case this test is about
    store = build_store(view)
    assert "MHI" not in store.derived                        # a well curve: filled, not a new curve
    derived = {z.zone_id: r.derived_curves.get("MHI") for z, r in zone_results(view, "saturation")}
    for z in view.zones:
        got = view.zone_values(z, "MHI")
        own = workflow[z.indices]
        if np.isfinite(own).any():                           # interpreted: unchanged
            assert np.array_equal(got, own, equal_nan=True)
        elif derived.get(z.zone_id) is not None:              # empty: the saturation analyzer's own values
            assert np.array_equal(got, np.asarray(derived[z.zone_id].data, dtype=float), equal_nan=True)
    assert np.isfinite(view.prep.curve("MHI")[view.mask]).sum() == np.isfinite(workflow).sum()   # the well unchanged
