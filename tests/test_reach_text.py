"""Under reach "well" the model is told what a tool's zones may name
beyond the interval's zones: the brief's zones line (a depth range, a unit of the tops file) and the map (the well's
span, the units with their depths). Under reach "focus" (the benchmark) every text is today's: the prompt fixture and
the golden tapes prove it byte for byte; here the brief's two forms and the map are checked directly, and a general-mode
question's READ and step prompts end to end (tests/agent/prompt_fixture.render, a stub model).

    .venv/bin/python -m pytest tests/test_reach_text.py -q
"""
from dataclasses import replace

import pytest

from _wells import CASES, formation_of, task_cfg

FOCUS_LINE = ('  zones (any lookup that takes them): zone ids ["Z2", "Z3"], a lithology ["SILT"] for its zones, '
              'or ["ALL"]; left out, every zone')


def test_the_focus_brief_lists_zones_as_today():
    from petroharness.agent.prompts import tools_text
    assert tools_text() == tools_text("focus") and FOCUS_LINE in tools_text("focus").splitlines()


def test_under_reach_well_only_the_zones_line_differs():
    from petroharness.agent.prompts import brief, tools_text
    focus, well = tools_text("focus").splitlines(), tools_text("well").splitlines()
    diff = [(a, b) for a, b in zip(focus, well) if a != b]
    assert len(focus) == len(well) and len(diff) == 1 and diff[0][0] == FOCUS_LINE
    assert 'a depth range ["2870-2890"]' in diff[0][1] and 'a unit of the tops file by its name ["<unit name>"]' in diff[0][1]
    assert brief(reach="well") != brief() and brief() == brief(reach="focus")


@pytest.fixture(scope="module")
def brent():
    return formation_of(CASES["brent"])


def test_the_map_names_the_reach_and_the_units_with_their_depths(brent):
    from petroharness.agent.map import render
    text = render(brent.inv)
    reach = next(l for l in text.splitlines() if l.startswith("Well: its log runs "))
    lo, hi = brent.inv.well_span
    assert brent.inv.reach == "well" and lo < 2841 and hi > 3223, (lo, hi)
    assert "a depth range TOP-BASE anywhere in it or a unit of the tops file" in reach
    units = next(l for l in text.splitlines() if l.startswith("  Units of the tops file: "))
    for part in ("NORDLAND GP. 181-726 m", "Ness Fm. 2841-2865 m", "DUNLIN GP. 2958-3223 m", "Statfjord Fm. 3223-3556 m"):
        assert part in units, (part, units[:300])
    lines = text.splitlines()
    assert lines.index(reach) < next(i for i, l in enumerate(lines) if l.startswith("Zones: "))


def test_the_map_counts_the_units_beyond_the_ones_it_lists(brent):
    from petroharness.agent.map import UNITS_SHOWN, render
    many = [(f"UNIT {k}", 1000.0 + k, 1001.0 + k) for k in range(UNITS_SHOWN + 5)]
    units = next(l for l in render(replace(brent.inv, units=many)).splitlines() if l.startswith("  Units of the tops file: "))
    assert units.endswith("; and 5 more") and f"UNIT {UNITS_SHOWN - 1} " in units and f"UNIT {UNITS_SHOWN} " not in units


def test_under_reach_focus_the_map_has_no_reach(tmp_path):
    from petroharness.agent.map import render
    f = formation_of(replace(CASES["brent"], data=(("reach", "focus"),)))
    assert f.inv.reach == "focus" and f.inv.units == []
    lines = render(f.inv).splitlines()
    assert not any(l.startswith(("Well:", "  Units of the tops file")) for l in lines)
    assert lines[1].startswith("Interval: ") and f"; {f.inv.samples} samples every " in lines[1]   # the header as it was


def test_a_general_question_reads_the_reach_end_to_end():
    """The READ call's system prompt and the step prompts of a general-mode Brent question (reach well): the brief's
    zones line and the map's reach lines, as the model receives them."""
    import prompt_fixture
    from petroharness.config import given_settings
    task, cfg, data = task_cfg(CASES["brent"], "p")
    with given_settings({"data": data, "eval": {}}):
        got = prompt_fixture.render(task, cfg, 0)
    assert 'a depth range ["2870-2890"]' in got["brief"] and FOCUS_LINE not in got["brief"].splitlines()
    assert "Well: its log runs " in got["read"] + got["step1"]
    assert "Units of the tops file: " in got["read"] + got["step1"]


def test_the_map_gives_the_wells_log_before_the_interval(brent):
    """Live round 5: 'every interval in the whole well' was read as the interval in 3 of 11 READ calls, the model
    taking the interval's samples for the log's ('544 samples every 0.1524 m gives 82.75 m, so the LAS interval is just
    82.75 m long'). Under reach well the map gives the well's log first, its samples counted from the depths, then the
    interval as a part of it."""
    import numpy as np
    from petroharness.agent.map import num, render
    lines = render(brent.inv).splitlines()
    d = np.asarray(brent.view.prep.depth, dtype=float)
    lo, hi = float(np.nanmin(d)), float(np.nanmax(d))
    assert lines[1] == (f"Well: its log runs {num(lo)}-{num(hi)} m, {int(np.isfinite(d).sum())} samples every "
                        f"{num(brent.inv.step)} m; a tool's zones may name a depth range TOP-BASE anywhere in it or a "
                        "unit of the tops file, computed on that stretch")
    assert lines[2].startswith("Interval (the formation the session opened on, one part of the well): ")
    assert "the question's" not in "\n".join(lines[:4])       # the interval does not claim the question (suite F1)
    assert lines[2].endswith(f"; {brent.inv.samples} of the well's samples") and brent.inv.samples < int(np.isfinite(d).sum())
