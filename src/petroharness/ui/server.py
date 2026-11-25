"""The PetroHarness web UI: ask about a LAS file in the browser and follow the answer as it is made.

    petroharness --launch-ui [the same options]     (starts the UI and opens it in your browser)
    petroharness ui [--host 127.0.0.1] [--port 7860] [--runs DIR] [--workers N] [--model NAME | --model-card CARD]
                    [--model-url URLS] [--open]

Standard library only. It binds to 127.0.0.1 by default: open http://localhost:7860 on the same machine, or forward the
port from a remote one (`ssh -L 7860:localhost:7860 HOST`, or the editor's port forwarding). `--host localhost` listens
on both 127.0.0.1 and ::1; `--host 0.0.0.0` on every interface (anyone who can reach the port can then ask questions
and read the saved runs).

The model: K2-Horizon-7B by default, or any chat model on an OpenAI-compatible endpoint (--model NAME, or a model card
with --model-card; docs/MODELS.md), on the endpoints in PETROHARNESS_MODEL_URL (comma-separated), or --model-url. Each
question goes to the least busy endpoint that serves the model. --workers questions run at once (default 4); more wait
in a queue.

API (JSON):
    GET  /api/config                endpoints and their health, workers, queue, defaults, topic areas, context profiles,
                                    each tool's group
    GET  /api/settings              the interpretation settings, grouped, with their defaults and help
    POST /api/preview               the inputs, before any question -> the interval, its zones, how they were read and
                                    the value each setting took on this well
    GET  /api/samples               Petrophys's sample wells, each with its header and its tops sample
    GET  /api/las?path=             a LAS file's header (well, depth range and unit, curves)
    GET  /api/tops?path=[&las=&unit=]  the formations a tops file names, with the interval each would use
    POST /api/upload?kind=las|tops|zones|notes  the file's bytes, header X-Filename -> {path, ...}
    GET  /api/zones?path=[&las=]    the user's zones a zones file gives, and what is wrong in them
    GET  /api/notes?path=           a field notes file: its name, settings and notes, checked
    POST /api/ask                   the inputs (petroharness.ui.adapter) -> {id}
    POST /api/stop/<id>             stop a question that is waiting or running -> {id, status}
    GET  /api/job/<id>?since=N      status, the events from N on, then the answer and the result
    GET  /api/runs                  the runs, newest first (running and saved)
    GET  /api/run/<id>              a saved run in full
    GET  /api/run/<id>/answer.md | trace.json
    GET  /api/run/<id>/conversation the run's conversation as it stands: every question in order, with answer and figures
    GET  /api/run/<id>/figures/<name>  one figure of the answer (PNG)
    GET  /api/run/<id>/audit        the answer's audit trail (Markdown)
    GET  /api/run/<id>/lineage      what the answer rests on: claims, results, curves, Petrophys steps, measured logs
    GET  /api/run/<id>/logview?extent=interval|well   the log viewer: every curve it can show, tracks, zones
    GET  /api/run/<id>/logdata?top=&base=&curves=A,B&points=N&extent=   those curves in a depth window (thinned to N)
    POST /api/rate/<id>             {verdict: good|partly|wrong, note}
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import statistics
import socket
import sys
import threading
import time
import traceback
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from petroharness.ui import adapter as A
from petroharness.ui.store import Store, brief

STATIC = Path(__file__).resolve().parent / "static"
MAX_UPLOAD = 1024 * 2 ** 20
MAX_JSON = 2 * 2 ** 20
CONTENT_TYPES = {".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
KEEP_FINISHED = 100          # finished jobs kept in memory; older ones are read from the runs folder


# --- the model endpoints -------------------------------------------------------------------------------------------

def served_model(model: str | None = None, card: str | None = None) -> str:
    """The model id the harness asks the endpoints for: --model, else its model card's (a card that names none, as
    the generic card, needs --model: a ValueError, as the question command says it)."""
    from petroharness.models import card_file, card_settings
    file = card_file(card, model)
    served = model or str(card_settings(file)["model"] or "")
    if not served:
        raise ValueError(f"WHAT: the model card {Path(file).name} names no model. FIX: give the served model's name "
                         "(--model NAME, as the server lists it at /v1/models).")
    return served


class Endpoints:
    """The model endpoints: their health (GET /v1/models, kept 15 s) and how many questions each is answering."""

    def __init__(self, urls: list, model: str = "", max_age: float = 15.0):
        self.urls = [u.strip().rstrip("/") for u in urls if u.strip()]
        self.model = model
        self.max_age = max_age
        self.busy = {u: 0 for u in self.urls}
        self._rows: list = []
        self._t = 0.0
        self._lock = threading.Lock()

    def _probe(self, url: str) -> dict:
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(url + "/models", timeout=4) as r:
                ids = [m.get("id") for m in json.loads(r.read()).get("data", [])]
        except Exception as exc:  # noqa: BLE001  (any failure to answer: the endpoint is down for the page)
            return {"url": url, "ok": False, "models": [], "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        ok = not self.model or self.model in ids
        row = {"url": url, "ok": ok, "models": ids, "ms": round((time.perf_counter() - t0) * 1000)}
        if not ok:
            row["error"] = f"serves {', '.join(map(str, ids)) or 'no model'}, not {self.model}"
        return row

    def health(self, fresh: bool = False) -> list:
        if fresh or time.time() - self._t > self.max_age or len(self._rows) != len(self.urls):
            if self.urls:
                with ThreadPoolExecutor(len(self.urls)) as ex:
                    rows = list(ex.map(self._probe, self.urls))
            else:
                rows = []
            with self._lock:
                self._rows, self._t = rows, time.time()
        with self._lock:
            return [r | {"busy": self.busy.get(r["url"], 0)} for r in self._rows]

    def acquire(self) -> str:
        """The least busy endpoint serving the model (counted busy until release)."""
        if not self.urls:
            raise RuntimeError("WHAT: no model endpoint. WHY: the model answers through an OpenAI-compatible endpoint "
                               "(/v1). FIX: set PETROHARNESS_MODEL_URL=http://HOST:PORT/v1 (several, comma-separated) "
                               "or start the UI with --model-url, then restart it.")
        rows = self.health()
        live = [r["url"] for r in rows if r["ok"]]
        if not live:
            live = [r["url"] for r in self.health(fresh=True) if r["ok"]]
        if not live:
            said = "; ".join(f"{r['url']}: {r.get('error')}" for r in self._rows)
            raise RuntimeError(f"WHAT: no endpoint serves {self.model} ({said}). FIX: start the model server, or point "
                               "PETROHARNESS_MODEL_URL at one that runs.")
        with self._lock:
            url = min(live, key=lambda u: self.busy.get(u, 0))
            self.busy[url] = self.busy.get(url, 0) + 1
        return url

    def release(self, url: str) -> None:
        with self._lock:
            if url in self.busy:
                self.busy[url] = max(0, self.busy[url] - 1)


# --- the app: jobs, the worker pool --------------------------------------------------------------------------------

class App:
    """The runs folder, the endpoints, the jobs in this server's life and the workers that answer them."""

    def __init__(self, runs, workers: int = 4, urls: list | None = None, model_factory: Callable | None = None,
                 max_age: float = 15.0, model: str | None = None, model_card: str | None = None):
        from petroharness.models import card_file, label
        self.store = Store(runs)
        self.store.interrupted()
        self.choice = {k: v for k, v in (("model", model), ("model_card", model_card)) if v}   # ask's model options
        self.label = label(card_file(model_card, model), model)
        served = "" if model_factory is not None else served_model(model, model_card)
        self.endpoints = Endpoints(urls if urls is not None else _env_urls(), served, max_age)
        self.model_factory = model_factory          # tests: a stand-in model; no endpoint is used then
        self.workers = max(1, int(workers))
        self.jobs: dict = {}
        self.waiting: list = []                     # ids, in queue order
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        for i in range(self.workers):
            threading.Thread(target=self._work, name=f"petroharness-ui-{i + 1}", daemon=True).start()

    def submit(self, inputs: dict) -> A.Job:
        root = None
        follow = str(inputs.get("follow") or "").strip() if isinstance(inputs, dict) else ""
        scope = A.scope_input(inputs.get("scope")) if isinstance(inputs, dict) else None   # wrong: said now
        if follow:                                  # a follow-up: the next question of that run's conversation
            prev = self._record(follow)
            stopped = prev.get("status") == "stopped" and (prev.get("conversation") or {}).get("turn")
            if prev.get("status") != "done" and not stopped:     # a stopped question's conversation goes on
                raise A.InputError("WHAT: that question has no answer yet. FIX: wait for it to finish, then ask the "
                                   "follow-up.")
            root = (prev.get("conversation") or {}).get("root") or follow
            if not (self.store.folder(root) / "session" / "log.jsonl").is_file():
                raise A.InputError("WHAT: that run has no conversation to go on with (it was answered by an earlier "
                                   "version). FIX: ask its question again, then follow up on the new answer.")
            change = inputs.get("interpretation") if "interpretation" in inputs else None
            inputs = {**prev["inputs"], "question": inputs.get("question"), "follow": follow}
            inputs.pop("adopt", None)
            if change is not None:                  # the settings to run under from this question on (adopted)
                inputs.update(interpretation=change or {}, adopt=True)
        if isinstance(inputs, dict):                # the stretches this question is on, chosen by the user (an answer
            inputs = {k: v for k, v in inputs.items() if k != "scope"} | ({"scope": scope} if scope else {})
            #                                         to a question back), set before the question is read
        kwargs = A.arguments({k: v for k, v in inputs.items() if k != "scope"}) | self.choice   # wrong inputs are
        #                                             said now, not after the queue
        job = A.Job(self.store.new_id(), inputs, kwargs)
        job.root = root or job.id
        with self._lock:
            self.jobs[job.id] = job
            self.waiting.append(job.id)
        job.emit({"kind": "phase", "name": "queued"})
        self.store.prepare(job.id)
        self.store.save(job.record())
        self._queue.put(job)
        return job

    def stop(self, run_id: str) -> dict:
        """Stop a question: one still waiting is taken off the queue; one running is told to stop, and ends once the
        model call in flight is left (the page shows it stopping meanwhile). Its conversation goes on with the next
        question. A run that has finished is not changed."""
        job = self._job(run_id)
        if job is None or job.finished is not None:
            self._record(run_id)                                 # an unknown run: KeyError (404)
            raise A.InputError("WHAT: that question is not running. FIX: nothing to stop.")
        with self._lock:                                         # a worker takes a job off the list under this lock
            waiting = job.id in self.waiting
            if waiting:
                self.waiting.remove(job.id)
                job.status, job.finished = "stopped", time.time()
        job.stop.set()
        if waiting:                                              # never started: its worker will pass it by
            job.emit({"kind": "phase", "name": "finished", "status": "stopped"})
            self.store.save(job.record())
            job.saved = True
        else:
            job.emit({"kind": "phase", "name": "stopping"})
        return {"id": job.id, "status": "stopped" if waiting else "stopping"}

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            with self._lock:
                if job.id in self.waiting:
                    self.waiting.remove(job.id)
                gone = job.finished is not None                  # stopped while it waited (App.stop)
            if gone:
                self._queue.task_done()
                continue
            url = None
            try:
                if self.model_factory is None:
                    url = self.endpoints.acquire()
                    job.endpoint = url
                A.run(job, self.store.prepare(job.id), url, self.model_factory,
                      None if job.root == job.id else self.store.folder(job.root))
            except Exception as exc:  # noqa: BLE001  (no endpoint: the job fails with the reason)
                job.status, job.error = "error", str(exc)
                job.finished = job.finished or time.time()
                job.emit({"kind": "phase", "name": "finished", "status": "error", "error": job.error})
            finally:
                if url:
                    self.endpoints.release(url)
                try:
                    self.store.save(job.record())
                except Exception:  # noqa: BLE001  (a record not saved is said in the log; the worker goes on)
                    traceback.print_exc()
                job.saved = True                    # from here the page sees it finished
                self._forget()
                self._queue.task_done()

    def _job(self, run_id: str):
        """The job of a run while the job table holds it (read once, under its lock), else None."""
        with self._lock:
            return self.jobs.get(run_id)

    def _record(self, run_id: str) -> dict:
        """A run's record: its job's while the job table holds it, else its saved record (KeyError: no such run). A
        worker may drop a finished job from the table at any time (_forget), so the table is read once."""
        job = self._job(run_id)
        return job.record() if job is not None else self.store.load(run_id)

    def _live(self) -> list:
        """The jobs not yet finished, copied under the table's lock (workers add and drop jobs meanwhile)."""
        with self._lock:
            return [j for j in self.jobs.values() if j.finished is None]

    def _forget(self, keep: int = KEEP_FINISHED) -> None:
        """Finished jobs beyond the newest `keep` are served from their saved record."""
        with self._lock:
            done = sorted((j for j in self.jobs.values() if j.finished is not None), key=lambda j: j.finished)
            for j in done[:max(0, len(done) - keep)]:
                self.jobs.pop(j.id, None)

    def _evidence(self, run_id: str):
        """(the evidence graph of a run's conversation, the run's turn in it), from the conversation's session folder."""
        from petroharness.evidence import EvidenceGraph
        rec = self._record(run_id)
        conv = rec.get("conversation") or {}
        session = self.store.folder(conv.get("root") or run_id) / "session"
        if not (session / "log.jsonl").is_file() or not conv.get("turn"):
            raise KeyError(f"{run_id} has no audit trail (it has no answer yet, or was answered by an earlier version)")
        return EvidenceGraph.from_log(session), int(conv["turn"])

    def audit(self, run_id: str) -> str:
        """The audit trail of a run's answer (petroharness.evidence), from its conversation's session folder."""
        from petroharness.evidence import audit
        return audit.markdown(*self._evidence(run_id))

    def lineage(self, run_id: str) -> dict:
        """What a run's answer rests on, for the page's computation graph (EvidenceGraph.trail): its claims and the
        results they cite, which results show each number it states, the curves those name, the Petrophys steps behind
        them with their methods and parameters, and the measured logs they start from."""
        graph, turn = self._evidence(run_id)
        return graph.trail(turn)

    def conversation(self, run_id: str) -> dict:
        """The conversation a run belongs to, as it stands now: every question of it in order (those asked after this
        run's too, and one still waiting or running), each with its answer, its figures, the interpretation settings
        it ran under and the settings changed for it, for the page to keep the earlier questions on screen. A question
        not yet run is numbered after the last one that ran."""
        record = self._record
        root = (record(run_id).get("conversation") or {}).get("root") or run_id       # an unknown run: KeyError (404)
        live = {j.id: brief(j.record()) for j in self._live() if j.root == root}
        mine = list(live.values()) + [b for b in self.store.conversation(root) if b["id"] not in live]
        turns = []
        for b in sorted(mine, key=lambda b: (b.get("created") or "", b["id"])):
            r = record(b["id"])
            res = r.get("result") if isinstance(r.get("result"), dict) else {}
            n = (r.get("conversation") or {}).get("turn") or (turns[-1]["turn"] + 1 if turns else 1)
            turns.append({"id": r["id"], "turn": n, "question": (r.get("inputs") or {}).get("question", ""),
                          "status": r.get("status"), "outcome": res.get("status"), "created": r.get("created"),
                          "elapsed": r.get("elapsed"), "answer": r.get("answer") or "",
                          "interpretation": (r.get("inputs") or {}).get("interpretation") or {},
                          "settings_changed": (res.get("settings_changes") or {}).get("changed") or [],
                          "figures": [{"file": f.get("file"), "caption": f.get("caption", "")}
                                      for f in res.get("figures") or [] if isinstance(f, dict) and f.get("file")]})
        return {"root": root, "turns": turns}

    VIEWS_KEPT = 6                              # runs whose interpreted well the log viewer keeps open

    def view(self, run_id: str):
        """A run's view for the log viewer (adapter.view_of), kept for the last VIEWS_KEPT runs asked for."""
        with self._lock:
            views = self.__dict__.setdefault("_views", {})
            if run_id in views:
                views[run_id] = views.pop(run_id)           # the most recently used last
                return views[run_id]
        view = A.view_of(self._record(run_id)["inputs"], self.store.cache)
        with self._lock:
            views[run_id] = view
            while len(views) > self.VIEWS_KEPT:
                views.pop(next(iter(views)))
        return view

    def logs(self, run_id: str, what: str, q: dict) -> dict:
        """The log viewer's two reads of a run: logview (what it can show) and logdata (curves in a depth window)."""
        from petroharness.ui import wellplot as W
        view, extent = self.view(run_id), q.get("extent") or "interval"
        if what == "logview":
            return W.log_index(view, extent)
        try:
            top, base = float(q["top"]), float(q["base"])
        except (KeyError, ValueError):
            raise A.InputError("WHAT: the window needs top and base, as numbers. FIX: give both depths.") from None
        curves = [c for c in (q.get("curves") or "").split(",") if c]
        return W.log_window(view, top, base, curves, int(q.get("points") or W.MAX_POINTS), extent)

    def position(self, run_id: str) -> int | None:
        with self._lock:
            return self.waiting.index(run_id) + 1 if run_id in self.waiting else None

    def job_view(self, run_id: str, since: int) -> dict:
        job = self._job(run_id)
        if job is None:
            rec = self.store.load(run_id)
            return rec | {"events": rec.get("events", [])[since:], "n_events": len(rec.get("events", []))}
        out = job.view(since)
        out["queue_position"] = self.position(run_id)
        return out

    def runs(self) -> list:
        saved = self.store.history()
        live = {j.id: j for j in self._live()}
        out = [brief(j.record()) | {"elapsed": j.elapsed()} for j in sorted(live.values(), key=lambda j: j.id, reverse=True)]
        return out + [r for r in saved if r["id"] not in live]

    def typical(self) -> dict:
        """How long a question takes on this server, from its saved runs that answered: the median seconds and the
        number of runs, for a direct answer and for an investigation ({"direct": [s, n], "investigation": [s, n]}),
        each once it has TYPICAL_MIN runs. The page's time left. Read again at most every TYPICAL_TTL seconds."""
        now = time.time()
        with self._lock:
            got = getattr(self, "_typical", None)
            if got and now - got[0] < TYPICAL_TTL:
                return got[1]
        times: dict = {"direct": [], "investigation": []}
        for path in sorted(self.store.root.glob("*/run.json"))[-TYPICAL_RUNS:]:
            try:
                r = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            res = r.get("result") if isinstance(r.get("result"), dict) else {}
            if r.get("status") != "done" or res.get("status") not in ("ok", "unresolved_numbers") or not r.get("elapsed"):
                continue
            kind = "direct" if res.get("route") == "direct" else "investigation"
            times[kind].append(float(r["elapsed"]))
        out = {k: [round(statistics.median(v)), len(v)] for k, v in times.items() if len(v) >= TYPICAL_MIN}
        with self._lock:
            self._typical = (now, out)
        return out

    def config(self) -> dict:
        from petroharness import __version__
        from petroharness.agent import direction
        from petroharness.agent.state import MAX_STEPS
        with self._lock:
            running = sum(j.status == "running" for j in self.jobs.values())
            waiting = len(self.waiting)
        return {"version": __version__, "model": self.endpoints.model or "(stand-in model)", "label": self.label,
                "endpoints": self.endpoints.health() if self.model_factory is None else [],
                "workers": self.workers, "running": running, "queued": waiting, "runs": str(self.store.root),
                "max_steps": MAX_STEPS, "profiles": A.context_profiles(),
                "topics": {k: v.get("when", "") for k, v in direction.areas().items()},
                "verbs": verbs(), "petrophys_verbs": petrophys_verbs(),
                "examples": examples(), "typical": self.typical(),
                "skills_env": os.environ.get("PETROHARNESS_SKILLS", ""),
                "settings_env": os.environ.get("PETROHARNESS_DATA", "")}


TYPICAL_MIN, TYPICAL_RUNS, TYPICAL_TTL = 3, 400, 300     # runs needed for a typical time; the latest read; seconds kept


def examples() -> list:
    """Questions to start with, as the harness offers them when a request is outside what it does (C9
    outside_examples): each with {interval} for the interval's name."""
    from petroharness.agent import components as C
    return [str(x) for x in C.text("C9", "outside_examples")]


def verbs() -> dict:
    """Each tool's group, as the brief groups the tools (agent/toolset.py): {tool: group}."""
    from petroharness.agent.toolset import TOOLSET
    return {t: head.split(":")[0].strip().capitalize() for head, tools in TOOLSET.by_group() for t in tools}


def petrophys_verbs() -> list:
    """The verbs over Petrophys (docs/TOOLS.md): their requests have Petrophys compute what the record lacks."""
    from petroharness.agent.toolset import TOOLSET
    return [t.name for t in TOOLSET if t.verb]


def _env_urls() -> list:
    from petroharness.models import env_urls
    return env_urls()


# --- HTTP ------------------------------------------------------------------------------------------------------------

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


class Handler(BaseHTTPRequestHandler):
    server_version = "PetroHarnessUI"
    app: App = None                                 # set by make_servers
    loopback = True                                 # set by make_servers: the server listens on a loopback address
    allow_hosts: frozenset = frozenset()            # set by make_servers: further host names it answers (--allow-host)

    def _refused(self, method: str, path: str) -> str | None:
        """Why an API request is refused, or None. Another site's page cannot use this server through the user's
        browser: a request from another origin is refused; a POST must be the page's own (JSON, or an upload with
        its X-Filename header), which a browser does not send across sites without the server's leave; and a server
        on a loopback address answers its own host names only (a renamed host could otherwise reach it)."""
        host = (self.headers.get("Host") or "").strip().lower()
        name = urlparse("//" + host).hostname or ""
        if self.loopback and name not in LOOPBACK | self.allow_hosts:
            return (f"WHAT: a request for host {host!r}. WHY: this server listens on a loopback address and answers "
                    "its own host names only. FIX: open http://localhost:PORT, or start it with --allow-host NAME "
                    "for a proxy that keeps its own host name.")
        origin = self.headers.get("Origin")
        if origin is not None and (origin == "null" or (urlparse(origin).netloc or "").lower() != host):
            return (f"WHAT: a request from another site ({origin}). WHY: only this server's own page may use its "
                    "API. FIX: use the page this server serves.")
        if method == "POST":
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json" and not (path == "/api/upload" and self.headers.get("X-Filename") is not None):
                return "WHAT: a request the page does not send. FIX: use the page this server serves."
        return None

    def log_message(self, fmt, *args):             # the page loads only; the polling would be noise
        if self.path.split("?")[0] in ("/", "/index.html"):
            sys.stderr.write(f"{self.log_date_time_string()} {self.client_address[0]} {fmt % args}\n")

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, default=str).encode(), "application/json")

    def _body(self, limit: int) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise A.InputError(f"WHAT: the upload is {n / 2 ** 20:.0f} MB. FIX: keep it under {limit // 2 ** 20} MB.")
        return self.rfile.read(n) if n else b""

    def _payload(self) -> dict:
        raw = self._body(MAX_JSON)
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            raise A.InputError("WHAT: the request is not JSON. FIX: send the page's form.") from None

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def _route(self, method: str) -> None:
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        parts = [p for p in url.path.split("/") if p]
        app = self.app
        try:
            if method == "GET" and url.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if method == "GET" and len(parts) == 2 and parts[0] == "img":
                f = (STATIC / "img" / parts[1]).resolve()
                kind = CONTENT_TYPES.get(f.suffix.lower())
                if kind is None or f.parent != (STATIC / "img").resolve() or not f.is_file():
                    return self._json({"error": "not found"}, 404)
                return self._send(200, f.read_bytes(), kind)
            if not parts or parts[0] != "api":
                return self._json({"error": "not found"}, 404)
            why = self._refused(method, url.path)
            if why:
                return self._json({"error": why}, 403)
            what, arg = (parts[1] if len(parts) > 1 else ""), (parts[2] if len(parts) > 2 else "")
            if method == "GET" and what == "config":
                return self._json(app.config())
            if method == "GET" and what == "settings":            # the interpretation settings, their defaults and help
                from petroharness.well import settings as T
                return self._json(T.schema())
            if method == "POST" and what == "preview":            # Petrophys on this well with these settings
                return self._json(A.preview(self._payload(), app.store.cache))
            if method == "GET" and what == "samples":             # Petrophys's sample wells, for a one-click start
                return self._json(list(A.samples()))
            if method == "GET" and what == "las":
                return self._json(A.las_info(q.get("path")))
            if method == "GET" and what == "tops":
                return self._json(A.tops_info(q.get("path"), q.get("las") or None, q.get("unit") or None))
            if method == "POST" and what == "upload":
                kind = q.get("kind", "las")
                if kind not in ("las", "tops", "notes", "zones"):
                    raise A.InputError("WHAT: upload kind. FIX: kind=las, kind=tops, kind=zones or kind=notes.")
                path = app.store.upload(kind, self.headers.get("X-Filename") or "", self._body(MAX_UPLOAD))
                if kind == "las":
                    try:
                        return self._json(A.las_info(path))
                    except A.InputError:
                        path.unlink(missing_ok=True)
                        raise
                if kind == "notes":
                    return self._json(A.notes_info(path))
                return self._json({"path": str(path), "name": path.name})
            if method == "GET" and what == "notes":
                return self._json(A.notes_info(q.get("path")))
            if method == "GET" and what == "zones":                # the user's zones, and what is wrong in them
                return self._json(A.zones_info(q.get("path"), q.get("las") or None))
            if method == "POST" and what == "ask":
                return self._json({"id": app.submit(self._payload()).id})
            if method == "POST" and what == "stop":
                return self._json(app.stop(arg))
            if method == "GET" and what == "job":
                return self._json(app.job_view(arg, int(q.get("since", 0) or 0)))
            if method == "GET" and what == "runs":
                return self._json(app.runs())
            if method == "GET" and what == "run" and len(parts) == 5 and parts[3] == "figures":
                return self._send(200, app.store.figure(arg, parts[4]).read_bytes(), "image/png")
            if method == "GET" and what == "run" and len(parts) == 4 and parts[3] == "audit":
                return self._send(200, app.audit(arg).encode(), "text/markdown; charset=utf-8",
                                  {"Content-Disposition": f'inline; filename="{arg}-audit.md"'})
            if method == "GET" and what == "run" and len(parts) == 4 and parts[3] == "lineage":
                return self._json(app.lineage(arg))
            if method == "GET" and what == "run" and len(parts) == 4 and parts[3] == "conversation":
                return self._json(app.conversation(arg))
            if method == "GET" and what == "run" and len(parts) == 4 and parts[3] in ("logview", "logdata"):
                return self._json(app.logs(arg, parts[3], q))        # the log viewer
            if method == "GET" and what == "run" and len(parts) == 4:
                path = app.store.file(arg, parts[3])
                ctype = "text/markdown; charset=utf-8" if path.suffix == ".md" else "application/json"
                return self._send(200, path.read_bytes(), ctype,
                                  {"Content-Disposition": f'inline; filename="{arg}-{path.name}"'})
            if method == "GET" and what == "run":
                job = app.jobs.get(arg)
                return self._json(job.record() if job is not None else app.store.load(arg))
            if method == "POST" and what == "rate":
                body = self._payload()
                rating = app.store.rate(arg, body.get("verdict", ""), body.get("note", ""))
                if arg in app.jobs:
                    app.jobs[arg].rating = rating
                return self._json(rating)
            return self._json({"error": "not found"}, 404)
        except KeyError as exc:                     # its message as raised (str() of a KeyError is its repr)
            said = exc.args[0] if exc.args and isinstance(exc.args[0], str) else "not found"
            return self._json({"error": said}, 404)
        except (ValueError, LookupError, OSError) as exc:
            return self._json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001  (an unexpected failure is answered as a 500, the server goes on)
            traceback.print_exc()
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


class _Server6(_Server):
    address_family = socket.AF_INET6


def make_servers(app: App, host: str = "127.0.0.1", port: int = 7860, allow_hosts=()) -> list:
    """The HTTP servers for the app: one on `host`; for "localhost", one on 127.0.0.1 and one on ::1 (where the
    machine has IPv6), since clients that resolve localhost to ::1 first would otherwise find nothing. `allow_hosts`:
    further host names a loopback server answers (a proxy that keeps its own host name)."""
    handler = type("BoundHandler", (Handler,), {"app": app, "loopback": host in LOOPBACK,
                                                "allow_hosts": frozenset(h.strip().lower() for h in allow_hosts if h.strip())})
    if host != "localhost":
        return [(_Server6 if ":" in host else _Server)((host, port), handler)]
    first = _Server(("127.0.0.1", port), handler)
    out = [first]
    try:
        out.append(_Server6(("::1", first.server_address[1]), handler))
    except OSError:
        pass
    return out


def _url(address) -> str:
    host, port = address[0], address[1]
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="petroharness ui", description="The web UI: ask about a LAS file in the browser, "
                                 "with live progress, saved runs and replay.")
    ap.add_argument("--host", default="127.0.0.1", help="the address to listen on (default 127.0.0.1; localhost: "
                                                        "127.0.0.1 and ::1; 0.0.0.0: every interface)")
    ap.add_argument("--port", type=int, default=7860, help="the port (default 7860)")
    ap.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                    help="a further host name a server on a loopback address answers (a proxy that keeps its own "
                         "host name); repeatable")
    ap.add_argument("--runs", type=Path, default=Path("petroharness-ui-runs"),
                    help="the folder for saved runs and uploads (default ./petroharness-ui-runs)")
    ap.add_argument("--workers", type=int, default=4, help="questions answered at once (default 4); more wait")
    ap.add_argument("--model", help="the served model's name, for any chat model on an OpenAI-compatible endpoint "
                                    "(default: K2-Horizon-7B)")
    ap.add_argument("--model-card", help="a model card: a YAML file (docs/MODELS.md), or a packaged card's name")
    ap.add_argument("--model-url", help="the model endpoint(s), comma-separated (default: PETROHARNESS_MODEL_URL)")
    ap.add_argument("--open", action="store_true", help="open the UI in your browser once it listens (what "
                                                        "`petroharness --launch-ui` does)")
    return ap


def page_url(host: str, port: int) -> str:
    """The address to open in a browser on this machine: localhost for a loopback or every-interface server."""
    return f"http://localhost:{port}" if host in LOOPBACK | {"0.0.0.0", "::", ""} else _url((host, port))


def open_browser(url: str, env=None, platform: str | None = None, opener=None) -> bool:
    """Open url in the user's browser where there is one to open: a desktop (macOS, Windows, a Linux display) or a
    BROWSER the environment names (an editor's remote terminal sets one that opens the page on the editor's machine).
    On a Linux machine with no display it opens nothing, since Python's webbrowser would start a text browser in the
    terminal: the caller says where to point a browser instead."""
    import webbrowser
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if platform.startswith("linux") and not any(env.get(k) for k in ("BROWSER", "DISPLAY", "WAYLAND_DISPLAY")):
        return False
    try:
        return bool((opener or webbrowser.open)(url))
    except Exception:                               # noqa: BLE001  (no browser to open: the address is printed)
        return False


def main(argv: list | None = None) -> int:
    args = parser().parse_args(argv)
    urls = [u for u in args.model_url.split(",") if u.strip()] if args.model_url else None
    try:
        app = App(args.runs, workers=args.workers, urls=urls, model=args.model, model_card=args.model_card)
    except ValueError as exc:                       # a model card that is missing or wrong
        print(f"petroharness ui: {exc}", file=sys.stderr)
        return 2
    try:
        servers = make_servers(app, args.host, args.port, args.allow_host)
    except OSError as exc:
        print(f"petroharness ui: cannot listen on {args.host}:{args.port} ({exc}). FIX: choose another --port.",
              file=sys.stderr)
        return 2
    where = ", ".join(_url(s.server_address) for s in servers)
    print(f"PetroHarness UI on {where}", file=sys.stderr)
    if args.host not in LOOPBACK:
        print(f"  listening on {args.host}: anyone who can reach this port can ask questions and read the files this "
              "server can read; listen on 127.0.0.1 and forward the port where you can", file=sys.stderr)
    print(f"  runs: {app.store.root}; workers: {app.workers}; model: {app.label} ({app.endpoints.model}); endpoints: "
          f"{', '.join(app.endpoints.urls) or 'none (set PETROHARNESS_MODEL_URL or --model-url)'}", file=sys.stderr,
          flush=True)
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    if args.open:
        url = page_url(args.host, servers[0].server_address[1])
        if not open_browser(url):
            print(f"  open {url} in your browser (from another machine: ssh -L "
                  f"{servers[0].server_address[1]}:localhost:{servers[0].server_address[1]} HOST, then the same address)",
                  file=sys.stderr, flush=True)
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
