"""Each rule at the shared point every sibling passes through, tested over every sibling (every well case, every step,
every curve, every tool), not over the case that exposed it (gaps/fix1119/CONSOLIDATE.md, 2026-11-19).

    .venv/bin/python -m pytest tests/test_shared_points.py -q
"""
from pathlib import Path
import re

import numpy as np
import pytest

from _wells import CASES, formation_of

pytestmark = pytest.mark.data

WELLS = ["brent", "1671", "cheal", "tuhua", "hw3", "teapot"]


# --- C1: one field for class labels ----------------------------------------------------------------------------------

@pytest.mark.parametrize("case", WELLS)
def test_every_class_curve_is_named_from_the_one_field_petrophys_keeps(case):
    """Petrophys keeps a class curve's labels in metadata.custom["category_labels"] (its analyzer and log viewer read
    it); the harness reads that field for every curve that has it, the data's code table for the lithology log."""
    from petroharness.well.summary import code_labels
    f = formation_of(CASES[case])
    well = f.view.prep.well
    seen = 0
    for name in well.curves:
        labels = (well[name].metadata.custom or {}).get("category_labels")
        if not labels or name == getattr(f.view, "lithology_curve", None):
            continue
        seen += 1
        assert code_labels(f.view, name) == {float(k): str(v) for k, v in labels.items()}, name
        if name in f.inv.curves:
            held = f.inv.curves[name].codes
            assert held and all(held[c] == labels[int(c)] for c in held), (name, held)
    assert seen, "no class curve with labels"                    # LITHO or NET_EXCLUSION in every case
    from petrophys.model.curve import CurveMetadata
    assert "codes" not in CurveMetadata.__dataclass_fields__     # no second field for the same labels


# --- C3: no record line is dropped ------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", WELLS)
def test_no_record_line_is_dropped_or_rewritten(case):
    """C3 then O3: every step record line reaches the map as Petrophys wrote it (the whole well's run, the map's header
    says), none dropped, none rewritten by a regex over its counts; the interval's facts come from the step's curves
    (record.catalog.interval_facts). Dropping lines with a count had hidden the defaults (Rcl, the N-D clay point),
    fallbacks (SWIRR_APP) and checks (the Rw against Rwa) they stated."""
    from petroharness.agent.map import plain_inputs, render
    f = formation_of(CASES[case])
    text = " ".join(render(f.inv).split())
    for m in f.inv.methods:
        assert m.decisions_here == m.decisions and m.equations_here == m.equations, m.step
        for d in m.decisions:                          # as the map writes a fallback input ("A where present, ...")
            assert " ".join(plain_inputs(d, m.inputs).split())[:60] in text, (m.step, d[:80])


@pytest.mark.parametrize("case, line", [("hw3", "Rcl = 5.00 ohm.m (default because"),
                                        ("hw3", "N-D clay point: default"),
                                        ("hw3", "No clean porous rock reads as water"),
                                        ("1671", "The Rw in use looks too high"),
                                        ("1671", "SWIRR_APP = 0.200 fallback")])
def test_the_defaults_fallbacks_and_checks_reach_the_map(case, line):
    from petroharness.agent.map import render
    f = formation_of(CASES[case])
    assert line in render(f.inv)


# --- C5: every tool heads with the whole selection; a where's lines name the samples they cover -----------------------

TOOL_CALLS = [("estimate", {"parameter": "matrix"}, "RHOMAA", np.nanmedian),
              ("estimate", {"parameter": "temperature"}, None, None),
              ("calibrate", {"what": "shear"}, "DTS_GC", np.nanmedian),
              ("calibrate", {"what": "elastic"}, None, None)]


@pytest.mark.parametrize("case", WELLS)
def test_every_tool_heads_its_lines_with_the_whole_selection(case):
    """Every line that reports a per-sample result by bases starts with the whole selection where samples outside the
    zones hold a value (engine.scopes), and the whole value is numpy's over every interval sample with a value.
    Before, estimate matrix and temperature, calibrate and a Petrophys run gave the zones pooled and each zone only
    (question suite T04: every net-reservoir sample lay outside the rows and the tool read 0)."""
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    from petroharness.well import summary as S
    f = formation_of(CASES[case])
    away = S.outside_mask(f.view)
    seen = 0
    for tool, args, curve, stat in TOOL_CALLS:
        try:
            text = schemas.call(f, tool, args).text
        except ToolError:
            continue                                           # the well lacks the tool's input
        for ln in text.splitlines():
            if "pooled" not in ln:
                continue
            head = ln.find(S.whole_label_of(f.view))
            if head >= 0:
                assert head < ln.find("pooled"), ln              # the whole first, its breakdown after
        if curve and curve in f.view.calculated:
            x = np.asarray(f.view.calculated[curve], dtype=float)[f.view.mask]
            if np.isfinite(x[away]).any():
                seen += 1
                want = stat(x[np.isfinite(x)])
                line = next(ln for ln in text.splitlines() if S.whole_label_of(f.view) in ln)
                got = float(line.split(S.whole_label_of(f.view))[1].split(";")[0].split()[0])
                assert abs(got - want) <= 1e-3 * max(1.0, abs(want)), (tool, line, want)
    assert seen or pytest.skip("no tool result with values outside the zones in this case")


def test_a_where_names_the_samples_of_every_line_it_covers():
    """Under a where every line says which samples it covers: the whole selection's line names the where and its
    count, and the outside-any-zone line counts the where's samples outside the zones, not all of them."""
    from petroharness.agent import schemas
    from petroharness.well import summary as S
    f = formation_of(CASES["brent"])
    gr = np.asarray(f.view.values("GR"), dtype=float)
    m = np.isfinite(gr) & (gr < 60)
    away = S.outside_mask(f.view)
    for tool, args in [("stats", {"curves": ["GR"], "where": "GR < 60"}),
                       ("compare", {"a": "PHIE", "b": "PHIT", "where": "GR < 60"}),
                       ("crossplot", {"x": "PHIE", "y": "GR", "where": "GR < 60"})]:
        t = schemas.call(f, tool, args).text
        if (m & away).any():
            assert f"outside any zone ({int((m & away).sum())} samples; not a zone)" in t, (tool, t[-600:])
        assert f"outside any zone ({int(away.sum())} samples" not in t or int(away.sum()) == int((m & away).sum()), tool


# --- C8: a choice left to Petrophys is said -------------------------------------------------------------------------

def test_every_choice_a_call_leaves_to_petrophys_is_said_in_its_inputs():
    """A Petrophys function run with a choice it was not given (a lithology, a matrix) used its default unsaid: the
    shear prediction ran as sandstone in a carbonate (question suite W03). Every such choice is now in the Inputs
    line, with what it takes, for every function of the registry that declares one."""
    import inspect
    from petroharness.agent import library_api as A
    from petroharness.agent.engine import ToolError
    f = formation_of(CASES["hw3"])
    ran = 0
    for fn in A.registry():
        choices = [p for p, d in fn.kinds.items() if d.kind == "choice" and fn.params[p][1] is not inspect.Parameter.empty
                   and fn.params[p][1] is not None]
        if not choices:
            continue
        named = {}
        for p, d in fn.kinds.items():
            if fn.params[p][1] is inspect.Parameter.empty and d.kind in ("curve", "curve_name") and d.curve:
                here = A._here(f, d.curve)
                if here:
                    named[p] = here[0].split()[0]
        try:
            text = A.run(f, fn.verb, fn.name, named).text
        except ToolError:
            continue
        ran += 1
        inputs = text.splitlines()[0]
        for p in choices:
            if getattr(fn.kinds[p], "role", None) == "lithology":             # the record's lithology fills it (D3)
                assert re.search(rf"{p} (\S+ \(the record's lithology|each lithology of these samples|\S+ \(Petrophys's "
                                 "default: no option)", inputs), (fn.name, p, inputs[:400])
            else:
                assert f"{p} {A._shown_default(fn.params[p][1])} (Petrophys's default; " in inputs, (fn.name, p, inputs[:400])
    assert ran >= 3, ran


# --- C6: one range grammar --------------------------------------------------------------------------------------------

def test_a_where_depth_window_reads_as_every_range_does():
    """A where's depth window took 'ft' on a metres well as metres, and a limit with decimals left out the sample it
    rounds to. It is read by selection.parse_range and _rounded_limits, as zones read a range."""
    from petroharness.agent import engine as E, selection
    f = formation_of(CASES["brent"])
    d = np.asarray(f.depth, dtype=float)
    ft = E.select(f, "depth 9320-9400 ft").mask
    want = (d >= 9320 * 0.3048 - 1e-6) & (d <= 9400 * 0.3048 + 1e-6)
    assert ft.sum() == want.sum() > 0
    top = float(d[10])
    written = f"{top:.2f}-{float(d[40]):.2f}"                       # the limits as a map writes them, rounded
    z = selection.resolve(f, [written], force=True)[0]
    assert E.select(f, written).mask.sum() == int(z.view.mask.sum())   # the same samples as the zones range


# --- C13: the suite's low findings, each at its shared point -----------------------------------------------------------

@pytest.mark.parametrize("head, label, name", [("SW", "SW_ARCHIE_A1", "SW_ARCHIE_A1"), ("SW", "ARCHIE_A1", "SW_ARCHIE_A1"),
                                               ("SW_ARCHIE", "SW", "SW_ARCHIE"), ("PICKETT", "RW", "PICKETT_RW")])
def test_f12_a_name_and_a_label_name_it_once(head, label, name):
    """T03: the label SW_ARCHIE_A1 on a recomputed SW was written SW_SW_ARCHIE_A1. Every curve name made of a name and
    a label (calculate's recomputed curves, a Petrophys run's outputs) is joined by one rule."""
    from petroharness.agent.library import joined_name
    assert joined_name(head, label) == name


def test_f15_f17_a_las_description_is_the_providers_words_by_one_reading():
    """D01: 'Total CMR Porosity {F13.4}' (a LAS format in braces) was a curve's meaning; K02: the microlog's MI and MN
    had none, their LAS writing the names in the value field ('MI.  Micro Inverse:'). Petrophys reads a description by
    one rule (io.las_reader.curve_description), its reader and the harness's alike."""
    from types import SimpleNamespace as NS
    from petrophys.io.las_reader import curve_description
    from petroharness.well.view import las_curve_descriptions
    assert curve_description(NS(descr="Total CMR Porosity {F13.4}", value="")) == "Total CMR Porosity"
    assert curve_description(NS(descr="", value="Micro Inverse")) == "Micro Inverse"
    assert curve_description(NS(descr="", value="07 310 01 00")) == ""                  # an API code is not a name
    import os
    from pathlib import Path
    kgs = Path(os.environ.get("PETROHARNESS_SAMPLE_LAS", "/nonexistent")) / "1046123714.las"
    if kgs.exists():                                              # the KGS well with the microlog
        d = las_curve_descriptions(str(kgs))
        assert (d.get("MI"), d.get("MN")) == ("Micro Inverse", "Micro Normal")
    f = formation_of(CASES["teapot"])
    assert not any("{" in (f.view.prep.well[c].metadata.description or "") for c in f.view.prep.well.curves)


@pytest.mark.parametrize("case", WELLS)
def test_input_curves_with_the_same_values_name_each_other(case):
    """A LAS that carries one log under two names (GeoLink's CALI and DCAL): since the LAS's own curves are inputs
    (F5), two of them were no longer a copy pair, and the map lost "(same values as ...)". The inventory pairs every
    two input curves with the same values (Curve.same_as), and the map names the twin."""
    from petroharness.agent.map import render
    from petroharness.record.card import _same_values
    f = formation_of(CASES[case])
    ins = [c for c, cv in f.inv.curves.items() if cv.source == "input"]
    want = {(a, b) for a in ins for b in ins if a < b and _same_values(f.view.prep.curve(a), f.view.prep.curve(b))}
    got = {(a, b) for a in ins for b in f.inv.curves[a].same_as if a < b}
    assert got == want
    text = render(f.inv)
    for a, b in want:
        assert f"(same values as {b}" in text or f"same values as {a}" in text, (a, b)


# --- D2: one selection rule for a scope and a tool's zones -------------------------------------------------------------

def test_a_tools_zones_are_the_union_of_what_they_name():
    """selection.resolve, which every tool's zones and a question's scope pass: an item inside another is part of it,
    overlapping items join into one row; the notes come out of resolve apart from the selection's name, and the call
    and the scope say them, also where the union is the interval's own samples (the interval). Overlapping tool zones
    were refused ('ask for them in separate calls') while a scope merged them; then the notes sat in the selection's
    name (every whole line's label) and were lost where the union was the interval."""
    from types import SimpleNamespace as NS
    from petroharness.agent import loop, schemas, selection
    f = formation_of(CASES["brent"])
    notes = []
    inner = selection.resolve(f, ["Ness Fm.", "2850-2860 m"], force=True, notes=notes)[0]
    alone = selection.resolve(f, ["Ness Fm."], force=True)[0]
    assert selection.same_samples(inner.view, alone.view) and any("is part of" in n for n in notes), notes
    assert "part of" not in inner.view.selection                               # the name is the items' only
    notes = []
    joined = selection.resolve(f, ["2841-2870 m", "2860-2900 m"], force=True, notes=notes)[0]
    d = np.asarray(f.view.prep.depth, dtype=float) * f.view.depth_scale
    assert int(joined.view.mask.sum()) == int(((d >= 2841 - 1e-6) & (d <= 2900 + 1e-6)).sum())
    assert any("overlap: one row, 2841-2900 m" in n for n in notes), notes
    head = selection.header(joined, notes)                                     # one stretch: its lithology zones
    assert "its lithology zones" in head and "Zones as asked:" in head, head
    iv = f.view.interval
    notes = []
    same = selection.resolve(f, [f"{iv.top:g}-{iv.base:g} m", "Ness Fm."], force=True, notes=notes)[0]
    assert same is f and any("is part of" in n for n in notes), notes          # the interval itself, said
    notes = []                                                                 # X01: a unit whose top is written
    selection.resolve(f, [f"{iv.top:.4f}-{iv.base:.4f} m", "2841-2865 m"], force=True, notes=notes)   # above the
    assert notes and all("is part of" in n and "overlap" not in n for n in notes), notes    # first sample: inside
    assert not any("m) 2841" in n for n in notes), notes                                   # its depths said once
    t = schemas.call(f, "stats", {"curves": ["GR"], "zones": ["2841-2870 m", "2860-2900 m"]}).text
    assert "overlap: one row" in t and "ask for them in separate calls" not in t
    t = schemas.call(f, "stats", {"curves": ["GR"], "zones": [f"{iv.top:g}-{iv.base:g} m", "Ness Fm."]}).text
    assert t.startswith("Zones as asked:") and "is part of" in t.splitlines()[0], t[:300]
    s = NS(f=f, scope=[], scope_note="", scope_merged="", scope_by_user=False, frame=None)
    loop.apply_scope(s, ["Ness Fm.", "2850-2860 m"])
    assert s.scope == ["Ness Fm."] and "is part of" in s.scope_merged and not s.scope_note
    assert s.scope_merged in loop.scope_text(s)
    loop.apply_scope(s, [f"{iv.top:g}-{iv.base:g} m", "Ness Fm."])
    assert not s.scope and "the interval's own samples" in s.scope_merged and not s.scope_note


def test_a_focus_zone_named_twice_is_one_row():
    """engine.zones: a zone named by its id and by its lithology is one row (the union rule for focus zones)."""
    from petroharness.agent import engine as E
    f = formation_of(CASES["brent"])
    z = f.view.zones[0]
    got = E.zones(f, [E.zone_name(z), z.zone_id])
    assert [x.zone_id for x in got].count(z.zone_id) == 1


# --- D1: every curve's writer from the record --------------------------------------------------------------------------

def test_a_curve_an_analysis_wrote_inside_a_step_is_credited_to_that_analysis():
    """Question suite F16 (E01): VP_VS_RATIO read as 'model output of the net_pay step'; the net-pay step's
    hydrocarbon analysis writes it (Petrophys StepResult.written_by), and the record says so for every curve an
    analysis inside a step wrote. A record that lists its steps' outputs names every curve's writer itself (no
    fallback to Petrophys's static curve-to-step map)."""
    from pathlib import Path
    from petroharness.agent import engine as E
    from _wells import Case
    las = Path(__import__("petrophys").__file__).parent / "datasets" / "epslog" / "ede_01_composite.las"
    if not las.exists():
        pytest.skip("no EDE-01 sample")
    f = formation_of(Case(str(las), top=1016.0, base=1316.0, unit="m"))
    by = (f.view.prep.steps.get("net_pay") or {}).get("written_by") or {}
    assert by.get("VP_VS_RATIO") == "hydrocarbon analysis", by
    cv = f.inv.curves["VP_VS_RATIO"]
    assert (cv.step, cv.by) == ("net_pay", "hydrocarbon analysis")
    assert "of the hydrocarbon analysis, in the net_pay step" in E.status(f, "VP_VS_RATIO")
    assert not any((c.step_from or "").startswith("petrophys curve map") for c in f.inv.curves.values())


@pytest.mark.parametrize("case", WELLS + ["ede"])
def test_every_reader_names_the_writer_the_record_gives(case):
    """D1 at every reader: each computed curve whose record names the analysis that wrote it (written_by) is credited
    to that analysis by its status, the map, the step tool and the source ranking (inventory.Curve.writer); a curve
    the record names no analysis for, to its step. Before, only the status read it."""
    from pathlib import Path
    from petroharness.agent import engine as E
    from petroharness.agent.map import render
    from petroharness.agent.tools import step
    if case == "ede":
        from _wells import Case
        las = Path(__import__("petrophys").__file__).parent / "datasets" / "epslog" / "ede_01_composite.las"
        if not las.exists():
            pytest.skip("no EDE-01 sample")
        f = formation_of(Case(str(las), top=1016.0, base=1316.0, unit="m"))
    else:
        f = formation_of(CASES[case])
    text = render(f.inv)
    named = 0
    for name, cv in f.inv.curves.items():
        if cv.source != "computed" or not cv.step or cv.carried or cv.copy_of:
            continue                                   # a measured log carried, or a copy: named as such
        by = ((f.view.prep.steps.get(cv.step) or {}).get("written_by") or {}).get(name, "")
        assert cv.by == by, (name, cv.by, by)
        want = f"the {by}, in the {cv.step} step" if by else f"the {cv.step} step"
        assert cv.writer == want and f"of {want}" in E.status(f, name), (name, E.status(f, name)[:200])
        if by:
            assert f"(written by {want})" in text, name
            assert f"{name} (written by {want})" in step(f, cv.step).text, name
            named += 1
    if case == "ede":
        assert named >= 1


# --- D3: a lithology choice is filled from the record, at the binder ---------------------------------------------------

def test_a_lithology_choice_left_unset_is_the_records_per_sample_lithology():
    """Petrophys declares the parameters that take the rock's lithology (role "lithology"); library_api.bind, which
    every Petrophys call passes, fills one left unset from the record per sample (a function on curves runs once per
    lithology, the results put together; a sample whose rock no option names takes the default), says so, and leaves
    one the model gives as given. Before, a run by name used the function's default (sandstone) for a carbonate."""
    import inspect
    from petrophys.interpretation.saturation.sonic.rock_physics import vs_from_vp_greenberg_castagna as gc
    from petroharness.agent import library as L, library_api as A
    f = formation_of(CASES["hw3"])
    dtc = np.asarray(f.view.values("DTC"), dtype=float)
    vp = 304800.0 / dtc
    full = np.full(np.asarray(f.view.prep.depth).size, np.nan)
    full[f.view.mask] = vp
    from petroharness.agent.library import register
    register(f, "VP_TEST", full, "Vp from DTC (test)", "m/s", "test")
    r = A.run(f, "calculate", "vs_from_vp_greenberg_castagna", {"vp_ms": "VP_TEST"})
    inputs = r.text.split("Inputs: ", 1)[1].split("\n")[0]
    assert "lithology each lithology of these samples (" in inputs, inputs
    choice, counts, gaps, _ = L.sample_lithology(f, ("sandstone", "limestone", "dolomite", "shale"))
    assert len(counts) > 1                                                  # a mixed well: grouped calls
    default = inspect.signature(gc).parameters["lithology"].default
    want = np.full(vp.size, np.nan)
    for k in list(counts) + [None]:
        on = np.asarray([c == k for c in choice], dtype=bool)
        if on.any():
            want[on] = gc(vp[on], k if k is not None else default)
    got = np.asarray(f.view.calculated[next(c for c in f.view.calculated if c.startswith("VS_FROM"))], dtype=float)
    got = got[f.view.mask] if got.size != vp.size else got
    ok = np.isfinite(want) & np.isfinite(got)
    assert ok.sum() > 100 and np.allclose(got[ok], want[ok])
    given = A.run(f, "calculate", "vs_from_vp_greenberg_castagna", {"vp_ms": "VP_TEST", "lithology": "dolomite"})
    assert "lithology dolomite (asked)" in given.text


@pytest.mark.parametrize("case", WELLS)
def test_every_lithology_parameter_is_filled_by_one_rule(case):
    """Every parameter of the registry Petrophys declares to take the rock's lithology, whatever its default (one,
    None, or required), is filled by the one rule (library_api._record_lithology): each sample's rock from the record,
    taken to an option by Petrophys (lithology_choice); an option of the parameter, per sample where the record holds
    several, or Petrophys's default said when no option names the rock. Before, a label matched an option by
    substring ("ss" in "massive"; SHALY SANDSTONE never took shaly_sandstone; HALITE took sandstone)."""
    from petroharness.agent import library_api as A
    f = formation_of(CASES[case])
    seen = 0
    for fn in A.registry():
        for p, d in fn.kinds.items():
            if getattr(d, "role", None) != "lithology":
                continue
            seen += 1
            options = {str(c).lower() for c in d.choices}
            value, said = A._record_lithology(f, fn, p)
            if value is A._UNSET:
                assert "Petrophys's default: no option" in said, (fn.name, p, said)
            elif isinstance(value, A._ByLithology):
                assert {v for v in value.tolist() if v is not None} <= options and "each lithology" in said, (fn.name, p)
            else:
                one = value[0] if d.many else value
                assert one in options and "the record's lithology" in said, (fn.name, p, value, said)
    assert seen >= 7, seen


def test_a_result_not_one_per_sample_is_given_for_each_lithology():
    """A function whose result is not one value per sample (Archie defaults by formation type) on a well of several
    lithologies: each lithology's result is given, and the model reads the one it needs (G6). Before, code ran it on
    the most common lithology alone."""
    from petroharness.agent import library as L, library_api as A
    f = formation_of(CASES["hw3"])
    fn = A.lookup("default_archie_params")
    _, counts, _, _ = L.sample_lithology(f, [str(c).lower() for c in fn.kinds["formation_type"].choices])
    assert len(counts) > 1
    text = A.run(f, "calculate", "default_archie_params", {}).text
    assert "so it is given for each lithology, computed on all these samples" in text, text[:400]
    for k in counts:
        assert re.search(rf"(?<![a-z_]){re.escape(k)}\b", text.split("Inputs:", 1)[1]), (k, text[:600])


# --- O2: Petrophys's advice as data -----------------------------------------------------------------------------------

def test_petrophys_advice_names_its_inputs_as_data_and_the_call_door_reads_them():
    """Petrophys's advice ('pass formations=...', 'add steps.mud_filtrate(rmf=..., rmf_temp_f=...)') carries the inputs
    it asks for (petrophys._internal.advice.Advice: a str with .inputs), through exceptions, warnings, joins and
    rewordings; the call door collects them from every message a call shows and from its refusal's exception chain
    (engine.advised), and reads no sentence for them (the regex over 'name=' is gone)."""
    import warnings
    from petrophys._internal.advice import Advice, joined, restated
    from petroharness.agent import engine as E, schemas
    token = E.ADVISED.set([])
    try:
        try:
            raise ValueError(Advice("needs the water salinity: calculate(well, salinity=...)", ("salinity",)))
        except ValueError:
            try:
                raise E.ToolError("Petrophys rw: needs the water salinity") from None
            except E.ToolError as refusal:
                E.advised(refusal)                       # the refusal's context: Petrophys's own error
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warnings.warn(Advice("add steps.temperature(bht_f=...) first", ("bht_f",)))
        E.said_whole([w.message for w in caught] + [restated("mhi: " + joined(["x", Advice("rmf=...", ("rmf",))]),
                                                              joined(["x", Advice("rmf=...", ("rmf",))]))])
        assert E.ADVISED.get() == ["salinity", "bht_f", "rmf"]
    finally:
        E.ADVISED.reset(token)
    said = schemas.advice(["rmf", "rmf_temp_f"], "calculate", ["property", "method", "parameters"], {"property": "saturation"})
    assert said.startswith('as tool calls: {"calculate": {"property": "mud_filtrate_resistivity"')
    assert schemas.advice([], "stats", ["curves"], {}) == ""


# --- O4: codes the labels name alike are one class (F11) ---------------------------------------------------------------

def test_codes_named_alike_are_one_class_wherever_classes_are_counted():
    """Question suite F11 (S02): the data's code table names codes 9 and 12 LIMESTONE (5 and 6 SILT); class shares
    listed 'class 12 (LIMESTONE)' and 'class 9 (LIMESTONE)' apart. Every class count (summary.class_counts, with the
    record's labels) pools codes named alike into one class, written '9, 12 (LIMESTONE)'."""
    from petroharness.well import summary as S
    labels = {5.0: "SILT", 6.0: "SILT", 9.0: "LIMESTONE", 12.0: "LIMESTONE", 2.0: "SANDSTONE"}
    x = np.array([5, 6, 6, 9, 12, 12, 12, 2, np.nan])
    n, counts = S.class_counts(x, [2.0, 5.0, 6.0, 9.0, 12.0], labels)
    assert n == 8 and counts == [(2.0, 1), ((5.0, 6.0), 3), ((9.0, 12.0), 4)]
    assert [S.code_text(k, labels) for k, _ in counts] == ["2 (SANDSTONE)", "5, 6 (SILT)", "9, 12 (LIMESTONE)"]
    assert S.class_counts(x, [2.0, 5.0, 6.0, 9.0, 12.0])[1][1] == (5.0, 1)            # without labels: each code
    from petroharness.agent import schemas
    f = formation_of(CASES["1671"])
    lab = S.code_labels(f.view, f.view.lithology_curve) if f.view.lithology_curve else {}
    alike = {v for v in lab.values() if list(lab.values()).count(v) > 1}
    if f.view.lithology_curve and alike:
        t = schemas.call(f, "stats", {"curves": [f.view.lithology_curve]}).text
        for name in alike:
            assert t.count(f"({name})") <= t.count("\n") and not any(
                ln.count(f"({name})") > 1 for ln in t.splitlines()), name       # one class per line, named once


# --- O5: a curve name the record does not hold (F13) -------------------------------------------------------------------

def test_a_curve_name_the_record_does_not_hold_close_to_one_it_holds_is_flagged():
    """Question suite F13 and golden t496421020e: the writer wrote INVAISION_RATIO for INVASION_RATIO. writer.
    unknown_names flags a mnemonic-shaped name (an underscore or a digit) the record does not hold and the writer was
    not shown, when it is a near miss of a curve the record holds; the repair names the record's curve. A word, a class
    label or a name the writer was shown is left alone (measured on 168 answers: the near misses were misspellings)."""
    from types import SimpleNamespace as NS
    from petroharness.agent.graph import _repair_ask
    from petroharness.agent.writer import unknown_names
    f = formation_of(CASES["brent"])
    assert "INVASION_RATIO" in f.inv.curves
    text = "INVAISION_RATIO reads 3.2; INVASION_RATIO reads 3.1; GOOD_PERMEABILITY; HIGH rock; FOO_BAR_9 here"
    got = unknown_names(text, NS(f=f), shown="the classes GOOD_PERMEABILITY and VERY_GOOD_PERMEABILITY")
    assert got == [("INVAISION_RATIO", "INVASION_RATIO")], got
    ask = _repair_ask([], [], [], [], text, got)
    assert "INVAISION_RATIO (the record holds INVASION_RATIO)" in ask


# --- R4: a step run again starts from the record's run ---------------------------------------------------------------

@pytest.mark.parametrize("case", WELLS)
def test_a_word_the_record_states_for_a_step_parameter_is_its_baseline(case):
    """library.defaults (the baseline of what_if and calculate, and the menu) is Petrophys's reading of the record
    (steps.recorded_arguments): every word the record states for an argument that takes it (one of the argument's
    choices, Petrophys's step_choices) is the record's value, as its numbers are; the harness keeps no table of the
    record's names. The clay-volume step's nd_matrix (sandstone in the record) ran at the library's default."""
    from petrophys.workflow.steps import RECORDED_AS, step_choices
    from petroharness.agent import library as L
    f = formation_of(CASES[case])
    words, checked = step_choices(), 0
    assert not hasattr(L, "RECORD_NAMES") and not hasattr(L, "RECORD_STEP")
    for kind in ("porosity", "clay_volume", "saturation", "permeability", "net_pay"):
        m = L._method(f, kind)
        if m is None:
            continue
        rec, base, menu = dict(m.parameters or {}), L.defaults(f, kind), L.menu(f, kind).text
        for key, takes in words.items():
            k, p = key.split(".")
            if k != kind or p in ("method", "model"):
                continue
            stated = next((str(rec[n]).strip().lower() for n in (p, *RECORDED_AS.get(p, ()))
                           if isinstance(rec.get(n), str) and str(rec[n]).strip().lower() in takes), None)
            if stated:
                assert base.get(p) == stated and f"  {p} = {stated} (record)" in menu, (kind, p, stated, base)
                checked += 1
            else:
                assert p not in base or base[p] in takes, (kind, p, base)
    assert checked >= 2, checked


def test_a_step_refusal_names_the_calls_that_take_the_inputs_it_asks_for():
    """O2 through a real call: a step Petrophys refuses for missing inputs (Waxman-Smits without its CEC) keeps its
    Advice through Petrophys's joins of messages (its parameter checks, a step's requirements, a run's errors), and the
    call door names the tool call that takes them. The review found sibling joins that dropped the inputs."""
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    f = formation_of(CASES["brent"])
    with pytest.raises(ToolError) as got:
        schemas.call(f, "calculate", {"property": "saturation", "parameters": {"model": "waxman_smits"}})
    text = str(got.value)
    assert "needs cec=" in text and '"cec": ...' in text and '"b_coeff": ...' in text, text


def test_petrophys_leaves_no_input_asked_for_in_plain_text():
    """Petrophys's own check (petrophys._internal.advice.unwrapped_asks): every message that asks for an input by name
    is an Advice carrying it, so the call door never reads a sentence for it."""
    from petrophys._internal.advice import unwrapped_asks
    assert unwrapped_asks() == []


# --- R10: a range written with a unit's own depths is that unit --------------------------------------------------------

def test_a_range_with_a_units_top_and_base_is_that_unit_named_with_its_depths():
    """Question suite B01, B10: the READ wrote the Ness Fm.'s depths (as the map lists them) for "the Ness Formation",
    and the answer named a bare range. A range whose top and base are a unit's own (within half a sample) is that unit,
    on its samples, named "Ness Fm. (2841-2865 m)", for a scope and a tool's zones alike (selection._item)."""
    from types import SimpleNamespace as NS
    from petroharness.agent import loop, selection
    f = formation_of(CASES["brent"])
    u = next(x for x in f.view.units if x.name.upper().startswith("NESS"))
    rng = f"{u.top:g}-{u.base:g} m"
    on = selection.resolve(f, [rng], force=True)[0]
    by_name = selection.resolve(f, [u.name], force=True)[0]
    assert selection.same_samples(on.view, by_name.view) and on.view.selection == f"{u.name} ({rng})"
    s = NS(f=f, scope=[], scope_note="", scope_merged="", scope_by_user=False, frame=None)
    loop.apply_scope(s, [rng])
    assert s.scope == [f"{u.name} ({rng})"], s.scope
    d = np.asarray(f.view.prep.depth, dtype=float) * f.view.depth_scale        # X18: the unit's last sample for its
    last = float(d[(d < u.base)][-1]) if not u.closed else float(d[d <= u.base][-1])   # base: its samples, that unit
    tight = f"{u.top:g}-{last:.4f} m"
    assert selection.resolve(f, [tight], force=True)[0].view.selection.startswith(f"{u.name} (2841-")
    other = selection.resolve(f, [f"{u.top + 1:g}-{u.base:g} m"], force=True)[0]   # not the unit's top: a range
    assert other.view.selection == f"{u.top + 1:g}-{u.base:g} m"


@pytest.mark.parametrize("case", ["brent", "cheal", "tuhua", "hw3", "hw3_m"])
def test_every_name_the_harness_writes_for_a_stretch_selects_that_stretch(case):
    """Question suite B10, T01, X20 (30 refused lookups): a scope read as a unit's depths was kept as its label,
    "Etive Fm. (2865-2958 m)", which became every lookup's default zones and the SCOPE line the model copies, and the
    selection could not read it ("no zone or unit Etive Fm. (2865-2958 m)"). Every name the harness writes for a
    stretch (a scope's label, a result's header with its depths, the interval's name) selects the samples it names,
    for every unit of every well with a tops file."""
    from types import SimpleNamespace as NS
    from petroharness.agent import loop, selection
    f = formation_of(CASES[case])
    unit = f.view.report_unit
    checked = 0
    for u in f.view.units:
        try:
            by_name = selection.resolve(f, [u.name], force=True)[0]
        except Exception:
            continue                                     # a unit with no sample here, listed twice, or a zone's name
        s = NS(f=f, scope=[], scope_note="", scope_merged="", scope_by_user=False, frame=None)
        loop.apply_scope(s, [f"{u.top:g}-{u.base:g} {unit}"])
        written = list(s.scope) + [f"{u.name} {u.top:g}-{u.base:g} {unit}", f"{u.name} ({u.top:g}-{u.base:g} {unit})"]
        for w in written:
            on = selection.resolve(f, [w], force=True)[0]
            assert selection.same_samples(on.view, by_name.view) or (on is f and by_name is f), (u.name, w)
        checked += 1
    assert checked >= 1, checked
    own = selection.interval_name(f)                     # the interval, by the name every scope-less line gives it
    on = selection.resolve(f, [own], force=True)[0]
    assert on is f or selection.same_samples(on.view, f.view), own


# --- R02: where a log is recorded --------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", ["brent", "cheal", "hw3", "teapot"])
def test_a_selections_whole_line_says_where_a_partial_curve_has_values(case):
    """Question suite R02: "over which depths is RXO recorded" was answered with a lithology row's base (3575.615 m)
    for its last reading (3573.18 m); no result said where a curve's values lie. The whole line of a stats result says
    the first and last sample with a value of every curve that has values at only part of the selection's samples (the
    zones pooled line when it is the whole), and says nothing of the kind for a curve with a value at every sample."""
    from petroharness.agent import engine as E, schemas
    from petroharness.agent.map import num
    f = formation_of(CASES[case])
    d = np.asarray(f.view.depth, dtype=float)
    u = f.inv.depth_unit
    seen = {"part": 0, "full": 0}
    for c in sorted(f.inv.curves):
        if E.kind(f, c).kind != "values":
            continue
        x = np.asarray(f.view.values(c), dtype=float)
        if not np.isfinite(x).any() or (seen["part"] >= 3 and seen["full"] >= 3):
            continue
        lines = [ln for ln in schemas.call(f, "stats", {"curves": [c]}).text.splitlines() if f", {c}: n " in ln]
        whole = [ln for ln in lines if ln.strip().startswith("whole interval")]       # the widest line shown: the
        if whole:                                                                     # zones pooled when it is the
            idx = np.arange(x.size)                                                   # whole (no value outside them)
        else:
            whole = [ln for ln in lines if ln.strip().startswith("zones pooled")]
            idx = np.sort(np.concatenate([np.asarray(z.indices) for z in f.view.zones]))
        if not whole:
            continue
        ok = np.isfinite(x[idx])
        d_ = d[idx]
        if ok.all():
            assert "values from" not in whole[0], (c, whole[0])
            seen["full"] += 1
        else:
            said = f"values from {num(float(d_[ok][0]))} {u} to {num(float(d_[ok][-1]))} {u}"
            assert said in whole[0], (c, said, whole[0])
            seen["part"] += 1
    assert seen["part"] >= 1 and seen["full"] >= 1, seen


# --- X18: a where that keeps no sample of the call's stretch ------------------------------------------------------------

def test_a_where_that_keeps_no_sample_of_the_stretch_says_so_with_the_stretch():
    """Question suite X18: under a Ness scope the model asked for the Etive with where "2865-2958 m"; every row read
    "GR: n 0 of 30" and the answer said the Etive had no GR. A where that keeps no sample of the stretch a call
    computes on is said on the result's where line (engine.where_none, the one line every tool's where writes): that
    stretch and its depths, that every count is 0 for that reason, and how a call computes elsewhere. A finding, not a
    refusal (no pay in a formation is an answer); a where that keeps samples says nothing of the kind."""
    from petroharness.agent import schemas
    f = formation_of(CASES["brent"])
    ness = next(u for u in f.view.units if u.name.upper().startswith("NESS"))
    etive = next(u for u in f.view.units if u.name.upper().startswith("ETIVE"))
    window = f"{etive.top:g}-{etive.base:g} m"
    for tool, args in [("stats", {"curves": ["GR"]}), ("compare", {"a": "GR", "b": "RHOB"}),
                       ("crossplot", {"x": "NPHI", "y": "RHOB"}), ("profile", {"curve": "GR"})]:
        text = schemas.call(f, tool, {**args, "zones": [ness.name], "where": window}).text
        line = next(ln for ln in text.splitlines() if ln.startswith("Samples where"))
        assert f"it holds at no sample of {ness.name} (" in line and "every count below is 0" in line \
            and "naming it in zones" in line, (tool, line)
        ok = schemas.call(f, tool, {**args, "zones": [etive.name], "where": window}).text   # the window inside
        assert "holds at no sample" not in ok, tool


# --- X23: a measured temperature log's gaps ----------------------------------------------------------------------------

def test_a_temperature_logs_gaps_are_filled_continuous_with_it():
    """Question suite X23: cheal-1's TEMP log (a mud temperature, about 59 degC at the base) has 13 gaps at the base,
    which Petrophys filled with an unanchored 30 C/km profile from the surface: TEMP jumped from 138.9 to 221.8 degF
    within 2 m and the answer gave 105 degC for the base. The fill is the profile shifted to meet the log at each
    gap's ends (petrophys dynamic_workflow._fill_from_log): no step at a gap's edge beyond the log's own steps."""
    from petrophys.workflow.dynamic_workflow import _fill_from_log
    d = np.arange(0.0, 100.0, 1.0)
    log = 50.0 + 0.02 * d
    profile = 20.0 + 0.03 * d
    ok = np.ones(d.size, dtype=bool)
    ok[40:50] = False                                     # inside: the offset runs linearly between the gap's ends
    ok[90:] = False                                       # at the end: the last reading's offset, the profile's slope
    got = _fill_from_log(d, np.where(ok, log, np.nan), profile, ok)
    assert np.allclose(got[ok], log[ok])
    assert np.allclose(got[40:50], log[40:50]) and np.allclose(np.diff(got[89:]), 0.03)
    assert abs(got[90] - log[89]) < 0.05
    f = formation_of(CASES["cheal"])
    v = f.view
    t, raw = (np.asarray(v.well_values(c), dtype=float) for c in ("TEMP", "TEMP_LOG"))
    gap = ~np.isfinite(raw) & np.isfinite(t)
    assert gap.any(), "cheal-1's TEMP log has gaps"
    own = np.nanmax(np.abs(np.diff(raw)))
    edges = np.flatnonzero(np.diff(gap.astype(int)) != 0)
    unit = getattr(f.inv.curves.get("TEMP_LOG"), "unit", "") or ""
    scale = 1.8 if unit.upper().startswith("C") or unit.lower().startswith("deg c") else 1.0   # TEMP is degF
    assert all(abs(t[i + 1] - t[i]) <= scale * own + 1.0 for i in edges), [(i, t[i], t[i + 1]) for i in edges]


def test_values_at_gives_a_curves_nearest_reading_where_the_sample_has_none():
    """Question suite X23: values_at read TEMP_LOG at the Moki base, where the log has a gap, as "no value" at five
    depths; the answer gave the filled TEMP. A curve with no value at a depth's nearest sample says its nearest
    reading, its depth and how far it lies."""
    from petroharness.agent import schemas
    from petroharness.agent.map import num
    f = formation_of(CASES["cheal"])
    v = f.view
    d = np.asarray(v.prep.depth, dtype=float) * v.depth_scale
    raw = np.asarray(v.well_values("TEMP_LOG"), dtype=float)
    ok = np.flatnonzero(np.isfinite(raw))
    i = int(np.flatnonzero(~np.isfinite(raw))[-1])                       # a gap: its nearest reading
    j = int(ok[np.argmin(np.abs(d[ok] - d[i]))])
    t = schemas.call(f, "values_at", {"curves": ["TEMP_LOG"], "depths": [round(float(d[i]), 4)]}).text
    assert f"TEMP_LOG no value (its nearest reading {num(float(raw[j]))} at {num(float(d[j]))} " in t, t


# --- benchmark N2: the claim check's numbers after it cites ------------------------------------------------------------

def test_the_claim_check_names_holders_for_every_number_it_flags_after_citing(monkeypatch):
    """Benchmark N2 (one of 347 questions, KeyError '0.1864'): the claim check cites the results that hold a flagged
    number and checks again on the cited set; the second pass flagged a number the first had passed, and the holders
    were looked up for the first pass's numbers only. Holders are read for every number the final pass flags."""
    import re as _re
    from petroharness.agent.claims import Claims
    from petroharness.agent.loop import Session
    from petroharness.config import given_settings
    from _wells import task_cfg
    task, cfg, data = task_cfg(CASES["brent"], "c")
    with given_settings({"data": data, "eval": {}}):
        s = Session.build(task, cfg)
        s.run(("tool", "stats", {"curves": ["PHIE"]}))
    item = s.ledger.items[-1]
    long = next(m.group(0) for m in _re.finditer(r"\d{4,}\.\d+", item.text))   # held by this one result: cited
    passes = iter([[long], ["0.1864"]])
    monkeypatch.setattr(Claims, "_unsupported", lambda self, text, cited: next(passes, ["0.1864"]))
    claims = Claims(["p"], s.ledger, s.map, task.question, s.f.view, (task.well,))
    msgs = claims.apply([{"op": "add", "point": 1, "text": f"PHIE at {long} and 0.1864", "ev": [], "grade": "moderate"}])
    c = next(iter(claims.claims.values()))
    assert not msgs and item.id in c.ev and "0.1864" in c.unshown, (msgs, c.ev, c.unshown)


# --- X13: a curve read at a depth --------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", ["brent", "hw3"])
def test_values_at_gives_each_nearest_sample_and_a_ranges_samples(case):
    """Question suite X13: no tool read a curve at a depth; the answer called a stretch's extremes its nearest samples.
    tools.values_at: each depth's nearest sample of the well, its distance, where it lies and each curve's value (the
    view's whole-well values); a depth past the log says where the log ends; a range lists its samples; a depth in the
    other unit converts as a range's limits do."""
    from petroharness.agent import schemas
    f = formation_of(CASES[case])
    v = f.view
    d = np.asarray(v.prep.depth, dtype=float) * v.depth_scale
    c = next(x for x in ("GR", "RHOB", "PHIE") if x in f.inv.curves)
    x = np.asarray(v.well_values(c), dtype=float)
    ok = np.flatnonzero(np.isfinite(x) & np.asarray(v.mask, dtype=bool))
    i = int(ok[len(ok) // 2])
    want = float(d[i]) + 0.3 * float(np.median(np.diff(d)))                  # off the sample, nearest to it
    t = schemas.call(f, "values_at", {"curves": [c], "depths": [round(want, 4), float(d[-1]) + 100]}).text
    from petroharness.agent.map import num
    assert f"{num(float(d[i]))} {f.inv.depth_unit}" in t and f"{c} {num(float(x[i]))}" in t, t
    assert "beyond the log, which spans" in t
    rng = schemas.call(f, "values_at", {"curves": [c], "depths": [f"{d[i]:.4f}-{d[i + 2]:.4f}"]}).text
    assert ": 3 samples" in rng and rng.count(f" {c} ") == 3, rng
    other = "ft" if f.inv.depth_unit == "m" else "m"
    conv = d[i] / 0.3048 if other == "ft" else d[i] * 0.3048
    t2 = schemas.call(f, "values_at", {"curves": [c], "depths": [f"{conv:.3f} {other}"]}).text
    assert f"{num(float(d[i]))} {f.inv.depth_unit}" in t2, t2


# --- X25: a curve the record holds, screened out here; a number with its unit ------------------------------------------

def test_a_curve_screened_out_here_is_said_held_with_what_the_screening_removed():
    """Question suite X25 (16/7-1, 2000-2560 m): DTC's readings there lie outside Petrophys's plausible range and the
    preparation masked them; the question note said DTC was 'not in this well's record' and the answer that the well
    had no sonic log. The note now tells a curve the record does not hold from one it holds with no value here, and
    what the range screening removed (Petrophys metadata.custom["range_screening"]); the map's empty-log line and a
    screened curve's caution read the same record (summary.screened)."""
    from types import SimpleNamespace as NS
    from petroharness.agent import engine as E, vocabulary
    from petroharness.agent.map import render
    from petroharness.well.summary import screened
    from _wells import Case
    las = Path(__import__("petrophys").__file__).parent / "datasets" / "geolink" / "16_7-1.las"
    f = formation_of(Case(str(las), top=2000.0, base=2560.0, unit="m"))
    said = screened(f.view, "DTC")
    assert said.startswith("range screening removed ") and "us/ft" in said and said.endswith("left out too"), said
    assert f"DTC ({said})" in render(f.inv)
    s = NS(f=f, task=NS(question="What is the mean sonic slowness DTC where the gamma ray is above 100 API?"), reading={})
    text = vocabulary.note(s)
    assert "Named, in this well's record but with no values in this interval:" in text and f"DTC: {said}" in text, text
    assert "Named but not in this well's record" not in text or "DTC" not in text.split("Named but not", 1)[1].split("\n")[0]
    for c in f.inv.curves:                     # a curve with values here: a caution only where Petrophys judges it
        assert ("range screening" in E.status(f, c)) == bool(screened(f.view, c)), c   # mostly implausible
    brent = formation_of(CASES["brent"])       # a few spikes masked (GR, RHOB, CALI): no caution
    assert not any("range screening" in E.status(brent, c) for c in brent.inv.curves)
    gr = np.asarray(f.view.values("GR"), dtype=float)
    assert int(E.select(f, "GR > 100 API").mask.sum()) == int(np.nansum(gr > 100))   # a number with the curve's unit
    with pytest.raises(E.ToolError, match="GR is in"):
        E.select(f, "GR > 100 ohm.m")


# --- X18: a worked-out number the repair keeps -------------------------------------------------------------------------

def test_a_difference_of_numbers_stated_elsewhere_is_named_for_the_repair():
    """Question suite X18: "higher in the Ness by about 18.87 API" was flagged (the two means stood in the next
    sentence) and the repair's "or remove it" removed the answer's amount. checks.derivations finds the arithmetic of
    numbers the answer states elsewhere, each shown by a result, and the repair ask names it so the writer keeps the
    number with its inputs beside it; the check itself still reads the sentence."""
    from petroharness.agent.checks import derivations, number_provenance
    from petroharness.agent.graph import _repair_ask
    card = "GR mean 75.0116 in R1; GR mean 56.1434 in R2"
    draft = "GR is higher in the Ness by about 18.87 API. Ness mean 75.0116 API; Etive mean 56.1434 API."
    bad, _ = number_provenance(draft, card, [])
    assert bad == ["18.87"], bad
    worked = derivations(draft, card, [], bad)
    assert worked == {"18.87": ("elsewhere", "75.0116 - 56.1434")}, worked
    ask = _repair_ask(bad, [], [], [], draft, (), worked)
    assert "18.87" in ask and "= 75.0116 - 56.1434" in ask and "keep the number and write those beside it" in ask
    assert derivations("It is 12.5 here. Ness mean 75.0116.", card, [], ["12.5"]) == {}    # no arithmetic gives it
    fixed = "GR is higher in the Ness by about 18.87 API (75.0116 - 56.1434)."
    assert not number_provenance(fixed, card, [])[0]


@pytest.mark.parametrize("case", WELLS)
def test_a_step_that_writes_one_curve_of_values_gives_its_range_here(case):
    """Question suite X06: the record's temperature range is the whole well's, and the answer gave no temperature for
    the unit asked. A step that writes one curve of values (temperature, rw, rmf, bvw, ...) gives its range in this
    interval among its facts (catalog.interval_facts), equal to numpy's; a step that writes several gives none."""
    from petroharness.record.catalog import interval_facts
    from petroharness.well.summary import curve_kind
    f = formation_of(CASES[case])
    seen = 0
    for name, st in (f.view.prep.steps or {}).items():
        outs = [o for o in st.get("outputs") or [] if f.view.available(o)]
        vals = [o for o in outs if curve_kind(f.view, o).kind == "values"]
        lines, _ = interval_facts(f.view, st.get("outputs") or [])
        ranged = [ln for ln in lines if re.match(r"^[A-Z][A-Z0-9_]* from -?[\d.e+-]+ to ", ln)]
        if len(vals) != 1:
            assert not ranged, (name, ranged)
            continue
        x = np.asarray(f.view.values(vals[0]), dtype=float)
        if np.isfinite(x).any():
            m = re.match(rf"^{vals[0]} from (\S+) to (\S+)", ranged[0])
            assert m and abs(float(m.group(1)) - np.nanmin(x)) <= 1e-3 * max(1, abs(np.nanmin(x))), (name, ranged)
            assert abs(float(m.group(2)) - np.nanmax(x)) <= 1e-3 * max(1, abs(np.nanmax(x))), (name, ranged)
            seen += 1
    assert seen >= 2, seen



def test_arithmetic_written_out_is_given_its_value_and_a_product_or_a_mean_is_derived():
    """Benchmark N1 (11-20): the writer's arithmetic slipped in the last digits ("0.1417 / 0.2688 ≈ 0.5277", 0.5272;
    "4640 - 3159 = 481"), and the checker flagged correct work it did not read: a product ("0.875 x 27.5 ft = 24.0625",
    a share of a thickness) and the mean of values a sentence lists ("roughly 1.63 (1.6911, 1.541, 1.6435)"). A
    product and a mean of a listed run are derived numbers; arithmetic written out right before a flagged number is
    computed, and the repair says its value."""
    from petroharness.agent.checks import derivations, number_provenance
    from petroharness.agent.graph import _repair_ask
    card = "Z1 BVW 0.1417 PHIE_CC 0.2688\nNET_PAY fraction 0.875 zoned 27.5 ft\nratios 1.6911 1.541 1.6435\n4640 samples, 3159 valid"
    assert number_provenance("Z2 pay is 0.875 x 27.5 ft = 24.0625 ft.", card, [])[0] == []
    assert number_provenance("The sands read roughly 1.63 (1.6911, 1.541, 1.6435).", card, [])[0] == []
    text = "Z1 shows 0.1417 / 0.2688 ≈ 0.5277 v/v. NPHI is missing at 4640 − 3159 = 481 samples."
    bad, _ = number_provenance(text, card, [])
    assert set(bad) >= {"0.5277", "481"}, bad
    worked = derivations(text, card, [], bad)
    assert worked["0.5277"] == ("wrong", "0.1417 / 0.2688", "0.5272") and worked["481"] == ("wrong", "4640 - 3159", "1481")
    ask = _repair_ask(bad, [], [], [], text, (), worked)
    assert "0.1417 / 0.2688 is 0.5272, write 0.5272" in ask and "4640 - 3159 is 1481, write 1481" in ask, ask


# --- the condition grammar reads what the harness writes, and the usual ways of writing a condition -------------------

def _selections(f) -> list:
    """Every kind of name a condition takes, one each per flag, class, zone, curve: the conditions to read back."""
    from petroharness.agent.engine import Out
    out = [c for c in f.inv.curves if f.view.is_flag(c)][:6] + [c for c in f.inv.curves if not f.view.is_flag(c)][:6]
    out += [lab for sec in (f.store.sections.values() if f.store is not None else []) for lab in sec.classes][:12]
    out += [z.zone_id for z in f.view.zones][:4] + [f"{f.view.zones[0].zone_id}-{f.view.zones[-1].zone_id}"]
    out += [f"{float(f.depth[2])}-{float(f.depth[-3])}", Out(f).zone(f.view.zones[0])]
    return out


@pytest.mark.parametrize("case", WELLS)
def test_every_selection_the_harness_writes_reads_back_to_the_same_samples(case):
    """Every result says which samples it read ("NET_PAY > 0.5", "PEF has a value", "CLASS (section)", "in Z2",
    "depth A-B m"); given back as a condition (models copy it), each selects the same samples (benchmark N3/N4: 49 calls
    refused, among them the harness's own names)."""
    from petroharness.agent.engine import ToolError, select
    f = formation_of(CASES[case])
    checked = 0
    for c in _selections(f):
        try:
            sel = select(f, c)
        except ToolError as e:
            if "is a class in" in str(e):                    # a class in several sections: written section:CLASS
                continue
            raise
        again = select(f, sel.read)
        assert np.array_equal(sel.mask, again.mask), (c, sel.read)
        checked += 1
    assert checked >= 8


@pytest.mark.parametrize("case", WELLS)
def test_every_zone_written_with_its_name_or_depths_is_that_zone_in_a_condition(case):
    from petroharness.agent.engine import Out, select, zone_name
    f = formation_of(CASES[case])
    for z in f.view.zones:
        want = select(f, z.zone_id).mask
        for written in (Out(f).zone(z), f"{z.zone_id} {zone_name(z)}", f"{z.zone_id} ({zone_name(z)})",
                        f"in {z.zone_id}", f"{z.zone_id} {z.lithology}".lower()):
            assert np.array_equal(select(f, written).mask, want), written
    from petroharness.agent.engine import ToolError
    with pytest.raises(ToolError):
        select(f, f"{f.view.zones[0].zone_id} versus the rest")           # words that are not the zone's: refused


def test_a_condition_written_with_symbols_words_or_a_chain_is_its_plain_grammar():
    from petroharness.agent.engine import select
    f = formation_of(CASES["brent"])
    same = [("GR < 40 | GR > 120", "GR < 40 or GR > 120"), ("GR < 40 || GR > 120", "GR < 40 or GR > 120"),
            ("GR > 40 & RHOB > 2.3", "GR > 40 and RHOB > 2.3"), ("GR > 40 && RHOB > 2.3", "GR > 40 and RHOB > 2.3"),
            ("|DRHO| > 0.02 | GR > 120", "abs(DRHO) > 0.02 or GR > 120"), ("| DRHO | > 0.02", "|DRHO| > 0.02"),
            ("0.2 <= VCL <= 0.5", "VCL >= 0.2 and VCL <= 0.5"), ("0.5 > VCL > 0.2", "VCL < 0.5 and VCL > 0.2"),
            ("GR below 40", "GR < 40"), ("GR is above 120", "GR > 120"), ("GR at least 120", "GR >= 120"),
            ("VCL less_than 0.3", "VCL < 0.3"), ("PEF has a value", "PEF"), ("RHOB has values", "RHOB"),
            ("Z1 | Z3", "Z1 or Z3"), ("Z1|Z3", "Z1 or Z3")]
    for written, plain in same:
        assert np.array_equal(select(f, written).mask, select(f, plain).mask), written
        assert select(f, written).mask.any(), written


def test_a_verb_asked_for_a_tool_by_name_runs_that_tool_and_a_next_item_of_two_calls_is_two():
    """Question suite B05: {"check": {"what": "threshold_exceedance", ...}} was refused ("no check"), and
    {"stats": {...}, "check": {...}} ran stats only (check read as its argument, ignored)."""
    from petroharness.agent.loop import split_actions
    from petroharness.agent.schemas import call
    f = formation_of(CASES["brent"])
    direct = call(f, "threshold_exceedance", {"curve": "RHOB", "threshold": 2.5})
    routed = call(f, "check", {"what": "threshold_exceedance", "curves": ["RHOB"], "threshold": 2.5, "zones": ["ALL"]})
    assert direct.text in routed.text and "threshold_exceedance is a tool of its own" in routed.text
    run = call(f, "calibrate", {"run": "core_vs_log", "args": {}})                  # a verb's run naming a tool (N6)
    assert "core_vs_log is a tool of its own" in run.text and call(f, "core_vs_log", {}).text in run.text
    two = split_actions([{"stats": {"curves": ["RHOB"]}, "check": {"what": "held_readings"}}, {"get": "E1", "find": "Z2"}])
    assert two == [{"stats": {"curves": ["RHOB"]}}, {"check": {"what": "held_readings"}}, {"get": "E1", "find": "Z2"}]


def test_an_order_written_as_a_chain_of_curves_is_that_order():
    from petroharness.agent.engine import ToolError
    from petroharness.agent.schemas import call
    f = formation_of(CASES["brent"])
    plain = call(f, "curve_order", {"curves": ["RDEP", "RMED"], "relation": "decreasing"}).text
    assert call(f, "curve_order", {"curves": ["RDEP", "RMED"], "relation": "RDEP > RMED"}).text == plain
    assert call(f, "curve_order", {"relation": "RDEP > RMED"}).text == plain
    assert call(f, "curve_order", {"curves": ["RDEP", "RMED"], "relation": ">"}).text == plain
    assert call(f, "curve_order", {"curves": ["RMED", "RDEP"], "relation": "RMED < RDEP"}).text == \
        call(f, "curve_order", {"curves": ["RMED", "RDEP"], "relation": "increasing"}).text
    with pytest.raises(ToolError):
        call(f, "curve_order", {"curves": ["RDEP", "GR"], "relation": "RDEP > RMED"})


def test_the_basis_of_a_value_is_one_text_every_prompt_that_states_numbers_reads():
    """Question suite C01: the step's claim gave the zones-pooled plugs (203) for the well's 331, and the writer kept
    it; the basis rule was the writer's only. One text (C4 basis), in the brief the claims are written under and in
    both writer prompts."""
    from petroharness.agent import components as C
    from petroharness.agent import loop
    basis = C.text("C4", "basis")
    assert "whole line" in basis and "{basis}" not in loop.brief()
    assert basis in loop.brief() and basis in C.prompt("C9", "write")
    assert basis in C.prompt("C9", "reply_brief")
    assert all("{basis}" in C.text(c, e) for c, e in (("C1", "brief"), ("C9", "write"), ("C9", "reply_brief")))
    assert not any("whole line" in C.text(c, e) for c, e in (("C1", "brief"), ("C9", "write"), ("C9", "reply_brief")))


def test_a_search_sent_as_an_action_of_its_own_is_the_verbs_search():
    """Benchmark hw-7 (N1, N3, N4): a direct step's lookups were all {"search": ...} sent bare, none read, and the
    question went to an investigation (W 39-77 where the reference's direct reply scored 76-90)."""
    from petroharness.agent.loop import VERBS_RUN, coerce_action, split_actions
    assert coerce_action({"search": "density correction", "where": "calculate"}) == \
        ("tool", "calculate", {"search": "density correction"})
    assert coerce_action({"search": {"calibrate": "core porosity"}}) == ("tool", "calibrate", {"search": "core porosity"})
    bare = coerce_action({"search": "density correction"})
    assert bare[0] == "tool" and bare[1] in VERBS_RUN and bare[2] == {"search": "density correction"}
    assert coerce_action({"calculate": {"search": "gas"}}) == ("tool", "calculate", {"search": "gas"})   # as before
    assert split_actions([{"search": "density correction", "calc": "8512 + 8697"}]) == \
        [{"search": "density correction"}, {"calc": "8512 + 8697"}]
    from petroharness.agent.schemas import call
    f = formation_of(CASES["hw3"])
    assert "Petrophys functions matching" in call(f, *bare[1:]).text


def test_a_call_named_by_what_it_calls_is_that_call():
    """Benchmark N3/N4: 88 lookups unread, each naming its call by a tool's name under run or search, a Petrophys
    function under run without its verb, a verb's object as the key, a get's id inside a dict or several ids."""
    from petroharness.agent.loop import coerce_action, split_actions
    assert coerce_action({"search": "core_vs_log"}) == ("tool", "core_vs_log", {})
    assert coerce_action({"run": "core_vs_log", "args": {"zones": ["Z1", "Z2"]}}) == \
        ("tool", "core_vs_log", {"zones": ["Z1", "Z2"]})
    assert coerce_action({"run": "zone_contrast", "curve": "PERM", "inputs": ["VCL"]}) == \
        ("tool", "zone_contrast", {"curve": "PERM", "inputs": ["VCL"]})
    assert coerce_action({"held_readings": {"curves": ["DTC"], "zones": ["Z1"]}}) == \
        ("tool", "check", {"what": "held_readings", "curves": ["DTC"], "zones": ["Z1"]})
    assert coerce_action({"get": {"id": "E9", "find": "Z1, Z2"}}) == ("get", "E9", "Z1, Z2")
    assert coerce_action({"get": {"E8": "Z19"}}) == ("get", "E8", "Z19")
    assert coerce_action({"run": {"core_vs_log": {"zones": ["ALL"]}}}) == ("tool", "core_vs_log", {"zones": ["ALL"]})
    assert coerce_action({"run": {"name": "core_vs_log", "args": {}}}) == ("tool", "core_vs_log", {})
    assert coerce_action({"get": "section hydrocarbon.gas_detection"}) == \
        ("tool", "section", {"key": "hydrocarbon.gas_detection"})
    assert coerce_action({"run": "held_readings", "args": {"curves": ["DTC"]}}) == \
        ("tool", "check", {"what": "held_readings", "curves": ["DTC"]})
    assert coerce_action({"get": "hydrocarbon.gas_detection"}) == ("tool", "section", {"key": "hydrocarbon.gas_detection"})
    assert split_actions([{"get": "E3, E5", "find": "Z1"}]) == [{"get": "E3", "find": "Z1"}, {"get": "E5", "find": "Z1"}]
    from petroharness.agent.library_api import registry
    fn = next(fn for fn in registry() if fn.verb == "calculate")
    assert coerce_action({"run": fn.name, "args": {}}) == ("tool", "calculate", {"run": fn.name, "args": {}})


@pytest.mark.parametrize("case", ["brent", "hw3"])
def test_section_given_a_step_a_tool_or_a_family_reads_what_it_names(case):
    """Benchmark N3/N4: 26 section calls refused, among them "step porosity", a tool's name and a family alone."""
    from petroharness.agent.engine import ToolError
    from petroharness.agent.schemas import call
    f = formation_of(CASES[case])
    st = f.inv.methods[0].step
    assert call(f, "section", {"key": f"step {st}"}).text == call(f, "step", {"name": st}).text
    assert call(f, "section", {"key": "formation_summary"}).text == call(f, "formation_summary", {}).text
    fam = f.inv.sections[0].family
    if fam not in {m.step for m in f.inv.methods}:
        with pytest.raises(ToolError, match="is a family of sections"):
            call(f, "section", {"key": fam})
    key = f.inv.sections[0].key
    with pytest.raises(ToolError, match=f"did you mean {re.escape(key)}"):
        call(f, "section", {"key": key.replace("_", " ") + " xyz"} if "_" in key else {"key": key + "_xyz"})


def test_a_unit_and_its_own_depths_are_one_stretch_said_once():
    """Question suite B05 (a78c040a): the scope [the unit, its depths] noted "BRENT GP. (2841.02-2957.91 m) is part of
    BRENT GP."; two items that hold the same samples are one row, and a unit with its own depths needs no note."""
    from petroharness.agent import selection
    f = formation_of(CASES["brent"])
    iv = f.view.interval
    for items in ([iv.formation, f"{iv.top:.4f}-{iv.base:.4f} m"], ["Ness Fm.", "2841-2865 m"]):
        notes = []
        selection.resolve(f, items, force=True, notes=notes)
        assert not any("is part of" in n for n in notes), (items, notes)
    notes = []
    selection.resolve(f, ["Ness Fm.", "2850-2860 m"], force=True, notes=notes)
    assert any("is part of" in n for n in notes), notes                   # inside: said as before


TOOLS_POOLING = {"stats": {"curves": ["GR"]}, "overlap": {"a": "GR > 40", "b": "GR < 80"},
                 "threshold_exceedance": {"curve": "RHOB", "threshold": 2.5},
                 "spike_flags": {"curves": ["GR"]}, "adjacent_jumps": {"curve": "GR", "threshold": 10},
                 "lithology_stats": {"curves": ["GR"]}, "zone_contrast": {"curve": "GR"},
                 "profile": {"curve": "GR"}, "core_vs_log": {}}


@pytest.mark.parametrize("tool", sorted(TOOLS_POOLING))
def test_a_result_that_pools_the_zones_also_gives_the_whole_interval_where_samples_lie_outside_them(tool):
    """The interval's value is its whole line (C4 basis); a result that shows only the zones pooled where 201 samples
    lie outside the zones leaves the model no whole-interval value (suite Y01: overlap gave the band's share of the
    zones only, and the share of the Brent Group was "not computed")."""
    from petroharness.agent.engine import ToolError
    from petroharness.agent.schemas import call
    f = formation_of(CASES["brent"])
    try:
        text = call(f, tool, TOOLS_POOLING[tool]).text
    except ToolError as e:
        pytest.skip(f"{tool}: {e}")
    if "zones pooled" not in text:
        pytest.skip(f"{tool} writes no pooled line")
    assert "whole interval" in text, text[:1500]


SHARE_TOOLS = {**TOOLS_POOLING, "curve_order": {"curves": ["RDEP", "RMED"], "relation": "decreasing"},
               "runs": {"condition": "GR > 100"}}


@pytest.mark.parametrize("tool", sorted(SHARE_TOOLS))
def test_a_share_of_samples_is_written_with_its_count(tool):
    """Question suite B05, Y02, Y11 (64356713): "how many samples" was answered with a share, or "the absolute sample
    counts are not stated", because threshold_exceedance wrote "0.3% of 768 samples". Every share of samples a result
    writes stands with its count ("2 of 768 samples (0.3%)"), and the count is one of the result's numbers."""
    from petroharness.agent.engine import ToolError
    from petroharness.agent.schemas import call
    f = formation_of(CASES["brent"])
    try:
        r = call(f, tool, SHARE_TOOLS[tool])
    except ToolError as e:
        pytest.skip(f"{tool}: {e}")
    bare = re.findall(r"(?<!\()\b\d+(?:\.\d+)?% of \d+ (?:zoned )?samples", r.text)
    assert not bare, (tool, bare)
    for k, n in re.findall(r"\b(\d+) of (\d+) (?:zoned )?samples \(", r.text):
        assert int(k) in r.numbers or float(k) in r.numbers, (tool, k)


def test_threshold_exceedance_gives_the_count_beyond_in_each_zone_and_over_the_interval():
    from petroharness.agent.schemas import call
    f = formation_of(CASES["brent"])
    t = call(f, "threshold_exceedance", {"curve": "RHOB", "threshold": 2.7}).text
    d = np.asarray(f.view.prep.depth, dtype=float) * f.view.depth_scale
    rhob = np.asarray(f.view.values("RHOB"), dtype=float)
    k, n = int(np.sum(rhob[np.isfinite(rhob)] > 2.7)), int(np.isfinite(rhob).sum())
    assert f"{k} of {n} samples (" in t, t[-800:]
    assert "samples beyond" in t


@pytest.mark.parametrize("case", ["brent", "hw3", "cheal"])
def test_a_condition_on_a_curves_own_percentile_uses_the_percentile_the_tools_show(case):
    """Benchmark N6 (TRYGGVASON): "where GR is below the 25th percentile" had no form; the model filtered on another
    number than the p25 it quoted. "GR < p25" (or "25th percentile") takes the curve's percentile over the samples
    read, as stats computes it, and reads back to the same samples."""
    from petroharness.agent.engine import select
    from petroharness.agent.schemas import call
    f = formation_of(CASES[case])
    c = "GR"
    gr = np.asarray(f.view.values(c), dtype=float)
    shown = call(f, "stats", {"curves": [c], "statistics": ["p25"]}).text
    sel = select(f, f"{c} < p25")
    p25 = float(re.search(r"= ([-\d.e]+)\)$", sel.read).group(1))
    assert re.search(rf"\b{re.escape(sel.read.split('= ')[1].rstrip(')'))}\b", shown), (sel.read, shown[:600])
    assert np.array_equal(sel.mask, np.isfinite(gr) & (gr < p25 + 1e-9 * max(1, abs(p25))) & (gr <= p25)) or \
        int(sel.mask.sum()) == int(np.sum(gr[np.isfinite(gr)] < p25))
    for written in (f"{c} below its 25th percentile", f"{c} < P25", sel.read):
        assert np.array_equal(select(f, written).mask, sel.mask), written


@pytest.mark.parametrize("case", ["brent", "hw3", "cheal"])
def test_runs_over_the_zones_asked_gives_the_whole_intervals_total_where_samples_lie_outside_them(case):
    """Suite X15 (818f8fe3): "how many metres of the Brent Group have GR < 60" listed all 20 zones and got 57.08 m, the
    zones' samples only; the interval holds 69.17 m. The result gives the whole interval's total beside the zones'."""
    from petroharness.agent.schemas import call
    f = formation_of(CASES[case])
    cond = "GR < 60"
    plain = call(f, "runs", {"condition": cond}).text.splitlines()[0]
    listed = call(f, "runs", {"condition": cond, "zones": [z.zone_id for z in f.view.zones]}).text
    gr = np.asarray(f.view.values("GR"), dtype=float)
    inside = np.zeros(gr.size, dtype=bool)
    for z in f.view.zones:
        inside[np.asarray(z.indices)] = True
    if not ((gr < 60) & ~inside).any():
        pytest.skip("no sample outside the zones meets the condition")
    total = re.search(r"intervals?, ([\d.]+) ", plain).group(1)                  # the interval's own total, uncut
    line = next(ln for ln in listed.splitlines() if "whole interval" in ln)
    assert f", {total} " in line and "the zones asked leave out" in line, (plain, line)


def test_a_unit_listed_twice_written_as_where_is_said_with_both_stretches():
    """Suite T01 (tuhua-7, whose tops file lists Manganui twice): where "Manganui" got the condition grammar's refusal,
    which says nothing of the unit; it now gets the selection's own message, with both stretches."""
    from petroharness.agent.engine import ToolError
    from petroharness.agent.schemas import call
    f = formation_of(CASES["tuhua"])
    with pytest.raises(ToolError, match=r"where takes a condition.*Manganui is listed 2 times.*874.*2164.*its depths.*as zones"):
        call(f, "stats", {"curves": ["GR"], "where": "Manganui"})
