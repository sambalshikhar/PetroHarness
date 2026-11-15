"""Inventory tests (G1-G11): every formation of the configured dataset, an independent derivation of each curve's
source, mutations of real wells and hand-written cases.

    PYTHONPATH=src:. .venv/bin/python -m pytest tests/agent/test_b0_inventory.py -q                      (GeoLink)
    PETROHARNESS_DATA=.../data.costa.yaml PYTHONPATH=src:. .venv/bin/python -m pytest tests/agent/test_b0_inventory.py -q
"""

import copy
import re
import sys
import time
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from petroharness.config import HarnessConfig  # noqa: E402
from petroharness.tasks import load_tasks  # noqa: E402
from petroharness.well.view import FormationView  # noqa: E402
from petroharness.record.store import build as build_store  # noqa: E402
from petroharness.agent.inventory import _PP_STEPS, SOURCES, from_view  # noqa: E402

def default_reporting(cfg: HarnessConfig) -> HarnessConfig:
    """The configuration with the data's two reporting settings at the package's defaults: data.basis "all" (each
    zone, the zones pooled and the whole interval where it differs) and no conventions. A data file may set its own (a
    benchmark's file sets the zones basis and its conventions); the formations the tests share are built without them,
    so what the tests assert of the tools, the map and the prompts holds whichever data file is in use. The two
    settings have their own tests (tests/agent/test_writer_evidence.py; the zones basis over every summarising tool:
    tests/agent/test_summary.py)."""
    return cfg.model_copy(update={"data": cfg.data.model_copy(update={"basis": "all", "conventions": []})})


CFG = default_reporting(HarnessConfig())


@lru_cache(maxsize=1)
def formations() -> list:
    """(task, view, store, inventory) for each formation of the dataset, hydrocarbon tasks first (built on the default
    reporting settings: default_reporting)."""
    tasks, index = load_tasks(CFG.eval.questions, CFG.data.las_dir)
    tasks = sorted(tasks, key=lambda t: index[t.task_id]["category"] != "hydrocarbon")
    out, seen = [], set()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for t in tasks:
            k = (str(t.las_path), t.formation)
            if k in seen:
                continue
            seen.add(k)
            v = FormationView.build(t, CFG.for_tasks())
            s = build_store(v)
            out.append((t, v, s, from_view(v, s)))
    return out


def small():
    return min(formations(), key=lambda f: (len(f[1].zones), f[0].well))


# --- G1 every curve with data appears once ------------------------------------------------------------------------

@pytest.mark.data
def test_g1_every_curve_with_data_appears_once():
    for t, v, s, inv in formations():
        expected = {c for c in list(v.prep.well.curves) + list(v.analyzer_curves) + list(s.curves)
                    if c.upper() != "DEPT" and v.available(c)}
        assert set(inv.curves) == expected, (t.well, set(inv.curves) ^ expected)


# --- G2 meanings ----------------------------------------------------------------------------------------------------

def _named_in(text: str, names) -> set:
    return {c for c in names if re.search(rf"(?<![A-Z0-9_]){re.escape(c)}(?![A-Z0-9_])", text)}


@pytest.mark.data
def test_g2_curves_the_hydrocarbon_sections_name_have_meanings():
    unknown = []
    for t, v, s, inv in formations():
        text = " ".join(" ".join([sec.title, sec.method or "", sec.basis or ""] + [c.definition or "" for c in sec.classes])
                        for sec in inv.sections if sec.family == "hydrocarbon")
        for c in _named_in(text, inv.curves):
            if inv.curves[c].meaning == "unknown":
                unknown.append((t.well, c))
    assert not unknown, unknown[:10]


@pytest.mark.data
def test_g2_so_resolves_wherever_present():
    seen = 0
    for t, v, s, inv in formations():
        if "SO" in inv.curves:
            seen += 1
            assert "oil" in inv.curves["SO"].meaning.lower() or "hydrocarbon" in inv.curves["SO"].meaning.lower(), inv.curves["SO"]
    if not seen:
        pytest.skip("no SO curve in this dataset")


@pytest.mark.data
def test_g2_meanings_carry_no_source_story():
    for t, v, s, inv in formations():
        for c in inv.curves.values():
            assert not any(w in c.meaning for w in ("same values as", "supplied in the LAS", "{method}")), (t.well, c)


@pytest.mark.data
def test_g2_every_meaning_names_where_it_came_from():
    for t, v, s, inv in formations():
        for c in inv.curves.values():
            assert c.meaning_from in ("registry plain", "registry", "petrophys description", "petrophys label",
                                      "LAS header", "registry family", "step", "unknown"), c
            assert (c.meaning == "unknown") is (c.meaning_from == "unknown")


# --- G3 sources agree with an independent derivation ----------------------------------------------------------------

def _independent_source(v, inv, c: str) -> str:
    steps = v.prep.steps or {}
    listed = any("outputs" in (r or {}) for r in steps.values())
    writer = workflow_writer = None
    if listed:
        for name, rec in steps.items():
            if c in [str(o) for o in (rec or {}).get("outputs") or []]:
                writer = name                                   # the last step that wrote it
                if ((rec or {}).get("stage") or "workflow") == "workflow":
                    workflow_writer = name
    inputs = {x.upper() for x in v.prep.input_curves}
    if workflow_writer or (writer and c.upper() not in inputs):  # a LAS curve a preparation or QC only touched: input
        return "computed"
    reg = v.reg
    measured = {x.upper() for x in reg.raw_order} | {x.upper() for m in (reg.curves.get("families") or {}).values() for x in m}
    if c.upper() in inputs:
        return "input"
    if listed:
        a = v.prep.curve(c)
        for other in v.prep.input_curves:
            b = v.prep.curve(other)
            if a is None or b is None or other == c or a.shape != b.shape:
                continue
            fa, fb = np.isfinite(a), np.isfinite(b)
            both = fa & fb
            if both.sum() and both.sum() >= 0.95 * max(fa.sum(), fb.sum()) and np.allclose(a[both], b[both], rtol=1e-9, atol=0):
                return "copy"
    if c in v.analyzer_curves:
        return "analyzer"
    if c in _PP_STEPS:
        return "computed"
    return "unknown"


@pytest.mark.data
def test_g3_sources_agree_with_an_independent_derivation():
    bad = []
    for t, v, s, inv in formations():
        for c in inv.curves.values():
            assert c.source in SOURCES
            want = _independent_source(v, inv, c.name)
            if c.source != want:
                bad.append((t.well, c.name, c.source, want))
    assert not bad, bad[:10]


# --- G4 property sources ranked; a copy is never log-derived --------------------------------------------------------

@pytest.mark.data
def test_g4_property_sources_are_ranked_and_copies_follow_their_source():
    for t, v, s, inv in formations():
        for prop, ranks in inv.properties.items():
            assert [r.rank for r in ranks] == sorted(r.rank for r in ranks), (t.well, prop)
            names = [r.curve for r in ranks]
            for r in ranks:
                cv = inv.curves[r.curve] if r.curve in inv.curves else None
                if cv is not None and cv.copy_of:                  # a copy, or a step that passed its input through
                    assert r.kind == f"copy of {cv.copy_of}" and "log model" not in r.kind, (t.well, r)
                    if cv.copy_of in names:
                        assert names.index(cv.copy_of) < names.index(r.curve), (t.well, names)


@pytest.mark.data
def test_g4_supplied_core_corrected_permeability_is_the_permeability_of_record():
    seen = 0
    for t, v, s, inv in formations():
        pc, p = inv.curves.get("PERM_CC"), inv.curves.get("PERM")
        if pc and pc.source == "input" and "KH_CORE" not in inv.curves:
            seen += 1
            assert inv.properties["permeability"][0].curve == "PERM_CC", (t.well, inv.properties["permeability"])
            assert inv.properties["permeability"][0].kind == "core-calibrated (input)"
            if p and p.copy_of:
                assert p.copy_of == "PERM_CC"
    if not seen:
        pytest.skip("no supplied core-corrected permeability in this dataset")


@pytest.mark.data
def test_g4_a_step_that_passed_its_input_through_is_a_copy_of_it():
    """A computed curve with the same values as one of its step's inputs says so (the Petrophys workflow records the
    step that passes PERM_CC through as PERM); one with other values does not."""
    import numpy as np
    from petroharness.record.card import _same_values
    seen = 0
    for t, v, s, inv in formations():
        for c in inv.curves.values():
            if c.source != "computed" or not c.inputs:
                continue
            same = [i for i in c.inputs if i != c.name and _same_values(v.prep.curve(c.name), v.prep.curve(i))]
            assert c.copy_of == (same[0] if same else None), (t.well, c.name, c.copy_of, same)
            if c.copy_of:
                seen += 1
                a, b = v.prep.curve(c.name), v.prep.curve(c.copy_of)
                both = np.isfinite(a) & np.isfinite(b)
                assert both.any() and np.array_equal(a[both], b[both]), (t.well, c.name)
    if not seen:
        pytest.skip("no step passes an input through in this dataset")


# --- G5 zones -------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_g5_zones_ordered_inside_the_interval_and_add_up():
    for t, v, s, inv in formations():
        assert inv.depth_unit in ("ft", "m"), inv.depth_unit
        tol = 2 * inv.step + 1e-6
        prev = None
        for z in inv.zones:
            assert inv.top - tol <= z.top <= z.base <= inv.base + tol, (t.well, z)
            assert abs((z.base - z.top) - z.thickness) <= tol, (t.well, z)
            if prev is not None:
                assert z.top >= prev.base - 1e-6, (t.well, prev, z)
            prev = z
        assert abs(sum(z.thickness for z in inv.zones) - inv.zoned_thickness) <= tol * max(1, len(inv.zones)), t.well
        assert inv.zoned_thickness <= inv.gross + tol, t.well


# --- G6 sections ----------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_g6_every_section_listed_and_hydrocarbon_classes_defined():
    defined = total = 0
    for t, v, s, inv in formations():
        assert [sec.key for sec in inv.sections] == list(s.sections), t.well
        for sec in inv.sections:
            assert sec.title and sec.family == sec.key.split(".", 1)[0]
            if sec.family == "hydrocarbon":
                for c in sec.classes:
                    total += 1
                    defined += c.definition is not None
    assert total and defined / total >= 0.90, (defined, total)


# --- G7 logs present and absent -------------------------------------------------------------------------------------

@pytest.mark.data
def test_g7_measured_logs_present_and_absent_agree_with_the_las():
    for t, v, s, inv in formations():
        assert set(inv.logs_present) | set(inv.logs_absent) == set(v.reg.raw_order)
        assert not set(inv.logs_present) & set(inv.logs_absent)
        for c in inv.logs_present:
            assert v.available(c), (t.well, c)
        for c in inv.logs_absent:
            assert not v.available(c), (t.well, c)


# --- G8 mutations of a real well --------------------------------------------------------------------------------------

def _mutant():
    t, v, s, inv = small()
    return t, copy.deepcopy(v), s


def _rebuild(v, s):
    return from_view(v, s)


@pytest.mark.data
def test_g8_a_removed_curve_disappears():
    t, v, s = _mutant()
    gone = next(c for c in v.prep.input_curves if v.available(c))
    orig = v.prep.curve
    v.prep.curve = lambda c: None if c == gone else orig(c)
    assert gone not in _rebuild(v, s).curves


@pytest.mark.data
def test_g8_a_new_curve_with_a_supplied_curves_values_is_a_copy_where_the_record_lists_outputs():
    t, v, s = _mutant()
    src = next(c for c in v.prep.input_curves if v.available(c))
    v.prep.well.add_curve("MUT_COPY", v.prep.curve(src).copy(), v.prep.unit(src), "")
    inv = _rebuild(v, s)
    listed = any("outputs" in (r or {}) for r in (v.prep.steps or {}).values())
    c = inv.curves["MUT_COPY"]
    assert (c.source, c.copy_of) == (("copy", src) if listed else ("unknown", None)), c


@pytest.mark.data
def test_g8_a_flat_curve_and_a_zone_of_nan_are_reflected():
    t, v, s = _mutant()
    c = next(c for c in v.prep.well.curves if v.available(c) and c.upper() != "DEPT")
    z = v.zones[0]
    data = v.prep.curve(c).copy()
    whole_idx = np.flatnonzero(v.mask)[z.indices]
    data[whole_idx] = np.nan
    v.prep.well.add_curve("MUT_HOLE", data, v.prep.unit(c), "")
    v.prep.well.add_curve("MUT_FLAT", np.where(np.isfinite(v.prep.curve(c)), 1.0, np.nan), "", "")
    inv = _rebuild(v, s)
    assert inv.curves["MUT_FLAT"].flat is True
    if "MUT_HOLE" in inv.curves:
        assert inv.curves["MUT_HOLE"].zone_coverage[z.zone_id] == 0.0
        assert inv.curves["MUT_HOLE"].coverage < inv.curves[c].coverage or inv.curves[c].coverage == 0


@pytest.mark.data
def test_g8_a_record_without_output_lists_keeps_what_the_las_shows():
    t, v, s = _mutant()
    v.prep.steps = {k: {kk: vv for kk, vv in (r or {}).items() if kk not in ("outputs", "inputs")}
                    for k, r in (v.prep.steps or {}).items()}
    inv = _rebuild(v, s)
    assert inv.record_lists_outputs is False
    for c in inv.curves.values():
        if c.name.upper() in {x.upper() for x in v.prep.input_curves}:
            assert c.source == "input", c
        assert c.source != "copy", c                          # without output lists a copy cannot be shown
        if c.source == "computed":
            assert c.step_from.startswith("petrophys curve map"), c


# --- G9 hand-written cases ---------------------------------------------------------------------------------------------

@pytest.mark.data
@pytest.mark.parametrize("curve", ["PERM_CC", "PHIE_CC", "PERM"])
def test_g9_a_curve_means_what_it_is_whatever_its_source(curve):
    """PERM_CC is core-calibrated permeability whether the input carries it or the workflow calibrates it: its meaning is
    the curve catalog's line (what it is, its kind and inputs), the same whatever its source; where this
    well's copy came from is the source field, never part of the meaning."""
    from petroharness.registry import load
    line = load().curves["meanings"][curve]
    meaning = line.split("; ")[0]                     # the catalog line's first part: what it is
    hits = 0
    for t, v, s, inv in formations():
        c = inv.curves.get(curve)
        if c:
            hits += 1
            assert c.meaning == meaning and c.catalog == line, (t.well, c)
            assert not any(w in c.catalog for w in ("supplied", "the LAS", "log-derived", "same values")), c
    if not hits:
        pytest.skip(f"no {curve} in this dataset")


@pytest.mark.data
@pytest.mark.parametrize("curve", ["SO", "PHI_Z", "DTS"])
def test_g9_curves_without_a_registry_entry_still_have_a_meaning(curve):
    hits = 0
    for t, v, s, inv in formations():
        if curve in inv.curves:
            hits += 1
            assert inv.curves[curve].meaning != "unknown", (t.well, inv.curves[curve])
    if not hits:
        pytest.skip(f"no {curve} in this dataset")


@pytest.mark.data
def test_g9_one_depth_unit_and_zone_depths_in_it():
    units = set()
    for t, v, s, inv in formations():
        units.add(inv.depth_unit)
        assert inv.depth_unit == v.depth_unit
        eps = 1e-6 * max(1.0, abs(inv.base))                    # float precision of stored depths
        assert all(inv.top - eps <= z.top < z.base <= inv.base + 2 * inv.step for z in inv.zones), t.well
        assert inv.gross == pytest.approx(inv.base - inv.top, abs=2 * inv.step)
    assert len(units) == 1, units                                # one dataset, one depth unit


@pytest.mark.data
def test_g9_thickness_is_in_the_depth_unit():
    for t, v, s, inv in formations():
        assert inv.gross == pytest.approx(float(v.gross))
        assert inv.zoned_thickness == pytest.approx(float(v.zoned_thickness))


@pytest.mark.data
def test_g9_sample_step_matches_the_depths():
    for t, v, s, inv in formations()[:20]:
        d = v.prep.depth[v.mask] if hasattr(v.prep, "depth") else None
        if d is not None and d.size > 2:
            assert inv.step == pytest.approx(float(np.median(np.diff(d))), rel=1e-6)


@pytest.mark.data
def test_g9_record_format_is_reported():
    for t, v, s, inv in formations():
        listed = any("outputs" in (r or {}) for r in (v.prep.steps or {}).values())
        assert inv.record_lists_outputs is listed
        if not listed:
            assert not any(c.source == "copy" for c in inv.curves.values())


@pytest.mark.data
def test_g9_percent_flags_follow_the_view():
    for t, v, s, inv in formations():
        for c in inv.curves.values():
            assert c.percent is bool(v.in_percent(c.name))


@pytest.mark.data
def test_g9_coverage_is_the_share_of_finite_samples():
    for t, v, s, inv in formations()[:20]:
        for c in list(inv.curves.values())[:15]:
            x = v.values(c.name)
            assert c.coverage == pytest.approx(float(np.isfinite(x).mean()))
            assert c.n == int(np.isfinite(x).sum())


# --- G11 methods as the record has them ---------------------------------------------------------------------------

@pytest.mark.data
def test_g11_every_recorded_step_appears_verbatim():
    for t, v, s, inv in formations():
        steps = v.prep.steps or {}
        assert [m.step for m in inv.methods] == list(steps), t.well
        for m in inv.methods:
            rec = steps[m.step] or {}
            assert m.method == str(rec.get("method") or "")
            for k, x in m.parameters.items():
                assert rec["parameters"][k] == x                       # values exactly as recorded
            lines = [d for d in rec.get("decisions") or [] if isinstance(d, str)]
            assert sorted(m.equations + m.decisions) == sorted(lines)   # nothing added, nothing lost
            assert m.inputs == rec.get("inputs") and m.outputs == rec.get("outputs")


@pytest.mark.data
def test_g11_equations_are_decision_lines_that_state_one():
    eqs = 0
    for t, v, s, inv in formations():
        for m in inv.methods:
            for e in m.equations:
                eqs += 1
                assert re.match(r"^[A-Za-z][A-Za-z0-9_()]*(?:\s*[,/]\s*[A-Za-z][A-Za-z0-9_]*)?\s*=\s*\S", e), e
            for d in m.decisions:
                assert not re.match(r"^(PHI[A-Z_]*|SW|SXO|BVW|RQI|FZI|PERM|VCL|MHI)\s*=", d), d
    assert eqs > 0


@pytest.mark.data
def test_g11_the_saturation_model_and_its_coefficients_are_there():
    for t, v, s, inv in formations():
        sat = next((m for m in inv.methods if m.step == "saturation"), None)
        rec = (v.prep.steps or {}).get("saturation")
        if rec:
            assert sat is not None and sat.method == str(rec.get("method"))
            for k in ("a", "m", "n"):
                if isinstance((rec.get("parameters") or {}).get(k), (int, float)):
                    assert sat.parameters[k] == rec["parameters"][k]


@pytest.mark.data
def test_g11_interval_scoped_lines_count_this_interval():
    """Flag counts in the scoped lines are this interval's; a flag with no data here has no line (the record counts
    the whole well)."""
    pat = re.compile(r"^(?P<flag>[A-Z][A-Z0-9_]*)\b.*?->\s*(?P<n>\d+) samples .* in this interval")
    checked = 0
    for t, v, s, inv in formations():
        for m in inv.methods:
            for line in m.decisions_here + m.equations_here:
                hit = pat.match(line)
                if hit and hit.group("flag") in v.reg.flags:
                    x = v.values(hit.group("flag"))
                    assert x is not None and int(np.nansum(x > 0.5)) == int(hit.group("n")), (t.well, line)
                    checked += 1
            for line in m.decisions + m.equations:
                f = re.match(r"^([A-Z][A-Z0-9_]*)\b.*->\s*\d+ samples", line)
                if f and f.group(1) in v.reg.flags and not v.available(f.group(1)):
                    assert not any(l.startswith(f.group(1)) for l in m.decisions_here), (t.well, line)
    assert checked > 0


# --- G10 deterministic and fast ---------------------------------------------------------------------------------------

@pytest.mark.data
def test_g10_deterministic_and_fast():
    slow = []
    for t, v, s, inv in formations()[:30]:
        t0 = time.perf_counter()
        again = from_view(v, s)
        dt = time.perf_counter() - t0
        assert again.to_dict() == inv.to_dict(), t.well
        if dt > 2.0:
            slow.append((t.well, round(dt, 2)))
    assert not slow, slow
