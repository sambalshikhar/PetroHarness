"""Absence detected generally (src/petroharness/agent/vocabulary.py). What the question names - the READ call's named
list and the question's own vocabulary (curve mnemonics, the registry's synonyms, question terms and named
measurements) - resolves to curves; a name none of whose curves has data in the interval is named but not in this
well's record, said in one line under QUESTION, with no stand-in. The writer gets one general guideline for it.

    .venv/bin/python -m pytest tests/agent/test_absence.py -q   (PETROHARNESS_DATA selects the dataset for the data tests)
"""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness.agent import components as C, vocabulary  # noqa: E402
from petroharness.registry import DEFAULT_RULES_DIR, Registry  # noqa: E402

REG = Registry(DEFAULT_RULES_DIR).curves
HEAD = "Named but not in this well's record: "
STAND_IN = re.compile(r"in its place|instead|stand[- ]in|substitut|related evidence|context, not", re.I)


def _session(question: str, have: set, named=(), curves=None):
    """A session as the vocabulary reads it: the registry, the formation's curves, which of them have data here."""
    curves = set(curves if curves is not None else have)
    view = NS(reg=NS(curves=REG), available=lambda c: c in have)
    return NS(task=NS(question=question), reading={"named": list(named)}, f=NS(view=view, inv=NS(curves={c: None for c in curves})))


# --- the vocabulary (no data needed) ------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, want", [
    ("DTS", ["DTS"]), ("dts", ["DTS"]),                                       # a mnemonic: the whole name, any case
    ("shear sonic log (DTS)", ["DTS"]),                                       # a word in capitals; a question term
    ("deep resistivity", ["RDEP"]), ("water saturation", ["SW"]),             # synonyms
    ("irreducible water saturation", ["SWIRR_APP"]), ("bit size", ["BS"]),
    ("caliper", ["CALI", "DCAL"]),                                            # a question term naming a family
    ("spectral gamma ray", ["THOR", "URAN", "POTA", "SGR", "CGR"]),           # a question term and a named measurement
    ("porosity", []), ("a quantity no vocabulary names", []),
])
def test_a_name_resolves_through_the_vocabulary(name, want):
    assert vocabulary.resolve(name, REG) == want


def test_the_names_a_question_writes_in_order():
    got = vocabulary.in_text("Compare the DTS with the caliper and the bit size in this formation.", REG)
    assert [n for n, _ in got] == ["DTS", "caliper", "bit size"]
    assert dict(got) == {"DTS": ["DTS"], "caliper": ["CALI", "DCAL"], "bit size": ["BS"]}
    assert vocabulary.in_text("How porous is the sandstone?", REG) == []


def test_a_named_curve_without_data_gives_the_note():
    s = _session("What is the mean DTS?", have={"DTC", "GR"})
    assert vocabulary.absent(s) == [("DTS", ["DTS"])]
    assert vocabulary.note(s) == HEAD + "DTS (DTS)"
    s = _session("What does the shear log show?", have={"DTC"}, named=["shear sonic"])     # the READ call's names first
    assert vocabulary.note(s) == HEAD + "shear sonic (DTS)"


def test_a_named_curve_with_data_gives_none():
    s = _session("What is the mean DTS and water saturation?", have={"DTS", "SW"}, named=["DTS", "SW"])
    assert vocabulary.absent(s) == [] and vocabulary.note(s) == ""
    s = _session("How do the caliper and the bit size compare?", have={"DCAL", "BS"})     # one member of a family is enough
    assert vocabulary.note(s) == ""


def test_a_named_property_maps_through_the_synonyms():
    s = _session("What is the irreducible water saturation of the sands?", have={"SW", "BVW"})
    from petroharness.agent.library.api import computes
    fns = computes("irreducible water saturation")      # a derived quantity: the Petrophys functions that may compute it
    assert fns and vocabulary.note(s) == HEAD + f"irreducible water saturation (SWIRR_APP; Petrophys may compute it: {', '.join(fns)})"
    s = _session("Where does the density correction exceed 0.05 g/cc?", have={"RHOB"})
    assert vocabulary.note(s) == HEAD + "density correction (DRHO)"
    s = _session("Is the Vp/Vs ratio low in the sands?", have={"DTC"}, named=["Vp/Vs ratio", "DTS"])
    assert vocabulary.note(s) == HEAD + "Vp/Vs ratio (VP_VS_RATIO); DTS (DTS)"


def test_the_notes_as_data_hold_what_the_note_says():
    """The answer's reader gets the notes as data (vocabulary.facts; the web UI words them), item for item as the
    model is told them."""
    s = _session("Is the Vp/Vs ratio low in the sands?", have={"DTC"}, named=["Vp/Vs ratio", "DTS"])
    assert vocabulary.facts(s) == [{"kind": "absent", "name": "Vp/Vs ratio", "curves": ["VP_VS_RATIO"], "computes": []},
                                   {"kind": "absent", "name": "DTS", "curves": ["DTS"], "computes": []}]
    s = _session("What is the mean DTS and water saturation?", have={"DTS", "SW"}, named=["DTS", "SW"])
    assert vocabulary.facts(s) == []


def test_one_item_per_set_of_curves():
    """A name whose curves another named item already holds is said once (the larger set, or the first of equals)."""
    s = _session("Does the spectral gamma ray (THOR) show the clay type?", have={"GR"}, named=["spectral gamma ray"])
    assert vocabulary.note(s) == HEAD + "spectral gamma ray (THOR, URAN, POTA, SGR, CGR)"


def test_there_is_no_stand_in_text():
    """The note names what is missing and nothing else; no text the model reads maps a missing measurement to another."""
    s = _session("What is the irreducible water saturation and the Vp/Vs ratio?", have={"SW", "BVW", "DTC"})
    note = vocabulary.note(s)
    assert note.startswith(HEAD) and not STAND_IN.search(note) and "\n" not in note
    assert C.text("C10", "absent_note") == HEAD + "{items}"
    assert "absent_form_rule" not in C.meta("C9")["texts"] and "asked_absent" not in C.meta("C10")["texts"]
    assert "absent_rule" not in C.meta("C9")["texts"]          # the writer reads the note itself, under the question
    assert not STAND_IN.search(C.prompt("C9", "write"))
    brief = C.text("C1", "brief")
    assert "e.g. without SWIRR" not in brief and "ND separation is not a density correction" not in brief
    assert "asked_quantities" not in REG and not any("instead" in str(v) for v in REG.get("named_measurements", {}).values())


# --- the note in the run (data) -----------------------------------------------------------------------------------------

@pytest.mark.data
def test_the_note_reaches_step_1_the_settle_step_and_the_writer(monkeypatch):
    from test_read import read_model, _formation, _session as built
    from petroharness.agent import graph
    from petroharness.agent.state import Session
    raw = REG["inventory"]["raw"]
    t, f = _formation(lambda f: "PHIE" in f.inv.curves and any(not f.view.available(c) for c in raw))
    gone = next(c for c in raw if not f.view.available(c))
    t = t.model_copy(update={"question": f"How does porosity vary, and what does the {gone} show?"})
    s = built(t, f)
    monkeypatch.setattr(Session, "build", classmethod(lambda cls, task, cfg: s))
    llm = read_model([{"topics": ["porosity"], "named": [gone]}])
    out = graph.answer(t, "k2-horizon-7b", 1, 2, "open", "profile", llm_factory=lambda cfg: llm)
    tr = out["trace"]
    assert not tr.get("error"), tr.get("traceback")
    note = HEAD + f"{gone} ({gone})"
    assert tr["absent"] == [{"name": gone, "curves": [gone]}]
    assert llm.prompt("step_1").startswith(f"QUESTION:\n{t.question}\n{note}\n\nTHE MAP\n")
    assert f"QUESTION:\n{t.question}\n{note}\n" in llm.prompt("settle")
    writer = next(c for c in llm.sent if c["stage"] == "writer")
    assert f"QUESTION:\n{t.question}\n\n{note}\n\n" in writer["messages"][1]["content"]
    owners = {seg[0] for call in tr["calls"] if call["stage"] == "step_1" for seg in call["messages"][1]["segments"]}
    assert "C10" in owners                                                   # the note's line is C10's


@pytest.mark.data
def test_no_note_when_everything_named_is_here(monkeypatch):
    from test_read import read_model, _formation, _session as built
    from petroharness.agent import graph
    from petroharness.agent.state import Session
    t, f = _formation(lambda f: f.view.available("PHIE") and f.view.available("SW"))
    t = t.model_copy(update={"question": "How do PHIE and the water saturation vary by zone?"})
    s = built(t, f)
    monkeypatch.setattr(Session, "build", classmethod(lambda cls, task, cfg: s))
    llm = read_model([{"topics": ["porosity"], "named": ["PHIE", "water saturation"]}])
    out = graph.answer(t, "k2-horizon-7b", 1, 2, "open", "profile", llm_factory=lambda cfg: llm)
    assert out["trace"]["absent"] == [] and HEAD not in json.dumps([c["messages"] for c in llm.sent])
