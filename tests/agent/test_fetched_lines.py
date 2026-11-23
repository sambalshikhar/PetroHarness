"""What get and find fetch reaches the writer and the settle step (live round 3, Z4: the model fetched the 93 intervals
a list cut at its limit with get, and the answer said they were "not reproduced"). A result's text is what it shows;
the lines a get or find showed beyond it (a list's kept lines, a class line asked by zone) are kept per question
(Session.got) and read with their result (writer.result_text).

    .venv/bin/python -m pytest tests/agent/test_fetched_lines.py -q
"""
import re

import numpy as np
import pytest

from _wells import sample
from _support.model import ScriptedModel  # noqa: E402

pytestmark = pytest.mark.data


def test_get_and_find_hand_over_the_lines_they_showed_as_data():
    """The ledger records what a get or find showed (Ledger.take_fetched): the lines of each item shown, none for a
    miss, none for an item find left out; no reader parses the tool's text for them (a regex over '[E2] ...' heads did,
    C12)."""
    from _wells import CASES, formation_of
    from petroharness.agent.ledger import Ledger
    f = formation_of(CASES["brent"])
    led = Ledger(f)
    led.open("stats", {"curves": ["PHIE", "GR"]})
    led.open("compare", {"a": "PHIE", "b": "PHIT"})
    text = led.get("E1", "Z1")
    got = led.take_fetched()
    assert list(got) == ["E1"] and got["E1"] and all(ln in text for ln in got["E1"])
    assert led.take_fetched() == {}                                   # taken once
    led.get("E1", "NOSUCHNAME")
    assert led.take_fetched() == {}                                   # a miss shows no line
    text = led.find("PHIE")
    got = led.take_fetched()
    assert set(got) <= {"E1", "E2"} and all(ln in text for lines in got.values() for ln in lines)


def _intervals(las, curve: str, below: float) -> int:
    """The runs of consecutive samples where the curve is below the value, over the whole log (from the LAS; a negative
    reading is no reading: 30/6-5 holds GR -12.6 at 228 m, which Petrophys reads as missing, splitting a run)."""
    import lasio
    w = lasio.read(str(las))
    v = np.asarray(w[curve], dtype=float)
    on = np.isfinite(v) & (v >= 0) & (v < below)
    return int(on[0]) + int(np.sum(on[1:] & ~on[:-1]))


def _get_the_cut_line(messages):
    eid, find = re.search(r'get (E\d+) with find "([^"]+)"', messages[-1]["content"]).groups()
    return {"next": [{"get": eid, "find": find}], "done": False}


class Model(ScriptedModel):
    """A direct question: READ says the whole well; look step 1 lists GR < 60 cut at 3; step 2 gets the others with the
    find the cut line names; the writer states no number."""

    def __init__(self):
        super().__init__({
            "read*": {"topics": ["statistics_data_analysis"], "named": ["GR"], "depth": "direct",
                      "scope": ["the whole well"]},
            "step_1": {"next": [{"runs": {"condition": "GR < 60", "limit": 3}}], "done": False},
            "step_2": _get_the_cut_line,
            "step_*": {"done": True}, "settle*": {"done": True}},
            default="The intervals are listed in the results.")

@pytest.fixture(scope="module")
def asked(tmp_path_factory):
    from petroharness.session import Conversation
    mp = pytest.MonkeyPatch()
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS"):
        mp.delenv(key, raising=False)
    model = Model()
    c = Conversation.start(sample("30/6-5"), tmp_path_factory.mktemp("got") / "s",
                           tops=sample("formations_30_6-5.csv"), formation="BRENT GP.",
                           llm_factory=lambda cfg: model, figures=False, direct=True)
    t = c.ask("List every interval in the whole well where GR is below 60 API, with its depths.")
    mp.undo()
    return c, t, model


def test_the_writer_reads_the_intervals_get_fetched_beyond_the_cut_list(asked):
    c, t, model = asked
    assert t.ok, t.trace.get("error")
    assert t.trace["read"]["depth"] == "direct"
    s = c.live
    eid = re.search(r'get (E\d+) with find "', model.last("step_2")).group(1)
    item = s.ledger.by_id(eid)
    total = int(re.search(r"\((\d+) intervals", item.text).group(1))
    assert total == _intervals(sample("30/6-5"), "GR", 60.0)          # every run of the well's GR below 60, from the LAS
    got = s.got[eid]
    assert got and not set(got) & set(item.text.splitlines())         # lines the result's text does not show
    writer = model.last("writer")
    block = writer.split(f"[{eid}] ", 1)[1].split("\n\n[E", 1)[0]
    for ln in got:
        assert ln in block                                             # read with their result, under it
    cells = sum(len(re.findall(r"\d-\d", ln.split(":", 1)[1])) for ln in got)
    listed = len(re.findall(r"^    (?:at )?\d", block.split("other intervals:")[0], re.M))
    left = re.search(r"the other (\d+), each at most", item.text)
    assert listed == 3 and listed + cells + (int(left.group(1)) if left else 0) == total
    assert t.trace["fetched_lines"] == {eid: len(got)}
    lo, hi = c.live.f.inv.well_span                                    # the writer is told the question's stretch
    assert f"THE QUESTION'S STRETCH: {lo:g}-{hi:g} m (the stretches the question is about" in writer
    system = next(x for x in reversed(model.sent) if x["stage"] == "writer")["messages"][0]["content"]
    assert "The question is about the stretch THE QUESTION'S STRETCH names" in system


def test_a_get_of_lines_the_result_shows_adds_nothing(asked):
    """Lines a result's text shows are read there once; a get of them adds nothing to Session.got."""
    c, _, _ = asked
    s = c.live
    before = {k: list(v) for k, v in s.got.items()}
    eid = next(iter(s.got))
    shown = s.ledger.by_id(eid).text.splitlines()[1].strip()
    s.run(("get", eid, shown.split()[0]))
    assert s.got == before


def test_settle_reads_the_fetched_lines_too(asked):
    from petroharness.agent.writer import opened_results
    c, _, _ = asked
    s = c.live
    eid = next(iter(s.got))
    text = opened_results(s)
    assert all(ln in text for ln in s.got[eid])


def test_find_keeps_the_lines_it_shows_beyond_their_result():
    """find runs get over every result: the lines it shows beyond a result's text are kept for that result too."""
    from petroharness.agent.state import Session
    from petroharness.config import given_settings
    from _wells import CASES, task_cfg
    task, cfg, data = task_cfg(CASES["brent"], "s")
    with given_settings({"data": data, "eval": {}}):
        s = Session.build(task, cfg)
    _, item = s.run(("tool", "runs", {"condition": "GR < 60", "limit": 2}))
    hidden = [ln for ln in item.lines if ln not in item.text.splitlines()]
    term = re.search(r'with find "([^"]+)"', item.text).group(1)
    assert hidden and not s.got
    s.run(("find", term))
    assert s.got[item.id] and set(s.got[item.id]) <= set(hidden)


def test_without_a_scope_the_writer_is_told_no_stretch():
    """Reach focus (the benchmark) or no stretch named: the writer's prompt is as before."""
    from petroharness.agent.writer import question_stretch
    from types import SimpleNamespace
    assert question_stretch(SimpleNamespace(scope=[])) == "" and question_stretch(SimpleNamespace()) == ""
    inv = SimpleNamespace(depth_unit="m", top=2841.0, base=2958.0)
    s = SimpleNamespace(scope=["DUNLIN GP.", "2958-3100"], scope_by_user=True, f=SimpleNamespace(inv=inv))
    assert question_stretch(s) == ("THE QUESTION'S STRETCH: DUNLIN GP., 2958-3100 m (set by the user; every lookup "
                                   "computed on it); the interval 2841-2958 m is one part of the well")


class WholeModel(Model):
    """A direct question whose one lookup lists every GR < 60 run of the well (no limit): its text is cut at the size
    limit; no get follows."""

    def __init__(self):
        super().__init__()
        self.replies.update({"step_1": {"next": [{"runs": {"condition": "GR < 60"}}], "done": False},
                             "step_2": {"done": True}})

def test_a_direct_questions_writer_reads_a_list_cut_at_the_size_limit_whole(tmp_path, monkeypatch):
    """Live (Xg): the whole-well list was cut at the size limit, the look step said 'the answer's writer reads it
    whole', and the answer stopped at 2622 m. The direct writer reads every line of its results, in order."""
    from petroharness.session import Conversation
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS"):
        monkeypatch.delenv(key, raising=False)
    model = WholeModel()
    c = Conversation.start(sample("30/6-5"), tmp_path / "s", tops=sample("formations_30_6-5.csv"), formation="BRENT GP.",
                           llm_factory=lambda cfg: model, figures=False, direct=True)
    t = c.ask("List every interval in the whole well where GR is below 60 API, with its depths.")
    assert t.ok, t.trace.get("error")
    item = next(e for e in c.live.ledger.items if e.tool == "runs")
    assert "to keep within the size limit" in item.text                 # cut for the steps
    writer = model.last("writer")
    total = int(re.search(r"\((\d+) intervals", item.text).group(1))
    assert total == _intervals(sample("30/6-5"), "GR", 60.0)
    shown = set(item.text.splitlines())
    cut = [ln for ln in item.lines if ln not in shown]                 # held at the size limit, and kept for get
    assert cut and all(ln in writer for ln in item.lines)              # every line it holds, the cut ones too
    block = writer.split(f"[{item.id}] ", 1)[1].split("\n\n[E", 1)[0]
    assert "to keep within the size limit" not in block
    system = next(x for x in reversed(model.sent) if x["stage"] == "writer")["messages"][0]["content"]
    assert "besides a list the question asks for (every interval, every zone), which is given whole" in system
