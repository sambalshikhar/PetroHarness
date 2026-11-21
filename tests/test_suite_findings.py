"""Defects the question suite found (gaps/qsuite/FINDINGS.md, 2026-11-19), each with its general rule, checked against
the LAS or the record's arrays.

    .venv/bin/python -m pytest tests/test_suite_findings.py -q
"""
import re

import numpy as np
import pytest

from _wells import CASES, formation_of, sample

pytestmark = pytest.mark.data


def _las(name: str, curve: str):
    import lasio
    w = lasio.read(str(sample(name)))
    return np.asarray(w.index, dtype=float), np.asarray(w[curve], dtype=float)


def test_f3_under_a_where_the_all_samples_line_names_the_samples_it_covers():
    """B01: 'whole interval (201 samples outside any zone)' over the 158 samples of a depth window; the writer read it
    as the whole interval and the Ness mean (75.01 from the LAS) as unavailable."""
    from petroharness.agent import schemas
    f = formation_of(CASES["brent"])
    d, gr = _las("30/6-5", "GR")
    keep = (d >= 2841) & (d <= 2865) & np.isfinite(gr) & (gr >= 0)
    t = schemas.call(f, "stats", {"curves": ["GR"], "where": "2841-2865"}).text
    line = next(ln for ln in t.splitlines() if "every sample where" in ln)
    m = re.search(r"every sample where depth 2841-2865 m \((\d+) samples, (\d+) of them outside any zone\).*mean ([\d.]+)", line)
    assert m and int(m.group(1)) == keep.sum() and abs(float(m.group(3)) - gr[keep].mean()) < 1e-3, line
    assert "whole interval (" not in t


def test_f4_what_if_heads_with_the_whole_interval():
    """T04: tuhua's 16 net-reservoir samples lie outside the rows; what_if gave 0 pooled and 0 per zone for every
    cutoff, and the answer said the whole McKee 'is not computed'."""
    from petroharness.agent import schemas
    f = formation_of(CASES["tuhua"])
    res = np.asarray(f.view.values("NET_RES"), dtype=float)
    share = 100 * np.nanmean(res > 0.5)
    assert 0 < share and int(np.nansum(res > 0.5)) == 16
    t = schemas.call(f, "what_if", {"property": "net_pay", "parameter": "phie_cutoff", "values": [0.08],
                                    "target": "NET_RES"}).text
    base = next(ln for ln in t.splitlines() if ln.strip().startswith("baseline"))
    got = float(re.search(r"baseline \(record's parameters\): ([\d.]+) whole interval", base).group(1))
    assert abs(got - share) < 1e-3 and "the whole interval, the zones pooled and each zone" in t


def test_f7_a_lithology_dependent_default_reads_each_samples_lithology():
    """W03: the shear prediction used the porosity matrix's sandstone for the whole well. Each sample now takes its
    lithology from the record (the lithology log, then LITHO), the matrix only where neither names one, and a matrix
    that is a default says so."""
    from petrophys.interpretation.saturation.sonic.rock_physics import slowness_to_velocity, vs_from_vp_greenberg_castagna
    from petroharness.agent import schemas
    from petroharness.well.summary import code_labels
    f = formation_of(CASES["hw3"])
    lab = code_labels(f.view, "LITHO")
    x = np.asarray(f.view.values("LITHO"), dtype=float)
    want = {k: int(np.sum(x == c)) for c, k in lab.items() if k in ("limestone", "dolomite")}
    t = schemas.call(f, "calibrate", {"what": "shear"}).text.splitlines()[0]
    from petroharness.agent import library as L                       # D3: samples no option names (or with no
    _, _, gaps, _ = L.sample_lithology(f, ("sandstone", "limestone", "dolomite", "shale"))   # lithology) are said
    assert all(f"{k} {n}" in t for k, n in want.items() if n) and ("at Petrophys's default" in t) == bool(gaps), t
    dts = np.asarray(f.view.calculated["DTS_GC"], dtype=float)[f.view.mask]
    dtc = np.asarray(f.view.values("DTC"), dtype=float)
    lime = next(c for c, k in lab.items() if k == "limestone")
    i = int(np.flatnonzero((x == lime) & np.isfinite(dtc))[0])
    vs = vs_from_vp_greenberg_castagna(slowness_to_velocity(dtc[i]), "limestone")
    assert abs(dts[i] - 304800.0 / vs) < 1e-6                               # its own lithology's coefficients


@pytest.mark.parametrize("case, side", [("hw3", "No clean porous rock reads as water"),
                                        ("1671", "The Rw in use looks too high"), ("brent", None)])
def test_f8_the_rw_check_states_its_verdict_whichever_way_it_fails(case, side):
    """W02: HW-3's header Rw is about 1/99 of the Rwa of its clean porous rock (median Rwa / Rw 98.98), yet Petrophys
    warned only when the Rw looks too high, and the answer called the header Rw reliable. The check warns both ways,
    with its limits in the record's notes; a well with water-bearing rock (P5 below 1) stays quiet."""
    from petroharness.agent.map import render
    f = formation_of(CASES[case])
    st = f.view.prep.steps["rw"]
    p, said = st["parameters"], [d for d in st["decisions"] if d.startswith(("No clean porous", "The Rw in use looks"))]
    assert "above 2 (no clean porous rock reads as water)" in st["notes"]["rwa_p5_over_rw"]
    if side is None:
        assert said == [] and p["rwa_p5_over_rw"] < 1 < p["rwa_median_over_rw"]
        return
    assert len(said) == 1 and said[0].startswith(side), said
    if case == "hw3":
        assert p["rwa_p5_over_rw"] > 2 and f"is {p['rwa_p5_over_rw']:.2f} times it" in said[0]
        sw = float(re.search(r"Sw below ([\d.]+) at 95%", said[0]).group(1))
        assert abs(sw - (1 / p["rwa_p5_over_rw"]) ** 0.5) < 0.01                   # n = 2: Sw at the P5's Rwa
    assert side in render(f.inv)                                                   # the map the model reads says it


def test_p5_a_what_if_states_the_zones_range_on_each_side_and_of_the_change():
    """P5: under Rw 0.05 the answer said the zone means "run from 0.07249 (R1) to 0.05072 (R17)": R1's baseline and
    R17's changed mean, read off the pairs "R1 0.07249 -> 0.05178; ...". Each curve's effect now states the zones'
    range of the baseline, of the changed values and of the change, each end with its zone, read from the pairs."""
    from petroharness.agent import schemas
    f = formation_of(CASES["brent"])
    t = schemas.call(f, "calculate", {"property": "water_resistivity", "parameters": {"rw": 0.05}, "label": "P5"}).text
    pairs = next(ln for ln in t.splitlines() if ln.strip().startswith("each zone (mean, baseline -> changed)"))
    got = [(z, float(b), float(a)) for z, b, a in re.findall(r"(Z\d+) ([-\d.e]+) -> ([-\d.e]+)", pairs)]
    assert len(got) > 1
    # each change stated beside its pair, the pooled one too, and the changed samples with their total
    for z, b, a, d in re.findall(r"(Z\d+) ([-\d.e]+) -> ([-\d.e]+) \(([-+\d.e]+)\)", pairs):
        assert abs(float(d) - (float(a) - float(b))) <= 2e-4, (z, b, a, d)
    head = next(ln for ln in t.splitlines() if ln.strip().startswith("RW: mean"))
    m = re.search(r"; ([-\d.e]+) -> ([-\d.e]+) \(([-+\d.e]+)\) zones pooled; (\d+) of (\d+) samples changed", head)
    assert m and abs(float(m.group(3)) - (float(m.group(2)) - float(m.group(1)))) <= 2e-4, head
    assert int(m.group(4)) <= int(m.group(5)) == int(f.view.mask.sum()), head
    line = next(ln for ln in t.splitlines() if ln.strip().startswith("the zones' range (mean)"))
    m = re.search(r"baseline ([-\d.e]+) \((Z\d+)\) to ([-\d.e]+) \((Z\d+)\); changed ([-\d.e]+) \((Z\d+)\) to "
                  r"([-\d.e]+) \((Z\d+)\); change ([-\d.e]+) \((Z\d+)\) to ([-\d.e]+) \((Z\d+)\)", line)
    assert m, line
    lo_b, hi_b = min(got, key=lambda r: r[1]), max(got, key=lambda r: r[1])
    lo_a, hi_a = min(got, key=lambda r: r[2]), max(got, key=lambda r: r[2])
    assert (m.group(2), m.group(4), m.group(6), m.group(8)) == (lo_b[0], hi_b[0], lo_a[0], hi_a[0]), line
    assert abs(float(m.group(5)) - lo_a[2]) <= 1e-3 * abs(lo_a[2]) and abs(float(m.group(7)) - hi_a[2]) <= 1e-3 * abs(hi_a[2])
    assert float(m.group(9)) <= float(m.group(11)) < 0              # every zone's RW falls under a lower Rw
