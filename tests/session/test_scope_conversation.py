"""The scope adapts during a conversation (reach "well").

- Each question's READ says the stretches it is about; they are that question's default selection, and the next
  question reads its own (a question that names none is about the interval).
- The user's /scope is the default from the next question on, until the user changes it; a question that names other
  stretches is computed on those, for that question only; one that cannot be used leaves the user's, the reason said.
- /frame lithology: every lookup reports by the lithology zones; /frame zones takes it back.
- /zones FILE: the user's zones from the next question (the well's view made again, the ledger goes on); /zones none
  takes them away; a file that cannot be used changes nothing.
- Every change is logged with the question it takes effect at; a resumed conversation replays them in place.

A scripted model on Petrophys's sample well 30/6-5, Brent Group with its tops file (no server).

    .venv/bin/python -m pytest tests/session/test_scope_conversation.py -q
"""
import re

import pytest

from _wells import sample
from petroharness.session import Conversation
from petroharness.session import chat as CH
from _support.model import DONE, ScriptedModel, newest_result  # noqa: E402

pytestmark = pytest.mark.data
NESS_ETIVE = "zone,top,bottom\nNess,2841,2865\nEtive,2865,2958\n"


class Model(ScriptedModel):
    """READ: the next scope of its queue (None: a reply without scope); step 1 opens PHIE's statistics and adds a
    claim; step 2 settles it; the writer states no number."""

    def __init__(self):
        super().__init__({
            "step_1": {"points": ["What is the porosity?"], "intent": "characterize", "focus": "porosity",
                       "edits": [{"op": "add", "point": 1, "text": "Porosity is read from the results",
                                  "grade": "hypothesis"}],
                       "next": [{"stats": {"curves": ["PHIE"]}}], "done": False},
            "step_2": lambda m: {"edits": [{"op": "revise", "id": "C1", "ev": [newest_result(m)], "grade": "moderate",
                                            "means": "the porosity as computed"}], "next": [], "done": True},
            "step_*": DONE, "settle*": DONE},
            default="## Porosity\nPorosity is read from the results.\n")
        self.scopes = []

    def reply(self, stage, messages):
        if stage.startswith("read"):
            r = {"topics": ["porosity"], "named": ["PHIE"]}
            scope = self.scopes.pop(0) if self.scopes else []
            if scope is not None:
                r["scope"] = scope
            return r
        return super().reply(stage, messages)

@pytest.fixture(scope="module")
def env():
    mp = pytest.MonkeyPatch()
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS"):
        mp.delenv(key, raising=False)
    yield
    mp.undo()


def _start(folder, model, **kw):
    return Conversation.start(sample("30/6-5"), folder, tops=sample("formations_30_6-5.csv"), formation="BRENT GP.",
                              llm_factory=lambda cfg: model, figures=False, direct=False, **kw)


class Shown:
    """The result step 1's call showed the model (step 2's NEW: a call made before shows its item again)."""

    def __init__(self, model):
        new = model.last("step_2").split("NEW (from step 1):\n", 1)[1].split("\n\n", 1)[0]
        self.text = re.sub(r"^\[E\d+\] (\(opened before: [^)]*\)\) )?", "", new)


def _ask(c, model, question, scope):
    model.scopes.append(scope)
    t = c.ask(question)
    assert t.ok, t.trace.get("error")
    return t, Shown(model)


@pytest.fixture(scope="module")
def talk(env, tmp_path_factory):
    """One conversation: READ scopes, the user's /scope, a question overriding it, /scope back to the interval."""
    model = Model()
    c = _start(tmp_path_factory.mktemp("scope") / "s", model)
    got = {}
    got["q1"] = _ask(c, model, "What is the porosity of the Dunlin?", ["Dunlin GP."])
    got["q2"] = _ask(c, model, "And of the interval?", [])
    got["set"] = CH.command(c, "/scope 2900-3000 m")
    got["q3"] = _ask(c, model, "What is the porosity?", [])
    got["q3_step1"] = model.last("step_1")
    got["q4"] = _ask(c, model, "What about the Dunlin?", ["Dunlin GP."])
    got["q5"] = _ask(c, model, "And there?", [])
    got["q6"] = _ask(c, model, "And in Nowhere Fm.?", ["Nowhere Fm."])
    got["q6_step1"] = model.last("step_1")
    got["back"] = CH.command(c, "/scope")
    got["q7"] = _ask(c, model, "And the porosity now?", [])
    return c, model, got


def test_each_questions_read_scope_is_its_own(talk):
    _, _, got = talk
    assert got["q1"][1].text.startswith("Selection: DUNLIN GP. 2958-3223 m")
    assert got["q1"][0].trace["scope"]["used"] == ["Dunlin GP."]
    assert "Selection:" not in got["q2"][1].text            # the next question names none: the interval


def test_the_users_scope_holds_until_changed_and_a_question_may_name_another(talk):
    _, _, got = talk
    assert got["set"] == "from question 3: scope 2900-3000 m"
    assert got["q3"][1].text.startswith("Selection: 2900-3000 m")
    assert "SCOPE: 2900-3000 m (set by the user)" in got["q3_step1"]
    assert "Scope set before question 3 (by the user): 2900-3000 m, every lookup's default stretch" in got["q3_step1"]
    assert got["q3"][0].trace["scope"]["by"] == "user"
    assert got["q4"][1].text.startswith("Selection: DUNLIN GP. 2958-3223 m")      # named by the question
    assert got["q5"][1].text.startswith("Selection: 2900-3000 m")                  # the user's again


def test_a_question_scope_that_cannot_be_used_leaves_the_users_with_the_reason(talk):
    _, _, got = talk
    assert got["q6"][1].text.startswith("Selection: 2900-3000 m")
    assert "The scope read from the question (Nowhere Fm.) is not used: " in got["q6_step1"]
    assert "SCOPE: 2900-3000 m (set by the user)" in got["q6_step1"]


def test_a_users_scope_that_cannot_be_used_is_refused_when_given(talk):
    c, _, _ = talk
    said = CH.command(c, "/scope Nowhere Fm.")
    assert said.startswith("not changed: WHAT: scope Nowhere Fm.: ") and "FIX: name a unit" in said, said


def test_scope_back_to_the_interval(talk):
    _, _, got = talk
    assert got["back"] == "from question 7: scope the interval"
    assert "Selection:" not in got["q7"][1].text


def test_every_scope_change_is_logged_where_it_takes_effect(talk):
    c, _, _ = talk
    assert [(e["turn"], e["scope"], e["by"]) for e in c.log.events("scope")] == [
        (3, ["2900-3000 m"], "user"), (7, [], "user")]


def test_the_answer_header_names_the_scope(talk):
    c, _, _ = talk
    md = (c.folder / "turns").glob("*/answer.md")
    heads = {p.parent.name: p.read_text().split("---")[0] for p in md}
    assert heads, list((c.folder / "turns").iterdir())
    said = [h for h in heads.values() if "- **Scope:** 2900-3000 m" in h]
    assert len(said) >= 2, heads


def test_a_resumed_conversation_keeps_the_ledger_and_the_users_scope(talk, tmp_path):
    c, model, _ = talk
    CH.command(c, "/scope Dunlin GP.")
    r = Conversation.resume(c.folder, llm_factory=lambda cfg: model)
    assert r.log.events("session_resume")[-1]["differences"] == []
    assert r._scope == ["Dunlin GP."]


def test_frame_lithology_and_zones_files_mid_conversation(env, tmp_path):
    """/zones Ness+Etive: the next question is framed by them (Z ids, the user's names) and its prompts name the change;
    /frame lithology: reported by the lithology zones (L ids); /zones none: the lithology zones again; a bad file
    changes nothing. Resumed, the zones change is replayed and the ledger is as it was."""
    zones = tmp_path / "zones.csv"
    zones.write_text(NESS_ETIVE)
    bad = tmp_path / "overlap.csv"
    bad.write_text("zone,top,bottom\nA,2841,2870\nB,2860,2958\n")
    model = Model()
    c = _start(tmp_path / "s", model)
    _, s1 = _ask(c, model, "What is the porosity?", [])
    assert re.search(r"^  Z1 [A-Z]", s1.text, re.M)                  # the lithology zones frame it
    assert CH.command(c, f"/zones {zones}") == "from question 2: your zones from zones.csv"
    t2, s2 = _ask(c, model, "And now?", [])
    assert re.search(r"^  Z1 Ness ", s2.text, re.M) and re.search(r"^  Z2 Etive ", s2.text, re.M)
    head = (t2.folder / "answer.md").read_text().split("---")[0]
    assert "- **Zones:** yours, from zones.csv (2; the lithology zones are kept as L ids)" in head, head
    assert ("Zones changed before question 2 (by the user): your zones from zones.csv frame the interval (Z ids); the "
            "lithology zones keep L ids. Results E1 to E2 were read under the earlier zones" in model.last("step_1"))
    assert CH.command(c, "/frame lithology") == "from question 3: by the lithology zones"
    _, s3 = _ask(c, model, "By lithology?", [])
    assert re.search(r"^  L1 ", s3.text, re.M) and not re.search(r"^  Z\d ", s3.text, re.M)
    assert "FRAME: every lookup reports by the lithology zones" in model.last("step_1")
    assert "Frame set before question 3 (by the user): every lookup reports by the lithology zones" in model.last("step_1")
    assert CH.command(c, "/frame rock").startswith("not changed: WHAT: frame 'rock'")
    assert CH.command(c, "/frame zones") == "from question 4: by the zones in force"
    said = CH.command(c, f"/zones {bad}")
    assert said.startswith("not changed: ") and "overlap" in said, said
    assert c.inputs["zones"] == str(zones.resolve())
    _, s4 = _ask(c, model, "And with my zones?", [])
    assert re.search(r"^  Z1 Ness ", s4.text, re.M)
    assert CH.command(c, "/zones none") == "from question 5: the lithology zones (your zones taken away)"
    _, s5 = _ask(c, model, "And without them?", [])
    assert not re.search(r"^  Z\d (Ness|Etive) ", s5.text, re.M) and re.search(r"^  Z1 [A-Z]", s5.text, re.M)
    assert [(e["turn"], bool(e["zones"])) for e in c.log.events("zones")] == [(2, True), (5, False)]
    assert [(e["turn"], e["frame"]) for e in c.log.events("frame")] == [(3, "lithology"), (4, None)]
    r = Conversation.resume(c.folder, llm_factory=lambda cfg: model)
    assert r.log.events("session_resume")[-1]["differences"] == []
    assert "zones" not in r.inputs


def test_under_reach_focus_a_conversation_has_no_scope(env, tmp_path):
    """A data settings file with reach "focus" (a benchmark's): READ asks no scope, none is applied, and /scope is
    said to have no effect there."""
    settings = tmp_path / "data.yaml"
    settings.write_text("data:\n  reach: focus\n")
    model = Model()
    c = _start(tmp_path / "s", model, settings=str(settings))
    t, s1 = _ask(c, model, "What is the porosity of the Dunlin?", ["Dunlin GP."])
    assert "- scope:" not in model.last("read") and "scope" not in t.trace
    assert "Selection:" not in s1.text
    assert CH.command(c, "/scope Dunlin GP.").startswith("not changed: WHAT: this conversation answers for its "
                                                         "interval only")


def test_a_cleared_scope_names_the_interval_in_force(talk):
    """Question suite F6 (B10 turn 3): after /scope cleared it, the EARLIER line said 'the interval again' and the READ
    took it for the previous question's stretch ('that would be Ness Fm. ... per question 2')."""
    c, model, got = talk
    inv = c.live.f.inv
    said = f"none: every lookup computes on the interval the session opened on, {inv.formation} {inv.top:g}-{inv.base:g} m"
    shown = [x["stage"] for x in model.sent if "Scope set before question 7" in x["messages"][-1]["content"]]
    assert shown, [x["stage"] for x in model.sent][-8:]                # question 7's prompts carry the change
    last = next(x for x in reversed(model.sent) if "Scope set before question 7" in x["messages"][-1]["content"])
    text = last["messages"][-1]["content"]
    assert said in text and "the interval again" not in text, re.findall(r"Scope set before question 7[^\n]*", text)
