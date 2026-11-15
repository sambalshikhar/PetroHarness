"""The harness's components (agent/components/README.md): every fixed text the model reads belongs to one of
C1-C10; versions, slot filling, and per-call attribution of each message to its components."""
from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]          # the package: frames are named relative to it
HERE = Path(os.environ.get("PETROHARNESS_COMPONENTS") or Path(__file__).resolve().parent / "components")   # another set: an A/B of versions
COMPONENTS = {"C1": "system", "C2": "guardrails", "C3": "memory", "C4": "tools", "C5": "orchestration",
              "C6": "skills", "C7": "scripts", "C8": "middleware", "C9": "answer", "C10": "reading"}
SLOT = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
MIN_MATCH = 24                     # an entry shorter than this is not searched for (too likely to match by chance)


def folder(cid: str) -> Path:
    return HERE / f"{cid}_{COMPONENTS[cid]}"


@lru_cache(maxsize=None)
def meta(cid: str) -> dict:
    return yaml.safe_load((folder(cid) / "component.yaml").read_text()) or {}


@lru_cache(maxsize=None)
def text(cid: str, entry: str):
    """An entry's exact text (a .json entry: its list of strings)."""
    path = folder(cid) / meta(cid)["texts"][entry]
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw) if path.suffix == ".json" else raw


def fill(cid: str, entry: str, **values) -> str:
    """The entry with each {name} slot replaced by its value, in one pass; a slot without a value stays as written."""
    return fill_text(text(cid, entry), **values)


def fill_text(template: str, **values) -> str:
    return SLOT.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


def _files(cid: str) -> list:
    m = meta(cid)
    out = [folder(cid) / "component.yaml"] + [folder(cid) / f for f in (m.get("texts") or {}).values()]
    for pat in m.get("frames") or []:
        out += sorted(REPO.glob(pat))
    return sorted({p for p in out if p.is_file()})


@lru_cache(maxsize=None)
def version(cid: str) -> str:
    h = hashlib.sha1()
    for p in _files(cid):
        h.update(str(p.relative_to(HERE) if HERE in p.parents else p.relative_to(REPO)).encode())
        h.update(b"\0")
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def versions() -> dict:
    return {cid: version(cid) for cid in COMPONENTS}


# --- attribution ---------------------------------------------------------------------------------------------------------

def strings(value) -> list:
    """An entry's strings: itself, a list's items, a dict's values (nested)."""
    if isinstance(value, str):
        return [value]
    items = value.values() if isinstance(value, dict) else value
    return [s for v in items for s in strings(v)]


@lru_cache(maxsize=4)
def catalog(skills: tuple = ()) -> list:
    """(cid, pieces) for every entry: a template's literal pieces between its slots (each searched on its own), longest
    first; list entries contribute each string. skills: the plugged library's guide lines (C6's texts are data, in the
    library: direction.Library.lines)."""
    out = []
    for cid in COMPONENTS:
        for entry in (meta(cid).get("texts") or {}):
            value = text(cid, entry)
            for t in strings(value):
                for piece in SLOT.split(t)[::2]:
                    if len(piece.strip()) >= MIN_MATCH:
                        out.append((cid, piece))
    out += [("C6", ln.strip()) for ln in skills if len(ln.strip()) >= MIN_MATCH]
    return sorted(set(out), key=lambda x: -len(x[1]))


@lru_cache(maxsize=1)
def headers() -> list:
    """(header text, cid): the frame headers whose section belongs to a component (C5's frames entry)."""
    return [(h, cid) for h, cid in (text("C5", "section_owners") or {}).items()] if "section_owners" in (
        meta("C5").get("texts") or {}) else []


def attribute(message: str, owner: str, skills: tuple = ()) -> list:
    """[[cid, version, start, end], ...]: every character of the message attributed, adjacent same-component characters
    merged. Component entries (and the plugged library's guide lines, skills) found in the text are theirs; the rest
    belongs to the nearest preceding frame header's component, else to the message's owner."""
    n = len(message)
    who = [None] * n
    for cid, piece in catalog(tuple(skills)):
        start = 0
        while True:
            i = message.find(piece, start)
            if i < 0:
                break
            if all(w is None for w in who[i:i + len(piece)]):
                who[i:i + len(piece)] = [cid] * len(piece)
            start = i + 1
    marks = sorted((m.start(), cid) for h, cid in headers() for m in re.finditer(re.escape(h), message)
                   if h.startswith("\n") or m.start() == 0 or message[m.start() - 1] == "\n")   # a header opens a line
    k, cur = 0, owner
    for i in range(n):
        while k < len(marks) and marks[k][0] <= i:
            cur = marks[k][1]
            k += 1
        if who[i] is None:
            who[i] = cur
    spans = []
    for i, cid in enumerate(who):
        if spans and spans[-1][0] == cid and spans[-1][3] == i:
            spans[-1][3] = i + 1
        else:
            spans.append([cid, version(cid), i, i + 1])
    return spans


# --- the call record ---------------------------------------------------------------------------------------------------

# the component owning a call's unheaded text, by stage and message position (an assistant turn is the model's own text)
OWNERS = ((re.compile(r"read(_retry)?$"), ("C1", "C5")),
          (re.compile(r"step_\d+(_retry)?$"), ("C1", "C5")), (re.compile(r"step_\d+_fix$"), ("C2",)),
          (re.compile(r"step_1_points$"), ("C1", "C5", "C3", "C5")), (re.compile(r"settle$"), ("C1", "C5")),
          (re.compile(r"writer(_retry|_again)?$"), ("C9", "C9")), (re.compile(r"repair_\d+(_again)?$"), ("C9", "C9", "C3", "C2")),
          (re.compile(r"figures(_retry)?$"), ("C9", "C9")))


def owners(stage: str, n: int) -> list:
    own = next((o for pat, o in OWNERS if pat.match(stage)), ())
    return [own[i] if i < len(own) else "C3" for i in range(n)]


def record_call(trace: dict, stage: str, messages: list, skills: tuple = ()) -> None:
    """One model call's attribution, each message (role, content) with the component owning its unheaded text."""
    trace.setdefault("calls", []).append({"stage": stage, "messages": [
        {"role": m["role"], "segments": attribute(m["content"] or "", o, skills)}
        for m, o in zip(messages, owners(stage, len(messages)))]})


def recording(llm, trace: dict, library=None) -> None:
    """This question's client records every successful call's attribution in its trace (the request is unchanged);
    library: the plugged skill library (None: none), whose guide lines are C6's."""
    chat = llm.chat
    skills = library.lines if library is not None else ()

    def recorded(stage, messages, *args, **kwargs):
        out = chat(stage, messages, *args, **kwargs)
        record_call(trace, stage, messages, skills)
        return out
    llm.chat = recorded
