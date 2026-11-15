"""The setup record (petroharness.core.setup): what a run is made of, with one hash; printed by `petroharness setup`;
logged once per conversation and named in every trace and audit trail.

    .venv/bin/python -m pytest tests/core -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tests" / "agent"), str(ROOT / "tests" / "session")]
from petroharness.config import given_settings  # noqa: E402
from petroharness.core import setup as S  # noqa: E402


def one(**kw):
    cfg, given = S.config_for()
    with given_settings(given):
        return cfg, S.of(cfg, **kw)


def test_a_setup_names_every_part_and_hashes_the_same_twice():
    cfg, s = one()
    d = s.to_dict()
    assert set(d) == {"harness", "commit", "petrophys", "components", "functions", "skills", "model", "card", "data",
                      "policy", "writer", "fmt", "max_steps", "mode", "depth"}
    assert d["harness"] and "@" in d["petrophys"] and len(d["functions"]) == 12 and len(d["card"]) == 12
    assert set(d["components"]) >= {"C1", "C5", "C9"} and d["skills"]["library"] and d["max_steps"] > 0
    assert len(s.hash()) == 12 and s.hash() == one()[1].hash()
    json.dumps(d)                                                    # plain data: it goes in the session log


def test_what_answers_changes_the_hash_and_where_the_model_is_reached_does_not():
    cfg, s = one()
    _, other = one(writer="")
    assert other.hash() != s.hash() and S.differences(s.to_dict(), other.to_dict()) == ["writer"]
    moved = cfg.model_copy(deep=True)
    moved.model.base_url, moved.model.timeout_s = "http://elsewhere:9/v1", 5.0
    cfg2, given = S.config_for()
    with given_settings(given):
        assert S.of(moved).hash() == s.hash()                        # an endpoint or a timeout is not what answers
        warmer = cfg.model_copy(deep=True)
        warmer.model.temperature = cfg.model.temperature + 0.3
        hot = S.of(warmer)
    assert hot.hash() != s.hash() and S.differences(s.to_dict(), hot.to_dict()) == ["card"]
    a, b = s.to_dict(), s.to_dict()
    b["components"] = {**b["components"], "C9": "changed"}
    assert S.differences(a, b) == ["components.C9"] and S.differences(a, a) == []


def test_the_command_prints_the_record_and_its_hash(capsys):
    assert S.main([]) == 0
    out = capsys.readouterr().out
    _, s = one()
    assert out.startswith(f"setup {s.hash()}\n") and "  components:\n    C1: " in out and "  petrophys: " in out
    assert S.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["hash"] == s.hash()
    assert S.main(["--model-card", "no-such-card"]) == 2


@pytest.mark.data
def test_a_conversation_logs_its_setup_once_and_every_trace_and_trail_names_it(tmp_path):
    from test_conversation import Model, first_steps, later_steps, Q2
    from test_conversation import formation as _formation  # noqa: F401  (the fixture's function)
    pytest.importorskip("petroharness.session")
    from petroharness.evidence import EvidenceGraph, audit
    from petroharness.session import Conversation
    import test_conversation as T
    task = _build(T)
    if task is None:
        pytest.skip("no formation with PHIE, VCL and two zones")
    llm = Model(first_steps() + later_steps())
    c = Conversation.on_tasks(tmp_path / "s", "k200t", llm_factory=lambda cfg: llm, max_steps=4)
    one_, two = c.ask_task(task), c.ask_task(task.model_copy(update={"task_id": "second", "question": Q2}))
    events = c.log.events("setup")
    assert len(events) == 1 and events[0]["hash"] == c.setup.hash() and events[0]["mode"] == "tasks"
    assert events[0]["writer"] == "open" and events[0]["max_steps"] == 4
    assert one_.trace["setup"] == two.trace["setup"] == c.setup.hash()
    g = EvidenceGraph.from_log(c.folder)
    assert g.nodes["session"]["setup"] == c.setup.hash() and g.nodes["session"]["setups"] == [c.setup.hash()]
    assert f"- Setup (petroharness setup; the session log's setup event holds its parts): {c.setup.hash()}" in audit.markdown(g, 1)
    again = Conversation.resume(c.folder, key="k200t", llm_factory=lambda cfg: Model(later_steps()))
    again.ask_task(task.model_copy(update={"task_id": "third", "question": Q2}))
    assert len(again.log.events("setup")) == 1                       # the same setup: not logged again


def _build(T):
    """The session tests' formation, without the fixture machinery: (task) with Session.build patched for this run."""
    from test_b2_tools import F
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.loop import Session
    from petroharness.agent.map import render
    got = next(((t, f) for t, f in F() if {"PHIE", "VCL"} <= set(f.inv.curves) and len(f.view.zones) >= 2), None)
    if got is None:
        return None
    t, f = got
    _build.patch = pytest.MonkeyPatch()
    _build.patch.setattr(Session, "build", classmethod(lambda cls, task, cfg: Session(task, f, render(f.inv), Ledger(f))))
    return t.model_copy(update={"question": T.Q1})


@pytest.fixture(autouse=True)
def _undo():
    yield
    if getattr(_build, "patch", None) is not None:
        _build.patch.undo()
        _build.patch = None
