"""What the tools show.

1. Classes as located runs: each class with its criterion inline, its runs top to base zone by zone, thickness and share
   last, no noise note; a class with few runs listed in full; a cut list says so and gives the exact get.
2. Self-describing lines: the basis (each zone, the zones pooled, the whole interval only where samples outside the zones
   add to it, followed by what those samples hold; never a rock-type row or unit of their own), n of N, the direction
   with depth in words, and the status the record knows (measured, model output, parameter, uncalibrated, quicklook or
   fallback input, not computed), from the record and the catalog, never from a curve's name.
3. The overlap tool (A and B, A without B, B without A per zone, with runs); compare and crossplot lead with the zone
   level and label each coefficient with its n, ranges and transform.
4. The guides: an answer-shape line beside each area guide's criteria, recipes that say what each tool computes.

On synthetic values and on real formations of every dataset configured beside the data config (GeoLink, Costa, Danish).

    PYTHONPATH=src python -m pytest tests/agent/test_tool_lines.py -q        (PETROHARNESS_DATA selects the main dataset)
"""
import copy
import dataclasses
import re
import sys
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(Path(__file__).resolve().parent)]
from petroharness.agent import engine as E  # noqa: E402
from petroharness.agent import tools as T  # noqa: E402
from petroharness.agent.engine import Formation, ToolError  # noqa: E402
from petroharness.agent.inventory import criteria  # noqa: E402
from petroharness.agent.ledger import Ledger  # noqa: E402
from petroharness.agent.schemas import call, fit  # noqa: E402
from petroharness.well import summary as S  # noqa: E402

PER_DATASET = 10                 # formations read per dataset (the first ones of its question file, each once)


def _configs() -> list:
    from test_b4_direction import _dataset_configs
    return _dataset_configs()


@lru_cache(maxsize=None)
def formations(path: str) -> list:
    """The first PER_DATASET formations of a dataset config, built as the harness builds them, on the default reporting
    settings (every basis, no conventions, whatever the data file sets: test_b0_inventory.default_reporting)."""
    from petroharness.agent.inventory import from_view
    from petroharness.config import DataPaths, EvalPaths, HarnessConfig
    from petroharness.record.store import build as build_store
    from petroharness.tasks import load_tasks
    from petroharness.well.view import FormationView
    d = yaml.safe_load(Path(path).read_text())
    cfg = HarnessConfig(data=DataPaths(**{**d["data"], "basis": "all", "conventions": []}), eval=EvalPaths(**d["eval"]))
    tasks, _ = load_tasks(cfg.eval.questions, cfg.data.las_dir)
    out, seen = [], set()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for t in tasks:
            k = (str(t.las_path), t.formation)
            if k in seen:
                continue
            seen.add(k)
            v = FormationView.build(t, cfg.for_tasks())
            s = build_store(v)
            out.append((t, Formation(from_view(v, s), v, s)))
            if len(out) >= PER_DATASET:
                break
    return out


def every() -> list:
    return [(Path(p).stem, t, f) for p in _configs() for t, f in formations(str(p))]


DATASETS = pytest.mark.parametrize("config", _configs(), ids=lambda p: p.stem)


# --- 1. classes as located runs -----------------------------------------------------------------------------------------

def test_criteria_are_read_from_each_part_of_a_thresholds_line():
    """'NAME: rule; NAME: rule' gives each class its own rule (the first rule never swallows the rest); bands keep
    their reading; a rule in words that is one part of a longer rule stays on the recorded line."""
    raw = ("POTENTIAL_CONTACT_ZONE: dSw > 0.2 and dPHIT < 0.05; TRANSITION_ZONE: dSw > 0.1 and dPHIT < 0.05; "
           "STABLE_HC_ZONE: SW < 0.4; STABLE_WATER_ZONE: SW > 0.6.")
    got = criteria(raw, ["STABLE_HC_ZONE", "TRANSITION_ZONE", "POTENTIAL_CONTACT_ZONE", "STABLE_WATER_ZONE"])
    assert got == {"POTENTIAL_CONTACT_ZONE": "dSw > 0.2 and dPHIT < 0.05", "TRANSITION_ZONE": "dSw > 0.1 and dPHIT < 0.05",
                   "STABLE_HC_ZONE": "SW < 0.4", "STABLE_WATER_ZONE": "SW > 0.6"}
    raw = "POTENTIAL_PAY: existing pay flag > 0.5. MOVABLE_HC: MHI < 0.7 and SW < 0.60. LOW_SW: SW < 0.50."
    assert criteria(raw, ["LOW_SW", "POTENTIAL_PAY"]) == {"POTENTIAL_PAY": "existing pay flag > 0.5", "LOW_SW": "SW < 0.50"}
    assert criteria("EXCELLENT < 0.20; GOOD 0.20-0.40", ["EXCELLENT_POROSITY", "GOOD_POROSITY"]) == \
        {"EXCELLENT_POROSITY": "EXCELLENT < 0.20", "GOOD_POROSITY": "GOOD 0.20-0.40"}
    assert criteria("Quality base: FAIR when selected porosity >0.05, GOOD when >0.10.", ["GOOD_RESERVOIR"]) == {}


def _class_line(text: str, name: str) -> str:
    return next(ln for ln in text.splitlines() if ln.startswith(f"  {name}: "))


def _cells(line: str) -> list:
    """The depths of a class line's runs, in the order shown: [(zone, top, base)] (a cut list's thickest runs: their
    thickness and the condition of every run left out)."""
    body = re.sub(r"^thickest \d+ of \d+: ", "", line.split("; runs: ", 1)[1])
    body = re.sub(r" \.\.\. \(every run: condition [^)]*\)$", "", body)
    out = []
    for part in body.split("; "):
        m = re.match(r"^(Z\d+)(?: \([^)]*\))? (.*)$", part)          # each zone with its rock
        if not m:
            break
        for cell in m.group(2).split(", "):
            a, _, b = re.sub(r" \([^)]*\)$", "", cell).partition("-")
            out.append((m.group(1), float(a), float(b or a)))
    return out


def _size_line(text: str, name: str) -> str:
    return next(ln for ln in text.splitlines() if ln.startswith(f"    {name} in all: "))


@pytest.mark.data
@DATASETS
def test_a_class_is_its_runs_top_to_base_with_its_criterion_and_its_size_last(config):
    """Every class of every section: its criterion inline where the record defines one, its runs top to base zone by
    zone (every run when it has few, matched to the analyzer store), its thickness and share last; no noise note."""
    small = 0
    for t, f in formations(str(config)):
        for s in f.inv.sections:
            text = T.section(f, s.key).text
            assert "single sample" not in text and "noise" not in text, (t.well, s.key)
            lines = text.splitlines()
            for c in s.classes:
                ln = _class_line(text, c.name)                       # it starts with its label
                if c.definition:
                    assert ln.startswith(f"  {c.name}: criterion {c.definition}; "), (t.well, ln[:200])
                if c.thickness is not None and c.share_pct is not None:  # its size last, on the line after it
                    assert lines[lines.index(ln) + 1] == (f"    {c.name} in all: {E.num(c.thickness)} {f.inv.depth_unit}, "
                                                         f"{c.share_pct}% of the zoned thickness"), (t.well, ln[-120:])
                runs = T._store_runs(f, s.key, c.name)
                if not runs:
                    continue
                shown = _cells(ln)
                tops = [a for _, a, _ in shown]
                assert tops == sorted(tops), (t.well, s.key, c.name)                      # top to base
                assert f" {len(runs)} {'run' if len(runs) == 1 else 'runs'}, top to base; runs: " in ln
                if len(runs) <= T.FULL_RUNS:                                               # few: every run, as stored
                    small += 1
                    assert [(z, round(a, 3), round(b, 3)) for z, a, b in shown] == \
                        [(z, round(a, 3), round(b, 3)) for z, a, b in sorted(runs, key=lambda r: (r[1], r[2]))], \
                        (t.well, s.key, c.name, ln[:300])
    assert small


@pytest.mark.data
def test_a_small_class_reads_as_located_runs_not_as_noise():
    """A class of three runs (two of them one sample) is shown as its three depths beside its
    criterion, not as a share with a single-sample note; a section with few runs lists every run top to base."""
    for name, t, f in every():
        for s in f.inv.sections:
            for c in s.classes:
                runs = T._store_runs(f, s.key, c.name)
                single = [r for r in runs if r[1] == r[2]]
                if 2 <= len(runs) <= T.FULL_RUNS and single and c.definition and not c.background:
                    text = T.section(f, s.key).text
                    ln = _class_line(text, c.name)
                    for z, a, b in runs:
                        assert T._depth_cell(f, a, b) in ln, (name, t.well, ln[:300])
                    assert ln.index("criterion") < ln.index("; runs: ") and "single sample" not in text
                    assert text.index(ln) < text.index(_size_line(text, c.name))       # the size after the runs
                    return
    pytest.skip("no small class with a one-sample run and a criterion")


@pytest.mark.data
def test_a_cut_run_list_says_so_and_its_runs_call_lists_every_run():
    """A class with more runs than fit: its thickest runs in depth order, each with its thickness, the line saying how
    many of how many ("thickest k of N: ...") and ending with the condition that lists every run ("... (every run:
    condition KEY:NAME)"); that runs call counts every run. Never cut silently."""
    done = 0
    for name, t, f in every():
        for s in f.inv.sections:
            for c in s.classes:
                runs = T._store_runs(f, s.key, c.name)
                if len(runs) <= T.FULL_RUNS:
                    continue
                ln = _class_line(T.section(f, s.key).text, c.name)
                m = re.search(rf"; runs: thickest (\d+) of (\d+): .* \.\.\. \(every run: condition ([^)]*)\)$", ln)
                if not m:
                    assert _cells(ln) and len(_cells(ln)) == len(runs), ln[:300]       # not cut: every run
                    continue
                assert int(m.group(2)) == len(runs) and m.group(3) == f"{s.key}:{c.name}", ln[-200:]
                shown = _cells(ln)
                assert len(shown) == int(m.group(1)) and [a for _, a, _ in shown] == sorted(a for _, a, _ in shown)
                step = float(f.view.step)
                thick = sorted((b - a + step for _, a, b in runs), reverse=True)[:len(shown)]
                assert sorted((b - a + step for _, a, b in shown), reverse=True) == pytest.approx(thick, abs=1e-6)
                listed = T.runs(f, m.group(3)).text                                     # the runs call: every run
                assert re.search(rf"\({len(runs)} runs\)", listed.splitlines()[0]), listed.splitlines()[0]
                done += 1
                if done >= 4:
                    return
    if not done:
        pytest.skip("no cut run list")


def test_the_ledger_s_run_reader_reads_the_located_runs():
    """The ledger's run reader (ledger._class_runs) reads the section tool's class lines: each run's zone is found,
    written or from its depth; "none in Zn" only where the list is whole; a cut list says it is cut and names the runs
    call of every run."""
    from petroharness.agent import ledger
    reader = ledger._class_runs
    zone_at = {1000.0: "Z1", 1000.5: "Z1", 1002.0: "Z1", 1010.0: "Z2", 1010.5: "Z2", 1020.0: "Z3"}.get
    whole = "  NAME: criterion X > 1; 4 runs, top to base; runs: Z1 1000.0, 1002.0; Z2 1010.0-1010.5; Z3 1020.0"
    assert reader(whole, {"Z2"}, zone_at).endswith("runs: Z2 1010.0-1010.5")
    assert reader(whole, {"Z1"}, zone_at).endswith("runs: Z1 1000.0, 1002.0")       # 1002.0: its zone from its depth
    assert reader(whole, {"Z4"}, zone_at).endswith("runs: none in Z4")                # whole: none, said
    cut = ("  NAME: 30 runs, top to base; runs: thickest 2 of 30: Z1 1000.0-1000.5 (1 m); Z2 1010.0-1010.5 (1 m) ... "
           "(every run: condition fam.sec:NAME)")
    assert "Z2 1010.0-1010.5 (1 m)" in reader(cut, {"Z2"}, zone_at) and "the list is cut" in reader(cut, {"Z2"}, zone_at)
    got = reader(cut, {"Z3"}, zone_at)
    assert "none in" not in got and "not listed here for Z3" in got and "runs fam.sec:NAME" in got


@pytest.mark.data
def test_real_class_lines_read_by_the_run_reader():
    """On real sections of every dataset: the run reader finds the zone of every run of every whole list (no run left
    unread), and says "none in" only for a whole list."""
    from petroharness.agent import ledger
    reader = ledger._class_runs
    seen = 0
    for name, t, f in every():
        zone_at = lambda d, f=f: E.zone_at(f, d)
        for s in f.inv.sections[:12]:
            text = T.section(f, s.key).text
            for c in s.classes:
                runs = T._store_runs(f, s.key, c.name)
                if not runs:
                    continue
                ln = _class_line(text, c.name)
                cut = "thickest " in ln.split("; runs: ", 1)[1][:20]
                for z in f.view.zones[:4]:
                    got = reader(ln, {z.zone_id}, zone_at)
                    mine = [r for r in runs if r[0] == z.zone_id]
                    assert "do not name their zone" not in got, got[-200:]
                    if not cut:
                        assert ("none in" in got) == (not mine), (name, got[-200:])
                        for _, a, b in mine:
                            assert T._depth_cell(f, a, b) in got.split("; runs: ", 1)[1], (name, got[-200:])
                    else:
                        assert "none in" not in got, got[-200:]
                    seen += 1
    if not seen:
        pytest.skip("no formation with analyzer classes: the data configs are not available")
    assert seen > 50


def test_kept_rows_are_out_of_the_text_and_out_of_the_cut_line():
    from petroharness.agent.engine import Out

    class F:
        class inv:
            depth_unit = "m"
    out = Out(F)
    out.add("shown line")
    out.keep("  NAME runs in Z1: 1, 2")
    r = out.result()
    assert r.text == "shown line" and any("NAME runs in Z1" in ln for ln, _ in r.rows)


# --- 2. self-describing lines -------------------------------------------------------------------------------------------

def _outside_formation():
    for name, t, f in every():
        if S.outside(f.view) > 0 and len(f.view.zones) >= 2 and "GR" in f.inv.curves:
            return t, f
    pytest.skip("no formation with samples outside its zones")


@pytest.mark.data
def test_the_whole_interval_only_where_it_differs_then_what_the_outside_samples_hold():
    """stats: the whole interval only where a sample outside the zones has a value, followed by the outside samples'
    own line, labelled as runs no thicker than the zone minimum and not a zone; with no value outside the zones (a
    selection inside them), no whole-interval line at all."""
    t, f = _outside_formation()
    text = T.stats(f, ["GR"]).text
    lines = text.splitlines()
    k = S.outside(f.view)
    w = next(i for i, ln in enumerate(lines) if ln.startswith(f"  whole interval ({k} samples outside any zone), GR"))
    o = lines[w + 1]
    assert o.startswith(f"  outside any zone ({k} samples; not a zone), GR: "), o
    assert "mean " in o and "median" not in o and "(between zones)" not in o          # what they hold, briefly
    run = T.runs(f, "GR > 0").text                                                  # the label in full, once a result
    assert f"outside any zone ({k} samples, " in run and "zone minimum" in run and "not a zone" in run
    x = np.asarray(f.view.values("GR"), dtype=float)[S.outside_mask(f.view)]
    assert f"n {int(np.isfinite(x).sum())} of {k}" in o
    zone = f.view.zones[0].zone_id
    inside = T.stats(f, ["GR"], where=zone).text                       # the samples of one zone: none outside
    assert "whole interval" not in inside and "outside any zone" not in inside, inside


@pytest.mark.data
def test_a_class_found_only_outside_the_zones_is_never_a_unit():
    """lithology_stats: a rock type with no zone is not a row; the samples outside the zones are one labelled line
    that names it. stats of class codes: a class only outside the zones is said so in the whole-interval line."""
    for name, t, f in every():
        lab = np.asarray(f.view.labels)
        away = S.outside_mask(f.view)
        zoned = {z.lithology for z in f.view.zones}
        only = sorted({str(x) for x in lab[away].tolist()} - zoned - {"NO_LITHOLOGY_DATA"})
        if not only:
            continue
        text = call(f, "lithology_stats", {"curves": ["GR"] if "GR" in f.inv.curves else [next(iter(f.inv.curves))]}).text
        rows = [ln.split(" | ")[0].strip() for ln in text.splitlines()[1:] if " | " in ln]
        assert not set(only) & set(rows), (t.well, only, rows)
        fact = next(ln for ln in text.splitlines() if ln.startswith("- outside any zone ("))
        for lith in only:
            assert f"{lith} " in fact and "no zone of this rock type" in fact, fact
        log = f.view.lithology_curve
        if log and log in f.inv.curves and E.kind(f, log).kind == "classes":
            whole = next(ln for ln in T.stats(f, [log]).text.splitlines() if ln.startswith("  whole interval ("))
            assert "only outside the zones" in whole, whole
        return
    pytest.skip("no rock type found only outside the zones")


@pytest.mark.data
@DATASETS
def test_every_value_line_says_n_of_n(config):
    """stats, compare and crossplot rows give n of N (the group's samples)."""
    for t, f in formations(str(config))[:3]:
        have = [c for c in ("PHIE", "GR", "VCL", "RHOB", "NPHI", "SW") if c in f.inv.curves and E.kind(f, c).kind == "values"]
        if len(have) < 2:
            continue
        a, b = have[:2]
        for text in (T.compare(f, a, b).text, T.crossplot(f, a, b).text):
            rows = [ln for ln in text.splitlines() if re.match(r"^  (Z\d+ |zones pooled|whole interval|outside any zone)", ln)]
            assert rows and all(re.search(r"\bn \d+ of \d+\b", ln) for ln in rows), text[:600]


@pytest.mark.data
def test_direction_with_depth_is_said_in_words():
    """profile: each statistic's rank correlation with depth carries 'higher upward' (negative) or 'higher
    downward' (positive) where at least five zones give the order (summary.ORDER_MIN_ZONES), with the legend of the
    signs; over fewer zones it carries the number, the count of zones and that an order cannot be told from chance,
    with no direction words and no legend. crossplot on DEPTH: each fit says its direction."""
    seen = set()
    for name, t, f in every():
        if len(f.view.zones) < 3 or "GR" not in f.inv.curves:
            continue
        line = next((ln for ln in T.profile(f, "GR").text.splitlines() if ln.startswith("  with depth (")), None)
        if not line:
            continue
        head, cells = line.split("): ", 1)
        k = int(re.search(r" over (\d+) zones", head).group(1))
        cells = re.findall(r"(\w+) (-?[\d.]+) \(([^()]*)\)", cells)
        assert cells, line
        told = 0
        for s, v, words in cells:
            few = re.fullmatch(r"(\d+) zones: too few to tell an order from chance; at least 5 are needed", words)
            if few:                                                 # this statistic's zones: fewer than five
                assert 3 <= int(few.group(1)) <= min(k, S.ORDER_MIN_ZONES - 1), line
            else:
                told += 1
                assert words == ("higher upward" if float(v) < 0 else "higher downward" if float(v) > 0 else
                                 "no order with depth"), line
        if k < S.ORDER_MIN_ZONES:                                   # too few zones: no direction, no legend
            assert not told and "higher" not in line and "positive:" not in head, line
        else:
            assert head.endswith(f" over {k} zones; positive: higher deeper, negative: higher upward"), line
            assert re.search(r"\((higher (upward|downward)|no order with depth)\)", line), line
        rows = [ln for ln in T.crossplot(f, "GR", "DEPTH").text.splitlines() if ", GR on DEPTH: n " in ln and "slope" in ln]
        for ln in rows:
            slope = float(re.search(r"slope (-?[\d.e-]+)", ln).group(1))
            assert ln.endswith("; GR higher downward" if slope > 0 else "; GR higher upward" if slope < 0 else
                               "; GR no order with depth"), ln
        seen.add(k < S.ORDER_MIN_ZONES)                             # every such formation: both kinds where the data has them
    if not seen:
        pytest.skip("no formation of three zones with GR")


def _status_formation():
    for name, t, f in every():
        tw = [c for c in f.inv.curves if E.calibrated_twin(f, c) and E.calibrated_twin(f, c) not in E.same_as(f, c)]
        if tw:
            return t, f, tw[0]
    pytest.skip("no curve with a core-calibrated twin")


@pytest.mark.data
def test_status_tags_come_from_the_record_and_the_catalog():
    """A curve beside a core-calibrated twin is labelled uncalibrated in its label and on every row; a measured log
    'measurement'; a step's one-value curve a parameter; the tags follow the catalog's meanings, never the names: a
    twin whose catalog meaning is changed makes no tag, and a curve renamed keeps its tags."""
    t, f, c = _status_formation()
    twin = E.calibrated_twin(f, c)
    text = T.stats(f, [c]).text
    assert f"uncalibrated: the core-calibrated {twin} is in this interval" in text.splitlines()[0]
    rows = [ln for ln in text.splitlines()[1:] if ln.startswith("  Z")]
    assert rows and all(re.search(rf", {c} \([^)]*\buncalibrated\b[^)]*\): ", ln) for ln in rows), rows[:2]
    measured = next((x for x, cv in f.inv.curves.items() if cv.source == "input" and cv.measured_log), None)
    if measured:
        assert E.status(f, measured).startswith("measurement")
    par = next((x for x, cv in f.inv.curves.items() if cv.well_value is not None), None)
    if par:
        assert "one value over the whole well (" in E.status(f, par)
    inv = copy.copy(f.inv)                                           # the catalog decides, not the name
    inv.curves = {**f.inv.curves, twin: dataclasses.replace(f.inv.curves[twin], meaning="something else")}
    g = Formation(inv, f.view, f.store)
    assert not any(tag == "uncalibrated" for tag, _ in E.cautions(g, c))


@pytest.mark.data
def test_a_quicklook_and_the_curves_built_on_it_say_so():
    """Where the record's SXO route is the quicklook transform of SW, SXO is labelled quicklook and a curve the catalog
    says is computed from SXO is labelled as built on a quicklook input."""
    from petroharness.record.card import sxo_route
    for name, t, f in every():
        if "SXO" in f.inv.curves and sxo_route(f.view) == "quicklook":
            assert ("quicklook" in [tag for tag, _ in E.cautions(f, "SXO")])
            if "MHI" in f.inv.curves:
                assert "quicklook input" in [tag for tag, _ in E.cautions(f, "MHI")]
            return
        if "SXO" in f.inv.curves and sxo_route(f.view) == "measured":
            assert "quicklook" not in [tag for tag, _ in E.cautions(f, "SXO")]
    pytest.skip("no quicklook SXO here")


def test_a_never_set_flag_whose_input_has_no_value_is_not_computed_here():
    """A flag the catalog builds from an input with no value in the interval, and never set, says it was not computed
    here; one that is set somewhere was computed."""
    from types import SimpleNamespace as NS
    flag = np.zeros(10)
    cv = NS(source="computed", step="net_pay", catalog="flag, NET_RES and SW below the cutoff; a flag from VCL, porosity "
            "and SW", meaning="flag", inputs=["VCL", "SW"], well_value=None, measured_log=False, copy_of=None)
    vcl = NS(source="computed", step="vclay", catalog="", meaning="shale volume", inputs=[], well_value=None,
             measured_log=False, copy_of=None)
    reg = NS(curves={"inventory": {"derived": []}}, flags=set())
    view = NS(values=lambda c: {"NET_PAY": flag, "VCL": np.full(10, 0.2)}.get(c), reg=reg,
              prep=NS(well=NS(curves={"SW": None})))
    f = Formation(NS(curves={"NET_PAY": cv, "VCL": vcl}), view)
    tags = dict(E.cautions(f, "NET_PAY"))
    assert "not computed here" in tags and "SW has no value in this interval" in tags["not computed here"]
    flag[3] = 1.0
    g = Formation(NS(curves={"NET_PAY": cv, "VCL": vcl}), view)
    assert "not computed here" not in dict(E.cautions(g, "NET_PAY"))


# --- 3. the overlap tool, compare and crossplot -------------------------------------------------------------------------

class _Masks:
    """A view whose named curves hold given values (the rest as the formation has them)."""

    def __init__(self, view, values: dict):
        self._v, self._x = view, values

    def values(self, c):
        return self._x[c] if c in self._x else self._v.values(c)

    def zone_values(self, z, c):
        return self.values(c)[np.asarray(z.indices)]

    def __getattr__(self, name):
        return getattr(self._v, name)


def _runs_np(mask, z) -> list:
    """(top index, base index) of each stretch of True samples inside zone z."""
    idx = np.asarray(z.indices)
    on = mask[idx]
    out, start = [], None
    for j in range(idx.size):
        if on[j] and start is None:
            start = j
        if start is not None and (not on[j] or j == idx.size - 1 or idx[j + 1] != idx[j] + 1):
            end = j if on[j] else j - 1
            out.append((idx[start], idx[end]))
            start = None
    return out


@pytest.mark.data
def test_overlap_on_synthetic_conditions_matches_numpy():
    """Two synthetic flags: per zone the thickness and share of A, B, A and B, A without B and B without A (each zone
    from the top, the zone's thickness x its share), A = (A and B) + (A without B); the zones where each holds; the
    samples outside the zones apart; every run of each set, top to base by zone."""
    t, f = _outside_formation()
    n = f.depth.size
    rng = np.random.default_rng(7)
    a = (rng.random(n) < 0.35).astype(float)
    b = (rng.random(n) < 0.35).astype(float)
    a[np.asarray(f.view.zones[-1].indices)] = 0.0                     # a zone with no A
    inv = copy.copy(f.inv)
    flag = lambda nm: dataclasses.replace(next(iter(f.inv.curves.values())), name=nm, catalog="", meaning=nm,
                                          source="computed", step=None, inputs=None, well_value=None, copy_of=None)
    inv.curves = {**f.inv.curves, "FLAG_A": flag("FLAG_A"), "FLAG_B": flag("FLAG_B")}
    g = Formation(inv, _Masks(f.view, {"FLAG_A": a, "FLAG_B": b}), f.store)
    text = "\n".join(ln for ln, _ in T.overlap(g, "FLAG_A > 0.5", "FLAG_B > 0.5", limit=1000).rows)
    A, B = a > 0.5, b > 0.5
    sets = {"A": A, "B": B, "A and B": A & B, "A without B": A & ~B, "B without A": B & ~A}
    zs = sorted(f.view.zones, key=lambda z: z.top)
    rows = [ln for ln in text.splitlines() if re.match(r"^  Z\d+ ", ln)]
    assert [ln.split()[0] for ln in rows] == [z.zone_id for z in zs]
    for z, ln in zip(zs, rows):
        idx = np.asarray(z.indices)
        for name, m in sets.items():
            k = int(m[idx].sum())
            got = re.search(rf"(?:: |, ){re.escape(name)} (-?[\d.]+) \(([\d.]+)%\)", ln)
            assert got and abs(float(got.group(1)) - z.thickness * k / z.n_samples) <= 1e-3 * max(1, z.thickness), (name, ln)
            assert abs(float(got.group(2)) - 100 * k / z.n_samples) <= 0.051, (name, ln)
    last = rows[-1]
    assert " A 0 (0.0%)" in last or ": A 0 (0.0%)" in last
    zline = next(ln for ln in text.splitlines() if ln.startswith("  zones: "))
    both = [z.zone_id for z in zs if (A & B)[np.asarray(z.indices)].any()]
    assert f"A and B in {len(both)} of {len(zs)}" in zline
    assert next(ln for ln in text.splitlines() if ln.startswith("  outside any zone ("))
    for name in ("A and B", "A without B", "B without A"):
        line = next(ln for ln in text.splitlines() if ln.startswith(f"  {name}, ") or ln.startswith(f"  {name}: "))
        want = [(z.zone_id, i, j) for z in zs for i, j in _runs_np(sets[name], z)]
        assert f"{len(want)} {'run' if len(want) == 1 else 'runs'}, top to base: " in line, (name, line[:200])
        for zid, i, j in want:
            assert T._depth_cell(g, float(f.depth[i]), float(f.depth[j])) in line, (name, zid, line[:300])


@pytest.mark.data
def test_overlap_takes_classes_and_flags_and_refuses_one_condition_twice():
    t, f = _outside_formation()
    with pytest.raises(ToolError, match="two different conditions"):
        T.overlap(f, "GR > 50", "GR > 50")
    assert fit("overlap", {"conditions": ["NET_PAY", "GR > 50"]}) == {"a": "NET_PAY", "b": "GR > 50"}
    sec = next((s for s in f.inv.sections if any(not c.background and T._store_runs(f, s.key, c.name) for c in s.classes)), None)
    if sec is None:
        pytest.skip("no class with runs")
    cls = next(c for c in sec.classes if not c.background and T._store_runs(f, sec.key, c.name))
    text = call(f, "overlap", {"a": f"{sec.key}:{cls.name}", "b": "GR > 0"}).text
    assert text.startswith(f"Overlap of A = {cls.name} ({sec.key}) and B = GR > 0")


@pytest.mark.data
@DATASETS
def test_compare_and_crossplot_lead_with_the_zone_level_and_label_each_coefficient(config):
    """With two zones or more, the zone level comes before the first zone row; every rank correlation and correlation
    names its kind and transform, its n and each curve's range over the samples used."""
    seen = 0
    for t, f in formations(str(config)):
        have = [c for c in ("PHIE", "VCL", "GR", "RHOB", "SW") if c in f.inv.curves and E.kind(f, c).kind == "values"]
        if len(f.view.zones) < 2 or len(have) < 2:
            continue
        a, b = have[:2]
        for text in (T.compare(f, a, b).text, T.crossplot(f, a, b).text):
            lines = text.splitlines()
            lead = next((i for i, ln in enumerate(lines) if ln.startswith("  zone level (")), None)
            first = next(i for i, ln in enumerate(lines) if re.match(r"^  Z\d+ ", ln))
            assert lead is not None and lead < first, text[:500]
        rows = [ln for ln in T.compare(f, a, b).text.splitlines() if "rank correlation" in ln and re.match(r"^  Z\d+ ", ln)]
        z = f.view.zones[0]
        xa, xb = (np.asarray(f.view.values(c), dtype=float)[np.asarray(z.indices)] for c in (a, b))
        ok = np.isfinite(xa) & np.isfinite(xb)
        ln = next((r for r in rows if r.startswith(f"  {z.zone_id} ")), None)
        if ln is not None and ok.sum() >= 3:
            m = re.search(rf"\(Spearman, on ranks; n (\d+); {a} (-?[\d.]+)(?:-| to )(-?[\d.]+), {b} ", ln)
            assert m and int(m.group(1)) == int(ok.sum()), ln
            assert E.num(float(xa[ok].min())) == m.group(2) and E.num(float(xa[ok].max())) == m.group(3), ln
        fits = [r for r in T.crossplot(f, a, b, log_y=False).text.splitlines() if "correlation" in r and r.startswith("  Z")]
        assert all(f"(Pearson on {a} and {b}; n " in r for r in fits), fits[:1]
        seen += 1
        if seen >= 3:
            break
    if not seen:
        pytest.skip("no formation of two zones with two value curves")


@pytest.mark.data
def test_a_logarithm_s_dropped_samples_are_counted():
    for name, t, f in every():
        x = np.asarray(f.view.values("PHIE"), dtype=float) if "PHIE" in f.inv.curves else None
        if x is None or not (np.isfinite(x) & (x <= 0)).any() or "PERM" not in f.inv.curves:
            continue
        text = T.crossplot(f, "PERM", "PHIE", log_x=True).text
        k = int((np.isfinite(x) & (x <= 0)).sum())
        assert f"log10 leaves out {k} of {int(np.isfinite(x).sum())} samples of PHIE" in text
        return
    pytest.skip("no PHIE at or below 0")


# --- runs ---------------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_runs_lists_every_run_or_says_the_cut_and_its_get():
    """runs: every run top to base when they are at most limit; else the longest, in depth order, with the get of
    every run, which returns them a zone a line."""
    t, f = _outside_formation()
    cond = "GR > 0"
    found = E.extent(f, E.select(f, cond).mask, f.view.zones)
    full = T.runs(f, cond, limit=1000).text
    assert f"every run, top to base (top-base, thickness, zone), {len(found)} of {len(found)}:" in full
    if len(found) < 2:
        return
    led = Ledger(f)
    item, _ = led.open("runs", {"condition": cond, "limit": 1})
    assert re.search(rf'; the (other runs|next \d+ by thickness): get {item.id} with find "other runs"(; the other '
                     rf'\d+, each at most [\d.]+ \w+ thick, are not listed)?\), top to base, 1 of {len(found)}:', item.text)
    kept = [ln for ln in item.lines if ln.startswith("  other runs in ")]
    left = re.search(r"; the other (\d+), each at most", item.text)
    assert sum(len(ln.split(": ", 1)[1].split(", ")) for ln in kept) == len(found) - 1 - int(left.group(1) if left else 0)
    assert all(ln in led.get(item.id, "other runs") for ln in kept)


# --- 4. the guides ------------------------------------------------------------------------------------------------------

def _library():
    from petroharness.agent import direction
    from petroharness.config import DEFAULT_SKILLS, RESOURCES
    return direction.load((RESOURCES / DEFAULT_SKILLS).resolve())


def test_each_area_guide_ends_its_criteria_with_the_answer_s_shape():
    """The last Decide line of every area guide is its answer shape, in the ask forms with their words (locate,
    quantify, relate, classify, explain); its provenance row is a general guideline (class g) with its note's mark."""
    lib = _library()
    for g, f in lib.facets.items():
        if g in lib.common:
            continue
        line = f["decide"][-1]
        forms = re.findall(r"\b(locate \(depth runs, each graded\)|quantify \(values on each standard reading\)|"
                           r"relate \(direction, strength, where it holds and where it breaks\)|"
                           r"classify \(units with their classes\)|explain\b)", line)
        assert line.startswith("Answer shape: ") and forms, (g, line)                 # the ask forms, in their words
        row = lib.sources["facets"][g]["decide"][-1]
        assert row["class"] == "g" and "Harness format line" in str(row.get("note")), (g, row)


def test_recipes_say_what_each_tool_computes():
    """Every crossplot recipe says it is a least-squares line with R2 and n; every compare recipe names what it
    computes (means, difference or rank correlation); the overlap recipe is in the guides that relate two conditions."""
    lib = _library()
    for g, f in lib.facets.items():
        if g in lib.common:
            continue
        for e in f["compare"]:
            head, note = e.split("   (", 1)
            if head.startswith("crossplot "):
                assert "least-squares line" in note and "R2" in note, (g, e)
            if head.startswith("compare "):
                assert re.search(r"averages|difference|rank correlation", note), (g, e)
    for g in ("hydrocarbon_detection", "fluid_contacts", "invasion_movability", "net_reservoir_pay",
              "permeability_rock_quality"):
        assert any(e.startswith("overlap A B   (") for e in lib.facets[g]["compare"]), g


def test_overlap_is_a_tool_the_model_is_shown():
    from petroharness.agent.loop import TOOLS as SHOWN, tools_text
    from petroharness.agent.schemas import named
    from petroharness.agent.toolset import TOOLSET
    assert "overlap" in SHOWN and "overlap" in TOOLSET
    fn = next(t["function"] for t in named() if t["function"]["name"] == "overlap")
    assert fn["parameters"]["required"] == ["a", "b"] and "A without B" in fn["description"]
    assert '{"overlap": {"a": ..., "b": ...' in tools_text()
