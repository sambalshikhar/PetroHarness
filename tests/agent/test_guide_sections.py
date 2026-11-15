"""A guide read the first time opens the workflow sections it names that this formation has, beside (not inside) the
model's action cap.
    .venv/bin/python -m pytest tests/agent/test_guide_sections.py -q"""
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.llm import Usage  # noqa: E402
from test_b5_loop import Script, _session  # noqa: E402
from petroharness.agent import direction  # noqa: E402
from petroharness.agent.loop import investigate  # noqa: E402

FIRST = {"points": ["Where is net pay?"], "intent": "locate", "focus": "where",
         "edits": [{"op": "add", "point": 1, "text": "Pay likely in the upper zones", "grade": "hypothesis"}],
         "done": False}


def _run(on: bool, steps: list, cap: int = 6):
    """A short investigation with the lookup cap (a guide always opens its sections; `on` is kept for the callers)."""
    from petroharness.agent import loop as L
    s = _session()
    llm, trace = Script([{**FIRST, **steps[0]}] + steps[1:]), {}
    old, L.ACTIONS = L.ACTIONS, cap
    try:
        investigate(llm, s, Usage(), 4000, trace, max_steps=len(steps) + 1)
    finally:
        L.ACTIONS = old
    return s, llm, trace


def _sections(s):
    return [e.args["key"] for e in s.ledger.items if e.tool == "section"]


def _opens(s, name: str) -> list:
    """The sections a guide read first opens: those of its Compare list in the families of the session's first topic
    (the net_pay_flag_analysis line is a numerical section, opened only under a numerical first topic)."""
    fams = direction.families(s.topics[:1])
    return [k for k in s.library.sections(name, s.f) if k.split(".", 1)[0] in fams]


@pytest.mark.data
def test_sections_of_a_facet_are_those_this_formation_has():
    s = _session()
    lib = s.library
    have = {x.key for x in s.f.inv.sections}
    for name in lib.facets:
        keys = lib.sections(name, s.f)
        assert set(keys) <= have and len(keys) == len(set(keys)), name
        shown = [t for on, t in map(direction.gated, lib.facets[name]["compare"]) if on]   # gated lines follow options
        named = [e.split()[1] for e in shown if e.startswith("section ")]
        assert keys == [k for k in dict.fromkeys(named) if k in have], name
    assert lib.sections("no_such_facet", s.f) == [] and lib.sections("net_reservoir_pay", None) == []


@pytest.mark.data
def test_a_guide_opens_its_sections_first_and_outside_the_cap():
    s0 = _session()
    want = _opens(s0, "net_reservoir_pay")
    if not want:
        pytest.skip("no net-pay guide section in this formation")
    work = [{"profile": "SW"}, {"profile": "PHIE"}, {"stats": ["VCL"]}]
    s, llm, trace = _run(True, [{"next": [{"guide": "net_reservoir_pay"}] + work}], cap=3)
    assert _sections(s) == want and trace["steps"][0]["guide_sections"] == want
    tools = [e.tool for e in s.ledger.items]
    first = tools.index("section")
    assert tools[first:first + len(want)] == ["section"] * len(want)          # before the model's own actions
    assert tools[first + len(want):] == ["profile", "profile", "stats"]       # all three of the cap still ran
    user = llm.sent[1][1][-1]["content"]
    guides, new = user.split("\nGUIDES (", 1)[1].split("\nNEW (from step 1):\n", 1)     # guides in their own block
    assert "GUIDE net_reservoir_pay" in guides and "GUIDE " not in new and "Only the first" not in user
    ids = [e.id for e in s.ledger.items if e.tool == "section"]
    assert [i for i in ids if f"[{i}] " in new]


@pytest.mark.data
def test_an_opened_section_and_a_guide_read_again_open_nothing_twice():
    s0 = _session()
    want = _opens(s0, "net_reservoir_pay")
    if len(want) < 2:
        pytest.skip("fewer than two net-pay guide sections in this formation")
    s, llm, trace = _run(True, [{"next": [{"section": {"key": want[0]}}]},
                                {"edits": [], "next": [{"guide": "net_reservoir_pay"}], "done": False},
                                {"edits": [], "next": [{"guide": "net_reservoir_pay"}], "done": False}])
    assert sorted(_sections(s)) == sorted(want) and len(_sections(s)) == len(set(_sections(s)))
    assert trace["steps"][1]["guide_sections"] == want[1:] and trace["steps"][2]["guide_sections"] == []


@pytest.mark.data
def test_sections_beyond_the_step_budget_are_listed_to_get():
    from petroharness.agent import loop
    s0 = _session()
    want = _opens(s0, "net_reservoir_pay")
    if not want:
        pytest.skip("no net-pay guide section in this formation")
    keep = loop.NEW_CHARS
    loop.NEW_CHARS = 200                                                      # nothing fits beside the guide
    try:
        s, llm, trace = _run(True, [{"next": [{"guide": "net_reservoir_pay"}]}])
    finally:
        loop.NEW_CHARS = keep
    user = llm.sent[1][1][-1]["content"]
    assert _sections(s) == want and "Opened, not shown this step (size limit)" in user


# --- a guide opens only what bears on the READ's first topic -----------------------------------------------------------

STATS_GUIDE = "statistics_data_analysis"          # a statistics-type guide: its Compare lists numerical sections


def _read_guide(*topics):
    """A session whose READ chose these topics (in order), one step that reads the statistics guide."""
    from test_b5_loop import chose
    s = chose(_session(), *topics)
    llm, trace = Script([{**FIRST, "next": [{"guide": STATS_GUIDE}]}]), {}
    investigate(llm, s, Usage(), 4000, trace, max_steps=2)
    return s, llm, trace


@pytest.mark.data
def test_a_guide_opens_only_the_sections_of_the_primary_topic():
    s0 = _session()
    if s0.library is None or STATS_GUIDE not in s0.library.facets:
        pytest.skip("no statistics guide in the plugged library")
    numerical = [k for k in s0.library.sections(STATS_GUIDE, s0.f) if k.startswith("numerical.")]
    stats = s0.library.workflow_stats(STATS_GUIDE, s0.f)
    if not numerical:
        pytest.skip("no numerical section of the statistics guide in this formation")
    # hydrocarbon first: the statistics guide is read, its numerical sections and workflow curves stay listed
    s, llm, trace = _read_guide("hydrocarbon_detection", "statistics_data_analysis")
    assert STATS_GUIDE in s.guides and trace["steps"][0]["guide_sections"] == []
    assert not [k for k in _sections(s) if k.startswith("numerical.")]
    assert not [e for e in s.ledger.items if e.tool == "stats"][1:]         # only the first look's stats
    user = llm.sent[1][1][-1]["content"]
    assert all(f"section {k}" in user for k in numerical)                  # still listed in its Compare lines
    # numerical first: they open with the guide
    s, llm, trace = _read_guide("statistics_data_analysis", "hydrocarbon_detection")
    assert [k for k in _sections(s) if k.startswith("numerical.")] == numerical
    opened = [e.args for e in s.ledger.items if e.tool == "stats"][1:]
    assert opened == stats[:2]                                             # the workflow's curves it names, with it
    assert trace["steps"][0]["guide_sections"][:len(numerical)] == numerical


@pytest.mark.data
def test_no_topics_open_nothing_with_a_guide():
    s0 = _session()
    if s0.library is None or not s0.library.sections(STATS_GUIDE, s0.f):
        pytest.skip("no statistics guide sections here")
    s, llm, trace = _read_guide()
    assert STATS_GUIDE in s.guides and trace["steps"][0]["guide_sections"] == [] and _sections(s) == []
