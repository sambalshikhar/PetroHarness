"""Record and replay at the model boundary: a run's model calls saved as a tape and replayed, the proof that a
changed harness behaves exactly as before (tests/agent/test_golden_tapes.py)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class TapeMismatch(AssertionError):
    """A request the replayed harness sent differs from the recorded one (or the tape ran out, or calls were left)."""


def _plain(obj: Any) -> Any:
    """A request as plain JSON values (the SDK accepts dicts, lists, strings and numbers; anything else as str)."""
    return json.loads(json.dumps(obj, default=str))


def _reply(resp) -> dict:
    ch = resp.choices[0]
    msg = ch.message
    calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments} for c in (msg.tool_calls or [])]
    u = resp.usage
    return {"content": msg.content, "tool_calls": calls, "finish_reason": ch.finish_reason,
            "reasoning": getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None),
            "usage": None if u is None else {"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
                                             "total_tokens": getattr(u, "total_tokens", None)}}


def _response(rec: dict):
    """A recorded reply as the SDK's response object (the attributes the harness reads)."""
    r = rec["reply"]
    calls = [SimpleNamespace(id=c["id"], type="function", function=SimpleNamespace(name=c["name"], arguments=c["arguments"]))
             for c in r.get("tool_calls") or []] or None
    msg = SimpleNamespace(content=r.get("content"), tool_calls=calls, reasoning=r.get("reasoning"), reasoning_content=None)
    u = r.get("usage")
    usage = None if u is None else SimpleNamespace(**{k: v for k, v in u.items()})
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=r.get("finish_reason"))], usage=usage)


def record(llm, path: Path) -> list:
    """Wrap llm's client: every call is sent as usual and appended to path (JSON lines) and to the returned list."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    calls, lock, create = [], threading.Lock(), llm.client.chat.completions.create

    def recorded(**kwargs):
        resp = create(**kwargs)
        rec = {"n": len(calls), "request": _plain(kwargs), "reply": _reply(resp)}
        with lock:
            calls.append(rec)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        return resp

    llm.client.chat.completions.create = recorded
    return calls


def load(path: Path) -> list:
    """A tape (JSON lines; path.gz when only the compressed copy exists)."""
    path = Path(path)
    if not path.exists() and Path(f"{path}.gz").exists():
        path = Path(f"{path}.gz")
    if path.suffix == ".gz":
        import gzip
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _diff(a: Any, b: Any, where: str = "") -> str:
    """The first place two plain values differ, as a path and the two values (shortened)."""
    if type(a) is not type(b):
        return f"{where or 'request'}: {type(a).__name__} against {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{where}.{k}: {'missing' if k not in a else 'present'} in the replay"
            d = _diff(a[k], b[k], f"{where}.{k}")
            if d:
                return d
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{where}: {len(a)} items against {len(b)} recorded"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _diff(x, y, f"{where}[{i}]")
            if d:
                return d
        return ""
    if a != b:
        sa, sb = str(a), str(b)
        i = next((k for k, (x, y) in enumerate(zip(sa, sb)) if x != y), min(len(sa), len(sb)))
        return f"{where}: differs at character {i}: ...{sa[max(0, i - 60):i + 60]!r} against ...{sb[max(0, i - 60):i + 60]!r}"
    return ""


class Replayer:
    """Serves a tape in order to one harness run; .left() names calls the run never made. collect: a request that
    differs is recorded in .diffs (call index, where) and still answered with the recorded reply (what an edit reaches)."""

    def __init__(self, tape: list, collect: bool = False):
        self.tape, self.i, self.collect, self.diffs, self.sent = list(tape), 0, collect, [], []

    def __call__(self, **kwargs):
        if self.i >= len(self.tape):
            raise TapeMismatch(f"call {self.i}: the replay sent a request the recording does not have "
                               f"({kwargs.get('model')}, {len(kwargs.get('messages') or [])} messages)")
        rec = self.tape[self.i]
        d = _diff(_plain(kwargs), rec["request"])
        if d and not self.collect:
            raise TapeMismatch(f"call {self.i}: {d}")
        if d:
            self.diffs.append((self.i, d))
        if self.collect:
            self.sent.append(_plain(kwargs))
        self.i += 1
        return _response(rec)

    def left(self) -> int:
        return len(self.tape) - self.i


def replay(llm, tape: list, collect: bool = False) -> Replayer:
    r = Replayer(tape, collect)
    llm.client.chat.completions.create = r
    return r


# --- comparing a replayed run with the recording ---------------------------------------------------------------------

VOLATILE = {"harness", "commit", "seconds", "traceback"}     # a run's trace keys that do not decide behaviour


def first_diff(a: Any, b: Any, where: str = "trace") -> str:
    """The first place two JSON values differ ("" when equal)."""
    if type(a) is not type(b):
        return f"{where}: {type(a).__name__} against {type(b).__name__}"
    if isinstance(a, dict):
        for k in list(dict.fromkeys(list(a) + list(b))):
            if k not in a or k not in b:
                return f"{where}.{k}: only in the {'recording' if k in b else 'replay'}"
            d = first_diff(a[k], b[k], f"{where}.{k}")
            if d:
                return d
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{where}: {len(a)} items against {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{where}[{i}]")
            if d:
                return d
        return ""
    return "" if a == b else f"{where}: {str(a)[:120]!r} against {str(b)[:120]!r}"


ADDED = ("calls", "components", "draft_chars")   # trace keys a recording may lack (per-call attribution, the
                                  #   component versions, the writer's draft length before repair): compared when the
                                  #   recording has them, skipped otherwise


def unstamped(trace: dict) -> dict:
    """A trace without its version stamps: the component versions (`components`) and the version in every attributed
    span of `calls` ([component, version, start, end] -> [component, start, end]). What is left decides behaviour;
    the stamps say which files produced it (they change whenever a framed file is edited or moved)."""
    out = {k: v for k, v in trace.items() if k != "components"}
    if isinstance(out.get("setup_parts"), dict):               # the setup's component versions: stamps too
        out["setup_parts"] = {k: v for k, v in out["setup_parts"].items() if k != "components"}
    if isinstance(out.get("calls"), list):
        out["calls"] = [{**c, "messages": [{**m, "segments": [[s[0], *s[2:]] for s in m.get("segments") or []]}
                                           for m in c.get("messages") or []]} for c in out["calls"]]
    return out


def compare_run(got: dict, want: dict, replayer: "Replayer | None" = None, fixed: "dict | None" = None,
                versions: bool = True) -> str:
    """"" when a replayed run ({"answer", "status", "trace"}) equals the recorded one: every recorded call made, the same
    answer and status, the same trace except its volatile keys and the usage log's timings. A switch the recording does
    not know must be off (a new component, not yet in use). A switch the code does not have (a removed one) passes
    only when the recording ran it at the value now fixed in code (`fixed`: removed switch -> value); a key of ADDED
    only the replay has is skipped. versions=False: the behaviour verdict alone (the version stamps left out, see
    unstamped); with the default the stamps must be equal too."""
    if got["trace"].get("error") and "TapeMismatch" in got["trace"]["error"] and not want["trace"].get("error"):
        return got["trace"]["error"][:400]
    if replayer is not None and replayer.left():
        return f"{replayer.left()} recorded calls never made"
    if got["answer"] != want["answer"]:
        return "answer: " + first_diff(got["answer"], want["answer"], "answer")
    if got["status"] != want["status"]:
        return f"status {got['status']} against {want['status']}"
    g = {k: v for k, v in json.loads(json.dumps(got["trace"], default=str)).items() if k not in VOLATILE}
    w = {k: v for k, v in want["trace"].items() if k not in VOLATILE}
    for t in (g, w):                  # the setup hash covers the commit: its parts are compared, less the volatile ones
        t.pop("setup", None)
        if isinstance(t.get("setup_parts"), dict):
            t["setup_parts"] = {k: v for k, v in t["setup_parts"].items() if k not in VOLATILE}
    timing = lambda log: [{k: v for k, v in e.items() if k != "seconds"} for e in log or []]
    g["usage"], w["usage"] = timing(g.get("usage")), timing(w.get("usage"))
    added = {k: v for k, v in (g.get("options") or {}).items() if k not in (w.get("options") or {})}
    if any(added.values()):
        return f"trace.options: new switches on: {sorted(k for k, v in added.items() if v)}"
    g["options"] = {k: v for k, v in (g.get("options") or {}).items() if k not in added}
    fixed = fixed or {}
    gone = {k: v for k, v in (w.get("options") or {}).items() if k not in g["options"]}
    off = sorted(k for k, v in gone.items() if k not in fixed or fixed[k] != v)
    if off:
        return "trace.options: switches gone from the code, recorded at another value: " + ", ".join(
            f"{k}={gone[k]!r} (fixed {fixed.get(k, 'unknown')!r})" for k in off)
    w["options"] = {k: v for k, v in (w.get("options") or {}).items() if k not in gone}
    for k in ADDED:
        if k in g and k not in w:
            del g[k]
    if not versions:
        g, w = unstamped(g), unstamped(w)
    return first_diff(g, w)
