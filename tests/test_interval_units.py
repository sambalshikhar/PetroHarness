"""An interval given in feet on a log in metres (or the other way) holds the samples it names: a limit that lands on a
sample after the unit conversion keeps that sample, a hair of float error aside.

    .venv/bin/python -m pytest tests/test_interval_units.py -q
"""
import tempfile
from pathlib import Path

import numpy as np
import pytest

from petroharness.well.formation import Interval

from _wells import SAMPLES  # noqa: E402  (Petrophys's sample files; PETROHARNESS_SAMPLE_LAS for a folder of them)


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
        p = A.prepare(las, "k2-horizon-7b", A.Inputs(formation="w", top=top, base=base, depth_unit=unit), cache=cache)
        A.check(p, A.task_for(p, "q")[0])
        return int(p.view.mask.sum())

    p = A.prepare(las, "k2-horizon-7b", A.Inputs(), cache=cache)
    A.check(p, A.task_for(p, "q")[0])
    d = p.view.depth                                                            # the log's own depths, metres
    for i in (1093, 3089):                                                      # top and base on samples
        top, base = float(d[i]), float(d[i + 1859])
        assert samples(top, base, "m") == samples(top / 0.3048, base / 0.3048, "ft") == 1860


def test_a_name_the_settings_table_lists_twice_is_no_one_stretch(tmp_path):
    """The tops reader. A name the settings' tops table (data.tops_csv) lists twice for the well is no one stretch, as
    the tops-file reader reads it: the settings' reader says so, with the tops it found and what to fix. A name listed
    once is read as its row and the next top."""
    from petroharness.well.formation import resolve_interval
    table = tmp_path / "tops.csv"
    table.write_text("uwi,form,top\nW-1,A FM.,1000\nW-1,B FM.,1100\nW-1,A FM.,1300\nW-1,C FM.,1400\n")
    cols = {"well": "uwi", "name": "form", "top": "top"}
    with pytest.raises(ValueError, match=r"lists A FM\. 2 times for well 'W-1' \(tops at 1000, 1300\)") as err:
        resolve_interval("W-1", "A FM.", table, cols)
    assert all(part in str(err.value) for part in ("WHAT:", "WHY:", "FIX:"))
    got = resolve_interval("W-1", "B FM.", table, cols)                # a name listed once
    assert (got.top, got.base) == (1100.0, 1300.0)
