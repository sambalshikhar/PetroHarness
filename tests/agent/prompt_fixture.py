"""The rendered prompts of the 12 smoke tasks (6 GeoLink, 3 Costa, 3 Danish), the no-change
fixture of the prompts: the brief, the READ prompt, the step-1 user prompt (its first look: the tools' output), the
DIRECTION index, and the step-2 user prompt after step 1 read two guides and one action the harness does not read (the
guides' text, the sections they open, the not-run note). Rendered with a stub model (no model call) by whichever
petroharness is first on the path, through Session.build, read_question and investigate.

    PYTHONPATH=<a petroharness src> PETROHARNESS_DATA=<geolink.yaml> python tests/agent/prompt_fixture.py IDS_DIR OUT.json.gz LABEL

IDS_DIR holds smoke_ids_<dataset>.json; each dataset's config is found beside PETROHARNESS_DATA (<dataset>.yaml) and
read with the default reporting settings (config: data.basis all, no conventions), so the general and the benchmark
data files render the same fixture.
tests/agent/fixtures/prompts.json.gz is the current rendering (label "v3.5"); tests/agent/test_skill_library.py renders
the same tasks and compares, so a change proves it changes no prompt it does not mean to. A change that alters prompts
on purpose re-renders the fixture after checking that every changed line is intended.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import yaml

DATASETS = ("geolink", "costa", "danish")
STRINGS = ("brief", "read", "step1", "direction", "step2")
DONE = {"edits": [], "next": [], "done": True}


def topics(i: int, areas: list) -> list:
    """Task i's topics: two areas (tasks 0-10 cover all 14); none for the last task."""
    return [] if i == 11 else [areas[i % len(areas)], areas[(i + 7) % len(areas)]]


def reads(i: int, areas: list) -> list:
    """Task i's READ replies: its topics and named curves; the last task's two replies are unreadable (no topics: the
    index in its own order)."""
    if i == 11:
        return ["not JSON", '{"topics": ["no_such_area"], "named": []}']
    return [{"topics": topics(i, areas), "named": ["RDEP", "GR"]}]


def step1(i: int, areas: list) -> dict:
    """Step 1's reply: two guides (the researched library's guides are named for their areas; the last task reads a
    common guide and one that does not exist) and an action the harness does not read."""
    guides = topics(i, areas) or ["answer", "no_such_guide"]
    return {"asks": "What does the formation hold?", "points": ["How does it vary by zone?"], "intent": "characterize",
            "focus": "zones", "edits": [{"op": "add", "point": 1, "text": "It likely varies by zone", "grade": "hypothesis"}],
            "next": [{"guide": g} for g in guides] + [{"jump": "Z1"}], "done": False}


class Stub:
    """The model by stage: the READ replies in turn, step 1's object, then done. Keeps each stage's first messages."""

    def __init__(self, reads, step1):
        self.reads, self.step1, self.sent = list(reads), step1, {}

    def replays_reasoning(self):
        return True

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
        self.sent.setdefault(stage, [m["content"] for m in messages])
        usage.log.append({"stage": stage, "prompt_tokens": 0})
        r = self.reads.pop(0) if stage.startswith("read") else self.step1 if stage == "step_1" else DONE
        return r if isinstance(r, str) else json.dumps(r)


def config(path: Path):
    """A dataset's configuration, passed explicitly (whatever PETROHARNESS_DATA names), with the data's two reporting
    settings at the package's defaults (data.basis "all", no conventions): the fixture holds the prompts of the general
    harness, whichever data files render it (a benchmark's files set the zones basis and its conventions; the golden
    tapes hold those prompts)."""
    from petroharness.config import DataPaths, EvalPaths, HarnessConfig
    d = yaml.safe_load(Path(path).read_text())
    return HarnessConfig(data=DataPaths(**{**d["data"], "basis": "all", "conventions": []}), eval=EvalPaths(**d["eval"]))


def tasks(configs: dict, ids: dict) -> list:
    """[(dataset, qa_id, task, task config)] in the order given."""
    from petroharness.tasks import load_tasks
    out = []
    for ds, qa_ids in ids.items():
        cfg = config(configs[ds])
        ts, index = load_tasks(cfg.eval.questions, cfg.data.las_dir)
        by = {index[t.task_id]["qa_id"]: t for t in ts}
        out += [(ds, q, by[q], cfg.for_tasks()) for q in qa_ids]
    return out


def render(task, cfg, i: int) -> dict:
    """Build the session, run READ with the stub's reply, run steps 1 and 2: the strings the model reads."""
    from petroharness.agent import direction
    from petroharness.agent.loop import Session, investigate, read_question
    from petroharness.llm import Usage
    s = Session.build(task, cfg)
    areas = list(direction.areas())
    llm, trace = Stub(reads(i, areas), step1(i, areas)), {}
    read_question(llm, s, Usage(), 3000, trace)
    investigate(llm, s, Usage(), 3000, trace, max_steps=2)
    (brief, read), (system, first), (system2, second) = llm.sent["read"], llm.sent["step_1"], llm.sent["step_2"]
    assert system == brief == system2, "a step's system prompt is not the READ call's"
    return {"brief": brief, "read": read, "step1": first,
            "direction": first.split("\n\nDIRECTION\n", 1)[1].split("\n\n", 1)[0], "step2": second}


def main() -> None:
    import os
    import warnings
    ids_dir, out, label = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    here = Path(os.environ["PETROHARNESS_DATA"]).parent
    ids = {ds: json.loads((ids_dir / f"smoke_ids_{ds}.json").read_text())["qa_ids"] for ds in DATASETS}
    rows = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for i, (ds, q, t, cfg) in enumerate(tasks({ds: here / f"{ds}.yaml" for ds in DATASETS}, ids)):
            rows.append({"dataset": ds, "qa_id": q, "task_id": t.task_id, **render(t, cfg, i)})
            print(ds, q, {k: len(rows[-1][k]) for k in STRINGS}, flush=True)
    out.write_bytes(gzip.compress(json.dumps({"rendered_by": label, "tasks": rows}, indent=1).encode(), mtime=0))


if __name__ == "__main__":
    main()
