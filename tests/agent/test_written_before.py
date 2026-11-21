"""The settle step lists the claims whose text was written before results their point's claims now cite were opened
(live round 1, Z2: "the Brent stretch contains no Dunlin samples" was written at step 1 and revised five times without a
new text, citing the Dunlin results opened at step 4; at settle its means said the well does reach the Dunlin, its
text still said it did not). A fact of order: code reads no claim's content, the model reads whether each text holds.

    .venv/bin/python -m pytest tests/agent/test_written_before.py -q
"""
import json
import re

import pytest

from _wells import CASES, formation_of, sample

pytestmark = pytest.mark.data


@pytest.fixture()
def opened():
    from petroharness.agent.claims import Claims
    from petroharness.agent.ledger import Ledger
    f = formation_of(CASES["brent"])
    led = Ledger(f)
    led.open("stats", {"curves": ["PHIE"]})                                       # E1
    return led, Claims(["What is the porosity?", "And the clay?"], led, "", "q", f.view, ("30/6-5",))


def _listed(cl):
    from petroharness.agent.loop import written_before
    return written_before(list(cl.claims.values()), {e.id: e for e in cl.ledger.items})


def test_a_claim_whose_text_came_before_its_points_newer_results_is_listed(opened):
    led, cl = opened
    assert cl.apply([{"op": "add", "point": 1, "text": "Porosity is read from the statistics", "ev": ["E1"],
                      "grade": "moderate"}]) == []
    assert cl.claims["C1"].text_at == 1 and _listed(cl) == []
    led.open("stats", {"curves": ["VCL"]})                                        # E2
    led.open("stats", {"curves": ["PHIT"]})                                       # E3
    cl.apply([{"op": "revise", "id": "C1", "ev": ["E1", "E2"]}])                 # new results, the old text
    assert _listed(cl) == ["C1 (point 1; its text came before E2)"]
    cl.apply([{"op": "add", "point": 1, "text": "Total porosity is read too", "ev": ["E3"], "grade": "low"}])
    assert _listed(cl) == ["C1 (point 1; its text came before E2, E3)"]          # its point's claims cite E3 too
    cl.apply([{"op": "add", "point": 2, "text": "Clay is open", "grade": "hypothesis"}])
    assert len(_listed(cl)) == 1                                                  # a hypothesis, another point: not
    cl.apply([{"op": "revise", "id": "C1", "text": "Porosity is read from the statistics"}])
    assert cl.claims["C1"].text_at == 1                                           # the same text is not a new one
    cl.apply([{"op": "revise", "id": "C1", "text": "Porosity and clay are read from the statistics"}])
    assert cl.claims["C1"].text_at == 3 and _listed(cl) == []


class Model:
    """An investigation: step 1 adds a hypothesis citing nothing and opens PHIE's statistics; step 2 grades it on that
    result without a new text; settle changes nothing; the writer states no number."""

    def __init__(self):
        self.sent = []

    def replays_reasoning(self):
        return True

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
        self.sent.append({"stage": stage, "messages": json.loads(json.dumps(messages))})
        usage.log.append({"stage": stage, "prompt_tokens": 10, "completion_tokens": 5, "seconds": 0.0})
        if stage.startswith("read"):
            r = {"topics": ["porosity"], "named": ["PHIE"]}
        elif stage == "step_1":
            r = {"points": ["What is the porosity?"], "intent": "characterize", "focus": "porosity",
                 "edits": [{"op": "add", "point": 1, "text": "Porosity is to be read", "grade": "hypothesis"}],
                 "next": [{"stats": {"curves": ["PHIE"], "zones": ["Ness Fm."]}}], "done": False}
        elif stage == "step_2":
            newest = max(re.findall(r"\[(E\d+)\]", messages[-1]["content"]), key=lambda x: int(x[1:]))
            r = {"edits": [{"op": "revise", "id": "C1", "ev": [newest], "grade": "moderate"}], "next": [], "done": True}
        elif stage.startswith(("step_", "settle")):
            r = {"edits": [], "next": [], "done": True}
        else:
            r = "Porosity is read from the results."
        return r if isinstance(r, str) else json.dumps(r)

    def last(self, stage):
        return next(c for c in reversed(self.sent) if c["stage"] == stage)["messages"][-1]["content"]


def test_settle_is_shown_a_claim_its_newer_result_never_rewrote(tmp_path, monkeypatch):
    from petroharness.session import Conversation
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS"):
        monkeypatch.delenv(key, raising=False)
    model = Model()
    c = Conversation.start(sample("30/6-5"), tmp_path / "s", tops=sample("formations_30_6-5.csv"), formation="BRENT GP.",
                           llm_factory=lambda cfg: model, figures=False, direct=False)
    t = c.ask("What is the porosity of the Ness?")
    assert t.ok, t.trace.get("error")
    c1 = next(x for x in t.trace["claims"] if x["id"] == "C1")
    newest = c1["ev"][-1]
    assert int(newest[1:]) > c1["text_at"]                                        # opened after its text was written
    settle = model.last("settle")
    assert f"C1 (point 1; its text came before {newest})" in settle
    assert "written before results that their point's claims now cite were opened" in settle
