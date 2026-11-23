"""The session graph: one question of a conversation, from the user's message to its committed record, as a LangGraph
state graph (docs/GRAPH.md, "The session graph", is its blueprint; tests/session/test_session_graph.py keeps the two
equal).

    open -> turn -> project -> figures -> commit
              |        |__________________^        figures off, or prepared tasks: no figures
              |___________________________^        a question with no answer: nothing to project or draw

The question itself runs inside `turn` as its own graph (petroharness.agent.graph: the question graph for the first
question, the later-question graph after it), invoked in the node, so the two graphs share no state. What comes after
the answer hangs on the session graph, never inside the question: `project` (code only) and `figures` (one model call
and Petrophys' plots) cannot change an answer's text, and a benchmark run takes neither a model call nor a plot from
them.

The domain state is the conversation's (the log, the live session with its ledger, the earlier questions): held in
the run context and changed in place by the nodes, as the question graph holds its session. The graph state is the
question's control data and what one node hands the next. Nothing is checkpointed: the log is how a conversation is
resumed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from petroharness import ask as A
from petroharness.session.earlier import opening


@dataclass
class Ctx:
    """The run context of one question of a conversation: the conversation itself (private to the nodes)."""
    conversation: Any


class State(TypedDict, total=False):
    task: Any                    # the question as a task (input)
    question: str                # the question as asked (input)
    sent: str                    # the question as sent to the model (input)
    n: int                       # the question's number in the conversation
    folder: Path                 # turns/NN
    start: int                   # where this question's results start in the ledger
    shown: str                   # the earlier questions as the prompts show them ("" for the first)
    got: dict                    # the question graph's {"answer", "status", "trace"}
    items: list                  # the results this question opened
    settled: list                # its settled claims, each with the ids it cites
    cited: list                  # the ids the answer rests on, in the order of the points
    rests: list                  # the steps and parameters the answer rests on (petroharness.basis)
    shows: dict                  # each number the answer states -> the results that show it (evidence.links)
    figs: list                   # the figures drawn for it (petroharness.figures)
    out: Any                     # the committed Turn


# --- nodes -----------------------------------------------------------------------------------------------------------

def open_question(state: State, runtime: Runtime[Ctx]) -> dict:
    """The question enters the log; the session moves to it (the earlier questions as the prompts will show them)."""
    c = runtime.context.conversation
    task, n = state["task"], len(c.turns) + 1
    folder = c.folder / "turns" / f"{n:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    if c.setup is None:                                   # what this process answers under, once; logged when it changes
        from petroharness.agent.graph import task_config
        from petroharness.core import setup as S
        with c._settings():
            c.setup = S.of(task_config(task, c.key, 1), writer=c.writer, fmt=c.fmt, max_steps=c.max_steps,
                           mode="interactive" if c.p is not None else "tasks", depth=c.depth)
        if c.setup.hash() != (c.log.events("setup") or [{}])[-1].get("hash"):
            c.log.append("setup", n, hash=c.setup.hash(), **c.setup.to_dict())
    c.log.append("question", n, text=state["question"], task=json.loads(task.model_dump_json()))
    start = len(c.live.ledger.items) if c.live is not None else 0
    shown = c.earlier() if c.live is not None else ""
    if c.live is not None:
        with c._settings():
            c.live.next_turn(task, shown)
    return {"n": n, "folder": folder, "start": start, "shown": shown}


def turn(state: State, runtime: Runtime[Ctx]) -> dict:
    """The question graph runs (the whole graph for the first question, the later-question graph after it); its
    results enter the log, and its settled claims are read."""
    from petroharness.agent import graph
    from petroharness.cli import COMMIT
    c = runtime.context.conversation
    task, n = state["task"], state["n"]
    with c._settings():
        got, live = graph.turn(task, c.key, 1, c.max_steps or graph.MAX_STEPS, c.writer, c.fmt,
                               llm_factory=c._factory(state["folder"]), commit=COMMIT, session=c.live, depth=c.depth)
    c.live = live if live is not None else c.live
    trace = got["trace"]
    trace["answer"] = got["answer"]
    trace["setup"] = c.setup.hash()
    changes = c.changes() if c.p is not None else []
    if changes:                                           # the settings changed in this conversation: in force, and how
        trace["settings"] = {"turn": n, "in_force": c.settings, "sources": c.sources(), "changes": changes,
                             "changed": [x for e in changes if e["turn"] == n for x in e["changes"]]}
    if c.p is not None:
        trace["ask"] = A.ask_record(c.p, state["question"], state["sent"], trace)
    items = c.live.ledger.items[state["start"]:] if c.live is not None else []
    for e in items:
        c.log.append("result", n, id=e.id, tool=e.tool, args=e.args, sha256=c.log.blob(e.text), chars=len(e.text))
    if c.live is not None:                                # the record the results were read from, once per change
        from petroharness.evidence import record as R
        snap = R.snapshot(c.live.f.inv)
        sha = c.log.blob(json.dumps(snap, sort_keys=True))
        if sha != c.record_sha:
            c.log.append("record", n, sha256=sha, curves=len(snap["curves"]), steps=len(snap["steps"]))
            c.record_sha = sha
    claims = getattr(c.live, "claims", None) if c.live is not None else None
    settled = [{"point": k.point, "text": k.text, "grade": k.grade, "ev": list(k.ev)}
               for k in (claims.claims.values() if claims is not None else []) if k.grade != "hypothesis"]
    # what the answer rests on: the results its claims cite; a short answer has none, and rests on what its look
    # steps were shown (earlier questions' results among them) and opened
    cited = list(dict.fromkeys([x for k in sorted(settled, key=lambda k: k["point"]) for x in k["ev"]]
                               or list(getattr(c.live, "fetched", None) or []) + [e.id for e in items]))
    return {"got": got, "items": items, "settled": settled, "cited": cited, "rests": [], "shows": {}, "figs": []}


def project(state: State, runtime: Runtime[Ctx]) -> dict:
    """Code only: what is read off the answer and its results for the reader and for the evidence graph: the steps
    and parameters the answer rests on, and which results show each number it states. A projection that fails is said
    in the trace and costs nothing else."""
    from petroharness import basis
    from petroharness.evidence import links
    c, got = runtime.context.conversation, state["got"]
    rests, shows = [], {}
    try:
        rests = basis.used(c.live, state["cited"], got["answer"])
        shows = links.shows(got["answer"], c.live.ledger.items, c.live.f.view.reg.checks, (c.live.task.well,))
    except Exception as exc:                              # noqa: BLE001 - a projection never costs the answer
        got["trace"]["projection_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    got["trace"]["basis"] = rests
    return {"rests": rests, "shows": shows}


def figures(state: State, runtime: Runtime[Ctx]) -> dict:
    """One model call chooses among the plots Petrophys can draw from what the answer rests on; Petrophys draws them
    (petroharness.figures). The answer's text is not touched."""
    c, got, n = runtime.context.conversation, state["got"], state["n"]
    rec = c._figures(state["task"], state["question"], got["answer"], state["cited"], state["folder"], got["trace"])
    got["trace"]["figures"] = rec
    for g in rec["figures"]:
        c.log.append("figure", n, **{k: g[k] for k in ("id", "kind", "source", "caption", "file", "samples")})
    return {"figs": rec["figures"]}


def commit(state: State, runtime: Runtime[Ctx]) -> dict:
    """The question's record: its files (answer.md with the figures and the methods and parameters, trace.json), its
    turn_end event, and the conversation's list of questions."""
    from petroharness import basis
    from petroharness.figures import markdown
    from petroharness.session.conversation import Turn
    c, got, n, folder = runtime.context.conversation, state["got"], state["n"], state["folder"]
    trace, items, settled = got["trace"], state["items"], state["settled"]
    figs, rests = state.get("figs") or [], state.get("rests") or []
    usage = trace.get("usage") or []
    rec = {"turn": n, "question": state["question"], "task_id": state["task"].task_id, "status": got["status"],
           "opening": opening(got["answer"]), "claims": settled, "opened": [e.id for e in items],
           "cited": sorted({x for k in settled for x in k["ev"]}, key=lambda x: (len(x), x)),
           "answer_sha256": c.log.blob(got["answer"]), "earlier_chars": len(state["shown"]), "figures": len(figs),
           "basis": [r["step"] for r in rests], "shows": state.get("shows") or {},
           "steps": len(trace.get("steps") or []), "calls": sum(1 for u in usage if u.get("prompt_tokens")),
           "prompt_tokens": sum(u.get("prompt_tokens") or 0 for u in usage),
           "completion_tokens": sum(u.get("completion_tokens") or 0 for u in usage),
           "seconds": trace.get("seconds")}
    if (trace.get("settings") or {}).get("changed"):       # the settings were changed for this question
        rec["settings_changed"] = trace["settings"]["changed"]
    if not settled and state.get("cited"):                # a short answer: the results it was read from (it has no
        rec["read_from"] = list(state["cited"])           # claims to cite them by); the next question is shown them
    if c.p is not None:
        result = A.AskResult(answer=got["answer"], status=got["status"], trace=trace, interval=c.p.used, out_dir=folder)
        body = A._answer_md(result, c.p.las)
    else:
        body = f"**Question {n}:** {state['question']}\n\n---\n\n{got['answer']}\n"
    (folder / "answer.md").write_text(body + markdown(figs) + basis.markdown(rests), encoding="utf-8")
    (folder / "trace.json").write_text(json.dumps(trace, indent=1, default=str), encoding="utf-8")
    c.log.append("turn_end", n, **{k: v for k, v in rec.items() if k != "turn"})
    c.turns.append(rec)
    return {"out": Turn(number=n, question=state["question"], answer=got["answer"], status=got["status"], trace=trace,
                        folder=folder, figures=figs, basis=rests)}


# --- routes ----------------------------------------------------------------------------------------------------------

def after_turn(state: State, runtime: Runtime[Ctx]) -> str:
    """An answered question goes on to its projections; one with no answer (an error, an empty reply, a question its
    user stopped) is committed as it is."""
    from petroharness.session.conversation import unanswered
    c, got = runtime.context.conversation, state["got"]
    answered = c.live is not None and got["answer"].strip() and not unanswered(got["status"])
    return "project" if answered else "commit"


def after_project(state: State, runtime: Runtime[Ctx]) -> str:
    """Figures are for interactive use: a conversation on prepared tasks (a benchmark run), or one started with
    figures off, goes straight to commit."""
    return "figures" if runtime.context.conversation.figures else "commit"


def session_graph():
    """open -> turn -> project -> figures -> commit (docs/GRAPH.md, "The session graph")."""
    g = StateGraph(State, context_schema=Ctx)
    for name, fn in (("open", open_question), ("turn", turn), ("project", project), ("figures", figures),
                     ("commit", commit)):
        g.add_node(name, fn)
    g.add_edge(START, "open")
    g.add_edge("open", "turn")
    g.add_conditional_edges("turn", after_turn, ["project", "commit"])
    g.add_conditional_edges("project", after_project, ["figures", "commit"])
    g.add_edge("figures", "commit")
    g.add_edge("commit", END)
    return g.compile()


SESSION = session_graph()


def run(conversation, task, question: str, sent: str):
    """One question of a conversation through the session graph -> its Turn."""
    from petroharness.agent.graph import no_hosted_tracing
    no_hosted_tracing()
    out = SESSION.invoke({"task": task, "question": question, "sent": sent}, context=Ctx(conversation))
    return out["out"]
