"""Brick 3 of docs/designs/zones-and-intervals.md: the user's zones. A table of zone tops and bottoms (CSV, TSV or
Excel) read by Petrophys as formation tops are (well.user_zones.read_zones), each sample labelled by Petrophys
(label_depths: top <= depth < bottom); the zones frame the question in place of the lithology zones (ids Z1.. with the
user's names, no minimum thickness), the lithology zones kept as L1..; a stretch is framed by them too; `by:
"lithology"` reports a call by the lithology zones; L ids and lithologies select lithology zones; the user's zones are
units in reach by name anywhere in the well. No zones file: nothing changes (tests/test_stretch.py's snapshot).

Parts: reading, typed by hand; a synthetic well through the pipeline with a zones file chosen so every zone is known
(a 1 m zone, a gap, a zone below the focus); GeoLink 30/6-5 with Ness Fm. and Etive Fm. as the user's zones, against
the raw arrays.

    .venv/bin/python -m pytest tests/test_user_zones.py -q -n 4
"""
import re

import numpy as np
import pandas as pd
import pytest

from _synthetic import plausible_logs, runs_of, write_las, write_tops
from _wells import CASES, Case, formation_of

# ---------------------------------------------------------------------------------------------------------------------
# 1. reading

def _csv(tmp_path, rows, header=("zone", "top", "bottom"), name="zones.csv"):
    p = tmp_path / name
    p.write_text("\n".join([",".join(header)] + [",".join("" if v is None else str(v) for v in r) for r in rows]) + "\n")
    return p


def test_a_csv_of_zones_is_read_in_depth_order(tmp_path):
    from petroharness.well.user_zones import read_zones
    got = read_zones(_csv(tmp_path, [("Lower", 20, 30), ("Upper", 10, 20)]))
    assert [(z["name"], z["top"], z["base"], z["unit"], z["closed"]) for z in got] == [
        ("Upper", 10.0, 20.0, None, False), ("Lower", 20.0, 30.0, None, False)]


def test_an_excel_sheet_of_zones_is_read(tmp_path):
    from petroharness.well.user_zones import read_zones
    p = tmp_path / "zones.xlsx"
    with pd.ExcelWriter(p) as w:
        pd.DataFrame({"name": ["Other"], "from": [1.0], "to": [2.0]}).to_excel(w, sheet_name="First", index=False)
        pd.DataFrame({"zone_name": ["A", "B"], "top": [100.0, 110.0], "base": [110.0, 125.0]}).to_excel(
            w, sheet_name="Zones", index=False)
    got = read_zones(p, sheet="Zones")
    assert [(z["name"], z["top"], z["base"]) for z in got] == [("A", 100.0, 110.0), ("B", 110.0, 125.0)]


def test_a_table_of_several_wells_gives_this_wells_rows(tmp_path):
    from petroharness.well.user_zones import read_zones
    p = _csv(tmp_path, [("A-1", "Upper", 10, 20), ("B-2", "Other", 5, 50), ("A-1", "Lower", 20, 30)],
             header=("well", "zone", "top", "bottom"))
    assert [z["name"] for z in read_zones(p, ["x", "A-1"])] == ["Upper", "Lower"]
    with pytest.raises(ValueError, match=r"lists several wells .*none of them this well \(C-3\).*well column"):
        read_zones(p, ["C-3"])


def test_tops_only_are_refused_with_the_fix(tmp_path):
    from petroharness.well.user_zones import read_zones
    with pytest.raises(ValueError, match=r"gives tops only.*add a bottom column.*\(--tops\)"):
        read_zones(_csv(tmp_path, [("Upper", 10), ("Lower", 20)], header=("zone", "top")))


def test_a_depth_unit_column_is_read_and_a_wrong_one_refused(tmp_path):
    from petroharness.well.user_zones import read_zones
    got = read_zones(_csv(tmp_path, [("Upper", 10, 20, "ft")], header=("zone", "top", "bottom", "depth_unit")))
    assert got[0]["unit"] == "ft"
    with pytest.raises(ValueError, match="depth unit"):
        read_zones(_csv(tmp_path, [("Upper", 10, 20, "km")], header=("zone", "top", "bottom", "depth_unit"),
                        name="bad.csv"))


def test_a_missing_file_is_said(tmp_path):
    from petroharness.well.user_zones import read_zones
    with pytest.raises(FileNotFoundError, match="no zones file"):
        read_zones(tmp_path / "nowhere.csv")


# ---------------------------------------------------------------------------------------------------------------------
# 2. a synthetic well: 0.5 m samples 1000-1100 m; lithology SAND 1000-1009.5, SHALE 1010-1011.5, SAND 1012-1016.5,
# CROSSBEDDED SAND 1017-1031.5, SHALE 1032-1033, SILT 1033.5-1053, LIMESTONE 1053.5-1100; the focus UPPER FM.
# 1000-1050 m (stated base, 101 samples). The user's zones: Upper reservoir 1000-1012, Seal 1012-1013 (1 m),
# Lower reservoir 1013-1040, Deep zone 1060-1090 (below the focus); 1040-1050 in no zone.

ZONES = [("Upper reservoir", 1000, 1012), ("Seal", 1012, 1013), ("Lower reservoir", 1013, 1040),
         ("Deep zone", 1060, 1090)]


def _well(tmp_dir, zones=ZONES):
    depth = np.arange(1000.0, 1100.0 + 1e-9, 0.5)
    lith = runs_of([(1, 20), (7, 4), (2, 10), (3, 30), (7, 3), (5, 40), (9, 94)])
    logs = plausible_logs(depth, np.isin(lith, (1, 2, 3)))
    logs["LITHOLOGY"] = ("", lith)
    las = write_las(tmp_dir / "synth-z.las", depth, logs, unit="M", well="SYNTH-Z")
    tops = write_tops(tmp_dir / "tops.csv", [("UPPER FM.", 1000.0, 1050.0, "m"), ("LOWER FM.", 1050.0, 1100.0, "m")])
    zf = _csv(tmp_dir, zones)
    return formation_of(Case(str(las), str(tops), "UPPER FM.", zones=str(zf)))


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    return _well(tmp_path_factory.mktemp("uz"))


def _rows(f):
    return [(z.zone_id, z.lithology, z.top, z.base, z.n_samples) for z in f.view.zones]


def _phie(f, top, base, closed=False):
    d = np.asarray(f.view.prep.depth, dtype=float) * f.view.depth_scale
    x = np.asarray(f.view.prep.curve("PHIE"), dtype=float)
    sel = (d >= top) & ((d <= base) if closed else (d < base))
    return x[sel & np.isfinite(x)]


def test_the_users_zones_frame_the_focus(synth):
    assert _rows(synth) == [("Z1", "Upper reservoir", 1000.0, 1011.5, 24), ("Z2", "Seal", 1012.0, 1012.5, 2),
                            ("Z3", "Lower reservoir", 1013.0, 1039.5, 54)]
    assert int(synth.view.mask.sum()) == 101 and int(synth.view.zoned.sum()) == 80     # 1040-1050: no zone


def test_the_lithology_zones_are_kept_as_l_ids(synth):
    assert [(z.zone_id, z.lithology, z.top, z.base) for z in synth.view.lithology_zones] == [
        ("L1", "SAND", 1000.0, 1009.5), ("L2", "SAND", 1012.0, 1016.5), ("L3", "CROSSBEDDED SAND", 1017.0, 1031.5),
        ("L4", "SILT", 1033.5, 1050.0)]


def test_stats_report_by_the_users_zones_against_the_raw_arrays(synth):
    from petroharness.agent import schemas
    t = schemas.call(synth, "stats", {"curves": ["PHIE"]}).text
    for zid, name, top, base in (("Z1", "Upper reservoir", 1000, 1012), ("Z2", "Seal", 1012, 1013),
                                 ("Z3", "Lower reservoir", 1013, 1040)):
        line = next(l for l in t.splitlines() if l.strip().startswith(f"{zid} {name} "))
        want = _phie(synth, top, base)
        assert f"n {want.size} of " in line, (line, want.size)


def test_the_map_names_the_users_zones_and_the_lithology_zones(synth):
    from petroharness.agent.map import render
    text = render(synth.inv)
    assert re.search(r"^Zones: 3, your zones from zones\.csv, covering ", text, re.M)
    lz = next(l for l in text.splitlines() if l.startswith("  Lithology zones (4; "))
    assert "L1 SAND 1000-1009.5 m" in lz and "L4 SILT 1033.5-1050 m" in lz and '"by": "lithology"' in lz
    assert "Z2 Seal 1012-1012.5 m" in text
    assert "the zone's lithology is the formation's" not in text      # the zones are the user's, not the formation's


def test_a_users_zone_below_the_focus_is_reached_by_its_name(synth):
    from petroharness.agent import schemas
    r = schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["deep zone"]})
    assert r.text.startswith("Selection: Deep zone 1060-1090 m, 60 samples; row R1 is your zones within it")
    assert f"n {_phie(synth, 1060, 1090).size} of " in next(l for l in r.text.splitlines() if l.strip().startswith("R1 Deep zone"))


def test_a_depth_range_is_framed_by_the_users_zones_cut_to_it(synth):
    from petroharness.agent import schemas
    r = schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["1000-1020"]})
    rows = re.findall(r"^  (R\d) (.+?) ([\d.]+)-([\d.]+) m, PHIE", r.text, re.M)
    assert [(a, b, float(c), float(d)) for a, b, c, d in rows] == [
        ("R1", "Upper reservoir", 1000.0, 1011.5), ("R2", "Seal", 1012.0, 1012.5), ("R3", "Lower reservoir", 1013.0, 1020.0)]
    assert "rows R1-R3 are your zones within it" in r.text.splitlines()[0]


def test_a_lithology_selects_the_lithology_zones_under_the_users(synth):
    from petroharness.agent import schemas
    r = schemas.call(synth, "stats", {"curves": ["PHIE"], "zones": ["SAND"]})
    rows = re.findall(r"^  (R\d) (L\d) ([\d.]+)-([\d.]+) m, PHIE", r.text, re.M)
    assert [(a, b) for a, b, *_ in rows] == [("R1", "L1"), ("R2", "L2")]


def test_by_lithology_reports_by_the_lithology_zones(synth):
    from petroharness.agent import schemas
    t = schemas.call(synth, "stats", {"curves": ["PHIE"], "by": "lithology"}).text
    ids = re.findall(r"^  (L\d) ([A-Z ]+?) [\d.]+-[\d.]+ m, PHIE", t, re.M)
    assert [i for i, _ in ids] == ["L1", "L2", "L3", "L4"] and not re.search(r"^  Z\d ", t, re.M)
    with pytest.raises(Exception, match=r"by takes \"lithology\""):
        schemas.call(synth, "stats", {"curves": ["PHIE"], "by": "facies"})


def test_a_curve_written_under_by_lithology_is_known_to_the_question_after(synth):
    from petroharness.agent import schemas
    schemas.call(synth, "classify", {"what": "gas", "by": "lithology"})
    assert "GAS_FLAG" in synth.inv.curves


def test_by_lithology_without_the_users_zones_is_the_call_as_asked(tmp_path):
    from petroharness.agent import schemas
    f = formation_of(CASES["brent"])
    a = schemas.call(f, "stats", {"curves": ["PHIE"]}).text
    assert schemas.call(f, "stats", {"curves": ["PHIE"], "by": "lithology"}).text == a


def test_overlapping_zones_are_refused_with_the_fix(tmp_path):
    with pytest.raises(ValueError, match=r"zones of the zones file overlap.*do not overlap"):
        _well(tmp_path, zones=[("A", 1000, 1020), ("B", 1010, 1030)])


# ---------------------------------------------------------------------------------------------------------------------
# 3. GeoLink 30/6-5, Brent Group, with Ness Fm. and Etive Fm. as the user's zones

@pytest.fixture(scope="module")
def brent_zoned(tmp_path_factory):
    p = _csv(tmp_path_factory.mktemp("bz"), [("Ness", 2841.0, 2865.0), ("Etive", 2865.0, 2958.0)])
    return formation_of(Case("30/6-5", "formations_30_6-5.csv", "BRENT GP.", zones=str(p)))


def test_brent_framed_by_ness_and_etive_reads_each_on_its_own_samples(brent_zoned):
    from petroharness.agent import schemas
    from petroharness.well.view import fmt
    assert [(z.zone_id, z.lithology) for z in brent_zoned.view.zones] == [("Z1", "Ness"), ("Z2", "Etive")]
    t = schemas.call(brent_zoned, "stats", {"curves": ["PHIE"]}).text
    for name, top, base in (("Ness", 2841.0, 2865.0), ("Etive", 2865.0, 2958.0)):
        line = next(l for l in t.splitlines() if re.match(rf"^  Z\d {name} ", l))
        want = _phie(brent_zoned, top, base)
        assert f"n {want.size} of " in line and f"mean {fmt(float(want.mean()))}" in line, line
    assert len(brent_zoned.view.lithology_zones) == 20


# ---------------------------------------------------------------------------------------------------------------------
# 4. the way in: the command line, ask's prepare, a conversation's inputs

def test_the_command_line_takes_a_zones_file_and_its_sheet():
    from petroharness.ask import options, parser
    args = parser().parse_args(["--las", "w.las", "--question", "q", "--zones", "z.xlsx", "--zones-sheet", "Zones"])
    kw = options(args)
    assert str(kw["zones"]) == "z.xlsx" and kw["zones_sheet"] == "Zones"
    from petroharness.session.chat import parser as chat_parser
    a = chat_parser().parse_args(["--las", "w.las", "--zones", "z.csv"])
    assert str(a.zones) == "z.csv" and a.zones_sheet is None


def test_prepare_reads_the_zones_file_into_the_data_settings(tmp_path):
    import petroharness.ask as A
    from _wells import sample
    p = _csv(tmp_path, [("Ness", 2841.0, 2865.0), ("Etive", 2865.0, 2958.0)])
    got = A.prepare(sample("30/6-5"), "k", formation="BRENT GP.", tops=sample("formations_30_6-5.csv"), zones=p,
                    cache=tmp_path / ".cache")
    assert [z["name"] for z in got.data["zones"]] == ["Ness", "Etive"] and got.data["zones_source"] == "zones.csv"


def test_a_conversation_keeps_its_zones_file_among_its_inputs():
    from petroharness.session.conversation import INPUTS
    assert "zones" in INPUTS and "zones_sheet" in INPUTS


def test_a_call_by_lithology_is_not_served_the_same_call_by_the_users_zones(synth):
    """The ledger keys a call by what it computes: "by" changes the zones it reports by."""
    from petroharness.agent.ledger import Ledger
    led = Ledger(synth)
    a, _ = led.open("stats", {"curves": ["PHIE"]})
    b, new = led.open("stats", {"curves": ["PHIE"], "by": "lithology"})
    assert new and a.id != b.id and re.search(r"^  L1 ", b.text, re.M) and not re.search(r"^  L1 ", a.text, re.M)
