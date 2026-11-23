"""`petroharness chat` (petroharness.session.chat): inputs that cannot be used end the command with exit status 2 and
a WHAT / FIX line, before any question is asked.

    .venv/bin/python -m pytest tests/session/test_chat_command.py -q
"""

import pytest

from petroharness.session import chat as CH

from _wells import SAMPLES  # noqa: E402  (Petrophys's sample files; PETROHARNESS_SAMPLE_LAS for a folder of them)
LAS = SAMPLES / "tuhua-7.las"
WINDOW = ["--top", "600", "--base", "700", "--depth-unit", "m", "--formation", "test window"]
NOWHERE = ["--model-url", "http://127.0.0.1:9/v1"]           # never reached: the inputs fail first

pytestmark = pytest.mark.data


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    if not LAS.exists():
        pytest.skip(f"no sample wells at {SAMPLES} (PETROHARNESS_SAMPLE_LAS)")
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS"):
        monkeypatch.delenv(key, raising=False)


def test_a_skill_library_that_cannot_be_used_stops_the_command_before_a_question(tmp_path, capsys):
    code = CH.main(["--las", str(LAS), *WINDOW, *NOWHERE, "--session", str(tmp_path / "s"), "--no-figures",
                    "--skills", str(tmp_path / "no_library"), "--question", "What is the mean porosity?"])
    err = capsys.readouterr().err
    assert code == 2 and "WHAT: no skill library at" in err
    assert not list((tmp_path / "s").glob("turns/*"))                # no question was asked


def test_a_missing_questions_file_stops_the_command_before_a_session_folder_is_made(tmp_path, capsys):
    code = CH.main(["--las", str(LAS), *WINDOW, *NOWHERE, "--session", str(tmp_path / "s"), "--no-figures",
                    "--questions-file", str(tmp_path / "missing.txt")])
    err = capsys.readouterr().err
    assert code == 2 and "WHAT: the questions file" in err and "FIX:" in err
    assert not (tmp_path / "s").exists()
