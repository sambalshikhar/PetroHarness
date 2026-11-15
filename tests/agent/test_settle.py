"""The final settle step (src/petroharness/agent/loop.py settle): it shows every opened result and the claims, applies
the edits through the claim checks, and records what changed; an unreadable reply changes nothing.
    .venv/bin/python -m pytest tests/agent/test_settle.py -q"""
import json
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.llm import Usage  # noqa: E402
from test_b5_loop import MEANS, Script, _session  # noqa: E402
from petroharness.agent.claims import Claims  # noqa: E402
from petroharness.agent.loop import SETTLE, settle  # noqa: E402


def _state():
    s = _session()
    item, _ = s.ledger.open("stats", {"curves": ["SW"]})
    s.points = ["Where is SW low?"]
    s.claims = Claims(s.points, s.ledger, s.map, s.task.question, s.f.view, (s.task.well,))
    s.claims.apply([{"op": "add", "point": 1, "text": "SW zone means pending: to be confirmed against the stats",
                     "ev": [item.id], "grade": "low", "means": MEANS}])
    return s, item


@pytest.mark.data
def test_settle_shows_every_result_and_applies_the_edits():
    s, item = _state()
    reply = {"edits": [{"op": "revise", "id": "C1", "text": "SW is recorded in every zone (stats of SW)",
                        "ev": [item.id], "grade": "moderate", "means": MEANS}], "done": True}
    llm, trace = Script([reply]), {}
    settle(llm, s, Usage(), 4000, trace)
    stage, msgs = llm.sent[0]
    user = msgs[-1]["content"]
    assert stage == "settle" and SETTLE in user and "ALL RESULTS" in user and f"[{item.id}]" in user
    assert "YOUR ANSWER" in user and "pending" in user
    c = s.claims.claims["C1"]
    assert c.grade == "moderate" and "pending" not in c.text
    assert trace["settle"]["edits"] and trace["claims"][0]["grade"] == "moderate"
    assert trace["settle"]["claims_before"] == trace["settle"]["claims_after"] == 1


@pytest.mark.data
def test_an_unreadable_settle_reply_changes_nothing():
    s, _ = _state()
    before = json.dumps([c.__dict__ for c in s.claims.claims.values()], default=str)
    llm, trace = Script(["not json at all", "still not json"]), {}
    settle(llm, s, Usage(), 4000, trace)
    assert trace["settle"].get("error") == "unreadable reply"
    assert json.dumps([c.__dict__ for c in s.claims.claims.values()], default=str) == before
