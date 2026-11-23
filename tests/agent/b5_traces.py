"""The investigation loop's measures L1, L2, L3 and L5, on the traces of saved runs (L4, the traps: b5_traps.py).

    .venv/bin/python tests/agent/b5_traces.py OUT.json PREFIX [PREFIX ...]

L1 replies read without repair; tool calls that ran; questions answered.
L2 end state: every point settled (graded, cited, unflagged; undetermined with its reason); no hypothesis left; flags
   left; graded claims whose text is still provisional (the finding went into 'means' and the text kept the plan).
L3 breadth: for each facet the model read (guide), the sections it lists that this formation has, opened; and the
   sections of its topics' families opened (needs the formation: run on a compute node).
L5 the largest prompt per question (tokens) and the share of questions done before the last step.
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
warnings.simplefilter("ignore")

PROVISIONAL = re.compile(r"\b(still (?:unknown|unclear|to be \w+|open|pending)|not yet|to be (?:checked|verified|confirmed|"
                         r"determined|tested)|needs? (?:to be )?(?:check|verif|confirm)\w*|pending|unverified|tbd|"
                         r"must (?:be )?verif\w*|yet to be)\b", re.I)
TOOLS = ("stats", "runs", "compare", "profile", "section", "step")


def _sections_of(facet: str) -> list:
    from petroharness.agent.direction import parse_source, plugged
    out = []
    for e in plugged().facets.get(facet, {}).get("compare", []):
        src = parse_source(e)
        if src and src[0] == "section":
            out.append(src[1]["key"])
    return out


def per_question(tr: dict, have_sections=None) -> dict:
    steps = tr.get("steps", [])
    calls = [a for st in steps if "done_issues" not in st for a in st.get("actions", [])
             if a.split(" ", 1)[0] in TOOLS + ("get", "find")]
    claims = tr.get("claims", [])
    points = tr.get("points") or []
    settled = {c["point"] for c in claims if c["grade"] != "hypothesis" and not c["flags"]}
    graded = [c for c in claims if c["grade"] not in ("hypothesis",)]
    opened_keys = [ct.split(" ", 1)[1].split(" (")[0].strip() for _, ct in tr.get("opened") or [] if ct.startswith("section ")]
    hit = lambda key: any(key == k or key.endswith("." + k) for k in opened_keys)     # a section may be named by its short key
    out = {"task_id": tr["task_id"], "topics": tr.get("topics") or [], "status": tr.get("status"),
           "steps": len(steps), "repaired": sum(1 for st in steps if st.get("repaired")),
           "calls": len(calls), "errors": len(tr.get("errors") or []),
           "answered": bool((tr.get("answer") or "").strip()),
           "points": len(points), "points_settled": sum(1 for k in range(1, len(points) + 1) if k in settled),
           "hypotheses_left": sum(1 for c in claims if c["grade"] == "hypothesis"),
           "flags_left": sum(len(c["flags"]) for c in claims),
           "graded": len(graded), "graded_provisional": sum(1 for c in graded if PROVISIONAL.search(c["text"] or "")),
           "max_prompt_tokens": max([st.get("prompt_tokens") or 0 for st in steps] + [0]),
           "done_early": any(st.get("done") and "done_issues" not in st for st in steps[:-1]) or
                         (bool(steps) and steps[-1].get("done") and len(steps) < 8),
           "guides": list(tr.get("guides") or []), "opened_sections": opened_keys}
    if have_sections is not None:
        want = sorted({k for g in out["guides"] for k in _sections_of(g) if k in have_sections})
        out["guide_sections"], out["guide_sections_opened"] = len(want), sum(hit(k) for k in want)
        from petroharness.agent.direction import families
        own = sorted(k for k in have_sections if k.split(".")[0] in families(tr.get("topics")))
        out["own_sections"], out["own_sections_opened"] = len(own), sum(hit(k) for k in own)
    return out


def summarize(rows: list) -> dict:
    n = len(rows)
    tot = lambda k: sum(r[k] for r in rows)
    end_ok = [r["points_settled"] == r["points"] and r["hypotheses_left"] == 0 for r in rows]
    s = {"n": n,
         "L1_steps_read_without_repair": 1 - tot("repaired") / max(1, tot("steps")),
         "L1_calls_ran": 1 - tot("errors") / max(1, tot("calls")),
         "L1_answered": tot("answered") / n,
         "L2_end_state_ok": sum(end_ok) / n,
         "L2_points_settled": tot("points_settled") / max(1, tot("points")),
         "L2_hypotheses_left_per_q": tot("hypotheses_left") / n,
         "L2_flags_left_per_q": tot("flags_left") / n,
         "L2_graded_text_provisional": tot("graded_provisional") / max(1, tot("graded")),
         "L5_max_prompt_tokens": max(r["max_prompt_tokens"] for r in rows),
         "L5_questions_over_12k": sum(r["max_prompt_tokens"] > 12000 for r in rows),
         "L5_done_before_last_step": sum(bool(r["done_early"]) for r in rows) / n,
         "steps_mean": tot("steps") / n, "calls_mean": tot("calls") / n}
    if rows and "guide_sections" in rows[0]:
        s["L3_guide_sections_opened"] = tot("guide_sections_opened") / max(1, tot("guide_sections"))
        s["L3_questions_with_guide_sections"] = sum(r["guide_sections"] > 0 for r in rows)
        s["L3_own_sections_opened"] = tot("own_sections_opened") / max(1, tot("own_sections"))
    return s


def main():
    out, prefixes = sys.argv[1], sys.argv[2:]
    from petroharness.config import HarnessConfig
    from petroharness.tasks import load_tasks
    from petroharness.agent.state import Session
    cfg = HarnessConfig()
    tasks, _ = load_tasks(cfg.eval.questions, cfg.data.las_dir)
    by_id = {t.task_id: t for t in tasks}
    sections = {}
    rows = defaultdict(list)
    for prefix in prefixes:
        for path in sorted((ROOT / "runs").glob(f"{prefix}_*/traces/*.json")):
            tr = json.loads(path.read_text())
            t = by_id.get(tr["task_id"])
            if t is not None and t.task_id not in sections:
                s = Session.build(t, cfg.for_tasks())
                sections[t.task_id] = {sec.key for sec in s.f.inv.sections}
            rows[prefix].append(per_question(tr, sections.get(tr["task_id"])))
    report = {p: summarize(r) for p, r in rows.items()}
    every = [x for r in rows.values() for x in r]
    report["all"] = summarize(every)
    by_topic = defaultdict(list)                       # by the model's first topic
    for x in every:
        by_topic[(x["topics"] or ["none"])[0]].append(x)
    report["by_topic"] = {c: summarize(r) for c, r in sorted(by_topic.items())}
    Path(out).write_text(json.dumps({"report": report, "rows": rows}, indent=1))
    print(json.dumps(report["all"], indent=1))
    for c, r in report["by_topic"].items():
        print(c, {k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()
                  if k.startswith(("L2_end", "L2_graded", "L3", "L5_done", "L1_calls"))})


if __name__ == "__main__":
    main()
