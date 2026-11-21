"""The web UI's live progress (src/petroharness/ui/progress.py): the client wrapper passes every call through
unchanged and reports it; the results a prompt shows are read as the model read them; replies are read with the
harness's own parsers.

    python -m pytest tests/ui -q
"""
import json

import pytest

from petroharness.agent import components as C
from petroharness.llm import Usage
from petroharness.ui import progress as P


class Echo:
    """An inner client that records its calls and replies with a fixed text."""

    def __init__(self, reply="{}", fail=None):
        self.reply, self.fail, self.calls = reply, fail, []
        self.cfg = "the inner config"

    def replays_reasoning(self):
        return "inner"

    def chat(self, stage, messages, usage, max_tokens, *args, **kwargs):
        self.calls.append((stage, messages, usage, max_tokens, args, kwargs))
        if self.fail:
            raise self.fail
        usage.log.append({"stage": stage, "prompt_tokens": 100, "completion_tokens": 7, "seconds": 0.1})
        return self.reply


@pytest.mark.parametrize("stage, kind", [
    ("read", ("read", None)), ("read_retry", ("read", None)), ("step_1", ("step", 1)), ("step_12_retry", ("step", 12)),
    ("step_1_points", ("step", 1)), ("step_3_fix", ("step", 3)), ("settle", ("settle", None)),
    ("step_0_fix", ("settle", None)), ("writer", ("writer", None)), ("writer_again", ("writer", None)),
    ("repair_2", ("repair", 2)), ("repair_1_again", ("repair", 1)), ("something", ("other", None))])
def test_stage_kinds(stage, kind):
    assert P.kind_of(stage) == kind


def test_the_call_passes_through_unchanged():
    inner = Echo(reply='{"topics": ["porosity"], "named": ["PHIE"]}')
    events = []
    llm = P.Observed(inner, events.append)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
    usage = Usage()
    schema = {"type": "object"}
    out = llm.chat("read", msgs, usage, 512, json_schema=schema, temperature=0.3, retry=True)
    assert out == inner.reply
    assert inner.calls == [("read", msgs, usage, 512, (), {"json_schema": schema, "temperature": 0.3, "retry": True})]
    assert inner.calls[0][1] is msgs and inner.calls[0][2] is usage            # the same objects, not copies
    assert llm.replays_reasoning() == "inner" and llm.cfg == "the inner config"     # everything else is the inner's
    assert [e["kind"] for e in events] == ["call", "reply"]
    call, reply = events
    assert call == {"kind": "call", "stage": "read", "type": "read", "n": 1}
    assert reply["n"] == 1 and reply["prompt_tokens"] == 100 and reply["completion_tokens"] == 7
    assert reply["topics"] == ["porosity"] and reply["named"] == ["PHIE"] and reply["seconds"] >= 0


def test_the_harness_recording_wraps_it_as_it_wraps_the_llm():
    """components.recording replaces the client's chat on the instance (the trace's per-call attribution)."""
    inner = Echo(reply="answer")
    events, trace = [], {}
    llm = P.Observed(inner, events.append)
    C.recording(llm, trace, None)
    assert llm.chat("writer", [{"role": "user", "content": "x"}], Usage(), 10) == "answer"
    assert [c["stage"] for c in trace["calls"]] == ["writer"] and [e["kind"] for e in events] == ["call", "reply"]


def test_a_failed_call_is_reported_and_raised():
    events = []
    llm = P.Observed(Echo(fail=TimeoutError("no answer")), events.append)
    with pytest.raises(TimeoutError):
        llm.chat("step_2", [{"role": "user", "content": "x"}], Usage(), 10)
    assert events[-1]["kind"] == "reply" and events[-1]["error"] == "TimeoutError: no answer"


def test_step_replies_are_read_with_the_harness_parser():
    text = json.dumps({"focus": "where is net pay", "points": ["Where?", "How thick?"], "asks": "Where is pay?",
                       "intent": "locate", "edits": [{"op": "add", "point": 1, "text": "Pay in Z2", "grade": "low",
                                                      "ev": ["E1"]}],
                       "next": [{"runs": "NET_PAY"}, {"stats": ["SW", "PHIE"]}, {"guide": "porosity"}, "nonsense"],
                       "done": False})
    got = P.read_reply_of("step_1", text)
    assert got["focus"] == "where is net pay" and got["intent"] == "locate" and got["asks"] == "Where is pay?"
    assert got["points"] == ["Where?", "How thick?"] and got["done"] is False
    assert got["next"][:3] == ['runs {"condition": "NET_PAY"}', 'stats {"curves": ["SW", "PHIE"]}', "guide porosity"]
    assert got["next"][3].startswith("(not an action")
    assert got["edits"] == [{"op": "add", "point": 1, "grade": "low", "text": "Pay in Z2", "ev": ["E1"]}]
    assert P.read_reply_of("step_2", "not json at all")["unreadable"] is True
    assert P.read_reply_of("step_2", "") == {"empty": True}
    assert P.read_reply_of("settle", '{"edits": [{"op": "drop", "id": "C2", "why": "no support"}], "done": true}') \
        == {"edits": [{"op": "drop", "id": "C2", "text": "no support"}]}
    assert P.read_reply_of("read", "{}")["unreadable"] is True
    assert P.read_reply_of("writer", "## A\ntext") == {"draft": "## A\ntext", "chars": 9}


def test_a_reply_the_loop_salvages_is_shown_as_salvaged_not_unreadable():
    """A step reply cut off before its last brace: the loop reads the edits and actions it holds (salvage), so the
    page shows them, marked salvaged, rather than "could not be read; the harness asks the model to fix it"."""
    from petroharness.agent import loop as L
    cut = ('{"focus": "pay by zone", "edits": [{"op": "add", "point": 1, "grade": "low", "text": "Pay in Z2", '
           '"ev": ["E1"]}], "next": [{"runs": {"condition": "NET_PAY"}}], "done": false')
    assert L.complete_salvage(cut) is not None
    got = P.read_reply_of("step_2", cut)
    assert got.get("salvaged") is True and "unreadable" not in got
    assert got["edits"] == [{"op": "add", "point": 1, "grade": "low", "text": "Pay in Z2", "ev": ["E1"]}]


# --- results as the prompts show them -----------------------------------------------------------------------------------

E1 = "stats of PHIE, VCL\nPHIE [v/v]\n  Z1 mean 0.12 (n 40)\n  zones pooled: mean 0.11"
E2 = "runs of NET_PAY\n  Z2: 1010.5-1012.0 (1.5)\n  total 1.5 in 1 run"
E3_DIGEST = "section porosity.classes\n  classes (by zone)\n  (12 more lines: get E3 with find: a zone (Z1-Z2), a curve, class, parameter or depth)"
E3 = "section porosity.classes\n  classes (by zone)\n" + "\n".join(f"  line {i}" for i in range(12))


def test_results_in_a_step_prompt():
    withheld = C.text("C8", "withheld")
    prompt = (f"QUESTION:\nq\n\nTHE MAP\nmap text [not a result]\n\nOPENED (fetch exact lines with get or find):\n"
              f"  E1 stats PHIE, VCL\n  E2 runs NET_PAY\n\n[E3] {E3_DIGEST}\n\n"
              f"NEW (from step 2):\n[E1] (opened before: stats PHIE, VCL) {E1}\n\n[E2] {E2}\n\n"
              f"{C.fill('C8', 'shown_above', id='E2')}\n\n[E2] runs NET_PAY (find: Z2)\n  Z2: 1010.5-1012.0\n\n"
              f"[E1] nothing in E1 matches Z9 (zone Z9)\n\n{withheld}[E4] stats SW\n[E5] runs SW < 0.5\n\n"
              "Step 3 of 8: reply with JSON.")
    got = P.results_in(prompt)
    assert set(got) == {"E1", "E2", "E3"}                       # E4 and E5 are only listed as withheld
    assert got["E1"] == (E1, False) and got["E2"] == (E2, False)
    assert got["E3"] == (E3_DIGEST, True)


def test_results_in_the_first_look_and_all_results():
    first = f"FIRST LOOK (each zone's key curves for the topics you chose: porosity; opened for you):\n[E1] {E1}\n\nStep 1."
    assert P.results_in(first) == {"E1": (E1, False)}
    settle = f"ALL RESULTS:\n[E1] {E1}\n\n[E2] {E2}\n\n[E3] {E3}\n\nBOOKKEEPING (lists)"
    assert P.results_in(settle) == {"E1": (E1, False), "E2": (E2, False), "E3": (E3, False)}
    writer = (f"RESULT LINES (what the claims cite):\n[E1] stats PHIE, VCL (for C1)\n  Z1 mean 0.12\n\n"
              f"[E2] runs NET_PAY (for C2: holds 1.5)\n  total 1.5\n\nALL RESULTS (everything the investigation "
              f"computed):\n[E1] {E1}\n\nTHE MAP\nm")
    assert P.results_in(writer) == {"E1": (E1, False)}


def test_each_result_is_emitted_once_and_again_when_seen_whole():
    events = []
    llm = P.Observed(Echo(reply='{"edits": [], "next": [], "done": true}'), events.append)
    llm.chat("step_2", [{"role": "system", "content": "s"}, {"role": "user", "content": f"NEW (from step 1):\n[E1] {E1}\n\n[E3] {E3_DIGEST}\n\nx"}], Usage(), 10)
    llm.chat("step_2_retry", [{"role": "system", "content": "s"}, {"role": "user", "content": f"NEW (from step 1):\n[E1] {E1}\n\n[E3] {E3_DIGEST}\n\nx"}], Usage(), 10)
    llm.chat("settle", [{"role": "user", "content": f"ALL RESULTS:\n[E1] {E1}\n\n[E3] {E3}\n\nend"}], Usage(), 10)
    shown = [(e["stage"], [(i["id"], i["digest"]) for i in e["items"]]) for e in events if e["kind"] == "results"]
    assert shown == [("step_2", [("E1", False), ("E3", True)]), ("settle", [("E3", False)])]
    assert llm.results["E3"] == (E3, False)
    first = next(e for e in events if e["kind"] == "results")
    assert first["items"][0]["title"] == "stats of PHIE, VCL" and first["items"][0]["text"] == E1
    kinds = [e["kind"] for e in events]
    assert kinds[:3] == ["results", "call", "reply"]         # the results a request shows come before its call


def test_a_repair_round_carries_the_checker_findings():
    events = []
    llm = P.Observed(Echo(reply="## Fixed"), events.append)
    msgs = [{"role": "system", "content": "w"}, {"role": "user", "content": "draft this"},
            {"role": "assistant", "content": "## Draft"}, {"role": "user", "content": "These numbers appear in no result: 0.98."}]
    llm.chat("repair_1", msgs, Usage(), 10)
    call = next(e for e in events if e["kind"] == "call")
    assert call["type"] == "repair" and call["number"] == 1 and call["findings"].startswith("These numbers")


def test_the_page_is_told_how_a_question_was_read_and_answered():
    from petroharness.agent import direction
    from petroharness.ui import adapter as A
    area = next(iter(direction.areas()))
    plain = P.read_reply_of("read", json.dumps({"topics": [area], "named": ["porosity"]}))
    assert plain == {"topics": [area], "named": ["porosity"]}                      # no depth asked: none said
    direct = P.read_reply_of("read", json.dumps({"topics": [area], "named": [], "depth": "direct"}))
    assert direct["depth"] == "direct"
    look = {"read": {"topics": [area], "depth": "direct"}, "steps": [{"step": 1, "direct": True}]}
    assert A.summary(look, {}, "ok")["route"] == "direct" and A.summary(look, {}, "ok")["read"]["depth"] == "direct"
    back = {**look, "depth": {"read": "direct", "investigated_from_step": 1, "why": "the model asked for it"}}
    assert A.summary(back, {}, "ok")["route"] == "investigation after a look"
    assert A.summary({"read": {"topics": [area]}, "steps": []}, {}, "ok")["route"] == "investigation"
