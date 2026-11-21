"""Brick 1 of docs/designs/zones-and-intervals.md (section 4.1): a view of any stretch of the well.

`FormationView.stretch(top, base)` is the same prepared well over [top, base] in the reporting unit, both limits
included; its zones are built by the focus's rule over its own samples; everything else is the focus view's. The
focus view is made through the same path and must not change (tests/fixtures/focus_views.json, recorded before the
change). The cases are Petrophys's sample wells (tests/_wells.py): a lithology log in metres, an interval by depth,
shale-volume bands, a feet log reported in feet and in metres, the whole of a log, the formation layout.

Expectations are computed here from the prepared well's raw arrays, not from the view's own code.

    .venv/bin/python -m pytest tests/test_stretch.py -q -n 8
"""
import json
from pathlib import Path

import numpy as np
import pytest

from _wells import CASES, focus_view

_SNAP = Path(__file__).parent / "fixtures" / "focus_views.json"      # a maintainers' record: not in the public tree
SNAP = json.loads(_SNAP.read_text()) if _SNAP.exists() else {}
KEYS = list(CASES)
RUNS = [k for k in KEYS if dict(CASES[k].data).get("zone_layout") != "formation"]   # lithology runs or bands
FORMATION = [k for k in KEYS if k not in RUNS]


# --- helpers: independent of the view's code -------------------------------------------------------------------------

def _ranges(idx) -> list:
    idx = np.asarray(idx, dtype=int)
    if idx.size == 0:
        return []
    cut = np.flatnonzero(np.diff(idx) != 1)
    return [[int(a), int(b)] for a, b in zip(np.r_[idx[0], idx[cut + 1]], np.r_[idx[cut], idx[-1]])]


def _runs(values) -> list:
    out = []
    for v in values:
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return out


def _zones(view) -> list:
    return [(z.zone_id, z.name, z.lithology, z.top, z.base, z.n_samples, tuple(np.asarray(z.indices).tolist()), z.stated)
            for z in view.zones]


def _depth(view) -> np.ndarray:
    """Every sample of the well, in the reporting unit, from the prepared well's own depth."""
    return np.asarray(view.prep.depth, dtype=float) * view.depth_scale


def _expected(view, top: float, base: float) -> np.ndarray:
    d, tol = _depth(view), 1e-9
    return (d >= top - tol * max(1.0, abs(top))) & (d <= base + tol * max(1.0, abs(base)))


def _raw(view, curve: str):
    """A curve over the whole well as the view reads it: the workflow's, else the analyzers' or the question's own,
    with the analyzers' values where it has none."""
    data = view.prep.curve(curve)
    if data is None and curve in view.analyzer_curves:
        data = view.analyzer_curves[curve][0]
    if data is None:
        data = view.calculated.get(curve)
    if data is None:
        return None
    data = np.asarray(data, dtype=float)
    fill = view.analyzer_fills.get(curve)
    return data if fill is None else np.where(np.isfinite(data), data, np.asarray(fill, dtype=float))


def _curves(view) -> list:
    return sorted(set(view.prep.input_curves) | set(view.prep.derived_curves) | set(view.analyzer_curves)
                  | set(view.analyzer_fills))


def _stretches(view, seed: int) -> list:
    """(top, base, what): every kind of stretch, generated over the case's well."""
    rng = np.random.default_rng(seed)
    d = _depth(view)
    lo, hi = float(np.nanmin(d)), float(np.nanmax(d))
    f = view.depth
    ftop, fbase = float(f.min()), float(f.max())
    step = float(np.median(np.diff(d)))
    pick = lambda: float(d[int(rng.integers(d.size))])
    out = [(lo, hi, "the whole well"), (ftop, fbase, "the focus"),
           (lo - 50 * step, min(hi, lo + 200 * step), "across the top of the well"),
           (max(lo, hi - 200 * step), hi + 50 * step, "across the base of the well"),
           (ftop - 100 * step, ftop + 100 * step, "across the focus top"),
           (fbase - 100 * step, fbase + 100 * step, "across the focus base"),
           (lo - 1000 * step, hi + 1000 * step, "beyond the well both ways")]
    for _ in range(10):
        a, b = sorted((pick(), pick()))
        out.append((a, b, "limits on samples"))
    for _ in range(10):
        a, b = sorted(float(x) for x in rng.uniform(lo, hi, 2))
        out.append((a, b, "limits between samples"))
    i = int(rng.integers(d.size))
    out.append((float(d[i]), float(d[i]), "one sample"))
    fw = np.flatnonzero(view.mask)                        # windows of the focus's length, shifted: same sample count,
    k = max(1, fw.size // 3)                              # other samples (labels reused from the focus would pass)
    for shift in (k, -k):
        a, b = fw[0] + shift, fw[-1] + shift
        if 0 <= a and b < d.size:
            out.append((float(d[a]), float(d[b]), f"the focus's length, shifted {shift} samples"))
    return out


def _min_thickness(view) -> float:
    """The zone minimum in the reporting unit (the policy states it in metres)."""
    return float(view.policy["zones"]["min_thickness_m"]) / view.m_per_unit


# --- 1. the focus view is unchanged ----------------------------------------------------------------------------------

@pytest.mark.parametrize("key", KEYS)
def test_the_focus_view_is_the_one_recorded_before_the_change(key):
    from petroharness.well.prepare import library_identity
    if not SNAP:
        pytest.skip("the focus views recorded before the change are not in this checkout")
    if library_identity() != SNAP["petrophys"]:
        pytest.skip(f"recorded with Petrophys {SNAP['petrophys']}, this is {library_identity()}: its interpretation, "
                    "and so the shale-volume bands, can differ")
    v, want = focus_view(CASES[key]), SNAP["cases"][key]
    assert [v.interval.formation, v.interval.top, v.interval.base, v.interval.closed] == want["interval"]
    assert (v.report_unit, v.depth_scale, v.m_per_unit, v.lithology_curve) == \
        (want["report_unit"], want["depth_scale"], want["m_per_unit"], want["lithology_curve"])
    assert (list(v.vcl_bands) if v.vcl_bands else None) == want["vcl_bands"]
    assert v.mask.size == want["n_well"] and _ranges(np.flatnonzero(v.mask)) == want["mask"]
    assert _runs([str(x) for x in v.labels]) == want["labels"]
    assert [[z.zone_id, z.name, z.lithology, z.top, z.base, z.n_samples, _ranges(z.indices), z.stated]
            for z in v.zones] == want["zones"]


# --- 2. the same path ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", KEYS)
def test_a_stretch_over_the_focus_samples_is_the_focus_view(key):
    v = focus_view(CASES[key])
    s = v.stretch(float(v.depth.min()), float(v.depth.max()))
    assert np.array_equal(s.mask, v.mask)
    assert [str(x) for x in s.labels] == [str(x) for x in v.labels]
    assert _zones(s) == _zones(v)


# --- 3 and 4. generated stretches: values against the raw arrays, zone invariants ------------------------------------

@pytest.mark.parametrize("key", KEYS)
def test_every_stretch_reads_the_wells_own_samples_and_values(key):
    v = focus_view(CASES[key])
    d = _depth(v)
    lo, hi = float(np.nanmin(d)), float(np.nanmax(d))
    curves = _curves(v)
    assert len(curves) > 5
    checked = 0
    for top, base, what in _stretches(v, seed=sum(map(ord, key))):
        want = _expected(v, top, base)
        if not want.any():
            with pytest.raises(ValueError, match="no sample of the well"):
                v.stretch(top, base)
            continue
        s = v.stretch(top, base)
        assert np.array_equal(s.mask, want), (what, top, base)
        assert np.allclose(s.depth, d[want]), what
        assert s.interval.top == pytest.approx(max(top, lo)) and s.interval.base == pytest.approx(min(base, hi)), what
        assert s.interval.closed
        clipped = top < lo or base > hi
        assert (s.requested == (top, base)) if clipped else s.requested is None, what
        for c in curves:
            got, raw = s.values(c), _raw(v, c)
            assert got is not None and np.array_equal(got, raw[want], equal_nan=True), (what, c)
        checked += 1
    assert checked >= 20


@pytest.mark.parametrize("key", RUNS)
def test_the_zones_of_every_stretch_are_its_label_runs_thicker_than_the_minimum(key):
    """Recomputed here from the stretch's labels: the maximal runs of one label strictly thicker than the minimum, in
    depth order, ids Z1.. consecutive; and the labels are the focus's on the samples both hold."""
    v = focus_view(CASES[key])
    focus_label = dict(zip(np.flatnonzero(v.mask).tolist(), [str(x) for x in v.labels]))
    minimum = _min_thickness(v)
    for top, base, what in _stretches(v, seed=7 + len(key)):
        if not _expected(v, top, base).any():
            continue
        s = v.stretch(top, base)
        labels, depth = np.asarray([str(x) for x in s.labels]), s.depth
        n = int(s.mask.sum())
        assert labels.size == n and depth.size == n, what
        for i, w in enumerate(np.flatnonzero(s.mask).tolist()):
            if w in focus_label:
                assert labels[i] == focus_label[w], (what, w)
        runs, start = [], 0
        for i in range(1, n + 1):
            if i == n or labels[i] != labels[start]:
                if depth[i - 1] - depth[start] > minimum:
                    runs.append((start, i - 1, labels[start]))
                start = i
        got = [(int(z.indices[0]), int(z.indices[-1]), z.lithology) for z in s.zones]
        assert got == runs, (what, got[:3], runs[:3])
        seen = np.zeros(n, dtype=bool)
        for k, z in enumerate(s.zones, start=1):
            idx = np.asarray(z.indices)
            assert z.zone_id == f"Z{k}", what
            assert np.array_equal(idx, np.arange(idx[0], idx[-1] + 1)) and not seen[idx].any(), what
            seen[idx] = True
            assert set(labels[idx]) == {z.lithology}, what
            assert z.top == round(float(depth[idx[0]]), 4) and z.base == round(float(depth[idx[-1]]), 4), what
            assert z.n_samples == idx.size, what
        assert int(seen.sum()) == int(s.zoned.sum()), what


@pytest.mark.parametrize("key", FORMATION)
def test_the_formation_layout_gives_one_zone_over_every_sample_of_a_stretch(key):
    v = focus_view(CASES[key])
    for top, base, what in _stretches(v, seed=11):
        if not _expected(v, top, base).any():
            continue
        s = v.stretch(top, base)
        assert len(s.zones) == 1 and s.zones[0].zone_id == "Z1", what
        assert np.array_equal(s.zones[0].indices, np.arange(int(s.mask.sum()))), what


# --- 5. locality -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", RUNS)
def test_a_focus_zone_inside_a_stretch_is_a_zone_of_the_stretch(key):
    """A zone of the focus whose run is held whole by a stretch (not cut by the focus's or the stretch's limits) is a
    zone of the stretch: same samples of the well, lithology, top and base."""
    v = focus_view(CASES[key])
    fw = np.flatnonzero(v.mask)
    nf = fw.size
    if not any(np.asarray(z.indices)[0] > 0 and np.asarray(z.indices)[-1] < nf - 1 for z in v.zones):
        pytest.skip(f"every zone of the focus touches its limits ({len(v.zones)} zone(s) over the whole focus)")
    matched = 0
    for top, base, what in _stretches(v, seed=3):
        if not _expected(v, top, base).any():
            continue
        s = v.stretch(top, base)
        sw = np.flatnonzero(s.mask)
        theirs = {(tuple(sw[np.asarray(z.indices)].tolist()), z.lithology, z.top, z.base) for z in s.zones}
        for z in v.zones:
            idx = np.asarray(z.indices)
            if idx[0] == 0 or idx[-1] == nf - 1:
                continue                                   # cut by the focus's limits: it may run on outside
            w = fw[idx]
            if not (w[0] > sw[0] and w[-1] < sw[-1]):
                continue                                   # not held whole, away from the stretch's limits
            assert (tuple(w.tolist()), z.lithology, z.top, z.base) in theirs, (what, z.zone_id)
            matched += 1
    assert matched > 0


# --- 6. edges, typed by hand -----------------------------------------------------------------------------------------

def test_a_stretch_outside_the_well_is_refused_with_the_wells_range():
    v = focus_view(CASES["brent"])
    d = _depth(v)
    with pytest.raises(ValueError, match=r"no sample of the well.*from [\d.]+ to [\d.]+ m"):
        v.stretch(float(d.max()) + 100, float(d.max()) + 200)


def test_a_stretch_whose_top_is_below_its_base_is_refused():
    v = focus_view(CASES["brent"])
    with pytest.raises(ValueError, match=r"top 2900 m is below its base 2850 m"):
        v.stretch(2900.0, 2850.0)


def test_a_stretch_between_two_samples_is_refused():
    v = focus_view(CASES["brent"])
    d = v.depth
    with pytest.raises(ValueError, match="no sample of the well"):
        v.stretch(float(d[10]) + 0.01, float(d[11]) - 0.01)


def test_a_stretch_of_one_sample_has_it_and_no_zone():
    v = focus_view(CASES["brent"])
    d = v.depth
    s = v.stretch(float(d[100]), float(d[100]))
    assert int(s.mask.sum()) == 1 and s.zones == [] and int(s.zoned.sum()) == 0


def test_a_stretch_reaching_past_the_well_is_clipped_and_says_what_was_asked():
    v = focus_view(CASES["brent"])
    d = _depth(v)
    lo = float(d.min())
    s = v.stretch(lo - 100.0, lo + 10.0)
    assert s.interval.top == pytest.approx(lo) and s.interval.base == pytest.approx(lo + 10.0)
    assert s.requested == (lo - 100.0, lo + 10.0)


def test_a_stretch_includes_samples_exactly_on_its_limits():
    v = focus_view(CASES["brent"])
    d = v.depth
    s = v.stretch(float(d[50]), float(d[60]))
    assert int(s.mask.sum()) == 11 and s.depth[0] == pytest.approx(d[50]) and s.depth[-1] == pytest.approx(d[60])


def test_a_feet_log_reported_in_metres_takes_its_limits_in_metres():
    """Teapot 17-WX-21 is sampled every 0.5 ft from 0 ft. 700 to 800 m: the first sample at or below 700 m is
    2297.0 ft (700.1256 m; 2296.5 ft is 699.9732 m), the last at or above 800 m is 2624.5 ft (799.9476 m)."""
    v = focus_view(CASES["teapot_m"])
    assert v.report_unit == "m" and v.depth_scale == pytest.approx(0.3048)
    s = v.stretch(700.0, 800.0)
    assert int(s.mask.sum()) == 656
    assert s.depth[0] == pytest.approx(700.1256) and s.depth[-1] == pytest.approx(799.9476)


def test_a_feet_log_reported_in_feet_takes_its_limits_in_feet():
    v = focus_view(CASES["teapot"])
    assert v.report_unit == "ft" and v.depth_scale == 1.0
    s = v.stretch(2297.0, 2624.5)
    assert int(s.mask.sum()) == 656 and s.depth[0] == 2297.0 and s.depth[-1] == 2624.5


# --- 7. isolation ----------------------------------------------------------------------------------------------------

def test_a_stretch_leaves_the_focus_view_as_it_was():
    v = focus_view(CASES["brent"])
    mask, zones, labels = v.mask.copy(), _zones(v), [str(x) for x in v.labels]
    d = _depth(v)
    s = v.stretch(float(d.min()), float(d.max()))
    assert s is not v and int(s.mask.sum()) > int(v.mask.sum())
    assert np.array_equal(v.mask, mask) and _zones(v) == zones and [str(x) for x in v.labels] == labels
    assert v.requested is None and v.interval.formation == "BRENT GP."


def test_a_curve_calculated_after_the_stretch_was_made_is_read_by_both():
    v = focus_view(CASES["brent"])
    s = v.stretch(2700.0, 3000.0)
    values = np.arange(v.mask.size, dtype=float)
    v.calculated["STRETCH_TEST"] = values
    try:
        assert np.array_equal(s.values("STRETCH_TEST"), values[s.mask])
        assert np.array_equal(v.values("STRETCH_TEST"), values[v.mask])
    finally:
        del v.calculated["STRETCH_TEST"]
