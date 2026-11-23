"""The analyzers' class tables: the packaged policy uses the library's current set (no dataset's tables by default);
data interpreted by a Petrophys context package may name that package's set in its data settings.

    .venv/bin/python -m pytest tests/test_class_tables.py -q
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
from petroharness.config import DataPaths, ResourcePaths  # noqa: E402
from petroharness.well.prepare import load_policy  # noqa: E402

from _wells import SAMPLES  # noqa: E402  (Petrophys's sample files; PETROHARNESS_SAMPLE_LAS for a folder of them)


def test_the_packaged_policy_uses_the_librarys_current_tables():
    assert load_policy(ResourcePaths().policy_file)["analyzers"]["class_tables"] == "current"


def test_the_data_settings_may_name_a_set():
    assert DataPaths(las_dir=".", analyzer_class_tables="a_context_set").analyzer_class_tables == "a_context_set"
    assert DataPaths(las_dir=".").analyzer_class_tables is None


def _view(extra: dict):
    import petroharness.ask as A
    from petroharness.agent.state import Session
    from petroharness.config import HarnessConfig, given_settings
    from petroharness.tasks import Task
    las, tops = SAMPLES / "tuhua-7.las", SAMPLES / "formations_tuhua-7.csv"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    held = os.environ.pop("PETROHARNESS_DATA", None)
    try:
        data, _ = A._settings(las, None, None, None, Path(tempfile.mkdtemp()), ResourcePaths().policy_file)
    finally:
        if held is not None:
            os.environ["PETROHARNESS_DATA"] = held
    data.update(extra)
    span = A._interval(las, "Mount Messenger", tops, None, None, None, data)
    data.setdefault("depth_unit", "las")
    task = Task(task_id="c" + hashlib.sha256(str(las).encode()).hexdigest()[:10], question="q", well=las.stem,
                formation=span["name"], las_path=las, top=span["top"], base=span["base"], depth_unit="las",
                base_closed=span["closed"], formation_lithology=None)
    with given_settings({"data": data, "eval": {}}):
        return Session.build(task, HarnessConfig(data=DataPaths(**data), eval=None)).f.view


@pytest.mark.data
def test_a_well_without_data_settings_is_classified_with_the_current_tables():
    view = _view({})
    assert view.policy["analyzers"]["class_tables"] == "current"


@pytest.mark.data
def test_the_data_settings_choose_the_tables():
    view = _view({"analyzer_class_tables": "geolink"})
    assert view.policy["analyzers"]["class_tables"] == "geolink"


@pytest.mark.data
def test_the_commands_depth_unit_wins_over_a_settings_files(tmp_path):
    """--depth-unit m on a run whose settings file says ft: the answer's depths are in metres."""
    import petroharness.ask as A
    las, tops = SAMPLES / "tuhua-7.las", SAMPLES / "formations_tuhua-7.csv"
    if not las.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    settings = tmp_path / "settings.yaml"
    settings.write_text("data:\n  depth_unit: ft\n")
    held = os.environ.pop("PETROHARNESS_DATA", None)
    try:
        p = A.prepare(las, "k2-horizon-7b", A.Inputs(formation="Mount Messenger", tops=tops, depth_unit="m", settings=settings), cache=tmp_path / "cache")
        q = A.prepare(las, "k2-horizon-7b", A.Inputs(formation="Mount Messenger", tops=tops, settings=settings), cache=tmp_path / "cache")
    finally:
        if held is not None:
            os.environ["PETROHARNESS_DATA"] = held
    assert p.data["depth_unit"] in ("m", "las")              # tuhua-7 is logged in metres: m is the LAS's own unit
    assert q.data["depth_unit"] == "ft"                      # without the option the file's unit holds
