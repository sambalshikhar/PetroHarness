"""The settle step: the model settles its claims against the results before the writer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petroharness.agent.prompts import _reach, brief
from petroharness.agent.replies import parse

if TYPE_CHECKING:
    from petroharness.agent.state import Session

import re
from petroharness.llm import LLM, Usage
from petroharness.agent import vocabulary
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)


SETTLE = C.text("C5", "settle")


MAX_GUIDE_STATS = 2          # workflow-curve stats a guide opens with it (direction.Library.workflow_stats)


# the settle step is where claims become final; the readings rules are restated there, with the one rule for bases
# and conventions (C9 aspects_rule: the settle step's only; the writer is not given it)
SETTLE_WEAKNESSES = C.text("C10", "settle_weaknesses")


ASPECTS_RULE = C.text("C9", "aspects_rule")


BOOK_ITEMS = 12            # results named in the unused list at most (the rest counted)


def _n(eid: str) -> int:
    return int(eid[1:]) if re.fullmatch(r"E\d+", str(eid)) else 0


def written_before(claims: list, items: dict) -> list:
    """The graded claims whose text was written before results their point's claims now cite were opened (a fact of
    order, not of content: the model reads whether each text still holds against them), each with those results."""
    out = []
    for c in claims:
        if c.grade == "hypothesis":
            continue
        later = sorted({e for x in claims if x.point == c.point for e in x.ev if e in items and _n(e) > c.text_at}, key=_n)
        if later:
            out.append(f"{c.id} (point {c.point}; its text came before {', '.join(later)})")
    return out


def bookkeeping(s) -> str:
    """The settle step's lists (C5 'settle_lists'), for the model to act on as it sees fit; nothing waits
    on them: the measurements the READ call named (with data here) that no claim names or reaches through a result it
    cites; the opened results (not calculations) no claim cites; the claims still graded hypothesis; the claims whose
    text came before results their point's claims cite (written_before). Empty when all four are."""
    from petroharness.agent.claims import _item_names
    if s.claims is None:
        return ""
    reg, known = s.f.view.reg.curves, list(s.f.inv.curves)
    claims = list(s.claims.claims.values())
    items = {e.id: e for e in s.ledger.items}
    cited = {x for c in claims for x in c.ev}
    said = " ".join(f"{c.text} {c.means} {c.weak}" for c in claims)
    in_claims = {x.upper() for _, curves in vocabulary.in_text(said, reg, known) for x in curves}
    in_claims |= {x.upper() for x in vocabulary.written(said, known)}
    reached = {n for e in cited if e in items for n in _item_names(items[e])}
    named = []
    for n in (getattr(s, "reading", None) or {}).get("named") or []:
        curves = [c for c in vocabulary.resolve(n, reg, known) if c in s.f.inv.curves and s.f.view.available(c)]
        if not curves or {c.upper() for c in curves} & (in_claims | reached) or str(n).strip().lower() in said.lower():
            continue
        named.append(f"{str(n).strip()[:vocabulary.NAME_CHARS]} ({', '.join(curves)})")
    unused = [f"{e.id} {e.call_text()}" for e in s.read_items() if e.id not in cited and e.tool != "calc"]
    if len(unused) > BOOK_ITEMS:
        unused = unused[:BOOK_ITEMS] + [f"and {len(unused) - BOOK_ITEMS} more"]
    hyp = [c.id for c in claims if c.grade == "hypothesis"]
    stale = written_before(claims, items)
    if len(stale) > BOOK_ITEMS:
        stale = stale[:BOOK_ITEMS] + [f"and {len(stale) - BOOK_ITEMS} more"]
    texts = C.text("C5", "settle_lists")
    lines = [C.fill_text(texts[k], items=sep.join(v)) for k, v, sep in
             (("named", named, "; "), ("unused", unused, "; "), ("hypotheses", hyp, ", "), ("written_before", stale, "; "))
             if v]
    return (texts["head"] + "\n" + "\n".join(lines) + "\n\n") if lines else ""


def settle(llm: LLM, s: Session, usage: Usage, max_tokens: int, trace: dict) -> None:
    """The final step: no lookups; the model sees its claims and every opened result and makes the answer final. The
    claim checks apply as in the steps; the trace keeps the reply, the edits and what changed."""
    if s.claims is None or not s.ledger.items:
        return
    from petroharness.agent.writer import opened_results
    absent = vocabulary.note(s)
    pts = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(s.points))
    book = bookkeeping(s)                         # lists for the model, never a check
    user = (f"QUESTION:\n{s.task.question}\n" + (f"{absent}\n" if absent else "")
            + (f"\n{s.earlier}\n" if s.earlier else "")
            + f"\nTHE MAP\n{s.map}\n\nYOUR POINTS:\n{pts}\n\nYOUR ANSWER:\n{s.claims.render()}\n\n"
            f"ALL RESULTS:\n{opened_results(s, items=s.read_items())}\n\n" + book
            + f"{SETTLE}" + SETTLE_WEAKNESSES + "\n- " + ASPECTS_RULE)
    rec = {"claims_before": len(s.claims.claims), "issues_before": s.claims.done_issues(), "bookkeeping": book}
    text = llm.chat("settle", [{"role": "system", "content": brief(s.library, _reach(s))}, {"role": "user", "content": user}],
                    usage, max_tokens)
    rec["reply"] = (text or "")[:6000]
    rec["prompt_chars"] = len(user)
    obj = parse(llm, 0, text, usage, max_tokens, rec, stage="settle")
    if obj is None:
        rec["error"] = "unreadable reply"
    else:
        edits = obj.get("edits") if isinstance(obj.get("edits"), list) else []
        rec["edits"], rec["edit_msgs"] = edits, s.claims.apply(edits)
        s.claims.refresh()
    rec["claims_after"], rec["issues_after"] = len(s.claims.claims), s.claims.done_issues()
    trace["settle"] = rec
    trace["claims"] = [c.__dict__ for c in s.claims.claims.values()]
    trace["dropped"] = [c.__dict__ for c in s.claims.dropped]
    trace["done_issues"] = s.claims.done_issues()
