"""Depth: the model says in the READ call whether a question is direct or needs an investigation. A direct question
takes look steps instead of the investigation, no settle call, and a short answer; every call thinks as the model card
says (thinking was reduced in the look steps at first and measured: it cost accuracy and saved no time). A look step
or the writer can still hand the question to an investigation. Every question is read that way, a user's and a
benchmark's; a run that asks for the investigation every time (--investigate, direct=False) gets it.
A scripted model on a real formation (no server).

    .venv/bin/python -m pytest tests/session/test_depth.py -q   (PETROHARNESS_DATA selects the dataset)
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tests" / "agent"), str(Path(__file__).resolve().parent)]
from petroharness.agent import components as C  # noqa: E402
from petroharness.agent import options  # noqa: E402
from test_conversation import Q2, Model, first_steps, formation, later_steps  # noqa: E402,F401

SIMPLE = "What is the average effective porosity?"


class Direct(Model):
    """The scripted model reading every question as `depth`, and recording when it was told to think lightly."""

    def __init__(self, steps, depth="direct"):
        super().__init__(steps)
        self.depth, self.lights, self.light = depth, [], False

    def set_light(self, on):
        self.light = bool(on)
        self.lights.append(bool(on))

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
        if stage.startswith("read"):
            self.sent.append({"stage": stage, "messages": json.loads(json.dumps(messages)), "schema": json_schema,
                              "light": self.light})
            usage.log.append({"stage": stage, "prompt_tokens": 1})
            return json.dumps({"topics": ["porosity"], "named": ["porosity"], "depth": self.depth})
        out = super().chat(stage, messages, usage, max_tokens, json_schema, temperature, retry)
        self.sent[-1]["light"] = self.light
        return out


def run(task, llm, tmp_path, question=SIMPLE):
    from petroharness.session import Conversation
    c = Conversation.on_tasks(tmp_path / "s", "k200t", llm_factory=lambda cfg: llm, max_steps=4)
    return c, c.ask_task(task.model_copy(update={"question": question}))


def test_every_question_reads_its_route_unless_the_run_asks_for_the_investigation():
    import inspect
    from petroharness import cli
    from petroharness.agent import graph as G
    from petroharness.agent import loop as L
    assert "depth" not in options.as_dict()                           # the measured switch is the code now
    for fn in (G.turn, G.answer):
        assert inspect.signature(fn).parameters["depth"].default is True
    assert inspect.signature(cli.answer).parameters["direct"].default is True           # benchmark mode too
    assert "depth" not in L.read_schema()["properties"] and L.read_schema()["required"] == ["topics", "named"]
    reply = json.dumps({"topics": [next(iter(L.direction.areas()))], "named": [], "depth": "direct"})
    assert "depth" not in L._reading(reply)                           # said unasked: not read
    schema = L.read_schema(True)
    assert schema["properties"]["depth"] == {"enum": ["direct", "investigate"]} and "depth" in schema["required"]
    assert L._reading(reply, True)["depth"] == "direct"
    assert L._reading(reply.replace("direct", "quick"), True)["depth"] == "investigate"    # anything else: investigate
    import inspect
    from petroharness import ask as A
    from petroharness.session import Conversation
    assert inspect.signature(A.ask).parameters["direct"].default is True              # the command a user runs
    assert inspect.signature(Conversation.start).parameters["direct"].default is True  # chat and the web UI
    assert inspect.signature(Conversation.on_tasks).parameters["direct"].default is True  # prepared tasks: the same
    assert '"depth": "<direct or investigate>"' in C.text("C5", "read_depth") and "depth" not in C.text("C5", "read")


def test_a_light_call_uses_the_cards_light_setting_and_drops_reasoning_left_in_the_reply():
    from petroharness.llm import LLM, Usage
    model = NS(model="m", max_tokens_param="max_tokens", send_temperature=False, send_template_kwargs=True, top_p=None,
               temperature=0.0, structured_output="none", chat_template_kwargs={"reasoning_effort": "high"},
               retry_template_kwargs={"reasoning_effort": "low"}, light_template_kwargs={"reasoning_effort": "low"},
               reasoning_end="</end>", enable_thinking=False, reasoning=True)
    llm = LLM.__new__(LLM)
    llm.cfg, sent = NS(model=model), []

    def create(kwargs):
        sent.append(kwargs["extra_body"]["chat_template_kwargs"])
        text = "thinking about it</end>  The value is 0.21." if sent[-1]["reasoning_effort"] == "low" else "The value is 0.21."
        msg = NS(content=text, reasoning=None, reasoning_content=None)
        return NS(choices=[NS(message=msg, finish_reason="stop")], usage=None), None
    llm._create = create
    usage = Usage()
    assert llm.chat("step_1", [{"role": "user", "content": "q"}], usage, 100) == "The value is 0.21."
    llm.set_light(True)
    assert llm.chat("step_1", [{"role": "user", "content": "q"}], usage, 100) == "The value is 0.21."   # the reasoning is cut
    llm.set_light(False)
    llm.chat("writer", [{"role": "user", "content": "q"}], usage, 100)
    assert sent == [{"reasoning_effort": "high"}, {"reasoning_effort": "low"}, {"reasoning_effort": "high"}]
    assert [u.get("light") for u in usage.log] == [None, True, None]
    model.light_template_kwargs = None                                # a card with no light setting: nothing changes
    llm.set_light(True)
    llm.chat("writer", [{"role": "user", "content": "q"}], usage, 100)
    assert sent[-1] == {"reasoning_effort": "high"} and usage.log[-1].get("light") is None


@pytest.mark.data
def test_a_direct_question_takes_look_steps_no_settle_and_the_short_writer_at_normal_thinking(formation, tmp_path):  # noqa: F811
    llm = Direct([{"next": [{"stats": {"curves": ["VCL"]}}], "done": False}, {"done": True}])
    c, turn = run(formation, llm, tmp_path)
    assert turn.status == "ok", turn.trace.get("error")
    stages = [x["stage"] for x in llm.sent]
    assert stages == ["read", "step_1", "step_2", "writer"]                       # no settle, no points, no repair
    read, step1, step2, writer = llm.sent
    assert read["schema"]["required"] == ["topics", "named", "depth"] and read["light"] is False
    assert read["messages"][-1]["content"].startswith(C.text("C5", "read_depth"))
    assert not any(x["light"] for x in llm.sent) and True not in llm.lights     # every call thinks as the card says
    assert step1["messages"][-1]["content"].endswith(C.text("C5", "direct_step")) and "FIRST LOOK (" in step1["messages"][-1]["content"]
    assert "NEW (from step 1):" in step2["messages"][-1]["content"] and "stats VCL" in step2["messages"][-1]["content"]
    assert writer["messages"][0]["content"] == C.text("C9", "reply_brief") + "\n" + C.text("C9", "brief_direct")
    user = writer["messages"][-1]["content"]
    assert "THE ZONE TABLE" not in user and f"Point 1: {SIMPLE}" in user and "[E2] " in user
    tr = turn.trace
    assert tr["read"]["depth"] == "direct" and [s["direct"] for s in tr["steps"]] == [True, True]
    assert tr["steps"][0]["actions"] == ['stats {"curves": ["VCL"]}'] and tr["steps"][1]["done"] is True
    assert tr["options"] == {} and tr["reads_depth"] is True and tr["claims"] == [] and "settle" not in tr
    assert [e.id for e in c.live.ledger.items] == ["E1", "E2"]


@pytest.mark.data
def test_a_direct_question_whose_first_look_states_it_is_two_calls_after_read(formation, tmp_path):  # noqa: F811
    llm = Direct([{"done": True}])
    c, turn = run(formation, llm, tmp_path)
    assert [x["stage"] for x in llm.sent] == ["read", "step_1", "writer"] and turn.status == "ok"
    assert [e.id for e in c.live.ledger.items] == ["E1"]                          # the first look alone


@pytest.mark.data
def test_the_look_step_can_send_the_question_to_an_investigation_at_normal_thinking(formation, tmp_path):  # noqa: F811
    llm = Direct([{"depth": "investigate"}] + first_steps())
    c, turn = run(formation, llm, tmp_path)
    assert turn.status == "ok", turn.trace.get("error")
    stages = [x["stage"] for x in llm.sent]
    assert stages[:3] == ["read", "step_1", "step_1"] and "settle" in stages and stages[-1] == "writer"
    look, first = llm.sent[1], llm.sent[2]
    assert look["light"] is False and first["light"] is False and True not in llm.lights
    assert look["messages"][-1]["content"].endswith(C.text("C5", "direct_step"))
    assert not first["messages"][-1]["content"].endswith(C.text("C5", "direct_step"))   # the investigation's own step 1
    writer = llm.sent[-1]["messages"]
    assert writer[0]["content"].startswith(C.text("C9", "write")) and llm.sent[-1]["light"] is False
    assert turn.trace["depth"] == {"read": "direct", "investigated_from_step": 1, "why": "the model asked for it"}
    assert turn.trace["steps"][0]["to_investigation"] and turn.trace["claims"]


@pytest.mark.data
def test_a_question_read_as_an_investigation_runs_the_investigation(formation, tmp_path):  # noqa: F811
    llm = Direct(first_steps(), depth="investigate")
    c, turn = run(formation, llm, tmp_path)
    stages = [x["stage"] for x in llm.sent]
    assert stages == ["read", "step_1", "step_2", "settle", "writer"] and True not in llm.lights and turn.status == "ok"
    assert not any(x["light"] for x in llm.sent) and turn.trace["read"]["depth"] == "investigate"


@pytest.mark.data
def test_a_later_direct_question_reads_an_earlier_result_it_fetched_and_keeps_the_later_rule(formation, tmp_path):  # noqa: F811
    from petroharness.session import Conversation
    from petroharness.session import earlier as E
    llm = Direct(first_steps(), depth="investigate")
    c = Conversation.on_tasks(tmp_path / "s", "k200t", llm_factory=lambda cfg: llm, max_steps=4)
    c.ask_task(formation)
    n1 = len(llm.sent)
    llm.depth, llm.steps = "direct", [{"next": [{"get": "E2"}], "done": False}, {"done": True}]
    two = c.ask_task(formation.model_copy(update={"task_id": "second", "question": Q2}))
    later = llm.sent[n1:]
    assert [x["stage"] for x in later] == ["read", "step_1", "step_2", "writer"] and two.status == "ok"
    step1 = later[1]["messages"][-1]["content"]
    assert E.block(c.turns[:1]) in step1 and step1.endswith(C.text("C5", "direct_step"))
    assert C.text("C5", "step1_later") not in step1                 # the look step is not the investigation's step 1
    writer = later[-1]["messages"]
    assert writer[0]["content"] == (C.text("C9", "reply_brief") + "\n" + C.text("C9", "brief_later") + "\n"
                                    + C.text("C9", "brief_direct"))
    # the writer reads what the look steps were shown: the first look (the same call as question 1's: E1) and E2
    assert "[E1] " in writer[-1]["content"] and "[E2] " in writer[-1]["content"] and c.live.fetched == ["E1", "E2"]
    assert two.trace["session"]["turn"] == 2 and two.trace["read"]["depth"] == "direct"
    assert c.turns[1]["read_from"] == ["E1", "E2"] and c.turns[1]["claims"] == [] and "read_from" not in c.turns[0]
    assert "  (read from E1, E2)" in E.block(c.turns)                # what the next question is shown of this one


@pytest.mark.data
def test_a_later_direct_answer_is_written_from_the_earlier_results_its_look_steps_were_shown(formation, tmp_path):  # noqa: F811
    """Question 2's first look is the call question 1's was, so it shows an earlier result; the look step says the
    results state it; the writer must be given that result (a short answer has no claims to cite it by). The same
    for lines read with get and find."""
    from petroharness.session import Conversation
    llm = Direct(first_steps(), depth="investigate")
    c = Conversation.on_tasks(tmp_path / "s", "k200t", llm_factory=lambda cfg: llm, max_steps=4)
    c.ask_task(formation)
    assert [e.id for e in c.live.ledger.items] == ["E1", "E2"]
    n1 = len(llm.sent)
    llm.depth, llm.steps = "direct", [{"done": True}]
    two = c.ask_task(formation.model_copy(update={"task_id": "second", "question": Q2}))
    later = llm.sent[n1:]
    assert [x["stage"] for x in later] == ["read", "step_1", "writer"] and two.status == "ok"
    assert "FIRST LOOK (" in later[1]["messages"][-1]["content"] and "[E1] " in later[1]["messages"][-1]["content"]
    results = later[-1]["messages"][-1]["content"].split("RESULTS (", 1)[1].split("WHAT THE CURVES ARE", 1)[0]
    assert "[E1] " in results and "[E2] " not in results and c.live.fetched == ["E1"]
    assert [e.id for e in c.live.ledger.items] == ["E1", "E2"]            # nothing new was opened
    assert two.trace["basis"] is not None and c.turns[1]["read_from"] == ["E1"]
    n2 = len(llm.sent)                                                    # lines of an earlier result, by get and find
    zone = c.live.f.inv.zones[0].id
    llm.steps = [{"next": [{"get": "E2", "find": zone}], "done": False}, {"done": True}]
    three = c.ask_task(formation.model_copy(update={"task_id": "third", "question": SIMPLE}))
    assert three.status == "ok" and [x["stage"] for x in llm.sent[n2:]] == ["read", "step_1", "step_2", "writer"]
    results = llm.sent[-1]["messages"][-1]["content"].split("RESULTS (", 1)[1].split("WHAT THE CURVES ARE", 1)[0]
    assert "[E1] " in results and "[E2] " in results and c.live.fetched == ["E1", "E2"]


@pytest.mark.data
def test_a_look_reply_whose_lookups_cannot_be_read_gets_an_investigation(formation, tmp_path):  # noqa: F811
    llm = Direct([{"next": [{"zone_table_of": {"curves": ["PHIE"]}}], "done": False}] + first_steps())
    c, turn = run(formation, llm, tmp_path)
    assert turn.status == "ok", turn.trace.get("error")
    stages = [x["stage"] for x in llm.sent]
    assert stages[:3] == ["read", "step_1", "step_1"] and "settle" in stages and stages[-1] == "writer"
    assert turn.trace["depth"] == {"read": "direct", "investigated_from_step": 1, "why": "its lookups could not be read"}
    assert turn.trace["steps"][0]["unread"] and llm.sent[2]["light"] is False and c.live.fetched == []
    from petroharness.agent.graph import route, route_text
    assert route(turn.trace) == "investigation after a look" and route_text(turn.trace).startswith("an investigation after")


@pytest.mark.data
def test_the_way_back_is_read_after_the_reasoning_a_retry_leaves_in_its_reply(formation, tmp_path):  # noqa: F811
    """A reply that carries its reasoning before the card's reasoning_end (a retry's is not cut by the client): the
    reasoning may quote the prompt's own {"depth": "investigate"}; only the reply proper is read."""
    llm = Direct(['I could say {"depth": "investigate"} but the first look states it.</end>\n{"done": true}'])
    llm.cfg = NS(model=NS(reasoning_end="</end>"))
    c, turn = run(formation, llm, tmp_path)
    assert [x["stage"] for x in llm.sent] == ["read", "step_1", "writer"] and turn.status == "ok"
    assert "depth" not in turn.trace or not isinstance(turn.trace["depth"], dict)
    assert turn.trace["steps"][0]["reply"] == '{"done": true}'
    from petroharness.agent.graph import route, route_text
    assert route(turn.trace) == "direct" and route_text(turn.trace) == "a direct answer, 1 look step"


@pytest.mark.data
def test_a_client_shared_across_questions_starts_each_at_normal_thinking(formation, tmp_path):  # noqa: F811
    llm = Direct([{"done": True}])
    llm.light = True                                                   # left light by something before
    c, turn = run(formation, llm, tmp_path)
    assert llm.sent[0]["stage"] == "read" and llm.sent[0]["light"] is False and llm.lights[0] is False
    assert not any(x["light"] for x in llm.sent) and llm.light is False


def test_resume_and_the_chat_command_take_the_users_word_on_depth():
    import inspect
    from petroharness.session import Conversation, chat
    assert inspect.signature(Conversation.resume).parameters["direct"].default is None    # as it was started
    args = chat.parser().parse_args(["--resume", "folder", "--investigate"])
    assert args.investigate is True and args.resume

@pytest.mark.data
def test_a_run_that_asks_for_the_investigation_takes_the_3_5_6_route(formation, tmp_path):  # noqa: F811
    """direct=False (--investigate): the READ call is not asked for the route, and a model that would read the
    question as direct still gets the whole investigation; the setup and the log say so, and a resumed conversation
    keeps it."""
    from petroharness.session import Conversation
    llm = Direct([{"done": True}])
    c = Conversation.on_tasks(tmp_path / "s", "k200t", llm_factory=lambda cfg: llm, max_steps=4)
    turn = c.ask_task(formation.model_copy(update={"question": SIMPLE}))
    assert [x["stage"] for x in llm.sent] == ["read", "step_1", "writer"] and turn.status == "ok"
    assert turn.trace["reads_depth"] is True and turn.trace["options"] == {}
    assert c.setup.depth is True and c.log.events("setup")[0]["depth"] is True
    plain = Direct(first_steps(), depth="direct")                      # the same model, a run not reading the route
    c2 = Conversation.on_tasks(tmp_path / "t", "k200t", llm_factory=lambda cfg: plain, max_steps=4, direct=False)
    two = c2.ask_task(formation)
    assert two.trace["reads_depth"] is False and "depth" not in two.trace["read"] and c2.setup.depth is False
    assert [x["stage"] for x in plain.sent] == ["read", "step_1", "step_2", "settle", "writer"]
    assert plain.sent[0]["schema"]["required"] == ["topics", "named"]
    assert c2.log.events("session_start")[0]["direct"] is False
    again = Conversation.resume(tmp_path / "t", llm_factory=lambda cfg: plain)
    assert again.depth is False                                        # resumed as it was started


class HandsOver(Direct):
    """The scripted model whose short answer's writer first hands the question over."""

    def __init__(self, steps, word="INVESTIGATE"):
        super().__init__(steps)
        self.word, self.handed = word, False

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
        out = super().chat(stage, messages, usage, max_tokens, json_schema, temperature, retry)
        brief = messages[0]["content"].startswith(C.text("C9", "reply_brief"))
        if stage == "writer" and brief and not self.handed:
            self.handed = True
            return self.word
        return out


@pytest.mark.data
@pytest.mark.parametrize("word", ["INVESTIGATE", "**Investigate.**\n"])
def test_the_short_answers_writer_can_hand_the_question_to_an_investigation(formation, tmp_path, word):  # noqa: F811
    """The look step said the results state it; the writer finds they do not. It replies with the one word, and the
    question gets the investigation, from its own step 1, with the full writer at the end."""
    llm = HandsOver([{"done": True}] + first_steps(), word)
    c, turn = run(formation, llm, tmp_path)
    assert turn.status == "ok", turn.trace.get("error")
    stages = [x["stage"] for x in llm.sent]
    assert stages[:4] == ["read", "step_1", "writer", "step_1"] and "settle" in stages and stages[-1] == "writer"
    assert "INVESTIGATE" in llm.sent[2]["messages"][0]["content"]                 # the short brief says how to hand over
    final = llm.sent[-1]["messages"][0]["content"]
    assert final.startswith(C.text("C9", "write")) and C.text("C9", "brief_direct") not in final
    assert not llm.sent[3]["messages"][-1]["content"].endswith(C.text("C5", "direct_step"))   # the investigation's step 1
    assert turn.trace["depth"]["investigated_from"] == "the writer" and turn.trace["claims"]
    assert turn.answer.strip() and "INVESTIGATE" not in turn.answer.upper()
    from petroharness.agent.graph import route
    assert route(turn.trace) == "investigation after a look" and c.live.fetched == []


@pytest.mark.data
def test_an_answer_that_only_begins_with_the_word_is_an_answer(formation, tmp_path):  # noqa: F811
    text = "Investigate further only if core is acquired: the average effective porosity is as the zones show. " * 3
    llm = HandsOver([{"done": True}], text)
    c, turn = run(formation, llm, tmp_path)
    assert [x["stage"] for x in llm.sent][:3] == ["read", "step_1", "writer"] and "settle" not in [x["stage"] for x in llm.sent]
    assert not isinstance(turn.trace.get("depth"), dict)



@pytest.mark.data
def test_a_later_direct_question_its_writer_hands_over_runs_the_later_investigation(formation, tmp_path):  # noqa: F811
    from petroharness.session import Conversation
    llm = HandsOver(first_steps())
    llm.depth, llm.handed = "investigate", True                       # question 1: an investigation, no hand-over
    c = Conversation.on_tasks(tmp_path / "s", "k200t", llm_factory=lambda cfg: llm, max_steps=4)
    c.ask_task(formation)
    n1 = len(llm.sent)
    llm.depth, llm.handed, llm.steps = "direct", False, [{"done": True}] + later_steps()
    two = c.ask_task(formation.model_copy(update={"task_id": "second", "question": Q2}))
    later = llm.sent[n1:]
    stages = [x["stage"] for x in later]
    assert two.status == "ok", two.trace.get("error")
    assert stages[:4] == ["read", "step_1", "writer", "step_1"] and "settle" in stages and stages[-1] == "writer"
    assert C.text("C9", "brief_direct") in later[2]["messages"][0]["content"]          # the short brief, handed over
    assert C.text("C9", "brief_direct") not in later[-1]["messages"][0]["content"]     # the investigation's own writer
    assert two.trace["depth"]["investigated_from"] == "the writer" and two.trace["claims"] and c.live.fetched == []
    assert c.turns[1]["claims"] and "read_from" not in c.turns[1]                      # it has claims: they cite
