"""A policy can name a pinned interpretation engine (its workflow of record); the harness runs it on the raw LAS."""

import copy
import json

import numpy as np
import pytest

from petroharness.config import REPO_ROOT
from petroharness.well.prepare import _check_engine_cutoffs, engine_dir, load_policy, prepare_well

from _reference import CFG

V2 = REPO_ROOT / "src" / "petroharness" / "resources" / "policy" / "reference_v2.yaml"


def test_no_engine_means_the_installed_library(tmp_path):
    assert engine_dir({"name": "p"}, tmp_path) is None
    assert engine_dir({"name": "p", "engine": "installed"}, None) is None


def test_a_named_engine_must_exist_and_describe_itself(tmp_path):
    with pytest.raises(ValueError, match="no engines directory"):
        engine_dir({"engine": "e1"}, None)
    with pytest.raises(FileNotFoundError, match="'e1' not found"):
        engine_dir({"engine": "e1"}, tmp_path)
    (tmp_path / "e1").mkdir()
    (tmp_path / "e1" / "ENGINE.json").write_text(json.dumps({"name": "other"}))
    with pytest.raises(ValueError, match="does not describe engine 'e1'"):
        engine_dir({"engine": "e1"}, tmp_path)
    (tmp_path / "e1" / "ENGINE.json").write_text(json.dumps({"name": "e1"}))
    assert engine_dir({"engine": "e1"}, tmp_path) == tmp_path / "e1"


def test_an_engine_interprets_the_whole_well(tmp_path):
    (tmp_path / "e1").mkdir()
    (tmp_path / "e1" / "ENGINE.json").write_text(json.dumps({"name": "e1"}))
    policy = {"name": "p", "engine": "e1", "interpretation_scope": "formation"}
    with pytest.raises(ValueError, match="interprets the whole well"):
        prepare_well(tmp_path / "w.las", policy, None, None, tmp_path)


def test_policy_cutoffs_must_be_the_engines():
    steps = {"net_pay": {"parameters": {"lithology_domain": "carbonate", "vcl_cutoff": 0.3, "sw_cutoff": 0.7,
                                        "phie_cutoff": 0.045}}}
    cut = {"vcl_max": 0.3, "sw_max": 0.7, "phie_min_clastic": 0.08, "phie_min_carbonate": 0.045}
    _check_engine_cutoffs(steps, cut)                              # carbonate domain: the carbonate PHIE cutoff
    with pytest.raises(RuntimeError, match="sw_cutoff"):
        _check_engine_cutoffs(steps, cut | {"sw_max": 0.5})
    _check_engine_cutoffs({}, cut)                                 # no net-pay step: nothing to check


@pytest.mark.data
@pytest.mark.skipif(CFG.data.engines_dir is None, reason="needs a built engine (data.engines_dir)")
def test_engine_output_and_cache(tmp_path):
    """The engine's curves, step record and identity reach the prepared well; the cache returns the same well."""
    policy = load_policy(V2)
    las = CFG.data.las_dir / "15_9-2.las"
    prep = prepare_well(las, policy, None, tmp_path, CFG.data.engines_dir)
    assert prep.policy_adjustments["engine"]["name"] == policy["engine"]
    assert {"VCL", "PHIE", "SW", "PERM", "SWIRR_APP", "NET_PAY"} <= set(prep.derived_curves)
    assert prep.steps["permeability"]["method"] and prep.steps["net_pay"]["parameters"]["sw_cutoff"] == 0.7
    perm = prep.curve("PERM")
    ok = np.isfinite(perm)
    assert ok.any() and perm[ok].min() >= 1e-4 and perm[ok].max() <= 2e4    # the exporter's value-range QC
    again = prepare_well(las, policy, None, tmp_path, CFG.data.engines_dir)
    np.testing.assert_array_equal(again.curve("PERM"), perm)
    edited = copy.deepcopy(policy)
    edited["cutoffs"]["sw_max"] = 0.5                               # the engine's cutoffs are not inputs
    with pytest.raises(RuntimeError, match="sw_cutoff"):
        prepare_well(las, edited, None, tmp_path / "other", CFG.data.engines_dir)


def _well(**curves):
    from petrophys.model.well import Well

    w = Well("synthetic")
    w.depth = np.arange(len(next(iter(curves.values()))), dtype=float)
    w.depth_unit = "m"
    for name, data in curves.items():
        w.add_curve(name, np.asarray(data, dtype=float), "", name)
    return w


def test_value_qc_is_recorded_not_hidden():
    from petroharness.well.prepare import _apply_value_qc

    w = _well(PHIE=[0.2, 0.5, np.nan], SW=[1.2, 0.5, 0.3], GR=[50.0, 60.0, 70.0])
    qc = _apply_value_qc(w)
    assert set(qc["rules"]) == {"PHIE", "SW"}                                  # GR in range: nothing recorded
    np.testing.assert_array_equal(qc["changed"]["PHIE"], [False, True, False])
    assert np.isnan(w.get("PHIE").data[1]) and w.get("SW").data[0] == 1.0      # NaN-ed and clipped
    assert qc["rules"]["SW"]["action"] == "clip"


def test_engine_porosity_cutoff_is_checked_on_the_curves():
    from petroharness.well.prepare import _check_engine_cutoffs

    cut = {"vcl_max": 0.3, "sw_max": 0.7, "phie_min_clastic": 0.08, "phie_min_carbonate": 0.045}
    steps = {"net_pay": {"parameters": {"phie_cutoff": None, "lithology": "per-depth"},
                         "decisions": ["NET_RES:  + PHIE_CC > None -> 2 samples"]}}
    ok = _well(NET_ROCK=[1, 1, 1], NET_RES=[1, 1, 0], PHIE_CC=[0.2, 0.05, 0.03], PHIE=[0.0, 0.0, 0.0])
    _check_engine_cutoffs(steps, cut, ok)                     # 0.05 passes the carbonate cutoff; PHIE_CC is the one used
    leaky = _well(NET_ROCK=[1, 1], NET_RES=[1, 1], PHIE_CC=[0.2, 0.02])
    with pytest.raises(RuntimeError, match="1 reservoir samples at or below"):
        _check_engine_cutoffs(steps, cut, leaky)
    strict = _well(NET_ROCK=[1, 1], NET_RES=[1, 0], PHIE_CC=[0.2, 0.15])
    with pytest.raises(RuntimeError, match="1 net-rock samples above"):
        _check_engine_cutoffs(steps, cut, strict)


@pytest.mark.data
@pytest.mark.skipif(CFG.data.engines_dir is None, reason="needs a built engine (data.engines_dir)")
def test_engine_qc_record_reaches_the_prepared_well():
    prep = prepare_well(CFG.data.las_dir / "15_9-2.las", load_policy(V2), None, CFG.data.cache_dir, CFG.data.engines_dir)
    assert prep.value_qc and "PERM" in prep.value_qc["rules"]
    assert prep.value_qc["rules"]["PERM"]["low"] == 1e-4
    assert prep.value_qc["changed"]["PERM"].shape == prep.depth.shape
    assert np.isnan(prep.curve("PERM")[prep.value_qc["changed"]["PERM"]]).all()
