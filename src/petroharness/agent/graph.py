"""The question graph: the READ call, the investigation, the settle step and the writer with its checker as a
LangGraph state graph (docs/GRAPH.md); answer() runs one question."""
from __future__ import annotations

import hashlib
import json
import operator
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from petroharness.llm import LLM, Usage, assistant_turn

from petroharness.agent import components as C
from petroharness.agent import direction, options, vocabulary
from petroharness.agent.claims import Claims, coerce_edit
from petroharness.agent.inventory import calibrated_twins
from petroharness.agent import loop as L                    # the loop's tunables and prompt texts, read where used (tests set them)
from petroharness.agent.loop import (MAX_STEPS, Session, action_text, brief, coerce_action, parse, read_question,
                                     read_reply, settle, topics_text)

HARNESS = "petroharness 3.5"


def no_hosted_tracing() -> None:
    """The data stays on the cluster: LangSmith (installed with langgraph) turns tracing on from the environment and
    would send every prompt, well data included, to its service. Refuse to run instead."""
    import os
    on = [k for k in ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2")
          if os.environ.get(k, "").strip().lower() in ("true", "1")]
    if on:
        raise RuntimeError(f"WHAT: hosted tracing is switched on ({', '.join(on)}). WHY: LangSmith would send every "
                           f"prompt, with the well data, off the cluster. FIX: unset {on[0]} or set it to false.")


no_hosted_tracing()
RECURSION_LIMIT = 200          # supersteps: 8 steps x 4 nodes + the writer's rounds stay far below this


@dataclass
class Run:
    """The run context of one question: built once, private to the nodes (never part of a state update)."""
    task: Any
    cfg: Any                     # the task's HarnessConfig (cfg.for_tasks())
    llm: LLM
    usage: Usage
    trace: dict
    writer: str = ""
    fmt: str = "profile"
    max_tokens: int = 0          # a step's and the settle step's output cap (cfg.model.max_tokens_spec)
    max_tokens_writer: int = 0   # the writer's and a repair's output cap (cfg.model.max_tokens_writer)
    session: Optional[Session] = None
    depth: bool = False          # the READ call is asked whether the question is direct (docs/GRAPH.md, The direct route)
    system: str = ""             # the brief (step and settle system prompt)
    head: str = ""               # QUESTION, the note of what it names that the record lacks, THE MAP, DIRECTION (a library's)
    first_look: str = ""
    w_messages: list = field(default_factory=list)   # the writer's system and user messages
    w_table: str = ""


class State(TypedDict, total=False):
    k: int                       # the step being taken
    max_steps: int
    new: str                     # NEW: what the last actions returned
    shown_new: list              # ids NEW shows whole (left out of OPENED's digests)
    withheld: list               # ids opened and not shown for NEW's budget: first in the next step's NEW
    guides_new: list             # guides the last step read: in full in GUIDES (the others short)
    refused: bool                # done refused once by the claims' done rule
    polish: int                  # steps in a row that only rephrased a settled answer
    text: str                    # this step's reply as recorded
    user: str                    # this step's user prompt
    reply: Optional[dict]        # this step's step object (None: unreadable)
    call_errors: list
    rec: dict                    # this step's record
    steps: Annotated[list, operator.add]
    acts: list                   # the actions this step runs
    notes: list
    msgs: list                   # edit messages
    raw_edits: list
    settled_before: bool
    finished: bool               # the investigation ended at decide
    draft: str
    rounds: Annotated[list, operator.add]
    answer: str
    status: str


# --- the investigation ---------------------------------------------------------------------------------------------

def build(state: State, runtime: Runtime[Run]) -> dict:
    r = runtime.context
    r.session = Session.build(r.task, r.cfg)
    r.session.reads_depth = r.depth
    r.trace["map_chars"] = len(r.session.map)
    return {}


def read_step(state: State, runtime: Runtime[Run]) -> dict:
    """The READ call: the model reads the question and chooses its topics (loop.read_question); the map's notes
    follow its topics."""
    r = runtime.context
    read_question(r.llm, r.session, r.usage, r.max_tokens, r.trace)
    r.trace["map_chars"] = len(r.session.map)
    return {}


def first_look(state: State, runtime: Runtime[Run]) -> dict:
    """The brief, the prompt head (with the note of what the question names that this well's record lacks, and the
    DIRECTION index when a skill library is plugged) and the first look (the key curves of the topics the model chose
    and the curves its reading names, each with its core-calibrated twin where the record holds one: each zone, the
    zones pooled and the whole interval, with the default statistics), before step 1."""
    r = runtime.context
    s, trace = r.session, r.trace
    r.system = brief(s.library)
    absent = vocabulary.note(s)
    trace["absent"] = [{"name": n, "curves": c} for n, c in vocabulary.absent(s)]
    from petroharness.agent.writer import conventions_block
    conv = conventions_block(s)
    r.head = (f"QUESTION:\n{s.task.question}\n" + (f"{absent}\n" if absent else "")
              + (f"\n{s.earlier}\n" if s.earlier else "") + (f"\n{conv}\n" if conv else "")
              + f"\nTHE MAP\n{s.map}\n\n"
              + (f"DIRECTION\n{s.library.index(s.topics)}\n\n" if s.library is not None else ""))
    look = ""
    curves = [c for c in direction.overview(s.topics) if c in s.f.inv.curves][:8]
    # the measurements the model's reading names (catalog vocabulary)
    curves += [c for c in L.named_curves(s.f, s.reading.get("named")) if c not in curves]
    curves = curves[:12]
    # the formation's reservoir context for any question
    want = list(dict.fromkeys(c for c in (L.MINERAL_VOLUMES if L.MINERAL_TOPIC in s.topics else ()) + L.CORE_CURVES
                              if c in s.f.inv.curves))
    rest = [c for c in curves if c not in want][:max(L.CORE_LOOK_CAP - len(want), 8)]
    curves = [c for c in curves if c in rest or c in want] + [c for c in want if c not in curves]
    # each curve's core-calibrated twin beside it, where the record holds one (the inventory's ranking: X and X_CC)
    twins = calibrated_twins(s.f.inv)
    curves = list(dict.fromkeys(x for c in curves for x in ([c, twins[c]] if c in twins else [c])))
    if curves:                                                     # the default statistics (the summary layer)
        act = ("tool", "stats", {"curves": curves})
        out, item = s.run(act)
        trace["overview"] = action_text(act)
        if item is not None:
            chose = f" for the topics you chose: {', '.join(s.topics)};" if s.topics else ","
            look = f"FIRST LOOK (each zone's key curves{chose} opened for you):\n{out}\n\n"
    r.first_look = look
    return {"k": 1, "new": "", "shown_new": [], "withheld": [], "guides_new": [], "refused": False, "polish": 0}


def ask(state: State, runtime: Runtime[Run]) -> dict:
    """Step k: the prompt rebuilt from the state, one call (a retry after an empty reply), the reply read."""
    r = runtime.context
    s, llm, usage, k = r.session, r.llm, r.usage, state["k"]
    max_tokens, last = r.max_tokens, state["k"] == state["max_steps"]
    if k == 1:
        user = r.head + topics_text(s) + r.first_look + L.step1(s.library) + L.POINTS_SCOPE
        if s.turn > 1:                                  # a later question of a conversation: what is already opened
            user += C.text("C5", "step1_later")
            if not s.reads_depth:                       # its answer's length: said here, unless READ reads the depth
                user += C.text("C5", "step1_reply")
    else:
        pts = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(s.points))
        done_ = "set done to true"
        ask_ = C.fill("C5", "step_last", done=done_) if last else C.text("C5", "step_next")
        if not last and not s.claims.done_issues():
            ask_ += C.text("C5", "step_settled_check")
        user = (r.head + f"YOUR POINTS:\n{pts}\n\nYOUR ANSWER (after step {k - 1} of {state['max_steps']}):\n"
                f"{s.claims.render()}\n\nOPENED (fetch exact lines with get or find):\n{s.opened(set(state['shown_new']))}"
                f"\n\n{s.guides_text(state['guides_new'])}NEW (from step {k - 1}):\n{state['new']}\n\n{ask_}")
    rec = {"step": k}
    call_errors = []
    system = r.system
    text = llm.chat(f"step_{k}", [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    usage, max_tokens)
    if not (text or "").strip():
        text = llm.chat(f"step_{k}_retry", [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        usage, max_tokens, retry=True)
    obj = parse(llm, k, text, usage, max_tokens, rec)
    rec["prompt_chars"] = len(system) + len(user)
    rec["prompt_tokens"] = usage.log[-1].get("prompt_tokens") if usage.log else None
    rec["reply"] = (text or "")[:6000]
    return {"rec": rec, "reply": obj, "text": text, "user": user, "call_errors": call_errors, "shown_new": [],
            "guides_new": []}


def _light(llm, on: bool) -> None:
    """The client's calls from here on: the card's light thinking setting, or its normal one (a stand-in model has
    neither)."""
    switch = getattr(llm, "set_light", None)
    if callable(switch):
        switch(on)


_SHOWN = re.compile(r"^\[(E\d+)\] (?!nothing in )", re.M)


def _seen(s, text: str, item=None) -> None:
    """What a look step is shown, the short answer's writer reads: the result a lookup opened (or the one the same
    call opened before), and the results get or find read lines of. On a later question of a conversation these may
    be an earlier question's results, and a short answer has no claims to cite them by (Session.fetched)."""
    for eid in ([item.id] if item is not None else []) + _SHOWN.findall(text or ""):
        if eid not in s.fetched and s.ledger.by_id(eid) is not None:
            s.fetched.append(eid)


def _reply_proper(llm, text: str) -> str:
    """A reply without the reasoning a server left before it (the card's reasoning_end; llm.chat takes it off a
    light call's reply, not off a retry's)."""
    end = getattr(getattr(getattr(llm, "cfg", None), "model", None), "reasoning_end", None)
    text = text or ""
    return text.rsplit(end, 1)[1].lstrip() if isinstance(end, str) and end and end in text else text


def look(state: State, runtime: Runtime[Run]) -> dict:
    """A direct question's step (the READ call read the question as direct): one call that either says the opened
    results state what is asked, or names what to open; its lookups run into the ledger. No points and no claims: the
    writer reads the results. The step thinks as every call does: with thinking reduced, the direct answers of both
    measured models lost about 7 points of reference alignment (the step stopped at a result near what was asked, or
    chose a weaker lookup) and saved no measurable time. The reply may send the question to an investigation after
    all, and so does a reply that cannot be read, or one whose lookups cannot be read."""
    r = runtime.context
    s, llm, usage, k = r.session, r.llm, r.usage, state["k"]
    if k == 1:
        s.points, s.intent = [s.task.question.strip()[:240]], "value"
        s.claims = Claims(s.points, s.ledger, s.map, s.task.question, s.f.view, (s.task.well,))
        s.claims.families = tuple(s.families)
        user = r.head + topics_text(s) + r.first_look + C.text("C5", "direct_step")
        _seen(s, r.first_look)
    else:
        user = (r.head + f"OPENED (fetch exact lines with get or find):\n{s.opened(set(state['shown_new']))}"
                f"\n\nNEW (from step {k - 1}):\n{state['new']}\n\n" + C.text("C5", "direct_step"))
    rec = {"step": k, "direct": True}
    messages = [{"role": "system", "content": r.system}, {"role": "user", "content": user}]
    text = llm.chat(f"step_{k}", messages, usage, r.max_tokens)
    if not (text or "").strip():
        text = llm.chat(f"step_{k}_retry", messages, usage, r.max_tokens, retry=True)
    text = _reply_proper(llm, text)
    back = re.search(r'"depth"\s*:\s*"investigate"', text) is not None      # its way back, read before the step parser
    obj = {"depth": "investigate"} if back else parse(llm, k, text, usage, r.max_tokens, rec)
    rec.update(prompt_chars=len(r.system) + len(user), reply=text[:6000],
               prompt_tokens=usage.log[-1].get("prompt_tokens") if usage.log else None)
    read = [] if obj is None or back else [(a, coerce_action(a, s.library is not None)) for a in (obj.get("next") or [])]
    wanted = [c for _, c in read if c]
    why = ("unreadable reply" if obj is None else "the model asked for it" if back else
           "its lookups could not be read" if read and not wanted and not obj.get("done") else "")
    if why:
        s.depth, s.claims, s.points, s.fetched = "investigate", None, [], []    # the investigation starts from its own step 1
        rec["to_investigation"] = why
        if read:
            rec["unread"] = [json.dumps(a, default=str)[:200] for a, _ in read]
        r.trace["depth"] = {"read": "direct", "investigated_from_step": k, "why": why}
        return {"steps": [rec], "k": 1, "new": "", "shown_new": [], "withheld": [], "guides_new": [],
                "refused": False, "polish": 0, "finished": False}
    acts = [] if obj.get("done") else wanted[:L.DIRECT_ACTIONS]
    if len(wanted) > len(acts) and not obj.get("done"):
        rec["over_cap"] = len(wanted) - len(acts)       # lookups asked beyond the step's cap: not run
    parts, shown, used = [], [], 0
    for a in acts:
        out, item = s.run(a)
        _seen(s, out, item)                             # the writer reads what this step is shown
        if item is not None and used + len(out) > L.new_chars():
            out = f"[{item.id}] {item.call_text()} (opened; the answer's writer reads it whole)"
        elif item is not None:
            shown.append(item.id)
        parts.append(out)
        used += len(out)
    rec.update(actions=[action_text(a) for a in acts], done=bool(obj.get("done")),
               unread=[json.dumps(a, default=str)[:200] for a, c in read if not c])
    finished = bool(obj.get("done")) or not acts or k >= L.DIRECT_STEPS
    return {"steps": [rec], "new": "\n\n".join(parts) or C.text("C8", "nothing_new"), "shown_new": shown,
            "k": k + 1, "finished": finished}


def skip(state: State, runtime: Runtime[Run]) -> dict:
    """An unreadable reply: the step is recorded; the next step's NEW says so."""
    rec = {**state["rec"], "error": "unreadable reply"}
    new = C.text("C2", "skip")
    return {"steps": [rec], "rec": rec, "new": new, "k": state["k"] + 1}


def plan(state: State, runtime: Runtime[Run]) -> dict:
    """Step 1: what the question asks (point 1), the points, the intent, and the claims they open. The points are the
    model's: code adds, drops and rewrites none (only the numbering, the length cap and a point equal to point 1)."""
    r = runtime.context
    s, llm, usage = r.session, r.llm, r.usage
    obj, rec, text, user = dict(state["reply"]), dict(state["rec"]), state["text"], state["user"]
    refs = [e.get("point") for e in (obj.get("edits") or []) if isinstance(e, dict)]
    n = max([int(x) for x in refs if isinstance(x, (int, float)) and not isinstance(x, bool) and 0 < x <= 6] or [1])
    if not obj.get("points") and n > 1:                                # ask once for the points it numbers
        again = llm.chat("step_1_points", [{"role": "system", "content": r.system},
                                           {"role": "user", "content": user},
                                           assistant_turn(text, usage, llm.replays_reasoning()),
                                           {"role": "user", "content": L.POINTS.format(n=n)}], usage, r.max_tokens)
        try:
            got = read_reply(again) if '"points"' in again else {}
        except ValueError:
            got = {}
        if not got:
            m = re.search(r'"points"\s*:\s*\[(.*?)\]', again or "", re.S)
            got = {"points": re.findall(r'"((?:[^"\\]|\\.){8,})"', m.group(1))} if m else {}
        obj["points"], obj["intent"] = got.get("points"), obj.get("intent") or got.get("intent")
        rec["points_asked"] = bool(obj["points"])
    asks = obj.get("asks")
    asks = str(asks.get("text", asks) if isinstance(asks, dict) else asks or "").strip()
    listed = [re.sub(r"^\s*(?:\d+[.)]\s*)+", "", str(p.get("text", p) if isinstance(p, dict) else p)).strip()[:240]
              for p in obj.get("points") or [] if str(p).strip()]
    if asks:                                   # what the question asks is point 1; the points follow it
        listed = [asks[:240]] + [p for p in listed if p.lower() != asks.lower()]
    s.points = listed[:6] or [s.task.question[:240]]
    rec["asks"] = asks
    it = str(obj.get("intent", "")).strip().lower()
    s.intent = it if it in ("value", "locate", "characterize", "compare", "explain", "qc_check") else "characterize"
    if s.turn > 1:                              # a later question: the answer's length is the model's choice (C5 step1_later)
        s.reply = "brief" if str(obj.get("reply", "")).strip().lower() == "brief" else "full"
        r.trace.setdefault("session", {})["reply"] = s.reply
    s.claims = Claims(s.points, s.ledger, s.map, s.task.question, s.f.view, (s.task.well,))
    s.claims.families = tuple(s.families)
    return {"reply": obj, "rec": rec}


def decide(state: State, runtime: Runtime[Run]) -> dict:
    """The edits applied, the actions read (guides open their sections; with no skill library a guide call is no action,
    said back as not run), and the done check: the claims' rule, not the model's say-so, ends the investigation."""
    r = runtime.context
    s, k, obj, rec = r.session, state["k"], state["reply"], dict(state["rec"])
    last, refused = k == state["max_steps"], state["refused"]
    raw_edits = obj.get("edits") if isinstance(obj.get("edits"), list) else []
    settled_before = k > 1 and not s.claims.done_issues()
    msgs = s.claims.apply(raw_edits) + state["call_errors"]
    read = [(a, coerce_action(a, s.library is not None)) for a in (obj.get("next") or [])]
    acts = [c for _, c in read if c]
    unread = [a for a, c in read if not c]                          # said back, not dropped silently
    guides = [a for a in acts if a[0] == "guide"][:L.MAX_GUIDES]      # reading direction does not use an action slot
    calcs = [a for a in acts if a[0] == "calc"][:L.MAX_CALCS]         # nor does arithmetic on shown numbers
    work = [a for a in acts if a[0] not in ("guide", "calc")]
    cap = L.ACTIONS
    dropped = max(0, len(work) - cap)
    # a guide read the first time opens what it names that bears on the READ's first topic (the primary one): its
    # workflow sections of that topic's families, and, for a guide on that topic, the workflow's own curves it names;
    # the rest stays listed in its Compare lines. No topics: nothing is opened with a guide.
    primary = s.topics[0] if s.topics else None
    families = direction.families([primary]) if primary else []
    auto = []
    for g in guides:
        name = g[1].strip().lower()
        if name in s.guides or primary is None:
            continue
        for key in s.library.sections(name, s.f):
            if key.split(".", 1)[0] not in families:
                continue
            a = ("tool", "section", {"key": key})
            if a not in auto and not s.ledger.has("section", {"key": key}):
                auto.append(a)
        if primary not in (s.library.facets.get(name) or {}).get("areas", ()):
            continue
        for kw in s.library.workflow_stats(name, s.f)[:L.MAX_GUIDE_STATS]:   # their stats
            a = ("tool", "stats", kw)
            if a not in auto and not s.ledger.has("stats", kw):
                auto.append(a)
    rec["guide_sections"] = [a[2]["key"] if a[1] == "section" else action_text(a) for a in auto]
    acts = guides + calcs + auto + work[:cap]
    rec.update(focus=str(obj.get("focus", ""))[:300], edits=raw_edits, edit_msgs=msgs,
               actions=[action_text(a) for a in acts], done=bool(obj.get("done")))
    notes = []
    if unread:
        rec["unread"] = [json.dumps(a, default=str)[:200] for a in unread]
        notes.append(C.fill("C8", "not_run", items="; ".join(rec["unread"][:3]),
                            guide=C.text("C8", "not_run_guide") if s.library is not None else ""))
    if dropped:
        notes.append(C.fill("C8", "actions_left_out", cap=cap, dropped=dropped))
    if obj.get("done") and not last and state.get("withheld"):
        rec["held_done"] = list(state["withheld"])          # opened, not yet shown: shown first, then decide again
        notes.append(C.fill("C8", "done_waits", items=", ".join(state["withheld"])))
        return {"rec": rec, "acts": [], "notes": notes, "msgs": msgs, "raw_edits": raw_edits,
                "settled_before": settled_before, "refused": refused, "finished": False}
    if obj.get("done") or not acts or last:
        issues = s.claims.done_issues()
        rec["done_issues"] = issues
        if not issues or refused or last:
            rec["answer"] = s.claims.render()
            return {"rec": rec, "steps": [rec], "finished": True}
        refused = True
        notes.append(C.fill("C2", "not_done", why="you set done" if obj.get("done") else "no actions",
                            issues="; ".join(issues)))
        if obj.get("done"):
            acts = []
    return {"rec": rec, "acts": acts, "notes": notes, "msgs": msgs, "raw_edits": raw_edits,
            "settled_before": settled_before, "refused": refused, "finished": False}


def act(state: State, runtime: Runtime[Run]) -> dict:
    """The actions run into the ledger; NEW built within its budget from results only: the results withheld at the last
    step first, then this step's; a guide read goes to GUIDES, outside NEW; a result that does not fit is withheld and
    comes first at the next step. The convergence check."""
    r = runtime.context
    s, rec = r.session, dict(state["rec"])
    notes, msgs = state["notes"], state["msgs"]
    parts, used, withheld, shown, opened, read = list(notes), sum(len(n) for n in notes), [], [], [], []
    if msgs:
        parts.append(C.text("C8", "edits_not_applied") + "\n".join(f"- {m}" for m in msgs))

    def place(out: str, item) -> None:          # a result into NEW, or withheld when it does not fit
        nonlocal used
        if item is not None and item.id in shown:
            out = C.fill("C8", "shown_above", id=item.id)
        elif item is not None and used + len(out) > L.new_chars():
            if item.id not in withheld:
                withheld.append(item.id)
            return
        elif item is not None:
            shown.append(item.id)
        parts.append(out)
        used += len(out)
    for eid in state.get("withheld") or []:    # withheld at the last step: shown first
        item = s.ledger.by_id(eid)
        if item is not None:
            place(s.ledger.show(item), item)
    known = {e.id for e in s.ledger.items}
    for a in state["acts"]:
        out, item = s.run(a)
        if a[0] == "guide" and (name := str(a[1]).strip().lower()) in s.guides:   # to GUIDES, whole at the next step
            read += [] if name in read else [name]
            continue
        if item is not None and item.id not in known:
            opened.append(item.id)
        place(out, item)
    if withheld:                                # before the last step no NEW follows: settle shows every result
        head = C.text("C8", "withheld_last" if state["k"] + 1 >= state["max_steps"] else "withheld")
        parts.append(head + "\n".join(f"[{i}] {s.ledger.by_id(i).call_text()}" for i in withheld))
    rec.update(withheld=withheld, carried=[i for i in state.get("withheld") or [] if i in shown], guides_read=read)
    s.claims.refresh()
    ops = {str(coerce_edit(e)["op"]) for e in state["raw_edits"] if coerce_edit(e)}
    polish = state["polish"] + 1 if (state["settled_before"] and not s.claims.done_issues() and not opened
                                     and not ops & {"add", "drop"}) else 0
    if polish >= L.POLISH_STEPS:
        rec.update(answer=s.claims.render(), stopped="converged")
        return {"rec": rec, "steps": [rec], "polish": polish, "shown_new": shown, "withheld": withheld,
                "guides_new": read, "finished": True}
    new = "\n\n".join(parts) or C.text("C8", "nothing_new")
    rec["new_chars"] = len(new)
    rec["answer"] = s.claims.render()
    return {"rec": rec, "steps": [rec], "polish": polish, "shown_new": shown, "withheld": withheld, "guides_new": read,
            "new": new, "k": state["k"] + 1}


def close(state: State, runtime: Runtime[Run]) -> dict:
    """The investigation's record; a run whose step 1 was unreadable has no answer state and stops here."""
    r = runtime.context
    s, trace = r.session, r.trace
    trace["steps"] = state.get("steps") or []
    trace["options"] = options.as_dict()
    trace["points"], trace["intent"], trace["guides"] = s.points, s.intent, s.guides
    trace["opened"] = [(e.id, e.call_text()) for e in s.ledger.items]
    trace["errors"] = [str(x[2])[:200] for x in s.ledger.errors]
    if s.claims is not None:
        trace["claims"] = [c.__dict__ for c in s.claims.claims.values()]
        trace["dropped"] = [c.__dict__ for c in s.claims.dropped]
        trace["done_issues"] = s.claims.done_issues()
    return {}


def no_answer(state: State, runtime: Runtime[Run]) -> dict:
    raise RuntimeError("the investigation produced no answer state (step 1 unreadable)")


def settle_step(state: State, runtime: Runtime[Run]) -> dict:
    r = runtime.context
    settle(r.llm, r.session, r.usage, r.max_tokens, r.trace)
    return {}


# --- the writer and its checker ------------------------------------------------------------------------------------

def write(state: State, runtime: Runtime[Run]) -> dict:
    return _write(runtime.context)


HANDS_OVER = re.compile(r"\W*INVESTIGATE\b", re.I)


def write_brief(state: State, runtime: Runtime[Run]) -> dict:
    """The short answer: a direct question's, or a later question's that the model chose to answer briefly (step 1's
    "reply": "brief"; route reply_form). The writer's call under C9's reply_brief, with no zone table; the checker
    and the repair rounds are the same. A direct question's writer may hand the question to an investigation
    instead of answering (the one word INVESTIGATE, C9 brief_direct): the look steps' results do not state what is
    asked. The investigation then starts from its own step 1, with those results open."""
    r = runtime.context
    s = r.session
    out = _write(r, brief=True)
    draft = out["draft"].strip()
    if s.depth == "direct" and len(draft) < 200 and HANDS_OVER.match(draft):
        s.depth, s.claims, s.points, s.fetched = "investigate", None, [], []
        r.trace["depth"] = {"read": "direct", "investigated_from": "the writer",
                            "why": "the writer found that the results do not state what is asked"}
        return {"draft": "", "k": 1, "new": "", "shown_new": [], "withheld": [], "guides_new": [], "refused": False,
                "polish": 0, "finished": False}
    return out


def _write(r: Run, brief: bool = False) -> dict:
    from petroharness.agent.writer import clean_reply, cited_lines, prompt, reader_format
    s, llm, usage, trace, cap = r.session, r.llm, r.usage, r.trace, r.max_tokens_writer
    _light(llm, False)                                  # the answer and its repairs are written at normal thinking
    variant = r.writer                                  # the repair rounds it allows (route after_verify)
    system, user, table, shape = prompt(s, r.fmt, brief=brief)
    trace["writer_format"] = "profile" if reader_format(s.f.view.policy, r.fmt) else "default"
    trace["writer_user_chars"], trace["shape"], trace["writer_variant"] = len(user), shape, variant
    trace["cited_lines_chars"] = len(cited_lines(s.claims))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    r.w_messages, r.w_table = messages, table
    draft = llm.chat("writer", messages, usage, cap)
    if not draft.strip():
        draft = llm.chat("writer_retry", messages, usage, cap, retry=True)
    first = clean_reply(draft)
    if first != draft:
        trace["draft_notes_removed"] = bool(first)
        if not first:                                   # notes all through: write again
            draft = clean_reply(llm.chat("writer_again", messages, usage, cap, retry=True)) or draft
        else:
            draft = first
    trace["draft_chars"] = len(draft)
    return {"draft": draft}


def _repair_ask(bad: list, talk: list, contra: list, notes: list) -> str:
    """The repair request for the checker's findings ("" when there are none): the repair node's texts."""
    asks = []
    if contra:
        asks.append(C.text("C2", "repair_contradictions") + " ".join(contra[:4]))
    if bad:
        asks.append(C.fill("C2", "repair_numbers", numbers=", ".join(bad[:12])))
    if talk:
        asks.append(C.fill("C2", "repair_words", words=", ".join(repr(x) for x in talk[:8])))
    if notes:
        asks.append(C.fill("C2", "repair_leaks", leaks=", ".join(repr(x) for x in notes[:4])))
    return " ".join(asks) + C.text("C2", "repair_keep") if asks else ""


def _check(draft: str, r: Run) -> tuple:
    from petroharness.agent.writer import contradictions, leaks, process_words, strip_ids, unsupported
    return (unsupported(strip_ids(draft), r.session, r.w_table), process_words(strip_ids(draft)),
            contradictions(draft, r.session), leaks(strip_ids(draft)))


def verify(state: State, runtime: Runtime[Run]) -> dict:
    """The checker (code): numbers no result shows, words about the process, statements the data contradicts, working
    notes left in the text."""
    bad, talk, contra, notes = _check(state["draft"], runtime.context)
    return {"rounds": [{"round": len(state.get("rounds") or []), "unsupported": bad, "process": talk,
                        "contradictions": contra, "leaks": notes}]}


def repair(state: State, runtime: Runtime[Run]) -> dict:
    """One repair round on the checker's findings; a reply that is notes, empty or much shorter keeps the draft."""
    from petroharness.agent.writer import clean_reply
    r = runtime.context
    llm, usage, cap, draft = r.llm, r.usage, r.max_tokens_writer, state["draft"]
    last = state["rounds"][-1]
    bad, talk, contra, n = last["unsupported"], last["process"], last["contradictions"], len(state["rounds"])
    notes = last.get("leaks") or []
    asks = []
    if contra:
        asks.append(C.text("C2", "repair_contradictions") + " ".join(contra[:4]))
    if bad:
        asks.append(C.fill("C2", "repair_numbers", numbers=", ".join(bad[:12])))
    if talk:
        asks.append(C.fill("C2", "repair_words", words=", ".join(repr(t) for t in talk[:8])))
    if notes:
        asks.append(C.fill("C2", "repair_leaks", leaks=", ".join(repr(t) for t in notes[:4])))
    fix = " ".join(asks) + C.text("C2", "repair_keep")
    msgs = r.w_messages + [assistant_turn(draft, usage, llm.replays_reasoning()), {"role": "user", "content": fix}]
    repaired = clean_reply(llm.chat(f"repair_{n}", msgs, usage, cap), draft)
    if not repaired:                                # notes instead of an answer: ask once more
        repaired = clean_reply(llm.chat(f"repair_{n}_again", msgs, usage, cap, retry=True), draft)
    if repaired.strip() and len(repaired) > 0.6 * len(draft):
        return {"draft": repaired}
    return {"rounds": [{"round": n, "kept_draft": True, "unsupported": bad, "process": talk, "contradictions": contra,
                        "leaks": notes}]}


def delivered(draft: str, table: str) -> str:
    """The answer a reader gets from the writer's draft: the zone table on lines of its own, evidence ids and claim
    ids out, numbers as the results show them."""
    from petroharness.agent.compose import compose
    from petroharness.agent.writer import report_numbers, strip_ids
    draft = re.sub(r"[ \t]*\{\{ZONE_TABLE\}\}[ \t]*", "\n\n{{ZONE_TABLE}}\n\n", draft)     # the table on lines of its own
    return re.sub(r"\n{3,}", "\n\n", report_numbers(strip_ids(compose(draft, table))))


def finalize(state: State, runtime: Runtime[Run]) -> dict:
    """The zone table placed, numbers as the results show them, the status."""
    from petroharness.agent.compose import leftover_citations
    r = runtime.context
    trace, draft, table, rounds = r.trace, state["draft"], r.w_table, state["rounds"]
    trace["verify_rounds"] = rounds
    trace["zone_table"] = table
    # the writer's last draft as the model wrote it: the answer is delivered(draft, zone_table), so a change to how
    # the answer is delivered (ids, numbers) can be measured on the same drafts
    trace["draft"] = draft
    text = delivered(draft, table)
    left = leftover_citations(text)
    if left:
        trace["render_leftovers"] = left
    return {"answer": text, "status": "ok" if not rounds[-1]["unsupported"] else "unresolved_numbers"}


# --- routes (docs/GRAPH.md "Routes") --------------------------------------------------------------------------------

def after_first_look(state: State, runtime: Runtime[Run]) -> str:
    """A question the READ call read as direct takes the look steps; every other the investigation."""
    return "look" if runtime.context.session.depth == "direct" else "ask"


def after_look(state: State, runtime: Runtime[Run]) -> str:
    if runtime.context.session.depth != "direct":       # sent to an investigation after all
        return "ask"
    return "close" if state["finished"] else "look"


def after_ask(state: State) -> str:
    if state["reply"] is None:
        return "skip"
    return "plan" if state["k"] == 1 else "decide"


def after_skip(state: State) -> str:
    k = state["k"] - 1                                  # the step just skipped
    return "close" if k == 1 or k >= state["max_steps"] else "ask"


def after_decide(state: State) -> str:
    return "close" if state["finished"] else "act"


def after_act(state: State) -> str:
    if state.get("finished"):
        return "close"
    return "ask" if state["k"] <= state["max_steps"] else "close"


def after_close(state: State, runtime: Runtime[Run]) -> str:
    s = runtime.context.session
    if s.claims is None:
        return "no_answer"
    if s.depth == "direct":                             # no claims to settle: the short answer from the results
        return "write_brief"
    return "settle" if s.ledger.items else "write"


def reply_form(state: State, runtime: Runtime[Run]) -> str:
    """A later question: the writer node for the answer length the model chose in step 1 (Session.reply)."""
    return "write_brief" if runtime.context.session.reply == "brief" else "write"


def after_close_later(state: State, runtime: Runtime[Run]) -> str:
    """after_close for a later question: where it goes to the full writer, reply_form picks the node."""
    to = after_close(state, runtime)
    return reply_form(state, runtime) if to == "write" else to


def after_write_brief(state: State, runtime: Runtime[Run]) -> str:
    """The short answer goes to the checker; a direct question its writer handed over (write_brief) goes to the
    investigation's step 1."""
    return "ask" if runtime.context.session.claims is None else "verify"


def after_verify(state: State, runtime: Runtime[Run]) -> str:
    rounds, max_rounds = state["rounds"], (2 if runtime.context.writer == "open" else 1)
    last = rounds[-1]
    issues = last["unsupported"] or last["process"] or last["contradictions"] or last.get("leaks")
    return "repair" if issues and state["draft"].strip() and len(rounds) - 1 < max_rounds else "finalize"


def after_repair(state: State) -> str:
    return "finalize" if state["rounds"] and state["rounds"][-1].get("kept_draft") else "verify"


INVESTIGATION_NODES = (("first_look", first_look), ("look", look), ("ask", ask), ("skip", skip), ("plan", plan),
                       ("decide", decide), ("act", act), ("close", close))
WRITER_NODES = (("write", write), ("verify", verify), ("repair", repair), ("finalize", finalize))


def _investigation(g: StateGraph) -> None:
    g.add_conditional_edges("first_look", after_first_look, ["look", "ask"])
    g.add_conditional_edges("look", after_look, ["look", "ask", "close"])
    g.add_conditional_edges("ask", after_ask, ["skip", "plan", "decide"])
    g.add_conditional_edges("skip", after_skip, ["ask", "close"])
    g.add_edge("plan", "decide")
    g.add_conditional_edges("decide", after_decide, ["act", "close"])
    g.add_conditional_edges("act", after_act, ["ask", "close"])


def _writer(g: StateGraph) -> None:
    g.add_edge("write", "verify")
    g.add_conditional_edges("verify", after_verify, ["repair", "finalize"])
    g.add_conditional_edges("repair", after_repair, ["verify", "finalize"])


def question_graph():
    """build -> read -> the investigation -> settle -> the writer and its checker (docs/GRAPH.md)."""
    g = StateGraph(State, context_schema=Run)
    for name, fn in (("build", build), ("read", read_step)) + INVESTIGATION_NODES \
            + (("no_answer", no_answer), ("settle", settle_step), ("write_brief", write_brief)) + WRITER_NODES:
        g.add_node(name, fn)
    g.add_edge(START, "build")
    g.add_edge("build", "read")
    g.add_edge("read", "first_look")
    _investigation(g)
    g.add_conditional_edges("close", after_close, ["no_answer", "settle", "write", "write_brief"])
    g.add_edge("settle", "write")
    g.add_conditional_edges("write_brief", after_write_brief, ["ask", "verify"])
    _writer(g)
    g.add_edge("finalize", END)
    return g.compile()


def later_graph():
    """A later question of a conversation (petroharness.session; docs/GRAPH.md "The later-question graph"): the
    question graph without `build`, on the session the earlier questions ran on, with one more route: the answer
    length the model chose in step 1 picks the writer node (reply_form: write, or write_brief)."""
    g = StateGraph(State, context_schema=Run)
    for name, fn in (("read", read_step),) + INVESTIGATION_NODES \
            + (("no_answer", no_answer), ("settle", settle_step), ("write_brief", write_brief)) + WRITER_NODES:
        g.add_node(name, fn)
    g.add_edge(START, "read")
    g.add_edge("read", "first_look")
    _investigation(g)
    g.add_conditional_edges("close", after_close_later, ["no_answer", "settle", "write", "write_brief"])
    g.add_conditional_edges("settle", reply_form, ["write", "write_brief"])
    g.add_conditional_edges("write_brief", after_write_brief, ["ask", "verify"])
    _writer(g)
    g.add_edge("finalize", END)
    return g.compile()


def investigation_graph():
    g = StateGraph(State, context_schema=Run)
    for name, fn in INVESTIGATION_NODES:
        g.add_node(name, fn)
    g.add_edge(START, "first_look")
    _investigation(g)
    g.add_edge("close", END)
    return g.compile()


def writer_graph():
    g = StateGraph(State, context_schema=Run)
    for name, fn in WRITER_NODES:
        g.add_node(name, fn)
    g.add_edge(START, "write")
    _writer(g)
    g.add_edge("finalize", END)
    return g.compile()


GRAPH, INVESTIGATION, WRITER, LATER = question_graph(), investigation_graph(), writer_graph(), later_graph()
_CONFIG = {"recursion_limit": RECURSION_LIMIT}


def investigate(llm: LLM, s: Session, usage: Usage, max_tokens: int, trace: dict, max_steps: int = MAX_STEPS) -> Optional[Claims]:
    """The investigation alone, on a built session (loop.investigate, the tests' entry point), from the first look
    with the session's topics as they are (no READ call): the claims, or None (step 1 unreadable)."""
    run = Run(task=s.task, cfg=None, llm=llm, usage=usage, trace=trace, max_tokens=max_tokens, session=s)
    INVESTIGATION.invoke({"max_steps": max_steps}, context=run, config=_CONFIG)
    return s.claims


def write_answer(llm: LLM, s: Session, cfg, usage: Usage, trace: dict, variant: str = "", fmt: str = "profile") -> tuple:
    """The writer and its checker alone (src/petroharness/agent/writer.py's entry point): (answer, status)."""
    run = Run(task=s.task, cfg=cfg, llm=llm, usage=usage, trace=trace, writer=variant, fmt=fmt,
              max_tokens_writer=cfg.model.max_tokens_writer, session=s)
    out = WRITER.invoke({}, context=run, config=_CONFIG)
    return out["answer"], out["status"]


# --- one question ---------------------------------------------------------------------------------------------------

def task_config(task, model_key: str, rep: int):
    """The configuration one question runs under: the model's card, the endpoint this task is sent to (by its id and
    the repetition), the task's data settings."""
    from petroharness.config import HarnessConfig
    from petroharness.models import MODELS
    from petroharness.config import RESOURCES
    cfg_file, urls, *named = MODELS[model_key]
    cfg = HarnessConfig.load(RESOURCES / cfg_file)
    if named:
        cfg.model.model = named[0]                   # the served model's name (petroharness --model)
    cfg.model.base_url = urls[(int(hashlib.sha256(task.task_id.encode()).hexdigest()[:8], 16) + rep) % len(urls)]
    return cfg.for_tasks()


def answer(task, model_key: str, rep: int, max_steps: int = MAX_STEPS, writer: str = "", fmt: str = "profile",
           llm_factory: Optional[Callable] = None, commit: str = "", depth: bool = True) -> dict:
    """One question through the graph -> {"answer", "status", "trace"} (src/petroharness/cli.py's record). llm_factory(cfg) builds the
    model client (default: petroharness.llm.LLM on the registry's endpoint for this task). depth: turn()'s."""
    return turn(task, model_key, rep, max_steps, writer, fmt, llm_factory, commit, depth=depth)[0]


def route(trace: dict) -> str:
    """How a question was answered, from its trace: "direct" (look steps and a short answer), "investigation", or
    "investigation after a look" (read as direct, then sent to an investigation)."""
    if isinstance(trace.get("depth"), dict):
        return "investigation after a look"
    return "direct" if (trace.get("read") or {}).get("depth") == "direct" else "investigation"


def route_text(trace: dict) -> str:
    """The route in the words a user reads beside an answer."""
    n = len(trace.get("steps") or [])
    steps = f"{n} step{'' if n == 1 else 's'}"
    how = route(trace)
    if how == "direct":
        return f"a direct answer, {n} look step{'' if n == 1 else 's'}"
    if how == "investigation after a look":
        return f"an investigation after a first look, {steps}"
    return f"{n} investigation step{'' if n == 1 else 's'}"


def turn(task, model_key: str, rep: int, max_steps: int = MAX_STEPS, writer: str = "", fmt: str = "profile",
         llm_factory: Optional[Callable] = None, commit: str = "", session: Optional[Session] = None,
         depth: bool = True) -> tuple:
    """One question -> ({"answer", "status", "trace"}, the session it ran on). The first question of a conversation
    builds the session (`session` None: the whole question graph, as answer()). A later one runs on the session the
    earlier questions left, already moved to this task (Session.next_turn): the graph starts at the READ call, the
    well is not prepared again and the ledger's ids go on. `depth`: the READ call also says whether the question is
    direct (the direct route, docs/GRAPH.md); False: every question gets the investigation (the 3.5.6 route)."""
    tcfg = task_config(task, model_key, rep)
    library = direction.plugged(tcfg)                # the skill library, checked as it loads: a bad one stops here
    llm, usage = (llm_factory or LLM)(tcfg), Usage()
    _light(llm, False)                               # a client shared across questions starts each at normal thinking
    trace = {"task_id": task.task_id, "well": task.well, "formation": task.formation, "topics": [],
             "harness": HARNESS, "commit": commit, "model": model_key, "skills": direction.stamp(library)}
    trace["components"] = C.versions()               # each component's version (src/petroharness/agent/components)
    C.recording(llm, trace, library)                 # every call's attribution: trace["calls"]
    run = Run(task=task, cfg=tcfg, llm=llm, usage=usage, trace=trace, writer=writer, fmt=fmt,
              max_tokens=tcfg.model.max_tokens_spec, max_tokens_writer=tcfg.model.max_tokens_writer, session=session,
              depth=bool(depth))
    trace["reads_depth"] = run.depth                 # the route setting: False is the 3.5.6 route
    if session is not None:
        session.reads_depth = run.depth
        trace["session"] = {"turn": session.turn, "ledger_start": session.turn_start,
                            "earlier_chars": len(session.earlier)}
    t0 = time.time()
    try:
        out = (GRAPH if session is None else LATER).invoke({"max_steps": max_steps}, context=run, config=_CONFIG)
        text, status = out["answer"], out["status"]
    except Exception as exc:                         # one question's failure is recorded, the run goes on
        trace["error"] = f"{type(exc).__name__}: {exc}"
        trace["traceback"] = traceback.format_exc()[-4000:]
        text, status = "", f"error: {type(exc).__name__}"
    trace["status"], trace["seconds"] = status, round(time.time() - t0, 1)
    trace["usage"] = usage.log
    return {"answer": text, "status": status, "trace": trace}, run.session
