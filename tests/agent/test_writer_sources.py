"""The checker accepts the numbers the writer was shown (agent/writer.py: unsupported): the results, the map without
its notes, the zone table, the curve card and the limits the investigation found; and the limits leave out empty
weakness notes.

    .venv/bin/python -m pytest tests/agent/test_writer_sources.py -q   (PETROHARNESS_SAMPLE_LAS: the sample wells)
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parent)]
from petroharness.agent import writer as W  # noqa: E402

NOTE_NUMBER = "123.4567"


@pytest.fixture(scope="module")
def tuhua():
    from test_library_tools import SAMPLES, _session
    las, tops = SAMPLES / "tuhua-7.las", SAMPLES / "formations_tuhua-7.csv"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    return _session(las, tops, "Mount Messenger")


def _s(f, weak="", points=("How porous is it?",)):
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.map import render
    claims = {"C1": NS(point=1, weak=weak, grade="moderate")} if weak else {}
    return NS(f=f, ledger=Ledger(f), task=NS(question="q", well="tuhua-7"), card="",
              claims=NS(claims=claims, points=list(points)),
              map=render(f.inv) + f"\nNotes on this interval\n  - a note that holds {NOTE_NUMBER}")


@pytest.mark.data
def test_a_number_only_the_maps_notes_hold_is_unsupported(tuhua):
    assert NOTE_NUMBER in W.unsupported(f"The value is {NOTE_NUMBER}.", _s(tuhua))


@pytest.mark.data
def test_a_number_in_a_limit_the_writer_was_shown_is_supported(tuhua):
    assert not W.unsupported(f"The value is {NOTE_NUMBER}.", _s(tuhua, weak=f"a note gives {NOTE_NUMBER}"))


@pytest.mark.data
def test_a_number_in_a_point_the_writer_was_shown_is_supported(tuhua):
    """The question's points reach the writer (THE QUESTION'S POINTS): a number in one is shown, as a limit's is."""
    s = _s(tuhua, points=[f"How does the screen ({NOTE_NUMBER} samples) relate to porosity?"])
    assert not W.unsupported(f"The screen flags {NOTE_NUMBER} samples.", s)
    assert f"Point 1: How does the screen ({NOTE_NUMBER} samples)" in W.readings(s)


def test_an_empty_weakness_note_is_no_limit():
    claims = {f"C{i}": NS(point=i, weak=w, grade="moderate") for i, w in enumerate(["-", "none", "n/a", "--", "real one"])}
    assert W.doubts(NS(claims=NS(claims=claims))) == [(4, "real one")]
