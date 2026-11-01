"""The plumbing between the tools, the ledger and the prompts.

- Guides are outside NEW's budget: their own block, whole at the step after they are read, then short. A result
  withheld for the budget comes first at the next step. A call opened before, and get alone, show the result whole.
- get and find read "_" name parts and "|" alternatives, and a miss says what it read.
- Percent arithmetic: the number check recomputes a share's complement; calc shows the order it read.
- A flag computed from an input with no value reads "not computed"; a section whose index was not computed prints no
  thresholds.
- Every analyzer section is named by a guide's Compare list, on each dataset.
- The first look takes each curve's core-calibrated twin.

    PYTHONPATH=src:tests:tests/agent PETROHARNESS_DATA=<geolink.yaml> python -m pytest tests/agent/test_plumbing.py -q
"""
import re
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness.agent import components as C  # noqa: E402
from petroharness.agent import engine as E  # noqa: E402
from petroharness.agent.ledger import Item, Ledger, get_lines, grouping  # noqa: E402
from petroharness.llm import Usage  # noqa: E402


# --- the budget: guides outside NEW, withheld results first at the next step, a repeat shown whole -------------------

def _run(steps: list, max_steps: int, monkeypatch, budget: int = None, guide_chars: int = 0):
    """A short investigation on a real formation with no topics (a guide opens nothing with it); budget: NEW's;
    guide_chars: every guide made this long (a stand-in for the longest researched guides)."""
    from petroharness.agent import loop as L
    from petroharness.agent.loop import investigate
    from test_b5_loop import Script, _session, chose
    s = chose(_session())
    if budget is not None:
        monkeypatch.setattr(L, "NEW_CHARS", budget)
    if guide_chars:
        real = type(s.library).guide
        monkeypatch.setattr(type(s.library), "guide", lambda lib, name, f=None: (real(lib, name, f) + "\n" + "x" * guide_chars)
                            if name in lib.facets else real(lib, name, f))
    first = {"points": ["Where is net pay?"], "intent": "locate", "focus": "where",
             "edits": [{"op": "add", "point": 1, "text": "Pay likely in the upper zones", "grade": "hypothesis"}], "done": False}
    llm, trace = Script([{**first, **steps[0]}] + steps[1:]), {}
    investigate(llm, s, Usage(), 4000, trace, max_steps=max_steps)
    users = {stage: m[-1]["content"] for stage, m in llm.sent}
    return s, users, trace


def _new(user: str) -> str:
    return user.split("\n\nNEW (from step", 1)[1]


def _guides(user: str) -> str:
    return user.split("\nGUIDES (", 1)[1].split("\n\nNEW (from step", 1)[0] if "\nGUIDES (" in user else ""


FIVE = [{"runs": "NET_PAY"}, {"stats": {"curves": ["SW"]}}, {"stats": {"curves": ["PHIE"]}}, {"stats": {"curves": ["VCL"]}},
        {"profile": "SW"}]


@pytest.mark.data
def test_two_long_guides_and_five_results_withhold_no_result_that_fits(monkeypatch):
    """Step 1 reads two guides of 9,000 characters each and opens five results whose texts together fit NEW's budget:
    no result is withheld (the guides' text has its own block, so it never fills NEW's budget). The guides are
    whole in GUIDES at step 2, not in NEW, and short at step 3."""
    from petroharness.agent.loop import coerce_action
    from test_b5_loop import _session, chose
    probe = chose(_session())
    probe.run(("tool", "stats", {"curves": ["VCL", "PHIE", "SW", "PERM"]}))       # as the first look opens E1
    sizes = [len(probe.run(coerce_action(a))[0]) for a in FIVE]
    budget = sum(sizes) + 300                                                     # each fits alone, and all together
    guides = ["porosity", "water_saturation"]
    s, users, trace = _run([{"next": [{"guide": g} for g in guides] + FIVE}, {"edits": [], "next": [], "done": False}],
                           3, monkeypatch, budget=budget, guide_chars=9000)
    rec = trace["steps"][0]
    opened = [e.id for e in s.ledger.items[1:]]
    assert len(opened) == 5 and rec["withheld"] == [] and rec["guides_read"] == guides
    new, block = _new(users["step_2"]), _guides(users["step_2"])
    assert all(f"[{i}] " in new for i in opened) and "GUIDE " not in new and "not shown this step" not in new
    assert rec["new_chars"] <= budget
    for g in guides:                                                              # whole, once, in their own block
        assert f"GUIDE {s.library.guide(g, s.f)}" in block
    short = _guides(users["step_3"])                                              # short after
    assert "x" * 100 not in short
    for g in guides:
        assert C.fill("C6", "guide_short", name=g, calls="; ".join(s.library.calls(g, s.f))) in short


def _one_at_a_time() -> int:
    """A budget that holds either of FIVE[1:3] with the step's notes, and not both."""
    from petroharness.agent.loop import coerce_action
    from test_b5_loop import _session, chose
    probe = chose(_session())
    probe.run(("tool", "stats", {"curves": ["VCL", "PHIE", "SW", "PERM"]}))
    a, b = (len(probe.run(coerce_action(x))[0]) for x in FIVE[1:3])
    if min(a, b) < 700:
        pytest.skip("results too short here to hold one and not two")
    return max(a, b) + 600


@pytest.mark.data
def test_a_withheld_result_comes_first_at_the_next_step(monkeypatch):
    s, users, trace = _run([{"next": FIVE[1:3]}, {"edits": [], "next": [], "done": False}], 3, monkeypatch,
                           budget=_one_at_a_time())
    sw, phie = s.ledger.items[1], s.ledger.items[2]
    assert trace["steps"][0]["withheld"] == [phie.id]
    new2 = _new(users["step_2"])
    assert f"[{sw.id}] " in new2 and f"[{phie.id}] {phie.text}" not in new2
    assert C.text("C8", "withheld") + f"[{phie.id}] {phie.call_text()}" in new2
    assert trace["steps"][1]["carried"] == [phie.id] and f"[{phie.id}] {phie.text}" in _new(users["step_3"])


@pytest.mark.data
def test_before_the_last_step_the_note_says_settle_shows_them(monkeypatch):
    s, users, trace = _run([{"next": FIVE[1:3]}], 2, monkeypatch, budget=_one_at_a_time())
    assert C.text("C8", "withheld_last") in _new(users["step_2"])


@pytest.mark.data
def test_a_repeated_call_and_get_alone_show_the_result_whole(monkeypatch):
    s, users, trace = _run([{"next": [FIVE[1]]}, {"edits": [], "next": [FIVE[1], {"get": "E2"}], "done": False}], 3,
                           monkeypatch)
    item = s.ledger.items[1]
    new = _new(users["step_3"])
    assert len(s.ledger.items) == 2 and f"[{item.id}] (opened before: {item.call_text()}) {item.text}" in new
    assert C.fill("C8", "shown_above", id=item.id) in new                          # once in one NEW
    assert s.run(("get", item.id, ""))[1] is item and s.run(("get", item.id, "Z1"))[1] is None


def test_the_guides_block_owns_its_header():
    assert C.text("C5", "section_owners")["GUIDES (a guide"] == "C6"
    assert C.text("C6", "guides_head").startswith("GUIDES (a guide")


# --- get and find ----------------------------------------------------------------------------------------------------

def _ledger() -> Ledger:
    lines = ["saturation.movability: Saturation analyzer, movability: classes from MHI.",
             "  method: Prefers MHI.",
             "  HIGH_MOVEABLE_HC: 18.8 m, 49.2% of the zoned thickness, 2 intervals; runs: Z1 2500.1-2503.0, Z3 2510.0-2512.5",
             "  MINIMAL_MOVEABLE_HC: 2.1 m, 5.5% of the zoned thickness, 1 intervals; runs: Z2 2505.0-2507.1",
             "  PRIME_OIL_TARGET: 1.2 m, 3.1% of the zoned thickness, 1 intervals; runs: Z1 2501.0-2502.2",
             "  routing: Archie in sands, Indonesia in silts"]
    led = Ledger(None)
    led.items.append(Item("E1", "section", {"key": "saturation.movability"}, "k", [(ln, []) for ln in lines],
                          "\n".join(lines)))
    return led


def test_get_reads_name_parts_and_alternatives():
    led = _ledger()
    item = led.items[0]
    assert get_lines(item, "MOVEABLE") == []                                     # the writer's strict reading stays
    got = led.get("E1", "MOVEABLE")
    assert "HIGH_MOVEABLE_HC: 18.8 m" in got and "MINIMAL_MOVEABLE_HC: 2.1 m" in got and "PRIME_OIL" not in got
    got = led.get("E1", "PRIME_OIL_TARGET|HIGH_MOVEABLE_HC")
    assert "PRIME_OIL_TARGET: 1.2 m" in got and "HIGH_MOVEABLE_HC: 18.8 m" in got and "MINIMAL" not in got
    assert "Indonesia in silts" in led.get("E1", "route|Routing|Archie")
    got = led.get("E1", "MOVEABLE, Z2")                                          # a word and a zone: both
    assert "runs: Z2 2505.0-2507.1" in got and "intervals; runs: none in Z2" in got and "Z1 2500.1" not in got
    assert led.get("E1", "HIGH_MOVEABLE_HC") != led.get("E1", "MOVEABLE")        # a whole name stays that name
    assert "E1 is in" not in led.find("GAS") and led.find("MOVEABLE|TARGET").startswith("MOVEABLE|TARGET is in E1")


def test_a_miss_says_what_it_read_and_the_names_there_are():
    led = _ledger()
    miss = led.get("E1", "NOSUCH|Z9")
    assert miss.startswith("[E1] nothing in E1 matches NOSUCH|Z9 (read as zones Z9; words 'NOSUCH';")
    assert "its names: " in miss and "HIGH_MOVEABLE_HC" in miss.split("its names: ")[1]
    assert led.find("NOSUCH").startswith("no opened item matches NOSUCH (read as words 'NOSUCH';")


def test_a_cut_run_list_is_never_read_as_none():
    """The coordinator's case: a class set in Z1-Z3 whose run list is cut to its thickest runs said "none in Z1, Z2,
    Z3". Runs are read from cut lists, lists over several zones and one zone's runs written without its id."""
    from petroharness.agent.ledger import _class_runs
    head = "  WEAK_GAS_EFFECT: 21.3 m, 39.3% of the zoned thickness, 43 intervals; runs: "
    cut = (head + "thickest 3 of 43: Z2 1924.4-1924.9 (0.5 m), Z3 1950.0-1951.0 (1 m), Z1 1900.0-1900.5 (0.5 m) ... "
           "(every run: condition saturation.gas:WEAK_GAS_EFFECT)")
    got = _class_runs(cut, {"Z1", "Z2", "Z3"})
    assert "none" not in got and all(z in got for z in ("Z1 1900.0", "Z2 1924.4", "Z3 1950.0"))
    assert got.endswith("(the list is cut: more may be in Z1, Z2, Z3; every run: runs saturation.gas:WEAK_GAS_EFFECT)")
    assert _class_runs(cut, {"Z4"}) == head + ("not listed here for Z4 (the list is cut; every run: runs "
                                               "saturation.gas:WEAK_GAS_EFFECT)")
    whole = head + "Z1 1897.0-1917.3, Z2 1917.8-1930.0, Z3 1933.5-1984.2"
    assert _class_runs(whole, {"Z2"}) == head + "Z2 1917.8-1930.0" and _class_runs(whole, {"Z4"}) == head + "none in Z4"
    one = head + "8512.5-8591.0"                                    # one zone's runs carry no zone id
    assert _class_runs(one, {"Z1"}, lambda d: "Z1") == one and _class_runs(one, {"Z2"}, lambda d: "Z1") == head + "none in Z2"
    assert _class_runs(one, {"Z1"}) == head + "not listed here for Z1 (the runs here do not name their zone)"


def test_get_alone_is_the_whole_result():
    led = _ledger()
    item = led.items[0]
    assert led.get("E1", "") == led.get("E1", " , ") == f"[E1] (opened before: {item.call_text()}) {item.text}"


# --- percent arithmetic ------------------------------------------------------------------------------------------------

class _Ev:
    def __init__(self, *values):
        self.values = list(values)

    def render(self) -> str:
        return " ".join(str(v) for v in self.values)


def test_the_number_check_recomputes_a_share_complement():
    from petroharness.agent.checks import number_provenance
    ev = [_Ev(0.8626, 0.9318, 86.3)]
    ok = "About 13.7% of the log data is missing; at the median 6.8%; and 13.7 percent by the shares."
    assert number_provenance(ok, "", ev)[0] == []
    assert number_provenance("A missing share of 42.4% here.", "", ev)[0] == ["42.4%"]
    assert number_provenance("A value of 13.7 here.", "", ev)[0] == ["13.7"]         # a complement only as a percentage


def test_a_claim_with_the_complement_is_not_flagged():
    from petroharness.agent.claims import Claims
    led = Ledger(None)
    led.items.append(Item("E1", "stats", {"curves": ["DATA_COMPLETENESS"]}, "k",
                          [("  zones pooled, DATA_COMPLETENESS: n 40, mean 0.8626", [0.8626])],
                          "  zones pooled, DATA_COMPLETENESS: n 40, mean 0.8626", [0.8626]))
    claims = Claims(["How much data is missing?"], led, "", "How much data is missing?")
    claims.apply([{"op": "add", "point": 1, "text": "About 13.7% of the log data is missing.", "ev": ["E1"],
                   "grade": "moderate", "means": "most of the logs have values in most samples"}])
    assert not [f for f in claims.claims["C1"].flags if f.startswith("K3")]


def test_calc_shows_the_order_it_read():
    led = Ledger(None)
    led.items.append(Item("E1", "stats", {}, "k", [("mean 0.8626", [0.8626])], "mean 0.8626", [0.8626]))
    item, _ = led.calc("1 - 0.8626*100")
    assert item.lines[0] == "calc 1 - 0.8626*100 = -85.26" and item.lines[1] == "  read as: 1 - (0.8626 * 100)"
    item, _ = led.calc("(1 - 0.8626) * 100")
    assert item.lines[0] == "calc (1 - 0.8626) * 100 = 13.74" and not [ln for ln in item.lines if "read as" in ln]
    assert grouping("100 * 12.5 / 150.2") == grouping("78.8 + 58.4 + 11") == grouping("2 + (3 * 4)") == ""
    assert grouping("2 * 3 + 4 / 5") == "(2 * 3) + (4 / 5)" and grouping("sqrt(2) - 1 * 3") == "sqrt(2) - (1 * 3)"


# --- the writer's leak guard -------------------------------------------------------------------------------------------

def test_working_notes_in_the_text_are_found():
    from petroharness.agent.writer import leaks
    text = "Means of -0.06632 (SILT_GROUP_5) and -0.1021 (SIL... wait, SILT_GROUP_20, 3238.2-3322.9 m)."
    got = leaks(text)
    assert len(got) == 1 and "SIL... wait" in got[0]
    assert leaks("Hmm, the PERM values are high. Wait: the zone is thin.") and leaks("scratch that, it is Z3")
    assert leaks("The test waited for the wait time of the tool; no notes here.") == []


DRAFTED = ("We need answer per rules. Need craft the report shape with sections. Must use claims/results only.\n\n"
           "Need ensure numbers with result ids in brackets during drafting.\n\n"
           "Need include the intervals and their lithologies.\n\n"
           "## Formation Overview\n\nThe formation spans 2104.0-2181.0 m.\n\n## Conclusions\n\nShale holds the lowest Rwa.")


def test_the_writers_drafting_left_in_its_reply_is_cut_or_sent_back():
    from petroharness.agent.writer import clean_reply, drafting, leaks
    assert drafting(DRAFTED) == ["We need answer", "Need ensure", "Need include"]
    assert clean_reply(DRAFTED).startswith("## Formation Overview") and "Need" not in clean_reply(DRAFTED)
    body = "## Overview\n\nNeed ensure the units.\nNeed include the zones.\n\n## Conclusions\nDone."
    assert clean_reply(body) == ""                         # notes inside the answer: it is written again ...
    assert leaks(body) == ["Need ensure", "Need include"]   # ... and the checker sends any left back
    prose = ("## Data Limitations\n\nNeed for core data remains: a cored interval would confirm the contact.\n"
             "We need to stress that RXO is absent.")
    assert drafting(prose) == [] and leaks(prose) == [] and clean_reply(prose) == prose    # report prose is no draft


# --- not computed --------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_a_flag_whose_input_has_no_value_is_not_computed(monkeypatch):
    """NET_PAY's record line names SW: where SW has no value (here, made missing in the first zone), NET_PAY is not
    computed, in stats, runs and the writer's zone table, whatever the record holds there."""
    from test_b5_loop import _session, chose
    s = chose(_session())
    f = s.f
    if not E.flag_inputs(f, "NET_PAY"):
        pytest.skip("no record line for NET_PAY here")
    monkeypatch.setitem(f.__dict__, "_uncomputed", {})          # the formation is shared: its masks read anew here
    z = f.view.zones[0]
    real = f.view.values

    def values(c):
        x = real(c)
        if c == "SW" and x is not None:
            x = np.array(x, dtype=float)
            x[np.asarray(z.indices)] = np.nan
        return x
    monkeypatch.setattr(f.view, "values", values)
    gone, why = E.uncomputed(f, "NET_PAY")
    reasons = dict(why)
    assert gone[np.asarray(z.indices)].all() and reasons["SW has no value"][np.asarray(z.indices)].all()
    sw = np.asarray(values("SW"), dtype=float)
    assert np.isfinite(sw[~gone]).all()
    text = s.run(("tool", "stats", {"curves": ["NET_PAY"]}))[0]
    row = re.search(rf"^  {z.zone_id} .*NET_PAY(?: \([^)]*\))?: n 0 of \d+, not computed \((.*)\)$", text, re.M)   # the curve may carry its status tag
    assert row and "SW has no value" in row.group(1).split("; "), text[:800]
    assert all(dict(why)[r][np.asarray(z.indices)].any() for r in row.group(1).split("; "))   # the reasons that hold there
    assert "not computed at " in text.split("\n", 1)[0] and "a default, not a reading" in text.split("\n", 1)[0]
    runs = s.run(("tool", "runs", {"condition": "NET_PAY"}))[0]
    assert "inside the zones (" in runs.split("\n", 1)[0] and "; NET_PAY not computed at " in runs.split("\n", 1)[0]
    assert E.uncomputed(f, "SW")[1] == [] and not E.uncomputed(f, "SW")[0].any()             # values: never
    if "PRIME_OIL_TARGET" in f.inv.curves and ["NET_PAY"] in E.flag_inputs(f, "PRIME_OIL_TARGET"):
        assert E.uncomputed(f, "PRIME_OIL_TARGET")[0][np.asarray(z.indices)].all()


@pytest.mark.data
def test_a_section_whose_index_was_not_computed_prints_no_thresholds():
    """On the formations of the configured dataset: a section whose every class says not assessed and whose method
    names a curve with no value here prints why in place of its thresholds; every other section prints them as
    recorded."""
    from test_b2_tools import F
    seen = kept = 0
    for i, (t, f) in enumerate(F()):
        for sec in f.inv.sections:
            why = E.index_not_computed(f, sec) if sec.thresholds else ""
            if not sec.thresholds or (not why and i >= 3):          # every dropped line; the kept ones on three formations
                continue
            text = _section(f, sec.key)
            if why:
                assert f"  thresholds: none apply here ({why})" in text and sec.thresholds not in text, (t.well, sec.key)
                seen += 1
            else:
                assert f"  thresholds (as recorded): {sec.thresholds}" in text, (t.well, sec.key)
                kept += 1
    assert seen and kept


def _section(f, key):
    from petroharness.agent.tools import section
    return section(f, key).text


# --- every analyzer section reachable, flags not computed, and calibrated twins on each dataset --------------------------

def _datasets():
    from test_b4_direction import _dataset_configs
    return _dataset_configs()


@pytest.mark.data
@pytest.mark.parametrize("config", _datasets(), ids=lambda p: p.stem)
def test_on_each_dataset_every_section_is_reachable_and_flags_and_twins_read_right(config):
    """Every analyzer section of every formation is named by a guide's Compare list; a flag whose input has no value
    anywhere in the interval reads "not computed" in every zone row of stats; each calibrated twin is a
    core-calibrated curve X_CC with its own values beside X."""
    from petroharness.agent import direction
    from petroharness.agent.inventory import calibrated_twins
    from test_b4_direction import _formations
    lib = direction.plugged()
    listed = {e.split()[1] for g in lib.facets.values() for shown, e in map(direction.gated, g.get("compare") or [])
              if shown and e.startswith("section ")}
    keys, flags_seen = set(), 0
    for t, f in _formations(config):
        keys |= {s.key for s in f.inv.sections}
        for c in f.inv.curves:
            gone, why = E.uncomputed(f, c)
            if why and gone.all():
                text = _stats(f, c)
                rows = [ln for ln in text.splitlines() if re.match(rf"  Z\d+ .*, {c}(?: \([^)]*\))?: ", ln)]   # its status tag
                assert rows and all("not computed (" in ln for ln in rows), (t.well, c, text[:400])
                flags_seen += 1
        for base, twin in calibrated_twins(f.inv).items():
            ranks = {r.curve: r for rs in f.inv.properties.values() for r in rs}
            assert twin == base + "_CC" and ranks[twin].rank == 2 and not f.inv.curves[twin].copy_of, (t.well, twin)
            a, b = (np.asarray(f.view.values(x), dtype=float) for x in (base, twin))
            assert not np.array_equal(a, b, equal_nan=True), (t.well, base, twin)
    assert keys and not keys - listed, sorted(keys - listed)


def _stats(f, c):
    from petroharness.agent.tools import stats
    return stats(f, [c]).text


@pytest.mark.data
def test_the_first_look_takes_each_curves_calibrated_twin():
    """Where the record holds X and its core-calibrated X_CC, the first look's stats hold both, X_CC right after X,
    whatever topics were chosen."""
    from petroharness.agent.inventory import calibrated_twins
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.loop import Session, investigate
    from petroharness.agent.map import render
    from test_b2_tools import F
    from test_b5_loop import Script, chose
    hit = next(((t, f) for t, f in F() if calibrated_twins(f.inv)), None)
    if hit is None:
        pytest.skip("no core-calibrated twin in this dataset's formations")
    t, f = hit
    s = chose(Session(t, f, render(f.inv), Ledger(f)), "hydrocarbon_detection")
    trace = {}
    investigate(Script([{"points": ["p"], "intent": "characterize", "edits": [], "next": [], "done": True}]), s, Usage(),
                4000, trace, max_steps=1)
    curves = s.ledger.items[0].args["curves"]
    for base, twin in calibrated_twins(f.inv).items():
        if base in curves:
            assert curves[curves.index(base) + 1] == twin, curves
