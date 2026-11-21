"""The writer reads the question's points, every result the investigation opened and the provenance card of the curves
those name (docs/ARCHITECTURE.md, "The answer"); the tools give a class run's rock and a difference's size; the data's
settings set the statistics' bases and the reporting conventions (docs/BENCHMARK.md).

    .venv/bin/python -m pytest tests/agent/test_writer_evidence.py -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness.agent import components as C  # noqa: E402
from petroharness.agent import writer as W  # noqa: E402

QUESTION = "Where is porosity highest in the formation?"
CLAIM = "Porosity is uniform: no zone stands out"


class Stub:
    """A model by stage: READ, the step replies in order, settle, and the writer (which writes a number a result shows
    and one no result shows); every call is recorded."""

    def __init__(self, steps):
        self.steps, self.sent = list(steps), []

    def replays_reasoning(self):
        return True

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
        self.sent.append({"stage": stage, "messages": messages})
        usage.log.append({"stage": stage, "prompt_tokens": sum(len(m["content"]) for m in messages) // 4})
        if stage.startswith("read"):
            r = {"topics": ["porosity"], "named": ["porosity"]}
        elif stage.startswith("step_"):
            r = self.steps.pop(0) if self.steps else {"edits": [], "next": [], "done": True}
            r = r(messages) if callable(r) else r
        elif stage.startswith("settle"):
            r = {"edits": [], "done": True}
        else:
            r = "## Answer\nPorosity is highest in the upper zone, 0.987654 v/v.\n\n{{ZONE_TABLE}}"
        return r if isinstance(r, str) else json.dumps(r)

    def calls(self, stage):
        return [c for c in self.sent if c["stage"].startswith(stage)]


def _formation():
    from test_b2_tools import F
    got = next(((t, f) for t, f in F() if "PHIE" in f.inv.curves and len(f.view.zones) >= 2), None)
    if got is None:
        pytest.skip("no formation with PHIE and two zones")
    return got


def _run(monkeypatch, conventions=()):
    from petroharness.agent import graph
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.loop import Session
    from petroharness.agent.map import render
    t, f = _formation()
    t = t.model_copy(update={"question": QUESTION})
    monkeypatch.setattr(f.view, "conventions", list(conventions))
    s = Session(t, f, render(f.inv), Ledger(f))
    monkeypatch.setattr(Session, "build", classmethod(lambda cls, task, cfg: s))
    steps = [{"points": [QUESTION], "intent": "locate", "focus": "porosity",
              "edits": [{"op": "add", "point": 1, "text": CLAIM, "grade": "hypothesis"}],
              "next": [{"stats": {"curves": ["PHIE"]}}], "done": False},
             lambda messages: {"edits": [{"op": "revise", "id": "C1", "text": CLAIM, "ev": ["E1"], "grade": "moderate",
                                          "means": "the zones share one porosity level"}], "next": [], "done": True}]
    llm = Stub(steps)
    out = graph.answer(t, "k2-horizon-7b", 1, 4, "open", "profile", llm_factory=lambda cfg: llm)
    assert not out["trace"].get("error"), out["trace"].get("traceback")
    return s, llm, out


# --- the writer ---------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_the_writer_reads_the_points_every_opened_result_and_the_card(monkeypatch):
    s, llm, out = _run(monkeypatch)
    w = llm.calls("writer")[0]["messages"]
    system, user = w[0]["content"], w[-1]["content"]
    assert system.startswith(C.prompt("C9", "write")) and system.endswith("\n" + C.text("C9", "points_rule"))
    assert (W.TABLE_RULE in system) == bool(out["trace"].get("zone_table"))       # the zone table once
    assert user.startswith(f"QUESTION:\n{QUESTION}\n\nTHE QUESTION'S POINTS (the answer covers each):\nPoint 1: {QUESTION}\n\n")
    assert CLAIM not in user and "YOUR CLAIMS" not in user           # the results, not the investigation's readings
    assert "LIMITS THE INVESTIGATION FOUND" not in user              # the settled claim names no limit: no block
    for e in s.ledger.items:                                         # every opened result, whole
        assert f"[{e.id}] {e.text}" in user
    assert "WHAT THE CURVES ARE" in user and "- PHIE" in s.card and s.card in user
    assert "THIS DATA'S REPORTING CONVENTIONS" not in user           # none set: nothing shown


@pytest.mark.data
def test_the_checker_checks_the_answer_against_the_results(monkeypatch):
    s, llm, out = _run(monkeypatch)
    first = out["trace"]["verify_rounds"][0]
    assert "0.987654" in first["unsupported"]                       # a number no result shows goes back for repair
    assert llm.calls("repair_")                                     # and the repair is asked of the same writer


def test_the_results_are_cut_at_the_budget():
    from types import SimpleNamespace as NS
    items = [NS(id=f"E{i}", text="x" * 1000) for i in range(1, 80)]
    view = NS(reg=NS(shape_for=lambda intent: "direct_value"), policy=None, conventions=[])
    s = NS(f=NS(view=view, inv=NS(curves={})), intent="quantify", ledger=NS(items=items), claims=NS(points=[], claims={}),
           map="MAP", task=NS(question="How porous is it?", well="W"), card="")
    from unittest import mock
    with mock.patch.object(W, "claims_block", lambda c, confidence=False: ""), \
            mock.patch.object(W.vocabulary, "note", lambda s: ""), mock.patch.object(W, "curve_card", lambda s: ""):
        system, user, table, shape = W.prompt(s, fmt="default")
    body = user.split("RESULTS (everything the investigation computed, by id):\n", 1)[1].split("\n\nWHAT THE CURVES")[0]
    assert body.endswith("\n... (cut)") and len(body) == W.RESULTS_CHARS + len("\n... (cut)")
    assert table == "" and shape == "direct_value"


def test_the_writer_text_names_no_benchmark_and_states_no_conclusion():
    text = C.prompt("C9", "write").lower()
    for word in ("benchmark", "judge", "reference answer", "ground truth"):
        assert word not in text
    assert "never as none" in text and "candidate until" in text and "limitations" in text


# --- the tools: a class run's rock, a difference's size ------------------------------------------------------------------

@pytest.mark.data
def test_each_class_run_names_its_zone_s_lithology():
    from petroharness.agent import tools
    t, f = _formation()
    z = f.view.zones[0]
    assert tools._zone_cells(f, [(z.zone_id, z.top, z.top)]).startswith(f"{z.zone_id} ({z.lithology}) ")


@pytest.mark.data
def test_a_comparison_gives_the_mean_difference_against_its_spread():
    from petroharness.agent import tools
    t, f = _formation()
    pair = next(((a, b) for a, b in (("PHIE", "PHIT"), ("PHIE", "PHID"), ("PHID", "PHIN")) if a in f.inv.curves
                 and b in f.inv.curves), None)
    if pair is None:
        pytest.skip("no two porosity curves on one scale")
    text = tools.compare(f, *pair).text
    assert "mean / sd" in text


# --- the provenance card -------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_the_provenance_card_states_limits_and_constants_from_the_values():
    from petroharness.agent import engine as E
    from test_b2_tools import F
    for t, f in F():
        card = E.provenance(f, list(f.inv.curves)[:40])
        if "a limit or a default value" in card or "constant:" in card:
            line = next(ln for ln in card.splitlines() if "a limit or a default value" in ln or "constant:" in ln)
            assert line.startswith("- ") and " = " in line
            return
    pytest.skip("no formation with a curve held at a limit")


# --- the data's settings: the statistics' bases, the reporting conventions -----------------------------------------------

def test_the_basis_setting_is_the_data_s_and_defaults_to_all():
    from petroharness.config import DataPaths
    assert DataPaths(las_dir="/x").basis == "all" and DataPaths(las_dir="/x").conventions == []
    assert DataPaths(las_dir="/x", basis="zones").basis == "zones"
    with pytest.raises(Exception):
        DataPaths(las_dir="/x", basis="whole")


@pytest.mark.data
def test_the_zones_basis_leaves_the_whole_interval_out_of_the_tools_only(monkeypatch):
    from petroharness.agent import engine as E
    from petroharness.agent import tools
    from petroharness.well import summary as S
    from test_b2_tools import F
    got = next(((t, f) for t, f in F() if S.outside(f.view) > 0 and "GR" in f.inv.curves), None)
    if got is None:
        pytest.skip("no formation with samples outside the zones")
    t, f = got
    assert [b.kind for b in E.bases(f)][-1] == "whole"
    monkeypatch.setattr(f.view, "basis", "zones")
    assert "whole" not in [b.kind for b in E.bases(f)]
    assert [b.kind for b in S.bases(f.view)][-1] == "whole"           # the record's computations keep all three
    assert "whole interval (" not in tools.stats(f, ["GR"]).text


def test_the_conventions_are_shown_only_when_set():
    from types import SimpleNamespace as NS
    assert W.conventions_block(NS(f=NS(view=NS(conventions=[])))) == ""
    block = W.conventions_block(NS(f=NS(view=NS(conventions=["Units are reported per zone."]))))
    assert block.startswith("THIS DATA'S REPORTING CONVENTIONS") and "- Units are reported per zone." in block


@pytest.mark.data
def test_the_conventions_reach_the_investigation_and_the_writer(monkeypatch):
    _, llm, _ = _run(monkeypatch, conventions=["Units are reported per zone."])
    step = llm.calls("step_1")[0]["messages"][-1]["content"]
    writer = llm.calls("writer")[0]["messages"][-1]["content"]
    assert "- Units are reported per zone." in step and "- Units are reported per zone." in writer
