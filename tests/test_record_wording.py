"""The facts the record card reads from the workflow's decision lines, in the wording of Petrophys 3a9378e and in the
wording before it (src/petroharness/record/card.py, src/petroharness/well/prepare.py): the clauses of a line, the
curves its words stand for, the net-pay cutoffs, the inputs of a computed curve, the default SWIRR, and the saturation
routing read from the step's parameters. A wording Petrophys changes must not silently empty a line of the card.

    .venv/bin/python -m pytest tests/test_record_wording.py -q
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
from petroharness.record import card as K  # noqa: E402

RULES = yaml.safe_load((ROOT / "src/petroharness/resources/rules/curves.yaml").read_text())["construction"]
POLICY = {"cutoffs": {"vcl_max": 0.3, "sw_max": 0.7, "phie_min_clastic": 0.08, "phie_min_carbonate": 0.045}}
ROCK_QUALITY = ("RQI = 0.0314*sqrt(k/phi), PHI_Z = phi/(1-phi), FZI = RQI/PHI_Z; k is PERM_CC, and PERM at samples "
                "without PERM_CC; phi is PHIE_CC")


def test_a_line_splits_at_each_equation_and_its_words_name_curves():
    assert K.clauses(ROCK_QUALITY) == ["RQI = 0.0314*sqrt(k/phi)", "PHI_Z = phi/(1-phi)", "FZI = RQI/PHI_Z",
                                       "k is PERM_CC, and PERM at samples without PERM_CC", "phi is PHIE_CC"]
    assert K.bindings(ROCK_QUALITY) == {"k": "PERM_CC+PERM", "phi": "PHIE_CC"}
    assert K.bindings("x; phi is PHIE_CC (PHIE where it is missing)") == {"phi": "PHIE_CC+PHIE"}
    assert K.bindings("PHID = (rho_ma - RHOB) / (rho_ma - rho_fl)") == {}


def test_the_inputs_of_a_computed_curve_are_the_curves_the_line_binds():
    steps = {"rock_quality": {"decisions": [ROCK_QUALITY]},
             "mhi": {"decisions": ["MHI = SW / SXO at 18899 of 22176 samples, where SXO comes from invaded-zone "
                                   "resistivity; NaN where SXO is only SW^(1/5)"]},
             "porosity": {"decisions": ["PHIT from neutron and density: both logs at 1048 samples"]}}
    got = {c: K.recorded_inputs(steps, RULES[c]) for c in ("RQI", "PHI_Z", "FZI", "MHI", "PHIT")}
    assert got == {"RQI": ["PERM_CC", "PHIE_CC"], "PHI_Z": ["PHIE_CC"], "FZI": ["RQI", "PHI_Z"], "MHI": ["SW", "SXO"],
                   "PHIT": ["PHIN", "PHID"]}
    before = {"rock_quality": {"decisions": ["RQI = 0.0314*sqrt(PERM/PHIE); PHI_Z = PHIE/(1-PHIE); FZI = RQI/PHI_Z"]}}
    assert K.recorded_inputs(before, RULES["RQI"]) == ["PERM", "PHIE"]


def test_the_cutoffs_are_read_from_the_net_pay_line_in_either_wording():
    now = {"parameters": {}, "decisions": [
        "NET_ROCK: VCL < 0.3 -> 5313 samples (531.2 m)",
        "NET_RES: NET_ROCK and porosity > 0.08 (0.045 where carbonate) -> 5206 samples (520.5 m); porosity is PHIE_CC, "
        "and PHIE at samples without PHIE_CC",
        "NET_PAY: NET_RES and SW < 0.7 -> 2301 samples (230.1 m)"]}
    assert K.cutoff_fact(now, POLICY) == ("Cutoffs: NET_ROCK VCL<0.3; NET_RES +(PHIE_CC where present, otherwise PHIE)"
                                         ">0.08; NET_PAY +SW<0.7")
    before = {"parameters": {}, "decisions": ["NET_ROCK: VCL < 0.3 -> 1", "NET_RES: + PHIE > 0.08 -> 1",
                                              "NET_PAY: + SW < 0.7 -> 1"]}
    assert K.cutoff_fact(before, POLICY) == "Cutoffs: NET_ROCK VCL<0.3; NET_RES +PHIE>0.08; NET_PAY +SW<0.7"


def test_a_default_swirr_is_said_in_either_wording():
    for line in ("SWIRR_APP = 0.200 (default): only 3 hydrocarbon samples to estimate it from",
                 "SWIRR_APP = 0.200 fallback because hydrocarbon mask had 3 samples"):
        perm = {"parameters": {"swirr": 0.2, "swirr_metadata": {"hc_mask_samples": 3}}, "decisions": [line]}
        assert K.swirr_text(perm) == "SWIRR=0.2, a fallback default (only 3 samples)", line


def test_the_saturation_routing_is_read_from_the_step_s_parameters():
    sat = {"parameters": {"sw_model": "archie+indonesia", "sw_model_requested": "auto", "vcl_cutoff_for_routing": 0.3,
                          "sw_model_sample_counts": {"archie": 10, "indonesia": 5}},
           "decisions": ["Saturation equation chosen at each depth from the clay volume and lithology (sw_model='auto')"]}
    assert "SW model per sample, routed on VCL (cutoff 0.3) and lithology" in K.saturation_fact(sat, {}, {})
    asked = {"parameters": {**sat["parameters"], "sw_model_requested": "archie+indonesia"}, "decisions": []}
    assert "routing rule not recorded" in K.saturation_fact(asked, {}, {})


def test_a_value_petrophys_gives_with_its_unit_is_written_with_it():
    from petroharness.agent.library.shared import _shown, quantity
    assert quantity((230.0, "degF")) == (230.0, "degF") and quantity("65 degC") == (65.0, "degC")
    assert quantity(0.05) == (None, None) and quantity("archie") == (None, None)
    assert _shown((230.0, "degF")) == "230 degF" and _shown(0.05) == "0.05" and _shown("archie") == "archie"


def test_set_takes_a_value_with_a_space():
    """`/set bht="110 degC"` and `/set bht=110 degC m=1.8`: a word without "=" belongs to the value before it."""
    import shlex
    from petroharness.session import chat
    src = Path(chat.__file__).read_text()
    assert "shlex.split(rest)" in src and 'pairs[-1] += " " + w' in src
    words, pairs = shlex.split('bht=110 degC m=1.8'), []
    for w in words:
        if "=" in w or not pairs:
            pairs.append(w)
        else:
            pairs[-1] += " " + w
    assert pairs == ["bht=110 degC", "m=1.8"] and shlex.split('bht="110 degC"') == ["bht=110 degC"]

