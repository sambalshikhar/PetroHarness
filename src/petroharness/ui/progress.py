"""Live progress: the model client that reports each call as it happens, and what each call says.

`Observed` wraps the client the harness builds (petroharness.llm.LLM, or a stand-in in tests) and passes every call
through unchanged: the same arguments in, the same reply out. Around each call it emits two events: `call` when the
request leaves and `reply` when the answer is back, with its timing and token counts and what the reply holds, read
with the harness's own parsers (the READ call's topics; a step's focus, actions and claim edits; the settle step's
edits; the writer's draft). The prompts are also read for the results they show the model: each opened result is
emitted once, as the model read it (`results` events).
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from typing import Any

TEXT_CHARS = 1200          # a draft or an unreadable reply, in an event
EDIT_CHARS = 280           # a claim edit's text, in an event

# A result block in a prompt: "[E7] <its text>" at the start of a message, after a blank line, or right under the
# header that lists results (the first look, NEW, ALL RESULTS). It runs to the next blank line.
_BLOCK = re.compile(r"(?:\A|\n\n|(?:FIRST LOOK[^\n]*|NEW \(from step \d+\)|ALL RESULTS[^\n]*):\n)\[(E\d+)\] ")
_DIGEST_TAIL = re.compile(r"\n  \(\d+ more lines: get E\d+ with find: [^\n]*\)$")
_OPENED_BEFORE = re.compile(r"^\(opened before: .{1,90}?\) ")
# not a result's text: a pointer to one shown above, a get or find that matched nothing or some lines, the lines the
# writer is shown for a claim
_NOT_A_RESULT = re.compile(r"^(?:shown above in this NEW|nothing in E\d+ matches)|\((?:find: [^\n]*|for C\d+(?:: [^\n]*)?)\)$")


def kind_of(stage: str) -> tuple[str, int | None]:
    """A call's stage name as (kind, number): ('read', None), ('step', 3), ('settle', None), ('writer', None),
    ('repair', 1); anything else ('other', None)."""
    if stage.startswith("read"):
        return "read", None
    if stage == "settle" or stage.startswith("step_0_"):          # the settle step's reply repair is step_0_fix
        return "settle", None
    m = re.match(r"step_(\d+)", stage)
    if m:
        return "step", int(m.group(1))
    if stage.startswith("writer"):
        return "writer", None
    m = re.match(r"repair_(\d+)", stage)
    if m:
        return "repair", int(m.group(1))
    return "other", None


def results_in(text: str) -> dict:
    """The opened results a prompt shows: {id: (text, digest)}; digest is True for a shortened result (the full text
    is fetched with get). A result asked for with find, or said to be shown above, is not one."""
    out: dict = {}
    for m in _BLOCK.finditer(text or ""):
        start = m.start(1) - 1
        end = text.find("\n\n", start)
        block = text[start:end if end >= 0 else len(text)]
        body = _OPENED_BEFORE.sub("", block[len(m.group(1)) + 3:], count=1)
        first = body.split("\n", 1)[0]
        if not body.strip() or _NOT_A_RESULT.search(first):
            continue
        digest = bool(_DIGEST_TAIL.search(body))
        eid = m.group(1)
        if eid not in out or _better((body, digest), out[eid]):
            out[eid] = (body, digest)
    return out


def _better(new: tuple, old: tuple) -> bool:
    """A whole result beats a digest; between two of a kind, the longer."""
    if new[1] != old[1]:
        return old[1]
    return len(new[0]) > len(old[0])


def _action_text(action) -> str:
    from petroharness.agent.loop import action_text, coerce_action
    got = coerce_action(action, True)
    if got is None:
        return f"(not an action: {str(action)[:120]})"
    return action_text(got).strip()


def edit_view(e) -> dict:
    """A claim edit as the page shows it."""
    if not isinstance(e, dict):
        return {"op": "?", "text": str(e)[:EDIT_CHARS]}
    out = {"op": str(e.get("op", "")), "id": e.get("id"), "point": e.get("point"), "grade": e.get("grade"),
           "text": str(e.get("text") or e.get("why") or "")[:EDIT_CHARS]}
    if isinstance(e.get("ev"), list):
        out["ev"] = [str(x) for x in e["ev"]][:12]
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def read_reply_of(stage: str, text: str) -> dict:
    """What a reply says, for the page: read with the harness's own parsers (petroharness.agent.loop)."""
    from petroharness.agent import loop as L
    kind, _ = kind_of(stage)
    text = text or ""
    if kind == "read":
        got = L._reading(text)
        return {"topics": got["topics"], "named": got["named"]} if got else {"unreadable": True,
                                                                                 "text": text[:TEXT_CHARS]}
    if kind in ("step", "settle"):
        if not text.strip():
            return {"empty": True}
        try:
            obj = L.read_reply(text)
        except ValueError:
            return {"unreadable": True, "text": text[:TEXT_CHARS]}
        out: dict = {"edits": [edit_view(e) for e in (obj.get("edits") or []) if e]}
        if kind == "step":
            out["focus"] = str(obj.get("focus") or "")[:300]
            out["next"] = [_action_text(a) for a in (obj.get("next") or [])]
            out["done"] = bool(obj.get("done"))
            if obj.get("points"):
                out["points"] = [str(p.get("text", p) if isinstance(p, dict) else p)[:240] for p in obj["points"]][:6]
            for key in ("asks", "intent"):
                if obj.get(key):
                    out[key] = str(obj[key])[:240]
        return out
    if kind in ("writer", "repair"):
        return {"draft": text[:TEXT_CHARS], "chars": len(text)}
    return {"text": text[:TEXT_CHARS]}


class Observed:
    """The harness's model client with every call reported to `emit` (an event dict), behaviour unchanged."""

    def __init__(self, inner, emit: Callable[[dict], None]):
        self.inner = inner
        self.emit = emit
        self.calls = 0
        self.results: dict = {}                     # id -> (text, digest): the best seen so far
        self._scanned: set = set()

    def __getattr__(self, name: str) -> Any:        # cfg, client, replays_reasoning, ...: the inner client's
        if "inner" not in self.__dict__:
            raise AttributeError(name)
        return getattr(self.__dict__["inner"], name)

    def chat(self, stage: str, messages: list, usage, max_tokens: int, *args, **kwargs) -> str:
        self.calls += 1
        n = self.calls
        self._scan(stage, messages)
        kind, number = kind_of(stage)
        event = {"kind": "call", "stage": stage, "type": kind, "n": n}
        if number is not None:
            event["number"] = number
        if kind == "repair" and messages and messages[-1].get("role") == "user":
            event["findings"] = str(messages[-1].get("content") or "")[:4000]       # the checker's findings
        self.emit(event)
        logged = len(getattr(usage, "log", []) or [])
        t0 = time.perf_counter()
        try:
            text = self.inner.chat(stage, messages, usage, max_tokens, *args, **kwargs)
        except Exception as exc:                    # reported, then raised unchanged
            self.emit({"kind": "reply", "stage": stage, "type": kind, "n": n, "seconds": round(time.perf_counter() - t0, 1),
                       "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
            raise
        reply = {"kind": "reply", "stage": stage, "type": kind, "n": n, "seconds": round(time.perf_counter() - t0, 1)}
        log = getattr(usage, "log", []) or []
        if len(log) > logged:
            entry = log[-1]
            for key in ("prompt_tokens", "completion_tokens", "finish_reason", "discarded"):
                if entry.get(key) is not None:
                    reply[key] = entry[key]
        try:
            reply.update(read_reply_of(stage, text))
        except Exception as exc:  # noqa: BLE001  (the page's reading of a reply never fails the run)
            reply["unreadable"] = f"{type(exc).__name__}: {exc}"
        self.emit(reply)
        return text

    def _scan(self, stage: str, messages: list) -> None:
        """New or fuller results in this request's prompts, emitted once each."""
        fresh = []
        for m in messages:
            content = m.get("content") if isinstance(m, dict) else None
            if m.get("role") != "user" or not isinstance(content, str):
                continue
            key = hashlib.sha1(content.encode("utf-8", "replace")).hexdigest()
            if key in self._scanned:
                continue
            self._scanned.add(key)
            for eid, got in results_in(content).items():
                old = self.results.get(eid)
                if old is None or _better(got, old):
                    self.results[eid] = got
                    fresh.append(eid)
        if fresh:
            order = sorted(dict.fromkeys(fresh), key=lambda e: int(e[1:]))
            self.emit({"kind": "results", "stage": stage, "items": [
                {"id": e, "title": self.results[e][0].split("\n", 1)[0][:200], "text": self.results[e][0],
                 "digest": self.results[e][1]} for e in order]})
