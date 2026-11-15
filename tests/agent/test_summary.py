"""One summary layer (rule G6) under every tool that summarises a curve - each zone, the zones pooled and the whole
interval, always and in that order; the default statistics when none are named, the geometric mean added by the shape
of the data (never the curve's name); rankings by each statistic shown, none called the best; thresholds named with
their source; classes both ways.

    .venv/bin/python -m pytest tests/agent/test_summary.py -q        (PETROHARNESS_DATA selects the dataset)
"""
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.agent.engine import Formation  # noqa: E402
from petroharness.agent.schemas import call  # noqa: E402
from petroharness.well import summary as S  # noqa: E402

DEFAULT = ["n", "mean", "median", "p10", "p90", "min", "max"]


# --- the layer on synthetic values (no data) --------------------------------------------------------------------------

def test_the_shape_rule_adds_the_geometric_mean_by_the_data_alone():
    three, one = np.logspace(0, 3, 200), np.logspace(0, 1, 200)
    assert S.log_shaped(three) and not S.log_shaped(one)
    assert S.names(None, one) == DEFAULT
    assert S.names(None, three) == ["n", "mean", "median", "geo_mean", "p10", "p90", "min", "max"]
    assert not S.log_shaped(np.r_[0.0, three]) and not S.log_shaped(-three)        # positive values only
    assert S.names(["median", "mean"], three) == ["n", "median", "mean"]            # asked: as asked
    got = S.compute(three, ["p10", "p90", "geo_mean"], log=True)
    assert abs(np.log10(got["p10"]) - np.percentile(np.log10(three), 10)) < 1e-9     # percentiles on log10 values
    assert abs(np.log10(got["geo_mean"]) - np.log10(three).mean()) < 1e-9
    assert "orders of magnitude" in S.shape_note(three) and S.shape_note(one) == ""


def test_rankings_show_each_statistic_side_by_side_and_call_none_the_best():
    rows = [("Z1", {"n": 9.0, "mean": 10.0, "median": 1.0}), ("Z2", {"n": 9.0, "mean": 3.0, "median": 3.0}),
            ("Z3", {"n": 9.0, "mean": 2.0, "median": 2.0})]
    hi, lo = S.rankings(rows, ["n", "mean", "median"], lambda v: f"{v:g}")
    assert hi == "highest zone by each statistic: mean Z1 (10); median Z2 (3)"
    assert lo == "lowest zone by each statistic: mean Z3 (2); median Z1 (1)"
    assert "best" not in hi + lo and not re.search(r"(?:: |; )n ", hi + lo)
    tie = S.rankings([("Z1", {"mean": 5.0}), ("Z2", {"mean": 5.0}), ("Z3", {"mean": 1.0})], ["mean"], str)
    assert tie[0].endswith("mean Z1, Z2 (5.0)")                                       # a tie names every zone


def test_a_threshold_says_where_it_came_from():
    assert S.threshold_source(True) == "your threshold"
    assert S.threshold_source(False, "the policy's QC level") == "the workflow's: the policy's QC level"


# --- every summarising tool on a real formation ------------------------------------------------------------------------

@lru_cache(maxsize=1)
def formation():
    from test_b2_tools import F
    need = ("PHIE", "PERM", "GR", "VCL", "DTC")
    hit = [(t, f) for t, f in F() if len(f.view.zones) >= 3 and S.outside(f.view) > 0
           and all(c in f.inv.curves for c in need)]
    if not hit:
        pytest.skip("no formation with three zones, samples between them and PHIE, PERM, GR, VCL, DTC")
    return max(hit, key=lambda x: len(x[1].view.zones))


ZONE = re.compile(r"\bZ\d+\b")
POOLED = re.compile(r"(?:^|, )(?:these )?zones pooled[:|, ]|^all zones:|^zones asked:")
WHOLE = re.compile(r"(?:^|, )whole interval \(\d+ samples outside any zone\)")

SUMMARISING = [("stats", {"curves": ["PHIE"]}), ("stats", {"curves": ["PHIE", "PERM", "GR", "VCL"]}),
               ("stats", {"curves": ["PHIE"], "where": "VCL < 0.3"}), ("profile", {"curve": "PERM"}),
               ("compare", {"a": "PHIE", "b": "VCL"}), ("crossplot", {"y": "PERM", "x": "PHIE", "log_y": True}),
               ("runs", {"condition": "VCL < 0.3"}), ("lithology_stats", {"curves": ["PHIE"]}),
               ("threshold_exceedance", {"curve": "VCL", "threshold": 0.3}),
               ("spike_flags", {"curves": ["GR"]}), ("spike_flags", {"curves": ["GR"], "baseline": "interval"}),
               ("adjacent_jumps", {"curve": "DTC", "threshold": 5})]


def _bases(text: str) -> tuple:
    """(first zone line, first pooled line, first whole-interval line) by line index."""
    lines = [re.sub(r"^[\s-]*", "", ln) for ln in text.splitlines()]
    pooled = next((i for i, ln in enumerate(lines) if POOLED.search(ln)), None)
    whole = next((i for i, ln in enumerate(lines) if WHOLE.search(ln)), None)
    zone = next((i for i, ln in enumerate(lines) if ZONE.search(ln) and i not in (pooled, whole)), None)
    return zone, pooled, whole


@pytest.mark.data
@pytest.mark.parametrize("tool,args", SUMMARISING, ids=[f"{t}-{i}" for i, (t, _) in enumerate(SUMMARISING)])
def test_every_summarising_tool_shows_each_zone_the_zones_pooled_and_the_whole_interval_in_order(tool, args):
    t, f = formation()
    text = call(f, tool, args).text
    zone, pooled, whole = _bases(text)
    assert None not in (zone, pooled, whole) and zone < pooled < whole, (tool, text[:1500])
    k = S.outside(f.view)
    assert f"whole interval ({k} samples outside any zone)" in text


ON_THE_BASIS = ("stats", "profile", "compare", "crossplot", "runs")       # the tools the data's basis setting applies to


@pytest.mark.data
@pytest.mark.parametrize("tool,args", SUMMARISING, ids=[f"{t}-{i}" for i, (t, _) in enumerate(SUMMARISING)])
def test_on_the_zones_basis_the_tools_leave_the_whole_interval_out_and_the_record_s_computations_keep_it(tool, args, monkeypatch):
    """data.basis "zones" (a data file's setting, a benchmark's): stats, profile, compare, crossplot and runs show each
    zone and the zones pooled, with no whole-interval line and no line of the samples outside the zones; the tools
    over the record's own computations give the same text on either basis."""
    f = formation()[1]
    assert f.view.basis == "all"                                # the shared formations: the default basis
    full = call(f, tool, args).text
    monkeypatch.setattr(f.view, "basis", "zones")
    text = call(f, tool, args).text
    if tool not in ON_THE_BASIS:
        assert text == full, tool
        return
    zone, pooled, whole = _bases(text)
    assert None not in (zone, pooled) and zone < pooled and whole is None, (tool, text[:1500])
    assert not [ln for ln in text.splitlines() if ln.lstrip().startswith(("whole interval", "outside any zone"))]
    assert "whole interval" not in text.splitlines()[-1]        # nor named among what a cut text left out


@pytest.mark.data
def test_the_formation_summary_ranks_each_statistic_then_pools_then_the_whole_interval():
    t, f = formation()
    text = call(f, "formation_summary", {"curves": ["PHIE", "PERM"]}).text
    rows = [ln for ln in text.splitlines() if ln.startswith(("  PHIE | ", "  PERM | "))]      # labelled cells
    for ln in rows:
        assert ln.index("each zone, high to low: ") < ln.index("| zones pooled: ") < ln.index("| whole interval ("), ln
    stats = [ln.split(" | ")[1].split(": ", 1)[1] for ln in rows if ln.startswith("  PHIE | ")]
    assert stats == S.names(None, f.view.values("PHIE"))
    assert "best" not in text.lower() and "weakest" not in text.lower()
    mean = next(ln for ln in rows if ln.startswith("  PHIE | statistic: mean | ")).split(" | ")[2]
    vals = [float(v) for v in re.findall(r"Z\d+ (-?[\d.]+(?:e-?\d+)?)", mean)]
    assert vals == sorted(vals, reverse=True)                                       # high to low


def _names(line: str) -> list:
    """The statistic names of a stats/profile line, in order."""
    return [m.group(1) for m in re.finditer(r"(?:^|, )(n|mean|median|geo_mean|p\d+|min|max|std) ", line.split(": ", 1)[1])]


@pytest.mark.data
def test_with_no_statistic_named_the_default_set_by_the_shape_of_the_data():
    t, f = formation()
    for c in ("PHIE", "PERM", "GR"):
        want = S.names(None, f.view.values(c))
        for tool, args in (("stats", {"curves": [c]}), ("profile", {"curve": c})):
            text = call(f, tool, args).text
            line = next(ln for ln in text.splitlines() if re.match(rf"  zones pooled, {c}(?: \([^)]*\))?:", ln))
            assert _names(line) == want, (tool, c, line)
        lith = call(f, "lithology_stats", {"curves": [c]}).text.splitlines()[1]          # a row, its cells labelled
        assert [h.split(" ")[0] for h in lith.split(" | ")[6:]] == want, lith
    asked = call(f, "stats", {"curves": ["PERM"], "statistics": ["median"]}).text
    line = next(ln for ln in asked.splitlines() if re.match(r"  zones pooled, PERM(?: \([^)]*\))?:", ln))
    assert _names(line) == ["n", "median"]


class _Synthetic:
    """A view whose named curves hold given values (the rest as the formation has them)."""

    def __init__(self, view, values: dict):
        self._v, self._x = view, values

    def values(self, c):
        return self._x[c] if c in self._x else self._v.values(c)

    def zone_values(self, z, c):
        return self._x[c][np.asarray(z.indices)] if c in self._x else self._v.zone_values(z, c)

    def __getattr__(self, name):
        return getattr(self._v, name)


@pytest.mark.data
def test_the_shape_rule_is_the_same_whatever_the_curve_s_name():
    t, f = formation()
    n = f.depth.size
    rng = np.random.default_rng(3)
    for decades, geo in ((3.0, True), (1.0, False)):
        x = 10 ** rng.uniform(0, decades, n)
        x[0], x[-1] = 1.0, 10 ** decades
        seen = []
        for name in ("PHIE", "GR", "PERM"):
            g = Formation(f.inv, _Synthetic(f.view, {name: x}), f.store)
            text = call(g, "stats", {"curves": [name]}).text
            line = next(ln for ln in text.splitlines() if ln.startswith("  whole interval ("))
            seen.append(_names(line))
            assert ("geo_mean" in _names(line)) is geo, (name, decades, line)
            label = next(ln for ln in text.splitlines() if ln.startswith(f"{name} "))
            assert ("orders of magnitude" in label) is geo, label
        assert seen[0] == seen[1] == seen[2]


@pytest.mark.data
def test_where_mean_and_median_pick_different_zones_both_rankings_show_and_none_is_the_best():
    t, f = formation()
    zs = f.view.zones
    x = np.full(f.depth.size, np.nan)
    a, b = np.asarray(zs[0].indices), np.asarray(zs[1].indices)
    x[a] = 1.0
    x[a[0]] = 1000.0                                  # one high sample: the highest mean, the lowest median
    x[b] = 5.0
    for z in zs[2:]:
        x[np.asarray(z.indices)] = 3.0
    g = Formation(f.inv, _Synthetic(f.view, {"GR": x}), f.store)
    text = call(g, "profile", {"curve": "GR", "statistics": ["mean", "median"]}).text
    hi = next(ln for ln in text.splitlines() if ln.startswith("  highest zone by each statistic of GR:"))
    lo = next(ln for ln in text.splitlines() if ln.startswith("  lowest zone by each statistic of GR:"))
    assert f"mean {zs[0].zone_id} (" in hi and f"median {zs[1].zone_id} (" in hi, hi
    assert f"median {zs[0].zone_id} (" in lo, lo
    assert "best" not in text.lower() and "strongest" not in text.lower()


@pytest.mark.data
def test_each_threshold_is_named_with_its_source():
    t, f = formation()
    assert "threshold VCL > 0.3 (your threshold)" in call(f, "threshold_exceedance", {"curve": "VCL", "threshold": 0.3}).text
    qc = f.view.policy.get("qc_thresholds") or {}
    for c in [c for c in qc if c in f.inv.curves][:1]:
        assert "(the workflow's: the policy's QC level for" in call(f, "threshold_exceedance", {"curve": c}).text
    head = call(f, "spike_flags", {"curves": ["GR"]}).text.splitlines()[0]
    assert "k: the workflow's deviation rule" in head and "baseline: the workflow's" in head
    head = call(f, "spike_flags", {"curves": ["GR"], "k": 2.5, "baseline": "interval"}).text.splitlines()[0]
    assert "k: yours" in head and "baseline: yours" in head
    assert "(your threshold)" in call(f, "adjacent_jumps", {"curve": "DTC", "threshold": 5}).text
    seq = call(f, "vertical_sequence", {"curves": ["GR"]}).text
    assert "(the workflow's: petrophys stacking_pattern's default" in seq
    assert "(your threshold)" in call(f, "vertical_sequence", {"curves": ["GR"], "min_change": 5}).text


@pytest.mark.data
def test_classes_both_ways_each_zone_then_the_zones_pooled_then_the_whole_interval():
    t, f = formation()
    key = next((s.key for s in f.inv.sections if s.key.startswith("porosity.") and s.classes), None)
    if key is None:
        pytest.skip("no porosity section with classes here")
    text = call(f, "section", {"key": key}).text
    i = text.index("  class views (")
    views = text[i:].splitlines()[1:]
    zone_rows = [ln for ln in views if re.match(r"\s+Z\d+ ", ln)]
    assert len(zone_rows) == len(f.view.zones) and all("samples " in ln for ln in zone_rows)
    assert any("by its mean " in ln for ln in zone_rows)
    pooled = next(k for k, ln in enumerate(views) if ln.strip().startswith("zones pooled:"))
    # the whole interval only where a class is set outside the zones; else what the samples outside hold
    whole = next(k for k, ln in enumerate(views) if WHOLE.search(ln.strip()) or ln.strip().startswith(
        f"outside any zone ({S.outside(f.view)} samples"))
    assert views.index(zone_rows[-1]) < pooled < whole
    assert "by zone mean " in views[pooled] and "of the zone samples" in views[pooled]
    assert "the zone-level reading" not in text
    topic = "porosity_quality"
    zc = call(f, "zone_classes", {"topic": topic}).text
    head = zc.splitlines()[1]
    assert "(zone mean)" in head and "(samples)" in head
    assert re.search(r"\n- \S+, zones pooled: ", zc) and re.search(r"\n- \S+, (whole interval|outside any zone) \(\d+ samples", zc)


@pytest.mark.data
def test_the_workflow_s_flow_roles_pass_through_as_the_workflow_s():
    t, f = formation()
    text = call(f, "unit_roles", {}).text
    assert "role (the workflow's)" in text and "strongest flow interval (highest mean" not in text
    assert "median" not in text                                                    # nothing added to them
    assert "roles as the workflow assigns them (Petrophys flow_roles" in text


@pytest.mark.data
def test_the_first_look_takes_the_default_statistics_and_no_formation_summary():
    from test_b5_loop import Script, chose
    from petroharness.agent.graph import investigate
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.loop import Session
    from petroharness.agent.map import render
    from petroharness.llm import Usage
    t, f = formation()
    s = chose(Session(t, f, render(f.inv), Ledger(f)), "porosity")
    llm = Script([{"asks": "a", "points": [], "intent": "value", "edits": [], "next": [], "done": True}])
    investigate(llm, s, Usage(), 2000, {}, max_steps=1)
    assert s.ledger.items[0].tool == "stats" and "statistics" not in s.ledger.items[0].args
    assert all(e.tool != "formation_summary" for e in s.ledger.items)
    assert "FORMATION SUMMARY" not in llm.sent[0][1][-1]["content"]
