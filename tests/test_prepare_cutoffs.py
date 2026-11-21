"""The net-pay cutoff checks of the interpretation (src/petroharness/well/prepare.py): a cutoff the library sets per
depth by lithology is recorded as text, and only cutoffs recorded as one number are compared with the policy's.

    .venv/bin/python -m pytest tests/test_prepare_cutoffs.py -q
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
from petroharness.well.prepare import _check_cutoffs, _check_engine_cutoffs

POLICY = {"vcl_max": 0.4, "sw_max": 0.6, "phie_min_clastic": 0.08, "phie_min_carbonate": 0.045}


def _result(params: dict):
    step = SimpleNamespace(step="net_pay", to_dict=lambda: {"parameters": params})
    return SimpleNamespace(base_result=SimpleNamespace(steps_executed=[step]))


def test_a_cutoff_set_per_depth_is_not_compared_as_a_number():
    _check_cutoffs(_result({"vcl_cutoff": 0.4, "sw_cutoff": 0.6, "phie_cutoff": "lithology_dependent"}), POLICY)
    _check_engine_cutoffs({"net_pay": {"parameters": {"phie_cutoff": "lithology_dependent", "sw_cutoff": 0.6}}}, POLICY)


def test_a_numeric_cutoff_unlike_the_policys_still_stops_the_run():
    with pytest.raises(RuntimeError, match="sw_cutoff"):
        _check_cutoffs(_result({"vcl_cutoff": 0.4, "sw_cutoff": 0.7, "phie_cutoff": 0.08}), POLICY)
    with pytest.raises(RuntimeError, match="vcl_cutoff"):
        _check_engine_cutoffs({"net_pay": {"parameters": {"vcl_cutoff": 0.5}}}, POLICY)


def test_a_carbonate_interpretation_is_checked_against_the_carbonate_cutoff():
    """Petrophys records the net-pay step's domain as `lithology`: a carbonate run used phie_cutoff 0.045, the
    policy's carbonate cutoff, and passes."""
    from petroharness.well.prepare import lithology_domain
    carbonate = {"lithology": "carbonate", "vcl_cutoff": 0.4, "sw_cutoff": 0.6, "phie_cutoff": 0.045}
    assert lithology_domain(carbonate) == "carbonate" and lithology_domain({}) == "clastic"
    assert lithology_domain({"lithology_domain": "carbonate"}) == "carbonate"
    _check_cutoffs(_result(carbonate), POLICY)
    _check_engine_cutoffs({"net_pay": {"parameters": carbonate}}, POLICY)
    with pytest.raises(RuntimeError, match="phie_cutoff"):
        _check_cutoffs(_result({**carbonate, "lithology": "clastic"}), POLICY)
