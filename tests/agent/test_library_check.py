"""The check verb (src/petroharness/agent/library_check.py): held readings, the parts of bad hole
and the core-to-log depth shift, each from Petrophys, the flags written as curves of the question; on the sample wells
(data) and on a benchmark well that carries core plugs (data, $WELLLOGBENCH).

    .venv/bin/python -m pytest tests/agent/test_library_check.py -q
"""
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).resolve().parent)]
from test_library_tools import SAMPLES, _session

from petroharness.agent import schemas
from petroharness.agent.engine import ToolError
from petroharness.agent.library_check import OBJECTS, check


def test_the_checks_and_what_they_take():
    assert set(OBJECTS) == {"held_readings", "bad_hole", "depth_shift"}
    with pytest.raises(ToolError, match="no check 'spikes'; checks: held_readings"):
        check(None, "spikes")
    with pytest.raises(ToolError, match="threshold must be a number"):
        check(None, "bad_hole", threshold="high")


@pytest.fixture(scope="module")
def tuhua():
    las = SAMPLES / "tuhua-7.las"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    return _session(las, SAMPLES / "formations_tuhua-7.csv", "Mount Messenger")


@pytest.fixture(scope="module")
def topeka():
    las = SAMPLES / "1046123714.las"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    return _session(las, SAMPLES / "1046123714_formation_tops.csv", "Topeka")


@pytest.mark.data
def test_bad_hole_by_its_parts_as_flags(tuhua):
    r = check(tuhua, "bad_hole")
    assert "Petrophys WashoutDetection" in r.text and "WellboreQC" in r.text
    m = re.search(r"WASHOUT: ([\d.]+)% of the interval .*?; (\d+) runs?, .*?by zone: (.*?); written: WASHOUT", r.text)
    assert m and float(m.group(1)) > 0 and int(m.group(2)) > 0 and "Z" in m.group(3)
    assert "WASHOUT" in tuhua.inv.curves and "RUGOSE" in tuhua.inv.curves
    flag = tuhua.view.values("WASHOUT")
    assert set(np.unique(flag[np.isfinite(flag)])) <= {0.0, 1.0}
    assert abs(100 * flag.mean() - float(m.group(1))) < 0.06                   # the share shown is the flag's
    runs = schemas.call(tuhua, "runs", {"condition": "WASHOUT == 1"})             # a curve of the question
    assert "WASHOUT" in runs.text and "run" in runs.text
    assert "the record's BAD_HOLE" in r.text and r.numbers and all(np.isfinite(r.numbers))


@pytest.mark.data
def test_bad_hole_without_a_bit_size_says_washout_is_not_evaluated(topeka):
    r = check(topeka, "bad_hole")
    assert "no bit size (BS) in the well: washout is not evaluated" in r.text and "WASHOUT: none here" in r.text


@pytest.mark.data
def test_held_readings_flag_a_held_log_and_pass_the_others(tuhua):
    r = check(tuhua, "held_readings", curves=["TEMP", "GR"])
    assert "Petrophys find_held_readings" in r.text and "none held: GR" in r.text
    assert re.search(r"TEMP: [\d.]+% of its samples here held; \d+ runs?, .* written: HELD_TEMP", r.text)
    held = tuhua.view.values("HELD_TEMP")
    assert np.nansum(held) > 0
    default = check(tuhua, "held_readings")                                      # every measured log, none of them flat
    assert "BS" not in default.text.split("\n")[0]


@pytest.mark.data
def test_no_core_no_depth_shift(topeka):
    with pytest.raises(ToolError, match="no core plugs in this interval's LAS"):
        check(topeka, "depth_shift")


def _cored_session():
    """A benchmark well whose LAS carries core porosity (the first, by name, of the data config's LAS folder)."""
    import petroharness.ask as A
    from petroharness.agent.loop import Session
    from petroharness.config import (
        DataPaths,
        HarnessConfig,
        ResourcePaths,
        given_settings,
    )
    from petroharness.tasks import Task
    data_dir = os.environ.get("WELLLOGBENCH")
    cfg = Path(data_dir) / "geolink.yaml" if data_dir else None
    if not cfg or not cfg.exists():
        pytest.skip("WELLLOGBENCH is not set (the folder of the datasets' data configs)")
    las_dir = Path(yaml.safe_load(cfg.read_text())["data"]["las_dir"])
    cored = [p for p in sorted(las_dir.glob("*.las"))
             if re.search(r"^\s*PHIC[ .]", p.read_text(errors="ignore")[:20000], re.MULTILINE)]
    if not cored:
        pytest.skip("no LAS with core porosity in the data config's folder")
    las = cored[0]
    data, _ = A._settings(las, cfg, None, None, Path(tempfile.mkdtemp()), ResourcePaths().policy_file)
    span = A._interval(las, None, None, None, None, None, data)
    data.setdefault("depth_unit", "las")
    task = Task(task_id="a" + hashlib.sha256(str(las).encode()).hexdigest()[:10], question="q", well=las.stem,
                formation=span["name"], las_path=las, top=span["top"], base=span["base"], depth_unit=None,
                base_closed=span["closed"], formation_lithology=None)
    with given_settings({"data": data, "eval": {}}):
        return Session.build(task, HarnessConfig(data=DataPaths(**data), eval=None)).f


@pytest.mark.data
def test_the_core_to_log_depth_shift():
    f = _cored_session()
    r = check(f, "depth_shift")
    m = re.search(r"core porosity from the LAS, (\d+) plugs here, against PHIE;.*best shift (-?[\d.]+) \w+ .*r "
                  r"(-?[\d.]+) against (-?[\d.]+) unshifted", r.text)
    assert m and int(m.group(1)) >= 10 and float(m.group(3)) >= float(m.group(4))       # the best tie is no worse
    p = check(f, "depth_shift", curves=["PERM"], threshold=1)
    assert "core permeability" in p.text and "on log10" in p.text
    if "PHIE_CC" in f.inv.curves:
        cc = check(f, "depth_shift", curves=["PHIE_CC"])
        assert "PHIE_CC is calibrated to core: a tie against the same core is not independent" in cc.text
