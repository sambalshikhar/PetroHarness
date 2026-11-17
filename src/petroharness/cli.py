"""The console script. `petroharness --las WELL.las --question "..." ...` answers one question about one LAS file
(petroharness.ask; docs/USAGE.md), the default; `petroharness ui` starts the web UI (petroharness.ui,
docs/UI.md); `petroharness benchmark ...` is the validation mode below.

Benchmark mode runs the harness on benchmark questions, each as a user's question is run: the model first says
whether the question is direct (the direct route) or needs an investigation (petroharness.agent.graph; --investigate
gives every question the full investigation). The run takes the question, the well and the formation; the
evaluation index's category only groups the output files.

    PETROHARNESS_DATA=<data config> PETROHARNESS_MODEL_URL=<servers> petroharness benchmark --arm A1 --rep 1 \
        --cats hydrocarbon,porosity --ids IDS.json --gt-dir GT --workers 40
writes runs/<ARM>_<model>[r<rep>]_<cat>/{responses,traces} and the judge's reference subset runs/gt_subsets/<prefix>
(the evaluation side; the harness never reads it). Resumes from saved traces of the same commit. The defaults are
the configuration the benchmark runs with (model k200t, writer open, the reporting profile's format). Another
model: --model NAME (any chat model on an OpenAI-compatible endpoint) or --model-card CARD (docs/MODELS.md).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from petroharness.agent import direction
from petroharness.agent.graph import answer as graph_answer
from petroharness.agent.loop import MAX_STEPS
from petroharness.config import REPO_ROOT as ROOT, HarnessConfig
from petroharness.tasks import load_tasks

COMMIT = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


def save(prefix: str, model_key: str, arm: str, items: list, index: dict, gt_dir: Path | None = None) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    by_cat: dict = {}
    for t, r in items:
        by_cat.setdefault(index[t.task_id]["category"], []).append((t, r))
    for cat, rows in by_cat.items():
        out = ROOT / "runs" / f"{prefix}_{cat}"
        (out / "traces").mkdir(parents=True, exist_ok=True)
        (out / "responses").mkdir(exist_ok=True)
        for t, r in rows:
            (out / "traces" / f"{t.task_id}.json").write_text(json.dumps(r["trace"], indent=1, default=str))
        name = f"single_formation_{cat}_qa_pairs.json"
        pairs = [{"qa_id": index[t.task_id]["qa_id"], "question": t.question, "answer": r["answer"]} for t, r in rows]
        (out / "responses" / name).write_text(json.dumps({"metadata": {"category": cat, "model": model_key, "harness": f"petroharness {arm}",
                                                                       "created_utc": now, "answer_count": str(len(pairs))},
                                                          "qa_pairs": pairs}, indent=1))
        gt_all = json.loads(((gt_dir or ROOT / "runs" / "gt_subsets" / "dev") / name).read_text())
        gt_rows = gt_all["qa_pairs"] if isinstance(gt_all, dict) else gt_all
        keep = {p["qa_id"] for p in pairs}
        sub = ROOT / "runs" / "gt_subsets" / prefix
        sub.mkdir(parents=True, exist_ok=True)
        kept = [p for p in gt_rows if p["qa_id"] in keep]
        (sub / name).write_text(json.dumps({**gt_all, "qa_pairs": kept} if isinstance(gt_all, dict) else kept, indent=1))


def answer(task, model_key: str, rep: int, max_steps: int, writer: str = "", fmt: str = "profile",
           direct: bool = True) -> dict:
    """One question through the question graph (src/petroharness/agent/graph.py, docs/GRAPH.md) -> {"answer", "status",
    "trace"}. direct=False: the full investigation for every question."""
    return graph_answer(task, model_key, rep, max_steps, writer, fmt, commit=COMMIT, depth=direct)


def main():
    """petroharness [own-well options] (the default), petroharness ui [server options], petroharness benchmark [batch
    options]; arguments with --arm (the batch runner's older form, used by scripts) run the benchmark too."""
    argv = sys.argv[1:]
    if argv[:1] == ["benchmark"]:
        return benchmark(argv[1:])
    if argv[:1] == ["chat"]:                   # a conversation on one interval (src/petroharness/session)
        from petroharness.session.chat import main as chat_main
        return chat_main(argv[1:])
    if argv[:1] == ["setup"]:                  # what questions are answered under, with one hash (src/petroharness/core/setup.py)
        from petroharness.core.setup import main as setup_main
        return setup_main(argv[1:])
    if argv[:1] == ["report"]:                 # a conversation as one document (src/petroharness/evidence/report.py)
        from petroharness.evidence.report import main as report_main
        return report_main(argv[1:])
    if argv[:1] == ["audit"]:                  # an answer's audit trail from its session folder (src/petroharness/evidence)
        from petroharness.evidence.audit import main as audit_main
        return audit_main(argv[1:])
    if argv[:1] == ["ui"]:                     # the web UI (src/petroharness/ui, docs/UI.md)
        from petroharness.ui.server import main as ui_main
        return ui_main(argv[1:])
    if any(a == "--arm" or a.startswith("--arm=") for a in argv):
        return benchmark(argv)
    from petroharness.ask import main as ask_main
    return ask_main(argv[1:] if argv[:1] == ["ask"] else argv)


def benchmark(argv=None):
    """Benchmark mode: the questions of a benchmark's index through the harness, answers and traces under runs/."""
    ap = argparse.ArgumentParser(prog="petroharness benchmark",
                                 description="Validation mode: run the harness on a benchmark's questions.")
    ap.add_argument("--arm", required=True)
    ap.add_argument("--cats", default="hydrocarbon")
    ap.add_argument("--models", default="k200t", help="model registry keys, comma-separated (petroharness.models)")
    ap.add_argument("--model", help="the served model's name, for any chat model (the generic card; instead of --models)")
    ap.add_argument("--model-card", help="a model card: a YAML file or a packaged card's name (instead of --models)")
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--ids", required=True, help="JSON file {qa_ids: [...]}")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    ap.add_argument("--gt-dir", type=Path, required=True)
    ap.add_argument("--writer", default="open", help="the writer's repair rounds: open (two, the default) or '' (one)")
    ap.add_argument("--format", default="profile", choices=["profile", "default"],
                    help="the answer format: the reporting profile's format block, or the writer's own")
    ap.add_argument("--investigate", action="store_true",
                    help="give every question the full investigation (default: the model first "
                         "says whether a question is direct, and a direct question takes the direct route)")
    args = ap.parse_args(argv)
    cfg = HarnessConfig()
    direction.plugged(cfg)                     # the skill library (skills, PETROHARNESS_SKILLS): a bad one stops the run here
    tasks, index = load_tasks(cfg.eval.questions, cfg.data.las_dir)
    wanted = set(json.loads(Path(args.ids).read_text())["qa_ids"])
    cats = set(args.cats.split(","))
    tasks = [t for t in tasks if index[t.task_id]["qa_id"] in wanted and index[t.task_id]["category"] in cats]
    summary = {}
    if args.model or args.model_card:
        from petroharness.models import MODELS, card_file, env_urls, register
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", args.model or Path(card_file(args.model_card)).stem)
        keys = {name: register(env_urls() or MODELS["k200t"][1], args.model_card, args.model)}
    else:
        keys = {m: m for m in args.models.split(",")}
    for m, key in keys.items():
        prefix = f"{args.arm}_{m}" + (f"r{args.rep}" if args.rep > 1 else "")

        def one(t):
            group = index[t.task_id]["category"]                 # the output folder only; the run never sees it
            path = ROOT / "runs" / f"{prefix}_{group}" / "traces" / f"{t.task_id}.json"
            if path.exists():
                tr = json.loads(path.read_text())
                if tr.get("commit") == COMMIT and "answer" in tr and not str(tr.get("status", "")).startswith("error"):
                    return {"answer": tr["answer"], "status": tr["status"], "trace": tr}
            r = answer(t, key, args.rep, args.max_steps, args.writer, args.format, direct=not args.investigate)
            r["trace"]["answer"] = r["answer"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(r["trace"], indent=1, default=str))
            return r

        with ThreadPoolExecutor(args.workers) as ex:
            results = list(ex.map(one, tasks))
        save(prefix, m, args.arm, list(zip(tasks, results)), index, args.gt_dir)
        tr = [r["trace"] for r in results]
        summary[m] = {"prefix": prefix, "commit": COMMIT, "writer": args.writer, "format": args.format,
                      "route": "investigate" if args.investigate else "direct",
                      "n": len(tr), "ok": sum(r["status"] == "ok" for r in results),
                      "unresolved": sum(r["status"] == "unresolved_numbers" for r in results),
                      "errors": sum(str(r["status"]).startswith("error") for r in results),
                      "steps_mean": round(sum(len(x.get("steps", [])) for x in tr) / max(len(tr), 1), 2),
                      "opened_mean": round(sum(len(x.get("opened", [])) for x in tr) / max(len(tr), 1), 1)}
    (ROOT / "runs" / "summaries").mkdir(parents=True, exist_ok=True)
    (ROOT / "runs" / "summaries" / f"run_{args.arm}_r{args.rep}.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    sys.exit(main())
