"""Fixes from the structural audits of 2026-11-18 (names and kinds, reach, advice and scope, traces), each with the
check that would have caught it. Expectations come from the well's own record or the raw arrays.

    .venv/bin/python -m pytest tests/test_audit_fixes.py -q -n 4
"""
import re

import numpy as np
import pytest

from _wells import CASES, formation_of


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
    from petroharness.agent import library_api as A
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
    code = ("import sys; sys.path[:0]=['src']; from petroharness.agent.library_api import _shown_default; "
            "print(_shown_default(frozenset({'LIGHT OIL', 'DRY GAS', 'HC', 'GAS', 'HYDROCARBON', 'OIL'})))")
    seen = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={**os.environ, "PYTHONHASHSEED": str(seed)}).stdout for seed in (1, 2, 3, 4)}
    assert len(seen) == 1 and next(iter(seen)).startswith("{'DRY GAS', 'GAS', 'HC'"), seen
