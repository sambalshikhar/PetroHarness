"""A conversation on one interval of one well (the package docstring). The well is prepared once; every question runs
the question graph on the same session, so the ledger and its ids go on and a later question reads what earlier ones
opened. Each question runs through the session graph (petroharness.session.graph). The session folder:

    log.jsonl              the events: session_start, question, result, turn_end, session_resume (session/log.py)
    blobs/                 the texts the events name (results as shown, answers), each once, by SHA-256
    overview.png           the interval's log display by Petrophys, drawn when the conversation starts
    turns/NN/answer.md     question NN's answer with its header
    turns/NN/trace.json    its full trace
    turns/NN/tape.jsonl    its model requests and replies (petroharness.tape)
    .cache/                the interpreted well (a conversation started from a LAS file)

Two ways in. `Conversation.start` takes a LAS file and an interval, as petroharness.ask does, and `ask` takes each
question as text. `Conversation.on_tasks` runs prepared tasks (petroharness.tasks.Task, the batch runner's unit) with
`ask_task`: the questions of one well and interval from a question file, under the data settings in force.

Resuming rebuilds the session from the log: the well is prepared again (from the cache) and every recorded result is
opened again in order, which must give the same ids and texts (a difference is logged with the resume event).
"""
from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from petroharness import ask as A
from petroharness.session.earlier import block
from petroharness.session.log import SessionLog

# what a conversation on a LAS file is started with, kept in the log so it can be resumed (the model endpoint is not:
# it can change)
INPUTS = ("formation", "tops", "top", "base", "depth_unit", "lithology_curve", "formation_lithology", "profile",
          "settings", "skills", "model", "model_card", "max_steps", "figures", "direct")


@dataclass
class Turn:
    """One answered question of a conversation."""
    number: int
    question: str
    answer: str
    status: str                   # ok, unresolved_numbers, error: ...
    trace: dict
    folder: Path                  # turns/NN (answer.md, trace.json, tape.jsonl, figures/)
    figures: list = field(default_factory=list)   # the figures drawn for it (petroharness.figures): caption, file
    basis: list = field(default_factory=list)     # the steps and parameters it rests on (petroharness.basis)

    @property
    def ok(self) -> bool:
        return not self.status.startswith("error")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Conversation:
    def __init__(self, folder: Path, key: str, *, prepared: A.Prepared | None = None, inputs: dict | None = None,
                 llm_factory: Callable | None = None, writer: str = "open", fmt: str = "profile",
                 max_steps: int | None = None, figures: bool = False, depth: bool = True):
        self.folder, self.key, self.p, self.inputs = Path(folder), key, prepared, dict(inputs or {})
        self.llm_factory, self.writer, self.fmt, self.max_steps = llm_factory, writer, fmt, max_steps
        # whether the model first says if a question is direct (the direct route, docs/GRAPH.md); False: every
        # question gets the investigation (the 3.5.6 route: --investigate, direct=False)
        self.depth = bool(depth)
        self.figures = figures            # draw an answer's figures (petroharness.figures); never for a benchmark run
        self.log = SessionLog(self.folder)
        # the well's record as last kept in the log (evidence.record.snapshot; a new one is logged when it changes)
        self.record_sha = (self.log.events("record") or [{}])[-1].get("sha256")
        self.setup = None                 # what this process answers under (core.setup), set by the first question
        self.turns: list = []             # one record per question asked (the log's turn_end events)
        self.live = None                  # the session the questions run on (petroharness.agent.loop.Session)

    # --- opening ------------------------------------------------------------------------------------------------------
    @classmethod
    def start(cls, las, folder, *, formation: str | None = None, tops=None, top: float | None = None,
              base: float | None = None, depth_unit: str | None = None, lithology_curve: str | None = None,
              formation_lithology: str | None = None, profile: str | None = None, settings=None,
              skills: str | None = None, model_url: str | None = None, model: str | None = None,
              model_card: str | None = None, max_steps: int | None = None, llm_factory: Callable | None = None,
              on_view: Callable | None = None, figures: bool = True, direct: bool = True) -> Conversation:
        """A new conversation about one interval of a LAS file, kept in `folder` (the arguments are ask()'s). The
        interval is checked and the well interpreted here, before any question. `figures`: draw each answer's
        figures (one more model call per answer chooses them). `direct`: the model first says whether a question is
        direct (a short route and a short answer) or needs an investigation; False: always an investigation."""
        folder = cls._new(folder)
        las = Path(las).expanduser().resolve()
        if not las.is_file():
            raise FileNotFoundError(f"WHAT: no LAS file at {las}. FIX: give the path of the well's LAS file.")
        given = {"formation": formation, "tops": tops, "top": top, "base": base, "depth_unit": depth_unit,
                 "lithology_curve": lithology_curve, "formation_lithology": formation_lithology, "profile": profile,
                 "settings": settings, "skills": skills, "model": model, "model_card": model_card,
                 "max_steps": max_steps, "figures": figures, "direct": direct}
        inputs = {k: (str(v) if isinstance(v, Path) else v) for k, v in given.items()}
        c = cls._open(folder, las, inputs, model_url, llm_factory, on_view)
        from petroharness.cli import COMMIT
        from petroharness.well.prepare import library_identity
        c.log.append("session_start", mode="las", las=str(las),
                     las_sha256=hashlib.sha256(las.read_bytes()).hexdigest(), inputs=inputs, interval=c.p.used,
                     lithology=c.p.litho,
                     zones=[{"zone": z.zone_id, "lithology": z.lithology, "top": z.top, "base": z.base}
                            for z in c.p.view.zones],
                     model=A._model_label(c.key), petrophys=library_identity(), harness=COMMIT)
        return c

    @classmethod
    def on_tasks(cls, folder, key: str, *, llm_factory: Callable | None = None, writer: str = "open",
                 fmt: str = "profile", max_steps: int | None = None, figures: bool = False,
                 direct: bool = True) -> Conversation:
        """A new conversation whose questions are prepared tasks of one well and interval (`ask_task`), run under the
        data settings in force (the batch runner's: PETROHARNESS_DATA). `key`: the model registry key. `direct`:
        start()'s."""
        from petroharness.cli import COMMIT
        from petroharness.well.prepare import library_identity
        c = cls(cls._new(folder), key, llm_factory=llm_factory, writer=writer, fmt=fmt, max_steps=max_steps,
                figures=figures, depth=direct)
        c.log.append("session_start", mode="tasks", model=key, writer=writer, fmt=fmt, max_steps=max_steps,
                     figures=figures, direct=bool(direct),
                     petrophys=library_identity(), harness=COMMIT)
        return c

    @staticmethod
    def _new(folder) -> Path:
        folder = Path(folder).expanduser().resolve()
        if (folder / "log.jsonl").exists():
            raise ValueError(f"WHAT: a conversation already lives in {folder}. FIX: resume it (Conversation.resume, "
                             "petroharness chat --resume), or give another folder.")
        return folder

    @classmethod
    def resume(cls, folder, *, model_url: str | None = None, key: str | None = None,
               llm_factory: Callable | None = None, on_view: Callable | None = None,
               direct: bool | None = None) -> Conversation:
        """The conversation kept in `folder`, ready for its next question: the well prepared again and the ledger
        rebuilt from the log. `key`: the model registry key of a conversation on tasks (default: the one it started
        with). `direct`: start()'s, for the questions from here on (default: as the conversation was started)."""
        folder = Path(folder).expanduser().resolve()
        started = SessionLog(folder).events("session_start") if (folder / "log.jsonl").exists() else []
        if not started:
            raise ValueError(f"WHAT: no conversation in {folder}. FIX: give the folder a conversation was started in, "
                             "or start one (Conversation.start, petroharness chat --las ...).")
        s0 = started[0]
        if s0.get("mode") == "tasks":
            c = cls(folder, key or s0["model"], llm_factory=llm_factory, writer=s0.get("writer", "open"),
                    fmt=s0.get("fmt", "profile"), max_steps=s0.get("max_steps"), figures=bool(s0.get("figures")),
                    depth=bool(s0.get("direct", True)))
            if direct is not None:
                c.depth = bool(direct)
        else:
            c = cls._open(folder, Path(s0["las"]), s0["inputs"], model_url, llm_factory, on_view)
            if direct is not None:
                c.depth = bool(direct)
        c.turns = [{k: v for k, v in e.items() if k not in ("seq", "time", "type")} for e in c.log.events("turn_end")]
        differences = c._rebuild()
        c.log.append("session_resume", questions=len(c.turns), results=len(c.live.ledger.items) if c.live else 0,
                     differences=differences)
        return c

    @classmethod
    def _open(cls, folder: Path, las: Path, inputs: dict, model_url, llm_factory, on_view) -> Conversation:
        key = A._model_key(model_url, llm_factory, inputs.get("model"), inputs.get("model_card"))
        p = A.prepare(las, key, cache=folder / ".cache",
                      **{k: inputs.get(k) for k in INPUTS
                         if k not in ("model", "model_card", "max_steps", "figures", "direct")})
        A.check(p, A.task_for(p, "(the interval)")[0], on_view)
        return cls(folder, key, prepared=p, inputs=inputs, llm_factory=llm_factory, max_steps=inputs.get("max_steps"),
                   figures=bool(inputs.get("figures", True)), depth=bool(inputs.get("direct", True)))

    def overview(self) -> Path | None:
        """The interval's log display by Petrophys (petroharness.figures.overview), drawn once per conversation into
        the session folder; None where figures are off or it could not be drawn (said in the log)."""
        from petroharness import figures as F
        path = self.folder / F.OVERVIEW
        if not self.figures or self.p is None or getattr(self.p, "view", None) is None:
            return None
        if path.is_file():
            return path
        try:
            with self._settings():
                png = F.overview(self.p.view, str(self.p.used.get("name") or ""))
            path.write_bytes(png)
            self.log.append("display", 0, name="overview", file=F.OVERVIEW, function=F.FUNCTIONS[F.VIEWER], bytes=len(png))
            return path
        except Exception as exc:                          # noqa: BLE001 - a display never costs the conversation
            self.log.append("display", 0, name="overview", error=f"{type(exc).__name__}: {str(exc)[:300]}")
            return None

    def _settings(self):
        """The data settings every question runs under: the prepared interval's, or (tasks) the ones in force."""
        from petroharness.config import given_settings
        return given_settings(self.p.given) if self.p is not None else contextlib.nullcontext()

    def _rebuild(self) -> list:
        """The live session from the log: each recorded result opened again, in order -> the differences found (an id
        or a text that is not the recorded one), [] when the ledger is as it was."""
        from petroharness.agent import graph
        from petroharness.agent.loop import Session
        from petroharness.tasks import Task
        results, tasks, bad = {}, {}, []
        for e in self.log.events("result"):
            results.setdefault(e["turn"], []).append(e)
        for e in self.log.events("question"):
            tasks[e["turn"]] = Task(**e["task"])
        with self._settings():
            for rec in self.turns:
                task = tasks[rec["turn"]]
                if self.live is None:
                    if rec["turn"] not in results and str(rec.get("status", "")).startswith("error"):
                        continue                          # a question that failed before the well was read
                    self.live = Session.build(task, graph.task_config(task, self.key, 1))
                else:
                    self.live.next_turn(task, "")
                for e in results.get(rec["turn"], []):
                    try:
                        if e["tool"] == "calc":
                            item, _ = self.live.ledger.calc(e["args"]["expression"], f"{self.live.map}\n{task.question}")
                        else:
                            item, _ = self.live.ledger.open(e["tool"], e["args"])
                    except Exception as exc:              # noqa: BLE001 - a result that no longer opens is reported
                        bad.append({"id": e["id"], "what": f"not opened again: {type(exc).__name__}: {str(exc)[:200]}"})
                        continue
                    if item.id != e["id"]:
                        bad.append({"id": e["id"], "what": f"opened again as {item.id}"})
                    elif _sha(item.text) != e["sha256"]:
                        bad.append({"id": e["id"], "what": "its text differs from the recorded one"})
        return bad

    # --- asking -------------------------------------------------------------------------------------------------------
    def earlier(self) -> str:
        """EARLIER IN THIS SESSION as the next question's prompts will show it ("" before the first question)."""
        return block(self.turns)

    def ask(self, question: str) -> Turn:
        """The next question of a conversation on a LAS file -> its Turn. The first question is answered as
        petroharness.ask answers it; a later one runs on the same session with the earlier questions in view."""
        if self.p is None:
            raise ValueError("WHAT: this conversation runs prepared tasks. FIX: use ask_task(task).")
        question = str(question or "").strip()
        if not question:
            raise ValueError("WHAT: the question is empty. FIX: give the question to answer.")
        task, sent = A.task_for(self.p, question, len(self.turns) + 1)
        return self._run(task, question, sent)

    def ask_task(self, task) -> Turn:
        """The next question as a prepared task (the same well and interval as the conversation's first)."""
        return self._run(task, task.question, task.question)

    def _run(self, task, question: str, sent: str) -> Turn:
        """One question through the session graph (petroharness.session.graph: open -> turn -> project -> figures ->
        commit; docs/SESSION_GRAPH.md)."""
        from petroharness.session import graph
        return graph.run(self, task, question, sent)

    def _figures(self, task, question: str, answer: str, cited: list, tdir: Path) -> dict:
        """The answer's figures, after it is final (petroharness.figures.attach): one model call chooses among the
        plots of the cited results, code draws them into turns/NN/figures. The answer's text is not touched."""
        from petroharness import figures as F
        from petroharness.agent import graph
        from petroharness.llm import Usage
        usage = Usage()
        try:
            with self._settings():
                llm = self._factory(tdir)(graph.task_config(task, self.key, 1))
                graph._light(llm, True)               # choosing among listed plots needs little reasoning
                try:
                    rec = F.attach(self.live, question, answer, cited, llm, usage, tdir / "figures")
                finally:
                    graph._light(llm, False)          # a client shared with the next question: normal thinking again
        except Exception as exc:                          # noqa: BLE001 - figures never cost the answer
            rec = {"candidates": [], "chosen": [], "figures": [], "errors": [f"{type(exc).__name__}: {str(exc)[:300]}"]}
        rec["usage"] = usage.log
        return rec

    def _factory(self, tdir: Path) -> Callable:
        """The model client of one question: the caller's (or the endpoint's), with its requests and replies taped."""
        base = self.llm_factory

        def make(cfg):
            from petroharness import tape
            from petroharness.llm import LLM
            llm = (base or LLM)(cfg)
            if hasattr(getattr(getattr(llm, "client", None), "chat", None), "completions"):
                tape.record(llm, tdir / "tape.jsonl")
            return llm
        return make
