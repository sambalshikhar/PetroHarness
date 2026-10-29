"""Record the golden tapes (tests/golden/<dataset>/: selection.json, <task>.tape.jsonl.gz, <task>.result.json.gz).

    PYTHONPATH=src:tests/agent python tests/agent/record_golden.py replay [DATASET ...]
        keeps every tape (the model's recorded replies) and rewrites each result as the current code produces it
        from the tape; refuses when the code makes a request the tape does not hold (that is a behaviour change)
    PYTHONPATH=src:tests/agent K2H_TOOL_URLS=... python tests/agent/record_golden.py live [--workers N] DATASET ...
        records new tapes and results from the live model for the dataset's selected questions (a change of
        behaviour made on purpose), N questions at a time (default 12)

The data configs are read from $WELLLOGBENCH/<dataset>.yaml (WELLLOGBENCH is required). Record from a clean checkout
of the commit the tapes are for: the selection records it.
"""
import gzip
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden"
DATA = Path(os.environ["WELLLOGBENCH"]) if os.environ.get("WELLLOGBENCH") else None   # the folder of <dataset>.yaml data configs


def one(mode: str, ds: str, task, model: str) -> str:
    """Record (live) or replay one golden question; its tape and result are written beside the selection."""
    from petroharness import tape
    from petroharness.agent import graph
    from petroharness.llm import LLM
    base = GOLDEN / ds / task.task_id
    if mode == "replay":
        rec, seen = tape.load(Path(f"{base}.tape.jsonl")), {}

        class Taped(LLM):
            def __init__(self, c):
                super().__init__(c)
                seen["replayer"] = tape.replay(self, rec)
        factory = Taped
    else:
        live = Path(f"{base}.tape.jsonl")
        live.unlink(missing_ok=True)

        class Recorded(LLM):
            def __init__(self, c):
                super().__init__(c)
                tape.record(self, live)
        factory = Recorded
    got = graph.answer(task, model, 1, graph.MAX_STEPS, "open", "profile", llm_factory=factory)
    if got["trace"].get("error"):
        raise SystemExit(f"{ds} {task.task_id}: {got['trace']['error'][:400]}")
    if mode == "replay" and seen["replayer"].left():
        raise SystemExit(f"{ds} {task.task_id}: {seen['replayer'].left()} recorded calls never made")
    if mode == "live":
        with open(live, "rb") as f, gzip.open(f"{live}.gz", "wb") as g:
            g.write(f.read())
        live.unlink()
    with gzip.open(f"{base}.result.json.gz", "wt") as f:
        json.dump(json.loads(json.dumps(got, default=str)), f)
    return f"{ds} {task.task_id} {got['status']}"


def main():
    args = sys.argv[1:]
    workers = 12
    if "--workers" in args:
        i = args.index("--workers")
        workers = int(args[i + 1])
        del args[i:i + 2]
    mode, datasets = args[0], args[1:] or ["geolink", "costa", "danish"]
    if DATA is None:
        raise SystemExit("set WELLLOGBENCH to the folder of the datasets' data configs (<dataset>.yaml)")
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    for ds in datasets:
        os.environ["PETROHARNESS_DATA"], os.environ["PETROHARNESS_SET"] = str(DATA / f"{ds}.yaml"), ""
        from petroharness.config import HarnessConfig
        from petroharness.tasks import load_tasks
        cfg = HarnessConfig()
        tasks = {t.task_id: t for t in load_tasks(cfg.eval.questions, cfg.data.las_dir)[0]}
        sel_path = GOLDEN / ds / "selection.json"
        sel = json.loads(sel_path.read_text())
        todo = [tasks[q["task_id"]] for q in sel["questions"]]
        if mode == "live":
            with ThreadPoolExecutor(workers) as ex:
                for line in ex.map(lambda t, ds=ds, model=sel["model"]: one(mode, ds, t, model), todo):
                    print(line, flush=True)
            sel["tapes_from"] = {"code": "petroharness", "commit": commit}
        else:
            for t in todo:
                print(one(mode, ds, t, sel["model"]), flush=True)
            sel.setdefault("tapes_from", {"code": sel.get("code"), "commit": sel.get("commit")})
        sel["code"], sel["commit"], sel["recorded"] = "petroharness", commit, mode
        sel_path.write_text(json.dumps(sel, indent=1) + "\n")


if __name__ == "__main__":
    main()
