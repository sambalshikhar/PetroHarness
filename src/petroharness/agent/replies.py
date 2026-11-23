"""Reading the model's replies: a step's JSON (salvaged when it is not quite JSON), its edits and its actions,
the calls they name."""

from __future__ import annotations

import json
import re
from typing import Optional
from petroharness.llm import LLM, Usage
from petroharness.agent.claims import coerce_edit
from petroharness.agent.toolset import TOOLSET
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)


STEP_KEYS = {"asks", "points", "intent", "focus", "edits", "next", "done"}


TOOLS = set(TOOLSET.names())      # every tool the model is shown (agent/toolset.py); the reply parser reads no other


VERBS_RUN = {n for n in TOOLS if TOOLSET.get(n).verb}     # the verbs over Petrophys (each takes search and run)


_EDIT_KEY = re.compile(r'"op"\s*:')


_ACT_KEY = re.compile(r'\{\s*"(?:' + "|".join(sorted(TOOLS | {"get", "find", "guide", "calc", "tool", "action"}, key=len, reverse=True))
                      + r')"\s*:')


_WRAPS = ("step", "reply", "response", "answer", "output", "result")


# the tools by what users ask (docs/TOOLS.md), as the brief groups them: the record's lookups are members of their
# verb, and the verbs over Petrophys fill what they lack. Read from the tools' definitions (agent/toolset.py).
VERBS = TOOLSET.by_group()


# --- actions --------------------------------------------------------------------------------------------------------

def coerce_action(a, guides: bool = True) -> Optional[tuple]:
    """An action as models write it -> ("tool", name, args) | ("get", eid, find) | ("find", terms) | ("guide", facet)
    | ("calc", expression); None when it is no action this harness reads (a guide call with no skill library plugged:
    guides false).
    {"stats": {...}}, {"tool": "stats", "args": {...}} or {"tool": "stats", "curves": [...]}, {"runs": "NET_PAY"},
    {"stats": ["SW"]}, {"compare": ["PHIE", "PHIE_CC"]}, {"get": "E5", "find": "Z3"}, {"find": "Z3"}, {"guide": "porosity"},
    {"calc": "78.8 + 58.4"}."""
    if not isinstance(a, dict):
        return None
    d = dict(a)
    kind = str(d.pop("tool", "") or d.pop("action", "") or d.pop("type", "")).strip().lower()
    join = lambda v: ", ".join(map(str, v)) if isinstance(v, list) else str(v or "")
    if isinstance(d.get("get"), dict):                       # {"get": {"id": "E9", "find": "Z1"}}, {"get": {"E8": "Z19"}}
        g = d["get"]
        key = next((k for k in g if re.fullmatch(r"\s*E\d+\s*", str(k), re.I)), None) if len(g) == 1 else None
        g = {"id": key, "find": g[key]} if key else g
        d = {**{k: v for k, v in d.items() if k != "get"}, **g, "get": g.get("id") or g.get("item")}
    if "get" in d or kind == "get":
        eid = d.get("get") if "get" in d else (d.get("id") or d.get("item"))
        eid = (eid[0] if eid else "") if isinstance(eid, list) else eid
        key = re.fullmatch(r"\s*(?:section\s+)?([a-z_]+\.[a-z_]+)\s*", eid, re.I) if isinstance(eid, str) else None
        if key and "section" in TOOLS:
            return ("tool", "section", {"key": key.group(1)})      # an analyzer section's key: that section
        eid = str(eid or "").strip().strip("[]").upper()
        if not re.fullmatch(r"E\d+", eid):
            return None
        return ("get", eid, join(next((d[k] for k in ("find", "query", "terms", "zone", "where") if d.get(k)), "")))
    if "guide" in d or kind == "guide":
        if not guides:
            return None
        return ("guide", str(d.get("guide") or d.get("facet") or d.get("name") or "").strip())
    if "calc" in d or kind == "calc":
        e = d.get("calc") if "calc" in d else (d.get("expression") or d.get("expr"))
        e = (e.get("expression") or e.get("expr") or "") if isinstance(e, dict) else e
        return ("calc", str(e or "").strip())
    if ("find" in d or kind == "find") and not (TOOLS & set(d)):
        return ("find", join(d.get("find") if "find" in d else (d.get("query") or d.get("terms"))))
    named = _named_call(d) if kind not in TOOLS and not (TOOLS & set(d)) else None
    if named is not None:
        return named
    if "search" in d and kind not in TOOLS and not (TOOLS & set(d)):
        # a search of Petrophys's functions sent as an action of its own ({"search": "density correction"}, with its
        # verb as "where", or {"search": {"calculate": "..."}}): the verb's search; under the verb of its best match
        # when it names none (every lookup of a direct step unread sent it to an investigation)
        q, verb = d["search"], next((str(d[k]).strip().lower() for k in ("verb", "where", "in", "under")
                                     if str(d.get(k) or "").strip().lower() in VERBS_RUN), None)
        if isinstance(q, dict) and len(q) == 1 and str(next(iter(q))).strip().lower() in VERBS_RUN:
            verb, q = str(next(iter(q))).strip().lower(), next(iter(q.values()))
        words = join(list(q.values()) if isinstance(q, dict) else q).strip()
        if not words:
            return None
        from petroharness.agent.library.api import best_verb
        return ("tool", verb or best_verb(words), {"search": words})
    name = kind if kind in TOOLS else next((k for k in d if k in TOOLS), None)
    if name is None:
        return None
    body = d.pop(name, None) if name in d else None
    args = dict(d.get("args") or {}) if isinstance(d.get("args"), dict) else {k: v for k, v in d.items() if k != "args"}
    if isinstance(body, dict):
        args = {**body, **args}
    elif isinstance(body, str):
        args.setdefault(TOOLSET.main(name), body)
    elif isinstance(body, list):
        pair = TOOLSET[name].pair
        if pair and len(body) == 2:                     # the tool's two arguments, in order (Tool.pair)
            args.setdefault(pair[0], body[0]), args.setdefault(pair[1], body[1])
        else:
            args.setdefault("curves", body)
    return ("tool", name, args)


def _verb_objects() -> dict:
    """Each named object of the verbs that list objects (check, classify, summarize, calibrate) -> its verb."""
    from petroharness.agent.library.api import _objects
    out = {}
    for v in ("check", "classify", "summarize", "calibrate"):
        for o in _objects(v) if v in TOOLS else ():
            out.setdefault(str(o), set()).add(v)
    return {o: next(iter(vs)) for o, vs in out.items() if len(vs) == 1 and o not in TOOLS}


def _named_call(d: dict) -> Optional[tuple]:
    """A call named by what it calls rather than by a tool's key (88 lookups unread): a tool's name
    as run or search ({"run": "core_vs_log", "args": {...}}, {"search": "core_vs_log"}: that tool, the rest its
    arguments); a Petrophys function as run without its verb (the function's verb); a verb's object as the key
    ({"held_readings": {...}}: check's held_readings). None for anything else."""
    r = d.get("run")
    if isinstance(r, dict) and (isinstance(r.get("name"), str) or len(r) == 1):    # {"run": {"name": X, "args": {}}},
        name = r["name"] if isinstance(r.get("name"), str) else next(iter(r))        #   {"run": {X: {...}}}
        body = r.get("args") if isinstance(r.get("name"), str) else r[name]
        d = {**{k: v for k, v in d.items() if k != "run"}, "run": name, "args": body if isinstance(body, dict) else {}}
    rest = lambda *drop: {**(d.get("args") if isinstance(d.get("args"), dict) else {}),
                          **{k: v for k, v in d.items() if k not in ("args",) + drop}}
    objects = _verb_objects()
    for k in ("run", "search"):
        v = d.get(k)
        if isinstance(v, str) and v.strip() in TOOLS:
            return ("tool", v.strip(), rest(k))
        if isinstance(v, str) and v.strip() in objects:          # {"run": "held_readings"}: check's object
            return ("tool", objects[v.strip()], {TOOLSET.main(objects[v.strip()]): v.strip(), **rest(k)})
    if isinstance(d.get("run"), str) and d["run"].strip():
        from petroharness.agent.library.api import _is_function, lookup
        if _is_function(d["run"]):
            fn = lookup(d["run"])
            if fn.verb in VERBS_RUN:
                args = d.get("args") if isinstance(d.get("args"), dict) else {k: v for k, v in d.items() if k != "run"}
                return ("tool", fn.verb, {"run": fn.name, "args": args})
    hit = [k for k in d if k in objects and isinstance(d[k], (dict, list, str, type(None)))]
    if len(hit) == 1:
        body = d[hit[0]]
        args = dict(body) if isinstance(body, dict) else ({"curves": body} if isinstance(body, list) else {})
        verb = objects[hit[0]]
        return ("tool", verb, {TOOLSET.main(verb): hit[0], **args, **{k: v for k, v in d.items() if k != hit[0]}})
    return None


def split_actions(items) -> list:
    """The next items, one call each: an object that holds several calls ({"stats": {...}, "check": {...}}) is each of
    them, in its order (the second was read as an argument of the first, and ignored)."""
    out = []
    for a in items if isinstance(items, list) else []:
        if not isinstance(a, dict):
            out.append(a)
            continue
        ids = re.findall(r"E\d+", a["get"].upper()) if isinstance(a.get("get"), str) else []
        if len(ids) > 1:                                             # several results named in one get: each
            out += [{**a, "get": i} for i in ids]
            continue
        calls = [k for k, v in a.items() if (k in TOOLS and isinstance(v, dict)) or k == "calc"
                 or (k == "search" and not TOOLS & set(a))]          # a search beside no verb is a call of its own
        rest = {k: v for k, v in a.items() if k not in calls}         # (the words about them stay with each)
        out += [{k: a[k], **rest} for k in calls] if len(calls) > 1 else [a]
    return out


def action_text(act: tuple) -> str:
    if act[0] == "tool":
        return f"{act[1]} {json.dumps(act[2])}"
    return " ".join(str(x) for x in act)


# --- reading replies ------------------------------------------------------------------------------------------------

def _objects(text: str) -> list:
    dec, out, i = json.JSONDecoder(), [], 0
    while (j := text.find("{", i)) >= 0:
        try:
            obj, end = dec.raw_decode(text, j)
        except json.JSONDecodeError:
            i = j + 1
            continue
        if isinstance(obj, dict):
            out.append((j, end, obj))
        i = end
    return out


def _unwrap(obj: dict) -> dict:
    if not set(obj) & STEP_KEYS:
        for k in _WRAPS:
            if isinstance(obj.get(k), dict) and set(obj[k]) & STEP_KEYS:
                return obj[k]
    return obj


def _norm(obj: dict) -> dict:
    o = dict(obj)
    for k in ("edits", "next"):
        v = o.get(k)
        o[k] = [v] if isinstance(v, dict) else (v if isinstance(v, list) else [])
    d = o.get("done")
    o["done"] = d.strip().lower() in ("true", "yes", "1") if isinstance(d, str) else bool(d)
    return o


def read_reply(text: str) -> dict:
    """The reply's step object (the last one when a draft precedes it), holding every edit and action its text shows;
    ValueError otherwise."""
    for cand in dict.fromkeys([text or "", (text or "").replace("\\'", "'")]):
        steps = [(i, j, _unwrap(o)) for i, j, o in _objects(cand)]
        steps = [(i, j, o) for i, j, o in steps if set(o) & STEP_KEYS]
        if not steps:
            continue
        i, j, obj = steps[-1]
        obj = _norm(obj)
        rest = cand
        for i2, j2, _ in steps[:-1]:
            rest = rest[:i2] + " " * (j2 - i2) + rest[j2:]
        if len(_EDIT_KEY.findall(rest)) > len(obj["edits"]) or len(_ACT_KEY.findall(rest)) > len(obj["next"]):
            raise ValueError("the JSON object closes before edits or actions that follow it (or they are outside it)")
        return obj
    raise ValueError("the reply is not one readable JSON object (cut off, or invalid syntax: a missing comma, unquoted text)")


def salvage(text: str) -> dict:
    """Every complete inner object that is an edit or an action, and done when the reply says so."""
    s, dec, pos = text or "", json.JSONDecoder(), 0
    edits, acts = [], []
    while (j := s.find("{", pos)) >= 0:
        try:
            obj, end = dec.raw_decode(s, j)
        except json.JSONDecodeError:
            pos = j + 1
            continue
        if isinstance(obj, dict) and coerce_edit(obj):
            edits.append(obj)
            pos = end
        elif isinstance(obj, dict) and coerce_action(obj):
            acts.append(obj)
            pos = end
        else:
            pos = j + 1
    if not edits and not acts:
        raise ValueError("nothing readable")
    out = {"edits": edits, "next": acts, "done": bool(re.search(r'"done"\s*:\s*true', s)), "salvaged": True}
    a = re.search(r'"asks"\s*:\s*"((?:[^"\\]|\\.){8,})"', s)
    if a:
        out["asks"] = a.group(1)
    m = re.search(r'"points"\s*:\s*\[(.*?)\]', s, re.S)
    if m:
        out["points"] = re.findall(r'"((?:[^"\\]|\\.){8,})"', m.group(1))
    m = re.search(r'"intent"\s*:\s*"(\w+)"', s)
    if m:
        out["intent"] = m.group(1)
    return out


FIX = C.text("C2", "fix")


def complete_salvage(text: str, first: bool = False) -> Optional[dict]:
    """A reply that is not one JSON object, as its salvage, when the salvage holds every edit and lookup the reply
    names (and, at step 1, its points: first); None otherwise (the reply then goes to a fix call)."""
    try:
        sal = salvage(text)
    except ValueError:
        return None
    whole = (len(sal.get("edits") or []) >= len(_EDIT_KEY.findall(text or ""))
             and len(sal.get("next") or []) >= len(_ACT_KEY.findall(text or "")))
    return sal if whole and (not first or sal.get("points")) else None


def parse(llm: LLM, k: int, text: str, usage: Usage, max_tokens: int, rec: dict, stage: str = "") -> Optional[dict]:
    """A step's reply read as JSON; one that is not: salvaged when the salvage holds every edit and lookup it names
    (and, at step 1, its points), else reformatted by a fix call (staged '<stage>_fix'; stage: the call's, 'step_<k>'
    by default)."""
    stage = stage or f"step_{k}"
    try:
        return read_reply(text)
    except ValueError as exc:
        rec["repaired"] = {"error": str(exc)[:200], "broken": (text or "")[:20000]}
        whole = complete_salvage(text, first=k == 1)
        if whole is not None:
            rec["repaired"]["by"] = "salvage"
            return whole
        try:
            sal = salvage(text)
        except ValueError:
            sal = None
        if "{" in (text or ""):
            # a reformat, not a reading: the card's retry settings (no or low reasoning), so the budget goes to the JSON
            fixed = llm.chat(f"{stage}_fix", [{"role": "user", "content": FIX.format(error=str(exc)[:120], text=text)}],
                             usage, min(max_tokens, len(text) // 2 + 3000), retry=True)
            try:
                obj = read_reply(fixed)
                rec["repaired"]["by"] = "fix"
                return obj
            except ValueError:
                pass
        if sal:
            rec["repaired"]["by"] = "salvage, incomplete"
            return sal
        return None
