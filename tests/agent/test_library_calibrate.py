"""calibrate (src/petroharness/agent/library/calibrate.py): Petrophys's calibration fits of the log to core, the
poro-perm transform, the shear prediction and the elastic properties, on a sample well and, where the benchmark data
is present, on wells whose LAS carries core plugs or a measured shear sonic.

    .venv/bin/python -m pytest tests/agent/test_library.calibrate.py -q
"""
import hashlib
import math
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).resolve().parent)]
from test_library_tools import SAMPLES, _session

from petroharness.agent.library import calibrate as K
from petroharness.agent.engine import ToolError

DATA = Path(os.environ["WELLLOGBENCH"]) if os.environ.get("WELLLOGBENCH") else None   # the datasets' data configs


def test_the_objects_and_an_unknown_one():
    assert set(K.OBJECTS) == {"porosity", "permeability", "saturation", "poro_perm", "shear", "elastic"}
    for w in ("porosity", "permeability", "saturation"):
        assert "core_vs_log gives the statistics side by side" in K.OBJECTS[w]      # the fit, not the plain statistics
    with pytest.raises(ToolError, match="no calibration of 'magic'; calibrate: porosity"):
        K.calibrate(None, "magic")


def test_one_log_curve_at_a_time():
    assert K._one(None) is None and K._one("phie_cc") == "PHIE_CC" and K._one(["PHIT"]) == "PHIT"
    with pytest.raises(ToolError, match="one log curve, not 2"):
        K._one(["PHIE", "PHIT"])


# --- on a sample well without core (data) ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def topeka():
    las, tops = SAMPLES / "1046123714.las", SAMPLES / "1046123714_formation_tops.csv"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    return _session(las, tops, "Topeka")


@pytest.mark.data
def test_a_core_fit_without_core_names_the_plugs_it_needs(topeka):
    with pytest.raises(ToolError, match="no PHIC or CPOR core plugs with PHIE values"):
        K.calibrate(topeka, "porosity")
    with pytest.raises(ToolError, match="KH_CORE or CPERM"):
        K.calibrate(topeka, "permeability")


@pytest.mark.data
def test_poro_perm_on_the_log_says_so(topeka):
    r = K.calibrate(topeka, "poro_perm")
    assert "fitted on the log (PHIE and PERM: no core porosity and permeability here)" in r.text
    assert "log10(K) = A * porosity + B with A" in r.text and "PERM_PP" in topeka.inv.curves


@pytest.mark.data
def test_shear_then_elastic_on_the_predicted_shear(topeka):
    s = K.calibrate(topeka, "shear")
    assert re.search(r"vs_from_vp_greenberg_castagna, lithology (each lithology of these samples \(|\w+ \(the record's "
                     r"lithology|\S+ \(Petrophys's default)", s.text), s.text[:300]     # the binder's one rule (D3)
    assert "no measured DTS here" in s.text and "DTS_GC" in topeka.inv.curves
    e = K.calibrate(topeka, "elastic")
    assert "and DTS_GC (predicted in this question)" in e.text
    for name in ("VP", "AI", "VS", "POISSON", "SHEAR_MOD", "BULK_MOD"):
        assert name in topeka.inv.curves and topeka.view.available(name)
    assert "Vp/Vs:" in e.text and e.numbers


# --- on wells whose LAS carries core plugs or a shear sonic (benchmark data) ----------------------------------------

def _benchmark_session(well: str, formation: str):
    import yaml

    import petroharness.ask as A
    from petroharness.agent.state import Session
    from petroharness.config import (
        DataPaths,
        HarnessConfig,
        ResourcePaths,
        given_settings,
    )
    from petroharness.tasks import Task
    cfg = DATA / "geolink.yaml" if DATA else None
    if cfg is None or not cfg.exists():
        pytest.skip("WELLLOGBENCH is not set (the folder of the datasets' data configs)")
    las = Path(yaml.safe_load(cfg.read_text())["data"]["las_dir"]) / f"{well}.las"
    if not las.exists():
        pytest.skip(f"no {las.name} in the data config's LAS folder")
    data, _ = A._settings(las, cfg, None, None, Path(tempfile.mkdtemp()), ResourcePaths().policy_file)
    span = A._interval(las, formation, None, None, None, None, data)
    task = Task(task_id="a" + hashlib.sha256(f"{las}{formation}".encode()).hexdigest()[:10], question="q",
                well=las.stem, formation=span["name"], las_path=las, top=span["top"], base=span["base"],
                depth_unit=None, base_closed=span["closed"], formation_lithology=None)
    with given_settings({"data": data, "eval": {}}):
        return Session.build(task, HarnessConfig(data=DataPaths(**data), eval=None)).f


@pytest.fixture(scope="module")
def cored():
    return _benchmark_session("15_9-13", "Tor Fm. Top")


@pytest.mark.data
@pytest.mark.parametrize("what, core, space", [("porosity", "PHIC", ""), ("permeability", "KH_CORE", " in log10"),
                                               ("saturation", "SWC", "")])
def test_the_fit_of_the_log_to_core(cored, what, core, space):
    r = K.calibrate(cored, what)
    assert f"against core {core}{space} (Petrophys calibrate_{what}" in r.text
    assert "plugs, R2 " in r.text and "bias " in r.text and "RMSE " in r.text and "line: log = " in r.text
    assert "zones pooled" not in r.text                                 # one zone: its line alone
    assert all(math.isfinite(x) for x in r.numbers)


@pytest.mark.data
def test_poro_perm_on_core(cored):
    r = K.calibrate(cored, "poro_perm")
    assert "fitted on core plugs (Petrophys fit_poro_perm_transform)" in r.text and "against the record's PERM" in r.text


@pytest.mark.data
def test_predicted_shear_against_a_measured_one():
    g = _benchmark_session("15_9-23", "Tor Fm. Top")
    r = K.calibrate(g, "shear")
    assert "against the measured DTS: zones pooled: n " in r.text and "mean difference" in r.text
    e = K.calibrate(g, "elastic")
    assert "and the measured DTS" in e.text and "POISSON" in g.inv.curves
