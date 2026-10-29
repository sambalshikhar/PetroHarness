"""Every public Petrophys function reachable from its verb (src/petroharness/agent/library_api.py): the registry
generated from the library, search and run, and the binder (curves by role, conditions, the record's numbers, the
interval's limits, outputs as curves, values and parts).

    .venv/bin/python -m pytest tests/agent/test_library_api.py -q
"""
import inspect
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).resolve().parent)]
from petroharness.agent import library_api as A
from petroharness.agent import schemas
from petroharness.agent.engine import ToolError

SAMPLES = Path(os.environ.get("PETROHARNESS_SAMPLE_LAS", "sample_las"))


def test_the_registry_is_the_librarys_public_functions_by_verb():
    by = {}
    for fn in A.registry():
        by.setdefault(fn.verb, []).append(fn.name)
        assert not fn.name.startswith("_") and fn.path.startswith("petrophys.")
    assert set(by) == {"calculate", "estimate", "what_if", "check", "classify", "summarize", "calibrate"}
    assert "apparent_water_resistivity" in by["estimate"] and "summarize_pay" in by["summarize"]
    assert "thomas_stieber" in by["calculate"] and "fit_j_function" in by["calibrate"]
    assert sum(len(v) for v in by.values()) > 200


def test_parameter_spellings_find_their_curves():
    assert A._role("phi_d") == ["PHID"] and A._role("rt_curve") == ["RT", "RDEP"] and A._role("NPHI") == ["NPHI", "PHIN"]
    assert A._role("threshold") == []
    assert A._name_param("sw_curve", "Optional[str]", None) and not A._array_param("sw_curve", "Optional[str]")


def test_the_docstring_parameters_are_read():
    fn = A.lookup("apparent_water_resistivity")
    assert {"rt", "phi", "a", "m"} <= set(fn.params) and fn.summary.startswith("Apparent water resistivity")
    assert fn.params["rt"][1] is inspect.Parameter.empty and fn.params["m"][1] == 2.0


def test_the_verbs_take_search_and_run_beside_their_objects():
    shown = {t["function"]["name"]: t["function"] for t in schemas.named()}
    for v in ("calculate", "estimate", "what_if", "check", "classify", "summarize", "calibrate"):
        props = shown[v]["parameters"]["properties"]
        assert {"search", "run", "args"} <= set(props) and shown[v]["parameters"]["required"] == []
        assert "search / run: any of Petrophys's" in shown[v]["description"]


def test_an_unknown_function_points_to_search():
    with pytest.raises(ToolError, match="no Petrophys function 'nope'; search lists them"):
        A.lookup("nope", "classify")


@pytest.fixture(scope="module")
def tuhua():
    las = SAMPLES / "tuhua-7.las"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    from test_library_tools import _session
    return _session(las, SAMPLES / "formations_tuhua-7.csv", "Mount Messenger")


@pytest.mark.data
def test_search_ranks_the_verbs_own_then_the_others(tuhua):
    r = schemas.call(tuhua, "classify", {"search": "gas effect"})
    first = r.text.splitlines()[1]
    assert first.strip().startswith("detect_gas_effect (calculate)") and "bound here: nphi=NPHI, phi_d=PHID" in first


@pytest.mark.data
def test_run_binds_roles_and_the_records_numbers(tuhua):
    r = schemas.call(tuhua, "estimate", {"run": "apparent_water_resistivity"})
    assert "Inputs: rt RDEP; phi PHIE; a 0.81 (record, saturation); m 2 (record, saturation)" in r.text
    name = next(c for c in tuhua.inv.curves if c.startswith("APPARENT_WATER"))
    assert np.isfinite(tuhua.view.values(name)).any() and r.numbers


@pytest.mark.data
def test_run_takes_a_condition_and_names_tuple_parts(tuhua):
    r = schemas.call(tuhua, "estimate", {"run": "nd_shale_point", "args": {"shale": "VCL > 0.6"}})
    assert "shale VCL > 0.6 (asked)" in r.text and "  0: " in r.text and "  1: " in r.text and len(r.numbers) >= 2


@pytest.mark.data
def test_a_whole_well_function_gets_the_intervals_limits(tuhua):
    r = schemas.call(tuhua, "summarize", {"run": "calculate_net_gross"})
    assert "top_depth (the interval's); bottom_depth (the interval's)" in r.text and "ntg_pay:" in r.text


@pytest.mark.data
def test_outputs_become_curves_and_class_codes_shares(tuhua):
    r = schemas.call(tuhua, "calculate", {"run": "thomas_stieber", "args": {"phi_sand": 0.25, "phi_shale": 0.1},
                                          "label": "TS"})
    assert "TS_V_LAMINAR" in tuhua.inv.curves and "classes, share of the zones' samples" in r.text
    assert schemas.call(tuhua, "stats", {"curves": ["TS_V_LAMINAR"]}).text


@pytest.mark.data
def test_a_missing_input_is_asked_for(tuhua):
    with pytest.raises(ToolError, match="thomas_stieber needs phi_sand"):
        schemas.call(tuhua, "calculate", {"run": "thomas_stieber"})


def test_text_arguments_keep_their_case_and_shape():
    assert A._text_arg("SW", "Optional[str]") == "SW"                          # a curve's mnemonic keeps its case
    assert A._text_arg("SW", "Union[str, Sequence[str]]") == ["SW"]            # one name where a list is taken
    assert A._text_arg("0.25", "float") == 0.25 and A._text_arg("skelt_harrison", "str") == "skelt_harrison"
