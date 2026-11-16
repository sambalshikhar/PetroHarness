"""Field notes (petroharness.well.notes; docs/SESSIONS.md, "Field notes"): a team's standing settings and notes for a
field. What is wrong in a file is said per entry; its settings are in force from the start, under the ones the user
gives, each marked as the field notes'; its notes reach the model with every question as the user's statement; the
answer's header names them; the log keeps what the file held, so a resumed conversation does not read it again; a
later change is the user's. A scripted model on the public sample well (no server).

    PETROHARNESS_SAMPLE_LAS=<folder of tuhua-7.las> .venv/bin/python -m pytest tests/session/test_field_notes.py -q
"""
import json
import os
import shutil
from pathlib import Path

import pytest

from petroharness import ask as A
from petroharness.session import Conversation
from petroharness.ui import adapter as AD
from petroharness.well import notes as N
from petroharness.well import settings as T

SAMPLES = Path(os.environ.get("PETROHARNESS_SAMPLE_LAS", "sample_las"))
LAS = SAMPLES / "tuhua-7.las"
WINDOW = dict(top=600.0, base=700.0, depth_unit="m", formation="test window")
NOTES = """name: Test field study
settings:
  m: 1.8
  sw_cutoff: 0.6
notes:
  - Call the upper sand the A sand
  - Report saturation with its model named.
"""


class Model:
    def __init__(self):
        self.sent = []

    def replays_reasoning(self):
        return True

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
        self.sent.append({"stage": stage, "messages": json.loads(json.dumps(messages))})
        usage.log.append({"stage": stage, "prompt_tokens": 10, "completion_tokens": 5, "seconds": 0.0})
        if stage.startswith("read"):
            r = {"topics": ["saturation"], "named": ["SW"]}
        elif stage == "step_1":
            r = {"points": ["What is the mean SW?"], "intent": "characterize", "focus": "water saturation",
                 "edits": [], "next": [{"stats": {"curves": ["SW"]}}], "done": False}
        elif stage.startswith(("step_", "settle")):
            r = {"edits": [], "next": [], "done": True}
        else:
            r = "## Water saturation\nWater saturation is read from the results.\n"
        return r if isinstance(r, str) else json.dumps(r)


def _write(tmp_path, text, name="notes.yaml"):
    p = tmp_path / name
    p.write_text(text)
    return p


@pytest.mark.parametrize("text, says", [
    ("settings: [1, 2]\n", "not a table of setting"),
    ("settings:\n  m: -2\n", "cannot be used"),
    ("settings:\n  nope: 1\n", "not a setting this panel knows"),
    ("notes: 3\n", "not a list of sentences"),
    ("wells: [a]\n", "entries no reader knows"),
    ("settings: {m: 1.8\n", "not readable YAML"),
])
def test_what_is_wrong_in_a_file_is_said(tmp_path, text, says):
    with pytest.raises(ValueError, match=says):
        N.load(_write(tmp_path, text))


def test_a_file_reads_and_its_notes_become_one_statement(tmp_path):
    n = N.load(_write(tmp_path, NOTES))
    assert n["name"] == "Test field study" and n["settings"] == {"m": 1.8, "sw_cutoff": 0.6}
    assert n["notes"] == ["Call the upper sand the A sand", "Report saturation with its model named."]
    assert len(n["sha256"]) == 64
    assert N.statement(n) == ("(The user's field notes for this field, Test field study: Call the upper sand the A "
                              "sand. Report saturation with its model named.)")
    assert N.statement({"notes": []}) == "" and N.statement(None) == ""
    assert N.sources({"m": 1.8, "rw": 0.04}, n) == {"m": "field notes", "rw": "user"}
    assert N.sources({"m": 1.8}, n, changed={"m"}) == {"m": "user"}
    assert N.sources({"m": 1.9}, n) == {"m": "user"}




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
def started(env, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("notes")
    notes = _write(tmp, NOTES)
    model = Model()
    c = Conversation.start(LAS, tmp / "s", **WINDOW, llm_factory=lambda cfg: model, figures=False, direct=False,
                           field_notes=notes, interpretation={"sw_cutoff": 0.7})
    t1 = c.ask("What is the mean water saturation?")
    n1 = len(model.sent)
    t2 = c.ask("And in the A sand?")
    return {"c": c, "model": model, "t1": t1, "t2": t2, "n1": n1, "notes": notes, "folder": tmp / "s"}


@pytest.mark.data
def test_the_settings_are_in_force_from_the_start_under_the_users(started):
    c = started["c"]
    assert c.settings == {"m": 1.8, "sw_cutoff": 0.7}                      # the user's sw_cutoff over the notes'
    assert c.sources() == {"m": "field notes", "sw_cutoff": "user"}
    assert T.used(c.p.view.prep)["m"]["value"] == pytest.approx(1.8)
    start = c.log.events("session_start")[0]["inputs"]["field_notes"]
    assert start["name"] == "Test field study" and start["settings"] == {"m": 1.8, "sw_cutoff": 0.6}
    assert len(start["sha256"]) == 64 and start["notes"]


@pytest.mark.data
def test_the_notes_reach_the_model_with_every_question(started):
    model, n1 = started["model"], started["n1"]
    stmt = "(The user's field notes for this field, Test field study: Call the upper sand the A sand."
    for calls in (model.sent[:n1], model.sent[n1:]):
        step = [x for x in calls if x["stage"] == "step_1"][0]
        assert stmt in step["messages"][-1]["content"]


@pytest.mark.data
def test_the_answer_names_the_field_notes(started):
    head = (started["t1"].folder / "answer.md").read_text().split("---")[0]
    assert "**Field notes:** Test field study (m 1.8; sw_cutoff 0.6); 2 notes with the question" in head
    assert started["t1"].trace["ask"]["field_notes"]["name"] == "Test field study"


@pytest.mark.data
def test_a_resumed_conversation_keeps_what_the_file_held(started, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(started["folder"], copy, symlinks=True)
    started["notes"].write_text("name: changed\nsettings:\n  m: 2.2\n")    # the file changed since
    r = Conversation.resume(copy, llm_factory=lambda cfg: Model())
    assert r.log.events("session_resume")[-1]["differences"] == []
    assert r.settings == {"m": 1.8, "sw_cutoff": 0.7} and r.p.notes["name"] == "Test field study"
    started["notes"].write_text(NOTES)


@pytest.mark.data
def test_a_later_change_is_the_users(started, tmp_path):
    copy = tmp_path / "copy2"
    shutil.copytree(started["folder"], copy, symlinks=True)
    r = Conversation.resume(copy, llm_factory=lambda cfg: Model())
    r.adopt({"m": 2.0})
    assert r.sources() == {"m": "user", "sw_cutoff": "user"}


@pytest.mark.data
def test_one_question_with_field_notes(env, tmp_path):
    notes = _write(tmp_path, NOTES)
    res = A.ask(LAS, "What is the mean water saturation?", **WINDOW, llm_factory=lambda cfg: Model(),
                field_notes=notes, out=tmp_path / "out", direct=False)
    assert "Test field study" in res.files["answer"].read_text().split("---")[0]
    assert "field notes for this field" in res.trace["ask"]["question_sent"]


@pytest.mark.data
def test_the_page_checks_and_previews_field_notes(env, tmp_path):
    notes = _write(tmp_path, NOTES)
    info = AD.notes_info(str(notes))
    assert info["name"] == "Test field study" and info["settings"]["m"] == 1.8
    with pytest.raises(AD.InputError, match="no field notes file"):
        AD.notes_info(str(tmp_path / "none.yaml"))
    kw = AD.arguments({"las": str(LAS), "question": "q", "field_notes": str(notes)})
    assert kw["field_notes"] == str(notes.resolve())
    bad = _write(tmp_path, "settings:\n  m: -1\n", "bad.yaml")
    with pytest.raises(AD.InputError, match="cannot be used"):
        AD.arguments({"las": str(LAS), "question": "q", "field_notes": str(bad)})
    got = AD.preview({"las": str(LAS), "interval": {"mode": "depths", "top": 600, "base": 700, "unit": "m"},
                      "field_notes": str(notes)}, tmp_path / "cache")
    assert got["used"]["m"]["value"] == pytest.approx(1.8)
