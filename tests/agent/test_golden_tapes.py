"""The no-change gate: every golden question (tests/golden: the model calls recorded live on 36 questions, 12 per
dataset, and the result the harness gives from them) replayed through the question graph gives the recorded requests,
answer, status and trace, component versions included (tests/agent/record_golden.py re-records them). Data test: it
builds each question's formation (about 10 s each).

    .venv/bin/python -m pytest tests/agent/test_golden_tapes.py -m data -q -n 12
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
GOLDEN = ROOT / "tests" / "golden"
DATA = Path(os.environ["WELLLOGBENCH"]) if os.environ.get("WELLLOGBENCH") else None   # the folder of <dataset>.yaml data configs
CASES = [(ds, q["task_id"], q["category"]) for ds in ("geolink", "costa", "danish") if (GOLDEN / ds / "selection.json").exists()
         for q in json.loads((GOLDEN / ds / "selection.json").read_text())["questions"]]


@pytest.mark.data
@pytest.mark.skipif(DATA is None, reason="WELLLOGBENCH is not set (the folder of the datasets' data configs)")
@pytest.mark.parametrize("ds, task_id, category", CASES, ids=[f"{d}-{c}-{t}" for d, t, c in CASES])
def test_golden_tape_replays_identically(ds, task_id, category, monkeypatch):
    import gzip
    from petroharness import tape
    from petroharness.config import HarnessConfig
    from petroharness.tasks import load_tasks
    from petroharness.llm import LLM
    monkeypatch.setenv("PETROHARNESS_DATA", str(DATA / f"{ds}.yaml"))
    monkeypatch.setenv("PETROHARNESS_SET", "")
    from petroharness.agent import graph
    cfg = HarnessConfig()
    tasks, _ = load_tasks(cfg.eval.questions, cfg.data.las_dir)
    task = next(t for t in tasks if t.task_id == task_id)
    sel = json.loads((GOLDEN / ds / "selection.json").read_text())
    rec = tape.load(GOLDEN / ds / f"{task_id}.tape.jsonl")
    seen = {}

    class Taped(LLM):
        def __init__(self, c):
            super().__init__(c)
            seen["replayer"] = tape.replay(self, rec)

    got = graph.answer(task, sel["model"], 1, graph.MAX_STEPS, "open", "profile", llm_factory=Taped)
    with gzip.open(GOLDEN / ds / f"{task_id}.result.json.gz", "rt") as f:
        want = json.load(f)
    problem = tape.compare_run(got, want, seen.get("replayer"))
    assert not problem, problem
