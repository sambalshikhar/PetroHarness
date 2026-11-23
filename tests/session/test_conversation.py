"""A conversation on one interval (petroharness.session): the first question is the question graph's own run; a later
question runs on the same session with the earlier ones in view, and the ledger's ids go on; the log rebuilds it.
A scripted model on a real formation (no server).

    .venv/bin/python -m pytest tests/session -q   (PETROHARNESS_DATA selects the dataset)
"""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tests" / "agent")]
from petroharness.agent import components as C  # noqa: E402
from petroharness.session import Conversation  # noqa: E402
from petroharness.session import earlier as E  # noqa: E402
from _support.model import ScriptedModel  # noqa: E402

Q1 = "Where is porosity highest in the formation?"
Q2 = "And how does the clay volume vary?"
Q3 = "Which zone would you look at first?"
CLAIM1 = "Porosity is uniform: no zone stands out"
CLAIM2 = "Clay volume is low in every zone"


class Model(ScriptedModel):
    """READ, the step replies in order (then done), settle, and a writer whose numbers all come from results."""

    def __init__(self, steps):
        super().__init__({"read*": {"topics": ["porosity"], "named": ["porosity"]}, "step_*": list(steps),
                          "settle*": {"edits": [], "done": True}}, default="The zones are alike: no zone stands out.\n")

    @property
    def steps(self) -> list:
        """The step replies still to come (a later question sets its own)."""
        return self.replies["step_*"]

    @steps.setter
    def steps(self, items):
        self.replies["step_*"] = list(items)


def first_steps():
    return [{"points": [Q1], "intent": "locate", "focus": "porosity",
             "edits": [{"op": "add", "point": 1, "text": CLAIM1, "grade": "hypothesis"}],
             "next": [{"stats": {"curves": ["PHIE"]}}], "done": False},
            {"edits": [{"op": "revise", "id": "C1", "text": CLAIM1, "ev": ["E2"], "grade": "moderate",
                        "means": "the zones share one porosity level"}], "next": [], "done": True}]


def later_steps(cite=("E2", "E3")):
    return [{"points": [Q2], "intent": "characterize", "focus": "clay",
             "edits": [{"op": "add", "point": 1, "text": CLAIM2, "grade": "hypothesis"}],
             "next": [{"stats": {"curves": ["VCL"]}}], "done": False},
            {"edits": [{"op": "revise", "id": "C1", "text": CLAIM2, "ev": list(cite), "grade": "moderate",
                        "means": "the zones are clean"}], "next": [], "done": True}]


@pytest.fixture
def formation(monkeypatch):
    """(task, a build that gives a fresh session on one real formation with PHIE, VCL and two zones)."""
    from _support.formations import F
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.state import Session
    from petroharness.agent.map import render
    got = next(((t, f) for t, f in F() if {"PHIE", "VCL"} <= set(f.inv.curves) and len(f.view.zones) >= 2), None)
    if got is None:
        pytest.skip("no formation with PHIE, VCL and two zones")
    t, f = got
    monkeypatch.setattr(Session, "build", classmethod(lambda cls, task, cfg: Session(task, f, render(f.inv), Ledger(f))))
    return t.model_copy(update={"question": Q1})


def messages(llm):
    return [(c["stage"], c["messages"]) for c in llm.sent]


@pytest.mark.data
def test_the_first_question_is_the_question_graphs_own_run(formation, tmp_path):
    from petroharness.agent import graph
    alone = Model(first_steps())
    out = graph.answer(formation, "k2-horizon-7b", 1, 4, "open", "profile", llm_factory=lambda cfg: alone)
    assert not out["trace"].get("error"), out["trace"].get("traceback")
    llm = Model(first_steps())
    c = Conversation.on_tasks(tmp_path / "s", "k2-horizon-7b", llm_factory=lambda cfg: llm, max_steps=4)
    turn = c.ask_task(formation)
    assert messages(llm) == messages(alone)                    # the same requests, call by call
    assert turn.answer == out["answer"] and turn.status == out["status"]
    assert "session" not in turn.trace                         # the first question's trace is the graph's
    assert c.overview() is None and not (tmp_path / "s" / "overview.png").exists()   # prepared tasks: no display drawn
    assert not any("EARLIER IN THIS SESSION" in m["content"] for _, ms in messages(llm) for m in ms)


def two_questions(formation, tmp_path, cite=("E2", "E3")):
    """Two questions: the first opens the first look (E1) and PHIE (E2), the second VCL (E3; its first look is E1
    again, the same call)."""
    llm = Model(first_steps() + later_steps(cite))
    c = Conversation.on_tasks(tmp_path / "s", "k2-horizon-7b", llm_factory=lambda cfg: llm, max_steps=4)
    c.ask_task(formation)
    n1 = len(llm.sent)
    second = c.ask_task(formation.model_copy(update={"task_id": "second", "question": Q2}))
    assert not second.trace.get("error"), second.trace.get("traceback")
    return c, llm, n1, second


@pytest.mark.data
def test_a_later_question_sees_the_earlier_one_and_the_ids_go_on(formation, tmp_path):
    c, llm, n1, second = two_questions(formation, tmp_path)
    later = llm.sent[n1:]
    assert [e.id for e in c.live.ledger.items] == ["E1", "E2", "E3"] and c.turns[1]["opened"] == ["E3"]
    rests = second.trace["basis"]                              # the steps and parameters the answer rests on, by code
    assert second.basis == rests and c.turns[1]["basis"] == [r["step"] for r in rests]
    assert {c.live.f.inv.curves[n].step for n in ("PHIE", "VCL")} <= {r["step"] for r in rests if r["why"] == "named"}
    assert "## Methods and parameters this answer rests on" in (second.folder / "answer.md").read_text()
    assert second.trace["session"] == {"turn": 2, "ledger_start": 2, "earlier_chars": c.turns[1]["earlier_chars"],
                                       "reply": "full"}
    assert c.turns[1]["earlier_chars"] == len(E.block(c.turns[:1])) > 0
    head = C.text("C3", "earlier_head")
    block = E.block(c.turns[:1])
    assert block.startswith(head) and f"Question 1: {Q1}" in block and f"- {CLAIM1} (moderate; E2)" in block
    for stage in ("read", "step_1", "step_2", "settle", "writer"):
        user = next(x for x in later if x["stage"] == stage)["messages"][-1]["content"]
        assert block in user, stage                            # every call of the later question shows the earlier one
    step1 = next(x for x in later if x["stage"] == "step_1")["messages"][-1]["content"]
    assert step1.endswith(C.text("C5", "step1_later"))          # READ read the route, so step 1 is not asked for
    assert C.text("C5", "step1_reply") not in step1              # the answer's length (that is --investigate's way)
    step2 = next(x for x in later if x["stage"] == "step_2")["messages"][-1]["content"]
    assert C.text("C5", "step1_later") not in step2
    opened = step2[step2.index("OPENED (fetch exact lines"):]
    assert "E3 stats VCL" in opened and "[E3] " in opened       # its own result is listed and shown
    assert "E2 stats PHIE" not in opened and "[E2] " not in opened   # an earlier result no claim of it cites yet is not
    settle = next(x for x in later if x["stage"] == "settle")["messages"][-1]["content"]
    results = settle[settle.index("ALL RESULTS:"):]
    assert "[E2] " in results and "[E3] " in results and "[E1] " not in results   # cited at step 2: settle reads it
    writer = next(x for x in later if x["stage"] == "writer")["messages"]
    assert writer[0]["content"].endswith(C.text("C9", "later_rule").strip())
    for e in c.live.ledger.items[1:]:                          # its own result, and the earlier one its claim cites
        assert f"[{e.id}] {e.text}" in writer[-1]["content"]


@pytest.mark.data
def test_a_later_question_is_answered_briefly_when_the_model_says_so_and_never_the_first(formation, tmp_path):
    """The answer-length route of a run that does not read the route in READ (--investigate): a later question's
    step 1 is asked how long the answer should be."""
    first, later = first_steps(), later_steps()
    first[0]["reply"] = later[0]["reply"] = "brief"            # the model asks for a short reply in both step 1s
    llm = Model(first + later)
    c = Conversation.on_tasks(tmp_path / "s", "k2-horizon-7b", llm_factory=lambda cfg: llm, max_steps=4, direct=False)
    one = c.ask_task(formation)
    n1 = len(llm.sent)
    two = c.ask_task(formation.model_copy(update={"task_id": "second", "question": Q2}))
    step1 = next(x for x in llm.sent[n1:] if x["stage"] == "step_1")["messages"][-1]["content"]
    assert step1.endswith(C.text("C5", "step1_later") + C.text("C5", "step1_reply"))
    w1 = next(x for x in llm.sent[:n1] if x["stage"] == "writer")["messages"]
    w2 = next(x for x in llm.sent[n1:] if x["stage"] == "writer")["messages"]
    assert w1[0]["content"].startswith(C.prompt("C9", "write")) and "session" not in one.trace   # the first: the full form
    assert w2[0]["content"] == C.prompt("C9", "reply_brief") + "\n" + C.text("C9", "brief_later")
    assert two.trace["session"]["reply"] == "brief"
    assert "THE ZONE TABLE" not in w2[-1]["content"] and "THE QUESTION'S POINTS" in w2[-1]["content"]
    assert E.block(c.turns[:1]) in w2[-1]["content"] and f"[E3] " in w2[-1]["content"]   # the earlier question, its result
    # with no word on the length (or any other word), a later question keeps the full form with the later rule
    c2, llm2, m1, second = two_questions(formation, tmp_path / "t")
    w = next(x for x in llm2.sent[m1:] if x["stage"] == "writer")["messages"]
    assert w[0]["content"].startswith(C.prompt("C9", "write")) and second.trace["session"]["reply"] == "full"
    assert C.text("C5", "step1_reply").rstrip().endswith('"full" where it needs an analysis in parts.')


@pytest.mark.data
def test_a_later_writer_reads_only_its_own_results_and_the_ones_its_claims_cite(formation, tmp_path):
    c, llm, n1, _ = two_questions(formation, tmp_path, cite=("E3",))
    user = next(x for x in llm.sent[n1:] if x["stage"] == "writer")["messages"][-1]["content"]
    results = user[user.index("RESULTS (everything"):user.index("WHAT THE CURVES ARE")]
    assert "[E3] " in results and "[E2] " not in results and "[E1] " not in results


@pytest.mark.data
def test_the_log_holds_the_conversation_and_resuming_gives_the_same_next_question(formation, tmp_path):
    c, llm, _, _ = two_questions(formation, tmp_path)
    kinds = [e["type"] for e in c.log.events()]
    assert kinds == ["session_start", "setup", "question", "result", "result", "record", "turn_end", "question",
                     "result", "turn_end"]                     # the setup and the well's record once: neither changed
    for e in c.log.events("result"):                           # each result's text is kept under its hash
        item = c.live.ledger.by_id(e["id"])
        assert c.log.read(e["sha256"]) == item.text and e["tool"] == item.tool and e["args"] == item.args
    assert c.log.read(c.turns[0]["answer_sha256"]).startswith("The zones are alike")
    for n in ("01", "02"):
        assert (c.folder / "turns" / n / "answer.md").exists() and (c.folder / "turns" / n / "trace.json").exists()
    shutil.copytree(c.folder, tmp_path / "copy")
    third = formation.model_copy(update={"task_id": "third", "question": Q3})
    llm.steps, mark = [{"points": [Q3], "intent": "locate", "edits": [], "next": [], "done": True}], len(llm.sent)
    c.ask_task(third)
    again = Model([{"points": [Q3], "intent": "locate", "edits": [], "next": [], "done": True}])
    r = Conversation.resume(tmp_path / "copy", llm_factory=lambda cfg: again)
    assert r.log.events("session_resume")[-1] == {**r.log.events("session_resume")[-1], "questions": 2, "results": 3,
                                                  "differences": []}
    assert [e.id for e in r.live.ledger.items] == ["E1", "E2", "E3"] and r.live.turn == 2
    r.ask_task(third)
    assert messages(again) == [(x["stage"], x["messages"]) for x in llm.sent[mark:]]   # the same third question


def test_the_earlier_block_keeps_the_newest_whole_and_counts_the_oldest():
    turns = [{"turn": k, "question": f"Question text {k}?", "status": "ok", "opening": "It is so. " * 20,
              "claims": [{"text": "a finding " * 12, "grade": "high", "ev": ["E1", "E2"]}] * 3} for k in range(1, 30)]
    text = E.block(turns, budget=3000)
    assert len(text) <= 3000 and text.startswith(C.text("C3", "earlier_head"))
    assert "Question 29: Question text 29?" in text and "(high; E1, E2)" in text
    assert "earlier questions not shown here" in text and "Question 1: " not in text
    assert text.index("Question 28:") < text.index("Question 29:")                   # oldest first
    assert E.block([]) == ""
    failed = E.entry({"turn": 3, "question": "Why?", "status": "error: Timeout"})
    assert failed == "Question 3: Why?\n  (not answered: the run failed)"


def test_the_opening_is_the_first_prose_paragraph():
    answer = "# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n**Answer**\n\nThe upper sand holds the pay, 12 ft of it. " \
             "The lower sand is wet.\n\n## Evidence\nMore."
    assert E.opening(answer) == "The upper sand holds the pay, 12 ft of it. The lower sand is wet."
    long = "A sentence about the zone. " * 60
    assert len(E.opening(long)) <= E.OPENING_CHARS + 4 and E.opening(long).endswith(". ...")
    assert E.opening("") == ""
    bold = "**Bottom line:** The upper sand holds the pay, and **12 ft** of it is net.\n\nMore."
    assert E.opening(bold) == "Bottom line: The upper sand holds the pay, and 12 ft of it is net."


def test_a_result_that_read_a_curve_computed_again_is_marked_and_not_served_from_the_cache():
    from types import SimpleNamespace as NS
    from petroharness.agent.ledger import Item, Ledger
    led = Ledger(NS(view=NS(calculated={})))
    old = Item("E1", "stats", {"curves": ["SW_ALT"]}, "stats|SW_ALT", [], "SW_ALT [v/v]: mean 0.41")
    other = Item("E2", "stats", {"curves": ["PHIE"]}, "stats|PHIE", [], "PHIE [v/v]: mean 0.21")
    led.items, led._keys, led.turn_start = [old, other], {old.key: old, other.key: other}, 2
    led._supersede(["SW_ALT"], "E3")
    assert led.superseded == {"E1": ("SW_ALT", "E3")} and old.key not in led._keys and other.key in led._keys
    assert led.show(old, False).startswith("[E1] (opened before SW_ALT was computed again in [E3]: these are the earlier values;")
    assert led.show(other, False).startswith("[E2] (opened before: ")


def test_a_curve_computed_again_in_the_same_question_is_not_served_stale(monkeypatch):
    """calculate m=2.0, compare SW_ALT SW, calculate m=2.2 under the same name, compare SW_ALT SW again, all in one
    question: the second compare was served from the first, with the m=2.0 numbers. It is computed anew, and the
    first compare says it holds the earlier values when read again (as from a conversation's second question on)."""
    from types import SimpleNamespace as NS
    from petroharness.agent import ledger as Lg
    calculated, computed = {}, []

    def calculate(f, m=None):
        pass

    def compare(f, a=None, b=None):
        pass

    def call(f, name, args):
        computed.append((name, dict(args)))
        if name == "calculate":
            calculated["SW_ALT"] = [args["m"]]                    # a new array under the same name
        text = f"SW_ALT mean {calculated['SW_ALT'][0]}" if name == "compare" else f"SW_ALT computed, m {args['m']}"
        return NS(rows=[], text=text, numbers=[])
    monkeypatch.setattr(Lg, "TOOLS", {"calculate": calculate, "compare": compare})
    monkeypatch.setattr(Lg, "fit", lambda name, args: args)
    monkeypatch.setattr(Lg, "arguments", lambda raw, tool=None: dict(raw))
    monkeypatch.setattr(Lg, "door_args", lambda f, name, args: args)
    monkeypatch.setattr(Lg, "call", call)
    led = Lg.Ledger(NS(view=NS(calculated=calculated)))
    led.open("calculate", {"m": 2.0})
    first, _ = led.open("compare", {"a": "SW_ALT", "b": "SW"})
    led.open("calculate", {"m": 2.2})
    second, new = led.open("compare", {"a": "SW_ALT", "b": "SW"})
    assert new and second is not first and second.text == "SW_ALT mean 2.2"
    assert [n for n, _ in computed] == ["calculate", "compare", "calculate", "compare"]
    assert led.superseded["E2"] == ("SW_ALT", "E3") and "E3" not in led.superseded
    assert led.show(first, False).startswith("[E2] (opened before SW_ALT was computed again in [E3]: these are the "
                                             "earlier values;")


@pytest.mark.data
def test_ask_and_a_conversations_first_question_send_the_model_the_same_prompts(tmp_path, monkeypatch):
    """ask() and a conversation prepare the interval from the same inputs (interval.Inputs) and answer the first
    question the same way: every call's messages are the same."""
    from test_adopt import LAS, Q1, WINDOW, Model as Saturation
    from petroharness import ask as A
    if not LAS.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS"):
        monkeypatch.delenv(key, raising=False)
    one, two = Saturation(), Saturation()
    A.ask(LAS, Q1, **WINDOW, llm_factory=lambda cfg: one, direct=False)
    Conversation.start(LAS, tmp_path / "s", **WINDOW, llm_factory=lambda cfg: two, figures=False,
                       direct=False).ask(Q1)
    assert one.stages() == two.stages()
    for a, b in zip(one.sent, two.sent):
        assert a["messages"] == b["messages"], a["stage"]
