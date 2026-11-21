"""Every public Petrophys function reachable from its verb (src/petroharness/agent/library_api.py): the registry
generated from the library, search and run, and the binder (the inputs the model names, read as Petrophys declares
them; the question's scope; a missing input asked for; outputs as curves, values and parts).

    .venv/bin/python -m pytest tests/agent/test_library_api.py -q
"""
import inspect
import os
import re
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


def test_every_function_carries_petrophys_declarations():
    """What each parameter takes comes from Petrophys (petrophys.function_schema), not from its name: archie's rw is
    a curve (Rw at each sample), pickett_analysis's rw one number (an Rw, or none: it estimates Rw)."""
    for fn in A.registry():
        assert set(fn.kinds) == set(fn.params), fn.qualified
    archie, pickett = A.lookup("archie"), A.lookup("pickett_analysis")
    assert (archie.kinds["rt"].kind, archie.kinds["rt"].curve, archie.kinds["rw"].kind) == ("curve", "RDEP", "curve")
    assert (pickett.kinds["rw"].kind, pickett.kinds["method"].choices) == ("value", ("rma", "ols"))
    assert A.lookup("identify_lithology_zone").samplewise


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
    assert first.strip().startswith("detect_gas_effect (calculate)")
    assert "Needs nphi (curve; Neutron Porosity here: " in first and "NPHI v/v" in first     # what this well has


@pytest.mark.data
def test_run_takes_the_inputs_the_model_names_and_says_each(tuhua):
    """The model names each input (the curves Petrophys reads as its quantity here, the record's value of that name are
    shown to it); nothing else is filled in: a and m left out keep Petrophys's defaults."""
    with pytest.raises(ToolError, match=r"apparent_water_resistivity needs rt \(curve, ohm.m; Deep Resistivity here: .*RDEP ohm.m"):
        schemas.call(tuhua, "estimate", {"run": "apparent_water_resistivity"})
    r = schemas.call(tuhua, "estimate", {"run": "apparent_water_resistivity",
                                         "args": {"rt": "RDEP", "phi": "PHIE", "a": 0.81}})
    assert "Inputs: rt RDEP (asked); phi PHIE (asked); a 0.81 (asked)." in r.text
    name = next(c for c in tuhua.inv.curves if c.startswith("APPARENT_WATER"))
    assert np.isfinite(tuhua.view.values(name)).any() and r.numbers


@pytest.mark.data
def test_run_takes_a_condition_and_names_tuple_parts(tuhua):
    r = schemas.call(tuhua, "estimate", {"run": "nd_shale_point",
                                         "args": {"nphi": "NPHI", "rhob": "RHOB", "shale": "VCL > 0.6"}})
    assert "shale VCL > 0.6 (asked)" in r.text and len(r.numbers) >= 2
    # a tuple's parts are named by their index; where the matrix is filled from several lithologies (D3), its point
    # (not one value per sample) is given for each lithology, computed on all the samples
    assert re.search(r"^  (\S+\.)?0: ", r.text, re.M) and re.search(r"^  (\S+\.)?1: ", r.text, re.M), r.text[:600]


@pytest.mark.data
def test_a_whole_well_function_gets_the_intervals_limits(tuhua):
    r = schemas.call(tuhua, "summarize", {"run": "calculate_net_gross"})
    assert "top_depth (the interval's); bottom_depth (the interval's)" in r.text and "ntg_pay:" in r.text


@pytest.mark.data
def test_outputs_become_curves_and_class_codes_shares(tuhua):
    r = schemas.call(tuhua, "calculate", {"run": "thomas_stieber", "args": {"phit": "PHIT", "vsh": "VCL",
                                                                            "phi_sand": 0.25, "phi_shale": 0.1},
                                          "label": "TS"})
    assert "TS_V_LAMINAR" in tuhua.inv.curves and "classes, share of the samples of the whole interval (" in r.text
    assert schemas.call(tuhua, "stats", {"curves": ["TS_V_LAMINAR"]}).text


@pytest.mark.data
def test_a_missing_input_is_asked_for(tuhua):
    with pytest.raises(ToolError, match=r"thomas_stieber needs phit \(curve, v/v; Total Porosity here: PHIT"):
        schemas.call(tuhua, "calculate", {"run": "thomas_stieber"})


def test_an_asked_value_is_read_as_its_kind():
    """A curve name for a list of names is a list of one (a bare "SW" was read as ["S", "W"]); a number written as
    text a number; a switch's word a bool; a choice matched to its own spelling."""
    fn = A.lookup("fit_saturation_height_from_well")
    assert A._asked(None, fn, "sw_curve", "SW") == ["SW"] and A._asked(None, fn, "fwl", "2958") == 2958.0
    assert A._asked(None, fn, "vertical", "true") is True and A._asked(None, fn, "model", "Cuddy") == "cuddy"


@pytest.mark.data
def test_a_function_given_the_well_finds_its_optional_curves_itself(tuhua):
    """fit_saturation_height_from_well takes the well: its Sw and porosity curve names keep Petrophys's defaults (SW,
    PHIE_CC ...), which it looks up with its own fallbacks, and the fit runs (it once got the letters of "SW")."""
    fn = A.lookup("fit_saturation_height_from_well")
    base = float(np.asarray(tuhua.view.prep.depth, dtype=float)[tuhua.view.mask].max())
    kw, src = A.bind(tuhua, fn, {"vertical": True, "fwl": base})
    assert "well" in kw and "sw_curve" not in kw and "phi_curve" not in kw
    r = schemas.call(tuhua, "calibrate", {"run": "fit_saturation_height_from_well", "args": {"vertical": True,
                                                                                              "fwl": base}})
    assert "Petrophys" in r.text and "No Sw curve" not in r.text


def _bound(f, fn, args):
    """kwargs as the binder gives them, a placeholder for each required input the call leaves out: a curve name where
    Petrophys declares a curve, a curve name or a mask (one call's values are the same samples), else a number."""
    args = dict(args)
    for _ in range(len(fn.params) + 1):
        try:
            return A.bind(f, fn, args)[0], args
        except ToolError as e:
            need = re.search(r" needs (\w+)", str(e))
            if not need or need.group(1) in args:
                return None, args
            d = fn.kinds.get(need.group(1))
            args[need.group(1)] = "SW" if d is not None and d.kind in ("curve", "curve_name", "mask") else 1.0
    return None, args


@pytest.mark.data
def test_every_value_the_binder_gives_has_its_declared_shape(tuhua):
    """Over the registry: what the binder gives each parameter has the shape its declared kind takes (a curve the
    samples or a number, a list of curve names a list, one name a name, a number a number, the well when required)."""
    wrong, checked = [], 0
    for fn in A.registry():
        kw, args = _bound(tuhua, fn, {})
        if kw is None:
            continue
        checked += 1
        for p, v in kw.items():
            if p in args:                                # a placeholder of the test, not the binder's
                continue
            d = fn.kinds[p]
            ok = {"curve": isinstance(v, (np.ndarray, float, int)),
                  "curve_name": isinstance(v, list) if d.many else isinstance(v, str),
                  "value": isinstance(v, (float, int)), "window": isinstance(v, float),
                  "depth": isinstance(v, np.ndarray), "well": not isinstance(v, (str, np.ndarray))}.get(d.kind, True)
            if not ok:
                wrong.append(f"{fn.name}.{p} ({d.kind}) = {type(v).__name__}")
        well = [p for p, d in fn.kinds.items() if d.kind == "well"]
        if well and fn.params[well[0]][1] is inspect.Parameter.empty and well[0] not in kw:
            wrong.append(f"{fn.name}: requires the well and was not given it")
    assert checked > 200 and not wrong, (checked, wrong)


@pytest.mark.data
def test_a_curve_named_where_values_are_taken_gives_its_values(tuhua):
    """height_above_fwl(tvd: Any, fwl): "DEPTH" (or a curve's name) is the interval's values, not the text 'DEPTH'
    (Petrophys: could not convert string to float: 'DEPTH')."""
    fn = A.lookup("height_above_fwl")
    depth = np.asarray(tuhua.view.prep.depth, dtype=float)[tuhua.view.mask]
    kw, src = A.bind(tuhua, fn, {"tvd": "DEPTH", "fwl": float(depth.max())})
    assert isinstance(kw["tvd"], np.ndarray) and np.array_equal(kw["tvd"], depth) and "tvd DEPTH (asked)" in src
    r = schemas.call(tuhua, "calibrate", {"run": "height_above_fwl", "args": {"tvd": "DEPTH", "fwl": float(depth.max())}})
    assert "could not convert" not in r.text and "written as" in r.text


@pytest.mark.data
def test_a_curve_named_for_a_curve_or_mask_parameter_is_its_values(tuhua):
    """Over the registry: a curve's name given where Petrophys declares a curve or a mask reaches it as the curve's
    values (a mask: where the curve is set), never as the text."""
    wrong, checked = [], 0
    for fn in A.registry():
        for p, d in fn.kinds.items():
            if d.kind not in ("curve", "mask"):
                continue
            kw, _ = _bound(tuhua, fn, {p: "SW"})
            if kw is None:
                continue
            checked += 1
            if not isinstance(kw.get(p), np.ndarray):
                wrong.append(f"{fn.name}.{p} ({d.kind}) got {kw.get(p)!r}")
    assert checked > 150 and not wrong, (checked, wrong)


def test_a_choice_outside_its_choices_is_refused_with_them():
    """A word that is none of a choice's options is refused with the options and Petrophys's default (Petrophys would
    refuse it only at the call, after the model's step)."""
    fn = A.lookup("fit_saturation_height_from_well")
    with pytest.raises(ToolError, match=r"model is one of power, cuddy, skelt_harrison, not 'brooks_corey'; leave "
                                        r"it out for Petrophys's default \('skelt_harrison'\)"):
        A._asked(None, fn, "model", "brooks_corey")
    assert A._asked(None, fn, "model", "Cuddy") == "cuddy"                 # an option in any case


@pytest.mark.data
def test_a_refusal_gives_back_the_whole_call_with_what_it_left_out(tuhua):
    """A model named thomas_stieber's curves, then (shown only the missing inputs) its two numbers alone, then the
    curves again: it never ran. The refusal's call keeps what the call gave and adds what it left out."""
    with pytest.raises(ToolError) as e:
        schemas.call(tuhua, "calculate", {"run": "thomas_stieber", "args": {"phit": "PHIT", "vsh": "VCL"}})
    assert str(e.value).startswith("thomas_stieber needs phi_sand (number")
    assert str(e.value).endswith('every input in one args: {"run": "thomas_stieber", "args": {"phit": "PHIT", '
                                 '"vsh": "VCL", "phi_sand": ..., "phi_shale": ...}}')


@pytest.mark.data
def test_a_number_beside_curves_is_refused_with_what_the_input_takes(tuhua):
    """fit_saturation_height(height, sw, ...): sw named as a curve and height as one number (a model passed the FWL
    depth) reached Petrophys, which failed on the shapes (IndexError). One call's values are the same samples."""
    with pytest.raises(ToolError, match=r"fit_saturation_height: sw is a curve over the interval, so height must be "
                                        r"one too, not the number 2958: height \(curve"):
        schemas.call(tuhua, "calibrate", {"run": "fit_saturation_height", "args": {"height": 2958, "sw": "SW"}})


def test_numbers_alone_evaluate_a_function_at_one_point():
    """Every curve input given as a number is a point, not a mix: Rwa at Rt 20 ohm.m and porosity 0.25 (m 2, a 1)."""
    from types import SimpleNamespace
    fn = A.lookup("apparent_water_resistivity")
    kw, src = A.bind(SimpleNamespace(), fn, {"rt": 20, "phi": 0.25})
    assert kw == {"rt": 20, "phi": 0.25}


@pytest.mark.data
def test_default_asked_keeps_the_functions_own_default(tuhua):
    """"model": "default" asks for Petrophys's own default: it is kept and said, not passed as the word (a model sent
    it, and Petrophys refused it at the model's last step)."""
    fn = A.lookup("fit_saturation_height_from_well")
    kw, src = A.bind(tuhua, fn, {"model": "default", "fwl": 2000})
    assert "model" not in kw and "model Petrophys's default ('skelt_harrison', asked)" in src


@pytest.mark.data
def test_a_function_that_requires_the_well_gets_it(tuhua):
    """detect_washout(well, bit_size=None): its bit size has a curve role, which once made the binder treat it as a
    function of curves and leave the well out (missing 1 required positional argument: 'well')."""
    r = schemas.call(tuhua, "check", {"run": "detect_washout"})
    assert "well (the prepared well)" in r.text and "bit_size" not in r.text.split("Inputs:")[1].split(".")[0]


@pytest.mark.data
def test_an_optional_number_keeps_petrophys_default(tuhua):
    """pickett_analysis(rt, phi, ..., rw=None) estimates Rw from the data: an Rw the model does not name is not given
    to it (the record's RW curve once was, and Petrophys could not read an array where it takes one number)."""
    r = schemas.call(tuhua, "estimate", {"run": "pickett_analysis", "args": {"rt": "RDEP", "phi": "PHIE"}})
    inputs = r.text.split("Inputs: ", 1)[1].split("\n")[0]
    assert inputs.startswith("rt RDEP (asked); phi PHIE (asked); method 'rma' (Petrophys's default; one of rma/ols)")
    assert "rw " not in inputs and "vcl" not in inputs                          # no Rw, no clay volume: not named
    assert re.search(r"\.rw: [\d.]+", r.text)                                  # Pickett's own Rw from its fit


@pytest.mark.data
def test_a_function_of_one_sample_is_applied_sample_by_sample(tuhua):
    """identify_lithology_zone(nphi: float, rhob: float) labels one point; given the curves it labels each sample."""
    r = schemas.call(tuhua, "classify", {"run": "identify_lithology_zone", "args": {"nphi": "NPHI", "rhob": "RHOB"}})
    assert "applied sample by sample (it takes one value of nphi and rhob)" in r.text
    assert "one label per sample; share of the samples of the whole interval (" in r.text


def test_a_docstring_line_naming_several_parameters_documents_each():
    from petroharness.agent.library_api import _param_docs
    doc = """Do it.

    Parameters
    ----------
    curve : str
        The curve to read.
    low, high : float
        The band's limits, in the curve's units.
    **kwargs
        Passed on.

    Returns
    -------
    dict
    """
    got = _param_docs(doc)
    assert got["curve"] == "The curve to read."                         # nothing of the next line joined to it
    assert got["low"] == got["high"] == "The band's limits, in the curve's units."
    assert got["kwargs"] == "Passed on."


# --- every function, run as the model runs it ------------------------------------------------------------------------

FAULTS = re.compile(r"missing \d+ required positional argument|unexpected keyword argument|truth value of an array"
                    r"|among \['\w', '\w'|object has no attribute|not subscriptable|not iterable|unhashable type"
                    r"|could not convert string to float")


def _fingerprint(f) -> dict:
    """The record's curves as the view reads them and the prepared well's curves, by a hash of their values."""
    out = {f"view:{c}": hash(np.asarray(v, dtype=float).tobytes()) for c in f.inv.curves
           if (v := f.view.own_values(c)) is not None}
    w = f.view.prep.well
    out.update({f"well:{c}": hash(np.asarray(w.get(c).data, dtype=float).tobytes()) for c in list(w.curves)})
    return out


@pytest.mark.data
def test_every_function_runs_or_is_refused_without_a_harness_fault():
    """Every Petrophys function the verbs reach, called as the model may call it, on a session of its own: with no
    arguments, and with each required curve named from what the refusal shows this well has. It runs, asks for an
    input, or Petrophys refuses for a reason of its own. No exception escapes the tool, no refusal comes from the
    harness's arguments (a name where a list is taken, a curve where one number is, the well left out), and no call
    changes the record's curves (apply_value_range_qc once clipped them in place)."""
    las = SAMPLES / "tuhua-7.las"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    from test_library_tools import _session
    f = _session(las, SAMPLES / "formations_tuhua-7.csv", "Mount Messenger")
    before, faults, ran = _fingerprint(f), [], 0
    for fn in A.registry():
        named = {}
        for p, d in fn.kinds.items():                     # each required curve: the first this well has for it
            if fn.params[p][1] is inspect.Parameter.empty and d.kind in ("curve", "curve_name") and d.curve:
                here = A._here(f, d.curve)
                if here:
                    named[p] = here[0].split()[0]
        for args in ({}, named) if named else ({},):
            try:
                A.run(f, fn.verb, fn.name, args)
                ran += 1
            except ToolError as e:
                if FAULTS.search(str(e)):
                    faults.append(f"{fn.name}: {str(e)[:200]}")
            except Exception as e:  # noqa: BLE001  (an exception outside Petrophys's call is the harness's)
                faults.append(f"{fn.name}: {type(e).__name__} outside the call: {str(e)[:200]}")
    changed = sorted(k for k, v in _fingerprint(f).items() if k in before and before[k] != v)
    assert ran > 80 and not faults and not changed, (ran, faults, changed)
