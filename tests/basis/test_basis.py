"""The methods and parameters an answer rests on (petroharness.basis): the steps behind the curves an answer names, the
steps those read from, the parameters as the record holds them. Code only: no model, and nothing reaches a prompt.

    .venv/bin/python -m pytest tests/basis -q   (PETROHARNESS_DATA selects the dataset for the data test)
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tests" / "agent")]
from petroharness import basis as B  # noqa: E402


def curve(step=None, source="computed"):
    return NS(source=source, step=step)


def method(step, name, inputs, outputs, parameters=None):
    return NS(step=step, method=name, inputs=inputs, outputs=outputs, parameters=parameters or {})


def fake(cited_calls):
    """A session over a small record: clay volume -> porosity -> saturation -> net flags; the interval holds no
    samples of the saturation curve (it is a step's output only); one curve was computed on request."""
    inv = NS(curves={"GR": curve(source="input"), "RHOB": curve(source="input"), "VCL": curve("clay"),
                     "PHIE": curve("porosity"), "NET": curve("net"), "SW_ALT": curve("saturation (on request)")},
             methods=[method("clay", "linear", ["GR"], ["VCL"], {"gr_min": 10.0, "gr_max": 120, "note_path": "x"}),
                      method("porosity", "density", ["RHOB", "VCL"], ["PHIE", "PHIT"],
                             {"rho_ma": 2.65, "table": {"a": 1}, "use_sonic": False, "matrix": "sandstone",
                              "long": "x" * 81, "empty": " ", "none": None, "rows": [1, 2]}),
                      method("saturation", "archie", ["PHIE", "RW/RT"], ["SW"], {"m": 2, "n": 2, "a": 1}),
                      method("rw", "from the record", [], ["RW"], {"rw": 0.05}),
                      method("net", "cutoffs", ["VCL", "PHIE", "SW"], ["NET"], {"sw_cutoff": 0.7})])
    items = {f"E{i}": NS(call_text=lambda t=t: t) for i, t in enumerate(cited_calls, 1)}
    return NS(f=NS(inv=inv), ledger=NS(by_id=items.get))


def test_the_steps_behind_the_named_curves_and_the_steps_those_read_from():
    rows = B.used(fake(["stats PHIE"]), ["E1", "E9"], "Porosity averages 0.21.")
    assert [(r["step"], r["why"]) for r in rows] == [("clay", B.UPSTREAM), ("porosity", B.NAMED)]   # workflow order
    por = rows[1]
    assert por["method"] == "density" and por["curves"] == ["PHIE"] and por["inputs"] == ["RHOB", "VCL"]
    assert por["parameters"] == {"rho_ma": 2.65, "use_sonic": False, "matrix": "sandstone"}   # scalars only, as recorded
    assert rows[0]["curves"] == ["VCL"] and rows[0]["parameters"] == {"gr_min": 10.0, "gr_max": 120}


def test_a_curve_the_answer_names_counts_and_a_steps_output_needs_no_samples():
    rows = B.used(fake(["stats PHIE"]), ["E1"], "SW falls where PHIE rises.")
    assert [(r["step"], r["why"]) for r in rows] == [("clay", B.UPSTREAM), ("porosity", B.NAMED),
                                                     ("saturation", B.NAMED), ("rw", B.UPSTREAM)]
    assert next(r for r in rows if r["step"] == "saturation")["curves"] == ["SW"]
    assert next(r for r in rows if r["step"] == "rw")["curves"] == ["RW"]        # an upstream step shows its outputs


def test_a_curve_computed_on_request_comes_last_by_its_label_and_inputs_alone_give_nothing():
    rows = B.used(fake(["compare SW_ALT PHIE", "stats GR"]), ["E1", "E2"])
    assert rows[-1] == {"step": "saturation (on request)", "method": B.ON_REQUEST, "curves": ["SW_ALT"], "inputs": [],
                        "parameters": {}, "why": B.NAMED}
    assert B.used(fake(["stats GR", "stats RHOB"]), ["E1", "E2"], "GR is high.") == []
    assert B.markdown([]) == ""


def test_the_section_of_the_answer_file():
    text = B.markdown(B.used(fake(["stats NET"]), ["E1"], ""))
    assert text.startswith("\n\n## Methods and parameters this answer rests on\n")
    assert "- **net**: cutoffs. computed NET. read VCL, PHIE, SW. parameters sw_cutoff = 0.7." in text
    assert "The steps those read from:" in text and "- **saturation**: archie. computed SW." in text
    assert "use_sonic = no" in text and "gr_max = 120" in text
    assert text.index("**net**") < text.index("The steps those read from:") < text.index("**clay**")


@pytest.mark.data
def test_on_a_real_formation_the_porosity_curve_leads_to_its_recorded_step():
    from _support.formations import F as formations
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.state import Session
    from petroharness.agent.map import render
    got = next(((t, f) for t, f in formations() if f.inv.curves.get("PHIE") is not None and f.inv.curves["PHIE"].step), None)
    if got is None:
        pytest.skip("no formation with a computed PHIE")
    t, f = got
    s = Session(t, f, render(f.inv), Ledger(f))
    s.ledger.open("stats", {"curves": ["PHIE"]})
    rows = B.used(s, [e.id for e in s.ledger.items])
    named = [r for r in rows if r["why"] == B.NAMED]
    assert [r["step"] for r in named] == [f.inv.curves["PHIE"].step] and "PHIE" in named[0]["curves"]
    assert named[0]["method"] and named[0]["method"] != B.ON_REQUEST
    steps = [m.step for m in f.inv.methods]
    assert [r["step"] for r in rows] == sorted((r["step"] for r in rows), key=steps.index)
    assert B.markdown(rows).count("\n- **") == len(rows)
