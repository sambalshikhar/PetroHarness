"""Writer replay: rebuild a saved investigation and run only the writer.

    s, report = rebuild(trace, task)      the session with the ledger replayed from the traced tool calls (in order, so the
                                          ids match) and the claims restored; report says whether the rebuild is exact
    metrics(s, answer, trace)             the writer's per-answer checks (W1-W9)

    .venv/bin/python tests/agent/replay.py PREFIX OUT.json [--variant NAME] [--limit N]
writes the replayed answers and their metrics; with --variant it runs the writer under that variant's options.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
warnings.simplefilter("ignore")

from petroharness.agent.claims import Claim, Claims  # noqa: E402
from petroharness.agent.engine import ToolError  # noqa: E402
from petroharness.agent.loop import Session  # noqa: E402

NUM = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?(?![A-Za-z0-9_])")


def _action(a: str):
    """'stats {"curves": [...]}' -> ("stats", {...}); 'get E1 Z1' and the like -> None (they open nothing)."""
    name, _, rest = a.partition(" ")
    from petroharness.agent.tools import TOOLS
    if name in TOOLS:
        try:
            return name, json.loads(rest)
        except json.JSONDecodeError:
            return None
    return None


def rebuild(trace: dict, task, cfg) -> tuple:
    """The session as the investigation left it; report: opened items equal to the trace's, and the claims' flags
    (re-checked now) equal to the traced flags."""
    s = Session.build(task, cfg)
    if trace.get("topics"):                           # the topics the READ call chose, when the trace has them
        s.choose(trace["topics"])
        s.reading = dict(trace.get("read") or {})
    want = [list(x) for x in trace.get("opened", [])]

    def keep_traced() -> None:                        # a call that failed then and runs now (later fixes) is not kept
        while s.ledger.items and (len(s.ledger.items) > len(want)
                                  or s.ledger.items[-1].call_text() != want[len(s.ledger.items) - 1][1]):
            e = s.ledger.items.pop()
            s.ledger._keys = {k: v for k, v in s.ledger._keys.items() if v is not e}
    for k in ("overview", "overview_summary"):         # the first look (and its formation summary), before step 1
        if not trace.get(k):
            continue
        act = _action(trace[k])
        if act is not None:
            try:
                s.ledger.open(*act)
            except Exception:
                pass
            keep_traced()
    for step in trace.get("steps", []):
        if "done_issues" in step:                     # the loop checked done before running them: they never ran
            continue
        for a in step.get("actions", []):
            act = _action(a)
            if act is None:
                if a.startswith("guide "):
                    s.guides.append(a.split(" ", 1)[1])
                elif a.startswith("calc "):
                    s.run(("calc", a.split(" ", 1)[1]))
                    keep_traced()
                continue
            try:
                s.ledger.open(*act)
            except Exception:                         # as the loop does: a call that failed then fails now
                pass
            keep_traced()
    s.points, s.intent = list(trace.get("points") or []), trace.get("intent") or "characterize"
    s.claims = Claims(s.points, s.ledger, s.map, task.question, s.f.view, (task.well,))
    for d in trace.get("claims", []):
        s.claims.claims[d["id"]] = Claim(**{k: d[k] for k in ("id", "point", "text", "means", "ev", "grade", "weak", "flags", "history")})
    s.claims._n = max([int(k[1:]) for k in s.claims.claims] + [0])
    traced_flags = {c.id: [f.split(" ")[0] for f in c.flags] for c in s.claims.claims.values()}
    s.claims.refresh()
    now_flags = {c.id: [f.split(" ")[0] for f in c.flags] for c in s.claims.claims.values()}
    opened = [[e.id, e.call_text()] for e in s.ledger.items]
    return s, {"opened_equal": opened == [list(x) for x in trace.get("opened", [])],
               "flags_equal": traced_flags == now_flags, "n_opened": len(opened)}


# --- the writer's checks ------------------------------------------------------------------------------------------

CONFIDENCE = re.compile(r"\b(?:low|moderate|high)(?:[- ]to[- ](?:low|moderate|high))?[- ]confidence\b|"
                        r"\bconfidence(?: in [^.:;\n]{1,60}?)?(?: is|:)\s*(?:low|moderate|high)\b", re.I)


def _covered(claim_text: str, answer_nums: list) -> bool:
    """A claim's key numbers (three or more significant digits) appear in the answer at the answer's own precision."""
    nums = [x for x in NUM.findall(claim_text) if len(re.sub(r"[^0-9]", "", x).lstrip("0")) >= 3]
    if not nums:
        return True
    for x in nums[:3]:
        v = float(x)
        for a in answer_nums:
            dec = len(a.split(".")[1]) if "." in a else 0
            if abs(float(a) - v) <= 0.5 * 10 ** (-dec) * 1.001 + 1e-9 * max(1, abs(v)):
                return True
    return False


def metrics(s, answer: str, trace: dict) -> dict:
    from petroharness.agent.writer import META, PROCESS
    claims = [c for c in s.claims.claims.values() if c.grade != "hypothesis"]
    settled = [c for c in claims if not c.flags]
    anums = NUM.findall(answer)
    cov = [_covered(c.text, anums) for c in settled]
    words = lambda t: {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z_]{5,}", t)} - {"between", "within", "across", "formation"}
    pts = []
    for p in s.points:
        w = words(p)
        pts.append(not w or len(w & words(answer)) / len(w) >= 0.5)
    absent = bool(trace.get("absent"))
    said = bool(re.search(r"\b(not available|not logged|not in (?:this|the) (?:well|interval|log set)|absent|missing|no "
                          r"(?:\w+ ){0,3}(?:log|curve|measurement)s?\b|was not (?:run|acquired|recorded))", answer, re.I))
    conf = len(CONFIDENCE.findall(answer))
    lines = answer.split("\n")
    bad_table = any(ln.lstrip().startswith("|") and i > 0 and lines[i - 1].strip() and not lines[i - 1].lstrip().startswith("|")
                    for i, ln in enumerate(lines)) or bool(re.search(r"[^\n|]\s\|\s*Zone\s*\|", answer))
    known = set(s.f.inv.curves) | set(s.f.inv.logs_absent) | set(s.f.inv.logs_present) | \
        {c.name for sec in s.f.inv.sections for c in sec.classes} | {z.id for z in s.f.inv.zones} | \
        {getattr(z, "name", "") for z in s.f.view.zones} | {sec.key.split(".")[0].upper() for sec in s.f.inv.sections} | \
        {c for m in (s.f.view.reg.curves.get("named_measurements") or {}).values() for c in m} | \
        {c for fam in (s.f.view.reg.curves.get("families") or {}).values() for c in fam}
    names = {t for t in re.findall(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9]*_[A-Z0-9_]+(?![A-Za-z0-9_])", answer)}
    shown = "\n".join([s.map, s.task.question] + [e.text for e in s.ledger.items])
    in_data = lambda n: n in known or re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", shown)
    claims_text = " ".join(f"{c.text} {c.means} {c.weak}" for c in s.claims.claims.values())
    unknown = sorted(n for n in names if not in_data(n) and n not in claims_text)       # the writer's own
    from_claims = sorted(n for n in names if not in_data(n) and n in claims_text)       # the loop's
    zone_names = {z.zone_id: getattr(z, "name", "") for z in s.f.view.zones}
    mentioned = [z for z in zone_names if re.search(rf"(?<![A-Za-z0-9_]){z}(?![0-9])", answer)]
    named = [z for z in mentioned if zone_names[z] and zone_names[z] in answer]
    from petroharness.agent.engine import same_as
    pairs = [(c, same_as(s.f, c)) for c in s.f.inv.curves if same_as(s.f, c)]
    word = lambda n: re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", answer)
    used = [(c, t) for c, t in pairs if word(c)]
    heads = [h.strip().lower() for h in re.findall(r"^#+\s*(.+)$", answer, re.M)]
    prose = "\n".join(l for l in answer.splitlines() if not l.lstrip().startswith("|"))
    form = {"overview_first": bool(heads) and heads[0].startswith("formation overview"),
            "limitations": any(h.startswith("data limitations") for h in heads),
            "conclusions_last": bool(heads) and heads[-1].startswith("conclusion"),
            "zone_ids_in_prose": len(re.findall(r"(?<![A-Za-z0-9_])Z\d+\b", prose))}
    vr = trace.get("verify_rounds") or [{}]
    verdict = re.compile(r"\b(confirmed|proven|established|commercial)\b", re.I)
    negated = re.compile(r"\b(not|no|never|neither|nor|cannot|can ?not|without|un|would|could|needs?|requires?|only by)\b", re.I)
    clauses = [x for x in re.split(r"(?<=[.;!?])\s+|\n+", answer) if x.strip()]
    verdicts = sum(1 for x in clauses if verdict.search(x) and not negated.search(x))
    return {"W1_untraced": bool(vr[-1].get("unsupported")),
            "W13_verdict_clauses": verdicts,
            "W15_contradictions_left": bool(vr[-1].get("contradictions")), "repair_rounds": max(0, len(vr) - 1),
            "W2_claim_coverage": sum(cov) / len(cov) if cov else 1.0,
            "W3_notes": bool(META.search(answer)), "W3_process": len(PROCESS.findall(answer)),
            "W4_points": sum(pts) / len(pts) if pts else 1.0,
            "W5_absent_said": (said if absent else None),
            "W6_conf_per_settled": min(1.0, conf / len(settled)) if settled else 1.0,
            "W7_bad_table": bad_table, "W8_unknown_names": unknown, "W8_names_from_claims": from_claims,
            "W9_zones_named": (len(named) / len(mentioned)) if mentioned else None,
            "W10_twins_named": (sum(all(word(x) for x in t) for _, t in used) / len(used)) if used else None,
            "W11_format": form,
            "words": len(answer.split())}


def summarize(rows: list) -> dict:
    n = len(rows)
    mean = lambda k: sum(r[k] for r in rows if r[k] is not None) / max(1, sum(1 for r in rows if r[k] is not None))
    return {"n": n, "W1_untraced_share": sum(r["W1_untraced"] for r in rows) / n,
            "W2_claim_coverage": mean("W2_claim_coverage"), "W3_notes": sum(r["W3_notes"] for r in rows),
            "W3_process_per_answer": mean("W3_process"), "W4_points": mean("W4_points"),
            "W5_absent_said": mean("W5_absent_said") if any(r["W5_absent_said"] is not None for r in rows) else None,
            "W6_conf": mean("W6_conf_per_settled"), "W7_bad_tables": sum(r["W7_bad_table"] for r in rows),
            "W8_answers_with_unknown_names": sum(bool(r["W8_unknown_names"]) for r in rows),
            "W8_answers_with_claim_names_not_in_data": sum(bool(r.get("W8_names_from_claims")) for r in rows),
            "W9_zones_named": mean("W9_zones_named") if any(r["W9_zones_named"] is not None for r in rows) else None,
            "W10_twins_named": mean("W10_twins_named") if any(r.get("W10_twins_named") is not None for r in rows) else None,
            "W11_overview_first": sum(r["W11_format"]["overview_first"] for r in rows if "W11_format" in r),
            "W11_limitations": sum(r["W11_format"]["limitations"] for r in rows if "W11_format" in r),
            "W11_conclusions_last": sum(r["W11_format"]["conclusions_last"] for r in rows if "W11_format" in r),
            "W11_answers_with_zone_ids_in_prose": sum(r["W11_format"]["zone_ids_in_prose"] > 0 for r in rows if "W11_format" in r),
            "W13_verdict_clauses": sum(r.get("W13_verdict_clauses") or 0 for r in rows),
            "W15_answers_contradicting_left": sum(bool(r.get("W15_contradictions_left")) for r in rows),
            "repair_rounds_mean": sum(r.get("repair_rounds") or 0 for r in rows) / n,
            "median_words": sorted(r["words"] for r in rows)[n // 2]}


def main():
    from petroharness.config import HarnessConfig
    from petroharness.tasks import load_tasks
    from petroharness.llm import LLM, Usage
    from petroharness.models import MODELS
    from petroharness.agent import writer
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("out")
    ap.add_argument("--variant", default="")
    ap.add_argument("--format", default="profile", choices=["profile", "default"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--baseline", action="store_true", help="measure the traced answers, run no writer")
    args = ap.parse_args()
    cfg = HarnessConfig()
    tasks, index = load_tasks(cfg.eval.questions, cfg.data.las_dir)
    by_id = {t.task_id: t for t in tasks}
    traces = sorted((ROOT / "runs").glob(f"{args.prefix}_*/traces/*.json"))
    if args.limit:
        traces = traces[:args.limit]
    from petroharness.models import env_urls
    urls = env_urls()                                       # PETROHARNESS_MODEL_URL (or K2H_TOOL_URLS)
    cfg_file, _ = MODELS["k200t"]

    def one(k_path):
        k, path = k_path
        tr = json.loads(path.read_text())
        task = by_id[tr["task_id"]]
        mc = HarnessConfig.load(ROOT / cfg_file)
        mc.model.base_url = urls[k % len(urls)] if urls else mc.model.base_url
        tcfg = mc.for_tasks()
        s, rep = rebuild(tr, task, tcfg)
        if args.baseline:
            ans, wtrace = tr.get("answer", ""), tr
        else:
            wtrace = {"absent": tr.get("absent")}
            from petroharness.agent.loop import settle                  # options.settle: the final step on the rebuilt session
            settle(LLM(tcfg), s, Usage(), tcfg.model.max_tokens_spec, wtrace)
            ans, _ = writer.write(LLM(tcfg), s, tcfg, Usage(), wtrace, variant=args.variant, fmt=args.format)
            wtrace["absent"] = tr.get("absent")
        return {"task_id": tr["task_id"], "topics": tr.get("topics"), "rebuild": rep, "answer": ans,
                "metrics": metrics(s, ans, wtrace), "verify_rounds": wtrace.get("verify_rounds"),
                "settle": wtrace.get("settle")}

    with ThreadPoolExecutor(min(64, len(traces))) as ex:
        rows = list(ex.map(one, enumerate(traces)))
    Path(args.out).write_text(json.dumps(rows, indent=1, default=str))
    exact = sum(r["rebuild"]["opened_equal"] and r["rebuild"]["flags_equal"] for r in rows)
    print(f"{args.prefix} variant={args.variant or '(current)'} baseline={args.baseline}: rebuilt exactly {exact} of {len(rows)}")
    print(json.dumps(summarize([r["metrics"] for r in rows]), indent=1))


if __name__ == "__main__":
    main()
