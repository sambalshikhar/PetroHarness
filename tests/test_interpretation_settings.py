"""The interpretation settings a user may change (petroharness.well.settings): every Petrophys setting is offered once
or deliberately left out, with Petrophys's own choices, help and defaults; the harness's defaults are the policy's;
what cannot be used is said per setting; and a run's settings reach petrophys.interpret's options and the zone rule.
No data and no model: Petrophys is the only thing read.

    python -m pytest tests/test_interpretation_settings.py -q
"""
import dataclasses

import pytest

from petroharness import ask as A
from petroharness.config import ResourcePaths
from petroharness.well import settings as T
from petroharness.well.prepare import load_policy


def _fields():
    return [f for g in T.schema()["groups"] for f in g["fields"]]


def test_every_petrophys_setting_is_offered_once_or_left_out_on_purpose():
    from petrophys.workflow import DynamicWorkflowConfig as C
    library = {f.name for f in dataclasses.fields(C) if not f.name.startswith("_")}
    offered = [f["key"] for f in _fields() if f["petrophys"]]
    assert len(offered) == len(set(offered))
    assert set(offered) | T.HIDDEN >= library, sorted(library - set(offered) - T.HIDDEN)
    assert not set(offered) & T.HIDDEN
    assert set(offered) <= library


def test_each_setting_says_what_it_is():
    for f in _fields():
        assert f["label"] and f["help"], f["key"]
        assert f["kind"] in ("number", "integer", "switch", "choice", "bands", "text"), f["key"]
        if f["kind"] == "choice":
            assert f["choices"], f["key"]


@pytest.mark.parametrize("key, some", [("sw_model", {"archie", "indonesia", "dual_water"}),
                                       ("gr_method", {"linear", "larionov_tertiary"}),
                                       ("perm_method", {"timur", "coates"}), ("mud_type", {"WBM", "OBM"})])
def test_choices_are_petrophys_own(key, some):
    from petrophys.workflow import DynamicWorkflowConfig as C
    f = next(x for x in _fields() if x["key"] == key)
    assert some <= set(f["choices"])
    for c in f["choices"]:
        C(**{key: c})                              # every choice offered is one Petrophys accepts


def test_the_harness_defaults_are_the_policy_s():
    policy = load_policy(ResourcePaths().policy_file)
    by = {f["key"]: f for f in _fields()}
    assert by["zone_min_thickness_m"]["default"] == policy["zones"]["min_thickness_m"]
    assert by["zone_vcl_bands"]["default"] == list(policy["zones"]["fallback_vcl_bands"])
    assert by["zone_layout"]["default"] == "lithology_runs"
    assert by["vcl_cutoff"]["default"] == policy["cutoffs"]["vcl_max"]
    assert by["sw_cutoff"]["default"] == policy["cutoffs"]["sw_max"]
    assert by["rw"]["default"] is None and by["rw"]["unit"] == "ohm.m"      # read from the header or the data


@pytest.mark.parametrize("given, key, says", [
    ({"rw": "x"}, "rw", "give a number"),
    ({"sw_model": "nope"}, "sw_model", "choose one of"),
    ({"zone_vcl_bands": [0.6, 0.3]}, "zone_vcl_bands", "first below the second"),
    ({"zone_min_thickness_m": 0}, "zone_min_thickness_m", "above 0"),
    ({"m": -3.0}, "m", "greater than 0"),                                   # Petrophys's own validation
    ({"apply_hc_correction": "yes"}, "apply_hc_correction", "true or false"),
    ({"not_a_setting": 1}, "not_a_setting", "not a setting"),
])
def test_what_cannot_be_used_is_said_per_setting(given, key, says):
    assert says in T.validate(given)[key]


def test_usable_settings_pass_and_split():
    given = {"rw": 0.05, "sw_model": "indonesia", "a": 1.0, "zone_min_thickness_m": 1.0, "zone_vcl_bands": [0.25, 0.55]}
    assert T.validate(given) == {}
    petro, zones = T.split(given)
    assert petro == {"rw": 0.05, "sw_model": "indonesia", "a": 1.0}
    assert zones == {"zone_min_thickness_m": 1.0, "zone_vcl_bands": [0.25, 0.55]}


def test_a_run_s_settings_reach_petrophys_and_the_zone_rule():
    data = {"interpret": {"vcl_cutoff": 0.3, "sw_cutoff": 0.7}}
    A._interpretation(data, {"sw_cutoff": 0.6, "rw": 0.04, "zone_min_thickness_m": 0.5})
    assert data["interpret"] == {"vcl_cutoff": 0.3, "sw_cutoff": 0.6, "rw": 0.04}      # the user's over the policy's
    assert data["zone_min_thickness_m"] == 0.5
    with pytest.raises(ValueError, match="context profile"):
        A._interpretation({"interpret": {"context_profile": "geolink"}}, {"rw": 0.04})
    with pytest.raises(ValueError, match="cannot be used"):
        A._interpretation({"interpret": {}}, {"rw": "x"})
    zones_only = {"interpret": {"context_profile": "geolink"}}
    A._interpretation(zones_only, {"zone_min_thickness_m": 1.0})          # the zone rule is the harness's, any profile
    assert zones_only["zone_min_thickness_m"] == 1.0


def test_used_reads_the_step_record():
    class Prep:
        steps = {"vclay": {"parameters": {"gr_min": 40.8, "gr_max": 101.2, "gr_curve": "GR"}},
                 "rw": {"parameters": {"vcl_cutoff": 0.3, "phie_cutoff": 0.05}},
                 "net_pay": {"parameters": {"vcl_cutoff": 0.35, "phie_cutoff": 0.08, "sw_cutoff": 0.7}},
                 "saturation": {"parameters": {"a": 0.81, "m": 2.0}}}
    got = T.used(Prep())
    assert got["gr_min"] == {"value": 40.8, "step": "vclay"} and "gr_curve" not in got
    assert got["phie_cutoff"] == {"value": 0.08, "step": "net_pay"}         # the cutoffs net pay used
    assert got["a"]["value"] == 0.81
