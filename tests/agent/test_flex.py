"""Tools that work on any zone layout (formations of one zone), and the harness's own tool names in the workflow's
messages.

    .venv/bin/python -m pytest tests/agent/test_flex.py -q        (PETROHARNESS_DATA selects the dataset)
"""
import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
import b2_reference as R  # noqa: E402
from test_b2_tools import F  # noqa: E402
from petroharness.agent.engine import ToolError  # noqa: E402


def _one_zone():
    hit = [(t, f) for t, f in F() if len(f.view.zones) == 1 and "GR" in f.inv.curves]
    if not hit:
        pytest.skip("no one-zone formation with GR in this dataset")
    return hit[0]


def test_workflow_tool_names_become_this_harness_s():
    from petroharness.agent.compute import harness_names
    msg = "WHAT: need a curve with data and at least two zones. FIX: use depth_trend or zone_stats."
    assert harness_names(msg) == ("WHAT: need a curve with data and at least two zones. FIX: use crossplot with x "
                                  "DEPTH (or profile) or stats.")


@pytest.mark.data
def test_vertical_sequence_on_one_zone_reads_its_thirds():
    from petroharness.agent.compute import vertical_sequence
    t, f = _one_zone()
    r = vertical_sequence(f, ["GR"])
    z = f.view.zones[0]
    parts = list(reversed(np.array_split(np.asarray(z.indices), 3)))           # base first
    x = np.asarray(f.view.values("GR"), float)
    ln = next(l for l in r.text.splitlines() if l.lstrip().startswith("GR"))
    got = [float(v) for v in re.findall(r"third [^:]+: (-?[\d.]+)", ln)]
    want = [float(np.nanmean(x[p])) for p in parts]
    assert len(got) == 3 and all(R.agrees(a, b) for a, b in zip(got, want)), (ln, want)
    way = "increasing upward" if want[0] < want[1] < want[2] else "decreasing upward" if want[0] > want[1] > want[2] \
        else "no single direction"
    assert way in ln


@pytest.mark.data
def test_a_misspelt_curve_with_one_clear_match_is_that_curve():
    from petroharness.agent.engine import curve
    t, f = next(((t, f) for t, f in F() if "INVASION_RATIO" in f.inv.curves), (None, None))
    if f is None:
        pytest.skip("no INVASION_RATIO")
    assert curve(f, "INVA-SION_RATIO") == "INVASION_RATIO" and curve(f, "INVAIASION_RATIO") == "INVASION_RATIO"
    with pytest.raises(ToolError):
        curve(f, "NOT_A_CURVE_AT_ALL")


@pytest.mark.data
def test_a_zone_named_as_the_spike_baseline_is_that_zone_s_own():
    from petroharness.agent.compute import spike_flags
    t, f = next(((t, f) for t, f in F() if "GR" in f.inv.curves and f.view.zones), (None, None))
    zid = f.view.zones[0].zone_id
    assert spike_flags(f, ["GR"], baseline=zid).text == spike_flags(f, ["GR"], baseline="zone", zones=[zid]).text


@pytest.mark.data
def test_profile_of_one_zone_reads_its_thirds():
    from petroharness.agent.tools import profile
    t, f = _one_zone()
    z = f.view.zones[0]
    on = profile(f, "GR").text                                    # the default text, then the thirds
    x = np.asarray(f.view.values("GR"), float)
    parts = np.array_split(np.asarray(z.indices), 3)
    lines = [ln for ln in on.splitlines() if "third" in ln]
    assert [ln.split()[:2] for ln in lines] == [[z.zone_id, w] for w in ("upper", "middle", "lower")]
    assert all(", GR: median " in ln for ln in lines)                         # each names its zone and curve
    for ln, p in zip(lines, parts):
        v = x[p][np.isfinite(x[p])]
        assert R.agrees(float(re.search(r"median (-?[\d.]+)", ln).group(1)), float(np.median(v)))
        assert int(re.search(r", n (\d+)", ln).group(1)) == v.size


@pytest.mark.data
def test_profile_of_several_zones_is_unchanged():
    from petroharness.agent.tools import profile
    hit = [f for t, f in F() if len(f.view.zones) > 1 and "GR" in f.inv.curves]
    if not hit:
        pytest.skip("no multi-zone formation with GR")
    assert "third" not in profile(hit[0], "GR").text              # several zones: read zone by zone, no thirds


@pytest.mark.data
def test_one_zone_drops_zone_mean_lines_and_the_map_says_how_to_read_it():
    from petroharness.agent.map import render
    from petroharness.agent.tools import runs
    t, f = _one_zone()
    cond = "GR > 0"
    on, m_on = runs(f, cond).text, render(f.inv)
    assert "zones whose means meet it" not in on
    assert "One zone: its variation is read by depth" in m_on


@pytest.mark.data
def test_the_lithology_first_look_reads_the_mineral_volumes():
    from petroharness.llm import Usage
    from test_b5_loop import Script, _session, chose
    from petroharness.agent.loop import MINERAL_VOLUMES, investigate
    s = chose(_session(), "lithology_mineralogy")
    first = {"points": ["What is the lithology?"], "intent": "describe", "edits": [], "next": [], "done": True}
    trace = {}
    investigate(Script([first, first]), s, Usage(), 4000, trace, max_steps=1)
    look = trace.get("overview", "")
    have = [c for c in MINERAL_VOLUMES if c in s.f.inv.curves]
    assert all(c in look for c in have[:4]), (look, have)          # core_look adds them for lithology_mineralogy
    assert ("p90" in look) == (len(s.f.view.zones) == 1)


@pytest.mark.data
def test_the_map_gives_the_tops_lithology_beside_the_log_s():
    from petroharness.agent.map import render
    for t, f in F():
        for z, iz in zip(f.view.zones, f.inv.zones):
            assert iz.stated == (getattr(z, "stated", "") or "")
            line = f"the formation tops record its lithology as {iz.stated} (the lithology log reads"
            assert (line in render(f.inv)) == bool(iz.stated), (t.well, iz.stated)


@pytest.mark.data
def test_a_log_in_the_input_without_values_here_is_not_called_missing():
    from petroharness.agent.map import primary_absent, render
    seen = 0
    for t, f in F():
        well = {str(c).upper() for c in f.view.prep.well.curves}
        empty = [c for c in f.inv.logs_absent if c.upper() in well]
        assert f.inv.logs_empty == empty
        m = render(f.inv)
        listed = [c for c in primary_absent(f.inv) if c in empty]
        missing = next((ln for ln in m.splitlines() if "measured logs not in the input:" in ln), "")
        nodata = next((ln for ln in m.splitlines() if "with no values in this interval:" in ln), "")
        for c in listed:
            seen += 1
            assert re.search(rf"\b{re.escape(c)}\b", nodata) and not re.search(rf"\b{re.escape(c)}\b", missing), (t.well, c)
    if not seen:
        pytest.skip("no interval here lacks values of a log its well has")


@pytest.mark.data
def test_the_solver_volumes_say_where_they_have_values_and_which_supports_are_here():
    from petroharness.agent.inventory import from_view
    from petroharness.agent.map import render
    hit = [f for t, f in F() if any(c in f.inv.curves for c in ("VQUAR", "VCALC", "VDOLO", "VANHY"))]
    if not hit:
        pytest.skip("no mineral-solver volumes here")
    f = hit[0]
    minerals = [c for c in ("VQUAR", "VCALC", "VDOLO", "VANHY") if f.view.available(c)]
    ok = np.zeros(int(f.view.mask.sum()), dtype=bool)
    for c in minerals:
        ok |= np.isfinite(np.asarray(f.view.values(c), dtype=float))
    m = render(from_view(f.view, f.store))
    line = next(ln for ln in m.splitlines() if "mineral-solver volumes" in ln)
    assert f"with values at {int(ok.sum())} of {ok.size} samples here" in line, line
    for name, on in (("PEF", f.view.available("PEF")), ("RHOB", f.view.available("RHOB"))):
        assert (name in line.split("here,")[-1]) == on or not on, (name, line)
    assert "QC flagged" not in m or not re.search(r"QC flagged \d+(?![\d.%])", m), "a well count left unscoped"


@pytest.mark.data
def test_a_one_zone_table_has_a_row_per_curve_with_its_spread():
    from test_b7_writer import _real_claims, _session
    from petroharness.agent.engine import statistic
    from petroharness.agent.writer import zone_table
    s = _session(["What is the porosity and water saturation?"], [])
    for c in _real_claims(s):
        s.claims.claims[c.id] = c
    s.topics = ["water_saturation"]
    tab = zone_table(s, s.claims, wide=True, style="by_interval")
    if len(s.f.view.zones) != 1:
        assert "| Curve | n | Min |" not in tab                      # several zones: the profile's layout is kept
        return
    rows = [r for r in tab.splitlines()[2:] if r.startswith("| Z1")]
    assert tab.splitlines()[0].startswith("| Zone | Lithology | Depth") and rows, tab
    z = s.f.view.zones[0]
    for r in rows:
        cells = [x.strip() for x in r.strip("|").split("|")]
        curve = cells[3].split(" = ")[0]
        assert curve not in s.f.view.reg.flags, r
        x = s.f.view.zone_values(z, curve)
        for got, k in zip(cells[4:9], ("n", "min", "median", "mean", "max")):
            want = statistic(x, k)
            assert R.agrees(float(got), float(want)), (curve, k, got, want)


@pytest.mark.data
def test_lithology_analyzer_classes_by_construction_are_noted():
    """NON_CARBONATE where the carbonate indicators could not test, CARBONATE_LOG_MISMATCH where only bulk RHOB fails,
    NO_LOG_LITHOLOGY_MATCH for a rock the consistency windows do not cover: each noted with counts from the data."""
    from petroharness.agent import notes as N
    seen = 0
    for t, f in F():
        sec = {s.key.split(".")[-1]: s for s in f.inv.sections}
        got = N.notes(f.view, f.inv.curves, f.inv.sections)
        pef, rho = (np.asarray(f.view.values(c), dtype=float) if f.view.values(c) is not None else np.full(int(f.view.mask.sum()), np.nan)
                    for c in ("PEF", "RHOB"))
        tested = np.isfinite(pef) & np.isfinite(rho)
        cn = [x for x in got if "need PEF and RHOB on the same sample" in x]
        if "carbonate_analysis" in sec and any(c.name == "NON_CARBONATE" for c in sec["carbonate_analysis"].classes) \
                and tested.mean() < 0.99:
            assert cn and f"together at {int(tested.sum())} of {tested.size} samples" in cn[0], (t.well, cn)
            seen += 1
        mn = [x for x in got if "only bulk RHOB fails" in x]
        if mn:
            k = int((tested & (pef > 2.8) & (rho <= 2.6)).sum())
            assert f"at {k} of {int(tested.sum())} tested samples" in mn[0], (t.well, mn)
            seen += 1
        for x in [x for x in got if "has no window" in x]:
            assert not re.search(r"the workflow's (SHALE|SANDSTONE|LIMESTONE|DOLOMITE) group", x), x
            seen += 1
    if not seen:
        pytest.skip("no analyzer class by construction in this dataset")


@pytest.mark.data
def test_a_class_line_lists_its_runs_without_a_noise_note():
    """A class with three or more runs lists them top to base with their count; no single-sample count, no noise
    wording (a run-shape note would frame one-sample runs as noise)."""
    from petroharness.agent.tools import _store_runs, section
    for t, f in F():
        if f.store is None:
            continue
        for s in f.inv.sections:
            for c in s.classes:
                rs = _store_runs(f, s.key, c.name)
                if len(rs) < 3:
                    continue
                ln = next(x for x in section(f, s.key).text.splitlines() if x.startswith(f"  {c.name}"))
                assert f" {len(rs)} runs, top to base; runs: " in ln and "single sample" not in ln, ln[:200]
                return
    pytest.skip("no class with three or more runs")


@pytest.mark.data
def test_the_gas_screen_note_counts_the_screen_and_the_crossover_call():
    from petroharness.agent import notes as N
    for t, f in F():
        got = [x for x in N.notes(f.view, f.inv.curves, f.inv.sections) if "its gas classes screen" in x]
        if not got:
            continue
        sep, flag = (np.asarray(f.view.values(c), dtype=float) for c in ("ND_SEPARATION", "CROSSOVER_FLAG"))
        with np.errstate(invalid="ignore"):
            k, both = int((sep >= 0.03).sum()), int(((sep >= 0.03) & (flag > 0.5)).sum())
        assert f"at {k} of {sep.size} samples here" in got[0] and got[0].endswith(f"is set at {both} of them"), got[0]
        return
    pytest.skip("no gas classes here")


@pytest.mark.data
def test_the_first_look_opens_the_key_curves_of_every_topic_the_model_chose():
    from petroharness.llm import Usage
    from test_b5_loop import Script, _session, chose
    from petroharness.agent import direction
    from petroharness.agent.loop import investigate
    s = chose(_session(), "lithology_mineralogy", "porosity", "permeability_rock_quality")
    s.task = s.task.model_copy(update={"question": "Characterize the relationship between mineralogy, porosity and permeability."})
    first = {"points": ["x"], "intent": "describe", "edits": [], "next": [], "done": True}
    trace = {}
    investigate(Script([first, first]), s, Usage(), 4000, trace, max_steps=1)
    look = trace.get("overview", "")
    extra = [c for area in ("porosity", "permeability_rock_quality") for c in direction.overview([area])[:3]
             if c in s.f.inv.curves and c not in direction.overview(["lithology_mineralogy"])]
    if not extra:
        pytest.skip("no porosity/permeability key curves here")
    assert all(c in look for c in extra[:1]), (look, extra)


@pytest.mark.data
@pytest.mark.parametrize('on', [True])
def test_core_look_adds_the_reservoir_context_and_the_mineral_volumes(on):
    from petroharness.llm import Usage
    from test_b5_loop import Script, _session, chose
    from petroharness.agent.loop import CORE_CURVES, MINERAL_VOLUMES, investigate
    s = chose(_session(), "lithology_mineralogy")
    first = {"points": ["x"], "intent": "describe", "edits": [], "next": [], "done": True}
    trace = {}
    investigate(Script([first, first]), s, Usage(), 4000, trace, max_steps=1)
    look = [str(c).upper() for c in s.ledger.items[0].args.get("curves", [])]   # the first look's curves (the trace's
    core = [c for c in CORE_CURVES if c in s.f.inv.curves]                       # action text is cut short)
    minerals = [c for c in MINERAL_VOLUMES if c in s.f.inv.curves]
    if on:
        assert all(c in look for c in (core + minerals)[:14] if (core + minerals).index(c) < 6), (look, core, minerals)
    else:
        assert not all(c in look for c in core) or set(core) <= {"VCL"}


@pytest.mark.parametrize('flex', [True])
def test_route_counts_name_their_unit(flex):
    from petroharness.agent import routes
    c = {"n": 1960, "RSHA": 1924, "RMED": 36, "other": 0}
    text = routes._pairs(c)
    assert ("RSHA/RDEP at 1924 samples" in text and "RMED/RDEP at 36 samples" in text) == flex, text
    assert "RSHA/RDEP at 1924" in text


@pytest.mark.data
@pytest.mark.parametrize("flex", [True])
def test_a_guide_opens_the_workflow_curves_it_names(flex):
    from petroharness.llm import Usage
    from test_b5_loop import Script, _session
    from petroharness.agent.loop import investigate
    s = _session()
    want = s.library.workflow_stats("water_saturation", s.f)      # stats BVW, PHIE, SW
    if not want:
        pytest.skip("no workflow-computed BVW, PHIE and SW here")
    assert all(s.f.inv.curves[c].source in ("computed", "analyzer") for kw in want for c in kw["curves"])
    llm = Script([{"asks": "How does bulk volume water vary?", "points": ["How does bulk volume water vary?"],
                   "intent": "value", "focus": "f",
                   "edits": [{"op": "add", "point": 1, "text": "Likely near constant", "grade": "hypothesis"}],
                   "next": [{"guide": "water_saturation"}], "done": False}])
    trace = {}
    investigate(llm, s, Usage(), 4000, trace, max_steps=2)
    opened = [e.call_text() for e in s.ledger.items]
    got = [t for t in opened if t.startswith("stats ") and all(c in t for c in want[0]["curves"])
           and not any(o in t for o in ("GR", "RHOB"))]
    assert bool(got) == flex, opened
