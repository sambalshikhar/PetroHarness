"""The measured build's six behaviours. Each was a switch while it was measured (3.5.4: zone_order, see_first,
stop_check, writer_points; 3.5.6: writer_fresh, fresh_doubts); the 3.5.6 lock built them in and left no switch
(agent/options.py), so each test asserts the behaviour as the code has it:

- an order over fewer than five zones is said untestable, with its number and without direction words or legend;
- a done set while opened results are still withheld waits: they are shown first, then the model decides again;
- once every point is settled, the step asks for the brief's checks ("Before you finish"), and the brief's stop
  sentence says the same;
- the writer reads the question's points, the limits the investigation found (by point) and every result, not the
  claims, and gives each point its own part (rule 10); the answer is one writer call.

    .venv/bin/python -m pytest tests/agent/test_measured_build.py -q   (PETROHARNESS_DATA selects the dataset for the data tests)
"""
import json
import sys
from itertools import pairwise
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parent)]
from petroharness.agent import components as C, loop as L, writer as W  # noqa: E402
from petroharness.agent.loop import brief, investigate  # noqa: E402
from petroharness.llm import Usage  # noqa: E402
from petroharness.well import summary as S  # noqa: E402

TOO_FEW = "{k} zones: too few to tell an order from chance; at least 5 are needed"


# --- an order over the zones (zone_order) -----------------------------------------------------------------------------

@pytest.mark.parametrize("k", [3, 4])
def test_an_order_over_fewer_than_five_zones_is_said_untestable(k):
    assert S.ORDER_MIN_ZONES == 5
    for rc in (-1.0, 0.6, 0.0):                                # whatever the correlation: no direction words
        assert S.order_words(rc, k, S.direction_words) == TOO_FEW.format(k=k)


@pytest.mark.parametrize("k", [5, 9])
def test_from_five_zones_an_order_is_said_in_words(k):
    assert S.order_words(-0.9, k, S.direction_words) == "higher upward"
    assert S.order_words(0.6, k, S.direction_words) == "higher downward"


def _depth_order(k):
    """The with-depth line of k zones whose mean falls with depth (rank correlation -1)."""
    rows = [(f"Z{i}", {"mean": 0.30 - 0.02 * i}) for i in range(1, k + 1)]
    mids = {f"Z{i}": 100.0 + 10.0 * i for i in range(1, k + 1)}
    return S.depth_order(rows, mids, ["mean"], lambda x: f"{x:.2f}", lambda a, b: -1.0)


@pytest.mark.parametrize("k", [3, 4])
def test_the_depth_line_of_few_zones_keeps_the_number_and_gives_no_direction(k):
    assert _depth_order(k) == (f"with depth (rank correlation of each zone's value with its mid-depth over {k} zones): "
                               f"mean -1.00 ({TOO_FEW.format(k=k)})")


def test_the_depth_line_of_five_zones_gives_the_direction_and_its_legend():
    assert _depth_order(5) == ("with depth (rank correlation of each zone's value with its mid-depth over 5 zones; "
                               "positive: higher deeper, negative: higher upward): mean -1.00 (higher upward)")


# --- the stop (stop_check) --------------------------------------------------------------------------------------------

def test_the_brief_stops_on_settled_points_with_nothing_left_on_its_list():
    b = brief(None)
    assert 'Stop when every point is settled and nothing on the list under "Before you finish" is left.' in b
    assert "Stop when every point is settled." not in b
    assert "\nBefore you finish, look further when " in b      # the list the sentence points to is in the brief


def _settled_run(max_steps):
    """Step 1 opens NET_PAY runs with a hypothesis on point 1, step 2 settles the claim on them (done false, one more
    action), step 3 ends: the user prompts of steps 2 and 3."""
    from test_b5_loop import MEANS, Script, _session
    s = _session()
    llm = Script([{"points": ["Where is net pay?"], "intent": "locate", "done": False, "next": [{"runs": "NET_PAY"}],
                   "edits": [{"op": "add", "point": 1, "text": "Pay likely in the upper zones", "grade": "hypothesis"}]}])
    orig = llm.chat                                            # step 2 is written below from the ledger; then: done

    def chat(stage, messages, usage, max_tokens, retry=False):
        if stage == "step_2":
            llm.sent.append((stage, messages))
            usage.log.append({"stage": stage})
            runs_item = next(e for e in s.ledger.items if e.tool == "runs")
            return json.dumps({"edits": [{"op": "revise", "id": "C1", "text": "NET_PAY is set in the zones listed by the runs",
                                          "ev": [runs_item.id], "grade": "moderate", "means": MEANS}],
                               "next": [{"stats": {"curves": ["SW"]}}], "done": False})
        return orig(stage, messages, usage, max_tokens, retry)
    llm.chat = chat
    investigate(llm, s, Usage(), 4000, {}, max_steps=max_steps)
    return [next(m[-1]["content"] for st, m in llm.sent if st == f"step_{k}") for k in (2, 3)]


@pytest.mark.data
def test_once_every_point_is_settled_the_step_asks_for_the_brief_s_checks():
    check = C.text("C5", "step_settled_check")
    assert check.startswith(' Every point has a settled claim. Before you set done, go through the list under "Before '
                            'you finish" in your brief:') and check.endswith("Set done to true when none of these is left.")
    open_, settled = _settled_run(4)
    assert open_.endswith(C.text("C5", "step_next")) and "Every point has a settled claim" not in open_   # a hypothesis
    assert settled.endswith(C.text("C5", "step_next") + check)                    # settled, steps left: the checks


@pytest.mark.data
def test_the_last_step_asks_for_done_without_the_checks():
    _, last = _settled_run(3)                                  # the same run, step 3 the last
    assert last.endswith(C.fill("C5", "step_last", done="set done to true"))
    assert "This is the last step" in last and "Every point has a settled claim" not in last


# --- a done while results are withheld (see_first; a scripted model on a real formation) ------------------------------

ACTIONS = [{"runs": "NET_PAY"}, {"stats": {"curves": ["SW"]}}, {"stats": {"curves": ["PHIE"]}}]


def _withheld_run(monkeypatch, max_steps=6):
    """Step 1 opens three results under a NEW budget that fits the largest of them alone (so some are withheld and
    each comes within a step or two); every later reply sets done."""
    from test_b5_loop import Script, _session
    sizes = [len(_session().run(L.coerce_action(a))[0]) for a in ACTIONS]      # each result as NEW shows it
    monkeypatch.setattr(L, "NEW_CHARS", max(sizes) + 400)      # the largest fits (with the notes before it), not all three
    assert sum(sizes) > L.new_chars()
    s = _session()
    llm = Script([{"points": ["Where is net pay?"], "intent": "locate", "edits": [], "done": False, "next": ACTIONS}])
    trace = {}                                                 # the script's later replies: no edits, done true
    investigate(llm, s, Usage(), 4000, trace, max_steps=max_steps)
    return s, llm, trace


@pytest.mark.data
def test_a_done_waits_while_opened_results_are_withheld_and_they_are_shown_first(monkeypatch):
    s, llm, trace = _withheld_run(monkeypatch)
    steps = trace["steps"]
    held = steps[0]["withheld"]
    assert held and set(held) < {e.id for e in s.ledger.items}                   # opened at step 1, not shown yet
    assert steps[1]["done"] is True and steps[1]["held_done"] == held and steps[1]["actions"] == []
    assert "done_issues" not in steps[1]                       # the done is not weighed yet: it waits
    nxt = llm.sent[2][1][-1]["content"].split("\nNEW (from step 2):\n", 1)[1]    # step 3's NEW
    assert nxt.startswith(C.fill("C8", "done_waits", items=", ".join(held)))
    first = s.ledger.by_id(held[0])
    assert s.ledger.show(first) in nxt and held[0] in steps[1]["carried"]        # the first withheld result, whole


@pytest.mark.data
def test_a_done_is_weighed_only_when_nothing_is_withheld_or_at_the_last_step(monkeypatch):
    for max_steps in (6, 2):
        steps = _withheld_run(monkeypatch, max_steps)[2]["steps"]
        for before, st in pairwise(steps):
            last = st["step"] == max_steps
            if before["withheld"] and not last:                # results still to be shown: the done waits
                assert st["held_done"] == before["withheld"] and "done_issues" not in st
            else:                                              # nothing withheld, or no step left: weighed by the claims' rule
                assert "held_done" not in st and "done_issues" in st
        assert not steps[-2]["withheld"] or steps[-1]["step"] == max_steps      # no end over results not shown, but the last step's


# --- the writer (writer_points, writer_fresh, fresh_doubts) ------------------------------------------------------------

class _StageWriter:
    """A writer model that replies by stage; records each call's stage, messages and retry flag."""

    def __init__(self, replies):
        self.replies, self.sent = dict(replies), []

    def replays_reasoning(self):
        return True

    def chat(self, stage, messages, usage, max_tokens, retry=False):
        self.sent.append((stage, messages, retry))
        usage.log.append({"stage": stage})
        return self.replies.get(stage, "")


def _wcfg():
    from types import SimpleNamespace
    return SimpleNamespace(model=SimpleNamespace(max_tokens_writer=4000))


POINTS = ["Where is net pay?", "How thick is it?"]
POINTS_BLOCK = "THE QUESTION'S POINTS (the answer covers each):\nPoint 1: Where is net pay?\nPoint 2: How thick is it?"
LIMITS_HEAD = ("LIMITS THE INVESTIGATION FOUND (in some results or their methods, by point; weigh them as you read the "
               "results):\n")
RESULTS_HEAD = "RESULTS (everything the investigation computed, by id):\n"


def _wreal():
    """A session with two points, two opened results and four claims (three settled, one of them with a limit; one
    hypothesis)."""
    from test_b7_writer import _real_claims
    from test_b7_writer import _session as wsession
    s = wsession(list(POINTS), [])
    for c in _real_claims(s):
        s.claims.claims[c.id] = c
    s.claims._n = 4
    return s


@pytest.mark.data
def test_the_writer_reads_the_points_and_every_result_not_the_claims():
    from test_b7_writer import MEANS
    s = _wreal()
    system, user, _, _ = W.prompt(s, "default")
    assert user.startswith(f"QUESTION:\n{s.task.question}\n\n")
    assert user.index(POINTS_BLOCK) < user.index(RESULTS_HEAD)
    assert "YOUR CLAIMS" not in user and MEANS not in user and "| grade: " not in user and "| means: " not in user
    for c in s.claims.claims.values():                         # no claim's finding, settled or hypothesis
        assert c.text not in user, c.id
    results = user.split(RESULTS_HEAD, 1)[1].split("\n\nWHAT THE CURVES ARE (", 1)[0]
    assert results == "\n\n".join(f"[{e.id}] {e.text}" for e in s.ledger.items) and len(s.ledger.items) >= 2   # every result, whole
    head = system.split("\n\nHow to report")[0]
    assert "the points the answer must cover (from the investigation's plan)" in head
    assert "For each point, read what the results show and write that." in head and "claim" not in head


@pytest.mark.data
def test_the_writer_gives_each_point_its_own_part():
    s = _wreal()
    system, _, table, _ = W.prompt(s, "default")
    rule = C.text("C9", "points_rule")
    assert rule.startswith("10. Give each of your points its own part, in the order of the points: its finding, the "
                           "numbers and intervals it rests on, and what limits it.")
    assert table and system == C.text("C9", "write") + f"\n9. {W.TABLE_RULE}" + "\n" + rule          # rules 1-8, 9, 10
    s.intent = "value"                                         # a shape without a zone table: no rule 9, rule 10 stays
    system, _, table, _ = W.prompt(s, "default")
    assert not table and system == C.text("C9", "write") + "\n" + rule


@pytest.mark.data
def test_the_limits_the_investigation_found_follow_the_points_by_point_with_nothing_else_of_the_claims():
    doubts, prompt = W.doubts, W.prompt
    s = _wreal()
    cs = sorted(s.claims.claims.values(), key=lambda c: c.id)
    for c in cs:
        c.grade = "high"
    for c, w in zip(cs, ["Solver leaves 42% unsolved.", "None; a data absence.", "Solver leaves 42% unsolved.", ""]):
        c.weak = w
    cs[0].point, cs[1].point, cs[2].point = 2, 1, 3
    assert doubts(s) == [(2, "Solver leaves 42% unsolved.")]                     # once; 'None...' and empty left out
    _, user, _, _ = prompt(s, "default")
    block = "\n\n" + LIMITS_HEAD + "Point 2: Solver leaves 42% unsolved."
    assert POINTS_BLOCK + block + "\n\n" + RESULTS_HEAD in user                  # after the points, before the results
    for c in cs:
        assert c.text not in user and "| grade: " not in user                    # no finding, no grade
    cs[3].grade, cs[3].weak, cs[3].point = "hypothesis", "Unchecked against core.", 1
    assert doubts(s) == [(2, "Solver leaves 42% unsolved.")]                     # a hypothesis's limit is not one
    for c in cs:
        c.weak = ""
    assert doubts(s) == []
    _, bare, _, _ = prompt(s, "default")                                         # no limit found: no block
    assert "LIMITS THE INVESTIGATION FOUND" not in bare and bare == user.replace(block, "")


@pytest.mark.data
def test_the_answer_is_one_writer_call():
    s = _wreal()
    llm = _StageWriter({"writer": "## Answer\nNet pay is in the listed zones.\n\n## Limitations\nok"})
    trace = {}
    text, status = W.write(llm, s, _wcfg(), Usage(), trace)
    assert [st for st, _, _ in llm.sent] == ["writer"] and status == "ok"       # no deciding call, no parts, no frame
    system, user, _, _ = W.prompt(s, "profile")
    assert [m["content"] for m in llm.sent[0][1]] == [system, user]
    assert "## Answer" in text and trace["draft_chars"] > 0


# --- the JSON fix call --------------------------------------------------------------------------------------------------

def test_fix_call_reformats_with_the_retry_settings():
    """A step reply that is not JSON is reformatted by a fix call made with the card's retry settings (no or low
    reasoning): a reasoning model otherwise spends the fix budget thinking and the reply's edits are lost."""
    calls = []

    class Fake:
        def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
            calls.append((stage, retry))
            return '{"edits": [], "next": [], "done": true}'
    broken = ('{"focus": "x", "edits": [{"op": "add", "point": 1, "text": "t", "grade": "low"}, '
              '{"op": "add", "point": 2, "text": "cut off')       # the second edit is lost: salvage is incomplete
    out = L.parse(Fake(), 3, broken, Usage(), 16384, {})
    assert calls == [("step_3_fix", True)] and out == {"edits": [], "next": [], "done": True}
