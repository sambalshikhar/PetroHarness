"""The saved runs: one folder per question under the runs folder (petroharness ui --runs, default
./petroharness-ui-runs).

    <runs>/<run id>/run.json     the inputs, the live events, the answer, what the page shows of the trace, the rating
    <runs>/<run id>/answer.md    the answer with its header (written by petroharness.ask)
    <runs>/<run id>/trace.json   the full trace (written by petroharness.ask)
    <runs>/uploads/              uploaded LAS and tops files
    <runs>/.cache/               interpreted wells, shared by every run (each run's .cache links here)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import threading
from pathlib import Path

RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
VERDICTS = ("good", "partly", "wrong")
LAS_SUFFIXES = (".las",)
TOPS_SUFFIXES = (".csv", ".tsv", ".txt", ".xlsx", ".xls")


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.uploads = self.root / "uploads"
        self.cache = self.root / ".cache"
        self._lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)

    # runs ---------------------------------------------------------------------------------------------------------
    def new_id(self) -> str:
        return dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)

    def folder(self, run_id: str) -> Path:
        if not RUN_ID.fullmatch(str(run_id)):
            raise KeyError(f"no run {run_id!r}")
        return self.root / run_id

    def prepare(self, run_id: str) -> Path:
        """The run's folder, its .cache linked to the shared one (an interpreted well is reused by later questions
        about the same LAS; the cache is keyed by the file's content and written atomically)."""
        out = self.folder(run_id)
        out.mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(exist_ok=True)
        link = out / ".cache"
        if not link.exists() and not link.is_symlink():
            try:
                link.symlink_to(os.path.relpath(self.cache, out), target_is_directory=True)
            except OSError:                         # no symlinks here: the run keeps its own cache
                pass
        return out

    def save(self, record: dict) -> None:
        out = self.folder(record["id"])
        out.mkdir(parents=True, exist_ok=True)
        self._write(out / "run.json", record)

    def load(self, run_id: str) -> dict:
        path = self.folder(run_id) / "run.json"
        if not path.is_file():
            raise KeyError(f"no run {run_id!r}")
        return json.loads(path.read_text())

    def file(self, run_id: str, name: str) -> Path:
        if name not in ("answer.md", "trace.json"):
            raise KeyError(name)
        path = self.folder(run_id) / name
        if not path.is_file():
            raise KeyError(f"{run_id} has no {name}")
        return path

    def figure(self, run_id: str, name: str) -> Path:
        """One figure of a run's answer (petroharness.figures writes them as figure_<n>_<kind>.png)."""
        if not re.fullmatch(r"figure_\d+_[a-z]+(_[a-z]+)*\.png|overview\.png", str(name)):
            raise KeyError(name)
        path = self.folder(run_id) / "figures" / name
        if not path.is_file():
            raise KeyError(f"{run_id} has no {name}")
        return path

    def history(self, limit: int = 500) -> list:
        """The saved runs, newest first: what the run list shows."""
        out = []
        for path in sorted(self.root.glob("*/run.json"), reverse=True)[:limit]:
            try:
                r = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            out.append(brief(r))
        return out

    def rate(self, run_id: str, verdict: str, note: str) -> dict:
        verdict = str(verdict or "").strip().lower()
        if verdict and verdict not in VERDICTS:
            raise ValueError(f"WHAT: verdict {verdict!r}. FIX: use one of {', '.join(VERDICTS)}.")
        with self._lock:
            rec = self.load(run_id)
            rec["rating"] = {"verdict": verdict, "note": str(note or "")[:4000],
                             "rated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            self.save(rec)
        return rec["rating"]

    def interrupted(self) -> int:
        """Runs a stopped server left queued or running: marked interrupted (their events are kept)."""
        n = 0
        for path in self.root.glob("*/run.json"):
            try:
                rec = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if rec.get("status") in ("queued", "running"):
                rec["status"], rec["error"] = "interrupted", "the server stopped before this run finished"
                self._write(path, rec)
                n += 1
        return n

    # uploads ------------------------------------------------------------------------------------------------------
    def upload(self, kind: str, name: str, body: bytes) -> Path:
        """An uploaded file, kept under uploads/ by its own name (a different file of the same name gets a suffix)."""
        suffixes = LAS_SUFFIXES if kind == "las" else TOPS_SUFFIXES
        stem, suffix = Path(str(name or "")).stem, Path(str(name or "")).suffix.lower()
        if suffix not in suffixes:
            raise ValueError(f"WHAT: {name!r} is not a {'LAS' if kind == 'las' else 'tops'} file. FIX: upload a file "
                             f"ending in {', '.join(suffixes)}.")
        if not body:
            raise ValueError(f"WHAT: {name!r} is empty. FIX: upload the file again.")
        stem = re.sub(r"[^A-Za-z0-9_.-]", "_", stem).strip("._") or "upload"
        self.uploads.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(body).hexdigest()[:8]
        path = self.uploads / f"{stem}{suffix}"
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()[:8] != digest:
            path = self.uploads / f"{stem}_{digest}{suffix}"
        path.write_bytes(body)
        return path

    @staticmethod
    def _write(path: Path, record: dict) -> None:
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(record, indent=1, default=str))
        os.replace(tmp, path)


def brief(r: dict) -> dict:
    """A run as the run list shows it."""
    i = r.get("inputs") or {}
    return {"id": r.get("id"), "status": r.get("status"), "question": i.get("question", ""),
            "las": Path(str(i.get("las") or "")).name, "las_path": i.get("las"), "label": r.get("label", ""),
            "created": r.get("created"), "elapsed": r.get("elapsed"),
            "verdict": (r.get("rating") or {}).get("verdict", ""),
            "turn": (r.get("conversation") or {}).get("turn") or 1}
