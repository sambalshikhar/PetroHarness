"""An interval given in feet on a log in metres (or the other way) holds the samples it names: a limit that lands on a
sample after the unit conversion keeps that sample, a hair of float error aside.

    .venv/bin/python -m pytest tests/test_interval_units.py -q
"""
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from petroharness.well.formation import Interval

SAMPLES = Path(os.environ.get("PETROHARNESS_SAMPLE_LAS", "sample_las"))


def test_a_limit_a_conversion_lands_a_hair_off_a_sample_keeps_it():
    """Limits given in feet are taken into the log's metres (x 0.3048): 4978.5 ft is 1517.4468000000002 m, a float
    error above the sample at 1517.4468 m it names."""
    metres = np.array([1517.2944, 1517.4468, 1517.5992, 1821.3324, 1821.4848, 1821.6372])
    top, base = 4978.5 * 0.3048, 5976.0 * 0.3048
    assert top > metres[1] and base > metres[4]                                 # the float error the test is about
    assert Interval("w", top, base, closed=True).contains(metres).tolist() == [False, True, True, True, True, False]
    assert Interval("w", top, base).contains(metres).tolist() == [False, True, True, True, False, False]   # next top: out
    assert Interval("w", 1517.4468, None).contains(metres).tolist() == [False, True, True, True, True, True]


@pytest.mark.data
def test_the_same_interval_in_metres_and_in_feet_holds_the_same_samples(monkeypatch):
    import petroharness.ask as A
    las = SAMPLES / "tuhua-7.las"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    monkeypatch.delenv("PETROHARNESS_DATA", raising=False)
    cache = Path(tempfile.mkdtemp())

    def samples(top, base, unit):
        p = A.prepare(las, "k2-horizon-7b", formation="w", top=top, base=base, depth_unit=unit, cache=cache)
        A.check(p, A.task_for(p, "q")[0])
        return int(p.view.mask.sum())

    p = A.prepare(las, "k2-horizon-7b", cache=cache)
    A.check(p, A.task_for(p, "q")[0])
    d = p.view.depth                                                            # the log's own depths, metres
    for i in (1093, 3089):                                                      # top and base on samples
        top, base = float(d[i]), float(d[i + 1859])
        assert samples(top, base, "m") == samples(top / 0.3048, base / 0.3048, "ft") == 1860
