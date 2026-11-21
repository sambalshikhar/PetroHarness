"""Brick 2a of docs/designs/zones-and-intervals.md (4.2): what a tool's `zones` names, anywhere in the well.

An item is, first match wins: a zone id of the focus, ALL, a lithology of the focus's zones, a unit of the tops file
(matched as the focus's name is), a depth range TOP-BASE (a unit m or ft, else the reporting unit). Focus items alone
keep today's path; one unit or range is its stretch, with rows R1.. (its lithology zones); several items are one row
each, a shared boundary sample the deeper item's; overlaps, units listed twice, items with no sample and unknown items
are refused. Under `reach: focus` (the benchmark's data configs) nothing but focus items is taken, refused as today.

Parts: parsing typed by hand; resolution on a synthetic well with hand-typed expectations; the real pipeline and call
door on a synthetic LAS and tops file; every tool that takes zones on GeoLink 30/6-5 with its tops file.

    .venv/bin/python -m pytest tests/test_selection.py -q -n 8
"""
import re
from types import SimpleNamespace

import numpy as np
import pytest

from _synthetic import runs_of, view

# ---------------------------------------------------------------------------------------------------------------------
# 1. parsing: a depth range in the reporting unit

M = SimpleNamespace(report_unit="m", m_per_unit=1.0)
FT = SimpleNamespace(report_unit="ft", m_per_unit=0.3048)


@pytest.mark.parametrize("text, want", [
    ("2870-2890", (2870.0, 2890.0)), ("2870 - 2890 m", (2870.0, 2890.0)), ("2870–2890", (2870.0, 2890.0)),
    ("2870—2890", (2870.0, 2890.0)), ("2870.5-2890.25", (2870.5, 2890.25)), ("2870-2890M", (2870.0, 2890.0)),
    (" 2870-2890 ", (2870.0, 2890.0)), ("2870-2890 metres", (2870.0, 2890.0)), ("2870 to 2890 m", (2870.0, 2890.0)),
    ("9400-9500 ft", (9400 * 0.3048, 9500 * 0.3048)), ("9400-9500 feet", (9400 * 0.3048, 9500 * 0.3048)),
])
def test_a_depth_range_is_read_in_the_reporting_unit(text, want):
    from petroharness.agent.selection import parse_range
    got = parse_range(text, M)
    assert got == pytest.approx(want)


def test_a_range_in_metres_on_a_well_reported_in_feet():
    from petroharness.agent.selection import parse_range
    assert parse_range("2870-2890 m", FT) == pytest.approx((2870 / 0.3048, 2890 / 0.3048))
    assert parse_range("9400-9500", FT) == pytest.approx((9400.0, 9500.0))


@pytest.mark.parametrize("text", ["Z3", "SAND", "2870", "Ness Fm.", "ALL", "2870-2890-2900", "", "-", "R2"])
def test_what_is_no_range_is_not_read_as_one(text):
    from petroharness.agent.selection import parse_range
    assert parse_range(text, M) is None


def test_a_reversed_range_is_refused_with_the_fix():
    from petroharness.agent.selection import parse_range
    with pytest.raises(ValueError, match=r"2890-2870: its top 2890 m is below its base 2870 m.*shallower depth first"):
        parse_range("2890-2870", M)


def test_a_range_in_an_unknown_unit_is_refused():
    from petroharness.agent.selection import parse_range
    with pytest.raises(ValueError, match=r"2870-2890 km: the unit km is not m or ft"):
        parse_range("2870-2890 km", M)


# ---------------------------------------------------------------------------------------------------------------------
# 2. resolution on a synthetic well: 0.5 m samples from 0 m. SAND 0-2.0, SHALE 2.5-5.0, SAND 5.5-8.5, SILT 9.0,
# LIMESTONE 9.5-14.0 (29 samples). The focus is 0-7.0 m (15 samples): SAND 0-2.0 (2.0 m) and SAND 5.5-7.0 (1.5 m)
# are no zones, so its one zone is Z1 SHALE 2.5-5.0.

DEPTH = np.arange(29) * 0.5
CODES = runs_of([(1, 5), (7, 6), (1, 3), (2, 4), (5, 1), (9, 10)])
UNITS = [  # name, top, base (reporting unit), the tops file's line; a unit listed twice has two rows
    ("UPPER", 0.0, 7.0, 2), ("LOWER", 7.0, 14.0, 3), ("MID MEMBER", 3.0, 5.0, 4), ("SAND", 10.0, 12.0, 5),
    ("Z1", 12.0, 14.0, 6), ("FAR", 100.0, 200.0, 7), ("TWICE", 1.0, 2.0, 8), ("TWICE", 11.0, 12.0, 9),
]


def _f(reach="well"):
    from petroharness.agent.engine import Formation
    from petroharness.agent.selection import Unit
    v = view(DEPTH, lithology=CODES, focus=(0.0, 7.0))
    v.reach = reach
    v.units = [Unit(name=n, top=t, base=b, line=line) for n, t, b, line in UNITS]
    return Formation(inv=None, view=v)


def _rows(f2):
    return [(z.zone_id, z.lithology, z.top, z.base, z.n_samples) for z in f2.view.zones]


def test_the_synthetic_focus_has_one_zone():
    f = _f()
    assert [(z.zone_id, z.lithology, z.top, z.base) for z in f.view.zones] == [("Z1", "SHALE", 2.5, 5.0)]


@pytest.mark.parametrize("asked", [["Z1"], ["z1"], ["SHALE"], ["ALL"], None, []])
def test_focus_items_keep_todays_path(asked):
    """A zone id of the focus (in any case) wins over the unit named Z1; a lithology of the focus's zones, ALL and
    nothing asked are the focus too: the call goes on as today."""
    from petroharness.agent.selection import resolve
    f = _f()
    f2, zones = resolve(f, asked)
    assert f2 is f and zones == asked


def test_a_lithology_of_the_focus_wins_over_a_unit_of_that_name():
    from petroharness.agent.selection import resolve
    f = _f()
    f.view.zones[0].lithology = "SAND"            # the focus has a SAND zone: SAND is the lithology, not the unit
    f2, zones = resolve(f, ["SAND"])
    assert f2 is f and zones == ["SAND"]


def test_one_unit_outside_the_focus_is_its_stretch_with_rows_of_its_own():
    """LOWER 7.0-14.0 m: SAND 7.0-8.5 (1.5 m: no row), SILT 9.0, LIMESTONE 9.5-14.0 (a row)."""
    from petroharness.agent.selection import resolve
    f2, zones = resolve(_f(), ["lower"])
    assert zones is None and f2.view.selection == "LOWER"
    assert f2.view.depth[0] == 7.0 and f2.view.depth[-1] == 14.0 and int(f2.view.mask.sum()) == 15
    assert _rows(f2) == [("R1", "LIMESTONE", 9.5, 14.0, 10)]


def test_one_range_is_its_stretch_named_as_asked():
    from petroharness.agent.selection import resolve
    f2, zones = resolve(_f(), ["7-14"])                         # LOWER's own top and base: LOWER, its depths said (R10)
    assert zones is None and f2.view.selection == "LOWER (7-14 m)" and int(f2.view.mask.sum()) == 15
    assert _rows(f2) == [("R1", "LIMESTONE", 9.5, 14.0, 10)]


def test_a_unit_named_like_a_zone_of_the_focus_loses_to_it_and_is_reached_by_its_depths():
    from petroharness.agent.selection import resolve
    f2, zones = resolve(_f(), ["12-14"])
    assert f2.view.selection == "12-14 m" and int(f2.view.mask.sum()) == 5


def test_two_adjacent_units_are_two_rows_and_their_shared_boundary_is_the_deeper_ones():
    """UPPER 0-7 and LOWER 7-14 share 7.0 m: UPPER keeps 0-6.5 (14 samples), LOWER 7.0-14.0 (15)."""
    from petroharness.agent.selection import resolve
    f2, zones = resolve(_f(), ["UPPER", "LOWER"])
    assert zones is None and f2.view.selection == "UPPER, LOWER"
    assert _rows(f2) == [("R1", "UPPER", 0.0, 6.5, 14), ("R2", "LOWER", 7.0, 14.0, 15)]
    idx = [set(np.asarray(z.indices).tolist()) for z in f2.view.zones]
    assert not (idx[0] & idx[1]) and len(idx[0] | idx[1]) == int(f2.view.mask.sum()) == 29


def test_rows_are_in_depth_order_whatever_the_order_asked():
    from petroharness.agent.selection import resolve
    f2, _ = resolve(_f(), ["LOWER", "UPPER"])
    assert [z.lithology for z in f2.view.zones] == ["UPPER", "LOWER"]


def test_a_focus_zone_with_a_unit_is_two_rows_the_zone_named_as_asked():
    from petroharness.agent.selection import resolve
    f2, _ = resolve(_f(), ["Z1", "LOWER"])
    assert _rows(f2) == [("R1", "Z1", 2.5, 5.0, 6), ("R2", "LOWER", 7.0, 14.0, 15)]


def test_ranges_with_a_gap_between_them_leave_its_samples_outside_any_row():
    from petroharness.agent.selection import resolve
    f2, _ = resolve(_f(), ["0-2", "10-12"])
    assert _rows(f2) == [("R1", "0-2 m", 0.0, 2.0, 5), ("R2", "SAND (10-12 m)", 10.0, 12.0, 5)]   # SAND's own depths
    assert int(f2.view.mask.sum()) == 25 and int(f2.view.zoned.sum()) == 10


def test_nested_units_are_one_stretch_the_union():
    """D2: a selection is the union of what it names; a unit inside another is part of it, and the selection says so
    (overlapping items were refused here while a question's scope merged them)."""
    from petroharness.agent.selection import _picked, _union, resolve
    f, _ = resolve(_f(), ["UPPER", "MID MEMBER"])
    alone, _ = resolve(_f(), ["UPPER"])
    assert int(f.view.mask.sum()) == int(alone.view.mask.sum())             # (UPPER may be the interval itself)
    items, notes = _union(_f(), _picked(_f(), ["UPPER", "MID MEMBER"]))
    assert [it.label for it in items] == ["UPPER"] and notes == ["MID MEMBER 3-5 m is part of UPPER 0-7 m"]


def test_a_unit_with_no_sample_of_the_well_is_refused_with_the_wells_range():
    from petroharness.agent.selection import resolve
    from petroharness.agent.engine import ToolError
    with pytest.raises(ToolError, match=r"FAR 100-200 m: no sample of the well.*from 0 to 14 m"):
        resolve(_f(), ["FAR"])


def test_a_unit_listed_twice_is_refused_with_both_rows():
    from petroharness.agent.selection import resolve
    from petroharness.agent.engine import ToolError
    with pytest.raises(ToolError, match=r"TWICE is listed 2 times.*line 8: 1-2 m.*line 9: 11-12 m.*its depths"):
        resolve(_f(), ["TWICE"])


def test_a_unit_that_ends_at_the_next_top_leaves_out_the_sample_on_it():
    """A unit with no stated base ends at the next top, not included: OPEN 0-7.0 m holds 0-6.5 (14 samples)."""
    from petroharness.agent.selection import Unit, resolve
    f = _f()
    f.view.units = [Unit(name="OPEN", top=0.0, base=7.0, line=2, closed=False)]
    f2, _ = resolve(f, ["OPEN"])
    assert int(f2.view.mask.sum()) == 14 and f2.view.depth[-1] == 6.5


def test_a_row_id_asked_again_is_refused_with_how_to_select_it():
    from petroharness.agent.selection import resolve
    from petroharness.agent.engine import ToolError
    with pytest.raises(ToolError, match=r"R1 is a row of an earlier result.*by its depths"):
        resolve(_f(), ["R1"])


def test_an_unknown_item_is_refused_with_every_kind_on_offer():
    from petroharness.agent.selection import resolve
    from petroharness.agent.engine import ToolError
    with pytest.raises(ToolError) as e:
        resolve(_f(), ["Nowhere Fm."])
    said = str(e.value)
    for part in ("Nowhere Fm.", "Z1", "SHALE", "ALL", "UPPER 0-7 m", "LOWER 7-14 m", "TOP-BASE", "0 to 14 m"):
        assert part in said, (part, said)


def test_units_match_as_the_focus_name_does():
    from petroharness.agent.selection import resolve
    for asked in ("lower", "LOWER", " Lower. ", "lower,"):
        f2, _ = resolve(_f(), [asked])
        assert f2.view.selection == "LOWER", asked


def test_under_reach_focus_only_focus_items_are_taken_refused_as_today():
    from petroharness.agent.selection import resolve
    from petroharness.agent.engine import ToolError
    f = _f(reach="focus")
    assert resolve(f, ["Z1"]) == (f, ["Z1"])
    for asked in (["LOWER"], ["7-14"]):
        with pytest.raises(ToolError, match=r"^no zone .*; zones: Z1; or a lithology: SHALE; or ALL$"):
            resolve(f, asked)


def test_rows_never_take_the_focus_ids():
    from petroharness.agent.selection import resolve
    for asked in (["LOWER"], ["UPPER", "LOWER"], ["Z1", "LOWER"], ["0-14"]):
        f2, _ = resolve(_f(), asked)
        assert f2.view.zones and all(re.fullmatch(r"R\d+", z.zone_id) for z in f2.view.zones), asked


def test_a_selection_never_changes_the_focus():
    from petroharness.agent.selection import resolve
    f = _f()
    before = (f.view.mask.copy(), [(z.zone_id, z.top, z.base) for z in f.view.zones], f.view.selection)
    resolve(f, ["UPPER", "LOWER"])
    resolve(f, ["7-14"])
    assert np.array_equal(f.view.mask, before[0]) and [(z.zone_id, z.top, z.base) for z in f.view.zones] == before[1]
    assert f.view.selection is None


# ---------------------------------------------------------------------------------------------------------------------
# 3. the real pipeline and call door on a synthetic well: 0.5 m samples 1000-1100 m; lithology SAND 1000-1009.5,
# SHALE 1010-1011.5, SAND 1012-1016.5, CROSSBEDDED SAND 1017-1031.5, SHALE 1032-1033, SILT 1033.5-1053,
# LIMESTONE 1053.5-1100. A tops file with a well column (rows of another well too), the focus UPPER FM. 1000-1050.

def _synthetic_well(tmp_dir, reach="well"):
    from _synthetic import plausible_logs, write_las, write_tops
    from _wells import Case, formation_of
    depth = np.arange(1000.0, 1100.0 + 1e-9, 0.5)
    lith = runs_of([(1, 20), (7, 4), (2, 10), (3, 30), (7, 3), (5, 40), (9, 94)])
    logs = plausible_logs(depth, np.isin(lith, (1, 2, 3)))
    logs["LITHOLOGY"] = ("", lith)
    logs["XTRA"] = ("V/V", np.where(depth > 1050.0, 0.25, np.nan))      # a log with values below the focus only
    las = write_las(tmp_dir / "synth-1.las", depth, logs, unit="M", well="SYNTH-1")
    tops = write_tops(tmp_dir / "tops.csv", [
        ("SYNTH-1", "UPPER FM.", 1000.0, 1050.0, "m"), ("SYNTH-1", "LOWER FM.", 1050.0, 1100.0, "m"),
        ("SYNTH-1", "MID MBR.", 1010.0, 1030.0, "m"), ("SYNTH-1", "FAR FM.", 2000.0, 2100.0, "m"),
        ("SYNTH-1", "FT UNIT", 3445.0, 3500.0, "ft"), ("SYNTH-1", "TOP ONLY", 1060.0, None, "m"),
        ("OTHER-9", "OTHER FM.", 1000.0, 1100.0, "m")],
        header=("well", "formation_name", "top_depth", "bottom_depth", "depth_unit"))
    data = () if reach == "well" else (("reach", "focus"),)
    return formation_of(Case(str(las), str(tops), "UPPER FM.", data=data))


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    return _synthetic_well(tmp_path_factory.mktemp("synth"))


def _phie(f, top, base, closed=True):
    """The finite PHIE samples of the well with top <= depth <= base (or < base), from the prepared well's arrays."""
    d = np.asarray(f.view.prep.depth, dtype=float) * f.view.depth_scale
    x = np.asarray(f.view.prep.curve("PHIE"), dtype=float)
    sel = (d >= top) & ((d <= base) if closed else (d < base))
    return x[sel & np.isfinite(x)]


def _line(text: str, start: str) -> str:
    return next(l for l in text.splitlines() if l.strip().startswith(start))


def test_the_units_in_reach_are_this_wells_rows_in_the_reporting_unit(synth):
    got = {u.name: (round(u.top, 4), round(u.base, 4), u.closed) for u in synth.view.units}
    assert got == {"UPPER FM.": (1000.0, 1050.0, True), "LOWER FM.": (1050.0, 1100.0, True),
                   "MID MBR.": (1010.0, 1030.0, True), "FAR FM.": (2000.0, 2100.0, True),
                   "FT UNIT": (round(3445 * 0.3048, 4), round(3500 * 0.3048, 4), True),
                   "TOP ONLY": (1060.0, 2000.0, False)}
    assert synth.view.reach == "well"


def test_stats_of_a_unit_outside_the_focus_reads_its_samples_with_rows_of_its_own(synth):
    from petroharness.agent import schemas
    """LOWER FM. 1050-1100 m: SILT 1050-1053 (3 m: row R1), LIMESTONE 1053.5-1100 (R2); every sample in a row."""
    from petroharness.well.view import fmt
    r = schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["lower fm"]})
    want = _phie(synth, 1050.0, 1100.0)
    assert r.text.splitlines()[0] == ("Selection: LOWER FM. 1050-1100 m, 101 samples; rows R1-R2 are its lithology "
                                      "zones (ids of this result only)")
    pooled = _line(r.text, "rows pooled")
    assert f"n {want.size} of " in pooled and f"mean {fmt(float(want.mean()))}" in pooled
    assert "R1 SILT 1050-1053 m" in r.text and "R2 LIMESTONE 1053.5-1100 m" in r.text
    assert not re.search(r"\bZ\d+\b", r.text)


def test_two_units_are_two_rows_each_counted_on_its_own_samples(synth):
    from petroharness.agent import schemas
    r = schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["UPPER FM.", "LOWER FM."]})
    upper, lower = _phie(synth, 1000.0, 1050.0, closed=False), _phie(synth, 1050.0, 1100.0)
    assert f"n {upper.size} of " in _line(r.text, "R1 UPPER FM.") and f"n {lower.size} of " in _line(r.text, "R2 LOWER FM.")


def test_a_unit_in_feet_on_a_metres_well_is_converted(synth):
    from petroharness.agent import schemas
    r = schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["FT UNIT"]})
    want = _phie(synth, 3445 * 0.3048, 3500 * 0.3048)
    assert r.text.startswith("Selection: FT UNIT 1050.04-1066.8 m, 33 samples;")
    assert want.size == 33 and f"n {want.size} of " in _line(r.text, "rows pooled")


def test_a_unit_ending_at_the_next_top_reaches_to_the_end_of_the_well(synth):
    from petroharness.agent import schemas
    r = schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["TOP ONLY"]})
    assert r.text.startswith("Selection: TOP ONLY 1060-1100 m, 81 samples;")
    assert f"n {_phie(synth, 1060.0, 1100.0).size} of " in _line(r.text, "rows pooled")


def test_nested_units_and_a_unit_outside_the_well_are_refused_at_the_call(synth):
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    r = schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["UPPER FM.", "MID MBR."]})   # one stretch (D2)
    u = schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["UPPER FM."]})
    head = r.text.splitlines()[0]                                             # the same samples as UPPER FM. alone,
    assert head.startswith("Zones as asked:") and re.search(r"MID MBR\. [^;]* is part of UPPER FM\.", head), head   # the merge said
    assert r.text.splitlines()[1:] == u.text.splitlines()
    with pytest.raises(ToolError, match="no sample of the well"):
        schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["FAR FM."]})
    with pytest.raises(ToolError, match="no zone or unit OTHER FM."):
        schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["OTHER FM."]})


def test_focus_zones_at_the_call_are_todays(synth):
    from petroharness.agent import schemas
    z = synth.view.zones[0].zone_id
    a = schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": [z]}).text
    assert a.splitlines()[1].strip().startswith(f"{z} ") and "UPPER FM." not in a.splitlines()[1]


def test_under_reach_focus_a_unit_is_refused_as_today(tmp_path):
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    f = _synthetic_well(tmp_path, reach="focus")
    assert f.view.reach == "focus" and f.view.units == []
    with pytest.raises(ToolError, match=r"^no zone LOWER FM\.; zones: "):
        schemas.call(f, "stats", {"curves": ["PHIE"], "zones": ["LOWER FM."]})


# ---------------------------------------------------------------------------------------------------------------------
# 4. every tool that takes zones, on GeoLink 30/6-5 with its tops file (the focus BRENT GP. 2841-2958 m)

TOOL_ARGS = {
    "stats": {"curves": ["PHIE"]}, "profile": {"curve": "PHIE"}, "runs": {"condition": "PHIE > 0.1"},
    "compare": {"a": "PHIE", "b": "PHIT"}, "crossplot": {"y": "PHIE", "x": "VCL"}, "overlap": {"a": "PHIE", "b": "PHIT"},
    "lithology_stats": {"curves": ["PHIE"]}, "zone_contrast": {"curve": "PHIE"}, "curve_order": {"curves": ["PHIE", "VCL"]},
    "check": {"what": "bad_hole"}, "spike_flags": {"curves": ["GR"]}, "adjacent_jumps": {"curve": "GR", "threshold": 20},
    "threshold_exceedance": {"curve": "VCL", "threshold": 0.5}, "data_record": {}, "lag_correlation": {"curves": ["PHIE", "PHIT"]},
    "estimate": {"parameter": "rw", "method": "rwa"}, "classify": {"what": "gas"}, "unit_roles": {},
    "summarize": {"what": "pay"}, "calibrate": {"what": "porosity"}, "core_vs_log": {},
}
SELECTIONS = {"Dunlin GP. (below the focus)": (["Dunlin GP."], 2958.0, 3223.0),
              "Ness Fm. and Etive Fm. (inside)": (["Ness Fm.", "Etive Fm."], 2841.0, 2958.0),
              "2900-3000 (across the focus base)": (["2900-3000"], 2900.0, 3000.0)}
_DEPTHS = re.compile(r"(?<![\w.])(\d{4}(?:\.\d+)?)(?:\s*[-–]\s*(\d{4}(?:\.\d+)?))?\s*m\b")


def test_every_tool_that_takes_zones_is_in_the_table():
    from petroharness.agent.toolset import TOOLSET
    takes = sorted(t.name for t in TOOLSET if "zones" in (t.arguments() if callable(t.arguments) else t.arguments))
    assert takes == sorted(TOOL_ARGS)


@pytest.fixture(scope="module")
def brent():
    from _wells import CASES, formation_of
    return formation_of(CASES["brent"])


@pytest.mark.parametrize("tool", sorted(TOOL_ARGS))
@pytest.mark.parametrize("what", sorted(SELECTIONS))
def test_every_tool_computes_on_the_selection_or_refuses_with_the_focus_reason(brent, tool, what):
    """Computed: every depth it prints (metres, 2000-4500 m) lies in the selection, and no zone id of the focus
    appears for a selection outside the focus. Refused: only because the tool reads what the workflow computed for the
    focus (selection.FOCUS_ONLY), said so; any other refusal of the selection is a failure."""
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    from petroharness.agent.selection import FOCUS_ONLY
    zones, top, base = SELECTIONS[what]
    try:
        r = schemas.call(brent, tool, {**TOOL_ARGS[tool], "zones": zones})
    except ToolError as e:
        said = str(e)
        if tool in FOCUS_ONLY:
            assert "computed for the focus" in said, (tool, what, said[:300])
        else:                                    # a reason of the data inside the selection, not the selection unread
            assert not re.search(r"no zone|no unit|not a zone|is a row of", said), (tool, what, said[:300])
        return
    assert tool not in FOCUS_ONLY, (tool, "computed although listed as focus-only")
    step = 0.16
    bad = []
    for m in _DEPTHS.finditer(r.text):
        for g in m.groups():
            if g is not None and 2000 <= float(g) <= 4500 and not (top - step <= float(g) <= base + step):
                bad.append(m.group(0))
    assert not bad, (tool, what, bad[:5], r.text[:600])
    if what.startswith("Dunlin"):
        assert not re.search(r"\bZ\d+\b", r.text), (tool, re.findall(r".{40}\bZ\d+\b.{20}", r.text)[:3])
    lines = re.findall(r"^\s*(?:whole interval \(|zones pooled\b|these zones pooled\b|zones whose means meet it).*$",
                       r.text, re.M)
    assert not lines, (tool, what, lines[:2])            # a selection's value lines name it and its rows


def test_calibrate_refuses_the_dunlin_for_its_lack_of_core_plugs_which_is_true(brent):
    """calibrate porosity on Dunlin GP. is refused for fewer than 3 core plugs: counted here from the raw arrays."""
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    d = np.asarray(brent.view.prep.depth, dtype=float) * brent.view.depth_scale
    plugs = brent.view.prep.curve("PHIC")
    inside = (d >= 2958.0) & (d <= 3223.0)
    n = 0 if plugs is None else int(np.isfinite(np.asarray(plugs, dtype=float)[inside]).sum())
    with pytest.raises(ToolError, match="core plugs"):
        schemas.call(brent, "calibrate", {"what": "porosity", "zones": ["Dunlin GP."]})
    assert n < 3, n


def test_a_selection_reads_a_curve_with_data_there_only(synth):
    """XTRA has values below 1050 m only: 100 of LOWER FM.'s 101 samples, none in the focus UPPER FM. (1000-1050)."""
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    assert "XTRA" not in synth.inv.curves                     # no data in the focus: not one of its curves
    r = schemas.call(synth, "stats", {"curves": ["XTRA"], "zones": ["LOWER FM."]})
    assert "n 100 of 101" in _line(r.text, "rows pooled")
    try:
        t = schemas.call(synth, "stats", {"curves": ["XTRA"]}).text
        assert "No data in this interval for: XTRA" in t, t[:300]
    except ToolError as e:
        assert "curves with data" in str(e)


def test_a_selection_has_its_own_gross(synth):
    """A condition true at every sample of 1060-1100 m (40 m; the focus is 50 m) covers 100% of its gross, not a share
    of the focus's."""
    from petroharness.agent import schemas
    t = schemas.call(synth, "runs", {"condition": "GR > 0", "zones": ["1060-1100"]}).text
    head = next(l for l in t.splitlines() if l.startswith("Intervals where GR > 0"))
    assert "(1 interval, " in head and "100.0% of the gross" in head, head


def test_a_curve_written_on_a_selection_is_known_to_the_focus_after(synth):
    from petroharness.agent import schemas
    before = set(synth.inv.curves)
    schemas.call(synth, "classify", {"what": "gas", "zones": ["LOWER FM."]})
    new = set(synth.inv.curves) - before
    assert "GAS_FLAG" in new and "GAS_FLAG" in synth.view.calculated


@pytest.mark.parametrize("line", ["  rows pooled, PHIE: n 101 of 101, mean 0.02",
                                  "  these rows pooled: gross 12",
                                  "  rows whose means meet it (on PHIE; each row by its mean values): R2 (1 of 2 rows)",
                                  "  LOWER FM. 1050-1100 m (0 samples outside any row), PHIE: n 101 of 101",
                                  "  by zone: Z1 1.9 m (43.3% of the zone)", "  by row: R1 2.1 m (50.0% of the row)"])
def test_a_digest_keeps_a_selections_summary_lines(line):
    """The ledger's digest of an earlier result keeps its summary lines first (ledger._P1); a selection's are its own."""
    from petroharness.agent.ledger import _P1
    assert _P1.match(line), line


@pytest.mark.parametrize("asked", ["Brent Group", "brent gp", "Dunlin Group", "Ness Formation", "ETIVE FM"])
def test_a_units_rank_written_out_or_abbreviated_is_the_same_unit(brent, asked):
    """Live (a conversation): the model wrote "Brent Group" for the tops file's "BRENT GP."."""
    from petroharness.agent import selection
    f = brent
    on, _ = selection.resolve(f, [asked], force=True)
    if asked.upper().startswith("BRENT"):                  # the interval's own unit: the interval itself (D2)
        assert on is f
    else:
        assert on is not f and on.view.selection.split()[0].upper() == asked.split()[0].upper(), on.view.selection

