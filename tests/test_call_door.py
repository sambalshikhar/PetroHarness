"""Brick 5 of docs/designs/zones-and-intervals.md (4.4): `zones` read at the call door for every tool, `where` for a
verb's `run` (reach "well"; under "focus" every call is today's: the golden tapes).

- A tool that does not take zones (calculate, what_if, formation_summary, vertical_sequence, pay_summary), or a verb's
  run, computes on the selection, focus zone ids included; one that reads the workflow's results for the focus
  (section, zone_classes) keeps today's path for focus zones and refuses elsewhere; step (the well's record, the same for
  any stretch) drops zones with the usual note.
- `where` on a run: the function gets the samples where the condition holds; one that reads the well or a depth
  window is refused there.

On GeoLink 30/6-5 (Brent Group, its tops file), every tool, with expectations from the raw arrays.

    .venv/bin/python -m pytest tests/test_call_door.py -q -n 8
"""
import re

import numpy as np
import pytest

from _wells import CASES, formation_of
from test_selection import SELECTIONS, TOOL_ARGS, _DEPTHS

OTHER_ARGS = {"calculate": {"property": "porosity", "method": "density"},
              "what_if": {"property": "saturation", "parameter": "m", "values": [1.8, 2.2]},
              "formation_summary": {}, "vertical_sequence": {"curves": ["GR"]}, "pay_summary": {},
              "zone_classes": {"topic": "hc_indicators"}, "step": {"name": "rw"},
              "values_at": {"curves": ["GR"], "depths": [2900]}}


@pytest.fixture(scope="module")
def brent():
    return formation_of(CASES["brent"])


def _section_key(f):
    return next(iter(f.store.sections))


def test_every_tool_is_in_one_table(brent):
    from petroharness.agent.toolset import TOOLSET
    assert sorted(t.name for t in TOOLSET) == sorted(set(TOOL_ARGS) | set(OTHER_ARGS) | {"section"})


def _args(f, tool):
    if tool == "section":
        return {"key": _section_key(f)}
    return dict(TOOL_ARGS.get(tool) or OTHER_ARGS[tool])


def _inside(text, top, base, step=0.16):
    bad = []
    for m in _DEPTHS.finditer(text):
        for g in m.groups():
            if g is not None and 2000 <= float(g) <= 4500 and not (top - step <= float(g) <= base + step):
                bad.append(m.group(0))
    return bad


@pytest.mark.parametrize("tool", sorted(OTHER_ARGS) + ["section"])
@pytest.mark.parametrize("what", sorted(SELECTIONS))
def test_a_tool_without_zones_computes_on_a_selection_or_says_why_not(brent, tool, what):
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    from petroharness.agent.selection import FOCUS_ONLY
    zones, top, base = SELECTIONS[what]
    try:
        r = schemas.call(brent, tool, {**_args(brent, tool), "zones": zones})
    except ToolError as e:
        assert tool in FOCUS_ONLY and "computed for the focus" in str(e), (tool, what, str(e)[:300])
        return
    from petroharness.agent.selection import WHOLE_WELL
    if tool in WHOLE_WELL:                                   # the same for any stretch: zones dropped with the note
        assert r.text.startswith(f"(ignored zones: {tool} takes "), r.text[:200]
        return
    assert tool not in FOCUS_ONLY, (tool, "computed although it reads the focus's results")
    assert r.text.startswith("Selection: "), (tool, what, r.text[:200])
    assert not _inside(r.text, top, base), (tool, what, _inside(r.text, top, base)[:4], r.text[:500])
    if what.startswith("Dunlin"):
        assert not re.search(r"\bZ\d+\b", r.text), (tool, re.findall(r".{40}\bZ\d+\b.{20}", r.text)[:3])
    said = re.findall(r"[^\n]*(?:\bzones pooled\b|whole interval \()[^\n]*", r.text)
    said = [s for s in said if not re.search(r"(each zone|the zones pooled|zones pooled and the whole)", s)]   # titles
    assert not said, (tool, what, said[:2])              # a selection's value lines name its rows


@pytest.mark.parametrize("tool", ["calculate", "what_if", "formation_summary", "vertical_sequence", "pay_summary"])
def test_a_focus_zone_given_to_a_tool_without_zones_is_what_it_computes_on(brent, tool):
    """Today these drop zones ("ignored zones") and report the whole focus; under reach well, Z7 alone."""
    from petroharness.agent import schemas
    z7 = next(z for z in brent.view.zones if z.zone_id == "Z7")
    r = schemas.call(brent, tool, {**OTHER_ARGS[tool], "zones": ["Z7"]})
    assert r.text.startswith(f"Selection: Z7 {z7.top:g}-{z7.base:g} m, {z7.n_samples} samples;"), r.text[:200]
    assert not _inside(r.text, z7.top, z7.base), _inside(r.text, z7.top, z7.base)[:4]
    assert "(ignored zones" not in r.text


def test_a_focus_tool_keeps_todays_path_for_focus_zones(brent):
    from petroharness.agent import schemas
    a = schemas.call(brent, "zone_classes", {"topic": "hc_indicators"}).text
    b = schemas.call(brent, "zone_classes", {"topic": "hc_indicators", "zones": ["Z3"]}).text
    assert b == "(ignored zones: zone_classes takes topic)\n" + a


def test_run_on_a_focus_zone_writes_only_there(brent):
    from petroharness.agent import schemas
    z7 = next(z for z in brent.view.zones if z.zone_id == "Z7")
    r = schemas.call(brent, "estimate", {"run": "apparent_water_resistivity", "args": {"rt": "RDEP", "phi": "PHIE"},
                                         "zones": ["Z7"], "label": "RWA_Z7"})
    assert r.text.startswith(f"Selection: Z7 {z7.top:g}-{z7.base:g} m, {z7.n_samples} samples;")
    name = next(c for c in brent.view.calculated if c.startswith("RWA_Z7"))
    x = np.asarray(brent.view.calculated[name], dtype=float)
    d = np.asarray(brent.view.prep.depth, dtype=float) * brent.view.depth_scale
    on = np.isfinite(x)
    zd = np.asarray(brent.view.depth, dtype=float)[np.asarray(z7.indices)]      # Z7's own samples (its top and base
    lo, hi = float(zd[0]), float(zd[-1])                                       # are kept rounded to 4 decimals)
    assert on.any() and d[on].min() >= lo - 1e-9 and d[on].max() <= hi + 1e-9
    rt, phi = (np.asarray(brent.view.prep.curve(c), dtype=float) for c in ("RDEP", "PHIE"))
    inside = (d >= lo - 1e-9) & (d <= hi + 1e-9)
    assert int(on.sum()) <= int((inside & np.isfinite(rt) & np.isfinite(phi)).sum())


def test_pickett_on_the_water_leg_fits_those_samples_only(brent):
    """where "SW > 0.95" with VCL given: Pickett fits the clean water-leg samples, the condition's samples that Petrophys's
    own rule accepts (finite, Rt > 0, porosity > 0.01, VCL below its 0.3 default cutoff), counted here from the raw
    arrays over the focus; its m is then in the usual range (fitted on every clean sample it reads m -4.24)."""
    from petroharness.agent import schemas
    r = schemas.call(brent, "estimate", {"run": "pickett_analysis", "args": {"rt": "RDEP", "phi": "PHIE", "vcl": "VCL"},
                                         "where": "SW > 0.95"})
    v = brent.view
    sw, rt, phi, vcl = (np.asarray(v.values(c), dtype=float) for c in ("SW", "RDEP", "PHIE", "VCL"))
    n = int((np.isfinite(sw) & (sw > 0.95) & np.isfinite(rt) & (rt > 0) & np.isfinite(phi) & (phi > 0.01)
             & np.isfinite(vcl) & (vcl < 0.3)).sum())
    assert r.text.startswith("Selection: the samples where SW > 0.95: ")
    assert re.search(rf"n_points: {n}\b", r.text), (n, re.findall(r"n_points: \d+", r.text))
    m = float(re.search(r"\b0\.m: (-?[\d.]+)", r.text).group(1))
    assert 1.3 <= m <= 3.0, m


def test_a_depth_window_function_under_where_is_refused(brent):
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    with pytest.raises(ToolError, match=r"reads the well over a depth window .*select by zones or a depth range"):
        schemas.call(brent, "summarize", {"run": "calculate_net_gross", "where": "SW < 0.5"})


def test_where_with_no_sample_is_refused(brent):
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    with pytest.raises(ToolError, match="no sample here where"):
        schemas.call(brent, "estimate", {"run": "pickett_analysis", "args": {"rt": "RDEP", "phi": "PHIE"},
                                         "where": "SW > 5"})


def test_text_sent_as_a_list_of_one_is_that_text():
    """Question suite B10: where ["2865-2958"] was refused ("where must be text"), the direct route's last lookup.
    Text sent as a list of one is that text, as one name sent as text is a list of one (schemas.arguments); a list of
    several stays refused."""
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    assert schemas.arguments({"where": ["NET_PAY"]})["where"] == "NET_PAY"
    assert schemas.arguments({"curves": "PHIE"})["curves"] == ["PHIE"]
    with pytest.raises(ToolError, match="where must be text"):
        schemas.arguments({"where": ["NET_PAY", "SW < 0.5"]})


def test_under_reach_focus_run_takes_no_where_and_zones_are_todays():
    from dataclasses import replace
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    f = formation_of(replace(CASES["brent"], data=(("reach", "focus"),)))
    with pytest.raises(ToolError, match="takes no where here"):
        schemas.call(f, "estimate", {"run": "pickett_analysis", "args": {"rt": "RDEP", "phi": "PHIE"},
                                     "where": "SW > 0.95"})
    t = schemas.call(f, "calculate", {"property": "porosity", "method": "density", "zones": ["Z7"]}).text
    assert t.startswith("(ignored zones: calculate takes ") and not t.startswith("Selection")


def test_calls_that_differ_only_at_the_door_are_two_results():
    """The ledger serves an identical call's item again; zones given to a tool that does not take them, and where on
    a run, change what is computed (reach well), so they are part of the call: two results, never one for the other."""
    from petroharness.agent.ledger import Ledger
    f = formation_of(CASES["brent"])
    led = Ledger(f)
    a, _ = led.open("calculate", {"property": "porosity", "method": "density", "zones": ["Z7"]})
    b, new = led.open("calculate", {"property": "porosity", "method": "density", "zones": ["Dunlin GP."]})
    assert new and a.id != b.id and "DUNLIN GP." in b.text and "DUNLIN GP." not in a.text
    c, new = led.open("calculate", {"property": "porosity", "method": "density", "zones": ["Z7"]})
    assert not new and c.id == a.id                                     # the same call: the same item
    run = {"run": "pickett_analysis", "args": {"rt": "RDEP", "phi": "PHIE", "vcl": "VCL"}}
    d, _ = led.open("estimate", {**run, "where": "SW > 0.95"})
    e, new = led.open("estimate", {**run, "where": "SW > 0.9"})
    assert new and d.id != e.id


def test_a_curated_estimate_under_where_fits_those_samples_and_its_caution_is_shown(brent):
    """Live (Z6): the curated Pickett estimate fitted every clean sample (m -4.32) and dropped a where silently;
    Petrophys's caution went to stderr. Under reach well, where selects the samples (the water leg: m in range), and
    the out-of-range fit shows the caution and the call that fits the water leg alone."""
    from petroharness.agent import schemas
    call = {"parameter": "archie_m", "method": "pickett", "vcl_max": 0.3}
    plain = schemas.call(brent, "estimate", call).text
    assert re.search(r"Petrophys said: Pickett fit gives m = -4\.\d+, outside the usual", plain), plain[:600]
    assert 'this call again with "where"' in plain
    leg = schemas.call(brent, "estimate", {**call, "where": "SW > 0.95"}).text
    v = brent.view
    sw, rt, phi, vcl = (np.asarray(v.values(c), dtype=float) for c in ("SW", "RDEP", "PHIE", "VCL"))
    inz = np.ones(sw.size, dtype=bool)                   # a curated estimate with no zones reads the whole interval
    n = int((inz & np.isfinite(sw) & (sw > 0.95) & np.isfinite(rt) & (rt > 0) & np.isfinite(phi) & (phi > 0.01)
             & np.isfinite(vcl) & (vcl < 0.3)).sum())
    assert leg.startswith("Selection: the samples where SW > 0.95: ") and re.search(rf"n_points {n}\b", leg), n
    m = float(re.search(r"\bm (-?[\d.]+), n ", leg).group(1))
    assert 1.3 <= m <= 3.0 and 'this call again with "where"' not in leg


def test_under_reach_focus_a_curated_estimate_keeps_todays_where():
    from dataclasses import replace
    from petroharness.agent import schemas
    f = formation_of(replace(CASES["brent"], data=(("reach", "focus"),)))
    call = {"parameter": "archie_m", "method": "pickett", "vcl_max": 0.3}
    a, b = schemas.call(f, "estimate", call).text, schemas.call(f, "estimate", {**call, "where": "SW > 0.95"}).text
    assert not b.startswith("Selection") and 'this call again with "where"' not in a


def test_zones_written_inside_args_are_refused_with_the_call_to_send(brent):
    """Live (Z6 round 2): zones inside a run's args read "takes ...; not m, zones" and the model gave up on the run
    (its answer took m from a crossplot slope). The refusal now gives the call with zones beside run, and that call
    computes on the stretch."""
    import json
    from petroharness.agent import schemas
    from petroharness.agent.engine import ToolError
    bad = {"run": "pickett_analysis", "args": {"rt": "RDEP", "phi": "PHIE", "vcl": "VCL", "m": 2.0,
                                               "zones": ["Etive Fm."], "where": "SW > 0.95"}}
    with pytest.raises(ToolError) as e:
        schemas.call(brent, "estimate", bad)
    said = str(e.value)
    assert said.startswith("zones, where go beside run, not inside args, and pickett_analysis takes no m: send "), said
    fixed = json.loads(said.split(": send ", 1)[1])["estimate"]
    assert fixed == {"run": "pickett_analysis", "args": {"rt": "RDEP", "phi": "PHIE", "vcl": "VCL"},
                     "zones": ["Etive Fm."], "where": "SW > 0.95"}
    t = schemas.call(brent, "estimate", fixed).text
    assert t.startswith("Selection: the samples where SW > 0.95 in Etive Fm.: "), t[:160]
