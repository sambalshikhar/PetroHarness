"""A conversation as one document: the well and the interval, what answered, the interval's log display, each question
with its answer (its figures, its methods and parameters), then each answer's audit trail. Assembled from the session
folder alone: the log, the answer files, the evidence graph.

    petroharness report SESSION [--out FILE]        (default: SESSION/report.md, so its pictures resolve)

    markdown(folder) -> the document
    main(argv)       -> the command
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from petroharness.evidence import audit
from petroharness.evidence.graph import EvidenceGraph


def _events(folder: Path) -> list:
    return [json.loads(line) for line in (folder / "log.jsonl").read_text().splitlines() if line.strip()]


def _interval(used) -> str:
    if not isinstance(used, dict):
        return ""
    span = f"{used.get('top')}-{used.get('base')} {used.get('unit') or ''}".strip()
    return f"{used.get('name') or 'the interval'} ({span}; {used.get('samples')} samples)"


def _answer(folder: Path, n: int) -> str:
    """Question n's answer file without its own header, its pictures addressed from the session folder."""
    path = folder / "turns" / f"{n:02d}" / "answer.md"
    if not path.is_file():
        return "(no answer file)"
    text = path.read_text()
    if "\n---\n" in text:
        text = text.split("\n---\n", 1)[1]
    text = re.sub(r"\]\((figures/[^)]+)\)", lambda m: f"](turns/{n:02d}/{m.group(1)})", text)
    # the answer's own headings sit under the question's heading (two levels down, six at most)
    return re.sub(r"^(#{1,6}) ", lambda m: "#" * min(len(m.group(1)) + 2, 6) + " ", text, flags=re.MULTILINE).strip()


def markdown(folder) -> str:
    folder = Path(folder)
    events = _events(folder)
    start = next((e for e in events if e["type"] == "session_start"), {})
    setup = next((e for e in reversed(events) if e["type"] == "setup"), {})
    questions = {e["turn"]: e.get("text") for e in events if e["type"] == "question"}
    ended = {e["turn"]: e for e in events if e["type"] == "turn_end"}
    las = Path(start["las"]).name if start.get("las") else "prepared tasks"
    out = [f"# Conversation report: {las}", ""]
    if start.get("interval"):
        out.append(f"- **Interval:** {_interval(start['interval'])}")
    if start.get("las"):
        out.append(f"- **LAS file:** `{start['las']}`, SHA-256 `{start.get('las_sha256')}`")
    out += [f"- **Model:** {start.get('model')}", f"- **Petrophys:** {start.get('petrophys')}",
            f"- **PetroHarness:** {setup.get('harness') or ''} commit {start.get('harness') or setup.get('commit') or '-'}"
            + (f", setup `{setup['hash']}`" if setup.get("hash") else ""),
            f"- **Questions:** {len(ended)} answered of {len(questions)} asked", ""]
    if (folder / "overview.png").is_file():
        out += ["![The interval as Petrophys displays it](overview.png)", "",
                "*The interval as Petrophys displays it (its log viewer; the zones as the lithology track).*", ""]
    for n in sorted(questions):
        status = ended.get(n, {}).get("status", "not answered")
        out += ["---", "", f"## Question {n}: {questions[n]}", "", f"*Status: {status}.*", "", _answer(folder, n), ""]
    g = EvidenceGraph.from_log(folder)
    answered = [n for n in g.questions() if f"A{n}" in g.nodes]
    if answered:
        out += ["---", "", "# Audit trails", "",
                "For each answer: what it states, the results that show it, the curves and Petrophys steps behind "
                "them, and the source file.", ""]
        for n in answered:
            out += [re.sub(r"^(#{1,5}) ", lambda m: "#" + m.group(1) + " ", audit.markdown(g, n), flags=re.MULTILINE), ""]
    return "\n".join(out).rstrip() + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="petroharness report", description=(
        "Write a conversation as one document: the interval, each question with its answer, figures, methods and "
        "parameters, and each answer's audit trail. Read from the session folder alone."))
    ap.add_argument("session", help="the session folder (petroharness chat --session DIR)")
    ap.add_argument("--out", help="the file to write (default: report.md in the session folder, where its pictures resolve)")
    args = ap.parse_args(argv)
    folder = Path(args.session)
    if not (folder / "log.jsonl").is_file():
        print(f"petroharness report: WHAT: {folder} holds no session log (log.jsonl). FIX: give a session folder.",
              file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else folder / "report.md"
    out.write_text(markdown(folder))
    print(out)
    return 0
