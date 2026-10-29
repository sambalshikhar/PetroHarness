"""Every citation form models produce is removed before delivery; numbers and tables survive."""

import glob
import json
import os

import pytest

from petroharness.agent.compose import leftover_citations, strip_citations

CASES = [
    ("mean SW 0.45 [E1].", "mean SW 0.45."),
    ("values [E1, E4] here", "values here"),
    ("Z10 0.9767 [E1/E7]. BVW", "Z10 0.9767. BVW"),
    ("counts are available [E1-E5]. The", "counts are available. The"),
    ("not exported [E5–E8].", "not exported."),
    ("dual_water for 193 (E3). Zone", "dual_water for 193. Zone"),
    ("named statistics (E2, E3). The", "named statistics. The"),
    ("max |DRHO| = 0.02459 (E4/E6). The", "max |DRHO| = 0.02459. The"),
    ("core plugs [E1 card].", "core plugs."),
    ("not independent evidence [E6? no, card]. No", "not independent evidence. No"),
    ("unflagged [E1; borehole quality: 14% per card]. SP", "unflagged. SP"),
    ("unavailable [card].", "unavailable."),
    ("per 10 m of depth E5. SXO", "per 10 m of depth. SXO"),
    ("ranges E1–E3 show", "ranges show"),
]


@pytest.mark.parametrize("raw,clean", CASES)
def test_citation_forms_are_removed(raw, clean):
    assert strip_citations(raw) == clean


@pytest.mark.parametrize("keep", [
    "| Z1 | Sand | 2801.4–2812.2 | 5.708 |",
    "RDEP (ohm.m) is 0.89 (Z6), VCL < 0.30 (cutoff)",
    "EIRIKSSON MB. TOP has E-W trending beds; ratio 1E3",
    "see the card for the Rw route",
])
def test_ordinary_text_is_kept(keep):
    assert strip_citations(keep) == keep


@pytest.mark.skipif(not os.environ.get("PETROHARNESS_RUNS"), reason="PETROHARNESS_RUNS is not set (a glob of saved run folders)")
def test_no_leftovers_on_stored_answers():
    """The stored answers of saved runs (PETROHARNESS_RUNS: a glob of run folders, each with responses/) hold no
    citation left after stripping."""
    files = glob.glob(os.path.join(os.environ["PETROHARNESS_RUNS"], "responses", "*.json"))
    if not files:
        pytest.skip("no responses in the PETROHARNESS_RUNS folders")
    left = [(f, x) for f in files for p in json.load(open(f))["qa_pairs"] for x in leftover_citations(strip_citations(p["answer"]))]
    assert not left, left[:5]
