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
    ("rebuilt from E5’s zone means of RMED", "rebuilt from the zone means of RMED"),   # a possessive id: a determiner
    ("corroborated by E12's EXTREME_DEVIATION_ZONE run", "corroborated by the EXTREME_DEVIATION_ZONE run"),
    ("held. E3's pooled line gives 0.21", "held. The pooled line gives 0.21"),
    ("E3’s pooled line gives 0.21", "The pooled line gives 0.21"),
    ("mean 0.04326 v/v over 18 samples, E4), but", "mean 0.04326 v/v over 18 samples), but"),   # no stray comma
    ("(the rw step, E7). It is", "(the rw step). It is"),
    ("(Z1 0.21; E3) and", "(Z1 0.21) and"),
    ("PHIE 0.21 (E3 E4). Next", "PHIE 0.21. Next"),
    # a parenthesis that cites and says something: the citation goes, what it says stays
    ("PHIE 0.21 (E10, n = 161). Next", "PHIE 0.21 (n = 161). Next"),
    ("sonic (E10, threshold 20 us/ft) holds", "sonic (threshold 20 us/ft) holds"),
    ("the fit (E12: R² 0.91 at zone level).", "the fit (R² 0.91 at zone level)."),
    ("the line (E1 pooled 0.1256 vs baseline 0.3132)", "the line (pooled 0.1256 vs baseline 0.3132)"),
    ("labels (E2/E5 k-bands and FZI classes)", "labels (k-bands and FZI classes)"),
    ("a screen (E1//E4 read as a class screen, not evidence)", "a screen (the results read as a class screen, not evidence)"),
    ("a change (E3 –3% over the zone)", "a change (–3% over the zone)"),                  # a minus sign is no separator
    ("model output (model output of the analyzers,/E10).", "model output (model output of the analyzers)."),
    ("one sample (max 0.2552 at 7808 ft, a single sample —/E7).", "one sample (max 0.2552 at 7808 ft, a single sample)."),
    ("index (E8; sqrt(PHIT × log10 PERM), range 0–1)", "index (sqrt(PHIT × log10 PERM), range 0–1)"),
    ("the rule (E8's definition of the deviation rule)", "the rule (the definition of the deviation rule)"),
    # ... and one that only names a part of what the writer was shown goes whole
    ("its limits (E6, Point 3 Limit).", "its limits."),
    ("the curves (E1, What The Curves Are).", "the curves."),
    ("the curves (E1, WHAT THE CURVES ARE).", "the curves."),
    ("not solved (E1, MAP).", "not solved."),
    ("the classes (E7, Map) and", "the classes and"),
    ("the record (E9 record).", "the record."),
    ("the route (E1, Workflow Map).", "the route."),
    ("the class (Map/E1).", "the class."),
    ("zone Z3 (see C8b/E7).", "zone Z3."),
    # an id that is its phrase's noun becomes "the result"; deleted, it left "of alone"
    ("I use E10 for pay character.", "I use the result for pay character."),
    ("from the Pearson lines of E6 alone.", "from the Pearson lines of the result alone."),
    ("is not part of E9.", "is not part of the result."),
    ("This rests on E2, which fits", "This rests on the result, which fits"),
    ("The LOW_SW flag in E3 (criterion `SW < 0.50`) is", "The LOW_SW flag in the result (criterion `SW < 0.50`) is"),
    ("Gas flags in E9/E5 carry no VCL", "Gas flags in the results carry no VCL"),
    ("at 8419 ft). E4 labels Z2 as gas", "at 8419 ft). The result labels Z2 as gas"),
    ("- E5 (`SW < 0.4`): all 270 samples", "- The result (`SW < 0.4`): all 270 samples"),
    ("**E3 vs draft:** the share", "**The result vs draft:** the share"),
    ("Result E3 shows 0.2", "The result shows 0.2"),
    ("as in the result E3 above", "as in the result above"),
    ("shown in the E7.", "shown in the result."),
    # ... one that qualifies a noun is deleted, and so is a chain's tail after a slash
    ("in the E7 zone contrast", "in the zone contrast"),
    ("from the complete E12 output", "from the complete output"),
    ("- **E4 carbonate analysis** returns NON_CARBONATE", "- **carbonate analysis** returns NON_CARBONATE"),
    ("- **E3/E4**: Deviation, consistency", "- Deviation, consistency"),
    ("included in the/E11 analysis", "included in the analysis"),
    ("- **/E9:** per-zone means", "- per-zone means"),
    ("sum to ~152 ft;/E6 zone fractions imply", "sum to ~152 ft; zone fractions imply"),
    ("(porosity step;/E9 show Z2 and Z4 at 0)", "(porosity step; the result show Z2 and Z4 at 0)"),
    ("statistics,/E5 analyzer class runs", "statistics, analyzer class runs"),
    ("shares;/E19-consistent shares give 125", "shares; consistent shares give 125"),
    # an id opening a bracket as its subject; a long square bracket that says something; one never closed
    ("the sections (E14/E16 now supply localizing context)", "the sections (the results now supply localizing context)"),
    ("was computed (E8 lists core-requiring functions).", "was computed (the result lists core-requiring functions)."),
    ("only [E8 pooled n=772, slope ≈17; the near-unity fits hold for the shallow macro-pore sands alone]",
     "only (pooled n=772, slope ≈17; the near-unity fits hold for the shallow macro-pore sands alone)"),
    ("span 2.868–12.0471 ohm.m [E1,\n\n| Z1 |", "span 2.868–12.0471 ohm.m\n\n| Z1 |"),
    # the writer's sections named with or without an id
    ("a fallback Rwa calculation (E1, Workflow). The", "a fallback Rwa calculation. The"),
    ("measurements (E13, map record).", "measurements."),
    ("near 1 (median 1.2861) (ZONE_TABLE,). There", "near 1 (median 1.2861). There"),
    ("zone contrast (WHAT THE CURVES ARE, MAP).", "zone contrast."),
    ("Because **E5** reports PHIE", "Because the result reports PHIE"),
    ("| Real but mild; three beds inverted,/E13 |\n", "| Real but mild; three beds inverted |"),
    ("non-pay zones have mean VCL 0.49 (E8 vs).", "non-pay zones have mean VCL 0.49."),
    ("- **E7** — Zone means for PERM", "- Zone means for PERM"),
    ("Zone-mean PERM ranking from/E8:\n\n1. Z3", "Zone-mean PERM ranking from the result:\n\n1. Z3"),
    ("- POTENTIAL_PAY: 0.607 m in Z1 (same thin run as E2).", "- POTENTIAL_PAY: 0.607 m in Z1 (same thin run as the result)."),
    ("to PHIT (fallback noted in/E13). Derived", "to PHIT (fallback noted in the result). Derived"),
    ("### Finding\n\nPer [E2] and [E4], permeability is", "### Finding\n\nPer the results, permeability is"),
    ("class shares from [E3]; porosity", "class shares from the result; porosity"),
    ("derived from an assumed 75F reference (E2, Limit Point 4).", "derived from an assumed 75F reference."),
    ("at the lower limit of 0 (E1, curve description). The", "at the lower limit of 0. The"),
]


@pytest.mark.parametrize("raw,clean", CASES)
def test_citation_forms_are_removed(raw, clean):
    assert strip_citations(raw) == clean


@pytest.mark.parametrize("keep", [
    "| Z1 | Sand | 2801.4–2812.2 | 5.708 |",
    "RDEP (ohm.m) is 0.89 (Z6), VCL < 0.30 (cutoff)",
    "EIRIKSSON MB. TOP has E-W trending beds; ratio 1E3",
    "see the card for the Rw route",
    "values (Z1, Z2) and log10(RT) with f(x)",
    "C1-C5 gas ratios (C1/C2 = 12) and the C3 map",
    "porosity from the E-log (Z2/Z3) and E3.5 units",
    "**PHIE** **0.21** and x ** 2",
    "the zone table (Z2, Z5) and the map of Z1",
    "(see the zone table)",
    "washout (CALI - BS > 1.5 in, |DRHO| > 0.15 g/cc) and",
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
