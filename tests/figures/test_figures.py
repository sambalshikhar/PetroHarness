"""Figures for an answer (petroharness.figures): Petrophys draws them. The plots offered from the results and the
interval's standard displays, the model's choice read, what Petrophys is given (the interval's well, the zones, the
numbers with their sources), the captions. A real formation, no model.

    .venv/bin/python -m pytest tests/figures -q   (PETROHARNESS_DATA selects the dataset)
"""
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tests" / "agent")]
from petroharness import figures as F  # noqa: E402
from petroharness.agent import components as C  # noqa: E402
from _support.model import ScriptedModel, in_turn  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def session():
    from _support.formations import F as formations
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.state import Session
    from petroharness.agent.map import render
    got = next(((t, f) for t, f in formations() if {"PHIE", "VCL", "SW"} <= set(f.inv.curves) and len(f.view.zones) >= 2),
               None)
    if got is None:
        pytest.skip("no formation with PHIE, VCL, SW and two zones")
    t, f = got
    s = Session(t, f, render(f.inv), Ledger(f))
    for tool, args in (("stats", {"curves": ["PHIE", "SW"]}), ("crossplot", {"y": "SW", "x": "PHIE"}),
                       ("compare", {"a": "PHIE", "b": "VCL"}), ("profile", {"curve": "VCL"}),
                       ("crossplot", {"y": "PHIE", "x": "DEPTH"})):
        s.ledger.open(tool, args)
    return s


def test_the_harness_draws_nothing_itself_and_every_plot_is_a_petrophys_function():
    source = inspect.getsource(F)
    for call in ("subplots(", ".hist(", ".scatter(", ".plot(", "savefig(", "add_subplot(", "Figure("):
        assert call not in source, f"{call}: WHY: Petrophys draws. FIX: use or add the plot in petrophys.visualization."
    for function in list(F.FUNCTIONS.values()) + list(F.DISPLAYS):
        assert callable(F._function(function)), function
    for function in F.DISPLAYS:
        assert F.summary(function) and F.kind_of(function).replace("_", "").isalpha(), function
    assert F.kind_of("pickett_plot") == "pickett" and F.kind_of("nd_plot") == "nd"
    assert F.kind_of("zone_flags_plot") == "zone_flags" and F.kind_of("triple_combo") == "triple_combo"
    assert F.summary("buckles_plot").startswith("Buckles plot")              # Petrophys' own words


@pytest.mark.data
def test_each_result_gives_its_plots_then_the_standard_displays_of_the_same_curves(session):
    ids = [e.id for e in session.ledger.items]
    cands = F.candidates(session, ids)
    results = [c for c in cands if c.source != "interval"]
    assert [(c.id, c.kind, c.source) for c in results] == [
        ("F1", "histogram", "E1"), ("F2", "histogram", "E1"), ("F3", "log_viewer", "E1"), ("F4", "crossplot", "E2"),
        ("F5", "crossplot", "E3"), ("F6", "log_viewer", "E4")]      # E5's log display of PHIE is in F3 already
    assert results[0].title.startswith("Histogram of PHIE") and "all zones" in results[0].title
    assert results[3].spec["line"] == "fit" and results[4].spec["line"] == "one"   # PHIE and VCL are on one scale
    f = session.f
    other = next(c for c in ("PERM", "RDEP", "GR", "RHOB") if c in f.inv.curves and f.inv.curves[c].unit != f.inv.curves["PHIE"].unit)
    (_, title, spec), = F.forms(f, NS(tool="compare", args={"a": other, "b": "PHIE"}))
    assert spec["line"] is None and "1:1" not in title              # two scales: no 1:1 line to read against
    s2 = NS(f=f, ledger=NS(by_id={"A": NS(id="A", tool="compare", args={"a": "SW", "b": "PHIE"}, call_text=lambda: "compare SW PHIE"),
                                  "B": session.ledger.by_id("E2")}.get))
    pairs = [c for c in F.candidates(s2, ["A", "B"]) if c.kind == "crossplot"]
    assert len(pairs) == 1 and pairs[0].spec["line"] in ("one", "fit")   # one crossplot of a pair, with a line
    assert F.candidates(session, ["E1", "E1", "E99"])[:3] == cands[:3]       # each plot once; an unknown id is skipped
    assert F.forms(session.f, NS(tool="section", args={"key": "x.y"})) == []
    every = [z.zone_id for z in session.f.view.zones]         # all zones named one by one: the same plots, offered once
    assert F.forms(session.f, NS(tool="stats", args={"curves": ["PHIE"], "zones": every})) == \
        F.forms(session.f, NS(tool="stats", args={"curves": ["PHIE"]}))
    assert F.forms(session.f, NS(tool="stats", args={"curves": ["NO_SUCH_CURVE"]})) == []
    # the standard displays: after the results' plots, each read from curves the results rest on
    shown = cands[len(results):]
    touched = F.behind(session, ids)
    assert {"PHIE", "SW", "VCL"} <= touched
    assert shown and "buckles" in [c.kind for c in shown]                    # PHIE and SW are both read by E1
    for c in shown:
        assert c.source == "interval" and c.spec["function"] in F.DISPLAYS and set(c.spec["curves"]) <= touched, c
        assert c.title.startswith(F.summary(c.spec["function"]))
    assert F.candidates(session, []) == [] and F.candidates(session, ["E99"]) == []


@pytest.mark.data
def test_petrophys_draws_every_candidate_and_no_figure_stays_open(session):
    import matplotlib.pyplot as plt
    for c in F.candidates(session, [e.id for e in session.ledger.items]):
        png, samples = F.draw(session.f, c)
        assert png.startswith(PNG) and len(png) > 5000 and samples > 0, c
    assert plt.get_fignums() == []
    first = F.candidates(session, ["E1"])[0]
    zone = session.f.view.zones[0].zone_id
    one = F.Candidate("F1", "histogram", "E1", "t", {"curve": "PHIE", "zones": [zone], "where": None})
    assert 0 < F.draw(session.f, one)[1] < F.draw(session.f, first)[1]       # one zone: fewer samples than all zones
    low = F.Candidate("F1", "histogram", "E1", "t", {"curve": "PHIE", "zones": None, "where": "PHIE < -5"})
    with pytest.raises(ValueError, match="no values"):
        F.draw(session.f, low)
    assert plt.get_fignums() == []                                           # also after a plot that could not be drawn


@pytest.mark.data
def test_the_well_petrophys_is_given_holds_the_values_the_results_read(session):
    f = session.f
    w = F.plot_well(f, ["PHIE"])
    assert w is not f.view.prep.well and w.n_samples == f.depth.size
    assert np.array_equal(np.asarray(w.get("PHIE").data, dtype=float), np.asarray(f.view.values("PHIE"), dtype=float),
                          equal_nan=True)
    mid = float(np.nanmedian(f.view.values("PHIE")))
    part = F.plot_well(f, ["PHIE"], where=f"PHIE > {mid}")
    kept = np.isfinite(np.asarray(part.get("PHIE").data, dtype=float))
    assert 0 < kept.sum() < np.isfinite(np.asarray(w.get("PHIE").data, dtype=float)).sum()
    assert np.nanmin(np.asarray(part.get("PHIE").data, dtype=float)) > mid
    assert part.get("PHIE").unit == w.get("PHIE").unit                       # the curve keeps its unit
    inside = F.plot_well(f, ["PHIE"], zones=[f.view.zones[0].zone_id], inside=True)
    got = np.isfinite(np.asarray(inside.get("PHIE").data, dtype=float))
    assert got.sum() <= len(f.view.zones[0].indices) and not got[[i for i in range(got.size)
                                                                  if i not in set(f.view.zones[0].indices)]].any()
    table = F.zone_table(f)
    assert list(table.columns) == ["top", "bottom", "lithology"] and len(table) == len(f.view.zones)
    import matplotlib.pyplot as plt
    shown = F.overview(f.view, "the interval")              # the interval as Petrophys displays it, before any question
    assert shown.startswith(PNG) and len(shown) > 20000 and plt.get_fignums() == []
    assert np.isfinite(np.asarray(f.view.prep.well.get("PHIE").data, dtype=float)).sum() > 0   # the workflow's well is untouched


def fake(curves: dict, record: dict):
    """A formation over named curves (values over 5 samples) and one recorded step's parameters."""
    inv = NS(curves={c: NS(unit="") for c in curves},
             methods=[NS(step="saturation", parameters=record)])
    view = NS(available=lambda c: c in curves and bool(np.isfinite(curves[c]).any()), values=lambda c: curves.get(c))
    return NS(inv=inv, view=view)


def test_a_display_takes_its_curves_and_numbers_from_the_interval_each_said_with_its_source():
    x = np.array([0.1, 0.2, 0.3, np.nan, 0.2])
    f = fake({"PHIE": x, "RDEP": x * 10, "RW": np.array([0.04, 0.05, 0.06, 0.05, np.nan]), "SW": x}, {"m": 1.8, "n": 2})
    kw, curves, said = F.bind(f, "pickett_plot")
    assert kw == {"rw": 0.05, "phi": "PHIE", "rt": "RDEP", "m": 1.8, "n": 2.0} and curves == ["PHIE", "RDEP"]
    assert said == ["rw 0.05 (median of RW over the interval)", "a 1 (Petrophys' default)", "m 1.8 (record, saturation)",
                    "n 2 (record, saturation)", "vcl_max 0.15 (Petrophys' default)"]
    assert F.bind(f, "buckles_plot")[:2] == ({"phi": "PHIE", "sw": "SW"}, ["PHIE", "SW"])
    assert F.bind(f, "nd_plot") is None                                       # no neutron or density here
    no_rw = fake({"PHIE": x, "RDEP": x}, {"rw": 0.08})
    assert F.bind(no_rw, "pickett_plot")[2][0] == "rw 0.08 (record, saturation)"
    # no RW curve and no recorded rw: not offered (Petrophys would read rw from the RW curve, and refuse without it)
    assert F.bind(fake({"PHIE": x, "RDEP": x}, {}), "pickett_plot") is None
    assert F.bind(fake({"PHIE": x}, {"rw": 0.08}), "pickett_plot") is None    # no resistivity
    # flow units from the core plugs (Petrophys draws them from a well's plugs), not from the log curves
    assert F.bind(fake({"PHIC": x, "KH_CORE": x * 100}, {}), "flow_unit_plot")[:2] == ({}, ["PHIC", "KH_CORE"])
    assert F.bind(fake({"PHIE": x, "PERM": x * 100}, {}), "flow_unit_plot") is None
    # a parameter that takes a list of curves is given every curve of its entry that holds values
    flags = F.bind(fake({"NET_RES": x, "NET_PAY": x, "NET_ROCK": np.full(5, np.nan)}, {}), "zone_flags_plot")
    assert flags[:2] == ({"flag_curves": ["NET_RES", "NET_PAY"]}, ["NET_RES", "NET_PAY"])
    empty = fake({"PHIE": x, "SW": np.full(5, np.nan)}, {})
    assert F.bind(empty, "buckles_plot") is None                              # a curve with no values is not held


def test_the_choice_is_read_in_order_and_ids_not_offered_are_dropped():
    cands = [F.Candidate(f"F{i}", "histogram", "E1", f"t{i}") for i in range(1, 6)]
    pick = lambda text: [c.id for c in F.chosen(text, cands)]
    assert pick('{"figures": ["F2", "F1"]}') == ["F2", "F1"]
    assert pick('Here: {"figures": ["F9", "f3", "F3", {"id": "F4"}, "F1", "F2"]}') == ["F3", "F4", "F1"]   # at most 3
    assert pick('["F5"]') == ["F5"] and pick('{"figures": []}') == [] and pick("") == [] and pick("none") == []
    assert pick("I would show F2 and F4 {broken") == ["F2", "F4"]


def one_reply(*replies, cap=None) -> ScriptedModel:
    """The replies in turn, the last one for every call after; cap: the card's spec allowance."""
    llm = in_turn(list(replies), then=replies[-1])
    if cap:
        llm.cfg = NS(model=NS(max_tokens_spec=cap))
    return llm


def test_the_choice_is_asked_on_a_steps_allowance_with_the_offered_ids_and_once_more_when_empty():
    cands = [F.Candidate(f"F{i}", "histogram", "E1", f"t{i}") for i in range(1, 3)] \
        + [F.Candidate("F3", "pickett", "interval", "t3", {"function": "pickett_plot"})]
    llm = one_reply("", '{"figures": ["F3"]}', cap=32768)
    assert [c.id for c in F.pick(llm, None, "q", "a", cands)] == ["F3"]
    c1, c2 = llm.sent
    assert llm.stages() == ["figures", "figures_retry"] and c1["max_tokens"] == c2["max_tokens"] == 32768 and c2["retry"] is True
    assert c1["schema"] == {"type": "object", "required": ["figures"], "properties": {"figures": {
        "type": "array", "items": {"enum": ["F1", "F2", "F3"]}, "maxItems": F.MAX_FIGURES}}}
    listing = llm.sent[0]["messages"][1]["content"].split("CANDIDATE FIGURES:\n")[1]
    assert listing == "F1: t1 (from result E1)\nF2: t2 (from result E1)\nF3: t3 (a standard display of the interval)"
    assert C.owners("figures_retry", 2) == C.owners("figures", 2) == ["C9", "C9"]
    silent = one_reply("")                                          # a model that never replies: None, said by attach
    assert F.pick(silent, None, "q", "a", cands) is None and [c["max_tokens"] for c in silent.sent] == [3000, 3000]
    assert F.pick(one_reply('{"figures": []}'), None, "q", "a", cands) == [] and F.pick(silent, None, "q", "a", []) == []


@pytest.mark.data
def test_attach_asks_once_petrophys_draws_the_chosen_and_the_captions_say_so(session, tmp_path):
    cands = F.candidates(session, ["E1", "E2"])
    buckles = next(c.id for c in cands if c.kind == "buckles")
    llm = one_reply(json_reply := f'{{"figures": ["F4", "F1", "{buckles}"]}}')
    rec = F.attach(session, "How does SW relate to PHIE?", "SW falls as PHIE rises.", ["E1", "E2"], llm, None,
                   tmp_path / "figures")
    (call,) = llm.sent
    stage, messages = call["stage"], call["messages"]
    assert stage == "figures" and messages[0]["content"] == C.text("C9", "figures") and json_reply
    user = messages[1]["content"]
    assert user.startswith("QUESTION:\nHow does SW relate to PHIE?\n\nTHE ANSWER:\nSW falls as PHIE rises.\n\nCANDIDATE FIGURES:\n")
    assert "F4: Crossplot of SW" in user and "(from result E2)" in user and "(a standard display of the interval)" in user
    assert rec["chosen"] == ["F4", "F1", buckles] and not rec["errors"]
    assert [g["source"] for g in rec["figures"]] == ["E2", "E1", "interval"]
    ends = ["Drawn by Petrophys (pp.crossplot) from result E2.",
            "Drawn by Petrophys (pp.histograms) from result E1.",
            "Drawn by Petrophys (pp.buckles_plot) from the interval's curves."]
    for n, (g, end) in enumerate(zip(rec["figures"], ends), 1):
        assert (tmp_path / g["file"]).read_bytes().startswith(PNG)
        assert g["caption"].startswith(f"Figure {n}. ") and g["caption"].endswith(end)
        assert f"; {g['samples']} samples." in g["caption"]
    assert [Path(g["file"]).name for g in rec["figures"]] == ["figure_1_crossplot.png", "figure_2_histogram.png",
                                                              "figure_3_buckles.png"]
    md = F.markdown(rec["figures"])
    assert md.startswith("\n\n## Figures\n\n![Figure 1. Crossplot of SW") and "(figures/figure_1_crossplot.png)" in md
    assert F.markdown([]) == ""
    none = F.attach(session, "q", "a", [], one_reply("{}"), None, tmp_path / "none")
    assert none["candidates"] == [] and none["figures"] == [] and not (tmp_path / "none").exists()
    unread = F.attach(session, "q", "a", ["E1"], one_reply(""), None, tmp_path / "unread")
    assert unread["figures"] == [] and unread["errors"] == ["the model gave no readable choice of figures"]


def test_a_list_parameter_and_the_net_flags_display_are_read_as_petrophys_declares_them():
    """A parameter annotated as a list takes every held curve of its entry (Optional[List[str]] too), and the net
    flags are offered where the answer rests on any one of them, as the net-pay display was."""
    import inspect as I
    from typing import List, Optional

    def plot(well, flag_curves: List[str], other: Optional[List[str]] = None, one: str = "x"):
        pass
    ps = I.signature(plot).parameters
    assert F._takes_a_list(ps["flag_curves"]) and F._takes_a_list(ps["other"]) and not F._takes_a_list(ps["one"])
    x = np.array([0.0, 1.0, 1.0, np.nan, 0.0])
    f = fake({"NET_ROCK": x, "NET_RES": x, "NET_PAY": x}, {})
    assert F._rests_on(f, "zone_flags_plot", {"NET_PAY"}) and not F._rests_on(f, "zone_flags_plot", {"PHIE"})
    assert F._rests_on(fake({"PHIE": x, "SW": x}, {}), "buckles_plot", {"PHIE", "SW"})
    assert not F._rests_on(fake({"PHIE": x, "SW": x}, {}), "buckles_plot", {"PHIE"})
    assert "zone_flags_plot" in F.DEPTH_DISPLAYS and "pickett_plot" not in F.DEPTH_DISPLAYS

