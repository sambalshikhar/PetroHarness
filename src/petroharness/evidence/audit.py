"""The audit trail of an answer: from what it states, back through the results, the curves and the steps to the LAS
file. Written from the evidence graph (petroharness.evidence.graph), so it needs only the session folder.

    petroharness audit SESSION [--question N] [--json] [--out FILE]

    markdown(graph, n) -> the trail of answer n as a document
    main(argv)         -> the command
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from petroharness.evidence.graph import EvidenceGraph


def _value(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def _call(r: dict) -> str:
    args = ", ".join(f"{k}={json.dumps(v)}" for k, v in (r.get("args") or {}).items())
    return f"{r.get('tool')}({args})"


def markdown(g: EvidenceGraph, n: int) -> str:
    """The trail of answer n: the claims with the results they cite, the numbers with the results that show them,
    each result with its call and the curves it read, the steps behind those curves with their parameters, the
    measured logs they start from, and the file."""
    t = g.trail(n)
    q, a = t["question"], t["answer"]
    out = [f"# Audit trail: question {n}", "", f"**Question:** {q['text']}", "",
           f"**Answer:** status {a['status']}; text SHA-256 `{a['sha256']}`"]
    if a.get("opening"):
        out += ["", f"> {a['opening']}"]
    out += ["", "## Claims and the results they cite", ""]
    if t["claims"]:
        out += [f"{i}. {c['text']} ({c['grade']}): {', '.join(c['results']) or 'no result cited'}"
                for i, c in enumerate(t["claims"], 1)]
    else:
        out.append("No settled claim.")
    out += ["", "## Numbers the answer states and the results that show them", ""]
    if t["numbers"]:
        out += ["| Number | Shown by |", "|---|---|"] + [f"| {k} | {', '.join(v)} |" for k, v in t["numbers"].items()]
    else:
        out.append("No number of the answer was matched to a single result.")
    out += ["", "## Results", "", "| Result | Asked in | Call | Curves it read | Text SHA-256 |", "|---|---|---|---|---|"]
    out += [f"| {r['id']} | question {r['question']} | `{_call(r)}` | {', '.join(r['curves']) or '-'} | "
            f"`{str(r['sha256'])[:16]}` |" for r in t["results"]]
    out += ["", "## Curves", "", "| Curve | Unit | Where it comes from |", "|---|---|---|"]
    for c in t["curves"]:
        origin = f"computed by step `{c['step']}`" if c["step"] else ("measured (the LAS file)" if c["source"] == "input"
                                                                      else str(c["source"] or "unknown"))
        out.append(f"| {c['name']} | {c['unit'] or '-'} | {origin} |")
    out += ["", "## Steps Petrophys ran", ""]
    for s in t["steps"]:
        params = "; ".join(f"{k} = {_value(v)}" for k, v in s["parameters"].items()) or "none recorded"
        out.append(f"- **{s['step']}**: {s['method'] or 'method not recorded'}. Read {', '.join(s['reads']) or 'nothing recorded'}. "
                   f"Parameters: {params}.")
    if not t["steps"]:
        out.append("No computed curve is behind this answer.")
    if t["figures"]:
        out += ["", "## Figures", ""] + [f"- {f['file']}: {f['caption']}" for f in t["figures"]]
    out += ["", "## Source", ""]
    las, ses = t.get("las") or {}, t.get("session") or {}
    if las:
        out.append(f"- LAS file: `{las.get('path')}`, SHA-256 `{las.get('sha256')}`")
    for key, label in (("petrophys", "Petrophys"), ("harness", "PetroHarness commit"), ("model", "Model"),
                       ("setup", "Setup (petroharness setup; the session log's setup event holds its parts)")):
        if ses.get(key):
            out.append(f"- {label}: {ses[key] if not isinstance(ses[key], dict) else json.dumps(ses[key])}")
    out += ["", "Every result's text is kept in the session folder under its SHA-256 (`blobs/`)."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="petroharness audit", description=(
        "The audit trail of a conversation's answers: what each answer states, the results that show it, the curves "
        "and Petrophys steps behind them, back to the LAS file. Read from the session folder alone."))
    ap.add_argument("session", help="the session folder (petroharness chat --session DIR)")
    ap.add_argument("--question", type=int, help="one question's number (default: every answered question)")
    ap.add_argument("--json", action="store_true", help="the evidence graph (or one question's trail) as JSON")
    ap.add_argument("--out", help="write to this file instead of standard output")
    args = ap.parse_args(argv)
    folder = Path(args.session)
    if not (folder / "log.jsonl").is_file():
        print(f"petroharness audit: WHAT: {folder} holds no session log (log.jsonl). FIX: give a session folder.",
              file=sys.stderr)
        return 2
    g = EvidenceGraph.from_log(folder)
    answered = [n for n in g.questions() if f"A{n}" in g.nodes]
    try:
        wanted = [args.question] if args.question is not None else answered
        if args.json:
            text = json.dumps(g.trail(args.question) if args.question is not None else g.to_json(), indent=1)
        else:
            text = "\n".join(markdown(g, n) for n in wanted)
    except KeyError as exc:
        print(f"petroharness audit: {exc.args[0]}", file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)
    return 0
