"""The public mini set (tests/gate/mini): recorded conversations on a sample well that ships with Petrophys, replayed
with no model server and no private data. Every request the code builds must equal the recorded one (the replayer
stops at the first difference and names the call and the place), and the answers, the results opened, the number
links, the steps and the figures chosen must come out the same. It runs the whole path a user runs: the LAS file, the
tops table, the first question, the later questions, the figures and the audit trail.

    .venv/bin/python -m pytest tests/gate -q          (no data settings, no endpoint)

A different Petrophys version computes different curves, so different prompts: the test then skips and says so.
Record again with tests/gate/record_mini.py after a change that is meant to alter what the model is sent.
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(HERE)]
import record_mini as R  # noqa: E402

RECORDED = sorted(p.parent.name for p in R.MINI.glob("*/set.json"))


def test_the_request_gate_compares_run_by_run_and_names_every_difference(tmp_path, capsys):
    import request_gate as G
    run = {"task_id": "t1", "calls": [["read", ["a", "b"], "s", 100, None, False], ["writer", ["c"], "", 200, None, False]],
           "status": "ok", "answer": "x"}
    base, same, other = tmp_path / "base.jsonl", tmp_path / "same.jsonl", tmp_path / "other.jsonl"
    base.write_text(json.dumps(run) + "\n")
    same.write_text(json.dumps(run) + "\n")
    changed = {**run, "calls": [run["calls"][0], ["writer", ["d"], "", 200, None, False]], "answer": "y"}
    other.write_text(json.dumps(changed) + "\n")
    assert G.compare([(base, same)]) == 0 and "1/1 runs identical" in capsys.readouterr().out
    assert G.compare([(base, other)]) == 1
    out = capsys.readouterr().out
    assert "0/1 runs identical" in out and "messages at writer" in out and "answer" in out
    assert G.compare([(base, tmp_path / "none.jsonl")]) == 1
    trace = {"points": ["what is asked", "second point"], "intent": "locate", "answer": "the answer",
             "read": {"reply": '{"topics": ["porosity"]}'},
             "steps": [{"focus": "f", "edits": [{"op": "add", "point": 1, "text": "c", "flags": ["x"]}],
                        "actions": ['stats {"curves": ["PHIE"]}', "get E1 mean", "guide porosity"], "done": False}]}
    step = json.loads(G.replies(trace, "step_1"))
    assert step == {"asks": "what is asked", "points": ["second point"], "intent": "locate", "focus": "f",
                    "edits": [{"op": "add", "point": 1, "text": "c"}],
                    "next": [{"stats": {"curves": ["PHIE"]}}, {"get": "E1", "find": "mean"}, {"guide": "porosity"}],
                    "done": False}
    assert G.replies(trace, "read_retry") == '{"topics": ["porosity"]}' and G.replies(trace, "repair_1") == "the answer"


def test_the_replayer_serves_a_direct_runs_replies_in_the_order_its_route_took_them():
    """A run's look steps and its investigation's steps share their stage names (step_1, ...): the replayer serves
    the looks first, then a writer's hand-over (INVESTIGATE) where there was one, then the investigation."""
    import request_gate as G
    look = lambda k, reply, **kw: {"step": k, "direct": True, "reply": reply, **kw}
    step = {"step": 1, "focus": "f", "edits": [], "actions": ['stats {"curves": ["PHIE"]}'], "done": True}
    direct = {"read": {"reply": '{"topics": ["porosity"], "named": [], "depth": "direct"}', "depth": "direct"},
              "steps": [look(1, '{"next": [{"stats": {"curves": ["VCL"]}}], "done": false}'), look(2, '{"done": true}')],
              "points": ["what is asked"], "answer": "the short answer"}
    R = G.Replies(direct)
    assert [R(s) for s in ("read", "step_1", "step_1_retry", "step_2", "writer", "repair_1")] == [
        direct["read"]["reply"], direct["steps"][0]["reply"], direct["steps"][0]["reply"], '{"done": true}',
        "the short answer", "the short answer"]
    back = {**direct, "steps": [look(1, '{"depth": "investigate"}', to_investigation="the model asked for it"), step],
            "depth": {"read": "direct", "investigated_from_step": 1}, "points": ["the question", "a point"]}
    R = G.Replies(back)
    assert R("step_1") == '{"depth": "investigate"}'
    again = json.loads(R("step_1"))                                   # the investigation's own step 1
    assert again["points"] == ["a point"] and again["next"] == [{"stats": {"curves": ["PHIE"]}}]
    assert R("writer") == "the short answer"
    handed = {**direct, "steps": [look(1, '{"done": true}'), step], "points": ["the question"],
              "depth": {"read": "direct", "investigated_from": "the writer"}}
    R = G.Replies(handed)
    assert [R("step_1"), R("writer")] == ['{"done": true}', "INVESTIGATE"]           # the short answer handed over
    assert json.loads(R("step_1"))["done"] is True and R("writer") == "the short answer"
    plain = {**direct, "steps": [step], "read": {"reply": "{}"}}                     # no look: as replies() serves
    R = G.Replies(plain)
    assert R("step_1") == G.replies(plain, "step_1") and R("writer") == "the short answer"


@pytest.mark.skipif(not RECORDED, reason="no recorded mini set in this checkout (tests/gate/record_mini.py)")
@pytest.mark.parametrize("name", RECORDED)
def test_a_recorded_conversation_replays_request_for_request(name, tmp_path, monkeypatch):
    from petroharness import tape
    from petroharness.evidence import EvidenceGraph, audit
    from petroharness.llm import LLM
    from petroharness.session import Conversation
    from petroharness.well.prepare import library_identity
    spec = json.loads((R.MINI / name / "set.json").read_text())
    here, then = library_identity().split("@")[0], spec["petrophys"].split("@")[0]
    if here != then:
        pytest.skip(f"recorded with Petrophys {then}; this is {here}: the curves, and so the prompts, differ")
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS", "PETROHARNESS_MODEL_URL", "PETROHARNESS_BASE_URL"):
        monkeypatch.delenv(key, raising=False)                        # a user's defaults: no settings, no endpoint
    las, tops = R.sample_files(spec)
    served = {}

    def factory(cfg):                                                 # the harness's own client, answered from the tape
        llm = LLM(cfg)
        llm.client.chat.completions.create = served["replayer"]
        return llm
    c = Conversation.start(las, tmp_path / "session", formation=spec["formation"], tops=tops, llm_factory=factory)
    assert c.p.used == spec["interval"]
    for n, question in enumerate(spec["questions"], 1):
        served["replayer"] = tape.Replayer(tape.load(R.MINI / name / "turns" / f"{n:02d}.tape.jsonl"))
        turn = c.ask(question)
        assert not turn.trace.get("error"), turn.trace.get("error")   # a request that differs is said here
        figure_errors = (turn.trace.get("figures") or {}).get("errors") or []
        assert not any("TapeMismatch" in e for e in figure_errors), figure_errors   # or here, for the figures call
        assert served["replayer"].left() == 0, "the replay made fewer model calls than the recording"
        assert R.expected(c, turn) == spec["turns"][f"{n:02d}"]
        assert turn.answer == (R.MINI / name / "turns" / f"{n:02d}.answer.md").read_text()
    # what a user gets beside the answers: the interval's display, the audit trail from the folder alone
    shown = c.overview()
    assert shown == c.folder / "overview.png" and shown.read_bytes().startswith(b"\x89PNG")
    g = EvidenceGraph.from_log(c.folder)
    assert "las" in g.nodes and g.nodes["las"]["sha256"] and g.questions() == list(range(1, len(spec["questions"]) + 1))
    trail = g.trail(1)
    assert trail["results"] and trail["steps"] and any(x["source"] == "input" for x in trail["curves"])
    assert "## Steps Petrophys ran" in audit.markdown(g, 1)
