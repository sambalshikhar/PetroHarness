"""The mini set's recorder (tests/gate/record_mini.py): a live recording that fails leaves the earlier one as it was;
a set recorded with another Petrophys build is not replayed against this one.

    .venv/bin/python -m pytest tests/gate/test_record_mini.py -q
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(HERE)]
import record_mini as R  # noqa: E402


def test_a_failed_live_question_leaves_the_earlier_recording(tmp_path, monkeypatch):
    from petroharness.session import conversation
    mini = tmp_path / "mini"
    earlier = mini / "brent"
    (earlier / "turns").mkdir(parents=True)
    (earlier / "set.json").write_text('{"name": "brent"}', encoding="utf-8")
    (earlier / "turns" / "01.answer.md").write_text("the earlier answer", encoding="utf-8")
    monkeypatch.setattr(R, "MINI", mini)
    monkeypatch.setattr(R, "sample_files", lambda spec: (tmp_path / "w.las", tmp_path / "tops.csv"))

    class Failing:                                                       # its first question fails
        turns = []

        def ask(self, q):
            return NS(number=1, status="error: the model server went away", trace={"error": "connection refused"})

    monkeypatch.setattr(conversation.Conversation, "start", classmethod(lambda cls, *a, **k: Failing()))
    with pytest.raises(SystemExit, match="the earlier recording is kept"):
        R.record("brent")
    assert (earlier / "set.json").read_text(encoding="utf-8") == '{"name": "brent"}'
    assert (earlier / "turns" / "01.answer.md").read_text(encoding="utf-8") == "the earlier answer"
    assert sorted(p.name for p in mini.iterdir()) == ["brent"]              # no half-made recording left


def test_another_build_of_the_same_petrophys_version_is_a_reason_to_skip(monkeypatch):
    from petroharness.well import prepare
    monkeypatch.setattr(prepare, "library_identity", lambda: "3.0.0@files-aaaaaaaaaaaa")
    assert R.other_build("3.0.0@files-aaaaaaaaaaaa") == ""
    assert "another build of Petrophys 3.0.0" in R.other_build("3.0.0@files-bbbbbbbbbbbb")
    assert "recorded with Petrophys 2.9.1@x" in R.other_build("2.9.1@x")
