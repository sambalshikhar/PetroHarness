"""`runs` opens with the intervals where the condition holds over the whole interval or selection, uncut by zones,
each with the zones it touches (or "outside any zone"); a one-sample interval reads "at D (one sample)"; then each
zone's thickness. The layout is the same under every reach; reach "focus" (the benchmark) lists the 20 thickest when
the call gives no limit, reach "well" every interval.

A synthetic well with GR written by hand gives the intervals of GR < 70 exactly; on GeoLink 30/6-5 the intervals of
NET_PAY = 1 are compared with the runs of the raw flag computed here.

    .venv/bin/python -m pytest tests/test_runs_intervals.py -q -n 4
"""
import re

import numpy as np
import pytest

from _synthetic import plausible_logs, runs_of, write_las, write_tops
from _wells import CASES, Case, formation_of

# 0.5 m samples 1000-1100 m. SAND 1000-1009.5 (Z1), SHALE 1010-1011.5 (thin: outside any zone), SAND 1012-1016.5 (Z2),
# CROSSBEDDED SAND 1017-1031.5 (Z3), SHALE 1032-1033 (thin), SILT 1033.5-1053 (Z4 in the focus 1000-1050),
# LIMESTONE 1053.5-1100. GR 35 in sand, 110 elsewhere, and 30 at 1010.5 m and at 1040 m.
LITH = [(1, 20), (7, 4), (2, 10), (3, 30), (7, 3), (5, 40), (9, 94)]


def _well(tmp_dir, reach="well"):
    depth = np.arange(1000.0, 1100.0 + 1e-9, 0.5)
    lith = runs_of(LITH)
    logs = plausible_logs(depth, np.isin(lith, (1, 2, 3)))
    gr = np.where(np.isin(lith, (1, 2, 3)), 35.0, 110.0)
    gr[np.isclose(depth, 1010.5)] = 30.0
    gr[np.isclose(depth, 1040.0)] = 30.0
    logs["GR"] = ("GAPI", gr)
    logs["LITHOLOGY"] = ("", lith)
    las = write_las(tmp_dir / "synth-runs.las", depth, logs, unit="M", well="SYNTH-R")
    tops = write_tops(tmp_dir / "tops.csv", [("UPPER FM.", 1000.0, 1050.0, "m"), ("LOWER FM.", 1050.0, 1100.0, "m")])
    data = () if reach == "well" else (("reach", "focus"),)
    return formation_of(Case(str(las), str(tops), "UPPER FM.", data=data))


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    return _well(tmp_path_factory.mktemp("runs"))


def _thick(f, n):
    """A run of n samples as thickness, the whole interval's convention (its gross x the share of its samples)."""
    return f.inv.gross * n / f.depth.size


def test_the_synthetic_focus_has_the_zones_typed_here(synth):
    assert [(z.zone_id, z.lithology, z.top, z.base) for z in synth.view.zones] == [
        ("Z1", "SAND", 1000.0, 1009.5), ("Z2", "SAND", 1012.0, 1016.5), ("Z3", "CROSSBEDDED SAND", 1017.0, 1031.5),
        ("Z4", "SILT", 1033.5, 1050.0)]


def _parts(line: str):
    """(span text, thickness, zones) of an interval line."""
    m = re.match(r"^    (.+?), ([\d.]+) m, (.+)$", line)
    return m.group(1), float(m.group(2)), m.group(3)


def test_runs_opens_with_every_interval_uncut_by_zones(synth):
    from petroharness.agent import schemas
    t = schemas.call(synth, "runs", {"condition": "GR < 70"}).text
    lines = t.splitlines()
    head = re.match(r"^Intervals where GR < 70 \(4 intervals, ([\d.]+) m, ", lines[0])
    assert head and float(head.group(1)) == pytest.approx(_thick(synth, 62), abs=1e-3)
    assert lines[1] == "  every interval, top to base (top-base, thickness, zones), 4 of 4:"
    want = [("1000-1009.5 m", 20, "Z1"), ("at 1010.5 m (one sample)", 1, "outside any zone"),
            ("1012-1031.5 m", 40, "Z2, Z3"), ("at 1040 m (one sample)", 1, "Z4")]
    for line, (span, n, zones) in zip(lines[2:6], want):
        got = _parts(line)
        assert got[0] == span and got[2] == zones and got[1] == pytest.approx(_thick(synth, n), abs=1e-3), line


def test_then_each_zones_thickness_in_the_zones_convention(synth):
    from petroharness.agent import schemas
    t = schemas.call(synth, "runs", {"condition": "GR < 70"}).text
    by = next(l for l in t.splitlines() if l.startswith("  by zone:"))
    zs = {z.zone_id: z for z in synth.view.zones}
    for zid, n in (("Z1", 20), ("Z2", 10), ("Z3", 30), ("Z4", 1)):
        z = zs[zid]
        got = float(re.search(rf"\b{zid} ([\d.]+) m", by).group(1))
        assert got == pytest.approx(z.thickness * n / z.n_samples, abs=1e-3), (zid, by)
    assert "none in" not in by


def test_a_limit_lists_the_thickest_and_keeps_the_others(synth):
    from petroharness.agent import schemas
    t = schemas.call(synth, "runs", {"condition": "GR < 70", "limit": 2}).text
    lines = t.splitlines()
    assert lines[1].startswith("  thickest intervals, top to base (top-base, thickness, zones; the other intervals: ")
    assert lines[1].endswith("), 2 of 4:")
    assert lines[2].startswith("    1000-1009.5 m,") and lines[3].startswith("    1012-1031.5 m,")


def test_zones_asked_keep_the_intervals_inside_them(synth):
    from petroharness.agent import schemas
    t = schemas.call(synth, "runs", {"condition": "GR < 70", "zones": ["Z3"]}).text
    lines = t.splitlines()
    assert lines[0].startswith("Intervals where GR < 70 in Z3 (1 interval, ")
    first = next(ln for ln in lines if ln.startswith("    "))          # the zone's interval (the whole interval's
    assert first == "    1017-1031.5 m, " + first.split(", ")[1] + ", Z3"   # line, under the head, says the rest)


def test_no_interval_says_so_with_where_it_looked(synth):
    from petroharness.agent import schemas
    t = schemas.call(synth, "runs", {"condition": "GR < 70", "zones": ["LOWER FM."]}).text
    assert "No interval where GR < 70" in t and t.startswith("Selection: LOWER FM. 1050-1100 m")


def test_under_reach_focus_the_layout_is_the_same(synth, tmp_path):
    from petroharness.agent import schemas
    f = _well(tmp_path, reach="focus")
    t = schemas.call(f, "runs", {"condition": "GR < 70"}).text
    assert t.startswith("Intervals where GR < 70 (4 intervals, ") and "inside the zones" not in t
    assert t == schemas.call(synth, "runs", {"condition": "GR < 70"}).text       # line for line what reach well gives


@pytest.fixture(scope="module")
def brent():
    return formation_of(CASES["brent"])


def _raw_runs(f, flag):
    """(top, base, n) of each run of consecutive interval samples with flag > 0.5, from the prepared well's arrays."""
    v = f.view
    d = np.asarray(v.prep.depth, dtype=float)[v.mask] * v.depth_scale
    x = np.asarray(v.prep.curve(flag), dtype=float)[v.mask]
    on = np.isfinite(x) & (x > 0.5)
    idx = np.flatnonzero(on)
    if not idx.size:
        return []
    br = np.flatnonzero(np.diff(idx) > 1)
    return [(float(d[a]), float(d[b]), int(b - a + 1)) for a, b in zip(np.r_[idx[0], idx[br + 1]], np.r_[idx[br], idx[-1]])]


def test_brent_pay_intervals_are_the_runs_of_the_raw_flag(brent):
    from petroharness.agent import schemas
    t = schemas.call(brent, "runs", {"condition": "NET_PAY = 1", "limit": 50}).text
    want = _raw_runs(brent, "NET_PAY")
    got = re.findall(r"^    (?:at )?([\d.]+)(?:-([\d.]+))? m(?: \(one sample\))?, ", t, re.M)
    got = [(float(a), float(b) if b else float(a)) for a, b in got]
    assert len(got) == len(want) and all(abs(g[0] - w[0]) < 1e-3 and abs(g[1] - w[1]) < 1e-3 for g, w in zip(got, want)), \
        (got[:5], want[:5])
    assert t.splitlines()[0].startswith(f"Intervals where NET_PAY = 1 ({len(want)} interval")


def test_an_interval_across_zones_names_each_it_touches(brent):
    """Brent's pay runs from Z6 into Z7 without a break: one interval (the raw flag's run holding 2877.5 m), its line
    naming Z6 and Z7 among the zones it touches."""
    from petroharness.agent import schemas
    t = schemas.call(brent, "runs", {"condition": "NET_PAY = 1", "limit": 50}).text
    a, b, n = next(r for r in _raw_runs(brent, "NET_PAY") if r[0] < 2877.5 < r[1])
    spans = [(m, float(m.group(1)), float(m.group(2))) for m in
             (re.match(r"^    ([\d.]+)-([\d.]+) m, ", l) for l in t.splitlines()) if m]
    line = next(m.string for m, top, base in spans if abs(top - a) < 1e-3 and abs(base - b) < 1e-3)
    zones = line.split(" m, ")[-1].split(", ")
    assert "Z6" in zones and "Z7" in zones, line


def test_every_interval_is_listed_unless_a_limit_is_given():
    """Live (tuhua, "list every interval in the whole well where GR is below 60"): 28 intervals, 20 listed by the
    default limit and the other 8 out of the answer's reach. Under reach well the list is whole; a limit given is kept;
    under reach focus the default is the 20 thickest."""
    from dataclasses import replace
    from petroharness.agent import schemas
    from _wells import CASES, formation_of
    f = formation_of(CASES["tuhua"])
    t = schemas.call(f, "runs", {"condition": "GR < 60"}).text
    n = int(__import__("re").search(r"\((\d+) intervals,", t).group(1))
    assert n > 20 and f"every interval, top to base (top-base, thickness, zones), {n} of {n}:" in t
    assert f"thickest intervals, top to base" in schemas.call(f, "runs", {"condition": "GR < 60", "limit": 5}).text
    g = formation_of(replace(CASES["tuhua"], data=(("reach", "focus"),)))
    assert ", 20 of " in schemas.call(g, "runs", {"condition": "GR < 60"}).text
