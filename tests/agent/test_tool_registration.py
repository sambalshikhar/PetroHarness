"""A tool is defined once (petroharness.tools.spec.Tool, in petroharness.agent.toolset), and every list of tools is
read from the definitions: the functions, the schemas, the brief's groups, the names the reply parser knows, the
argument a bare value fills, the one-line listing of a call. These tests check the definitions and that each list
follows them.

    .venv/bin/python -m pytest tests/agent/test_tool_registration.py -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]

from petroharness.tools.spec import Tool, Toolset  # noqa: E402


def _run(f, curves, zones=None):
    return None


# --- the definition's own rules -----------------------------------------------------------------------------------------

def test_a_toolset_gives_every_list_from_its_definitions():
    ts = Toolset(("LOOK", "COUNT", "UNUSED"))
    ts.add(Tool("peek", _run, "LOOK", "Look at curves.", {"curves": {"type": "array"}, "zones": {"type": "array"}},
                ("curves",), lead="curves"),
           Tool("tally", _run, "COUNT", lambda: "Count things.", lambda: {"what": {"type": "string"}}, (),
                main="what", table=True, verb=True),
           Tool("glance", _run, "LOOK", "Look again.", {"curve": {"type": "string"}}, ("curve",), main="curve"))
    assert ts.names() == ["peek", "tally", "glance"] and len(ts) == 3 and "peek" in ts and "stare" not in ts
    assert ts.functions() == {"peek": _run, "tally": _run, "glance": _run}
    assert ts.by_group() == (("LOOK", ("peek", "glance")), ("COUNT", ("tally",)))     # a group with no tool is left out
    assert (ts.main("peek"), ts.main("tally"), ts.main("glance"), ts.main("stare")) == ("curves", "what", "curve", "curves")
    assert (ts.lead("peek"), ts.lead("tally"), ts.lead("stare")) == ("curves", "", "")
    assert ts["tally"].table and ts["tally"].verb and not ts["peek"].table and ts.get("stare") is None
    assert ts["peek"].parameters() == ["curves", "zones"]
    one, two = ts.schemas()[0], ts.schemas()[1]
    assert one == {"type": "function", "function": {"name": "peek", "description": "Look at curves.", "parameters": {
        "type": "object", "properties": {"curves": {"type": "array"}, "zones": {"type": "array"}}, "required": ["curves"]}}}
    assert two["function"]["description"] == "Count things." and list(two["function"]["parameters"]["properties"]) == ["what"]
    one["function"]["parameters"]["properties"]["curves"]["type"] = "changed"            # a schema is a copy
    assert ts.schemas()[0]["function"]["parameters"]["properties"]["curves"]["type"] == "array"


@pytest.mark.parametrize("tool, says", [
    (Tool("peek", _run, "LOOK", "Twice."), "defined twice"),
    (Tool("two words", _run, "LOOK", "Text."), "a tool named"),
    (Tool("stare", _run, "NOWHERE", "Text."), "the brief does not list"),
    (Tool("stare", None, "LOOK", "Text."), "nothing to run"),
    (Tool("stare", _run, "LOOK", "  "), "no description"),
    (Tool("stare", _run, "LOOK", "Text.", {"curves": {}}, ("curve",)), "requires curve"),
    (Tool("stare", _run, "LOOK", "Text.", {"curves": {}}, (), lead="curve"), "listed by its argument 'curve'"),
    (Tool("stare", _run, "LOOK", "Text.", {"zones": {}}), "a bare value given to the tool stare fills 'curves'"),
])
def test_a_wrong_definition_is_said_when_it_is_added(tool, says):
    ts = Toolset(("LOOK",))
    ts.add(Tool("peek", _run, "LOOK", "Look."))
    with pytest.raises(ValueError, match=says) as e:
        ts.add(tool)
    assert "WHAT:" in str(e.value) and "FIX:" in str(e.value)
    assert ts.names() == ["peek"]


# --- the harness's tools ------------------------------------------------------------------------------------------------

def test_every_definition_is_whole():
    from petroharness.agent.toolset import TOOLSET
    assert len(TOOLSET) >= 29
    for t in TOOLSET:
        fn = t.schema()["function"]
        props = fn["parameters"]["properties"]
        assert fn["description"].strip(), f"{t.name} has no description"
        assert set(fn["parameters"]["required"]) <= set(props), t.name
        assert not t.lead or t.lead in props, f"{t.name}: its listing argument {t.lead!r} is not one of its arguments"
        assert not props or t.main in props, f"{t.name}: a bare value fills {t.main!r}, not one of its arguments"
        # every argument the model is shown is one the function takes (else a call would be told it was ignored)
        unknown = [a for a in props if a not in t.parameters()]
        assert not unknown, f"{t.name} shows arguments its function does not take: {unknown}"
        if t.verb:                                                    # a verb reaches every Petrophys function it serves
            assert {"search", "run", "args", "label"} <= set(props) and fn["parameters"]["required"] == [], t.name


def test_every_list_of_tools_follows_the_definitions():
    from petroharness.agent import loop as L
    from petroharness.agent import schemas as S
    from petroharness.agent.toolset import TOOLS, TOOLSET
    names = TOOLSET.names()
    assert L.TOOLS == set(names)                                          # the reply parser
    assert list(TOOLS) == names and S.TOOLS is TOOLS                      # the functions the door runs
    assert [t["function"]["name"] for t in S.named()] == names            # the schemas
    assert [n for _, ns in L.VERBS for n in ns] == names                  # the brief's groups, in the brief's order
    assert set(S.LIBRARY_NAMES) == {t.name for t in TOOLSET if t.verb}
    for t in TOOLSET:
        assert L.coerce_action({t.name: "X"}) == ("tool", t.name, {t.main: "X"}), t.name   # a bare value: its main argument
    assert L.coerce_action({"what_if": "net_pay"}) == ("tool", "what_if", {"property": "net_pay"})
    assert L.coerce_action({"unit_roles": "Z2"}) == ("tool", "unit_roles", {"zones": "Z2"})


def test_the_brief_lists_each_tool_once_under_its_group():
    from petroharness.agent import loop as L
    from petroharness.agent.toolset import TOOLSET
    text = L.tools_text()
    lines = text.split("\n")
    at = {head: lines.index(f"  {head}") for head, _ in TOOLSET.by_group()}
    assert list(at.values()) == sorted(at.values())                       # the groups in their order
    heads = sorted(at.values()) + [len(lines)]
    for t in TOOLSET:
        mine = [i for i, ln in enumerate(lines) if ln.startswith(f'  {{"{t.name}": {{')]
        assert len(mine) == 1, f"{t.name} is listed {len(mine)} times in the brief"
        start = at[t.group]
        assert start < mine[0] < heads[heads.index(start) + 1], f"{t.name} is not under {t.group}"
        args = ", ".join(f'"{k}": ...' for k in t.properties())
        assert lines[mine[0]].startswith(f'  {{"{t.name}": {{{args}}}}}   '), t.name
    assert L.brief(None).count(text) == 1                                 # the investigation's system prompt carries it


def test_a_call_is_listed_by_its_tools_lead():
    from petroharness.agent.ledger import Item
    item = lambda tool, args: Item(id="E1", tool=tool, args=args, key="k", rows=[], text="t").call_text()
    assert item("runs", {"condition": "NET_PAY", "limit": 5}) == "runs NET_PAY (limit 5)"
    assert item("stats", {"curves": ["PHIE", "SW"], "zones": ["Z1"]}) == "stats PHIE, SW (zones Z1)"
    assert item("compare", {"a": "PHIE", "b": "PHIE_CC"}) == "compare PHIE vs PHIE_CC"
    assert item("crossplot", {"y": "RHOB", "x": "NPHI"}) == "crossplot RHOB on NPHI"
    assert item("zone_classes", {"topic": "flow_units"}) == "zone_classes flow_units"
    assert item("calc", {"expression": "1 + 2"}) == "calc 1 + 2"
    assert item("check", {"what": "bad_hole"}) == "check (what bad_hole)"                 # a verb: no lead, no gap


def test_a_call_of_a_tool_with_no_lead_is_listed_without_a_gap():
    from petroharness.agent.ledger import Item
    item = lambda tool, args: Item(id="E1", tool=tool, args=args, key="", rows=[], text="")
    assert item("unit_roles", {"zones": ["Z1", "Z2"]}).call_text() == "unit_roles (zones Z1, Z2)"
    assert item("pay_summary", {}).call_text() == "pay_summary"
    assert item("stats", {"curves": ["GR"], "zones": ["Z1"]}).call_text() == "stats GR (zones Z1)"
