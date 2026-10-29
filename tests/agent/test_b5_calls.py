"""The calls models send. The shapes come from the failed calls of 912 traced investigations
(tests/agent/b5_traces.py): what each meant is read as that; what cannot be read stays a message the model reads. And calc:
arithmetic on shown numbers as an item a claim can cite (K3).

    .venv/bin/python -m pytest tests/agent/test_b5_calls.py -q   (PETROHARNESS_DATA selects the dataset)
"""
import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.agent.engine import ToolError  # noqa: E402
from petroharness.agent.ledger import evaluate  # noqa: E402
from petroharness.agent.loop import coerce_action  # noqa: E402
from petroharness.agent.schemas import arguments, fit  # noqa: E402


# --- fit: what the shapes mean (hand-written, from the traced failures) ----------------------------------------------

@pytest.mark.parametrize("name,raw,want", [
    ("stats", {"curves": ["SW"], "zones": True}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "zones": "all"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "zones": ["ALL"]}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "zones": ["pooled"]}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "zones": [1, 3]}, {"curves": ["SW"], "zones": ["Z1", "Z3"]}),
    ("stats", {"curves": ["SW"], "zones": ["Z1-Z3"]}, {"curves": ["SW"], "zones": ["Z1", "Z2", "Z3"]}),
    ("stats", {"curves": ["SW"], "zones": ["Z2 to Z4"]}, {"curves": ["SW"], "zones": ["Z2", "Z3", "Z4"]}),
    ("stats", {"curves": ["SW"], "zones": ["Z1 LIMESTONE", "Z2 DOLOMITE"]}, {"curves": ["SW"], "zones": ["Z1", "Z2"]}),
    ("stats", {"curves": ["SW"], "zones": ["Z1 (7805-7867.5 ft)"]}, {"curves": ["SW"], "zones": ["Z1"]}),
    ("stats", {"curves": ["SW"], "zones": ["MICRO_PORES"]}, {"curves": ["SW"], "zones": ["MICRO_PORES"]}),   # stays: an error names the zones
    ("stats", {"curves": ["SW"], "statistics": ["P10", "P90", "Mean"]}, {"curves": ["SW"], "statistics": ["p10", "p90", "mean"]}),
    ("stats", {"curves": ["SW"], "statistics": ["geometric_mean", "stdev", "P50", "p25"]},
     {"curves": ["SW"], "statistics": ["geo_mean", "std", "median", "p25"]}),
    ("stats", {"curves": ["SW"], "statistics": ["percentile_75"]}, {"curves": ["SW"], "statistics": ["p75"]}),
    ("stats", {"curves": ["SW"], "where": "all"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "where": "whole interval"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "where": "All Samples"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "where": "both finite"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "where": "NET_PAY"}, {"curves": ["SW"], "where": "NET_PAY"}),
    ("stats", {"curve": "SW"}, {"curves": ["SW"]}),
    ("stats", {"curve": ["SW", "PHIE"]}, {"curves": ["SW", "PHIE"]}),
    ("profile", {"curves": ["SW"]}, {"curve": "SW"}),
    ("section", {"key": "hydrocarbon.x", "find": "Z2"}, {"key": "hydrocarbon.x"}),
    ("section", {"key": "hydrocarbon.x", "reason": "check gas"}, {"key": "hydrocarbon.x"}),
    ("step", {"name": "saturation", "find": "Rw"}, {"name": "saturation"}),
    ("runs", {"condition": "NET_PAY", "where": "VCL < 0.3"}, {"condition": "NET_PAY and VCL < 0.3"}),
    ("runs", {"condition": "NET_PAY or GAS", "where": "VCL < 0.3"}, {"condition": "NET_PAY or GAS", "where": "VCL < 0.3"}),
    ("runs", {"condition": "NET_PAY", "limit": 0}, {"condition": "NET_PAY"}),
    ("runs", {"condition": "NET_PAY", "limit": 5.0}, {"condition": "NET_PAY", "limit": 5}),
    ("runs", {"condition": "NET_PAY", "limit": 0.7}, {"condition": "NET_PAY", "limit": 0.7}),      # a threshold: an error says so
])
def test_fit_reads_what_the_shape_means(name, raw, want):
    assert fit(name, arguments(raw)) == want


def test_fit_is_idempotent():
    for name, raw in [("stats", {"curves": ["SW"], "zones": ["Z1-Z3"], "statistics": ["P10"]}),
                      ("runs", {"condition": "NET_PAY", "where": "VCL < 0.3", "limit": 0})]:
        once = fit(name, arguments(raw))
        assert fit(name, dict(once)) == once


# --- calc: the arithmetic (hand-written) ----------------------------------------------------------------------------

@pytest.mark.parametrize("expr,value,inputs", [
    ("78.8 + 58.4 + 11", 148.2, ["78.8", "58.4", "11"]),
    ("100 * 12.5 / 150.2", 100 * 12.5 / 150.2, ["100", "12.5", "150.2"]),
    ("(0.6939 - 0.00099) / (8403.5 - 8234)", (0.6939 - 0.00099) / (8403.5 - 8234), ["0.6939", "0.00099", "8403.5", "8234"]),
    ("(130.26 - 15.2372) / 27.5851", (130.26 - 15.2372) / 27.5851, ["130.26", "15.2372", "27.5851"]),
    ("0.29 × 0.1193", 0.29 * 0.1193, ["0.29", "0.1193"]),
    ("12.5% * 2", 25.0, ["12.5", "2"]),
    ("sqrt(0.25)", 0.5, ["0.25"]),
    ("log10(100)", 2.0, ["100"]),
    ("ln(2.718281828)", math.log(2.718281828), ["2.718281828"]),
    ("mean(0.21, 0.23, 0.25)", 0.23, ["0.21", "0.23", "0.25"]),
    ("max(3.5, 7.25) - min(3.5, 7.25)", 3.75, ["3.5", "7.25", "3.5", "7.25"]),
    ("-0.4515 + 1", 1 - 0.4515, ["0.4515", "1"]),
    ("2^3", 8.0, ["2", "3"]),
    ("1.5e-3 * 1000", 1.5, ["1.5e-3", "1000"]),
])
def test_calc_evaluates(expr, value, inputs):
    v, ins = evaluate(expr)
    assert abs(v - value) <= 1e-9 * max(1, abs(value)) and ins == inputs


@pytest.mark.parametrize("expr,says", [
    ("log(10)", "log10( ) or ln( )"), ("1 / 0", "division by zero"), ("SW * 2", "cannot use"),
    ("__import__('os')", "cannot use"), ("2 ** 1000", "exponent"), ("sqrt(-1)", "cannot take"),
    ("(-8) ** 0.5", "not a finite number"), ("1 +", "cannot read"), ("[1, 2]", "cannot use"), ("x = 1", "cannot read"),
])
def test_calc_refuses(expr, says):
    with pytest.raises(ToolError, match=re.escape(says)):
        evaluate(expr)


@pytest.mark.parametrize("raw,want", [
    ({"calc": "78.8 + 58.4"}, ("calc", "78.8 + 58.4")),
    ({"calc": {"expression": "1 + 2.5"}}, ("calc", "1 + 2.5")),
    ({"tool": "calc", "expression": "3 * 0.25"}, ("calc", "3 * 0.25")),
    ({"action": "calc", "expr": "3 * 0.25"}, ("calc", "3 * 0.25")),
])
def test_calc_actions_as_models_write_them(raw, want):
    assert coerce_action(raw) == want


# --- on real formations ---------------------------------------------------------------------------------------------

def _f():
    from test_b2_tools import F
    return next(f for t, f in F() if {"NET_PAY", "SW", "PHIE"} <= set(f.inv.curves) and len(f.view.zones) >= 3)


def _ledger():
    from petroharness.agent.ledger import Ledger
    return Ledger(_f())


@pytest.mark.data
@pytest.mark.parametrize("raw", [
    {"curves": ["SW"], "zones": True}, {"curves": ["SW"], "zones": ["all"]}, {"curves": ["SW"], "zones": [1, 2]},
    {"curves": ["SW"], "zones": ["Z1-Z3"]}, {"curves": ["SW"], "statistics": ["P10", "P90"]},
    {"curves": ["SW"], "statistics": ["p25", "p75", "geometric_mean"]}, {"curves": ["SW"], "where": "all samples"},
    {"curve": "SW"}, {"curves": ["SW"], "where": "Z2"}, {"curves": ["SW"], "where": "Z1-Z2 and SW < 0.9"},
    {"curves": ["SW"], "where": "PHIE - SW > -1"}, {"curves": ["SW"], "where": "DEPTH >= 0"},
])
def test_shapes_models_send_now_run(raw):
    led = _ledger()
    item, new = led.open("stats", raw)
    assert new and item.text and not led.errors


@pytest.mark.data
def test_percentiles_are_numpy_percentiles():
    from petroharness.agent.tools import stats
    f = _f()
    x = np.asarray(f.view.values("SW"), dtype=float)
    z = f.view.zones[0]
    want = np.percentile(x[z.indices][np.isfinite(x[z.indices])], 25)
    out = stats(f, ["SW"], zones=[z.zone_id], statistics=["p25"]).text
    shown = re.search(rf"{z.zone_id}\b.*?p25 (-?[\d.]+)", out).group(1)
    dec = len(shown.split(".")[1]) if "." in shown else 0
    assert abs(float(shown) - want) <= 0.5 * 10 ** -dec * 1.0001 + 1e-12          # at the precision it is shown


@pytest.mark.data
def test_a_zone_term_selects_the_zone_and_a_window_its_depths():
    from petroharness.agent.engine import select
    f = _f()
    z1, z2 = f.view.zones[0], f.view.zones[1]
    m = select(f, "Z2").mask
    assert m.sum() == len(z2.indices) and m[np.asarray(z2.indices)].all()
    m = select(f, "Z1-Z2").mask
    assert m.sum() == len(z1.indices) + len(z2.indices)
    top, base = z2.top, z2.base
    w = select(f, f"{top}-{base} {f.inv.depth_unit}").mask
    d = f.depth
    assert w.sum() == int(((d >= top - 1e-6) & (d <= base + 1e-6)).sum())
    assert (select(f, f"DEPTH >= {top} and DEPTH <= {base}").mask == w).all()
    with pytest.raises(ToolError, match="no zone Z999"):
        select(f, "Z999")


@pytest.mark.data
def test_a_side_adds_and_subtracts_curves():
    from petroharness.agent.engine import select
    f = _f()
    a, b = (np.asarray(f.view.values(c), dtype=float) for c in ("PHIE", "SW"))
    with np.errstate(invalid="ignore"):
        want = (a - b > -0.5) & np.isfinite(a) & np.isfinite(b)
        assert (select(f, "PHIE - SW > -0.5").mask == want).all()
        want = (a > b - 0.5) & np.isfinite(a) & np.isfinite(b)
        assert (select(f, "PHIE > SW - 0.5").mask == want).all()
        want = (a + 0.1 < b) & np.isfinite(a) & np.isfinite(b)
        assert (select(f, "PHIE + 0.1 < SW").mask == want).all()
    with pytest.raises(ToolError):
        select(f, "PHIE - NOSUCH > 0")


@pytest.mark.data
@pytest.mark.parametrize("name,raw,says", [
    ("runs", {"condition": "NET_PAY", "limit": 0.7}, "limit"),
    ("stats", {"curves": ["SW"], "zones": ["MICRO_PORES"]}, "no zone MICRO_PORES"),
    ("stats", {"curves": ["SW"], "where": "top of Z2"}, "cannot read"),
    ("profile", {"curves": ["SW", "PHIE"]}, "profile takes"),
])
def test_what_cannot_be_read_is_still_a_message(name, raw, says):
    led = _ledger()
    with pytest.raises(ToolError, match=re.escape(says)):
        led.open(name, raw)
    assert led.errors and not led.items


@pytest.mark.data
def test_a_statistic_the_tool_does_not_compute_is_said_and_the_call_runs():
    """The line says how to derive it with calc; the statistics it computes are served."""
    led = _ledger()
    item, _ = led.open("stats", {"curves": ["SW"], "statistics": ["share", "variance"]})
    first = item.text.splitlines()[0]
    assert first.startswith("no statistic 'share' in this tool") and "calc" in first
    assert "variance " in item.text and not led.errors


@pytest.mark.data
def test_calc_on_shown_numbers_is_an_item_a_claim_can_cite():
    from petroharness.agent.claims import Claims
    led = _ledger()
    e1, _ = led.open("runs", {"condition": "NET_PAY"})
    total = re.search(r"all zones: ([\d.]+)", e1.text).group(1)
    zt = re.search(r"\(([\d.]+)% of the zoned thickness\)", e1.text).group(1)
    item, new = led.calc(f"{total} * 2")
    assert new and item.id == "E2" and item.tool == "calc" and f"{total} (E1)" in item.text
    again, new2 = led.calc(f" {total}*2 ")
    assert again is item and not new2
    doubled = float(total) * 2
    from petroharness.agent.map import num
    c = Claims(["How much pay?"], led, "", "q", None, ("w",))
    c.apply([{"op": "add", "point": 1, "text": f"Twice the net pay is {num(doubled)} ft", "ev": ["E2"], "grade": "low",
              "means": "so the pay is thick enough to matter here"}])
    assert not [f for f in c.claims["C1"].flags if f.startswith("K3")], c.claims["C1"].flags
    c.apply([{"op": "add", "point": 1, "text": f"Pay is {num(doubled + 7.77)} ft", "ev": ["E2"], "grade": "low",
              "means": "so the pay is thick enough to matter here"}])
    assert [f for f in c.claims["C2"].flags if f.startswith("K3") and "calc" in f]
    assert float(zt) >= 0


@pytest.mark.data
@pytest.mark.parametrize("expr,says", [
    ("123.456789 + 1", "123.456789 is in none"),            # an input no result shows
    ("12.5", "computes nothing"),
    ("", "needs an expression"),
])
def test_calc_refuses_numbers_no_result_shows(expr, says):
    led = _ledger()
    led.open("runs", {"condition": "NET_PAY"})
    with pytest.raises(ToolError, match=re.escape(says)):
        led.calc(expr)
    assert len(led.items) == 1 and led.errors[-1][0] == "calc"


@pytest.mark.data
def test_calc_needs_a_shown_number_and_small_whole_numbers_are_constants():
    led = _ledger()
    with pytest.raises(ToolError, match="at least one number"):
        led.calc("40 + 2")                                  # nothing opened: constants only
    led.open("runs", {"condition": "NET_PAY"})
    total = re.search(r"all zones: ([\d.]+)", led.items[0].text).group(1)
    item, _ = led.calc(f"100 * {total} / 97")
    assert f"{total} (E1)" in item.text and re.search(r"\b(100|97) \((constant|E1)\)", item.text)


@pytest.mark.data
def test_calc_takes_numbers_from_the_map_and_question():
    led = _ledger()
    item, _ = led.calc("1234.5 - 1200.25", shown="Interval: 1200.25-1234.5 ft")
    assert "map or question" in item.text and abs(item.numbers[0] - 34.25) < 1e-9


@pytest.mark.data
def test_calcs_run_beside_the_three_actions():
    import json
    from petroharness.llm import Usage
    from test_b5_loop import Script, _session
    from petroharness.agent.loop import investigate
    s = _session()
    llm = Script([
        {"points": ["How thick is the pay?"], "intent": "value", "edits": [{"op": "add", "point": 1, "text": "Pay is thin", "grade": "hypothesis"}],
         "next": [{"runs": "NET_PAY"}], "done": False},
        None, {"edits": [], "next": [], "done": True}])
    trace = {}

    def chat(stage, messages, usage, max_tokens, retry=False):
        llm.sent.append((stage, messages))
        usage.log.append({"stage": stage})
        if stage == "step_2":
            total = re.search(r"all zones: ([\d.]+)", next(e for e in s.ledger.items if e.tool == "runs").text).group(1)
            return json.dumps({"edits": [], "next": [{"calc": f"{total} * 2"}, {"calc": f"{total} / 2"}, {"calc": f"{total} + 1"},
                                                     {"calc": f"{total} - 1"}, {"stats": ["SW"]}, {"stats": ["PHIE"]},
                                                     {"profile": "SW"}], "done": False})
        r = llm.replies.pop(0) if llm.replies else '{"edits": [], "next": [], "done": true}'
        if r is None:
            r = llm.replies.pop(0)
        return r if isinstance(r, str) else json.dumps(r)
    llm.chat = chat
    investigate(llm, s, Usage(), 4000, trace, max_steps=4)
    tools = [e.tool for e in s.ledger.items]
    assert tools.count("calc") == 3 and tools.count("stats") == 3 and tools.count("profile") == 1     # + the first look
    assert any(a.startswith("calc ") for a in trace["steps"][1]["actions"])


# --- more shapes from traced investigations ------------------------------------------------------------------------

@pytest.mark.parametrize("name,raw,want", [
    ("stats", {"curves": ["SW"], "where": "all zones pooled"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "where": "zones pooled"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "where": "all available samples"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "where": "all zones for completeness"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "where": "all curves over Z2"}, {"curves": ["SW"], "zones": ["Z2"]}),
    ("stats", {"curves": ["SW"], "where": "all interval, Z1"}, {"curves": ["SW"], "zones": ["Z1"]}),
    ("stats", {"curves": ["SW"], "zones": ["Z3"], "where": "all interval, Z1"}, {"curves": ["SW"], "zones": ["Z3"]}),
    ("stats", {"curves": ["SW"], "where": "SW < 0.5 in all zones"}, {"curves": ["SW"], "where": "SW < 0.5 in all zones"}),
    ("stats", {"curves": ["SW"], "where": "Z5 limestone; fill zone-level quality rows"},
     {"curves": ["SW"], "where": "Z5 limestone; fill zone-level quality rows"}),
    ("stats", {"curves": ["SW"], "statistics": True}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "zones": 2}, {"curves": ["SW"], "zones": ["Z2"]}),
    ("stats", {"curves": ["SW"], "zones": ["Z1..Z3"]}, {"curves": ["SW"], "zones": ["Z1", "Z2", "Z3"]}),
    ("stats", {"curves": ["SW"], "zones": ["Z2…Z3"]}, {"curves": ["SW"], "zones": ["Z2", "Z3"]}),
])
def test_more_shapes_are_read_as_meant(name, raw, want):
    assert fit(name, arguments(raw)) == want


@pytest.mark.data
def test_an_argument_a_tool_does_not_take_is_ignored_and_said():
    from petroharness.agent.schemas import call
    led = _ledger()
    f = led.f
    pair = [c for c in ("PHIE", "SW", "GR", "VCL") if c in f.inv.curves][:2]
    r = call(f, "compare", {"a": pair[0], "b": pair[1], "limit": 5})
    assert r.text.startswith("(ignored limit: compare takes a, b, zones, tolerance, where)")
    item, new = led.open("compare", {"a": pair[0], "b": pair[1], "limit": 5})
    again, new2 = led.open("compare", {"a": pair[0], "b": pair[1]})
    assert new and again is item and not new2                          # the ignored argument is not part of the call
    r = call(f, "pay_summary", {"curves": ["GR"], "basis": "zoned"})
    assert r.text.startswith("(ignored curves, basis: pay_summary takes no arguments)")


@pytest.mark.data
def test_a_section_named_under_another_family_is_found_by_its_name():
    from petroharness.agent.schemas import call
    f = _f()
    names = [s.key.split(".")[-1] for s in f.inv.sections]
    unique = [s for s in f.inv.sections if names.count(s.key.split(".")[-1]) == 1]
    s = unique[0]
    got = call(f, "section", {"key": "elsewhere." + s.key.split(".")[-1]})
    assert got.text == call(f, "section", {"key": s.key}).text
    dup = [n for n in set(names) if names.count(n) > 1]
    if dup:
        with pytest.raises(ToolError, match="sections"):
            call(f, "section", {"key": "elsewhere." + dup[0]})


@pytest.mark.data
def test_absolute_value_in_a_condition():
    from petroharness.agent.engine import select
    f = _f()
    c = next((c for c in sorted(f.inv.curves) if np.nanmin(np.asarray(f.view.values(c), dtype=float)) < 0
              and np.nanmax(np.asarray(f.view.values(c), dtype=float)) > 0), None)
    if c is None:
        pytest.skip("no curve with both signs")
    x = np.asarray(f.view.values(c), dtype=float)
    thr = float(np.nanmedian(np.abs(x)))
    with np.errstate(invalid="ignore"):
        want = (np.abs(x) > thr) & np.isfinite(x)
    assert (select(f, f"|{c}| > {thr}").mask == want).all()
    assert (select(f, f"| {c} | > {thr}").mask == want).all()
    with pytest.raises(ToolError):
        select(f, "|NOSUCH| > 1")


def test_two_curves_for_a_one_curve_view_is_a_message():
    with pytest.raises(ToolError, match="profile takes one curve, not 2"):
        fit("profile", arguments({"curves": ["SW", "PHIE"]}))


@pytest.mark.parametrize("name,raw,want", [
    ("stats", {"curves": ["SW"], "where": "zoned thickness"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "where": "always"}, {"curves": ["SW"]}),
    ("stats", {"curves": ["SW"], "where": "all zones incl. Z3"}, {"curves": ["SW"], "zones": ["Z3"]}),
    ("runs", {"where": "NET_PAY"}, {"condition": "NET_PAY"}),
    ("runs", {"where": "NET_PAY", "condition": "SW < 0.5"}, {"condition": "SW < 0.5 and NET_PAY"}),
])
def test_still_more_shapes(name, raw, want):
    assert fit(name, arguments(raw)) == want


@pytest.mark.data
def test_abs_function_and_has_a_value_in_words():
    from petroharness.agent.engine import select
    f = _f()
    c = next((c for c in sorted(f.inv.curves) if np.nanmin(np.asarray(f.view.values(c), dtype=float)) < 0
              and np.nanmax(np.asarray(f.view.values(c), dtype=float)) > 0), None)
    if c is not None:
        assert (select(f, f"abs({c}) > 0.01").mask == select(f, f"|{c}| > 0.01").mask).all()
    g = next(iter(sorted(f.inv.curves)))
    for words in (f"{g} finite", f"{g} is valid", f"{g} present"):
        assert (select(f, words).mask == select(f, g).mask).all(), words
