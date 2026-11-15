"""The web UI's adapter over petroharness.ask: the page's inputs as ask()'s arguments (checked before a question is
queued), a LAS file's header, the formations a tops file names, and one question run as a Job, with its live
progress (progress.Observed) and the parts of its trace the page shows.

The page's inputs (POST /api/ask):

    {"las": PATH, "question": TEXT,
     "interval": {"mode": "whole"}
               | {"mode": "tops", "tops": PATH, "formation": NAME[, "unit": "m"|"ft"]}
               | {"mode": "depths", "top": D, "base": D[, "unit": "m"|"ft"][, "name": LABEL]},
     "lithology_curve": MNEMONIC, "formation_lithology": TEXT, "profile": NAME,
     "skills": "default" | "none" | PATH, "max_steps": N, "depth": "investigate"}

Everything but the LAS, the question and the interval is optional.
"""

from __future__ import annotations

import itertools
import json
import threading
import time
import traceback
import warnings
from collections.abc import Callable
from pathlib import Path

MAX_QUESTION = 8000
MAX_STEPS_LIMIT = 30


class InputError(ValueError):
    """An input the page must correct: the message says what, why and how (as ask's own errors do)."""


# --- the inputs --------------------------------------------------------------------------------------------------------

def _file(path, what: str) -> Path:
    text = str(path or "").strip()
    if not text:
        raise InputError(f"WHAT: no {what} given. FIX: give its path on the server, or upload it.")
    p = Path(text).expanduser()
    if not p.is_file():
        raise InputError(f"WHAT: no {what} at {text}. FIX: give the path of an existing file on the server, or "
                         "upload it.")
    return p.resolve()


def las_info(path) -> dict:
    """A LAS file's header as the page shows it: the well's names, the depth unit, the first and last depth of the log,
    its samples and curves (mnemonic, unit, description), and the curves that look like a lithology log."""
    import lasio
    import numpy as np

    from petroharness.ask import _las_header
    from petroharness.well.formation import LITHOLOGY_LOG
    from petroharness.well.prepare import read_depth

    p = _file(path, "LAS file")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            head = lasio.read(str(p), ignore_data=True)
            unit, names = _las_header(p)
            depth = np.asarray(read_depth(p), dtype=float)
    except Exception as exc:  # noqa: BLE001  (any failure to read is the same answer: not a readable LAS)
        raise InputError(f"WHAT: {p.name} could not be read as a LAS file ({type(exc).__name__}: {str(exc)[:200]}). "
                         "FIX: give a LAS 2.0 file (a well log with ~Version, ~Well, ~Curve and ~A sections).") from None
    finite = depth[np.isfinite(depth)]

    def well_item(key):
        return str(head.well.get(key, "").value or "").strip()

    curves = [{"mnemonic": c.mnemonic, "unit": (c.unit or "").strip(), "description": (c.descr or "").strip()}
              for c in head.curves[1:]]
    step = float(np.median(np.diff(finite))) if finite.size > 1 else None
    return {"path": str(p), "name": p.name, "well": well_item("WELL"), "uwi": well_item("UWI"),
            "names": names, "depth_unit": unit, "depth_unit_raw": (head.curves[0].unit or "").strip() if len(head.curves) else "",
            "top": float(finite.min()) if finite.size else None, "base": float(finite.max()) if finite.size else None,
            "step": round(step, 6) if step else None, "samples": int(depth.size), "curves": curves,
            "lithology_candidates": [c["mnemonic"] for c in curves
                                     if LITHOLOGY_LOG.search(c["mnemonic"]) or LITHOLOGY_LOG.search(c["description"])]}


def tops_info(path, las=None, unit: str | None = None) -> dict:
    """The formations a tops file names, as the tops reader finds them (petroharness.well.tops), each with the
    interval a question about it would use. With a LAS file, a table with a well column is read for that well only,
    and depths with no stated unit are in the LAS's unit."""
    from petroharness.ask import _las_header
    from petroharness.well.formation import FormationNotFound
    from petroharness.well.tops import read_tops

    p = _file(path, "tops file")
    las_unit, names = (None, [])
    if las:
        las_unit, names = _las_header(_file(las, "LAS file"))
    try:
        table = read_tops(p, names, unit or None, las_unit)
    except (ValueError, LookupError, OSError) as exc:
        raise InputError(str(exc)) from None
    out = []
    for name in table.names():
        row = {"name": name}
        try:
            got = table.interval(name)
            row.update(top=got.top, base=got.base, unit=got.unit, closed=got.closed, base_from=got.base_from)
        except FormationNotFound:                        # a name listed twice: asked about by its depths
            hits = [t for t in table.tops if t.name == name]
            row.update(repeated=[{"top": t.top, "base": t.base, "line": t.line, "unit": t.unit} for t in hits])
        except ValueError as exc:
            row["error"] = str(exc)
        out.append(row)
    return {"path": str(p), "name": p.name, "columns": table.columns, "wells": list(table.wells), "formations": out}


def _number(value, what: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise InputError(f"WHAT: the {what} {value!r} is not a number. FIX: give a depth such as 1520.5.") from None


def _unit(value) -> str | None:
    from petroharness.well.tops import depth_unit_name
    if value in (None, ""):
        return None
    got = depth_unit_name(value)
    if got is None:
        raise InputError(f"WHAT: depth unit {value!r} is not m or ft. FIX: choose m or ft.")
    return got


def arguments(inputs: dict) -> dict:
    """The page's inputs as petroharness.ask's keyword arguments, checked: what can be wrong in them is said now,
    before the question waits for a worker."""
    if not isinstance(inputs, dict):
        raise InputError("WHAT: the request is not a JSON object. FIX: send the page's form.")
    las = _file(inputs.get("las"), "LAS file")
    question = str(inputs.get("question") or "").strip()
    if not question:
        raise InputError("WHAT: the question is empty. FIX: write the question to answer.")
    if len(question) > MAX_QUESTION:
        raise InputError(f"WHAT: the question has {len(question)} characters. FIX: keep it under {MAX_QUESTION}.")
    kw: dict = {"las": las, "question": question}
    iv = inputs.get("interval") or {"mode": "whole"}
    mode = str(iv.get("mode") or "whole")
    if mode == "tops":
        tops = _file(iv.get("tops"), "tops file")
        formation = str(iv.get("formation") or "").strip()
        if not formation:
            raise InputError("WHAT: no formation chosen. FIX: pick one of the names the tops file lists.")
        kw.update(tops=tops, formation=formation, depth_unit=_unit(iv.get("unit")))
        from petroharness.ask import _las_header
        from petroharness.well.tops import read_tops
        las_unit, names = _las_header(las)
        try:
            read_tops(tops, names, kw["depth_unit"], las_unit).interval(formation)
        except (ValueError, LookupError, OSError) as exc:
            raise InputError(str(exc)) from None
    elif mode == "depths":
        top, base = _number(iv.get("top"), "top"), _number(iv.get("base"), "base")
        if top is None and base is None:
            raise InputError("WHAT: no depths given. FIX: give the interval's top and base (or choose the whole well).")
        if top is not None and base is not None and base <= top:
            raise InputError(f"WHAT: the base ({base:g}) is not below the top ({top:g}). FIX: give the top above the "
                             "base (depths increase downwards).")
        name = str(iv.get("name") or "").strip()
        kw.update(top=top, base=base, depth_unit=_unit(iv.get("unit")), formation=name or None)
    elif mode != "whole":
        raise InputError(f"WHAT: interval mode {mode!r}. FIX: use whole, tops or depths.")
    for key in ("lithology_curve", "formation_lithology"):
        value = str(inputs.get(key) or "").strip()
        if value:
            kw[key] = value
    profile = str(inputs.get("profile") or "").strip()
    if profile:
        known = context_profiles()
        if known and profile not in known:
            raise InputError(f"WHAT: no context profile {profile!r}. FIX: choose one of {', '.join(known)}, or none.")
        kw["profile"] = profile
    skills = str(inputs.get("skills") or "").strip()
    if skills and skills.lower() not in ("default", "none"):
        p = Path(skills).expanduser()
        if not p.is_dir():
            raise InputError(f"WHAT: no skill library folder at {skills}. FIX: give a library folder (laid out as the "
                             "packaged one), or choose the default library or none.")
        kw["skills"] = str(p.resolve())
    elif skills.lower() == "none":
        kw["skills"] = "none"
    steps = inputs.get("max_steps")
    if steps not in (None, ""):
        try:
            steps = int(steps)
        except (TypeError, ValueError):
            raise InputError(f"WHAT: max steps {steps!r} is not a whole number. FIX: give 1 to {MAX_STEPS_LIMIT}.") from None
        if not 1 <= steps <= MAX_STEPS_LIMIT:
            raise InputError(f"WHAT: max steps {steps}. FIX: give 1 to {MAX_STEPS_LIMIT}.")
        kw["max_steps"] = steps
    depth = str(inputs.get("depth") or "").strip().lower()
    if depth == "investigate":                                # default: the model says whether a question is direct
        kw["direct"] = False
    elif depth not in ("", "auto"):
        raise InputError(f"WHAT: depth {depth!r}. FIX: leave it out (the model decides), or give 'investigate' for a "
                         "full investigation of every question.")
    return kw


def context_profiles() -> list:
    """Petrophys's context profiles (empty when the installed Petrophys lists none)."""
    try:
        import petrophys
        return list(petrophys.list_context_profiles())
    except Exception:  # noqa: BLE001  (a Petrophys without profiles, or one that fails to list them: none offered)
        return []


def interval_label(inputs: dict) -> str:
    """The interval as the run list names it."""
    iv = inputs.get("interval") or {}
    mode = iv.get("mode") or "whole"
    if mode == "tops":
        return str(iv.get("formation") or "")
    if mode == "depths":
        span = f"{iv.get('top') if iv.get('top') not in (None, '') else 'log top'}-" \
               f"{iv.get('base') if iv.get('base') not in (None, '') else 'log base'}"
        return str(iv.get("name") or "").strip() or f"{span} {iv.get('unit') or ''}".strip()
    return "whole well"


# --- one question ----------------------------------------------------------------------------------------------------

class Job:
    """One question: its inputs, its live events, then the answer and what the page shows of the trace."""

    def __init__(self, run_id: str, inputs: dict, kwargs: dict):
        self.id = run_id
        self.inputs = inputs
        self.kwargs = kwargs
        self.events: list = []
        self.status = "queued"
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.endpoint = ""
        self.answer = ""
        self.result: dict | None = None
        self.error = ""
        self.rating: dict = {}
        self.root = run_id                 # the run that started this conversation (itself, for a first question)
        self.conversation: dict = {}       # {root, turn, thread: [{turn, question, run}]}, once the question ran
        self.saved = False                 # its finished record is on disk (the server sets it after saving)
        self._lock = threading.Lock()

    def emit(self, event: dict) -> None:
        t0 = self.started or self.created
        with self._lock:
            self.events.append({"t": round(max(time.time() - t0, 0.0), 1), **event})

    def elapsed(self) -> float:
        if self.started is None:
            return 0.0
        return round((self.finished or time.time()) - self.started, 1)

    def view(self, since: int = 0, final: bool | None = None) -> dict:
        """What the page is given. A job shows as finished once its record is saved, so whoever sees it finished finds
        the record on disk (final=True: the record itself, as it is)."""
        with self._lock:
            events = self.events[since:]
            n = len(self.events)
        finished = self.finished is not None and (self.saved if final is None else final)
        status = self.status if finished or self.finished is None else "running"
        return {"id": self.id, "status": status, "inputs": self.inputs, "label": interval_label(self.inputs),
                "created": _iso(self.created), "elapsed": self.elapsed(), "endpoint": self.endpoint,
                "events": events, "n_events": n, "answer": self.answer if finished else "",
                "result": self.result if finished else None, "error": self.error, "rating": self.rating,
                "conversation": self.conversation or {"root": self.root}}

    def record(self) -> dict:
        return self.view(0, final=True) | {"finished": _iso(self.finished) if self.finished else None}


def _iso(t: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="seconds")


_ASKING: dict = {}                     # a conversation's folder -> its lock: one question of it at a time
_ASKING_GUARD = threading.Lock()


def _asking(session: Path) -> threading.Lock:
    with _ASKING_GUARD:
        return _ASKING.setdefault(str(session), threading.Lock())


def run(job: Job, out: Path, model_url: str | None, model_factory: Callable | None = None,
        root_out: Path | None = None) -> None:
    """Answer the job's question as a question of a conversation (petroharness.session), reporting the interval's
    logs once Petrophys has interpreted the well (a `well` event: petroharness.ui.wellplot) and each model call as it
    happens. A first question starts the conversation in `out`/session and is answered as petroharness.ask answers
    it; a follow-up (`root_out`: the folder of the conversation's first run) resumes that conversation. The answer,
    the trace and the figures are written to `out`. model_factory(cfg) builds the model client (default: the
    harness's own LLM)."""
    import shutil

    from petroharness.llm import LLM
    from petroharness.session import Conversation

    base = model_factory or LLM
    job.status, job.started = "running", time.time()
    job.emit({"kind": "phase", "name": "started", "endpoint": model_url or ""})
    job.emit({"kind": "phase", "name": "interpreting"})
    def plot(view) -> None:                                   # the interval's logs, once Petrophys has read the well
        try:
            from petroharness.ui.wellplot import payload
            job.emit({"kind": "well", **payload(view)})
        except Exception as exc:  # noqa: BLE001  (the plot never fails the run)
            job.emit({"kind": "well", "error": f"{type(exc).__name__}: {exc}"})

    try:
        from petroharness.ui.progress import Observed
        kw = dict(job.kwargs)
        question = kw.pop("question")
        numbers = itertools.count(1)                         # one numbering for the run's calls (the question's client
        factory = lambda cfg: Observed(base(cfg), job.emit, numbers)   # and the figures call's)
        session = (root_out or out) / "session"
        with _asking(session):
            if root_out is None:
                session.mkdir(parents=True, exist_ok=True)
                cache = out / ".cache"
                if cache.exists() and not (session / ".cache").exists():     # the interpreted wells shared by every run
                    (session / ".cache").symlink_to(cache.resolve(), target_is_directory=True)
                c = Conversation.start(kw.pop("las"), session, **kw, model_url=model_url, llm_factory=factory,
                                       on_view=plot)
            else:
                c = Conversation.resume(session, model_url=model_url, llm_factory=factory, on_view=plot)
            shown = c.overview()                              # the interval's log display by Petrophys, once
            if shown is not None:
                (out / "figures").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(shown, out / "figures" / shown.name)
                job.emit({"kind": "display", "file": shown.name})
            turn = c.ask(question)
            runs = json.loads((session / "runs.json").read_text()) if (session / "runs.json").exists() else {}
            runs[str(turn.number)] = job.id
            (session / "runs.json").write_text(json.dumps(runs))
        for name in ("answer.md", "trace.json"):
            shutil.copyfile(turn.folder / name, out / name)
        if (turn.folder / "figures").is_dir():
            shutil.copytree(turn.folder / "figures", out / "figures", dirs_exist_ok=True)
        job.conversation = {"root": job.root, "turn": turn.number,
                            "thread": [{"turn": r["turn"], "question": r["question"], "status": r["status"],
                                        "run": runs.get(str(r["turn"]))} for r in c.turns]}
        job.answer = turn.answer
        job.result = summary(turn.trace, c.p.used, turn.status)
        job.result["figures"] = [{"caption": g["caption"], "file": Path(g["file"]).name, "kind": g["kind"],
                                  "source": g["source"]} for g in turn.figures]
        job.result["basis"] = turn.basis
        job.status = "done" if turn.ok else "error"
        if not turn.ok:
            job.error = str(turn.trace.get("error") or turn.status)
    except (ValueError, LookupError, OSError) as exc:          # the inputs (ask's own checks): said as ask says them
        job.status, job.error = "error", str(exc)
    except Exception as exc:  # noqa: BLE001  (one question's failure is recorded; the server goes on)
        job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
        job.result = {"traceback": traceback.format_exc()[-4000:]}
    finally:
        job.finished = time.time()
        job.emit({"kind": "phase", "name": "finished", "status": job.status, **({"error": job.error} if job.error else {})})


def _route(trace: dict) -> str:
    from petroharness.agent.graph import route
    return route(trace)


def summary(trace: dict, interval: dict, status: str) -> dict:
    """What the page shows of a run's trace: the interval and zones, the READ, the points and claims, the opened
    results, each step, the settle step, the checker's rounds, the skills, the usage."""
    a = trace.get("ask") or {}
    usage = trace.get("usage") or []
    claims = [{k: c.get(k) for k in ("id", "point", "text", "means", "weak", "grade", "ev", "flags")}
              for c in trace.get("claims") or [] if isinstance(c, dict)]
    from petroharness.ui.progress import edit_view
    steps = []
    for s in trace.get("steps") or []:
        steps.append({"step": s.get("step"), "focus": s.get("focus", ""), "actions": s.get("actions") or [],
                      "guide_sections": s.get("guide_sections") or [],
                      "edits": [edit_view(e) for e in s.get("edits") or [] if e],
                      "edit_msgs": s.get("edit_msgs") or [], "done": s.get("done"), "error": s.get("error"),
                      "repaired": (s.get("repaired") or {}).get("by"), "stopped": s.get("stopped"),
                      "withheld": s.get("withheld") or [], "prompt_tokens": s.get("prompt_tokens")})
    settle = trace.get("settle") or {}
    return {
        "status": status, "seconds": trace.get("seconds"), "interval": interval,
        "question_sent": a.get("question_sent"), "lithology": a.get("lithology"), "zones": a.get("zones") or [],
        "settings": a.get("settings"), "interpret": a.get("interpret"), "petrophys": a.get("petrophys"),
        "read": {k: (trace.get("read") or {}).get(k) for k in ("topics", "named", "parse", "depth")},
        "route": _route(trace),
        "topics": trace.get("topics") or [], "absent": trace.get("absent") or [],
        "points": trace.get("points") or [], "intent": trace.get("intent"),
        "claims": claims,
        "dropped": [{k: c.get(k) for k in ("id", "point", "text")} for c in trace.get("dropped") or [] if isinstance(c, dict)],
        "done_issues": trace.get("done_issues") or [],
        "opened": [{"id": o[0], "call": o[1]} for o in trace.get("opened") or [] if isinstance(o, (list, tuple))],
        "errors": trace.get("errors") or [],
        "guides": trace.get("guides") or [], "skills": trace.get("skills"), "skills_given": a.get("skills_given"),
        "steps": steps,
        "settle": {k: settle.get(k) for k in ("claims_before", "claims_after", "issues_after", "error")}
                  | {"edits": len(settle.get("edits") or [])} if settle else None,
        "verify_rounds": trace.get("verify_rounds") or [],
        "zone_table": trace.get("zone_table") or "",
        "usage": {"calls": len(usage), "prompt_tokens": sum(u.get("prompt_tokens") or 0 for u in usage),
                  "completion_tokens": sum(u.get("completion_tokens") or 0 for u in usage),
                  "seconds": round(sum(u.get("seconds") or 0 for u in usage), 1),
                  "log": [{k: u.get(k) for k in ("stage", "prompt_tokens", "completion_tokens", "seconds")} for u in usage]},
        "error": trace.get("error"), "traceback": trace.get("traceback"),
    }
