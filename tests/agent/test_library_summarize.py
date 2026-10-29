"""summarize (src/petroharness/agent/library_summarize.py): net pay and HCPT per zone with the cutoffs the model
gives, by Petrophys summarize_pay; on a sample well (data).

    .venv/bin/python -m pytest tests/agent/test_library_summarize.py -q
"""
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).resolve().parent)]
from petroharness.agent import schemas
from petroharness.agent.engine import ToolError
from petroharness.agent.library_summarize import OBJECTS, summarize

SAMPLES = Path(os.environ.get("PETROHARNESS_SAMPLE_LAS", "sample_las"))   # a folder of sample wells; tests skip without it


def test_only_what_pay_summary_lacks():
    assert set(OBJECTS) == {"pay"} and "pay_summary gives the record's own flags" in OBJECTS["pay"]
    with pytest.raises(ToolError, match="summarize has no 'zones'"):
        summarize(None, "zones")


@pytest.fixture(scope="module")
def teapot():
    from test_library_tools import _session
    las = SAMPLES / "teapot_17-wx-21.las"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    return _session(las)


def _pay(text: str, label: str) -> float:
    return float(re.search(re.escape(label) + r"[^\n]*?net pay ([\d.]+)", text).group(1))


@pytest.mark.data
def test_the_records_cutoffs_by_default(teapot):
    r = summarize(teapot)
    assert "VCL < 0.3 (record), PHIE > 0.08 (record), SW < 0.7 (record)" in r.text
    assert "zones pooled:" in r.text and "whole interval (11300 samples)" in r.text and "HCPT" in r.text
    assert "written:" not in r.text                                       # nothing asked: no flags written
    assert r.numbers and all(np.isfinite(x) for x in r.numbers)


@pytest.mark.data
def test_a_looser_sw_cutoff_never_shrinks_pay(teapot):
    base = summarize(teapot)
    loose = summarize(teapot, sw_cutoff=0.9)
    assert "SW < 0.9 (asked)" in loose.text
    assert _pay(loose.text, "whole interval") >= _pay(base.text, "whole interval")
    assert "NET_PAY_SW0_9" in teapot.inv.curves
    runs = schemas.call(teapot, "runs", {"condition": "NET_PAY_SW0_9 == 1", "limit": 2})
    assert "NET_PAY_SW0_9" in runs.text


@pytest.mark.data
def test_zones_asked_and_bad_cutoffs(teapot):
    r = summarize(teapot, zones=["Z9", "Z10"])
    assert "Z9 " in r.text and "zones pooled (Z9, Z10)" in r.text and "whole interval" not in r.text
    with pytest.raises(ToolError, match="fraction between 0 and 1"):
        summarize(teapot, sw_cutoff=70)
