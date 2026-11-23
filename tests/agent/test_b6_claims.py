"""The claims (C1-C7 below). Hand-written cases on stub ledger items and, with -m data, claims generated from every
formation's real ledger items and content cases built from each formation's own data.

    .venv/bin/python -m pytest tests/agent/test_b6_claims.py -q   (PETROHARNESS_DATA selects the dataset)
"""
import random
import re
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.agent.claims import Claims, clean_text, coerce_edit, norm_grade  # noqa: E402
from petroharness.agent.ledger import Item, shown_values  # noqa: E402

MEANS = "so the zone is the better reservoir of the two"


# --- hand-written items -------------------------------------------------------------------------------------------

def item(eid, tool, lines):
    rows = [(ln, [float(x) for x in re.findall(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?(?![A-Za-z0-9_])",
                                               re.sub(r"\bZ\d+\b|[A-Z]+_?[A-Z]*\d\w*", " ", ln))]) for ln in lines]
    return Item(eid, tool, {}, eid, rows, "\n".join(lines), [x for _, ns in rows for x in ns])


class StubLedger:
    def __init__(self, items):
        self.items, self.f = items, None


E1 = item("E1", "stats", ["SW [v/v] = water saturation (computed)", "  Z1 SAND 1950-1975 m: n 50 of 50, mean 0.4567",
                          "  Z2 SAND 1975-2000 m: n 50 of 50, mean 0.2934",
                          "  LOW_SW: 12.5 m, 40.5% of the zoned thickness, 3 intervals; runs: Z1 1950-1962.5"])
E2 = item("E2", "stats", ["RDEP [ohm.m] = deep resistivity (input)", "  Z2 SAND 1979.6-1991.8 m: n 40 of 40, mean 8.402"])
E3 = item("E3", "stats", ["PHIE [v/v] = effective porosity (computed)", "  Z2 SAND 1975-2000 m: n 30 of 30, mean 0.2311"])
MAPTEXT = "Interval: 1950-2100 m (gross 150 m); 301 samples every 0.5 m\nZones: 2\n  Z2 SAND 1975-2000 m"


def claims(items=None):
    return Claims(["p1", "p2"], StubLedger(list(items or [E1, E2, E3])), MAPTEXT, "Is SW below 0.5?", None, ("35/11-6",))


# --- C1 edit shapes -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ({"op": "add", "point": 1, "text": "x", "ev": ["E1"], "grade": "low"}, {"op": "add", "point": 1, "ev": ["E1"], "grade": "low"}),
    ({"op": "ADD", "point": "2", "text": "x"}, {"op": "add", "point": 2}),
    ({"op": "add", "point": "P3", "text": "x"}, {"op": "add", "point": 3}),
    ({"op": "add", "point": "point 3", "text": "x"}, {"op": "add", "point": 3}),
    ({"op": "add", "point": 2.0, "text": "x"}, {"op": "add", "point": 2}),
    ({"add": {"point": 1, "claim": "x", "evidence": "E4", "confidence": "Moderate confidence"}}, {"op": "add", "point": 1, "ev": ["E4"], "grade": "Moderate confidence"}),
    ({"op": "add", "point": 1, "text": "x", "ev": "E1, E2"}, {"ev": ["E1", "E2"]}),
    ({"op": "add", "point": 1, "text": "x", "ev": "E1 E2"}, {"ev": ["E1", "E2"]}),
    ({"op": "add", "point": 1, "text": "x", "ev": ["[E3]", "e4"]}, {"ev": ["E3", "E4"]}),
    ({"op": "add", "point": 1, "text": "x", "ev": ["E2-E4"]}, {"ev": ["E2", "E3", "E4"]}),
    ({"op": "add", "point": 1, "text": "x", "ev": ["E2–E4", "MAP"]}, {"ev": ["E2", "E3", "E4", "MAP"]}),
    ({"op": "add", "point": 1, "text": "x", "ev": ["description", "E1"]}, {"ev": ["MAP", "E1"]}),
    ({"op": "add", "point": 1, "text": "x", "ev": ["E1", "E1"]}, {"ev": ["E1"]}),
    ({"op": "revise", "id": "c3", "grade": "high"}, {"op": "revise", "id": "C3", "grade": "high"}),
    ({"revise": "C3", "text": "y"}, {"op": "revise", "id": "C3", "text": "y"}),
    ({"revise": {"id": "C3", "limits": "z"}}, {"op": "revise", "id": "C3", "weak": "z"}),
    ({"update": "C2", "text": "y"}, {"op": "revise", "id": "C2"}),
    ({"op": "edit", "id": "C2"}, {"op": "revise", "id": "C2"}),
    ({"drop": "C4", "why": "E2"}, {"op": "drop", "id": "C4", "why": "E2"}),
    ({"op": "delete", "id": "C4"}, {"op": "drop", "id": "C4"}),
    ({"op": "remove", "claim_id": "C4"}, {"op": "drop", "id": "C4"}),
    ({"action": "add", "point": 1, "finding": "x"}, {"op": "add", "point": 1}),
    ({"op": "add", "point": 1, "statement": "x", "caveats": "c"}, {"weak": "c"}),
    ({"op": "add", "point": 1, "text": "x", "meaning": "m", "weaknesses": "w"}, {"means": "m", "weak": "w"}),
    ({"op": "add", "point": 1, "text": "x", "implication": "m", "limitations": "w"}, {"means": "m", "weak": "w"}),
    ({"op": "add", "point": 1, "text": "x", "interpretation": "m"}, {"means": "m"}),
    ({"op": "add", "point": 1, "text": "x", "cite": "E2"}, {"ev": ["E2"]}),
])
def test_c1_coerce_edit(raw, want):
    got = coerce_edit(raw)
    assert got is not None
    for k, v in want.items():
        assert got[k] == v, (k, got[k], v)


@pytest.mark.parametrize("raw", [None, "add C1", ["op", "add"], {"op": "jump"}, {}, {"text": "x"}, {"open": "a.b"}])
def test_c1_coerce_edit_rejects(raw):
    assert coerce_edit(raw) is None


@pytest.mark.parametrize("raw,want", [
    ("high", "high"), ("High confidence", "high"), ("corroborated", "high"), ("strong", "high"),
    ("moderate", "moderate"), ("Moderate confidence", "moderate"), ("medium", "moderate"),
    ("low", "low"), ("low confidence", "low"), ("log-indicated, not validated", "low"), ("marginal", "low"),
    ("candidate with named weaknesses", "low"), ("weak", "low"),
    ("not indicated", "not indicated"), ("absent", "not indicated"), ("none", "not indicated"),
    ("undetermined", "undetermined"), ("cannot be determined", "undetermined"), ("not determinable", "undetermined"),
    ("insufficient data", "undetermined"),
    ("hypothesis", "hypothesis"), ("unchecked", "hypothesis"), ("to check", "hypothesis"),
    ("not high", None), ("", None), ("banana", None),
])
def test_c1_norm_grade(raw, want):
    assert norm_grade(raw) == want


@pytest.mark.parametrize("raw,text,cited", [
    ("C1 [moderate] C1 [moderate] The separation is RMED/RDEP (MAP, E1–E4, E9)", "The separation is RMED/RDEP.",
     ["E1", "E2", "E3", "E4", "E9", "MAP"]),
    ("RDEP mean 2.1 in Z3 (E5) and higher above.", "RDEP mean 2.1 in Z3 (E5) and higher above.", []),
    ("Pay is thin (E10). (MAP, E10) (MAP, E10)", "Pay is thin (E10).", ["MAP", "E10"]),
    ("Z3 (1979.6–1991.8 m) is the best interval", "Z3 (1979.6–1991.8 m) is the best interval", []),
    ("Low SW in Z2 (E3, E4).", "Low SW in Z2.", ["E3", "E4"]),
    ("", "", []),
])
def test_c1_clean_text(raw, text, cited):
    t, c = clean_text(raw)
    assert t == text and sorted(set(c)) == sorted(set(cited))


# --- C2-C4 numbers (hand-written) -----------------------------------------------------------------------------------

@pytest.mark.parametrize("text,ev,flagged", [
    ("mean SW 0.4567 in Z1", ["E1"], False),
    ("mean SW 0.457 in Z1", ["E1"], False),
    ("mean SW 0.46 in Z1", ["E1"], False),
    ("mean SW 0.45 in Z1", ["E1"], True),
    ("mean SW 0.4568 in Z1", ["E1"], True),
    ("SW 45.67% in Z1", ["E1"], False),
    ("LOW_SW covers 12.5 m (40.5%)", ["E1"], False),
    ("RDEP mean 8.402 ohm.m", ["E2"], False),
    ("RDEP mean 8.402 ohm.m", ["E1"], False),               # distinctive, same name, uncited: cited by code
    ("RDEP mean 8.402 ohm.m", [], False),
    ("PHIE 0.2311 in Z2", ["E1"], False),
    ("mean SW 0.4567 against PHIE 0.23", ["E1"], True),     # short number in an uncited item: not cited by code
    ("interval 1950-2100 m, gross 150 m", [], False),       # the map's numbers
    ("SW below 0.5 as asked", ["E1"], False),               # the question's number
    ("the 12.5 m is 8.3% of the 150 m gross", ["E1"], False),
    ("the 12.5 m is 40.5% of 30.86 m", ["E1"], True),
    ("about 8.4 ohm.m", ["E2"], False),
    ("8.4 ohm.m", ["E2"], False),
    ("9.1 ohm.m", ["E2"], True),
    ("well 35/11-6 in Z2", ["E1"], False),
    ("Z26 and Z2 differ", ["E1"], False),
    ("1979.6-1991.8 m", ["E2"], False),
    ("1979.6-1991.9 m", ["E2"], True),
    ("SW 0.4567 in Z1 and 0.2934 in Z2, 0.1633 apart", ["E1"], False),   # a difference of two shown numbers
])
def test_c2_c3_numbers(text, ev, flagged):
    a = claims()
    a.apply([{"op": "add", "point": 1, "text": text, "ev": ev, "grade": "low", "means": MEANS}])
    c = list(a.claims.values())[0]
    assert any(f.startswith("K3") for f in c.flags) == flagged, c.flags


def test_c3_numbers_in_means_and_weak_are_checked_too():
    a = claims()
    a.apply([{"op": "add", "point": 1, "text": "mean SW 0.4567 in Z1", "ev": ["E1"], "grade": "low",
              "means": "so 0.61 of the pores hold water there", "weak": "only 50 samples"}])
    assert any(f.startswith("K3") and "0.61" in f for f in a.claims["C1"].flags)


def test_c4_auto_cite_is_logged_and_named():
    a = claims()
    a.apply([{"op": "add", "point": 1, "text": "RDEP mean 8.402 ohm.m in Z2", "ev": ["E1"], "grade": "low", "means": MEANS}])
    c = a.claims["C1"]
    assert c.ev == ["E1", "E2"] and any(h.get("by") == "code" for h in c.history) and not c.flags


def test_c4_flag_names_the_item_that_holds_it():
    a = claims()
    a.apply([{"op": "add", "point": 1, "text": "mean SW 0.4567 against PHIE 0.23", "ev": ["E1"], "grade": "low", "means": MEANS}])
    f = next(x for x in a.claims["C1"].flags if x.startswith("K3"))
    assert "0.23 is in E3" in f


# --- C6 edit semantics, C7 done -------------------------------------------------------------------------------------

def test_c6_c7_edit_semantics_and_done():
    a = claims()
    msgs = a.apply([{"op": "add", "point": 1, "text": "SW low in Z2", "grade": "hypothesis"},
                    {"op": "add", "point": 2, "text": "RDEP mean 8.402 ohm.m", "ev": ["E2"], "grade": "moderate", "means": MEANS},
                    {"op": "add", "point": 3, "text": "out of range"},
                    {"op": "add", "point": 1},
                    {"op": "revise", "id": "C9", "text": "x"},
                    {"op": "drop", "id": "C9"}])
    assert len(msgs) == 4 and set(a.claims) == {"C1", "C2"}
    assert a.claims["C1"].grade == "hypothesis" and not a.claims["C1"].settles and a.claims["C2"].settles
    assert any("point 1 has no settled claim" in x for x in a.done_issues())
    assert any("hypotheses left: C1" in x for x in a.done_issues())
    a.apply([{"op": "revise", "id": "C1", "text": "mean SW 0.2934 in Z2", "ev": ["E1"], "grade": "low", "means": MEANS}])
    assert a.claims["C1"].settles and a.done_issues() == []
    a.apply([{"op": "revise", "id": "C1", "weak": "quicklook"}])
    assert a.claims["C1"].text == "mean SW 0.2934 in Z2" and a.claims["C1"].grade == "low" and a.claims["C1"].weak == "quicklook"
    assert a.apply([{"op": "revise", "id": "C1", "grade": "banana"}]) and a.claims["C1"].grade == "low"
    assert not a.apply([{"op": "revise", "point": 2, "weak": "L"}]) and a.claims["C2"].weak == "L"
    a.apply([{"op": "add", "point": 2, "text": "second", "ev": ["E2"], "grade": "low", "means": MEANS}])
    assert "point 2 has claims C2, C3" in a.apply([{"op": "revise", "point": 2, "weak": "M"}])[0]
    a.apply([{"op": "revise", "id": "C3", "grade": "high"}])
    assert any(f.startswith("K4") for f in a.claims["C3"].flags)
    a.apply([{"op": "revise", "id": "C3", "ev": ["E2", "E3"]}])
    assert not a.claims["C3"].flags
    a.apply([{"op": "drop", "id": "C3", "why": "dup"}, {"op": "add", "point": 2, "text": "third", "ev": ["E2"], "grade": "low", "means": MEANS}])
    assert "C3" not in a.claims and a.dropped[-1].id == "C3" and "C4" in a.claims
    a.apply([{"op": "add", "point": 2, "text": "later", "ev": ["E7"], "grade": "low", "means": MEANS}])
    assert any(f.startswith("K1") for f in a.claims["C5"].flags)
    a.ledger.items.append(item("E7", "stats", ["X = later (input)", "  Z1 SAND: n 1 of 1, mean 1"]))
    a.refresh()
    assert not a.claims["C5"].flags
    a.apply([{"op": "add", "point": 2, "text": "no ev", "grade": "low", "means": MEANS}])
    assert any(f.startswith("K2") for f in a.claims["C6"].flags)


def test_c5_a_claim_with_results_and_no_readable_grade_is_refused_not_graded():
    """The grade is the model's (G8). A claim added with results and no grade, or a grade the
    scale cannot read, is said back and asked for, as a revise with an unreadable grade is; without results it is a
    hypothesis."""
    a = claims()
    msgs = a.apply([{"op": "add", "point": 1, "text": "mean SW 0.2934 in Z2", "ev": ["E1"], "means": MEANS},
                    {"op": "add", "point": 1, "text": "mean SW 0.2934 in Z2", "ev": ["E1"], "grade": "not high"},
                    {"op": "add", "point": 1, "text": "SW may be low in Z2"}])
    assert len(msgs) == 2 and all("needs its grade, one of" in m for m in msgs), msgs
    assert "none given" in msgs[0] and "'not high'" in msgs[1]
    assert [c.grade for c in a.claims.values()] == ["hypothesis"]


def test_c6_k9_a_graded_claim_says_what_it_means():
    a = claims()
    a.apply([{"op": "add", "point": 1, "text": "mean SW 0.2934 in Z2", "ev": ["E1"], "grade": "moderate"},
             {"op": "add", "point": 1, "text": "mean SW 0.2934 in Z2", "ev": ["E1"], "grade": "undetermined"},
             {"op": "add", "point": 1, "text": "maybe low SW", "grade": "hypothesis"}])
    assert any(f.startswith("K9") for f in a.claims["C1"].flags)
    assert not any(f.startswith("K9") for f in a.claims["C2"].flags + a.claims["C3"].flags)
    a.apply([{"op": "revise", "id": "C1", "means": "hydrocarbon likely occupies most of the pore space in Z2"}])
    assert not a.claims["C1"].flags


def test_c6_render():
    a = claims()
    a.apply([{"op": "add", "point": 1, "text": "mean SW 0.4568 in Z1", "ev": ["E1"], "grade": "low", "means": MEANS, "weak": "one well"}])
    r = a.render()
    assert r.startswith("Point 1: p1 [open]\n  C1 [low] mean SW 0.4568 in Z1 (E1)\n     means: " + MEANS + "\n     weak: one well\n     ! K3")
    assert "Point 2: p2 [open]\n  (no claim yet)" in r


# --- real data: generated claims (C2, C3) ---------------------------------------------------------------------------

def _sessions():
    from test_b3_ledger import sessions
    return sessions()


def _row_claims(e, rng, n=12) -> list:
    """(claim text, the number as shown, the line's names) from an item's rows with a zone and a value."""
    out = []
    head = ""
    for ln, nums in e.rows:
        if not ln.startswith(" "):
            head = ln.split(" ", 1)[0]
        m = re.match(r"^  (Z\d+) [^:]*: (.*)$", ln)
        if not m or not nums:
            continue
        for part in m.group(2).split(", "):
            k = re.match(r"^(mean|median|p10|p90|std|geo_mean|difference mean) (-?\d+(?:\.\d+)?)$", part)
            if k:
                out.append((f"{head} {k.group(1)} in {m.group(1)} is {k.group(2)}.", k.group(2)))
    rng.shuffle(out)
    return out[:n]


@pytest.mark.data
def test_c2_c3_generated_claims_on_real_items():
    passed, wrong, caught, detectable, n = 0, [], 0, 0, 0
    for t, f, led, opened in _sessions():
        from petroharness.agent.map import render
        shown = render(f.inv)
        a = Claims(["p"], led, shown, "What does the formation hold?", None, (t.well,))
        rng = random.Random(t.well)
        rowed = [e for e in led.items if any(re.match(r"^  Z\d+ ", ln) for ln in e.lines)]     # items with zone rows
        for e in rowed:
            vals = shown_values(e) + [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", shown)]
            for text, raw in _row_claims(e, rng, 8):
                n += 1
                k = len(raw.split(".")[1]) if "." in raw else 0
                # C2: as shown, and coarser
                ok = [text]
                if k >= 2:                    # coarser, from the exact value (rounding the shown digits again can
                    exact = min(e.numbers, key=lambda v: abs(float(v) - float(raw)))     #   step past it: 0.03255)
                    ok.append(text.replace(raw, f"{round(float(exact), k - 1):.{k - 1}f}"))
                for tx in ok:
                    a.claims.clear()
                    a.apply([{"op": "add", "point": 1, "text": tx, "ev": [e.id], "grade": "low", "means": MEANS}])
                    c = list(a.claims.values())[0]
                    if any(x.startswith("K3") for x in c.flags):
                        wrong.append((t.well, e.id, tx, c.flags))
                    else:
                        passed += 1
                # C3: one unit to nine units off in the last digit
                step = 10 ** (-k)
                bad = float(raw) + rng.choice([-1, 1]) * rng.randint(1, 9) * step
                written = f"{bad:.{k}f}"
                if written == raw or (k == 0 and abs(bad) < 20):          # small counts are exempt by the shared rule
                    continue
                coincident = any(abs(float(written) - v) <= 0.5 * step + 1e-9 for v in vals)
                a.claims.clear()
                a.apply([{"op": "add", "point": 1, "text": text.replace(raw, written), "ev": [e.id], "grade": "low", "means": MEANS}])
                flagged = any(x.startswith("K3") for x in list(a.claims.values())[0].flags)
                if not coincident:
                    detectable += 1
                    caught += flagged
    assert n > 300 and not wrong, (n, len(wrong), wrong[:5])
    assert detectable and caught / detectable >= 0.95, (caught, detectable)
    print(f"C2 {passed} true claims unflagged; C3 caught {caught} of {detectable} detectable misquotes")


# --- real data: content checks (C5) ---------------------------------------------------------------------------------

def _claims_on(f, led, question="Where is the net pay and is there gas?"):
    from petroharness.agent.map import render
    return Claims(["p"], led, render(f.inv), question, f.view, ())


def _flags(a, text, grade="low", ev=("MAP",)):
    a.claims.clear()
    a.apply([{"op": "add", "point": 1, "text": text, "ev": list(ev), "grade": grade, "means": MEANS}])
    return list(a.claims.values())[0].flags


@pytest.mark.data
def test_c5_k5_data_said_missing_while_present():
    from petroharness.agent.ledger import Ledger
    seen = 0
    for t, f in __import__("test_b2_tools").F():
        a = _claims_on(f, Ledger(f))
        shallow = any(f.view.available(c) for c in ("RSHA", "RXO", "RMIC"))
        got = any(x.startswith("K5") for x in _flags(a, "There is no shallow resistivity, so mobility cannot be assessed."))
        assert got == shallow, (t.well, shallow)
        assert not any(x.startswith("K5") for x in _flags(a, "Deep resistivity is high in Z1."))
        seen += 1
    assert seen


@pytest.mark.data
def test_c5_k7_core_calibrated_availability():
    from petroharness.agent.ledger import Ledger
    for t, f in __import__("test_b2_tools").F():
        a = _claims_on(f, Ledger(f))
        core = f.view.available("PHIE_CC") or f.view.available("PERM_CC")
        said = any(x.startswith("K7") for x in _flags(a, "Core-calibrated porosity is not available in this well."))
        used = any(x.startswith("K7") for x in _flags(a, "PHIE_CC averages 0.2 over the pay."))
        assert said == core and used == (not core), (t.well, core, said, used)


@pytest.mark.data
def test_c5_k8_check_before_claim():
    from petroharness.agent.ledger import Ledger
    pos = neg = 0
    for t, f in __import__("test_b2_tools").F():
        led = Ledger(f)
        a = _claims_on(f, led)
        has = "CROSSOVER_FLAG" in f.inv.curves
        flags = _flags(a, "There is no neutron-density crossover in this formation.")
        k8 = any(x.startswith("K8") for x in flags)
        if has:
            assert k8, (t.well, flags)
            pos += 1
            led.open("runs", {"condition": "CROSSOVER_FLAG"})
            a.refresh()
            flags = _flags(a, "There is no neutron-density crossover in this formation.", ev=("E1",))
            assert not any(x.startswith("K8") for x in flags), (t.well, flags)
            # a denial of the property is the model's verdict; no check pushes it, K6 included
            b = _claims_on(f, led, "Is there neutron-density crossover?")
            assert not any(x.startswith("K6") for x in _flags(b, "No zones show crossover.", ev=("E1",)))
        else:
            assert not k8, (t.well, flags)
            neg += 1
    assert pos


@pytest.mark.data
def test_c5_k8_names_how_to_open_it():
    from petroharness.agent.ledger import Ledger
    for t, f in __import__("test_b2_tools").F():
        if "NET_PAY" in f.inv.curves:
            a = _claims_on(f, Ledger(f))
            flags = _flags(a, "The formation has no net pay.")
            k8 = next((x for x in flags if x.startswith("K8")), "")
            assert "runs NET_PAY" in k8, (t.well, flags)
            return
    pytest.skip("no NET_PAY")


@pytest.mark.parametrize("text,flagged", [("H2: LOW_SW likely in Z2", True), ("Hypothesis: pay in Z1", True),
                                          ("hypothesis - pay in Z1", True), ("Expected: SW below 0.5", True),
                                          ("mean SW 0.2934 in Z2", False), ("The hypothesis of pay is refuted by SW 0.4567", False)])
def test_k10_graded_claims_do_not_read_as_hypotheses(text, flagged):
    a = claims()
    a.apply([{"op": "add", "point": 1, "text": text, "ev": ["E1"], "grade": "low", "means": MEANS}])
    assert any(f.startswith("K10") for f in list(a.claims.values())[0].flags) == flagged
    a.apply([{"op": "add", "point": 1, "text": text, "grade": "hypothesis"}])
    assert not any(f.startswith("K10") for f in list(a.claims.values())[-1].flags)


# --- K11 a negative resting on a screen that could not run -----------------------------------------------------------

def _dead_screen():
    from b5_traps import screen_not_run
    from _support.formations import F
    for t, f in F():
        ctx = screen_not_run(f)
        if ctx:
            return t, f, ctx["key"]
    return None


@pytest.mark.data
@pytest.mark.parametrize("text,weak,cite,flagged", [
    ("No hydrocarbons are indicated anywhere in the interval.", "", "screen", True),
    ("Hydrocarbons are not indicated by the screening.", "", "screen", True),
    ("No hydrocarbons are indicated anywhere in the interval.", "the screen could not run: its inputs were unavailable", "screen", False),
    ("No hydrocarbons are indicated: SW is near 1 in every zone.", "", "stats", False),
    ("Hydrocarbons are indicated in the upper zone by low SW.", "", "screen", False),
])
def test_k11_a_screen_that_could_not_run_is_no_evidence(text, weak, cite, flagged):
    from petroharness.agent.claims import Claims
    from petroharness.agent.ledger import Ledger
    found = _dead_screen()
    if found is None:
        pytest.skip("no screen that could not run in this dataset")
    t, f, key = found
    led = Ledger(f)
    e_sec, _ = led.open("section", {"key": key})
    e_sw, _ = led.open("stats", {"curves": ["SW"]})
    c = Claims(["Are hydrocarbons indicated?"], led, "", "q", f.view, (t.well,))
    c.apply([{"op": "add", "point": 1, "text": text, "ev": [e_sec.id if cite == "screen" else e_sw.id], "grade": "moderate",
              "means": "so the formation holds no producible hydrocarbons here", "weak": weak}])
    k11 = [x for x in c.claims["C1"].flags if x.startswith("K11")]
    assert bool(k11) is flagged, c.claims["C1"].flags
