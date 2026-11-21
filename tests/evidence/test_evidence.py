"""The evidence graph (petroharness.evidence): the well's record as plain data, the numbers of an answer linked to the
results that show them, the graph rebuilt from a conversation's log, and the audit trail written from it. A scripted
model on a real formation (no server).

    .venv/bin/python -m pytest tests/evidence -q   (PETROHARNESS_DATA selects the dataset for the data tests)
"""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tests" / "agent"), str(ROOT / "tests" / "session")]
from petroharness.evidence import EvidenceGraph  # noqa: E402
from petroharness.evidence import audit, links  # noqa: E402
from petroharness.evidence import record as R  # noqa: E402
from test_conversation import CLAIM1, Q1, Q2, Model, first_steps, formation, later_steps  # noqa: E402,F401

SNAP = {"curves": {"GR": {"source": "input", "unit": "API", "step": ""},
                   "RHOB": {"source": "input", "unit": "g/cm3", "step": ""},
                   "VCL": {"source": "computed", "unit": "v/v", "step": "clay"},
                   "PHIE": {"source": "computed", "unit": "v/v", "step": "porosity"},
                   "SW_ALT": {"source": "computed", "unit": "v/v", "step": "saturation (on request)"}},
        "steps": [{"step": "clay", "method": "linear", "inputs": ["GR"], "outputs": ["VCL"], "parameters": {"gr_max": 120}},
                  {"step": "porosity", "method": "density", "inputs": ["RHOB", "VCL"], "outputs": ["PHIE", "PHIT"],
                   "parameters": {"rho_ma": 2.65}},
                  {"step": "saturation", "method": "archie", "inputs": ["PHIE", "RW/RT"], "outputs": ["SW"],
                   "parameters": {"m": 2}}]}


def test_the_record_is_walked_from_a_curve_back_through_the_steps_it_rests_on():
    assert R.step_of(SNAP) == {"VCL": "clay", "PHIE": "porosity", "PHIT": "porosity", "SW": "saturation",
                               "SW_ALT": "saturation (on request)"}
    rows = R.behind(SNAP, ["SW", "GR", "NOPE"])
    assert [(r["step"], r["why"]) for r in rows] == [("clay", R.UPSTREAM), ("porosity", R.UPSTREAM),
                                                     ("saturation", R.NAMED)]
    assert rows[2]["curves"] == ["SW"] and rows[2]["parameters"] == {"m": 2} and rows[1]["inputs"] == ["RHOB", "VCL"]
    assert R.behind(SNAP, ["SW_ALT"])[-1]["method"] == R.ON_REQUEST
    assert R.names("stats PHIE, SW where VCL < 0.3 and phie") == ["PHIE", "SW", "VCL"]
    inv = NS(curves={"PHIE": NS(source="computed", step="porosity", unit="v/v"), "GR": NS(source="input", step=None, unit="API")},
             methods=[NS(step="porosity", method="density", inputs=["RHOB"], outputs=["PHIE"],
                         parameters={"rho_ma": 2.65, "table": {"a": 1}})])
    assert R.snapshot(inv) == {"curves": {"PHIE": {"source": "computed", "unit": "v/v", "step": "porosity"},
                                          "GR": {"source": "input", "unit": "API", "step": ""}},
                               "steps": [{"step": "porosity", "method": "density", "inputs": ["RHOB"],
                                          "outputs": ["PHIE"], "parameters": {"rho_ma": 2.65}}]}
    json.dumps(R.snapshot(inv))                                    # plain data: it goes in the session log


class Stated(Model):
    """The scripted model, with a writer that states the first decimal number of its last result."""

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
        if stage.startswith("writer"):
            self.sent.append({"stage": stage, "messages": json.loads(json.dumps(messages))})
            usage.log.append({"stage": stage, "prompt_tokens": 1})
            results = messages[-1]["content"].split("RESULTS (everything", 1)[1].split("WHAT THE CURVES ARE", 1)[0]
            last = results.rsplit("\n[E", 1)[-1]
            self.number = re.search(r"(?<![\w.])\d+\.\d{3,}(?![\w.])", last).group(0)
            return f"The zones are alike: the value {self.number} stands for them.\n"
        return super().chat(stage, messages, usage, max_tokens, json_schema, temperature, retry)


@pytest.fixture
def conversation(formation, tmp_path):  # noqa: F811
    from petroharness.session import Conversation
    llm = Stated(first_steps() + later_steps())
    c = Conversation.on_tasks(tmp_path / "s", "k2-horizon-7b", llm_factory=lambda cfg: llm, max_steps=4)
    c.ask_task(formation)
    first = llm.number
    two = c.ask_task(formation.model_copy(update={"task_id": "second", "question": Q2}))
    assert two.status == "ok", two.trace.get("error")
    return c, first, llm.number


@pytest.mark.data
def test_an_answers_numbers_are_linked_to_the_results_that_show_them(conversation):
    c, first, second = conversation
    shown = c.turns[0]["shows"]
    assert first in shown and "E2" in shown[first]                 # the number the answer states, and its result
    assert set(c.turns[1]["shows"][second]) >= {"E3"}
    items = c.live.ledger.items
    assert set(links.shows(f"It is {first}.", items)[first]) >= set(shown[first])   # the later result may show it too
    assert links.shows("It is 987654.321, and 7 zones.", items) == {}   # a number no result shows; a small count


@pytest.mark.data
def test_the_graph_is_rebuilt_from_the_log_alone_and_twice_the_same(conversation):
    c, first, second = conversation
    g = EvidenceGraph.from_log(c.folder)
    assert g.to_json() == EvidenceGraph.from_log(c.folder).to_json()
    kinds = {}
    for v in g.nodes.values():
        kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
    assert kinds["question"] == kinds["answer"] == 2 and kinds["result"] == 3 and kinds["claim"] == 2
    assert kinds["curve"] > 5 and kinds["step"] > 2 and "las" not in g.nodes     # prepared tasks: no LAS file named
    assert g.out("Q1", "opened") == ["E1", "E2"] and g.out("Q2", "opened") == ["E3"]
    assert g.out("Q2", "answered_by") == ["A2"] and g.out("A1", "states") == ["C1.1"]
    assert g.nodes["C1.1"]["text"] == CLAIM1 and g.out("C1.1", "cites") == ["E2"]
    assert g.out("C2.1", "cites") == ["E2", "E3"]                   # a later claim cites an earlier question's result
    assert "curve:PHIE" in g.out("E2", "reads") and "curve:VCL" in g.out("E3", "reads")
    step = c.live.f.inv.curves["PHIE"].step
    assert g.out("curve:PHIE", "computed_by") == [f"step:{step}"] and g.nodes[f"step:{step}"]["method"]
    assert any(x["kind"] == "shows" and x["from"] == "A1" and x["to"] == "E2" and first in x["numbers"] for x in g.links)
    # the trail of the second answer reaches the first question's result, the curves and their steps
    t = g.trail(2)
    ids = [r["id"] for r in t["results"]]
    assert t["question"]["text"] == Q2 and ids[:2] == ["E2", "E3"]   # the cited results first, then others showing a number
    assert {r["id"]: r["question"] for r in t["results"]}.items() >= {"E2": 1, "E3": 2}.items()
    named = {x["name"] for x in t["curves"] if x["named"]}
    assert {"PHIE", "VCL"} <= named and len(t["curves"]) > len(named)             # and the curves those were computed from
    assert step in [s["step"] for s in t["steps"]] and all("parameters" in s for s in t["steps"])
    with pytest.raises(KeyError, match="question 9 has no answer"):
        g.trail(9)
    # resuming adds an event and changes nothing in the graph
    from petroharness.session import Conversation
    before = g.to_json()
    Conversation.resume(c.folder, key="k2-horizon-7b", llm_factory=lambda cfg: Model([]))
    assert EvidenceGraph.from_log(c.folder).to_json() == before


@pytest.mark.data
def test_the_audit_trail_is_written_from_the_session_folder(conversation, tmp_path, capsys):
    c, first, second = conversation
    text = audit.markdown(EvidenceGraph.from_log(c.folder), 1)
    for part in ("# Audit trail: question 1", f"**Question:** {Q1}", "## Claims and the results they cite",
                 f"1. {CLAIM1} (moderate): E2", f"| {first} | ", "## Results", "| E2 | question 1 | `stats(",
                 "## Curves", "| PHIE | ", "## Steps Petrophys ran", "## Source"):
        assert part in text, part
    out = tmp_path / "audit.md"
    assert audit.main([str(c.folder), "--out", str(out)]) == 0
    both = out.read_text()
    assert "# Audit trail: question 1" in both and "# Audit trail: question 2" in both
    assert audit.main([str(c.folder), "--question", "2", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["question"]["n"] == 2
    assert audit.main([str(c.folder), "--question", "9"]) == 2 and "no answer" in capsys.readouterr().err
    assert audit.main([str(tmp_path / "nowhere")]) == 2
    # the conversation as one document: each question with its answer, then the audit trails
    from petroharness.evidence import report
    doc = report.markdown(c.folder)
    for part in ("# Conversation report: prepared tasks", "- **Questions:** 2 answered of 2 asked", f"## Question 1: {Q1}",
                 f"## Question 2: {Q2}", "#### Methods and parameters this answer rests on", "# Audit trails",
                 "## Audit trail: question 2", f"The zones are alike: the value {second} stands for them."):
        assert part in doc, part
    assert report.main([str(c.folder)]) == 0 and (c.folder / "report.md").read_text() == doc
    assert capsys.readouterr().out.strip() == str(c.folder / "report.md")
    assert report.main([str(tmp_path / "nowhere")]) == 2


def test_the_links_read_numbers_as_the_checker_does():
    """links.shows leaves out what the checker leaves out: the well's name, the checks' ignore patterns and small
    counts below the checks' threshold."""
    from types import SimpleNamespace as NS
    items = [NS(id="E1", text="PHIE mean 0.2123; 15 samples; run 4500", numbers=["0.2123", "15", "4500"])]
    assert links.shows("Well 15/9-23 has PHIE 0.2123.", items, wells=("15/9-23",)) == {"0.2123": ["E1"]}
    assert "15" not in links.shows("Well 15/9-23.", items, wells=("15/9-23",))
    assert links.shows("It has 15 samples.", items, {"numbers": {"skip_integers_below": 10}}) == {"15": ["E1"]}
    assert links.shows("It has 15 samples.", items, {"numbers": {"skip_integers_below": 20}}) == {}
    assert links.shows("Run 4500 of PHIE 0.2123.", items, {"numbers": {"ignore": [r"Run \d+"]}}) == {"0.2123": ["E1"]}
