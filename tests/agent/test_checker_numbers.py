"""The writer's number checker and its repair request, on the three numbers golden answers ended unresolved with
(2026-11-19): a thousands separator split ("~20,700 ppm" read as 20 and 700), a band edge written as a negative number
("3.7% < -0.02" from "PHID < PHIN - 0.02 in 3.7%"), and a wrong total the repair never fixed ("50 samples beyond
2 std" where the results show 9 + 11 + 11 + 12 + 8 = 51: the request named a bare "50" in an answer that also wrote
"50.8 %").

    .venv/bin/python -m pytest tests/agent/test_checker_numbers.py -q
"""
import gzip
import json
from pathlib import Path

import pytest

from petroharness.agent.checks import number, number_provenance, shown_values

GOLDEN = Path(__file__).resolve().parents[1] / "golden"


def _bad(text: str, card: str) -> list:
    return number_provenance(text, card, [])[0]


def test_a_thousands_separator_is_one_number():
    assert number("20,700") == 20700 and number("-0.02") == -0.02
    assert _bad("plausible for ~20,700 ppm water", "consistent with WSAL 20700 mg/l") == []
    assert _bad("plausible for ~20,800 ppm water", "consistent with WSAL 20700 mg/l") == ["20,800"]
    assert _bad("zones 21,22 and 23", "zones 21, 22 and 23") == []          # a list without spaces stays a list


def test_thousands_grouped_by_spaces_are_one_number_where_the_record_shows_it():
    """Benchmark N2: a permeability answer wrote "3 114.1112 mD over 5 192 samples" and "Z6 (6 376)", and 20 of its
    numbers were read as pairs of others. Digits grouped by spaces read as one number where that number is one the
    record shows; digits that stand apart otherwise stay as written."""
    card = "pooled mean 3114.1112 over 5192 samples; Z6 6376; Z3 10000"
    assert _bad("the pooled mean is 3 114.1112 mD over 5 192 samples; Z3 (10 000) > Z6 (6 376)", card) == []
    assert _bad("the pooled mean is 3 114.1113 mD", card) == ["114.1113"]    # not the record's: as written (3 a small count)
    assert _bad("Z3 (10 000), 6 376", card) == []                                    # before a comma too


def test_an_ordinal_is_a_rank_not_a_value():
    """Benchmark N2: "the 90th percentile is 0.1696" and "10th-90th percentiles" left 90 unresolved. An ordinal is a
    rank (the one grammar, agent.numbers.NUM): not read as a number; p90 and Z12 stay names."""
    from petroharness.agent import numbers as N
    assert N.values("the 90th percentile is 0.1696; 10th-90th percentiles 0.85-1.25; the 1st, 2nd and 33rd") == \
        [0.1696, 0.85, 1.25]
    assert _bad("its 90th percentile is 0.1696", "p90 0.1696") == []


def test_a_band_edge_shown_after_a_minus_supports_its_negative():
    shown = "PHID > PHIN + 0.02 in 82.1%, PHID < PHIN - 0.02 in 3.7%, within 0.02 in 14.2%"
    assert -0.02 in shown_values(shown) and -82.1 not in shown_values(shown)
    assert _bad("3.7% < -0.02, 14.2% within", shown) == []
    assert _bad("a difference of -0.02", "within 0.02 of each other") == ["-0.02"]   # no band: the sign is unshown
    assert -2.0 in shown_values("beyond mean +/- 2 std") and -0.5 in shown_values("± 0.5")


def test_a_total_passes_beside_the_numbers_it_adds_and_only_when_right():
    card = "DTC: beyond: 9 samples; RDEP: beyond: 11 samples; GR: beyond: 11 samples; PERM: 12 samples; NPHI: 8 samples"
    assert _bad("51 samples beyond 2 std (DTC 9, RDEP 11, GR 11, PERM 12, NPHI 8)", card) == []
    assert _bad("50 samples beyond 2 std (DTC 9, RDEP 11, GR 11, PERM 12, NPHI 8)", card) == ["50"]
    assert _bad("50 samples beyond 2 std (9-12 per curve)", card) == ["50"]


def _writer(ds: str, task: str) -> tuple:
    """(the writer's user prompt, its draft) of a golden answer."""
    rows = [json.loads(line) for line in gzip.open(GOLDEN / ds / f"{task}.tape.jsonl.gz", "rt")]
    prompt = next(r for r in rows if "RESULTS (everything" in r["request"]["messages"][-1]["content"])
    result = json.load(gzip.open(GOLDEN / ds / f"{task}.result.json.gz", "rt"))
    return prompt["request"]["messages"][-1]["content"], result["trace"].get("draft") or result["answer"]


@pytest.mark.parametrize("ds, task, number_, ok", [("geolink", "t1594603efd", "20,700", True),
                                                   ("danish", "tdb5251a5d3", "-0.02", True),
                                                   ("geolink", "te5c93fc23f", "50", False)])
def test_the_golden_answers_numbers_against_what_their_writer_was_shown(ds, task, number_, ok):
    """Each answer's sentence with the number, against the writer's own prompt (its results, map and card)."""
    if not (GOLDEN / ds / f"{task}.tape.jsonl.gz").exists():
        pytest.skip("golden tapes not in this checkout")
    prompt, draft = _writer(ds, task)
    raw = number_.lstrip("-")
    sentence = next((s for s in draft.replace("−", "-").split(". ") if raw in s and
                     (number_ != "50" or "50 samples" in s)), None)
    if sentence is None:
        pytest.skip(f"the recorded draft no longer states {number_}")
    assert (number_ not in _bad(sentence.replace("−", "-"), prompt)) == ok, sentence


def test_the_repair_request_quotes_where_each_number_stands():
    from petroharness.agent.graph import _repair_ask, where_said
    draft = ("Correlation: EXCELLENT_LOG_CONSISTENCY 50.8 % (E6). Zone-baseline 2 std screens find 50 samples beyond "
             "2 std across DTC, RDEP, GR, PERM and NPHI (9-12 per curve). Adjacent changes exceed 1 us/ft.")
    assert where_said(draft, "50") == ("Zone-baseline 2 std screens find 50 samples beyond 2 std across DTC, RDEP, GR, "
                                       "PERM and NPHI (9-12 per curve)")
    ask = _repair_ask(["50"], [], [], [], draft)
    assert '50 (in "Zone-baseline 2 std screens find 50 samples beyond' in ask
    assert "A total, a difference or a share you worked out passes when the shown numbers it comes from stand beside it" in ask
    assert where_said(draft, "77") == "" and '77' in _repair_ask(["77"], [], [], [], draft)


@pytest.mark.parametrize("raw,written", [("-0.05", "-0.05"), ("-0.05", "\u22120.05"), ("\u22120.05", "-0.05"),
                                         ("9-12", "9\u201312"), ("-3.2%", "-3.2 %")])
def test_the_repair_request_finds_a_number_written_with_any_dash(raw, written):
    from petroharness.agent.graph import where_said
    draft = f"The density shift is {written} over the zone. Nothing else."
    assert where_said(draft, raw) == f"The density shift is {written} over the zone"


def test_a_claim_with_a_thousands_separator_is_checked_not_crashed():
    """Question suite: the claim check turned the checker's '4,000' into float('4,000') and the question was lost
    (ValueError after 564 s). Every consumer of the checker's numbers reads them with checks.number."""
    from petroharness.agent.claims import Claims, _share
    from petroharness.agent.ledger import Ledger
    from _wells import CASES, formation_of
    f = formation_of(CASES["brent"])
    led = Ledger(f)
    led.open("stats", {"curves": ["PHIE"]})
    cl = Claims(["What is the porosity?"], led, "", "q", f.view, ("30/6-5",))
    msgs = cl.apply([{"op": "add", "point": 1, "text": "About 4,000 samples hold PHIE, roughly 12,345.6 m of log",
                      "ev": ["E1"], "grade": "moderate"}])
    assert msgs == [] and any(f.startswith("K3") for f in cl.claims["C1"].flags)   # flagged as unshown, not a crash
    assert _share("25", "25% of the 1,000 samples, 250 of 1,000") is True


def test_a_flag_keeps_its_numbers_as_data_and_the_writer_reads_them_whole():
    """The claim check keeps a K3 flag's numbers with the claim (Claim.unshown); the writer reads that, never the
    flag's text ("4,000, 0.25" split at ", " was a parse of the harness's own sentence)."""
    from petroharness.agent.claims import Claims
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.writer import k3_split
    from _wells import CASES, formation_of
    f = formation_of(CASES["brent"])
    led = Ledger(f)
    led.open("stats", {"curves": ["PHIE"]})
    cl = Claims(["What is the porosity?"], led, "", "q", f.view, ("30/6-5",))
    cl.apply([{"op": "add", "point": 1, "text": "About 4,000 samples hold PHIE, 1.5e-3 of them flagged",
               "ev": ["E1"], "grade": "moderate"}])
    held, none = k3_split(cl.claims["C1"])
    assert "4,000" in none and "1.5e-3" in none and held == {}


def test_one_grammar_reads_every_written_number():
    from petroharness.agent import numbers as N
    from petroharness.agent.ledger import _claimed
    assert N.values("20,700 ppm, zones 21,22 and 2841-2865 m, R43, Z3, SW_ARCHIE_A1, 1.5e-3, 12.5 %") == \
        [20700, 21, 22, 2841, 2865, 0.0015, 12.5]
    assert _claimed("4,000") == (4000.0, 0.5) and _claimed("1.5e-3") == (0.0015, 0.00005)
    assert N.decimals("0.210") == 3 and N.decimals("20,700") == 0


def test_a_count_with_its_population_is_checked_as_a_pair():
    """Question suite F18 (and golden te5c93fc23f: '75 changes exceed 1 us/ft' written '75 of 254 zoned samples'): a
    'k of N' passes only when one shown line holds k with N, or N - k with N (those that are not: 'missing in 41 of
    50' from 'PERM at 9 of 50 samples'). On the 36 golden answers 284 pairs are written and only that one is flagged."""
    card = "Z1, PERM: n 9 of 50, mean 12.3\nzones pooled: 75 changes exceed 1 us/ft\nzones pooled, DTC: n 254 of 254"
    assert _bad("PERM exists at 9 of 50 samples", card) == []
    assert _bad("PERM is missing in 41 of 50 samples", card) == []                 # the complement
    assert _bad("jumps exceed 1 us/ft at 75 of 254 zoned samples", card) == ["75 of 254"]
    assert _bad("3 of 5 zones", card) == []                                       # small counts are exempt


def test_a_pair_is_found_in_every_row_of_a_result_not_only_its_cut_text():
    """Question suite B06 (b0614f8e): '34 of 88' stood in a row of a long result beyond its cut text; the direct
    writer reads results whole, so it was shown, but the pair check read the cut text and flagged it through three
    repair rounds. The pair check reads the rows the item's values come from."""
    import re
    from petroharness.agent.claims import _Item
    from petroharness.agent.ledger import Ledger
    from _wells import CASES, formation_of
    f = formation_of(CASES["brent"])
    led = Ledger(f)
    led.open("stats", {"curves": ["GR", "RHOB", "NPHI", "DTC", "PHIE_CC", "PHIT", "PHIE", "PERM_CC", "PERM", "PHIC",
                                  "VCL", "SW"]})
    e = led.items[0]
    row = next(ln for ln, _ in e.rows if "PHIC" in ln and ln.lstrip().startswith("Z7 "))
    assert row.strip()[:60] not in e.text                                   # beyond the cut
    k, n = re.search(r"n (\d+) of (\d+)", row).groups()
    assert number_provenance(f"Z7 has {k} of {n} PHIC plugs.", "", [_Item(e)])[0] == []


def test_a_total_passes_beside_its_breakdown_with_each_part_s_share():
    """Question suite S01 (b0614f8e): '3474 excluded samples are split as 662 bad hole (18.1%), 2799 evaporite
    (76.4%), 12 coal (0.3%) and 1 halite (0.0%)' was flagged through two repair rounds: the shares broke the run of
    counts the total was checked against. A count's run is read over the sentence's counts; a wrong total still fails."""
    card = ("class 1 (evaporite) 76.4% (2799 samples), class 3 (coal) 0.3% (12 samples), class 2 (halite) 0.0% (1 "
            "samples), class 4 (bad_hole) 18.1% (662 samples)")
    ok = "the remaining 3474 excluded samples are split as 662 bad hole (18.1%), 2799 evaporite (76.4%), 12 coal (0.3%) and 1 halite (0.0%)"
    assert _bad(ok, card) == []
    assert _bad(ok.replace("3474", "3475"), card) == ["3475"]


def test_a_signed_change_and_a_share_pass_beside_their_numbers():
    """Golden danish ta58af6e662 and t1141335d31 (3adda7f0): '78.375 to 74.625 at 10012.5 ft (-3.75 us/ft)' and
    '30 of 185 samples (16.2%)' were left unresolved: the derived rule took a difference without its sign and no
    share of two numbers. Both pass beside the numbers they come from, and only when right."""
    card = "DTC 78.375 at 10012 ft, 74.625 at 10012.5 ft; BAD_HOLE: n 185 of 185, set in 30 samples"
    assert _bad("78.375 to 74.625 at 10012.5 ft (-3.75 us/ft)", card) == []
    assert _bad("78.375 to 74.625 at 10012.5 ft (-3.85 us/ft)", card) == ["-3.85"]
    assert _bad("bad hole at 30 of 185 samples (16.2%)", card) == []
    assert _bad("bad hole at 30 of 185 samples (17.2%)", card) == ["17.2%"]


def test_a_pair_whose_count_is_a_total_written_with_its_arithmetic_passes():
    """Question suite B13 (3adda7f0): '32 + 17 + 75 = 124 of the 229 SW > 0.9 samples': 124 is a total the sentence
    shows the arithmetic of, and 229 a shown population; no line holds 124 with 229. A pair whose count is such a total
    passes beside a shown N; a shown count paired with an N no line pairs it with is still flagged."""
    card = "Z13 SW > 0.9: n 32\nZ14 SW > 0.9: n 17\nZ15 SW > 0.9: n 75\nevery sample where SW > 0.9 (229 samples)"
    assert _bad("Z13, Z14 and Z15 alone carry 32 + 17 + 75 = 124 of the 229 SW > 0.9 samples", card) == []
    assert _bad("Z13, Z14 and Z15 alone carry 32 + 17 + 75 = 125 of the 229 SW > 0.9 samples", card) == ["125 of the 229"]
    assert _bad("75 of 229 samples", card) == ["75 of 229"]


def test_a_difference_in_a_clause_after_a_semicolon_and_values_listed_with_slashes():
    """Golden tafd6c1d922 (re-recorded 11-20): "PHIE mean 0.1258; PHIT mean 0.1260 (diff 0.0002)" in a table cell was
    flagged, the semicolon read as the end of a sentence; "PERM med 40.0793/50.5081/36.5042" (three thirds' medians)
    was read as a count with its population. A sentence ends at . ! ? or a line; a count is a whole number."""
    from petroharness.agent.checks import number_provenance
    card = "PHIE mean 0.1258\nPHIT mean 0.126\nPERM median 40.0793\nPERM median 50.5081\nPERM median 36.5042"
    assert number_provenance("PHIE mean 0.1258; PHIT mean 0.1260 (diff 0.0002).", card, [])[0] == []
    assert number_provenance("PERM med 40.0793/50.5081/36.5042 by thirds.", card, [])[0] == []
    assert number_provenance("PHIT mean 0.1260 (diff 0.0003).", card, [])[0] == ["0.0003"]   # still checked
    assert number_provenance("Here 34 of 88 samples.", "34 of 90 samples", [])[0] == ["34 of 88"]   # a count's pair


@pytest.mark.parametrize("written, read", [
    ("opens at twenty-four forty-one metres", "opens at 2441 metres"),
    ("runs to twenty-four fifty-seven point nine", "runs to 2457.9"),
    ("one hundred sixteen point nine metres, seven hundred sixty-eight samples", "116.9 metres, 768 samples"),
    ("two thousand eight hundred forty-one m", "2841 m"), ("the one hundred and twenty samples", "the 120 samples"),
    ("between twenty and thirty percent", "between 20 and 30 percent"), ("one of the three zones", "one of the three zones"),
    ("point zero five", "0.05"), ("and the rest", "and the rest")])
def test_numbers_written_in_words_are_read_as_their_digits(written, read):
    from petroharness.agent.numbers import spelled_as_digits
    assert spelled_as_digits(written) == read


def test_a_number_written_in_words_is_checked_like_digits():
    """Question suite P7: an answer wrote the Brent's top as "twenty-four forty-one metres" (the record: 2841), and the
    checker, reading digits only, let it pass."""
    card = "BRENT GP. 2841-2958 m, 768 samples"
    assert _bad("The group opens at twenty-four forty-one metres.", card) == ["2441"]
    assert _bad("The group opens at twenty-eight forty-one metres over seven hundred sixty-eight samples.", card) == []


@pytest.mark.parametrize("text, card, flagged", [
    ("PHIE ranges 0.12 to 0.24, mean 0.18.", "PHIE min 0.12, max 0.24", ["0.18"]),       # a midpoint is no mean
    ("PHIE is 0.12, 0.24 and 0.21, mean 0.19.", "PHIE 0.12; 0.24; 0.21", []),             # a mean of three, shown
    ("Net pay is 12 m thick.", "NET_PAY 31.5 m", ["12"]),                                  # a small measure
    ("Zone 3 holds 12 runs.", "NET_PAY 31.5 m", []),                                       # a small count
])
def test_with_tight_numbers_a_midpoint_is_no_mean_and_a_small_measure_is_checked(text, card, flagged):
    """Off (as today) a mean of two stated numbers passes whatever it is, and whole numbers below 20 are
    never checked; with tight_numbers a mean needs three values, and a small whole number written with a unit is."""
    from petroharness import options
    assert number_provenance(text, card, [])[0] == []
    with options.use(tight_numbers=True):
        assert number_provenance(text, card, [])[0] == flagged


@pytest.mark.parametrize("text, card, flagged", [
    ("Z3 SW is 0.45.", "PHIE by zone\nZ5 0.45\nSW by zone\nZ3 0.31", ["0.45"]),          # 0.45 only where Z5 PHIE is
    ("Z3 SW is 0.45.", "SW by zone\nZ3 0.45", []),                                        # on the line naming Z3
    ("SW is 0.45 in Z5.", "| zone | SW |\n|---|---|\n| Z5 | 0.45 |", []),                 # a row, its header names SW
    ("The porosity is 0.45.", "PHIE by zone\nZ5 0.45", []),                               # the sentence names neither
])
def test_with_tight_numbers_a_number_tied_to_a_curve_or_zone_is_read_where_it_is_named(text, card, flagged):
    """Off (as today) a number passes on any line that shows it ('Z3 SW 0.45' on a PHIE line of Z5); with
    tight_numbers a number in a sentence naming curves or zones must be shown on a line naming one of them (the line,
    its result's first line or its table's header)."""
    from petroharness import options
    assert number_provenance(text, card, [])[0] == []
    with options.use(tight_numbers=True):
        assert number_provenance(text, card, [])[0] == flagged
