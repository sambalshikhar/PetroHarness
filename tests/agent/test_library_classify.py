"""classify (src/petroharness/agent/library_classify.py): what the rock or its fluid is, by Petrophys, written as
curves of the question: gas effect, mineral volumes, flow units, electrofacies, moveable hydrocarbons; on sample wells
(data).

    .venv/bin/python -m pytest tests/agent/test_library_classify.py -q
"""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).resolve().parent)]
from petroharness.agent import schemas
from petroharness.agent.engine import Out, ToolError
from petroharness.agent.library_classify import MANY, OBJECTS, _per_zone, classify

SAMPLES = Path(os.environ.get("PETROHARNESS_SAMPLE_LAS", "sample_las"))   # a folder of sample wells; tests skip without it


def test_the_objects_say_what_they_need():
    assert set(OBJECTS) == {"gas", "minerals", "flow_units", "electrofacies", "moveable_hydrocarbons"}
    assert "unit_roles" in OBJECTS["flow_units"] and "MHI" in OBJECTS["moveable_hydrocarbons"]


def test_long_zone_lists_keep_what_matters():
    row = Out.__new__(Out)
    row._pending = []
    few = _per_zone(row, [("Z1", 0.1), ("Z2", float("nan")), ("Z3", 0.3)])
    assert few == "Z1 0.1; Z3 0.3"
    many = [(f"Z{i}", 0.0) for i in range(1, 30)] + [("Z30", 5.0), ("Z31", 2.0)]
    text = _per_zone(row, many, pct=True, keep_zero=False)
    assert text.startswith("Z30 5.0%; Z31 2.0%") and "(29 other zones at 0)" in text
    ranked = _per_zone(row, [(f"Z{i}", float(i)) for i in range(1, 20)])
    assert ranked.startswith("Z19 19") and f"({19 - MANY} other zones lower)" in ranked


@pytest.fixture(scope="module")
def tuhua():
    from test_library_tools import _session
    las = SAMPLES / "tuhua-7.las"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    return _session(las, SAMPLES / "formations_tuhua-7.csv", "Mount Messenger")


@pytest.fixture(scope="module")
def teapot():
    from test_library_tools import _session
    las = SAMPLES / "teapot_17-wx-21.las"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    return _session(las)


@pytest.mark.data
def test_gas_writes_a_flag_runs_reads(teapot):
    r = classify(teapot, "gas")
    assert "Petrophys detect_gas_effect: PHID > PHIN + 0.05" in r.text and "GAS_FLAG" in teapot.inv.curves
    assert "other zones at 0" in r.text                                   # 124 zones: only the flagged ones listed
    runs = schemas.call(teapot, "runs", {"condition": "GAS_FLAG == 1", "limit": 3})
    assert "Runs where GAS_FLAG == 1" in runs.text


@pytest.mark.data
@pytest.mark.parametrize("method, written", [(None, ["V_QUARTZ", "V_CALCITE", "MM_POOR_FIT"]),
                                             ("calcite_dolomite", ["V_CALCITE", "V_DOLOMITE"])])
def test_minerals_by_either_solver(tuhua, method, written):
    r = classify(tuhua, "minerals", method)
    assert all(w in r.text.split("written:")[1] for w in written)
    v = tuhua.view.values(written[1])
    assert np.nanmin(v) >= 0 and np.nanmax(v) <= 1                       # bulk volumes
    with pytest.raises(ToolError, match="solver or calcite_dolomite"):
        classify(tuhua, "minerals", "magic")


@pytest.mark.data
def test_flow_units_from_fzi(tuhua):
    r = classify(tuhua, "flow_units", k=3)
    assert "3 units over" in r.text and "k 3 asked" in r.text and "FZI boundaries between units" in r.text
    fu = tuhua.view.values("FLOW_UNIT")
    assert set(np.unique(fu[np.isfinite(fu)])) == {1.0, 2.0, 3.0}
    s = schemas.call(tuhua, "stats", {"curves": ["PHIE"], "where": "FLOW_UNIT == 3"})
    assert "PHIE" in s.text
    with pytest.raises(ToolError, match="1 to 6"):
        classify(tuhua, "flow_units", k=12)


@pytest.mark.data
def test_electrofacies_are_classes_from_one(tuhua):
    r = classify(tuhua, "electrofacies", k=4)
    assert "the library fixes the curves and the class count" in r.text
    ef = tuhua.view.values("EFACIES")
    assert np.nanmin(ef) == 1


@pytest.mark.data
def test_moveable_hydrocarbons_need_a_flushed_zone_log(tuhua, teapot):
    with pytest.raises(ToolError, match="SXO is fifth_root_quicklook"):
        classify(tuhua, "moveable_hydrocarbons")
    r = classify(teapot, "moveable_hydrocarbons")
    assert "SXO by archie_rxo_rmf" in r.text and {"MOS", "SOR"} <= set(teapot.inv.curves)
    mos, sxo, sw = (teapot.view.values(c) for c in ("MOS", "SXO", "SW"))
    ok = np.isfinite(mos)
    assert np.allclose(mos[ok], np.maximum(sxo[ok] - sw[ok], 0))


def test_an_unknown_object_lists_them():
    with pytest.raises(ToolError, match="classify has no 'rocks'; it gives: gas"):
        classify(None, "rocks")
