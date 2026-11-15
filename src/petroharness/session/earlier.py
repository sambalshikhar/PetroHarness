"""EARLIER IN THIS SESSION: the earlier questions of a conversation as a later question's prompts show them. Built by
code from each question's record (its text, the opening of its answer, its settled claims with the results they
cite, or for a short answer the results it was read from), never written by a model, so a replayed conversation
builds the same prompts. The results themselves stay in the ledger: the block names their ids."""
from __future__ import annotations

import re

from petroharness.agent import components as C

EARLIER_CHARS = 6000       # the block at most; the newest questions whole, older ones short, the oldest counted
OPENING_CHARS = 600        # an answer's opening as shown
QUESTION_CHARS = 300
CLAIM_CHARS = 240


def _line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def opening(answer: str, limit: int = OPENING_CHARS) -> str:
    """The answer's first paragraph of prose (headings, tables and rules skipped), cut at a sentence end."""
    for para in re.split(r"\n\s*\n", str(answer or "")):
        lines = [ln for ln in para.splitlines() if ln.strip() and not re.match(r"\s*(#|\||-{3,}|\*{3,}|_{3,})", ln)]
        text = _line(" ".join(lines)).strip("*_ ")
        if len(text) < 40:                             # a title line or a label
            continue
        if len(text) <= limit:
            return text
        cut = text[:limit]
        end = max(cut.rfind(". "), cut.rfind("; "))
        return (cut[:end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0]) + " ..."
    return ""


def entry(rec: dict, full: bool = True) -> str:
    """One earlier question: its text, how its answer opened and (full) what was found, with the result ids."""
    lines = [f"Question {rec['turn']}: {_line(rec['question'])[:QUESTION_CHARS]}"]
    if str(rec.get("status", "")).startswith("error"):
        lines.append("  (not answered: the run failed)")
        return "\n".join(lines)
    if rec.get("opening"):
        lines.append(f"  Answered: {rec['opening']}")
    if full:
        for c in rec.get("claims") or []:
            ids = ", ".join(c.get("ev") or [])
            lines.append(f"  - {_line(c['text'])[:CLAIM_CHARS]} ({c.get('grade', '')}{'; ' + ids if ids else ''})")
        if not rec.get("claims") and rec.get("read_from"):     # a short answer: the results it was read from
            lines.append(f"  (read from {', '.join(rec['read_from'])})")
    return "\n".join(lines)


def block(turns: list, budget: int = EARLIER_CHARS) -> str:
    """The block for the next question ("" before any question): the newest questions with their findings while the
    budget lasts, older ones by question and opening, the oldest as a count."""
    if not turns:
        return ""
    head = C.text("C3", "earlier_head")
    used, kept = len(head), {}
    for rec in reversed(turns):                        # the newest first: whole, then short
        for full in (True, False):
            text = entry(rec, full)
            if used + len(text) + 1 <= budget:
                kept[rec["turn"]], used = text, used + len(text) + 1
                break
        else:
            break
    out = [head]
    left = [r["turn"] for r in turns if r["turn"] not in kept]
    if left:
        out.append(f"Questions {left[0]} to {left[-1]}: {len(left)} earlier questions not shown here (find reads their "
                   "results)")
    out += [kept[r["turn"]] for r in turns if r["turn"] in kept]
    return "\n".join(out)
