"""The writer, offline: what the writer's prompt must hold, the open variant's rules, the repair
rounds under a scripted model, and the replay's rebuild on saved traces (no K2H).

    .venv/bin/python -m pytest tests/agent/test_b7_writer.py -q   (PETROHARNESS_DATA selects the dataset)
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness.llm import Usage  # noqa: E402
from petroharness.agent import writer  # noqa: E402
from petroharness.agent.claims import Claim  # noqa: E402
from petroharness.agent.writer import OPEN_RULES, RULES, _OPEN_DROP, claims_block, opened_results, prompt  # noqa: E402

MEANS = "so the zone holds the formation's hydrocarbon-bearing rock"


# --- hand-written ---------------------------------------------------------------------------------------------------

def test_each_dropped_rule_names_exactly_one_rule():
    for head in _OPEN_DROP:
        assert sum(r.startswith(head) for r in RULES) == 1, head


def test_open_rules_cap_no_length_and_keep_traceability():
    rules = [r for r in RULES if not r.startswith(_OPEN_DROP)] + OPEN_RULES
    text = " ".join(rules)
    assert not re.search(r"\d+\s*(?:-\s*\d+\s*)?words", text) and "Respect the length" not in text
    assert any(r.startswith("Use only numbers") for r in rules)            # every number still traces


class _Claims:
    def __init__(self, points, claims):
        self.points, self.claims = points, {c.id: c for c in claims}


def _claim(cid, point, text, grade="moderate", flags=(), ev=("E1",), weak=""):
    return Claim(cid, point, text, MEANS, list(ev), grade, weak, list(flags), [])


def test_claims_block_shows_settled_claims_marks_unverified_and_hides_hypotheses():
    c = _Claims(["Where is pay?", "How thick?", "Which fluid?"], [
        _claim("C1", 1, "Pay is in Z2", "high"),
        _claim("C2", 2, "Net pay is 12.5 m", flags=["K3 12.5 (no result shows it)"]),
        _claim("C3", 3, "Gas is likely", "hypothesis")])
    plain, conf = claims_block(c), claims_block(c, confidence=True)
    assert "[C1] Pay is in Z2 | grade: high |" in plain and "grade: high confidence" in conf
    assert "unverified, do not state: 12.5" in plain
    assert "Gas is likely" not in plain and "Point 3: Which fluid?\n  (not settled by the investigation)" in plain


K3_REAL = ("K3 0.796 is in E7; 0.810 is in E7, E8; 0.797 in no opened item (cite the item a number comes from and write "
           "it as shown; a value no item shows is computed or recalled: compute it with calc and cite the result, or drop it)")


@pytest.mark.parametrize("flag, held, none", [
    (K3_REAL, {"0.796": ["E7"], "0.810": ["E7", "E8"]}, ["0.797"]),
    ("K3 24, 190 in no opened item (cite the item ...)", {}, ["24", "190"]),
    ("K3 58.51% is in E14 (cite the item ...)", {"58.51%": ["E14"]}, []),
    ("K3 12.5 (no result shows it)", {}, ["12.5"]),                        # unread wording stays unverified
    ("K4 high confidence needs two lines of evidence", {}, []),
])
def test_k3_split(flag, held, none):
    assert writer.k3_split(_claim("C1", 1, "x", flags=[flag])) == (held, none)


def test_claims_block_states_held_numbers_with_their_item_and_withholds_the_rest():
    c = _Claims(["How much BVW?"], [_claim("C1", 1, "BVW 0.796 in Z1, 0.810 in Z2, ratio 0.797", flags=[K3_REAL])])
    on = claims_block(c)
    assert "results: E1; E7 (holds 0.796); E7, E8 (holds 0.810) | unverified, do not state: 0.797" in on


def test_cited_lines_bring_the_lines_that_hold_the_numbers():
    from types import SimpleNamespace as NS
    e7 = NS(id="E7", rows=[("SW [v/v]", []), ("  Z1 SAND: mean 0.7961", [0.7961]), ("  Z2 SAND: mean 0.5", [0.5])],
            call_text=lambda: "stats SW")
    c = _claim("C1", 1, "SW 0.796 in Z1", flags=["K3 0.796 is in E7 (cite the item ...)"], ev=())
    claims = NS(claims={"C1": c}, items={"E7": e7})
    text = writer.cited_lines(claims)
    assert "[E7] stats SW (for C1: holds 0.796)" in text and "Z1 SAND: mean 0.7961" in text and "Z2 SAND" not in text


class _Item:
    def __init__(self, eid, text):
        self.id, self.text = eid, text


class _Ledger:
    def __init__(self, items):
        self.items = items

    def digest(self, e):
        return f"[{e.id}] digest"


def test_opened_results_are_whole_within_the_budget_then_digests():
    """The newest are kept whole first, then older ones, within the budget (no claims cite any here; the cited-first
    order: test_views_and_scope.py)."""
    s = type("S", (), {})()
    s.ledger = _Ledger([_Item("E1", "a" * 50), _Item("E2", "b" * 50), _Item("E3", "c" * 10)])
    out = opened_results(s, budget=100)
    parts = out.split("\n\n")
    assert len(parts) == 3 and parts[2] == "[E3] " + "c" * 10 and sum(p.endswith("digest") for p in parts) >= 1


@pytest.mark.parametrize("text,want", [
    ("Class thresholds are not shown in the opened record.", ["opened record"]),
    ("Contacts were not opened, so none is asserted.", ["not opened"]),
    ("Per the map, Z1-Z6 are limestone groups.", ["the map"]),
    ("The ledger shows SW 0.45 and E3 agrees.", ["The ledger", "E3"]),
    ("NEW results add the gas classes.", ["NEW"]),
    ("A new zone of low SW appears at 7930 ft.", []),
    ("The claim that gas is present rests on the crossover.", []),
    ("Z3 holds the best rock; E-W trending faults are not resolved.", []),
    ("Deep resistivity rises where the hole opened up? No: RDEP is 38 ohm.m.", []),        # 'opened up' is not 'opened'
])
def test_process_words(text, want):
    from petroharness.agent.writer import process_words
    got = process_words(text)
    assert [g.lower() for g in got] == [w.lower() for w in want] or (not want and not got), got


@pytest.mark.parametrize("text,want", [
    ("Moderate confidence [C2].", "Moderate confidence."),
    ("SW is 0.45 [E2] (C1, E3), as the zones show [MAP].", "SW is 0.45, as the zones show."),
    ("Zone C2 is not a claim id.", "Zone C2 is not a claim id."),
    ("PHIE 0.21 [E1, C3] in Z2.", "PHIE 0.21 in Z2."),
])
def test_strip_ids(text, want):
    from petroharness.agent.writer import strip_ids
    assert strip_ids(text) == want


@pytest.mark.parametrize("text,n", [
    ("Moderate confidence: from the log model alone.", 1), ("Confidence: moderate.", 1), ("Confidence is low.", 1),
    ("Confidence in the pay distribution is moderate.", 1), ("high-confidence pick", 1), ("This is low with confidence.", 0),
    ("Overall confidence is moderate; the gas call is low confidence.", 2), ("No confidence stated.", 0),
])
def test_the_w6_metric_reads_grades_in_words(text, n):
    from replay import CONFIDENCE
    assert len(CONFIDENCE.findall(text)) == n


# --- on a real formation --------------------------------------------------------------------------------------------

def _session(points, claims):
    from test_b5_loop import _session as b5
    from petroharness.agent.claims import Claims
    s = b5()
    s.ledger.open("runs", {"condition": "NET_PAY"})
    s.ledger.open("stats", {"curves": ["SW", "PHIE"], "where": "NET_PAY"})
    s.points, s.intent = points, "locate"
    s.claims = Claims(points, s.ledger, s.map, s.task.question, s.f.view, (s.task.well,))
    for c in claims:
        s.claims.claims[c.id] = c
    s.claims._n = len(claims)
    return s


def _real_claims(s):
    total = re.search(r"all zones: ([\d.]+)", s.ledger.items[0].text).group(1)
    return [_claim("C1", 1, "NET_PAY is set in the zones listed by the runs", ev=("E1",)),
            _claim("C2", 2, f"NET_PAY totals {total} {s.f.inv.depth_unit} over all zones", ev=("E1",), weak="from the log model alone"),
            _claim("C3", 1, "SW and PHIE in the net pay are as the stats give them", ev=("E2",)),     # names table curves
            _claim("C4", 2, "Pay may be thicker in the lower zones", "hypothesis")]


@pytest.fixture(scope="module")
def real():
    s = _session(["Where is net pay?", "How thick is it?"], [])
    for c in _real_claims(s):
        s.claims.claims[c.id] = c
    s.claims._n = 4
    return s


@pytest.mark.data
@pytest.mark.parametrize("variant", ["", "open"])
def test_the_prompt_holds_every_point_and_every_settled_claim(real, variant):
    system, user, table, shape = prompt(real, variant, "default")
    for p in real.points:
        assert p in user
    for c in real.claims.claims.values():
        assert (c.text in user) == (c.grade != "hypothesis"), c.id
    assert "{points}" not in user and "{claims_block" not in user and "{RULES}" not in system and "{SHAPES}" not in system
    assert shape == "list" and table.startswith("| Zone |")


@pytest.mark.data
def test_the_open_prompt_shows_everything_opened_and_sets_no_length(real):
    system, user, _, _ = prompt(real, "open", "default")
    assert "ALL RESULTS" in user and all(f"[{e.id}]" in user for e in real.ledger.items)
    assert not re.search(r"\d+\s*-\s*\d+\s*words|at most \d+ words", system)
    assert "low confidence" in system and "lithology and depth range" in system
    _, plain_user, _, _ = prompt(real, "", "default")
    assert "ALL RESULTS" not in plain_user and len(user) > len(plain_user)


@pytest.mark.data
def test_the_zone_table_names_zones_by_their_record_names(real):
    named = [z for z in real.f.view.zones if getattr(z, "name", "")]
    if not named:
        pytest.skip("no zone record names in this formation")
    _, _, table, _ = prompt(real, "open", "default")
    assert f"| {named[0].zone_id} ({named[0].name}) |" in table


class _Writer:
    """A writer model that replies from a list; records what it was sent."""

    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def replays_reasoning(self):
        return True

    def chat(self, stage, messages, usage, max_tokens, retry=False):
        self.sent.append((stage, messages))
        usage.log.append({"stage": stage})
        return self.replies.pop(0) if self.replies else ""


def _cfg():
    from types import SimpleNamespace
    return SimpleNamespace(model=SimpleNamespace(max_tokens_writer=4000))


@pytest.mark.data
@pytest.mark.parametrize("variant,rounds", [("", 1), ("open", 2)])
def test_untraced_numbers_get_the_variant_s_repair_rounds(real, variant, rounds):
    bad = "## Answer\nNet pay is 987.654 m thick [E1].\n\n{{ZONE_TABLE}}\n\n## Conclusions\nPay holds 987.654 m."
    llm = _Writer([bad] * 4)
    trace = {}
    text, status = writer.write(llm, real, _cfg(), Usage(), trace, variant=variant)
    assert [st for st, _ in llm.sent] == ["writer"] + [f"repair_{r}" for r in range(1, rounds + 1)]
    assert status == "unresolved_numbers" and len(trace["verify_rounds"]) == rounds + 1
    assert "987.654" in llm.sent[-1][1][-1]["content"] and "[E1]" not in text and \
        ("| Depth Interval (" in text or "| Zone |" in text)        # the profile's table, or the writer's own


@pytest.mark.data
def test_a_repair_that_traces_every_number_ends_the_rounds(real):
    total = re.search(r"all zones: ([\d.]+)", real.ledger.items[0].text).group(1)
    bad = "## Answer\nNet pay is 987.654 m thick [E1].\n\n## Conclusions\nok"
    good = f"## Answer\nNet pay totals {total} {real.f.inv.depth_unit} [E1].\n\n## Conclusions\nok"
    llm = _Writer([bad, good, bad])
    trace = {}
    text, status = writer.write(llm, real, _cfg(), Usage(), trace, variant="open")
    assert status == "ok" and len(llm.sent) == 2 and total in text and trace["verify_rounds"][-1]["unsupported"] == []


@pytest.mark.data
def test_a_repair_that_drops_most_of_the_answer_is_refused(real):
    bad = "## Answer\nNet pay is 987.654 m thick [E1]. " + "The zones are described below. " * 20 + "\n\n## Conclusions\nok"
    llm = _Writer([bad, "## Answer\nshort"])
    trace = {}
    text, _ = writer.write(llm, real, _cfg(), Usage(), trace, variant="open")
    assert trace["verify_rounds"][-1].get("kept_draft") and "described below" in text and len(llm.sent) == 2


@pytest.mark.data
def test_process_words_are_repaired_with_the_numbers(real):
    draft = "## Answer\nPay is in the listed zones; thresholds are not shown in the opened record.\n\n## Conclusions\nok [C1]."
    fixed = "## Answer\nPay is in the listed zones; the record gives no thresholds for this interval.\n\n## Conclusions\nok [C1]."
    llm = _Writer([draft, fixed])
    trace = {}
    text, status = writer.write(llm, real, _cfg(), Usage(), trace, variant="open")
    assert "opened record" in llm.sent[1][1][-1]["content"] and trace["verify_rounds"][-1]["process"] == []
    assert "opened" not in text and "[C1]" not in text and "## Conclusions\nok.\n" in text      # the zone table follows


@pytest.mark.data
def test_working_notes_inside_the_answer_are_repaired(real):
    """A self-correction left in the text ("SIL... wait,") is shown to the model in a repair round."""
    draft = "## Answer\nPay is in the SIL... wait, SILT zones.\n\n## Conclusions\nok [C1]."
    fixed = "## Answer\nPay is in the SILT zones.\n\n## Conclusions\nok [C1]."
    llm = _Writer([draft, fixed])
    trace = {}
    text, status = writer.write(llm, real, _cfg(), Usage(), trace, variant="")
    assert trace["verify_rounds"][0]["leaks"] and "working notes" in llm.sent[1][1][-1]["content"]
    assert "SIL... wait" in llm.sent[1][1][-1]["content"] and trace["verify_rounds"][-1]["leaks"] == []
    assert "wait" not in text and "SILT zones" in text


@pytest.mark.data
def test_working_notes_in_the_draft_are_removed(real):
    llm = _Writer(["The user wants the pay. Let me check.\n\n## Answer\nPay is in the listed zones.\n\n## Conclusions\nok"])
    text, status = writer.write(llm, real, _cfg(), Usage(), {}, variant="open")
    assert text.startswith("## Answer") and "Let me" not in text and status == "ok"


# --- the replay on saved investigations -----------------------------------------------------------------------------

# PETROHARNESS_RUNS: a glob of saved run folders (each with traces/, as src/petroharness/cli.py writes them)
RUNS = os.environ.get("PETROHARNESS_RUNS", "")
TRACES = sorted(Path(p) for p in glob.glob(os.path.join(RUNS, "traces", "*.json"))) if RUNS else []


@pytest.mark.data
@pytest.mark.skipif(not RUNS, reason="PETROHARNESS_RUNS is not set (a glob of saved run folders)")
def test_the_replay_rebuilds_saved_investigations_and_its_prompt_holds_them():
    from petroharness.config import HarnessConfig
    from petroharness.tasks import load_tasks
    from replay import rebuild
    from dataclasses import asdict

    from petroharness.agent import options
    cfg = HarnessConfig()
    tasks, _ = load_tasks(cfg.eval.questions, cfg.data.las_dir)
    by_id = {t.task_id: t for t in tasks}
    exact, seen = 0, 0
    for path in TRACES[::8]:
        tr = json.loads(path.read_text())
        if tr["task_id"] not in by_id:                  # the traces belong to another dataset
            continue
        seen += 1
        ran = {k: v for k, v in (tr.get("options") or {}).items() if k in asdict(options.Options())}   # the live switches
        with options.use(**ran):                             # the options the traces ran with (not the env's, not today's)
            s, rep = rebuild(tr, by_id[tr["task_id"]], cfg.for_tasks())
            _, user, _, _ = prompt(s, "open", "default")
        exact += rep["opened_equal"] and rep["flags_equal"]
        for c in tr["claims"]:
            if c["grade"] != "hypothesis":
                assert c["text"] in user, (path.name, c["id"])
    if not seen:
        pytest.skip("the saved traces belong to another dataset")
    assert exact >= seen - 1


# --- curves with the same values (PERM = PERM_CC where the workflow passed the core-calibrated curve through) ---------

def _twin_formation():
    from test_b2_tools import F
    from petroharness.agent.engine import same_as
    for t, f in F():
        for c in f.inv.curves:
            if same_as(f, c):
                return t, f, c, same_as(f, c)
    return None


@pytest.mark.data
def test_a_label_names_the_curve_with_the_same_values_both_ways():
    from petroharness.agent.engine import label
    found = _twin_formation()
    if found is None:
        pytest.skip("no curves with the same values in this dataset")
    t, f, c, twins = found
    for a, b in [(c, twins[0]), (twins[0], c)]:
        assert f"{b} holds the same values" in label(f, a) or f"{b}," in label(f, a) or f", {b} hold" in label(f, a), label(f, a)


@pytest.mark.data
def test_the_map_says_same_values_on_both_curves():
    from petroharness.agent.map import render
    found = _twin_formation()
    if found is None:
        pytest.skip("no curves with the same values in this dataset")
    t, f, c, twins = found
    m = render(f.inv)
    assert re.search(rf"\b{c} = [^;\n]*same values as[^;\n]*{twins[0]}", m) and \
        re.search(rf"\b{twins[0]} = [^;\n]*same values as[^;\n]*{c}", m), m[:3000]


@pytest.mark.data
def test_the_zone_table_gives_curves_with_the_same_values_one_row():
    from petroharness.agent.claims import Claims
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.loop import Session
    from petroharness.agent.map import render
    from petroharness.agent.writer import zone_table
    found = _twin_formation()
    if found is None:
        pytest.skip("no curves with the same values in this dataset")
    t, f, c, twins = found
    s = Session(t, f, render(f.inv), Ledger(f), topics=["permeability_rock_quality"])
    s.claims = Claims(["p"], s.ledger, s.map, "q", f.view, (t.well,))
    s.claims.claims["C1"] = _claim("C1", 1, f"{c} and {twins[0]} are high in the upper zones")
    if len(f.view.zones) < 2:
        pytest.skip("one zone: the zone table is by curve")
    table = zone_table(s, s.claims)
    rows = [ln for ln in table.splitlines()[2:]]
    assert len(rows) == len(f.view.zones) and all(f"{c} = {twins[0]}" in r for r in rows), table[:600]


def test_the_rule_on_curves_with_the_same_values_is_given():
    assert any(r.startswith("Two curves with the same values") for r in RULES)



# --- the reader's format (reporting profile `format`) ------------------------------------------------------------------

FORMAT = {"shapes": {"report": "## A, ## B, ## Conclusions"}, "words": [350, 900], "zone_names": "lithology_and_depth",
          "zone_table": "by_interval"}


def test_a_format_sets_shapes_length_and_zone_names():
    from petroharness.agent.writer import LITH_ZONES, OPEN_SHAPES, apply_format
    rules = [r for r in RULES if not r.startswith(writer._OPEN_DROP)] + writer.OPEN_RULES
    out, shapes = apply_format(rules, dict(OPEN_SHAPES), FORMAT)
    assert shapes["report"] == "## A, ## B, ## Conclusions" and shapes["list"] == OPEN_SHAPES["list"]
    assert any(r.startswith("Length: about 350-900 words") for r in out) and not any(r.startswith("Length follows") for r in out)
    assert out.count(LITH_ZONES) == 1 and not any(r.startswith(("Refer to zones by id", "Name each zone at first")) for r in out)
    assert apply_format(rules, dict(OPEN_SHAPES), {}) == (rules, dict(OPEN_SHAPES))


def test_a_format_without_a_length_rule_still_gets_one():
    from petroharness.agent.writer import apply_format
    out, _ = apply_format(list(RULES), {}, {"words": [400, 800]})
    assert sum(r.startswith("Length: about 400-800 words") for r in out) == 1


def test_the_profile_format_or_the_default(tmp_path):
    from petroharness.agent.writer import reader_format
    prof = tmp_path / "p.yaml"
    prof.write_text("format:\n  words: [300, 600]\n  zone_names: lithology_and_depth\n")
    policy = {"reporting": {"profile": str(prof)}}
    assert reader_format(policy)["words"] == [300, 600] and reader_format(policy, "default") == {}
    assert reader_format({}) == {} and reader_format(None) == {}


@pytest.mark.data
def test_the_benchmark_profile_reaches_the_writer(real):
    if len(real.f.view.zones) < 2:
        pytest.skip("one zone: the zone table is by curve")
    system, user, table, _ = prompt(real, "open")
    system_d, _, table_d, _ = prompt(real, "open", "default")
    assert "Length: about" in system and "do not write zone ids" in system and "Formation Overview" in system
    assert table.startswith(f"| Depth Interval ({real.f.inv.depth_unit}) | Lithology |")
    rows = table.splitlines()[2:]
    assert len(rows) == len(real.f.view.zones) and not any(re.search(r"\| Z\d+", r) for r in rows)
    assert "Length: about" not in system_d and table_d.startswith("| Zone |")


@pytest.mark.data
def test_the_interval_table_gives_flag_fractions_and_twin_names(real):
    from petroharness.agent.writer import zone_table
    flags = [c for c in real.f.inv.curves if c in real.f.view.reg.flags][:1]
    if not flags:
        pytest.skip("no flag curve")
    real.claims.claims["C9"] = _claim("C9", 1, f"{flags[0]} and SW in the zones")
    if len(real.f.view.zones) == 1:
        pytest.skip("one zone: the zone table is by curve")
    try:
        t = zone_table(real, real.claims, wide=True, style="by_interval")
    finally:
        real.claims.claims.pop("C9")
    head = t.splitlines()[0]
    assert f"{flags[0]} fraction" in head and "Mean SW" in head
    z = real.f.view.zones[0]
    want = np.nanmean(np.asarray(real.f.view.zone_values(z, flags[0]), dtype=float))
    cells = [c.strip() for c in t.splitlines()[2].split("|")[1:-1]]
    col = [c.strip() for c in head.split("|")[1:-1]].index(f"{flags[0]} fraction")
    assert abs(float(cells[col]) - want) < 0.001


# --- the general reporting rules (writer.V5_RULES) -------------------------------------------------------------------

def test_the_general_reporting_rules_name_no_dataset_and_no_verdict():
    from petroharness.agent.writer import V5_RULES
    dataset = re.compile(r"geolink|costa|volve|kharaib|equinor|\bnpd\b|norw(ay|egian)|north sea", re.I)
    verdict = re.compile(r"\b(confirmed|proven|established|commercial)\b", re.I)
    assert len(V5_RULES) == 7                                       # seven rules, none on a flag's basis
    assert not [r for r in V5_RULES if dataset.search(r)]
    assert [i for i, r in enumerate(V5_RULES) if verdict.search(r)] == [len(V5_RULES) - 1]   # only the rule forbidding them
    assert not [r for r in V5_RULES if re.search(r"\b(card|evidence ids?|readings? \(|the notes)\b", r)]  # terms the prompts do not use


@pytest.mark.data
def test_the_writer_prompt_holds_the_general_rules_and_the_absence_rule(real):
    """The general reporting rules and the absence rule both reach the writer."""
    from petroharness.agent.writer import V5_RULES
    system, user, _, _ = prompt(real, "open")
    assert all(r in system for r in V5_RULES)
    assert "If the question asks for a quantity this interval does not have" in system
    assert "Answer first." in system                                    # with the writer's own rules


# --- statements that contradict the data reach the repair round (writer.contradictions) ------------------------------

def _wsession(f, question, opened=()):
    from types import SimpleNamespace as NS
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.map import render
    led = Ledger(f)
    for tool, args in opened:
        led.open(tool, args)
    return NS(f=f, ledger=led, task=NS(question=question), map=render(f.inv))


def _first(pred):
    from test_b2_tools import F
    for t, f in F():
        if pred(f):
            return f
    pytest.skip("no formation of this dataset has what the case needs")


@pytest.mark.data
def test_data_said_missing_while_present_is_a_contradiction():
    from petroharness.agent import options
    from petroharness.agent.writer import contradictions
    f = _first(lambda f: any(f.view.available(c) for c in ("RSHA", "RXO", "RMIC")))
    s = _wsession(f, "Is there evidence of invasion?")
    c = next(c for c in ("RSHA", "RXO", "RMIC") if f.view.available(c))
    assert contradictions("## Answer\nNo shallow resistivity was recorded, so invasion cannot be assessed.", s)
    assert not contradictions(f"## Answer\nShallow resistivity ({c}) reads above the deep resistivity in Z1.", s)


@pytest.mark.data
def test_core_calibrated_availability_is_checked_against_the_data():
    from petroharness.agent.writer import contradictions
    f = _first(lambda f: f.view.available("PHIE_CC"))
    s = _wsession(f, "How porous is the formation?")
    assert contradictions("## Answer\nNo core-calibrated porosity is available in this interval.", s)
    assert not contradictions("## Answer\nCore-calibrated porosity (PHIE_CC) is the porosity of record here.", s)
    g = _first(lambda f: not f.view.available("PHIE_CC") and not f.view.available("PERM_CC"))
    assert contradictions("## Answer\nPHIE_CC averages 0.21 in the sands.", _wsession(g, "How porous is the formation?"))


@pytest.mark.data
def test_a_classed_interval_denied_is_the_model_s_verdict():
    """G8: a denial of a property whose classes the results place in intervals is the model's verdict; the checker
    never asks for a different one."""
    import numpy as np
    from petroharness.agent.writer import contradictions
    f = _first(lambda f: f.view.available("NET_PAY") and (np.nan_to_num(np.asarray(f.view.values("NET_PAY"), float)) > 0).sum() > 4)
    s = _wsession(f, "Where is the net pay in this formation?", [("runs", {"condition": "NET_PAY"})])
    assert not contradictions("## Answer\nNo zones show net pay in this formation.", s)
    assert not contradictions("## Answer\nNet pay is flagged in several intervals, graded low where thin.", s)


def test_the_writer_map_leaves_the_notes_out_unless_asked():
    from petroharness.agent import options
    from petroharness.agent.writer import writer_map
    m = "WELL W, FORMATION F\nZones: 2\nAnalyzer sections\n  hydrocarbon (3): a, b, c\nNotes on this interval\n  - MHI: follows SW"
    assert writer_map(m) == "WELL W, FORMATION F\nZones: 2\nAnalyzer sections\n  hydrocarbon (3): a, b, c"
    assert writer_map("no notes here") == "no notes here"


# --- exact_numbers: numbers as the results show them -------------------------------------------------------------------

def test_exact_numbers_keeps_digits_and_swaps_the_rounding_rule():
    from petroharness.agent import options
    from petroharness.agent.writer import report_numbers
    text = "PHIT mean 0.2612 v/v at 8522.5 ft; PERM 35.4123 mD"
    assert report_numbers(text) == text


@pytest.mark.data
@pytest.mark.parametrize('on', [True])
def test_exact_numbers_rule_in_the_prompt(real, on):
    from petroharness.agent import options
    from petroharness.agent.writer import EXACT_RULE
    system, _, _, _ = prompt(real, "open")
    assert (EXACT_RULE in system) is on
    assert ("Round numbers to the precision" in system) is (not on)


@pytest.mark.data
@pytest.mark.parametrize('absence', [True])
def test_the_absence_rule_stands_beside_the_general_rules(real, absence):
    from petroharness.agent import options
    system, _, _, _ = prompt(real, "open")
    assert ("If the question asks for a quantity this interval does not have" in system) is absence


@pytest.mark.data
def test_table_core_starts_with_the_topics_key_curves(real):
    from petroharness.agent import direction
    from petroharness.agent.writer import zone_table
    if len(real.f.view.zones) < 2:
        pytest.skip("one zone: the zone table is by curve")
    t = zone_table(real, real.claims, wide=True, style="by_interval")
    head = t.splitlines()[0]
    key = [c for c in direction.overview(real.topics) if c in real.f.inv.curves]
    assert key and f"Mean {key[0]}" in head
    assert head.count("|") - 1 <= 2 + 9


@pytest.mark.data
def test_the_prompt_has_one_guideline_for_bases_and_no_basis_rule(real):
    """G6: the writer has one guideline for bases and conventions, once, in its rules; no basis rule."""
    from petroharness.agent.writer import ASPECTS_RULE
    system, user, _, _ = prompt(real, "open")
    assert system.count(ASPECTS_RULE) == 1 and ASPECTS_RULE not in user
    assert "the record's basis" not in system and "lead with the lithology-zone" not in system.lower()
