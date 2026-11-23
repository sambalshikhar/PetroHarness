"""Changing a setting in a conversation (Conversation.adopt; docs/SESSIONS.md, "Changing a setting"): the change is
logged with who asked and the question it takes effect at; the well is interpreted again under it; the ledger goes on,
what was opened before says it rests on the earlier settings and the same call is computed anew; the next question's
prompts name the change and its answer's header says what it ran under; resuming replays the change in its place; and
each answer's trail shows the parameters it was made with. A scripted model on the public sample well (no server).

    PETROHARNESS_SAMPLE_LAS=<folder of tuhua-7.las> .venv/bin/python -m pytest tests/session/test_adopt.py -q
"""
import json
import shutil

import pytest

from petroharness.evidence.graph import EvidenceGraph
from petroharness.session import Conversation
from petroharness.session import chat as CH
from petroharness.well import settings as T
from _support.model import DONE, ScriptedModel, newest_result  # noqa: E402

from _wells import SAMPLES  # noqa: E402  (Petrophys's sample files; PETROHARNESS_SAMPLE_LAS for a folder of them)
LAS = SAMPLES / "tuhua-7.las"
WINDOW = dict(top=600.0, base=700.0, depth_unit="m", formation="test window")
Q1 = "What is the mean water saturation of the interval?"
Q2 = "And with the new cementation exponent?"

pytestmark = pytest.mark.data


class Model(ScriptedModel):
    """READ; step 1 opens the saturation's statistics and adds a claim; step 2 settles it on the newest result it was
    shown and is done; the writer states no number."""

    def __init__(self):
        super().__init__({
            "read*": {"topics": ["saturation"], "named": ["SW"]},
            "step_1": {"points": ["What is the mean SW?"], "intent": "characterize", "focus": "water saturation",
                       "edits": [{"op": "add", "point": 1, "text": "Water saturation is read zone by zone",
                                  "grade": "hypothesis"}],
                       "next": [{"stats": {"curves": ["SW"]}}], "done": False},
            "step_2": lambda m: {"edits": [{"op": "revise", "id": "C1", "ev": [newest_result(m)], "grade": "moderate",
                                            "means": "the saturation as computed"}], "next": [], "done": True},
            "step_*": DONE, "settle*": DONE},
            default="## Water saturation\nWater saturation is read zone by zone from the results.\n")

@pytest.fixture(scope="module")
def env():
    if not LAS.exists():
        pytest.skip(f"no sample wells at {SAMPLES} (PETROHARNESS_SAMPLE_LAS)")
    mp = pytest.MonkeyPatch()
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS"):
        mp.delenv(key, raising=False)
    yield
    mp.undo()


@pytest.fixture(scope="module")
def changed(env, tmp_path_factory):
    """A conversation: question 1, then m 1.8 adopted, then question 2 (the same call asked again)."""
    folder = tmp_path_factory.mktemp("adopt") / "s"
    model = Model()
    c = Conversation.start(LAS, folder, **WINDOW, llm_factory=lambda cfg: model, figures=False, direct=False)
    m_before = T.used(c.p.view.prep).get("m", {}).get("value")
    t1 = c.ask(Q1)
    opened1 = list(c.turns[0]["opened"])
    made = c.adopt({"m": 1.8})
    asked2 = len(model.sent)
    t2 = c.ask(Q2)
    return {"c": c, "model": model, "t1": t1, "t2": t2, "made": made, "opened1": opened1, "asked2": asked2,
            "m_before": m_before, "folder": folder}


def _sw_items(c):
    return [e for e in c.live.ledger.items if e.tool == "stats" and "SW" in json.dumps(e.args)]


def test_the_change_is_logged_and_the_well_interpreted_again(changed):
    c, made = changed["c"], changed["made"]
    assert made == [{"key": "m", "from": None, "to": 1.8}]
    assert c.settings == {"m": 1.8}
    ev = c.log.events("settings")
    assert len(ev) == 1 and ev[0]["turn"] == 2 and ev[0]["by"] == "user" and ev[0]["interpretation"] == {"m": 1.8}
    assert ev[0]["zones"] and ev[0]["interval"]
    assert "zones_before" not in ev[0]                                         # this change cut no zone anew
    assert T.used(c.p.view.prep)["m"]["value"] == pytest.approx(1.8)            # the saturation step ran with it
    assert changed["m_before"] != pytest.approx(1.8)
    assert c.adopt({"m": 1.8}) == [] and len(c.log.events("settings")) == 1       # the settings in force: no change
    with pytest.raises(ValueError, match="cannot be used"):
        c.adopt({"m": -3.0})


def test_the_ledger_goes_on_and_marks_what_was_opened_before(changed):
    c = changed["c"]
    first, second = _sw_items(c)[0], _sw_items(c)[-1]
    assert first.id in changed["opened1"] and second.id not in changed["opened1"]     # the same call computed anew
    assert int(second.id[1:]) > max(int(x[1:]) for x in changed["opened1"])          # the ids continue
    assert first.text != second.text                                                  # SW under the new m
    led = c.live.ledger
    assert set(changed["opened1"]) <= set(led.before)
    assert "rests on the earlier settings" in led.show(first, False) or "rest on the earlier settings" in led.show(first, False)
    assert "settings change before question 2" in led.digest(first)
    assert second.id not in led.before and "earlier settings" not in led.show(second)


def test_the_next_question_s_prompts_name_the_change(changed):
    later = [x for x in changed["model"].sent[changed["asked2"]:] if x["stage"] == "step_1"][0]
    text = later["messages"][-1]["content"]
    assert "Settings changed before question 2 (by the user): m the default" in text and "-> 1.8" in text
    assert "The well was interpreted again with them." in text
    assert "cut anew" not in text and not changed["c"].live.ledger.then      # the zones are as they were
    assert not any("Settings changed" in m["content"] for x in changed["model"].sent[:changed["asked2"]]
                   for m in x["messages"])                                   # never before the change


def test_the_answers_record_what_they_ran_under(changed):
    t1, t2 = changed["t1"], changed["t2"]
    assert "settings" not in t1.trace                                         # before the change: as without one
    assert t2.trace["settings"]["changed"] == changed["made"] and t2.trace["settings"]["in_force"] == {"m": 1.8}
    head = (t2.folder / "answer.md").read_text().split("---")[0]
    assert "**Settings changed for this question:** m the default" in head and "-> 1.8" in head
    assert "Settings" not in (t1.folder / "answer.md").read_text().split("---")[0]
    assert changed["c"].turns[1]["settings_changed"] == changed["made"] and "settings_changed" not in changed["c"].turns[0]


def test_resuming_replays_the_change_in_its_place(changed, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(changed["folder"], copy, symlinks=True)
    r = Conversation.resume(copy, llm_factory=lambda cfg: Model())
    assert r.log.events("session_resume")[-1]["differences"] == []        # every result opened again as recorded
    assert r.settings == {"m": 1.8} and T.used(r.p.view.prep)["m"]["value"] == pytest.approx(1.8)
    assert set(changed["opened1"]) <= set(r.live.ledger.before)
    assert "Settings changed before question 2" in r.earlier()


def test_each_answer_s_trail_shows_the_parameters_it_was_made_with(changed):
    g = EvidenceGraph.from_log(changed["folder"])

    def m_of(n):
        steps = {s["step"]: s for s in g.trail(n)["steps"]}
        return next((s["parameters"].get("m") for s in steps.values() if "m" in s["parameters"]), None)
    assert m_of(1) == pytest.approx(changed["m_before"]) and m_of(2) == pytest.approx(1.8)
    assert g.trail(1)["settings"] == [] and g.trail(2)["settings"][0]["changes"] == changed["made"]
    assert all("@gen" not in c["name"] for c in g.trail(2)["curves"])     # names as the well has them


def test_the_chat_commands_change_and_show_the_settings(changed):
    c = changed["c"]
    assert CH._value("1.8") == 1.8 and CH._value("default") is None and CH._value("0.3,0.6") == [0.3, 0.6]
    assert "m=1.8" in CH.command(c, "/settings") and "before question 2" in CH.command(c, "/settings")
    assert "usage" in CH.command(c, "/set m")
    assert "not changed" in CH.command(c, "/set m=-1")
    assert "no change" in CH.command(c, "/set m=1.8")


def test_settings_helpers():
    assert T.merged({"m": 2.0, "n": 2.0}, {"m": 1.8, "n": None, "a": 1.0}) == {"m": 1.8, "a": 1.0}
    assert T.diff({"m": 2.0}, {"m": 1.8, "a": 1.0}) == [{"key": "m", "from": 2.0, "to": 1.8},
                                                       {"key": "a", "from": None, "to": 1.0}]
    assert T.describe([{"key": "m", "from": 2.0, "to": 1.8}]) == "m 2 -> 1.8"
    assert T.describe([{"key": "rw", "from": None, "to": 0.04}]).startswith("rw the default")


# ---------- a change that cuts the zones anew ----------
REZONE = {"zone_min_thickness_m": 5}      # the window's thin first zone goes: Z2 and Z3 of before are Z1 and Z2 after


@pytest.fixture(scope="module")
def rezoned(env, tmp_path_factory):
    """Question 1, then a zone rule that cuts the zones anew, then question 2."""
    folder = tmp_path_factory.mktemp("rezoned") / "s"
    model = Model()
    c = Conversation.start(LAS, folder, **WINDOW, llm_factory=lambda cfg: model, figures=False, direct=False)
    then = [(z.zone_id, z.top, z.base) for z in c.p.view.zones]
    c.ask(Q1)
    opened1 = list(c.turns[0]["opened"])
    c.adopt(REZONE)
    asked2 = len(model.sent)
    shown = c.earlier()
    c.ask(Q2)
    now = [(z.zone_id, z.top, z.base) for z in c.p.view.zones]
    return {"c": c, "model": model, "opened1": opened1, "asked2": asked2, "then": then, "now": now, "folder": folder,
            "shown": shown}


def test_the_log_holds_the_zones_before_a_change_that_cut_them_anew(rezoned):
    c, then, now = rezoned["c"], rezoned["then"], rezoned["now"]
    assert len(now) < len(then) and then[1][1:] == now[0][1:] and then[1][0] != now[0][0]   # the same stretch, another id
    ev = c.log.events("settings")[0]
    assert [(z["zone"], z["top"], z["base"]) for z in ev["zones_before"]] == then
    assert [(z["zone"], z["top"], z["base"]) for z in ev["zones"]] == now


def test_the_next_question_is_shown_the_zones_of_then_and_where_each_lies_now(rezoned):
    then, now = rezoned["then"], rezoned["now"]
    later = [x for x in rezoned["model"].sent[rezoned["asked2"]:] if x["stage"] == "step_1"][0]
    text = later["messages"][-1]["content"]
    assert f"The zones were cut anew: {len(then)} before, {len(now)} now." in text
    assert "A zone id in a result or an answer from before names the zone as it was then" in text
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("then Z")]
    assert len(lines) == len(then)
    assert lines[0].startswith(f"then {then[0][0]} ") and lines[0].endswith(": now outside any zone")
    assert f": now {now[0][0]} " in lines[1] and lines[1].endswith("(the same depths)")       # then Z2 = now Z1
    assert text.index("Settings changed before question 2") < text.index("The zones were cut anew")
    assert rezoned["shown"] in text                                                 # the block as earlier() gives it


def test_a_result_opened_before_keeps_the_zones_it_was_opened_under(rezoned):
    c, then, now = rezoned["c"], rezoned["then"], rezoned["now"]
    led = c.live.ledger
    first, second = _sw_items(c)[0], _sw_items(c)[-1]
    assert set(rezoned["opened1"]) == set(led.then) and second.id not in led.then
    assert "and its zone ids name the zones as cut then" in led.show(first, False)
    assert "its zone ids: the zones as cut then" in led.digest(first)
    assert "zones as cut then" in led.get(first.id, then[1][0]) and "zones as cut then" not in led.show(second)
    depth = (then[1][1] + then[1][2]) / 2                      # inside the stretch whose id changed
    assert led.zone_of(depth, first) == then[1][0]             # by the zones the result was opened under
    assert led.zone_of(depth) == led.zone_of(depth, second) == now[0][0]


def test_resuming_keeps_the_zones_of_what_was_opened_before(rezoned, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(rezoned["folder"], copy, symlinks=True)
    r = Conversation.resume(copy, llm_factory=lambda cfg: Model())
    assert r.log.events("session_resume")[-1]["differences"] == []
    assert set(rezoned["opened1"]) == set(r.live.ledger.then)
    assert "The zones were cut anew" in r.earlier()
