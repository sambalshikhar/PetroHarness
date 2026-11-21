"""The session log: one append-only file of events per conversation (log.jsonl), and the large texts they name, kept
once each under their SHA-256 (blobs/). The log is the record a conversation is resumed, audited and replayed from;
everything else in a session folder can be rebuilt from it and the well's files."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path


class SessionLog:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        (self.folder / "blobs").mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "log.jsonl"
        self.seq = len(self.events())

    def append(self, kind: str, turn: int = 0, /, **data) -> dict:
        """One event: {seq, time (UTC), turn (0: the session itself), type, ...}. `kind` and `turn` are positional, so
        an event's own fields may carry those names."""
        self.seq += 1
        event = {"seq": self.seq, "time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 "turn": turn, "type": kind, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
        return event

    def events(self, kind: str | None = None) -> list:
        if not self.path.exists():
            return []
        out = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return out if kind is None else [e for e in out if e["type"] == kind]

    def blob(self, text: str) -> str:
        """Keep a text once; -> its SHA-256 (the name events refer to it by)."""
        sha = hashlib.sha256(text.encode()).hexdigest()
        path = self.folder / "blobs" / sha
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        return sha

    def read(self, sha: str) -> str:
        return (self.folder / "blobs" / sha).read_text(encoding="utf-8")
