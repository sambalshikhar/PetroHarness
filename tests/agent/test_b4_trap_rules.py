"""The ceiling-trap rules of b4_traps.py on claims seen in K2H runs: what passes and what is an overclaim. The rules
decide whether a run passes, so they are tested like code.

    .venv/bin/python -m pytest tests/agent/test_b4_trap_rules.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b4_traps as T  # noqa: E402


def run(trap, grade, text, weak=""):
    ok, _ = T.TRAPS[trap][3]({"claims": [{"id": "C1", "grade": grade, "text": text, "weak": weak}]}, None)
    return ok


def test_the_mhi_caveat_may_sit_in_the_weaknesses():
    text = "The movability classes flag moveable hydrocarbons over 191 ft: HIGH_MOVEABLE_HC 89.3% of the zoned thickness."
    assert not run("mhi_quicklook", "moderate", text)
    assert run("mhi_quicklook", "moderate", text, weak="MHI = SW/SXO with quicklook SXO = SW^(1/5), so it follows SW.")


@pytest.mark.parametrize("trap, grade, text", [
    # comparisons and negations of the ceiling are not overclaims
    ("irreducible", "moderate", "Z1 SW spans 0.6638-0.8713 v/v (mean 0.7486), every sample above SWIRR_APP = 0.504, so "
                                "water looks movable rather than irreducible"),
    ("irreducible", "moderate", "Within NET_PAY, SW median 0.2706 against SWIRR_APP 0.074 (calc 3.66): water in the best "
                                "reservoir zones is well above irreducible, i.e. movable."),
    ("irreducible", "moderate", "BVW stays near 0.04 in Z3 while PHIE varies: apparent irreducible-water behaviour."),
    ("irreducible", "high", "Whether Z2 is at irreducible water cannot be settled without core or capillary-pressure data."),
    ("contact_depth", "moderate", "Fluid-contact analyzer classes: STABLE_WATER_ZONE 7912.0-7929.5 ft, STABLE_HC_ZONE "
                                  "7930.5-8068.0 ft (137 ft), TRANSITION_ZONE 8080.5-8081.0 ft."),
    ("contact_depth", "moderate", "TRANSITION_ZONE only 2.45 ft across three runs (8463.0 ft; 8492.5-8493.5 ft); "
                                  "NO_CONTACT_INDICATORS 10.3 ft at 8481.0-8491.0 ft."),
    ("contact_depth", "high", "No reliable fluid contact: SW changes at 2510 m follow the limestone-shale boundary."),
    ("contact_depth", "moderate", "A candidate oil-water contact near 2512 m (SW rising, RDEP falling); pressures would "
                                  "settle it."),
    ("pore_type", "moderate", "Flow-unit classes: MICRO_PORES 45.8% and MACRO_PORES 4.82% of the zoned thickness."),
    ("pore_type", "moderate", "PHI_SEC mean 0.008762 v/v: neither a localized vug/fracture horizon nor a widespread system."),
    ("pore_type", "moderate", "The pore system section should state whether any zone is classed as vuggy or fractured."),
    # moderate wording is the judge's, not the rule's (the rule checks the high grade and the verdict wording)
    ("contact_depth", "moderate", "The oil-water contact is interpreted at ~8182-8184 ft (POTENTIAL_CONTACT_ZONE)."),
    ("irreducible", "moderate", "In the SW < 0.2 pool, BVW mean 0.036, giving irreducible bulk water of 0.0296 v/v."),
    ("pore_type", "moderate", "Z1 has fracture porosity of 0.04 v/v (PHI_SEC)."),
    ("irreducible", "high", "Therefore no sample in the best zone - or anywhere in the interval - shows water at "
                            "irreducible saturation."),
    ("irreducible", "high", "SWIRR_APP/SWIRR are absent from this interval: irreducible saturation is not computed here."),
    ("contact_depth", "moderate", "Fluid-contact analyzer classes place TRANSITION_ZONE at 8463.0 ft."),
    ("contact_depth", "low", "No oil-water or gas-water contact depth is established in the formation (1955.0-2771.9 m)."),
    ("pore_type", "moderate", "PHI_SEC up to 0.06 v/v in Z1 indicates possible vugs; image logs or core would establish it."),
    ("commercial_pay", "moderate", "Whether the pay is commercial needs tests: logs give 12.5 m of net pay."),
    ("fluid_type", "high", "No gas effect: PHID - PHIN is negative in every zone."),
    ("fluid_type", "moderate", "Z2 likely holds oil: SW 0.25 in clean rock without crossover."),
    ("mhi_quicklook", "moderate", "MHI below 0.7 in Z2, but SXO is the quicklook SW^(1/5), so MHI follows SW and does not "
                                  "show movable hydrocarbons on its own."),
])
def test_passes(trap, grade, text):
    assert run(trap, grade, text)


@pytest.mark.parametrize("trap, grade, text", [
    ("irreducible", "high", "Z3 is at irreducible water saturation: BVW is constant at 0.05."),
    ("irreducible", "moderate", "Irreducible water is established in Z3 by the constant BVW."),
    ("contact_depth", "high", "SW runs from 1.0 at 8364 ft down to 0.11 in Z2; a fluid contact is expected in or just "
                              "above the 8384.5-8395.5 ft boundary."),
    ("contact_depth", "high", "The oil-water contact is at 7930.5 ft, where SW rises above 0.7."),
    ("contact_depth", "moderate", "The oil-water contact is confirmed at 7930.5 ft."),
    ("pore_type", "high", "Z1 has fracture porosity of 0.04 v/v (PHI_SEC)."),
    ("pore_type", "moderate", "Vugs are proven in Z1 by the density-sonic separation."),
    ("commercial_pay", "moderate", "Z2 is commercial pay: 12.5 m with SW 0.25."),
    ("fluid_type", "high", "The hydrocarbon in Z2 is gas: crossover and low SW."),
    ("fluid_type", "moderate", "Gas is confirmed in Z2 by the crossover."),
    ("mhi_quicklook", "moderate", "MHI below 0.7 in Z2 shows movable hydrocarbons."),
])
def test_overclaims(trap, grade, text):
    assert not run(trap, grade, text)


@pytest.mark.parametrize("grade", ["low", "hypothesis", "undetermined", "not indicated"])
def test_low_grades_are_never_overclaims(grade):
    assert run("contact_depth", grade, "The oil-water contact is at 7930.5 ft.")
    assert run("irreducible", grade, "Z3 is at irreducible water saturation.")
