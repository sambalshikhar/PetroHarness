"""What a tool says about its own call: Petrophys's messages, a misplaced action or argument, a where that names a
stretch, a flag or a range on a selection, the inputs and defaults a computation took, what_if's sides and checks.
Expectations come from the well's own record, its LAS or the raw arrays.

    .venv/bin/python -m pytest tests/test_tool_texts.py -q -n 4
"""
import re

import numpy as np
import pytest

from _wells import CASES, formation_of, sample


@pytest.mark.parametrize("case", ["tuhua", "1671", "cheal", "brent"])
def test_clay_volume_from_sp_is_the_records_vcl_sp(case):
    """The record's sp_max is the clean-sand line and sp_min the shale baseline (Petrophys vcl_from_sp); the library
    step calls them sp_clean and sp_shale. Swapped, calculate returned 1 - VCL_SP."""
    from petroharness.agent import schemas
    f = formation_of(CASES[case])
    rec = np.asarray(f.view.values("VCL_SP"), dtype=float)
    t = schemas.call(f, "calculate", {"property": "clay_volume", "method": "sp", "label": "T"}).text
    got = np.asarray(f.view.calculated["VCL_T"], dtype=float)[f.view.mask]
    both = np.isfinite(rec) & np.isfinite(got)
    assert both.sum() > 50 and np.allclose(got[both], rec[both], atol=1e-9), case
    clean, shale = (float(x) for x in __import__("re").search(r"sp_clean (-?[\d.]+) \(record\), sp_shale (-?[\d.]+) "
                                                            r"\(record\)", t).groups())
    sp = np.asarray(f.view.values("SP"), dtype=float)
    ok = np.isfinite(sp) & np.isfinite(rec) & (rec > 0.02) & (rec < 0.98)
    assert np.allclose((clean - sp[ok]) / (clean - shale), rec[ok], atol=1e-3)     # the record's equation, its lines


def test_petrophys_messages_are_shown_whole_and_once():
    from petroharness.agent.engine import said_whole
    long = "x " * 200 + "FIX: give rmf."
    assert said_whole([long, long, "b\n  c"]) == [long.strip(), "b c"]
    assert said_whole([str(i) for i in range(11)], limit=8)[-1] == "and 3 more"


def test_calculate_says_what_petrophys_did_not_run_to_its_end():
    """tuhua, Simandoux: the mhi step's reason was cut at 160 characters, mid-word, before its second need."""
    from petroharness.agent import schemas
    f = formation_of(CASES["tuhua"])
    t = schemas.call(f, "calculate", {"property": "saturation", "method": "simandoux"}).text
    line = next(l for l in t.splitlines() if "Petrophys did not run:" in l)
    assert line.rstrip().endswith("which has no valid samples on this well"), line


def test_a_misplaced_action_is_told_the_tool_that_takes_it():
    """A bare {"run": ...} or {"search": ...} (about a dozen lost steps in the traces): the refusal names the tools that
    take the key, a run's function under the verb whose list holds it."""
    from petroharness.agent.graph import holders
    said = holders({"run": "pickett_analysis"})
    assert said.startswith(" run is an argument of estimate, ") and '{"estimate": {"run": "pickett_analysis"}}' in said
    assert "search is an argument of " in holders({"search": "archie m from core"})
    assert holders({"nonsense": 1}) == "" and holders(["x"]) == ""


def test_runs_limit_is_said_to_be_a_count_not_a_threshold():
    """A limit that is no count (the condition's threshold written there, benchmark N6: 10 calls) is left out and said;
    the call runs, as runs without a limit does."""
    from petroharness.agent import schemas
    f = formation_of(CASES["brent"])
    for tool, args in (("runs", {"condition": "SW < 0.7"}), ("overlap", {"a": "SW < 0.7", "b": "VCL < 0.3"})):
        r = schemas.call(f, tool, {**args, "limit": 0.7}).text
        assert r.startswith("(limit 0.7 is no count of intervals, left out") and "a threshold is the condition's" in r
        assert r.split("\n", 1)[1] == schemas.call(f, tool, args).text


@pytest.mark.parametrize("where, said", [
    (["Ness Fm."], 'give them as zones, "zones": ["Ness Fm."]'),
    ("Ness Fm.", 'give it as zones, "zones": ["Ness Fm."]'),
    ("SW < 0.5 in the Ness Fm.", '"where": "SW < 0.5", "zones": ["Ness Fm."]'),
    (["Z3", "2850-2860"], 'give them as zones, "zones": ["Z3", "2850-2860"]')])
def test_a_stretch_written_in_where_is_said_to_go_in_zones(where, said):
    """Live (2c, Z2): the model put units in where and read the condition grammar back; it now reads the call to make."""
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    f = formation_of(CASES["brent"])
    with pytest.raises(ToolError) as e:
        schemas.call(f, "stats", {"curves": ["PHIE"], "where": where})
    assert said in str(e.value), str(e.value)


def test_a_condition_or_a_depth_window_in_where_is_read_as_before():
    from petroharness.agent import schemas
    f = formation_of(CASES["brent"])
    for w in ("SW < 0.5", "2850-2900", "Z3", "NET_PAY"):
        schemas.call(f, "stats", {"curves": ["PHIE"], "where": w})
    from dataclasses import replace
    from petroharness.agent.engine import ToolError
    g = formation_of(replace(CASES["brent"], data=(("reach", "focus"),)))
    with pytest.raises(ToolError, match="cannot read 'Ness Fm.'"):             # reach focus: today's reading
        schemas.call(g, "stats", {"curves": ["PHIE"], "where": "Ness Fm."})


def test_a_zone_without_permeability_has_no_flow_role():
    """Petrophys flow_roles gives no role to a zone without a permeability; it was shown as a flow interval."""
    from petroharness.agent import schemas
    f = formation_of(CASES["brent"])
    t = schemas.call(f, "unit_roles", {"zones": ["Dunlin GP."]}).text
    rows = [l for l in t.splitlines() if l.startswith("  R")]
    empty = [l for l in rows if re.search(r"mean PERM\w* \(mD\): n/a", l)]
    assert len(empty) > 5 and all("role (the workflow's): no role (no PERM_CC value in the zone)" in l for l in empty)
    assert not [l for l in rows if l not in empty and "no role" in l]


def test_a_flag_written_on_a_selection_says_where_it_holds_values():
    """classify on the focus, then on the Dunlin (below the focus): the second writes GAS_FLAG again, on the Dunlin
    only. The question's inventory said the focus's GAS_FLAG still; it now says where the values are, and its
    coverage of the interval is the new curve's."""
    from petroharness.agent import schemas
    f = formation_of(CASES["brent"])
    schemas.call(f, "classify", {"what": "gas"})
    assert f.inv.curves["GAS_FLAG"].coverage > 0.5 and "computed on" not in f.inv.curves["GAS_FLAG"].meaning
    schemas.call(f, "classify", {"what": "gas", "zones": ["Dunlin GP."]})
    c = f.inv.curves["GAS_FLAG"]
    assert c.meaning.endswith("(computed on DUNLIN GP.; no value outside it)"), c.meaning
    vals = np.asarray(f.view.calculated["GAS_FLAG"], dtype=float)
    d = np.asarray(f.view.prep.depth, dtype=float) * f.view.depth_scale
    on = np.isfinite(vals)
    assert on.any() and d[on].min() >= 2958 - 0.2 and c.coverage == float(np.isfinite(vals[f.view.mask]).mean()) == 0.0
    t = schemas.call(f, "classify", {"what": "gas"}).text           # the focus again: the curve is the focus's
    assert "computed on" not in f.inv.curves["GAS_FLAG"].meaning and f.inv.curves["GAS_FLAG"].coverage > 0.5, t[:200]


def test_a_number_input_is_described_as_a_number_with_the_records_value_of_its_quantity():
    """tuhua: r_shale was 'number; no RCL curve here' and phi_cl 'number; Neutron Porosity here: NEUT, NPHI'; a number
    takes no curve, and the record's value of the same quantity under another name is what helps."""
    from petroharness.agent.library import api as A
    f = formation_of(CASES["tuhua"])
    rs = A._facts(f, A.lookup("laminated_sand_resistivity"), "r_shale")
    assert rs.startswith("r_shale (number") and "curve here" not in rs and "the record's rcl: 3.6126" in rs, rs
    pc = A._facts(f, A.lookup("correct_neutron_hc"), "phi_cl")
    assert "here:" not in pc and "NPHI" not in pc, pc
    rt = A._facts(f, A.lookup("pickett_analysis"), "rt")                # a curve input keeps the curves here
    assert "here: " in rt, rt


def test_a_method_the_record_used_that_is_no_choice_is_not_called_the_records():
    """tuhua: the record's porosity method (component_based) is none of the library step's choices; the menu said
    "method = density (record)" and the baseline it measured against was density's."""
    from petroharness.agent import schemas
    f = formation_of(CASES["tuhua"])
    t = schemas.call(f, "calculate", {"property": "porosity"}).text
    line = next(l for l in t.splitlines() if l.strip().startswith("method ="))
    assert "(record)" not in line and "library default; the record's component_based is not one of the choices" in line


@pytest.mark.parametrize("where, inside", [("2960-3223", "none of its samples is one of the interval's"),
                                           ("2800-3000", "only 768 of its samples are the interval's")])
def test_a_depth_window_in_where_that_reaches_outside_the_interval_is_said_to_go_in_zones(where, inside):
    """Live (Z2): where "2958-3223" read n 0 of the interval's samples, a claim said the well had no Dunlin samples,
    and the answer followed it although zones ["2958-3223"] had computed there."""
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    f = formation_of(CASES["brent"])
    with pytest.raises(ToolError) as e:
        schemas.call(f, "stats", {"curves": ["PHIT"], "where": where})
    assert inside in str(e.value) and f'"zones": ["{where}"]' in str(e.value), str(e.value)
    schemas.call(f, "stats", {"curves": ["PHIT"], "where": "2850-2900"})                      # inside: read as before
    t = schemas.call(f, "stats", {"curves": ["PHIT"], "zones": ["Dunlin GP."], "where": "3000-3100"}).text
    assert t.startswith("Selection: DUNLIN GP.")                                               # within its stretch


def test_a_range_selection_names_its_depths_once():
    from petroharness.agent import schemas
    f = formation_of(CASES["brent"])
    t = schemas.call(f, "stats", {"curves": ["PHIT"], "zones": ["2958-3223"]}).text
    assert t.startswith("Selection: DUNLIN GP. (2958-3223 m), ") and "2958-3223 m 2958-3223 m" not in t, t[:120]   # R10


def test_a_set_default_reads_the_same_in_every_process():
    """A golden tape replayed with another order of a frozenset default ({'HC', 'GAS', ...}): string hashing differs
    between processes. The default is shown sorted."""
    import os
    import subprocess
    import sys
    code = ("import sys; sys.path[:0]=['src']; from petroharness.agent.library.api import _shown_default; "
            "print(_shown_default(frozenset({'LIGHT OIL', 'DRY GAS', 'HC', 'GAS', 'HYDROCARBON', 'OIL'})))")
    seen = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={**os.environ, "PYTHONHASHSEED": str(seed)}).stdout for seed in (1, 2, 3, 4)}
    assert len(seen) == 1 and next(iter(seen)).startswith("{'DRY GAS', 'GAS', 'HC'"), seen


# --- tool lines on the sample wells ---------------------------------------------------------------------------------


def _las(name: str, curve: str):
    import lasio
    w = lasio.read(str(sample(name)))
    return np.asarray(w.index, dtype=float), np.asarray(w[curve], dtype=float)


@pytest.mark.data
def test_under_a_where_the_all_samples_line_names_the_samples_it_covers():
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


@pytest.mark.data
def test_what_if_heads_with_the_whole_interval():
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


@pytest.mark.data
def test_a_lithology_dependent_default_reads_each_samples_lithology():
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
@pytest.mark.data
def test_the_rw_check_states_its_verdict_whichever_way_it_fails(case, side):
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


@pytest.mark.data
def test_a_what_if_states_the_zones_range_on_each_side_and_of_the_change():
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


@pytest.mark.data
@pytest.mark.parametrize("case", ["brent", "1671", "cheal", "tuhua"])
def test_the_pay_averages_say_the_curve_and_the_mean_petrophys_took(case):
    """Petrophys averages PHIE and PERM over pay from the core-corrected curve where it has values, and every
    permeability (PERM_CC too) geometrically: each pay average's label says what Petrophys took."""
    from petroharness.record.catalog import pay_summary
    f = formation_of(CASES[case])
    view = f.view
    pay = view.values("NET_PAY")
    if pay is None or not np.nansum(pay > 0.5):
        pytest.skip("no net pay here")
    facts = pay_summary(view)["facts"]
    for c in ("PERM", "PERM_CC"):
        lines = [x for x in facts if f" {c} in NET_PAY samples" in x]
        assert all(x.startswith(f"geometric mean {c} in NET_PAY samples") for x in lines), (c, lines)
    from petrophys.evaluation.summaries.zone_summary import pay_average_curves
    took = pay_average_curves(view.interval_well())
    for c in ("PHIE", "PERM"):
        line = next((x for x in facts if f" {c} in NET_PAY samples" in x), None)
        if line and took.get(c) and took[c] != c:
            assert f"{took[c]} where it has a value, {c} elsewhere" in line
    assert [x for x in facts if "NET_PAY samples =" in x]


@pytest.mark.data
@pytest.mark.parametrize("case", ["brent", "1671"])
def test_with_cell_thickness_the_tools_count_thickness_as_petrophys_does(case):
    """Petrophys counts each sample its own cell (n regularly spaced samples, n steps): pay_summary's gross is
    Petrophys's. The tools take first to last sample, one step less, which is the base minus the top a reader computes
    from the depths. With the cell_thickness switch the interval, a zone and a count of samples are n steps."""
    from petroharness import options
    from petroharness.agent.engine import thickness
    from petrophys.evaluation.summaries.net_gross import calculate_net_gross
    view = formation_of(CASES[case]).view
    gross = calculate_net_gross(view.interval_well()).gross_thickness
    z = view.zones[0]
    step = (z.base - z.top) / (z.n_samples - 1)
    near = 0.01 * view.step                                     # the sampling is regular to a hundredth of a step
    assert abs(view.gross - (gross - view.step)) < near                     # off: one step less than Petrophys's
    assert abs(z.thickness - (z.base - z.top)) < 1e-9
    with options.use(cell_thickness=True):
        assert abs(view.gross - gross) < near
        assert abs(z.thickness - z.n_samples * step) < 1e-9 and abs(thickness(z, 3) - 3 * step) < 1e-9
