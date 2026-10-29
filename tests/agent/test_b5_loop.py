"""The investigation loop, offline: action and reply shapes (hand-written), and the control flow driven by a scripted model on a real
formation (no K2H).

    .venv/bin/python -m pytest tests/agent/test_b5_loop.py -q   (PETROHARNESS_DATA selects the dataset)
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.llm import Usage  # noqa: E402
from petroharness.agent.loop import Session, coerce_action, investigate, read_reply, salvage, tools_text  # noqa: E402

MAX_ACTIONS = 3            # the action cap these tests run under (the harness's own cap is loop.ACTIONS, 6)


# --- action shapes --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ({"stats": {"curves": ["SW"], "where": "NET_PAY"}}, ("tool", "stats", {"curves": ["SW"], "where": "NET_PAY"})),
    ({"tool": "stats", "args": {"curves": ["SW"]}}, ("tool", "stats", {"curves": ["SW"]})),
    ({"tool": "stats", "curves": ["SW"]}, ("tool", "stats", {"curves": ["SW"]})),
    ({"action": "runs", "condition": "NET_PAY"}, ("tool", "runs", {"condition": "NET_PAY"})),
    ({"runs": "NET_PAY"}, ("tool", "runs", {"condition": "NET_PAY"})),
    ({"runs": {"condition": "SW < 0.5", "zones": ["Z1"]}}, ("tool", "runs", {"condition": "SW < 0.5", "zones": ["Z1"]})),
    ({"stats": ["SW", "PHIE"]}, ("tool", "stats", {"curves": ["SW", "PHIE"]})),
    ({"compare": ["PHIE", "PHIE_CC"]}, ("tool", "compare", {"a": "PHIE", "b": "PHIE_CC"})),
    ({"compare": {"a": "PHIE", "b": "PHIT"}}, ("tool", "compare", {"a": "PHIE", "b": "PHIT"})),
    ({"profile": "SW"}, ("tool", "profile", {"curve": "SW"})),
    ({"section": "hydrocarbon.petrophysical_hydrocarbon_indicators"}, ("tool", "section", {"key": "hydrocarbon.petrophysical_hydrocarbon_indicators"})),
    ({"step": "saturation"}, ("tool", "step", {"name": "saturation"})),
    ({"get": "e3", "find": "Z2"}, ("get", "E3", "Z2")),
    ({"get": "[E3]", "zone": "Z2"}, ("get", "E3", "Z2")),
    ({"action": "get", "id": "E4", "query": ["LOW_SW", "Z1"]}, ("get", "E4", "LOW_SW, Z1")),
    ({"find": "Z3"}, ("find", "Z3")),
    ({"find": ["Z3", "SW"]}, ("find", "Z3, SW")),
    ({"guide": "gas"}, ("guide", "gas")),
    ({"tool": "guide", "facet": "pay"}, ("guide", "pay")),
])
def test_coerce_action(raw, want):
    assert coerce_action(raw) == want


@pytest.mark.parametrize("raw", [None, "stats SW", {}, {"open": "a.b"}, {"get": "Z3"}, {"tool": "jump"}, {"op": "add"}])
def test_coerce_action_rejects(raw):
    assert coerce_action(raw) is None


def test_tools_text_lists_every_tool_once():
    t = tools_text()
    for name in ("stats", "runs", "compare", "profile", "section", "step"):
        assert t.count(f'{{"{name}": {{') == 1


# --- reply reading --------------------------------------------------------------------------------------------------

def test_read_reply_plain_and_wrapped():
    r = read_reply('{"focus": "x", "edits": [], "next": [{"runs": "NET_PAY"}], "done": false}')
    assert r["next"] == [{"runs": "NET_PAY"}] and r["done"] is False
    r = read_reply('Sure:\n```json\n{"reply": {"edits": [{"op": "add", "point": 1, "text": "t"}], "next": [], "done": "true"}}\n```')
    assert r["done"] is True and len(r["edits"]) == 1


def test_read_reply_takes_the_last_object_after_a_draft():
    text = ('{"edits": [], "next": [{"runs": "A"}], "done": false}\nOn reflection:\n'
            '{"edits": [{"op": "add", "point": 1, "text": "t"}], "next": [{"runs": "NET_PAY"}], "done": false}')
    r = read_reply(text)
    assert r["next"] == [{"runs": "NET_PAY"}] and len(r["edits"]) == 1


def test_read_reply_refuses_an_object_closing_early():
    text = '{"edits": [], "next": [], "done": false} {"op": "add", "point": 1, "text": "t"} {"runs": "NET_PAY"}'
    with pytest.raises(ValueError):
        read_reply(text)


def test_salvage_keeps_complete_edits_and_actions():
    text = '{"edits": [{"op": "add", "point": 1, "text": "t", "grade": "low"}, {"op": "drop", "id": "C2"}], "next": [{"stats": {"curves": ["SW"]}}, {"runs": "NET_PAY"'
    s = salvage(text)
    assert len(s["edits"]) == 2 and len(s["next"]) == 1


# --- the loop with a scripted model ---------------------------------------------------------------------------------

class Script:
    """A model that replies from a list; records what it was sent."""

    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def replays_reasoning(self):
        return True

    def chat(self, stage, messages, usage, max_tokens, retry=False):
        self.sent.append((stage, messages))
        usage.log.append({"stage": stage, "prompt_tokens": sum(len(m["content"]) for m in messages) // 4})
        r = self.replies.pop(0) if self.replies else '{"edits": [], "next": [], "done": true}'
        return r if isinstance(r, str) else json.dumps(r)


def _session():
    from test_b2_tools import F
    t, f = next((t, f) for t, f in F() if "NET_PAY" in f.inv.curves and "SW" in f.inv.curves)
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.map import render
    return chose(Session(t, f, render(f.inv), Ledger(f)), "hydrocarbon_detection")


def chose(s, *topics):
    """The session as a READ call choosing these topics leaves it (the map kept as built)."""
    from petroharness.agent import direction
    s.topics, s.families = list(topics), direction.families(topics)
    return s


MEANS = "the zone holds the formation's hydrocarbon-bearing rock"


@pytest.mark.data
def test_loop_runs_tools_edits_and_stops_when_settled(monkeypatch):
    from petroharness.agent import loop as L
    monkeypatch.setattr(L, "ACTIONS", MAX_ACTIONS)            # the cap under test: 3 (6 by default)
    s = _session()
    llm = Script([
        {"points": ["Where is net pay?", "How thick is it?"], "intent": "locate", "focus": "where",
         "edits": [{"op": "add", "point": 1, "text": "Pay likely in the upper zones", "grade": "hypothesis"},
                   {"op": "add", "point": 2, "text": "Pay is likely thin", "grade": "hypothesis"}],
         "next": [{"runs": "NET_PAY"}, {"stats": {"curves": ["SW"], "where": "NET_PAY"}}, {"guide": "net_reservoir_pay"},
                  {"profile": "SW"}, {"profile": "PHIE"}],                  # a guide is free; a fourth action is left out
         "done": False},
        None,                                                               # filled below from the ledger
    ])
    trace = {}

    def second(stage, messages, usage, max_tokens, retry=False):
        user = messages[-1]["content"]
        assert "Only the first 3 actions ran" in user and "[E2]" in user and "[E3]" in user
        assert "GUIDE net_reservoir_pay" in user.split("\nGUIDES (", 1)[1].split("\nNEW (from step 1)", 1)[0]  # in its block
        runs_item = next(e for e in s.ledger.items if e.tool == "runs")      # E1 is the first look
        total = __import__("re").search(r"all zones: ([\d.]+)", runs_item.text).group(1)
        return json.dumps({"focus": "settle", "edits": [
            {"op": "revise", "id": "C1", "text": "NET_PAY is set in the zones listed by the runs", "ev": [runs_item.id], "grade": "moderate", "means": MEANS},
            {"op": "revise", "id": "C2", "text": f"NET_PAY totals {total} {s.f.inv.depth_unit} over all zones", "ev": [runs_item.id], "grade": "moderate", "means": MEANS}],
            "next": [], "done": True})
    llm.replies[1] = None
    orig = llm.chat

    def chat(stage, messages, usage, max_tokens, retry=False):
        if stage == "step_2":
            llm.sent.append((stage, messages))
            usage.log.append({"stage": stage})
            return second(stage, messages, usage, max_tokens)
        return orig(stage, messages, usage, max_tokens, retry)
    llm.chat = chat
    claims = investigate(llm, s, Usage(), 4000, trace)
    calls = [e.call_text().split(" ")[0] for e in s.ledger.items]
    assert calls[:1] == ["stats"] and calls[-3:] == ["runs", "stats", "profile"]   # the first look first (stats only)
    assert all(c in ("section", "stats") for c in calls[1:-3]), calls        # what the guide opened (its sections, curves)
    auto = trace["steps"][0]["guide_sections"]
    assert len(trace["steps"]) == 2 and len(trace["steps"][0]["actions"]) == 1 + len(auto) + MAX_ACTIONS   # the guide,
                                                                                   #   what it opened and 3 actions
    assert not claims.done_issues(), claims.render()
    assert s.guides == ["net_reservoir_pay"]


@pytest.mark.data
def test_done_is_refused_once_while_points_are_open_then_the_last_step_ends_it():
    s = _session()
    llm = Script([
        {"points": ["Where is net pay?"], "intent": "locate", "edits": [{"op": "add", "point": 1, "text": "Pay in the upper zones", "grade": "hypothesis"}],
         "next": [], "done": True},                                        # done with a hypothesis: refused once
        {"edits": [], "next": [], "done": True},                           # done again: accepted (the refusal is spent)
    ])
    trace = {}
    claims = investigate(llm, s, Usage(), 4000, trace, max_steps=5)
    assert "NOT DONE" in llm.sent[1][1][-1]["content"]
    assert len(trace["steps"]) == 2 and trace["done_issues"]


@pytest.mark.data
def test_the_last_step_says_so_and_ends():
    s = _session()
    step = {"edits": [], "next": [{"runs": "NET_PAY"}], "done": False}
    llm = Script([{"points": ["p"], "intent": "value", "edits": [], "next": [{"runs": "NET_PAY"}], "done": False}, step, step])
    trace = {}
    investigate(llm, s, Usage(), 4000, trace, max_steps=3)
    assert "This is the last step" in llm.sent[-1][1][-1]["content"] and len(trace["steps"]) == 3


@pytest.mark.data
def test_an_unreadable_reply_is_fixed_or_reported():
    s = _session()
    llm = Script(['{"points": ["p"], "intent": "value", "edits": [], "next": [{"runs": "NET_PAY"}], "done": false}',
                  '{"edits": [{"op": "add", "point": 1 "text": "x"}], "next": [], "done": false',   # broken
                  '{"edits": [{"op": "add", "point": 1, "text": "x"}], "next": [], "done": false}',  # the syntax fix
                  '{"edits": [], "next": [], "done": true}'])
    trace = {}
    investigate(llm, s, Usage(), 4000, trace, max_steps=4)
    assert trace["steps"][1].get("repaired", {}).get("by") in ("fix", "salvage", "salvage, incomplete")
    assert any(c["text"] == "x" for c in trace["claims"])


@pytest.mark.data
def test_get_find_and_repeated_calls():
    s = _session()
    out, item = s.run(("tool", "runs", {"condition": "NET_PAY"}))
    assert item is not None and out.startswith("[E1]")
    out, again = s.run(("tool", "runs", {"condition": "net_pay"}))
    assert again is item and out.startswith("[E1] (opened before") and out.endswith(item.text)   # whole again
    z = s.f.view.zones[0].zone_id
    assert s.run(("get", "E1", z))[0].startswith("[E1]")
    assert z in s.run(("find", z))[0]
    out, _ = s.run(("tool", "stats", {"curves": ["NOSUCH"]}))
    assert "not run" in out and "curves with data" in out
    first, again = s.run(("guide", "porosity")), s.run(("guide", "porosity"))
    assert first == again and first[0].startswith("GUIDE porosity") and s.guides == ["porosity"]   # whole again


@pytest.mark.data
def test_prompts_stay_bounded_on_the_largest_formation():
    from test_b2_tools import F
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.map import render
    t, f = max(F(), key=lambda tf: tf[1].inv.samples * max(len(tf[1].view.zones), 1))
    s = chose(Session(t, f, render(f.inv), Ledger(f)), "hydrocarbon_detection")
    many = [{"stats": {"curves": [c]}} for c in list(f.inv.curves)[:30]]
    replies = [{"points": ["p"], "intent": "characterize", "edits": [], "next": many[:3], "done": False}]
    replies += [{"edits": [], "next": many[i:i + 3], "done": False} for i in range(3, 30, 3)]
    llm = Script(replies)
    trace = {}
    investigate(llm, s, Usage(), 4000, trace, max_steps=8)
    sizes = [r["prompt_chars"] for r in trace["steps"]]
    assert max(sizes) < 72000, sizes            # map + direction + claims + opened (6k) + new (12k); the brief's
    #   tool list grouped by verb, with the verbs over Petrophys and their menus, adds about 11.5k (3.5.2)


@pytest.mark.data
def test_points_are_asked_for_when_the_draft_numbers_points_it_did_not_write():
    s = _session()
    llm = Script([
        {"focus": "f", "edits": [{"op": "add", "point": 1, "text": "h1", "grade": "hypothesis"},
                                 {"op": "add", "point": 2, "text": "h2", "grade": "hypothesis"}], "next": [], "done": False},
        '{"points": ["Where is the pay?", "How thick is it?"], "intent": "locate"}',
        {"edits": [], "next": [], "done": True}])
    trace = {}
    claims = investigate(llm, s, Usage(), 4000, trace, max_steps=3)
    assert s.points == ["Where is the pay?", "How thick is it?"] and len(claims.claims) == 2
    assert llm.sent[1][0] == "step_1_points" and trace["steps"][0]["points_asked"]


@pytest.mark.data
@pytest.mark.parametrize("act", [
                                 ("tool", "stats", {"curves": True}),
                                 ("tool", "runs", {"condition": ["SW < 0.5"]}),
                                 ("tool", "compare", {"a": "PHIE", "b": 3}),
                                 ("tool", "runs", {"condition": "NET_PAY", "limit": True})])
def test_malformed_arguments_are_a_message_not_a_crash(act):
    s = _session()
    out, item = s.run(act)
    assert item is None and "not run" in out


@pytest.mark.data
def test_statistics_all_and_a_single_name_as_text():
    s = _session()
    full = s.run(("tool", "stats", {"curves": ["SW"]}))[0]
    assert s.run(("tool", "stats", {"curves": "SW", "statistics": "all"}))[0].endswith(full.split("] ", 1)[1])
    out = s.run(("tool", "stats", {"curves": ["SW"], "statistics": "mean"}))[0]
    assert "mean" in out and "median" not in out.split("\n", 2)[1]


@pytest.mark.parametrize("raw", ["22.9448 ft", "SW 0.2703", "0.007902 apart", "-0.4515", "8205619.5955"])
def test_writer_reports_numbers_as_the_results_show_them(raw):
    """The delivered text keeps the results' own digits (no rounding in code)."""
    from petroharness.agent.writer import report_numbers
    assert report_numbers(raw) == raw


@pytest.mark.data
def test_a_typo_is_not_an_absence():
    s = _session()
    if "BVW" not in s.f.inv.curves:
        pytest.skip("no BVW")
    out, _ = s.run(("tool", "stats", {"curves": ["SW", "BWV"]}))
    assert "No curve named BWV (did you mean BVW" in out and "No data in this interval for: BWV" not in out
    out, _ = s.run(("tool", "stats", {"curves": ["BWV"]}))
    assert "not a curve here" in out and "did you mean" in out and "BVW" in out


def test_the_zone_table_gets_lines_of_its_own():
    import re
    draft = "Overview sentence. {{ZONE_TABLE}} Next sentence."
    fixed = re.sub(r"[ \t]*\{\{ZONE_TABLE\}\}[ \t]*", "\n\n{{ZONE_TABLE}}\n\n", draft)
    from petroharness.agent.compose import compose
    out = compose(fixed, "| a | b |\n|---|---|\n| 1 | 2 |")
    assert "sentence.\n\n| a | b |" in out and "| 1 | 2 |\n\nNext" in out


@pytest.mark.parametrize("reply,want", [
    ("## Overview\nSW 0.2 [E1].", "## Overview\nSW 0.2 [E1]."),
    ("The user wants me to rewrite the answer. Let me check.\n\n## Overview\nSW 0.2 [E1].", "## Overview\nSW 0.2 [E1]."),
    ("The user is pointing out 96.5%. Let me check where I used that number.", ""),
    ("## Overview\nActually, I said 0.3 before.\n", ""),
    ('- "157.0 ft" - this was supposed to be the share\n## Overview\nok', "## Overview\nok"),
    ("## Overview\nThe calibration status is unverified; core is recommended.", "## Overview\nThe calibration status is unverified; core is recommended."),
])
def test_working_notes_are_removed_or_the_reply_refused(reply, want):
    from petroharness.agent.writer import clean_reply
    assert clean_reply(reply, "## Overview\nx") == want



# --- asks: what the question asks is point 1 ---------------------------------------------------------------------------

def test_the_step_1_example_is_json_with_asks_as_point_1():
    from petroharness.agent.loop import step1
    for text in (step1(), step1(None)):                     # with the plugged library and with none
        ex = json.loads(text[text.index("{\"asks\""):])
        assert ex["asks"] and all(e["point"] in (1, 2, 3) for e in ex["edits"]) and ex["edits"][0]["point"] == 1


def test_salvage_keeps_asks():
    text = '{"asks": "Which zones hold oil, gas or water?", "points": ["Where is SW low?"], "edits": [{"op": "add", "point": 1, "text": "t"}], "next": [{"runs": "NET_PAY"'
    out = salvage(text)
    assert out["asks"] == "Which zones hold oil, gas or water?" and out["points"] == ["Where is SW low?"]


@pytest.mark.data
@pytest.mark.parametrize("reply,want", [
    ({"asks": "Which zones hold oil, gas or water?", "points": ["Where is SW low?", "Does RDEP agree?"]},
     ["Which zones hold oil, gas or water?", "Where is SW low?", "Does RDEP agree?"]),
    ({"asks": "Where is net pay?", "points": ["Where is net pay?", "How thick?"]}, ["Where is net pay?", "How thick?"]),
    ({"points": ["Where is SW low?", "Does RDEP agree?"]}, ["Where is SW low?", "Does RDEP agree?"]),
    ({"asks": {"text": "Which zones are pay?"}, "points": []}, ["Which zones are pay?"]),
])
def test_asks_becomes_point_1(reply, want):
    s = _session()
    first = dict(reply, intent="characterize", edits=[{"op": "add", "point": 1, "text": "Pay likely in the upper zones", "grade": "hypothesis"}],
                 next=[], done=False)
    llm = Script([first, {"edits": [], "next": [], "done": True}])
    trace = {}
    investigate(llm, s, Usage(), 4000, trace, max_steps=2)
    assert s.points == want and s.claims.claims["C1"].point == 1


# --- the first look: each zone's key curves for the model's topics, opened before step 1 -------------------------------

def test_every_first_look_curve_is_a_registry_curve():
    import yaml
    from petroharness.agent import direction
    reg = yaml.safe_load((Path(__file__).resolve().parents[2] / "src" / "petroharness" / "resources" / "rules" / "curves.yaml").read_text())
    names = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                names.add(str(k)); walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
        elif isinstance(x, str):
            names.update(re.findall(r"\b[A-Z][A-Z0-9_]+\b", x))
    walk(reg)
    for area, a in direction.areas().items():
        cs = direction.overview([area])
        assert cs == a["overview"] and len(cs) <= 8 and set(cs) <= names, (area, set(cs) - names)
        assert cs or area == "statistics_data_analysis", area          # statistics: the curves the question names


@pytest.mark.data
def test_the_first_look_is_e1_and_reaches_step_1():
    from petroharness.agent import direction
    from petroharness.agent import loop as L
    s = _session()
    llm = Script([{"asks": "Where is the pay?", "points": [], "intent": "locate", "edits": [], "next": [], "done": True}])
    trace = {}
    investigate(llm, s, Usage(), 4000, trace, max_steps=2)
    own = [c for c in direction.overview(s.topics) if c in s.f.inv.curves][:8]
    core = [c for c in L.CORE_CURVES if c in s.f.inv.curves]
    e1 = s.ledger.items[0]
    want = e1.args["curves"]                         # the topics' look plus the reservoir context (core_look)
    assert e1.id == "E1" and e1.tool == "stats" and set(core) <= set(want) and want[0] == own[0]
    assert "FIRST LOOK" in llm.sent[0][1][-1]["content"] and "[E1]" in llm.sent[0][1][-1]["content"]
    assert trace["overview"].startswith("stats ") and json.loads(trace["overview"].split(" ", 1)[1])["curves"] == want
