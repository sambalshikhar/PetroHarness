"""The request gate: does a change alter anything the model is sent on a first question?

For every saved run of a reference build, the question is run again with the model's replies taken from the run's
trace, in the order its route took them (Replies: a direct question's look steps, a writer that handed it to an
investigation, the investigation's steps, the writer), and every request the code builds is hashed (each message of
each call, its schema, its token cap, its temperature and its retry flag), with the status and the answer. Two builds
are the same for the model when their hash files are equal. Unlike the golden tapes (36 questions), this covers every
saved run of the reference runs (docs/DEVELOPMENT.md, "The reference runs").

A replay is not the run again. A step's reply is rebuilt from the fields its trace kept, and the writer's and a
repair's reply is the run's final answer, so a replay may take fewer steps or other repairs than the run took. It
gives both codes the same replies, and that is what the gate compares: given the same replies, does the code build the
same requests? The golden tapes hold every reply verbatim, for the questions they cover.

    record:   python tests/gate/request_gate.py record --runs RUNS --prefix PREFIX --ids IDS.json --card CARD --out FILE
              RUNS: a folder of saved runs (<PREFIX>_<category>/traces/<task id>.json, as the benchmark runner
              writes them); IDS.json: {"qa_ids": [...]}, the questions to replay; CARD: the runs' model card. The data
              settings are the environment's (PETROHARNESS_DATA), as for a benchmark run. PYTHONPATH selects the code
              under test. One process replays one run at a time (--workers 1, the default): replays in several
              threads of one process are not fully deterministic. --investigate: the runs were made with every
              question investigated (the 3.5.6 route, the benchmark runner's --investigate).
    compare:  python tests/gate/request_gate.py compare BASE.jsonl NEW.jsonl [BASE2.jsonl NEW2.jsonl ...]
              every difference is counted by kind (stage, messages, parameters, status, answer); exit 0 when none.

The saved runs are a benchmark's, so this gate is a maintainer's tool: it needs the benchmark data. The public mini
set (tests/gate/test_mini.py) is the gate anyone can run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import warnings
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _h(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _action(a: str):
    """A recorded action line ("stats {...}", "get E3 terms") as the step object's action."""
    head, _, rest = a.partition(" ")
    if head == "get":
        eid, _, terms = rest.partition(" ")
        return {"get": eid, "find": terms} if terms.strip() else {"get": eid}
    if head in ("find", "guide", "calc"):
        return {head: rest}
    try:
        return {head: json.loads(rest) if rest.strip() else {}}
    except json.JSONDecodeError:
        return None


def step_reply(trace: dict, k: int) -> str:
    """Step k's reply rebuilt from what the trace recorded of it (the points, the edits, the actions it asked for)."""
    st = trace["steps"][k - 1]
    obj = {}
    if k == 1:
        pts = list(trace.get("points") or [])
        obj["asks"] = st.get("asks") or (pts[0] if pts else "")
        obj["points"] = pts[1:]
        obj["intent"] = trace.get("intent")
    obj["focus"] = st.get("focus")
    obj["edits"] = [{j: v for j, v in e.items() if j not in ("flags", "history")} for e in st.get("edits") or []]
    auto = {g if " " in g else f'section {json.dumps({"key": g})}' for g in st.get("guide_sections") or []}
    obj["next"] = [x for x in (_action(a) for a in st.get("actions") or [] if a not in auto) if x]
    obj["done"] = bool(st.get("done"))
    return json.dumps(obj)


def replies(trace: dict, stage: str) -> str:
    """The reply a saved run gave at a stage (the writer's and a repair's: the run's final answer), for a run that was
    investigated from its first step (no look steps; Replies serves any run)."""
    base = stage.replace("_retry", "").replace("_fix", "").replace("_points", "")
    if base == "read":
        return (trace.get("read") or {}).get("reply") or "{}"
    if base == "settle" or base.startswith("step_0"):
        return json.dumps({"edits": [{j: v for j, v in e.items() if j not in ("flags", "history")}
                                     for e in (trace.get("settle") or {}).get("edits") or []], "done": True})
    if base.startswith("step_"):
        if stage.endswith("_points"):
            return json.dumps({"points": list(trace.get("points") or [])[1:], "intent": trace.get("intent")})
        return step_reply(trace, int(base.split("_")[1]))
    return trace.get("answer") or ""


class Replies:
    """The replies of one saved run, in the order its route asked for them. A question read as direct first takes its
    look steps (each one's recorded reply); a look reply or the short answer's writer may have handed it to an
    investigation (the writer's word, INVESTIGATE); then the investigation's steps, numbered from 1 again, and the
    writer. The look steps and the investigation's steps share their stage names, so the calls are served in order."""

    HAND_OVER = "INVESTIGATE"

    def __init__(self, trace: dict):
        steps = trace.get("steps") or []
        self.trace = trace
        self.looks = [s for s in steps if s.get("direct")]
        self.investigation = {**trace, "steps": [s for s in steps if not s.get("direct")]}
        back = trace.get("depth") if isinstance(trace.get("depth"), dict) else {}
        self.writer_hands_over = back.get("investigated_from") == "the writer"
        self.looked = 0                                   # look replies served
        self.handed = False

    def __call__(self, stage: str) -> str:
        base = stage.replace("_retry", "").replace("_fix", "").replace("_points", "")
        if base.startswith("step_") and not base.startswith("step_0") and not stage.endswith("_points"):
            k = int(base.split("_")[1])
            if self.looked < len(self.looks) and k == self.looked + (0 if stage != base else 1):
                if stage == base:                         # a look step's own call; its retry or fix gets the same reply
                    self.looked += 1
                return self.looks[self.looked - 1].get("reply") or "{}"
            return step_reply(self.investigation, k)
        if stage == "writer" and self.writer_hands_over and not self.handed:
            self.handed = True                            # the short answer's writer handed the question over
            return self.HAND_OVER
        return replies(self.investigation, stage)


def record(args) -> int:
    warnings.simplefilter("ignore")
    from petroharness.agent import graph
    from petroharness.config import HarnessConfig
    from petroharness.llm import LLM
    from petroharness.models import register
    from petroharness.tasks import load_tasks
    ids = set(json.loads(Path(args.ids).read_text())["qa_ids"])
    cfg = HarnessConfig()
    tasks, index = load_tasks(cfg.eval.questions, cfg.data.las_dir)
    tasks = [t for t in tasks if index[t.task_id]["qa_id"] in ids]
    key = register(["http://unused:1/v1"], args.card)

    def run(t):
        path = Path(args.runs) / f"{args.prefix}_{index[t.task_id]['category']}" / "traces" / f"{t.task_id}.json"
        trace, calls = json.loads(path.read_text()), []
        served = Replies(trace)

        class Replayed(LLM):
            def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
                usage.add(stage, None, 0.0, content_chars=0, reasoning_chars=0, finish_reason="stop")
                calls.append([stage, [_h(m["role"] + "\x00" + (m.get("content") or "")) for m in messages],
                              _h(json.dumps(json_schema, sort_keys=True)) if json_schema else "", max_tokens,
                              temperature, retry])
                return served(stage)
        try:
            r = graph.answer(t, key, 1, graph.MAX_STEPS, args.writer, "profile", llm_factory=Replayed,
                             depth=not args.investigate)
            status, answer = r["status"], _h(r["answer"])
        except Exception as exc:                              # noqa: BLE001 - a replay that breaks is recorded
            status, answer = "ERROR " + repr(exc)[:200], ""
        return {"task_id": t.task_id, "calls": calls, "status": status, "answer": answer}

    with ThreadPoolExecutor(args.workers) as ex:
        rows = sorted(ex.map(run, tasks), key=lambda r: r["task_id"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("".join(json.dumps(r) + "\n" for r in rows))
    broken = sum(r["status"].startswith("ERROR") for r in rows)
    print(f"{args.prefix}: {len(rows)} runs, {sum(len(r['calls']) for r in rows)} calls, {broken} replay errors")
    return 1 if broken else 0


def compare(pairs: list) -> int:
    """Each (base file, new file): the runs whose requests, status and answer are equal; every difference by kind."""
    total = same = 0
    kinds, examples = Counter(), []
    for base_file, new_file in pairs:
        load = lambda f: {r["task_id"]: r for r in map(json.loads, Path(f).read_text().splitlines())}
        base, new = load(base_file), (load(new_file) if Path(new_file).exists() else None)
        if new is None:
            kinds["file missing"] += 1
            total += len(base)
            print(f"{Path(base_file).stem:16s} MISSING: {new_file}")
            continue
        equal = 0
        for k, b in base.items():
            total += 1
            o = new.get(k)
            if o is None:
                kinds["run missing"] += 1
                continue
            if b == o:
                same += 1
                equal += 1
                continue
            if len(b["calls"]) != len(o["calls"]):
                kinds["number of calls"] += 1
            for i, (x, y) in enumerate(zip(b["calls"], o["calls"])):
                if x != y:
                    what = "stage" if x[0] != y[0] else ("messages" if x[1] != y[1] else "parameters")
                    kinds[f"{what} at {x[0]}"] += 1
                    if len(examples) < 10:
                        examples.append((Path(base_file).stem, k, i, x[0], what))
            kinds["status"] += b["status"] != o["status"]
            kinds["answer"] += b["answer"] != o["answer"]
        print(f"{Path(base_file).stem:16s} {equal}/{len(base)} identical")
    print(f"\n{same}/{total} runs identical (calls, messages, parameters, status, answer)")
    for kind, n in kinds.most_common():
        if n:
            print(f"  {n:5d}  {kind}")
    for e in examples:
        print("  e.g.", e)
    return 0 if total and same == total else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tests/gate/request_gate.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="hash every request the code under test builds for saved runs")
    rec.add_argument("--runs", required=True, help="the folder of saved runs")
    rec.add_argument("--prefix", required=True, help="the runs' prefix (the benchmark runner's <arm>_<model>)")
    rec.add_argument("--ids", required=True, help='JSON file {"qa_ids": [...]}')
    rec.add_argument("--card", required=True, help="the model card the runs were made with")
    rec.add_argument("--writer", default="open", help="the writer's repair rounds the runs used (default: open)")
    rec.add_argument("--out", required=True)
    rec.add_argument("--workers", type=int, default=1)
    rec.add_argument("--investigate", action="store_true",
                     help="the runs gave every question the investigation (the 3.5.6 route; benchmark --investigate)")
    cmp_ = sub.add_parser("compare", help="compare hash files pair by pair")
    cmp_.add_argument("files", nargs="+", help="BASE.jsonl NEW.jsonl [BASE2.jsonl NEW2.jsonl ...]")
    args = ap.parse_args(argv)
    if args.cmd == "record":
        return record(args)
    if len(args.files) % 2:
        ap.error("compare takes pairs of files: BASE.jsonl NEW.jsonl ...")
    return compare(list(zip(args.files[::2], args.files[1::2])))


if __name__ == "__main__":
    sys.exit(main())
