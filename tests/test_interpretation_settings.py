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
    tables = {f.name for f in dataclasses.fields(C) if T._takes_a_table(f.type)}     # set in a settings file
    assert set(offered) | T.HIDDEN | tables >= library, sorted(library - set(offered) - T.HIDDEN - tables)
    assert not set(offered) & T.HIDDEN
    assert set(offered) <= library


def test_each_setting_says_what_it_is():
    for f in _fields():
        assert f["label"] and f["help"], f["key"]
        assert f["kind"] in ("number", "integer", "quantity", "switch", "choice", "bands", "text"), f["key"]
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


def test_the_policy_follows_the_users_cutoffs():
    """A cutoff the user sets is the one Petrophys used: the view's policy takes it (its card and checks quote it, and
    the check that the engine used the policy's cutoffs passes); without one the policy is the policy."""
    from petroharness.well.view import user_cutoffs
    pol = {"name": "p", "cutoffs": {"vcl_max": 0.35, "sw_max": 0.7, "phie_min_clastic": 0.08, "phie_min_carbonate": 0.05}}
    assert user_cutoffs(pol, None) is pol and user_cutoffs(pol, {"vcl_cutoff": 0.35, "sw_cutoff": 0.7}) is pol
    got = user_cutoffs(pol, {"sw_cutoff": 0.6, "phie_cutoff": 0.1})["cutoffs"]
    assert got == {"vcl_max": 0.35, "sw_max": 0.6, "phie_min_clastic": 0.1, "phie_min_carbonate": 0.1}
    assert pol["cutoffs"]["sw_max"] == 0.7                                   # the policy itself is untouched


# --- the panel says what Petrophys means and used --------------------------------------------------------------------

def _by_key():
    from petroharness.well import settings as S
    return {x["key"]: x for g in S.schema()["groups"] for x in g["fields"]}


def test_the_sp_lines_are_named_as_petrophys_defines_them():
    f = _by_key()
    assert "shale" in f["sp_min"]["label"].lower() and "clean" in f["sp_max"]["label"].lower()


def test_a_unit_is_the_one_the_help_states_for_a_number():
    f = _by_key()
    assert f["rmf_chlorides_mg_l"]["unit"] == "mg/l" and f["cec"]["unit"] == "meq/100 g"
    assert f["allow_default_rw"]["unit"] == "" and f["carbonate_calibration"]["unit"] == ""


def test_the_porosity_cutoff_shows_the_policys_default():
    assert _by_key()["phie_cutoff"]["default"] == 0.08


def test_the_help_keeps_its_first_sentence_whole():
    from petroharness.well.settings import _first
    assert _first("A flag, i.e. the reservoir flag built first. More here.") == "A flag, i.e. the reservoir flag built first."
    assert _first("Lines for an SP (e.g. a drift-corrected SP). Then more.") == "Lines for an SP (e.g. a drift-corrected SP)."


def test_a_first_sentence_that_ends_on_a_unit_or_a_letter_ends_there():
    """A unit (v/v, ohm.m) or a one-letter symbol before the period ends the sentence: the help is that sentence alone,
    not the defaults and profile notes that follow it."""
    from petroharness.well.settings import _first, schema
    assert _first("Maximum water saturation for net pay, v/v. Unset: 0.60 clastic.") == \
        "Maximum water saturation for net pay, v/v."
    assert _first("Shale resistivity, ohm.m. Defaults to the computed clay resistivity.") == "Shale resistivity, ohm.m."
    assert _first("Tortuosity factor a. One value for every sample.") == "Tortuosity factor a."
    by = {f["key"]: f for g in schema()["groups"] for f in g["fields"]}
    for key in ("vcl_cutoff", "sw_cutoff", "phie_cutoff", "rtsh", "a"):
        assert by[key]["help"].count(". ") == 0 and by[key]["help"].endswith("."), (key, by[key]["help"])


def test_used_reports_the_value_petrophys_applied():
    from types import SimpleNamespace
    from petroharness.well.settings import used
    prep = SimpleNamespace(steps={"vclay": {"parameters": {"gr_min": 40.84, "gr_min_used": 20.0, "gr_max": 120.0}}})
    got = used(prep)
    assert got["gr_min"]["value"] == 20.0 and got["gr_max"]["value"] == 120.0


def test_a_used_value_carries_the_unit_its_step_records():
    """Petrophys records td_unit beside td: the log's depth unit when the total depth came from the log (metres on
    tuhua-7), ft when the value was given. A unit setting it records under its computed name (bht_f, the setting bht)
    is the setting's, in that name's unit. The panel shows that unit, not the setting name's."""
    from types import SimpleNamespace
    from petroharness.well.settings import used
    taken = used(SimpleNamespace(steps={"temperature": {"parameters": {
        "td": 1350.2, "td_unit": "m", "bht_f": 210, "surface_temp_f": 68.0, "gradient_f_per_100ft": 1.64}}}))
    assert taken["td"] == {"value": 1350.2, "step": "temperature", "unit": "m"}
    assert taken["bht"] == {"value": 210, "step": "temperature", "unit": "°F"} and taken["surface_temp"]["unit"] == "°F"
    assert taken["temperature_gradient"] == {"value": 1.64, "step": "temperature", "unit": "°F/100 ft"}
    given = used(SimpleNamespace(steps={"temperature": {"parameters": {"td": 8500, "td_unit": "ft"}}}))
    assert given["td"]["unit"] == "ft"
    from pathlib import Path
    page = (Path(__file__).resolve().parents[1] / "src" / "petroharness" / "ui" / "static" / "index.html").read_text(
        encoding="utf-8")
    assert "ishow(used.unit ? {...f, unit: used.unit} : f, used.value)" in page


def _takes_a_table(t) -> bool:
    import typing
    args = [a for a in typing.get_args(t) if a is not type(None)] if typing.get_origin(t) is typing.Union else [t]
    return bool(args) and all(typing.get_origin(a) in (dict, list, tuple) for a in args)


def test_a_setting_that_takes_a_table_is_not_offered_as_a_value():
    """A Petrophys setting whose type takes a table, a list or a pair (mineral_endpoints, bad_hole, ...) is not a field
    of the page (a number field cannot hold it); a settings file gives it under data.interpret."""
    import dataclasses
    from petrophys.workflow import DynamicWorkflowConfig as C
    from petroharness.well.settings import schema
    offered = {f["key"] for g in schema()["groups"] for f in g["fields"]}
    tables = {f.name for f in dataclasses.fields(C) if not f.name.startswith("_") and _takes_a_table(f.type)}
    assert not tables & offered, sorted(tables & offered)


def test_the_hydrocarbon_and_gradient_settings_sit_in_their_groups():
    from petroharness.well.settings import schema
    where = {f["key"]: (g["key"], f["label"]) for g in schema()["groups"] for f in g["fields"]}
    for key, group in (("rho_hc", "porosity"), ("hc_hydrogen_index", "porosity"), ("temperature_gradient", "temperature")):
        if key in where:                                   # a Petrophys that has the setting
            assert where[key][0] == group and where[key][1] != key.replace("_", " "), (key, where[key])


def test_a_temperature_gradient_or_depth_is_given_with_its_unit_and_read_by_petrophys():
    """The settings Petrophys takes with a unit (read from its settings class: bht_f names the setting bht in degF)
    are quantities: a number, read in the unit shown, or a number with its unit, which Petrophys reads and checks."""
    from petroharness.well.settings import computed_names, schema, validate
    with_unit = {s for s, _ in computed_names().values()}
    assert with_unit == {"surface_temp", "bht", "td", "temperature_gradient", "rw_meas_temp", "rmf_meas_temp",
                         "rm_meas_temp"}
    fields = {f["key"]: f for g in schema()["groups"] for f in g["fields"]}
    assert {k for k, f in fields.items() if f["kind"] == "quantity"} == with_unit
    assert fields["bht"]["unit"] == "°F" and fields["temperature_gradient"]["unit"] == "°F/100 ft"
    assert fields["td"]["unit"] == ""                     # a bare total depth is in the well's own unit
    temperature = {f["key"] for g in schema()["groups"] if g["key"] == "temperature" for f in g["fields"]}
    assert temperature == {"surface_temp", "bht", "td", "temperature_gradient"}
    assert validate({"rw_meas_temp": "110 degC", "bht": 230, "td": "2650 m", "temperature_gradient": "30 degC/km"}) == {}
    assert validate({"bht": True}) == {"bht": "give a number, or a number with its unit"}
    assert "rw_meas_temp" in validate({"rw_meas_temp": "110 furlongs"})      # Petrophys refuses the unit, by name
    assert validate({"bht_f": 230})["bht_f"].startswith("not a setting this panel knows")  # the name before 3a9378e


def test_a_quantity_reads_back_with_its_unit_and_an_old_name_says_the_new_one():
    from petroharness.well.settings import describe, diff, schema, validate
    assert validate({"bht": (110, "degC")}) == {}                     # a (number, unit) pair, as Petrophys takes it
    assert "Petrophys now takes it as bht, with its unit" in validate({"bht_f": 230})["bht_f"]
    said = describe(diff({}, {"bht": 230, "rw_meas_temp": "65 degC", "temperature_gradient": (30, "degC/km")}))
    assert said == ("bht the default -> 230 °F; rw_meas_temp the default -> 65 degC; temperature_gradient the "
                    "default -> 30 degC/km")
    fields = {f["key"]: f for g in schema()["groups"] for f in g["fields"]}
    assert fields["surface_temp"]["default"] == 68.0 and fields["surface_temp"]["unit"] == "°F"

