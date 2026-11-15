"""The PetroHarness web UI: ask about a LAS file in the browser and follow the answer as it is made.

    petroharness ui [--host 127.0.0.1] [--port 7860] [--runs DIR] [--workers N] [--model NAME | --model-card CARD]
                    [--model-url URLS]

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
    GET  /api/las?path=             a LAS file's header (well, depth range and unit, curves)
    GET  /api/tops?path=[&las=&unit=]  the formations a tops file names, with the interval each would use
    POST /api/upload?kind=las|tops  the file's bytes, header X-Filename -> {path, ...}
    POST /api/ask                   the inputs (petroharness.ui.adapter) -> {id}
    GET  /api/job/<id>?since=N      status, the events from N on, then the answer and the result
    GET  /api/runs                  the runs, newest first (running and saved)
    GET  /api/run/<id>              a saved run in full
    GET  /api/run/<id>/answer.md | trace.json
    POST /api/rate/<id>             {verdict: good|partly|wrong, note}
"""

from __future__ import annotations

import argparse
import json
import os
import queue
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
    """The model id the harness asks the endpoints for: --model, else its model card's."""
    from petroharness.models import card_file, card_settings
    return model or str(card_settings(card_file(card, model))["model"])


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
        if follow:                                  # a follow-up: the next question of that run's conversation
            prev = self.jobs[follow].record() if follow in self.jobs else self.store.load(follow)
            if prev.get("status") != "done":
                raise A.InputError("WHAT: that question has no answer yet. FIX: wait for it to finish, then ask the "
                                   "follow-up.")
            root = (prev.get("conversation") or {}).get("root") or follow
            if not (self.store.folder(root) / "session" / "log.jsonl").is_file():
                raise A.InputError("WHAT: that run has no conversation to go on with (it was answered by an earlier "
                                   "version). FIX: ask its question again, then follow up on the new answer.")
            inputs = {**prev["inputs"], "question": inputs.get("question"), "follow": follow}
        kwargs = A.arguments(inputs) | self.choice  # wrong inputs are said now, not after the queue
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

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            with self._lock:
                if job.id in self.waiting:
                    self.waiting.remove(job.id)
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

    def _forget(self, keep: int = KEEP_FINISHED) -> None:
        """Finished jobs beyond the newest `keep` are served from their saved record."""
        with self._lock:
            done = sorted((j for j in self.jobs.values() if j.finished is not None), key=lambda j: j.finished)
            for j in done[:max(0, len(done) - keep)]:
                self.jobs.pop(j.id, None)

    def audit(self, run_id: str) -> str:
        """The audit trail of a run's answer (petroharness.evidence), from its conversation's session folder."""
        from petroharness.evidence import EvidenceGraph, audit
        rec = self.jobs[run_id].record() if run_id in self.jobs else self.store.load(run_id)
        conv = rec.get("conversation") or {}
        session = self.store.folder(conv.get("root") or run_id) / "session"
        if not (session / "log.jsonl").is_file() or not conv.get("turn"):
            raise KeyError(f"{run_id} has no audit trail (it has no answer yet, or was answered by an earlier version)")
        return audit.markdown(EvidenceGraph.from_log(session), int(conv["turn"]))

    def position(self, run_id: str) -> int | None:
        with self._lock:
            return self.waiting.index(run_id) + 1 if run_id in self.waiting else None

    def job_view(self, run_id: str, since: int) -> dict:
        job = self.jobs.get(run_id)
        if job is None:
            rec = self.store.load(run_id)
            return rec | {"events": rec.get("events", [])[since:], "n_events": len(rec.get("events", []))}
        out = job.view(since)
        out["queue_position"] = self.position(run_id)
        return out

    def runs(self) -> list:
        saved = self.store.history()
        live = {j.id: j for j in self.jobs.values() if j.finished is None}
        out = [brief(j.record()) | {"elapsed": j.elapsed()} for j in sorted(live.values(), key=lambda j: j.id, reverse=True)]
        return out + [r for r in saved if r["id"] not in live]

    def config(self) -> dict:
        from petroharness import __version__
        from petroharness.agent import direction
        from petroharness.agent.loop import MAX_STEPS
        with self._lock:
            running = sum(j.status == "running" for j in self.jobs.values())
            waiting = len(self.waiting)
        return {"version": __version__, "model": self.endpoints.model or "(stand-in model)", "label": self.label,
                "endpoints": self.endpoints.health() if self.model_factory is None else [],
                "workers": self.workers, "running": running, "queued": waiting, "runs": str(self.store.root),
                "max_steps": MAX_STEPS, "profiles": A.context_profiles(),
                "topics": {k: v.get("when", "") for k, v in direction.areas().items()},
                "verbs": verbs(), "petrophys_verbs": petrophys_verbs(),
                "skills_env": os.environ.get("PETROHARNESS_SKILLS", ""),
                "settings_env": os.environ.get("PETROHARNESS_DATA", "")}


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

class Handler(BaseHTTPRequestHandler):
    server_version = "PetroHarnessUI"
    app: App = None                                 # set by make_servers

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
            what, arg = (parts[1] if len(parts) > 1 else ""), (parts[2] if len(parts) > 2 else "")
            if method == "GET" and what == "config":
                return self._json(app.config())
            if method == "GET" and what == "las":
                return self._json(A.las_info(q.get("path")))
            if method == "GET" and what == "tops":
                return self._json(A.tops_info(q.get("path"), q.get("las") or None, q.get("unit") or None))
            if method == "POST" and what == "upload":
                kind = q.get("kind", "las")
                if kind not in ("las", "tops"):
                    raise A.InputError("WHAT: upload kind. FIX: kind=las or kind=tops.")
                path = app.store.upload(kind, self.headers.get("X-Filename") or "", self._body(MAX_UPLOAD))
                if kind == "las":
                    try:
                        return self._json(A.las_info(path))
                    except A.InputError:
                        path.unlink(missing_ok=True)
                        raise
                return self._json({"path": str(path), "name": path.name})
            if method == "POST" and what == "ask":
                return self._json({"id": app.submit(self._payload()).id})
            if method == "GET" and what == "job":
                return self._json(app.job_view(arg, int(q.get("since", 0) or 0)))
            if method == "GET" and what == "runs":
                return self._json(app.runs())
            if method == "GET" and what == "run" and len(parts) == 5 and parts[3] == "figures":
                return self._send(200, app.store.figure(arg, parts[4]).read_bytes(), "image/png")
            if method == "GET" and what == "run" and len(parts) == 4 and parts[3] == "audit":
                return self._send(200, app.audit(arg).encode(), "text/markdown; charset=utf-8",
                                  {"Content-Disposition": f'inline; filename="{arg}-audit.md"'})
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
        except KeyError as exc:
            return self._json({"error": str(exc).strip("'\"")}, 404)
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


def make_servers(app: App, host: str = "127.0.0.1", port: int = 7860) -> list:
    """The HTTP servers for the app: one on `host`; for "localhost", one on 127.0.0.1 and one on ::1 (where the
    machine has IPv6), since clients that resolve localhost to ::1 first would otherwise find nothing."""
    handler = type("BoundHandler", (Handler,), {"app": app})
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
    ap.add_argument("--runs", type=Path, default=Path("petroharness-ui-runs"),
                    help="the folder for saved runs and uploads (default ./petroharness-ui-runs)")
    ap.add_argument("--workers", type=int, default=4, help="questions answered at once (default 4); more wait")
    ap.add_argument("--model", help="the served model's name, for any chat model on an OpenAI-compatible endpoint "
                                    "(default: K2-Horizon-7B)")
    ap.add_argument("--model-card", help="a model card: a YAML file (docs/MODELS.md), or a packaged card's name")
    ap.add_argument("--model-url", help="the model endpoint(s), comma-separated (default: PETROHARNESS_MODEL_URL)")
    return ap


def main(argv: list | None = None) -> int:
    args = parser().parse_args(argv)
    urls = [u for u in args.model_url.split(",") if u.strip()] if args.model_url else None
    try:
        app = App(args.runs, workers=args.workers, urls=urls, model=args.model, model_card=args.model_card)
    except ValueError as exc:                       # a model card that is missing or wrong
        print(f"petroharness ui: {exc}", file=sys.stderr)
        return 2
    try:
        servers = make_servers(app, args.host, args.port)
    except OSError as exc:
        print(f"petroharness ui: cannot listen on {args.host}:{args.port} ({exc}). FIX: choose another --port.",
              file=sys.stderr)
        return 2
    where = ", ".join(_url(s.server_address) for s in servers)
    print(f"PetroHarness UI on {where}", file=sys.stderr)
    print(f"  runs: {app.store.root}; workers: {app.workers}; model: {app.label} ({app.endpoints.model}); endpoints: "
          f"{', '.join(app.endpoints.urls) or 'none (set PETROHARNESS_MODEL_URL or --model-url)'}", file=sys.stderr,
          flush=True)
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
