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

PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def session():
    from test_b2_tools import F as formations
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.loop import Session
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
    assert F.kind_of("create_pickett_plot") == "pickett" and F.kind_of("create_nd_crossplot") == "nd"
    assert F.summary("create_buckles_plot").startswith("Buckles plot")       # Petrophys' own words


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
    kw, curves, said = F.bind(f, "create_pickett_plot")
    assert kw == {"rw": 0.05, "phie_curve": "PHIE", "rt_curve": "RDEP", "m": 1.8, "n": 2.0} and curves == ["PHIE", "RDEP"]
    assert said == ["rw 0.05 (median of RW over the interval)", "a 1 (Petrophys' default)", "m 1.8 (record, saturation)",
                    "n 2 (record, saturation)"]
    assert F.bind(f, "create_buckles_plot")[:2] == ({"phie_curve": "PHIE", "sw_curve": "SW"}, ["PHIE", "SW"])
    assert F.bind(f, "create_nd_crossplot") is None                           # no neutron or density here
    no_rw = fake({"PHIE": x, "RDEP": x}, {"rw": 0.08})
    assert F.bind(no_rw, "create_pickett_plot")[2][0] == "rw 0.08 (record, saturation)"
    assert F.bind(fake({"PHIE": x, "RDEP": x}, {}), "create_pickett_plot") is None   # rw has no default: not offered
    assert F.bind(fake({"PHIE": x}, {"rw": 0.08}), "create_pickett_plot") is None    # no resistivity
    arrays = F.bind(fake({"PHIE": x, "PERM": x * 100}, {}), "create_flow_unit_plot")
    assert set(arrays[0]) == {"phi_e", "perm"} and arrays[1] == ["PHIE", "PERM"]
    empty = fake({"PHIE": x, "SW": np.full(5, np.nan)}, {})
    assert F.bind(empty, "create_buckles_plot") is None                       # a curve with no values is not held


def test_the_choice_is_read_in_order_and_ids_not_offered_are_dropped():
    cands = [F.Candidate(f"F{i}", "histogram", "E1", f"t{i}") for i in range(1, 6)]
    pick = lambda text: [c.id for c in F.chosen(text, cands)]
    assert pick('{"figures": ["F2", "F1"]}') == ["F2", "F1"]
    assert pick('Here: {"figures": ["F9", "f3", "F3", {"id": "F4"}, "F1", "F2"]}') == ["F3", "F4", "F1"]   # at most 3
    assert pick('["F5"]') == ["F5"] and pick('{"figures": []}') == [] and pick("") == [] and pick("none") == []
    assert pick("I would show F2 and F4 {broken") == ["F2", "F4"]


class OneReply:
    def __init__(self, *replies, cap=None):
        self.replies, self.sent, self.asked = list(replies), [], []
        if cap:
            self.cfg = NS(model=NS(max_tokens_spec=cap))

    def chat(self, stage, messages, usage, max_tokens, **kw):
        self.sent.append((stage, messages))
        self.asked.append((stage, max_tokens, kw))
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def test_the_choice_is_asked_on_a_steps_allowance_with_the_offered_ids_and_once_more_when_empty():
    cands = [F.Candidate(f"F{i}", "histogram", "E1", f"t{i}") for i in range(1, 3)] \
        + [F.Candidate("F3", "pickett", "interval", "t3", {"function": "create_pickett_plot"})]
    llm = OneReply("", '{"figures": ["F3"]}', cap=32768)
    assert [c.id for c in F.pick(llm, None, "q", "a", cands)] == ["F3"]
    (s1, cap1, kw1), (s2, cap2, kw2) = llm.asked
    assert (s1, s2) == ("figures", "figures_retry") and cap1 == cap2 == 32768 and kw2["retry"] is True
    assert kw1["json_schema"] == {"type": "object", "required": ["figures"], "properties": {"figures": {
        "type": "array", "items": {"enum": ["F1", "F2", "F3"]}, "maxItems": F.MAX_FIGURES}}}
    listing = llm.sent[0][1][1]["content"].split("CANDIDATE FIGURES:\n")[1]
    assert listing == "F1: t1 (from result E1)\nF2: t2 (from result E1)\nF3: t3 (a standard display of the interval)"
    assert C.owners("figures_retry", 2) == C.owners("figures", 2) == ["C9", "C9"]
    silent = OneReply("")                                          # a model that never replies: None, said by attach
    assert F.pick(silent, None, "q", "a", cands) is None and [a[1] for a in silent.asked] == [3000, 3000]
    assert F.pick(OneReply('{"figures": []}'), None, "q", "a", cands) == [] and F.pick(silent, None, "q", "a", []) == []


@pytest.mark.data
def test_attach_asks_once_petrophys_draws_the_chosen_and_the_captions_say_so(session, tmp_path):
    cands = F.candidates(session, ["E1", "E2"])
    buckles = next(c.id for c in cands if c.kind == "buckles")
    llm = OneReply(json_reply := f'{{"figures": ["F4", "F1", "{buckles}"]}}')
    rec = F.attach(session, "How does SW relate to PHIE?", "SW falls as PHIE rises.", ["E1", "E2"], llm, None,
                   tmp_path / "figures")
    (stage, messages), = llm.sent
    assert stage == "figures" and messages[0]["content"] == C.text("C9", "figures") and json_reply
    user = messages[1]["content"]
    assert user.startswith("QUESTION:\nHow does SW relate to PHIE?\n\nTHE ANSWER:\nSW falls as PHIE rises.\n\nCANDIDATE FIGURES:\n")
    assert "F4: Crossplot of SW" in user and "(from result E2)" in user and "(a standard display of the interval)" in user
    assert rec["chosen"] == ["F4", "F1", buckles] and not rec["errors"]
    assert [g["source"] for g in rec["figures"]] == ["E2", "E1", "interval"]
    ends = ["Drawn by Petrophys (create_crossplot) from result E2.",
            "Drawn by Petrophys (create_histogram_comparison) from result E1.",
            "Drawn by Petrophys (create_buckles_plot) from the interval's curves."]
    for n, (g, end) in enumerate(zip(rec["figures"], ends), 1):
        assert (tmp_path / g["file"]).read_bytes().startswith(PNG)
        assert g["caption"].startswith(f"Figure {n}. ") and g["caption"].endswith(end)
        assert f"; {g['samples']} samples." in g["caption"]
    assert [Path(g["file"]).name for g in rec["figures"]] == ["figure_1_crossplot.png", "figure_2_histogram.png",
                                                              "figure_3_buckles.png"]
    md = F.markdown(rec["figures"])
    assert md.startswith("\n\n## Figures\n\n![Figure 1. Crossplot of SW") and "(figures/figure_1_crossplot.png)" in md
    assert F.markdown([]) == ""
    none = F.attach(session, "q", "a", [], OneReply("{}"), None, tmp_path / "none")
    assert none["candidates"] == [] and none["figures"] == [] and not (tmp_path / "none").exists()
    unread = F.attach(session, "q", "a", ["E1"], OneReply(""), None, tmp_path / "unread")
    assert unread["figures"] == [] and unread["errors"] == ["the model gave no readable choice of figures"]
