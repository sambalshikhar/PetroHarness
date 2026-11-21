"""The investigation's state and steps: the session (map, ledger, claims), the brief, the READ call (the model's
topics), step 1's points, each step's prompt rebuilt from the state, the settle step."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from petroharness.llm import LLM, Usage

from petroharness.agent import direction, vocabulary
from petroharness.agent.claims import Claims, coerce_edit
from petroharness.agent.engine import Formation, ToolError
from petroharness.agent.ledger import Ledger, _terms
from petroharness.agent.map import render
from petroharness.agent.schemas import named
from petroharness.agent.toolset import TOOLSET

NEW_CHARS = 12000          # NEW's results at most (about 3k tokens); results beyond come first at the next step (the
#   guides read are not in NEW: they have their own block, GUIDES)
OPENED_CHARS = 6000        # digests of earlier results at most


def new_chars() -> int:
    """NEW's budget: NEW_CHARS."""
    return NEW_CHARS


def opened_chars() -> int:
    """OPENED's budget: OPENED_CHARS."""
    return OPENED_CHARS
ACTIONS = 6                 # lookups per step: the cap and the prompt's stated limit
MAX_GUIDES = 2             # guides read in a step, beside the actions
MAX_CALCS = 3              # calculations in a step, beside the actions
MAX_STEPS = 8
DIRECT_STEPS = 2            # look steps of a direct question
DIRECT_ACTIONS = 4          # lookups in one look step
POLISH_STEPS = 2           # settled and only rephrasing this many steps in a row: converged
STEP_KEYS = {"asks", "points", "intent", "focus", "edits", "next", "done"}
TOOLS = set(TOOLSET.names())      # every tool the model is shown (agent/toolset.py); the reply parser reads no other
VERBS_RUN = {n for n in TOOLS if TOOLSET.get(n).verb}     # the verbs over Petrophys (each takes search and run)
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)
_EDIT_KEY = re.compile(r'"op"\s*:')
_ACT_KEY = re.compile(r'\{\s*"(?:' + "|".join(sorted(TOOLS | {"get", "find", "guide", "calc", "tool", "action"}, key=len, reverse=True))
                      + r')"\s*:')
_WRAPS = ("step", "reply", "response", "answer", "output", "result")


# the tools by what users ask (docs/TOOLS.md), as the brief groups them: the record's lookups are members of their
# verb, and the verbs over Petrophys fill what they lack. Read from the tools' definitions (agent/toolset.py).
VERBS = TOOLSET.by_group()


def _tool_line(t: dict) -> str:
    fn = t["function"]
    args = ", ".join(f'"{k}": ...' for k in fn["parameters"]["properties"])
    return f'  {{"{fn["name"]}": {{{args}}}}}   {fn["description"]}'


def tools_text(reach: str = "focus") -> str:
    """The tools as the brief lists them, from the tool schemas (src/petroharness/agent/schemas.py), grouped by verb
    under the line that says where Petrophys's functions are."""
    by = {t["function"]["name"]: t for t in named()}
    out = [C.text("C4", "library")]
    for head, names in VERBS:                                # every tool has its group (tools.spec.Toolset.add)
        out.append(f"  {head}")
        out += [_tool_line(by[n]) for n in names]
    # the zone selector the engine reads
    out.append('  zones (any lookup that takes them): zone ids ["Z2", "Z3"], a lithology ["SILT"] for its zones, '
               'or ["ALL"]; left out, every zone')
    if reach == "well":                                      # anywhere in the well (docs/designs/zones-and-intervals.md)
        out[-1] = ('  zones (any lookup that takes them): zone ids ["Z2", "Z3"], a lithology ["SILT"] for its zones, '
                   'or ["ALL"]; anywhere in the well, a depth range ["2870-2890"] or a unit of the tops file by its name '
                   '["<unit name>"], the call computing on that stretch with rows of its own; several, one row each; '
                   'left out, every zone. A verb\'s run also takes "where": only the samples where a condition holds '
                   '(e.g. the water leg, "SW > 0.95"). runs lists every interval unless given a limit')
    return "\n".join(out)


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
        # when it names none (benchmark N1/N3/N4: every lookup of a direct step unread sent it to an investigation)
        q, verb = d["search"], next((str(d[k]).strip().lower() for k in ("verb", "where", "in", "under")
                                     if str(d.get(k) or "").strip().lower() in VERBS_RUN), None)
        if isinstance(q, dict) and len(q) == 1 and str(next(iter(q))).strip().lower() in VERBS_RUN:
            verb, q = str(next(iter(q))).strip().lower(), next(iter(q.values()))
        words = join(list(q.values()) if isinstance(q, dict) else q).strip()
        if not words:
            return None
        from petroharness.agent.library_api import best_verb
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
        if name == "compare" and len(body) == 2:
            args.setdefault("a", body[0]), args.setdefault("b", body[1])
        elif name == "crossplot" and len(body) == 2:
            args.setdefault("y", body[0]), args.setdefault("x", body[1])
        else:
            args.setdefault("curves", body)
    return ("tool", name, args)


def _verb_objects() -> dict:
    """Each named object of the verbs that list objects (check, classify, summarize, calibrate) -> its verb."""
    from petroharness.agent.library_api import _objects
    out = {}
    for v in ("check", "classify", "summarize", "calibrate"):
        for o in _objects(v) if v in TOOLS else ():
            out.setdefault(str(o), set()).add(v)
    return {o: next(iter(vs)) for o, vs in out.items() if len(vs) == 1 and o not in TOOLS}


def _named_call(d: dict) -> Optional[tuple]:
    """A call named by what it calls rather than by a tool's key (benchmark N3/N4: 88 lookups unread): a tool's name
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
        from petroharness.agent.library_api import _is_function, lookup
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
    them, in its order (question suite B05: the second was read as an argument of the first, and ignored)."""
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


# --- the session ----------------------------------------------------------------------------------------------------

@dataclass
class Session:
    task: object
    f: Formation
    map: str
    ledger: Ledger
    claims: Optional[Claims] = None
    points: list = field(default_factory=list)
    intent: str = "characterize"
    guides: list = field(default_factory=list)
    topics: list = field(default_factory=list)       # the topic areas the model chose (READ); empty: none
    families: list = field(default_factory=list)     # the analyzer families those topics read; empty: no scoping
    reading: dict = field(default_factory=dict)      # the READ reply: topics, named
    card: str = ""                                   # the provenance card the writer was shown (its numbers count as shown)
    # the skill library the guides come from (None: none, so no DIRECTION and no guide action); left out, the plugged one
    library: Optional[direction.Library] = field(default_factory=direction.plugged)
    # a conversation on this well and interval (petroharness.session): the question's number in it, where its results
    # start in the ledger, and the earlier questions as the prompts show them ("" for the first question)
    turn: int = 1
    turn_start: int = 0
    earlier: str = ""
    reply: str = "full"       # a later question's answer length, as the model chose in step 1: "brief" or "full"
    # Depth: whether the READ call is asked how much work the question needs (reads_depth: on unless the run asked
    # for the investigation every time, --investigate), how it read this question ("direct": look steps and a
    # short answer), and the results a direct question's look steps were shown (its writer reads them: on a later
    # question they may be an earlier question's)
    reads_depth: bool = False
    depth: str = "investigate"
    scope: list = field(default_factory=list)        # the stretches this question is about (READ, reach well): the
    scope_note: str = ""                             #   default zones of every lookup; why a scope read was not used
    ask_user: str = ""                               # the question back to the user (loop.ask_back)
    ask_status: str = "ask_user"                     # its status: ask_user, or outside (a request outside the well's logs)
    ask_choices: list = field(default_factory=list)  # its answers to pick, each {label, question, scope?} (the UI's buttons)
    unit_note: str = ""                              # a unit the question names that the tops file does not have
    unit_facts: list = field(default_factory=list)   # the same notes as data, for the answer's reader (vocabulary.facts)
    scope_merged: str = ""                           # what the scope's items became (one part of another, joined)
    frame: Optional[str] = None                      # "lithology": every lookup reports by the lithology zones
    user_scope: Optional[list] = None                # the user's scope (/scope), in force until the user changes it
    scope_chosen: bool = False                       # the user chose it for this question (an answer to a question back)
    scope_by_user: bool = False                      # this question's scope is the user's (no other stretch named)
    fetched: list = field(default_factory=list)
    # the lines get and find fetched beyond what each result shows ({id: [line]}): kept lines (a list cut at its limit,
    # "the other intervals") and lines read by zone; the writer and the settle step read them with their result
    got: dict = field(default_factory=dict)

    @classmethod
    def build(cls, task, cfg) -> "Session":
        from petroharness.well.view import FormationView
        from petroharness.record.store import build as build_store
        from petroharness.agent.inventory import from_view
        view = FormationView.build(task, cfg)
        store = build_store(view)
        f = Formation(from_view(view, store), view, store)
        s = cls(task, f, render(f.inv), Ledger(f), library=direction.plugged(cfg))
        s.take_user_scope(task)
        return s

    def take_user_scope(self, task) -> None:
        """The scope and frame the user set for this question on (a conversation's /scope, /frame): applied as the
        question starts; None keeps what is in force."""
        self.scope_chosen = bool(getattr(task, "scope_chosen", False))    # this question's stretch, chosen by the user
        if getattr(task, "scope", None) is not None:
            self.user_scope = [str(x) for x in task.scope]
        if self.user_scope is not None:              # the user's scope is the default; a question may name others
            apply_scope(self, self.user_scope, "set by the user")
        self.scope_by_user = bool(self.user_scope) and bool(self.scope)
        if getattr(task, "frame", None) is not None:
            self.frame = None if task.frame in ("", "zones", "none") else task.frame

    def rewell(self, task, cfg, change: str) -> None:
        """A conversation's settings changed: the well as Petrophys interpreted it again (`task`: the new prepared
        well), read from here on; the ledger goes on and marks what was opened before (Ledger.rewell)."""
        from petroharness.well.view import FormationView
        from petroharness.record.store import build as build_store
        from petroharness.agent.inventory import from_view
        view = FormationView.build(task, cfg)
        store = build_store(view)
        self.f = Formation(from_view(view, store), view, store)
        self.ledger.rewell(self.f, change)
        self.task = task
        self.map = render(self.f.inv)

    def next_turn(self, task, earlier: str) -> None:
        """A further question of the same conversation: the well, the ledger and its ids stay (results opened before
        are read with get and find, and may be cited); the question's own state (topics, points, claims, guides)
        starts again. `earlier`: the earlier questions and what was found, as the prompts show them."""
        self.task, self.earlier = task, earlier
        self.turn += 1
        self.turn_start = self.ledger.turn_start = len(self.ledger.items)
        self.claims, self.points, self.intent, self.reply = None, [], "characterize", "full"
        self.depth, self.fetched, self.got = "investigate", [], {}
        self.guides, self.topics, self.families, self.reading, self.card = [], [], [], {}, ""
        self.map = render(self.f.inv)
        self.take_user_scope(task)

    def choose(self, topics: list) -> None:
        """The topics the model chose: their families, and the map's notes scoped to them."""
        self.topics = list(topics)
        self.families = direction.families(self.topics)
        self.map = render(self.f.inv, self.families)

    def run(self, act: tuple) -> tuple:
        """One action -> (text for NEW, the item it shows whole or None). A call opened before shows its item whole
        again, as does get without find; a guide is read into the guides (Session.guides_text shows it)."""
        if act[0] == "get":
            item = self.ledger.by_id(act[1])
            whole = item is not None and not any(_terms(act[2]))
            self.ledger.take_fetched()                     # only this call's lines
            out = self.ledger.get(act[1], act[2])
            got = self.ledger.take_fetched()
            if not whole:
                self.keep_got(got)
            return out, (item if whole else None)
        if act[0] == "find":
            self.ledger.take_fetched()
            out = self.ledger.find(act[1])
            self.keep_got(self.ledger.take_fetched())
            return out, None
        if act[0] == "calc":
            try:
                item, new = self.ledger.calc(act[1], f"{self.map}\n{self.task.question}")
            except ToolError as e:
                return f"calc not run: {e}", None
            return self.ledger.show(item, new), item
        if act[0] == "guide":
            if self.library is None:                 # no library plugged: no action this harness reads
                return C.fill("C8", "not_run", items=action_text(act), guide=""), None
            name = act[1].strip().lower()
            g = self.library.guide(name, self.f)
            if not g.startswith("no facet") and name not in self.guides:
                self.guides.append(name)
            return f"GUIDE {g}", None
        args = act[2]
        if (self.scope and isinstance(args, dict) and act[1] not in _SCOPE_KEEPS
                and (not args.get("zones") or _all(args["zones"]))):
            args = {**args, "zones": list(self.scope)}       # the question's scope: every lookup's default zones; ALL is
            #                                                  every row of it (the call names no stretch of its own)
        if self.frame and isinstance(args, dict) and "by" not in args and act[1] not in _SCOPE_KEEPS:
            args = {**args, "by": self.frame}                # the conversation's frame: by the lithology zones
        try:
            item, new = self.ledger.open(act[1], args)
        except ToolError as e:
            return f"{act[1]} not run: {e}", None
        except Exception as e:                       # never lose the question to one malformed call
            return f"{act[1]} not run: the arguments could not be used ({type(e).__name__}: {str(e)[:120]})", None
        return self.ledger.show(item, new), item

    def keep_got(self, fetched: dict) -> None:
        """The lines a get or find showed that their result's text does not (Session.got), each once, in order; the
        ledger hands them over as data (Ledger.take_fetched)."""
        for eid, lines in fetched.items():
            item = self.ledger.by_id(eid)
            if item is None:
                continue
            shown = set(item.text.splitlines())
            have = self.got.setdefault(eid, [])
            have += [ln for ln in lines if ln not in shown and ln not in have]
            if not have:
                del self.got[eid]

    def guides_text(self, fresh) -> str:
        """GUIDES: every guide read, in the order read; those read at the last step (fresh) in full, the earlier ones
        short (their Compare calls). Empty before any guide is read, and with no library."""
        if self.library is None or not self.guides:
            return ""
        short = [C.fill("C6", "guide_short", name=n, calls="; ".join(self.library.calls(n, self.f)))
                 for n in self.guides if n not in fresh]
        full = [f"GUIDE {self.library.guide(n, self.f)}" for n in self.guides if n in fresh]
        return C.text("C6", "guides_head") + "\n".join(short + full) + "\n\n"

    def opened(self, exclude: set) -> str:
        """OPENED: every result listed; digests of earlier ones, newest first, within the budget."""
        if not self.ledger.items:
            return "(nothing yet)"
        lines, used = [self.ledger.listing()], 0
        for e in reversed(self.ledger.items):
            if e.id in exclude:
                continue
            d = self.ledger.digest(e)
            if used + len(d) > opened_chars():
                break
            lines.append(d)
            used += len(d)
        return "\n\n".join(lines)


_PLUGGED = object()            # brief() and step1() given no library: the plugged one (direction.plugged())


def _library(library):
    return direction.plugged() if library is _PLUGGED else library


def _reach(s) -> str:
    """The session's reach (data.reach, on its view): what a tool's zones may name."""
    return getattr(getattr(getattr(s, "f", None), "view", None), "reach", "focus")


def brief(library=_PLUGGED, reach: str = "focus") -> str:
    """The system prompt of the READ call, a step and the settle step. With a skill library it names DIRECTION and the
    guide action (C1's guide fragments); with none (None), neither."""
    on = _library(library) is not None
    text = C.prompt("C1", "brief", direction=C.text("C1", "brief_direction") if on else "",
                  guide_action=C.text("C1", "brief_guide") if on else "")
    text = text.rstrip() + "\n\n" + BRIEF_WEAKNESSES + "\n"
    text = text.rstrip() + "\n\n" + BRIEF_LEVELS + "\n"
    return text.replace("{TOOLS}", tools_text(reach)).replace("{ACTIONS}", str(ACTIONS))


# what turns a weakness into a verdict (e.g. "flow units not distinct" after opening three FZI classes; "clay is
# not a control" from one pooled crossplot)
BRIEF_WEAKNESSES = C.text("C10", "brief_weaknesses")


# the reservoir properties every answer's formation overview reads (clay, effective porosity, water
# saturation, permeability), added to any first look
CORE_CURVES = ("VCL", "PHIE", "SW", "PERM")
CORE_LOOK_CAP = 14
# the mineral volumes a workflow computes (the composition, when the model chose this topic)
MINERAL_VOLUMES = ("VCL", "VQUAR", "VCALC", "VDOLO", "VANHY", "VSAND", "VSILT", "VSHALE", "VCOAL")
MINERAL_TOPIC = "lithology_mineralogy"


def named_curves(f: Formation, named) -> list:
    """The curves with data here that the READ call's named measurements stand for, in their order (the catalog's
    vocabulary: src/petroharness/agent/vocabulary.py resolve)."""
    have = {c.upper(): c for c in f.inv.curves}
    out = []
    for item in named or []:
        out += [have[c.upper()] for c in vocabulary.resolve(item, f.view.reg.curves, have.values())
                if c.upper() in have and f.view.available(have[c.upper()])]
    return list(dict.fromkeys(out))


# levels as well as rankings
BRIEF_LEVELS = C.text("C10", "brief_levels")


STEP1 = C.text("C5", "step1")
EXAMPLE_TOPIC = "net_reservoir_pay"      # step 1's example is a question on pay: its guide call names the library's guide
#   on that topic area (else the library's first guide)


def step1(library=_PLUGGED) -> str:
    """Step 1's instructions. With a skill library, the guide sentence and the example's guide call (C5's guide
    fragments); with none (None), neither."""
    lib = _library(library)
    if lib is None:
        text = C.fill_text(STEP1, guide_sentence="", guide_call="")
    else:
        g = (lib.on(EXAMPLE_TOPIC) or list(lib.facets))[0]
        text = C.fill_text(STEP1, guide_sentence=C.text("C5", "step1_guides"),
                           guide_call=C.fill("C5", "step1_guide_call", guide=g))
    return text.replace("{ACTIONS}", str(ACTIONS))


# the points stay within the question: unasked step-1 points take steps and become answer sections
POINTS_SCOPE = C.text("C5", "points_scope")


# --- the READ call: the model reads the question and chooses its topics ------------------------------------------------

READ = C.text("C5", "read")
def _all(zones) -> bool:
    """A call's zones that name no stretch of their own: ALL (every zone in view)."""
    items = [zones] if isinstance(zones, str) else list(zones or [])
    return bool(items) and all(str(z).strip().upper() in ("ALL", "ALL ZONES") for z in items)


# lookups the question's scope does not apply to: the well's step record (the same for any stretch) and the
# workflow's results for the interval (agent.selection.FOCUS_ONLY)
_SCOPE_KEEPS = ("step", "section", "zone_classes")


SCOPE_ITEM_CHARS = 60          # one scope item: a unit's name, a zone's, a depth range (a sentence is not a stretch)


def read_schema(depth: bool = False, scope: bool = False, names: tuple = ()) -> dict:
    """The READ reply's JSON schema: the topics from the index's areas and the measurements the question names (nothing
    that frames the question before the evidence is in view); with `depth`, also what kind of answer it asks for; with
    `scope` (reach well), the stretches it is about, each one of `names` (selection.names) or a depth range."""
    schema = {"type": "object",
              "properties": {"topics": {"type": "array", "items": {"enum": list(direction.areas())}, "minItems": 1,
                                        "maxItems": 4},
                             "named": {"type": "array", "items": {"type": "string"}, "maxItems": 12}},
              "required": ["topics", "named"]}
    if depth:
        schema["properties"]["depth"] = {"enum": ["direct", "investigate"] + (["outside"] if scope else [])}
        schema["required"] = ["topics", "named", "depth"]
    if scope:                                        # reach well: the stretches the question is about
        from petroharness.agent.selection import RANGE_PATTERN
        typed = [{"type": "string", "pattern": RANGE_PATTERN}] + ([{"enum": list(names)}] if names else [])
        schema["properties"]["scope"] = {"type": "array", "items": {"anyOf": typed}, "maxItems": 8}   # items once each:
        #                                         read_question checks it (uniqueItems would move the server's decoder)
        schema["required"] = schema["required"] + ["scope"]
    return schema


def _reading(text: str, depth: bool = False, outside: bool = False) -> Optional[dict]:
    """The READ reply as {topics, named} (with `depth`: and depth); None when it is not the JSON object the schema asks
    for (topics not one of the areas). Other keys are not read."""
    try:
        obj = json.loads(text or "")
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("topics"), list):
        return None
    areas = direction.areas()
    topics = list(dict.fromkeys(x for x in obj["topics"] if isinstance(x, str) and x in areas))[:4]
    if not topics:
        return None
    named = obj.get("named")
    got = {"topics": topics,
           "named": [str(x).strip() for x in named if str(x).strip()][:12] if isinstance(named, list) else []}
    if depth:                                            # anything but a clear "direct" is an investigation
        said = str(obj.get("depth", "")).strip().lower()
        got["depth"] = "direct" if said == "direct" else "outside" if outside and said == "outside" else "investigate"
    return got


def read_question(llm: LLM, s: Session, usage: Usage, max_tokens: int, trace: dict) -> None:
    """The READ call, before the first look: one schema-guided call (one retry of the same call when the reply is not
    readable). The model's topics key the first look, the index, the sections a guide opens and the map's notes; no
    readable reply leaves no topics (the general first look, the index in its own order). How the question is read
    is step 1's, with the evidence in view."""
    well = _reach(s) == "well"
    s.ask_user = s.unit_note = ""                    # each question's own (a conversation's session goes on)
    s.unit_facts = []
    s.ask_status, s.ask_choices = "ask_user", []
    say_zones_left(s)                                # said under every question, whatever its scope or reach
    head = (C.text("C5", "read_depth") if s.reads_depth else READ)
    if well:                                     # the stretches the question is about (agent.selection)
        head = _with_scope(head, s)
        if s.reads_depth:                        # a request outside the well's logs (users type anything)
            parts = head.rsplit("\nReply with one JSON object", 1)
            line = C.text("C5", "read_outside").strip()
            head = (parts[0] + "\n" + line + "\nReply with one JSON object" + parts[1] if len(parts) == 2
                    else head + "\n" + line).replace("<direct or investigate>", "<direct, investigate or outside>", 1)
    user = (head
            + f"\n\nQUESTION:\n{s.task.question}\n" + (f"\n{s.earlier}\n" if s.earlier else "")
            + f"\nTHE MAP\n{s.map}\n\nTOPIC AREAS:\n"
            + "\n".join(f"{name} - {a['when']}" for name, a in direction.areas().items()))
    messages = [{"role": "system", "content": brief(s.library, _reach(s))}, {"role": "user", "content": user}]
    got, how, kept = None, "ok", None
    for stage in ("read", "read_retry"):
        text = llm.chat(stage, messages, usage, max_tokens, json_schema=read_schema(
            s.reads_depth, well, tuple(selection_names(s.f)) if well else ()))
        got = _reading(text, s.reads_depth, outside=well)
        if got is not None and well and _scope_repeats(text):   # its scope's items are a set, which the schema
            kept, got = kept or (got, text), None                # does not hold (read_schema): asked once more
        if got is not None:                                      # (question suite B10, S02, H02)
            break
        how = "retry"
    if got is None and kept:                         # repeated again: the first such reply, each item read once
        got, text = kept
    if got is None:
        got, how = {"topics": [], "named": []}, "failed"
    s.reading = got
    s.depth = got.get("depth", "investigate")
    if s.depth == "outside":                         # not about the well: what this assistant does, nothing computed
        from petroharness.agent.selection import interval_name
        s.ask_user, s.ask_status = C.fill("C9", "outside_reply", interval=interval_name(s.f)), "outside"
        s.ask_choices = [{"label": q, "question": q} for q in
                         (x.format(interval=interval_name(s.f)) for x in C.text("C9", "outside_examples"))]
        trace["outside"] = True
    s.choose(got["topics"])
    if well:
        read = _scope_read(text) if how != "failed" else None
        if s.scope_chosen and s.user_scope:           # the user's answer to a question back: this question's stretch,
            trace["scope_chosen"] = list(s.user_scope)   # whatever the READ reads (UI check: a misread unit replaced it)
            read = None
        if s.depth != "outside":
            s.ask_user = "" if s.user_scope else ask_back(s, [s.task.question])     # the user's own words (question
        #   suite U15, U16: the READ restated the unit the user's answer had resolved, and the question was asked again)
        if s.ask_user:                               # a unit listed more than once: the user chooses (a scope the user
            #                                          set is that choice), nothing read on
            trace["scope"] = {"read": read, "used": [], "note": "", "merged": ""}
            trace["ask_user"] = s.ask_user
            trace["ask_choices"] = list(s.ask_choices)
            read = None
        if read:                                     # the stretches this question names: for this question
            apply_scope(s, read)
            if not s.scope and s.scope_note:         # it named no stretch: asked again once, with the reason (the
                again = llm.chat("read_scope", [messages[0], {"role": "user", "content": user + "\n\n" + C.fill(
                    "C5", "read_scope_again", reason=s.scope_note)}], usage, max_tokens,   # same single-turn prompt)
                    json_schema=read_schema(s.reads_depth, well, tuple(selection_names(s.f))))
                second = _scope_read(again)
                trace["read_scope_again"] = {"reply": (again or "")[:1500], "scope": second, "note": s.scope_note}
                if second:
                    apply_scope(s, second)
                    read = second
            s.scope_by_user = False
            if not s.scope and s.user_scope:         # not usable: the user's scope stays, the reason said
                note = s.scope_note
                apply_scope(s, s.user_scope, "set by the user")
                s.scope_note, s.scope_by_user = note, bool(s.scope)
        elif read is not None and s.user_scope is None:  # none named, no user scope: the interval
            apply_scope(s, [])
        if not s.ask_user:
            trace["scope"] = {"read": read, "used": list(s.scope), "note": s.scope_note, "merged": s.scope_merged,
                              **({"by": "user"} if s.scope_by_user else {}), **({"frame": s.frame} if s.frame else {})}
    trace["read"] = {"reply": (text or "")[:3000], "parse": how, **got}
    trace["topics"] = list(s.topics)


def _with_scope(head: str, s: Session) -> str:
    """The READ text under reach "well": the scope line, before the reply's example, which gains "scope"; the scope
    in force (a conversation's) said when there is one."""
    line = C.text("C5", "read_scope").strip()
    if s.scope:
        line += f" Scope in force: {json.dumps(list(s.scope))}."
    parts = head.rsplit("\nReply with one JSON object", 1)
    head = parts[0] + "\n" + line + "\nReply with one JSON object" + parts[1] if len(parts) == 2 else head + "\n" + line
    return head.replace('"named": ["..."]', '"named": ["..."], "scope": ["..."]', 1)


def _scope_strings(text: str) -> list:
    """The READ reply's scope strings, as written, in order (repeats kept; none when the reply has none)."""
    try:
        obj = json.loads(text or "")
    except json.JSONDecodeError:
        return []
    raw = obj.get("scope") if isinstance(obj, dict) else None
    return [str(x).strip() for x in (raw if isinstance(raw, list) else []) if str(x).strip()]


def _scope_repeats(text: str) -> bool:
    """The READ reply's scope names an item twice (its items are a set)."""
    got = _scope_strings(text)
    return len(got) != len(set(got))


def _scope_read(text: str) -> list:
    """The READ reply's scope: its strings, as written, each once (none when the reply has none)."""
    return list(dict.fromkeys(_scope_strings(text)))[:8]


def selection_names(f: Formation) -> list:
    """The names a READ reply's scope items are typed to (agent.selection.names)."""
    from petroharness.agent.selection import names
    return names(f)


def scope_items(f: Formation, asked) -> list:
    """A scope's items as a selection takes them: "the whole well" (one typed item, selection.WHOLE_WELL_ITEM) as the
    well's span; every other item as written (a user's /scope that names no stretch is refused with the reason)."""
    from petroharness.agent.selection import WHOLE_WELL_ITEM
    span = getattr(f.inv, "well_span", ()) or ()
    items = [str(x).strip() for x in asked or [] if str(x).strip()]
    return [f"{span[0]:g}-{span[1]:g}" if x.lower() == WHOLE_WELL_ITEM and span else x for x in items]


def say_zones_left(s: Session) -> None:
    """The user's zones with no sample here, said under the question (Session.unit_note) and kept as data for the
    answer's reader (Session.unit_facts), under every question while the zones are in force: a question with the
    user's scope, or one about the whole well, skips the question back but not this (question suite Z2)."""
    left = getattr(s.f.view, "user_zones_left", None) or []
    if not left:
        return
    u = s.f.view.report_unit
    s.unit_note = C.fill("C10", "zones_left_note", items="; ".join(f"{n} {t:g}-{b:g} {u} ({why})" for n, t, b, why in left))
    s.unit_facts = [{"kind": "zones_left", "zones": [{"name": n, "top": t, "base": b, "unit": u, "why": why}
                                                     for n, t, b, why in left]}]


def ask_back(s: Session, texts) -> str:
    """The question back to the user when the question cannot be read as one stretch of the tops file: a unit it lists
    more than once (which one), a unit whose row was left out (the row to fix), a name close to units it lists but
    none of them (did you mean). A name close to none is said under the question (Session.unit_note) and answered as
    absent. "" when the question reads as it is (user, 2026-11-20: keep the user in the loop; question suite U01-U05)."""
    from petroharness.agent.selection import left_out_named, shared_names_unread, unit_names_unread
    asked = ask_listed_twice(s, texts)
    if asked:
        return asked
    u = s.f.view.report_unit
    q = s.task.question
    shared = shared_names_unread(s.f, texts)
    if shared:
        name, us = shared[0]
        s.ask_choices = [{"label": f"{x.name} {x.top:g}-{x.base:g} {u}", "question": _named_as(q, name, x.name)} for x in us]
        return C.fill("C9", "ask_which_unit", name=name, n=len(us),
                      listed="; ".join(f"{x.name} {x.top:g}-{x.base:g} {u}" for x in us),
                      example=f"{us[0].top:g}-{us[0].base:g} {u}")
    rows = left_out_named(s.f, texts)
    if rows:
        r = rows[0]
        if r.get("top") is not None and r.get("base") is not None:     # the row's own depths, in order: one choice
            lo, hi = sorted((float(r["top"]), float(r["base"])))
            ru = r.get("unit") or u
            s.ask_choices = [{"label": f"{r['name']} as {lo:g}-{hi:g} {ru} (the row's depths, in order)",
                              "question": q, "scope": [f"{lo:g}-{hi:g} {ru}"]}]
        return C.fill("C9", "ask_left_out", name=r["name"], line=r["line"], why=r["why"], unit=r.get("unit") or u)
    unread = unit_names_unread(s.f, texts)
    close = [(n, c) for n, c in unread if c]
    if close:
        name, cands = close[0]
        units = {x.name: x for x in s.f.view.units}
        ex = units[cands[0]]
        s.ask_choices = [{"label": c, "question": _named_as(q, name, c)} for c in cands]
        return C.fill("C9", "ask_did_you_mean", name=name, candidates=" or ".join(cands),
                      example=f"{ex.top:g}-{ex.base:g} {u}")
    if unread:
        listed = sorted({x.name for x in s.f.view.units}, key=lambda n: min(x.top for x in s.f.view.units if x.name == n))
        s.unit_note = (s.unit_note + "\n" if s.unit_note else "") + C.fill("C10", "absent_unit_note", items="; ".join(n for n, _ in unread),
                             units=", ".join(listed[:UNITS_LISTED]) + (f" and {len(listed) - UNITS_LISTED} more"
                                                                      if len(listed) > UNITS_LISTED else ""))
        s.unit_facts.append({"kind": "absent_unit", "names": [n for n, _ in unread], "units": listed})
    return ""


UNITS_LISTED = 16           # the tops file's units a note names (the rest counted)


def _named_as(question: str, written: str, name: str) -> str:
    """The question with a name as the user wrote it replaced by the one meant (a choice's question to send)."""
    return re.sub(rf"(?<![A-Za-z0-9]){re.escape(written)}(?![A-Za-z0-9])", lambda m: name, question, count=1, flags=re.I)


def ask_listed_twice(s: Session, texts) -> str:
    """The question back to the user when the question (or the scope read from it) names a unit the tops file lists
    more than once: which one, or a fixed tops file (C9 ask_listed_twice); "" otherwise."""
    from petroharness.agent.selection import listed_more_than_once
    found = listed_more_than_once(s.f, texts)
    if not found:
        return ""
    u = s.f.view.report_unit
    listed = "; ".join(f"{name} {len(rows)} times (" + ", ".join(f"line {ln}: {top:g}-{base:g} {u}" for ln, top, base
                                                                in rows) + ")" for name, rows in found)
    name, rows = found[0]
    spans = [f"{top:g}-{base:g} {u}" for _, top, base in rows]
    s.ask_choices = [{"label": f"{name} {sp}", "question": s.task.question, "scope": [sp]} for sp in spans] \
        + [{"label": f"all {len(spans)} of them", "question": s.task.question, "scope": spans}]
    return C.fill("C9", "ask_listed_twice", listed=listed, example=f"{rows[0][1]:g}-{rows[0][2]:g} {u}")


def apply_scope(s: Session, asked, who: str = "read from the question") -> None:
    """The stretches the question is about, as the model read them (READ) or a conversation keeps them: checked as a
    selection (agent.selection.resolve), then every lookup's default zones; "the whole well" is the well's own span.
    One that cannot be used is left out, and step 1 says why (Session.scope_note)."""
    from petroharness.agent import selection
    s.scope, s.scope_note, s.scope_merged = [], "", ""
    items = [str(x).strip() for x in asked or [] if str(x).strip()]
    if not items:
        return
    asked = scope_items(s.f, items)
    merged = []
    try:
        on, _ = selection.resolve(s.f, asked, force=True, notes=merged)   # the union of its items (selection._union)
        used = selection.union_labels(s.f, asked)
    except ToolError as e:
        said, short = str(e), [x if len(x) <= SCOPE_ITEM_CHARS else x[:SCOPE_ITEM_CHARS] + "..." for x in items]
        for x, y in zip(items, short):               # each item said short
            said = said.replace(x, y)
        s.scope_note = f"The scope {who} ({', '.join(short)}) is not used: {said}"
        return
    if merged:                                       # what its items became, said with the scope (or its absence)
        s.scope_merged = (f"The scope {who} ({', '.join(items)}): " + "; ".join(merged)
                          + ("; together they are the interval's own samples" if on is s.f else "") + ".")
    if on is s.f:
        return                                       # the interval's own samples: the interval, not a selection of it
    s.scope = used


def scope_text(s: Session) -> str:
    """The prompt's line of the question's scope (reach well): what every lookup computes on, or why the scope read
    was not used; empty with none."""
    frame = ("FRAME: every lookup reports by the lithology zones (L1..), as the user set it, unless its call gives "
             "\"by\".\n\n" if s.frame == "lithology" else "")
    if s.scope:
        who = "set by the user" if s.scope_by_user else "the stretches this question is about"
        return ((f"{s.scope_note}\n" if s.scope_note else "") + (f"{s.scope_merged}\n" if s.scope_merged else "")
                + f"SCOPE: {', '.join(s.scope)} ({who}): every lookup computes on it unless its call names other zones "
                "(\"ALL\" is every row of it); the record's sections and classes stay the interval's.\n\n" + frame)
    stretch = ""
    if _reach(s) == "well":                          # no scope: the stretch in force is the interval, said every time
        from petroharness.agent.selection import interval_name   # (question suite B10: a scope cleared was kept)
        stretch = (f"SCOPE: none: every lookup computes on the interval the session opened on, {interval_name(s.f)}, "
                   "unless its call names other zones.\n\n")
    return ((f"{s.scope_note}\n\n" if s.scope_note else "") + (f"{s.scope_merged}\n" if s.scope_merged else "")
            + stretch + frame)


def topics_text(s: Session) -> str:
    """Step 1's reminder of the topics the READ call chose (empty when none were read)."""
    if not s.topics:
        return ""
    return "YOUR TOPICS: " + ", ".join(s.topics) + "\n\n"


SETTLE = C.text("C5", "settle")
MAX_GUIDE_STATS = 2          # workflow-curve stats a guide opens with it (direction.Library.workflow_stats)


# the settle step is where claims become final; the readings rules are restated there, with the one rule for bases
# and conventions (C9 aspects_rule: the settle step's only; the writer is not given it)
SETTLE_WEAKNESSES = C.text("C10", "settle_weaknesses")
ASPECTS_RULE = C.text("C9", "aspects_rule")
BOOK_ITEMS = 12            # results named in the unused list at most (the rest counted)


def _n(eid: str) -> int:
    return int(eid[1:]) if re.fullmatch(r"E\d+", str(eid)) else 0


def written_before(claims: list, items: dict) -> list:
    """The graded claims whose text was written before results their point's claims now cite were opened (a fact of
    order, not of content: the model reads whether each text still holds against them), each with those results."""
    out = []
    for c in claims:
        if c.grade == "hypothesis":
            continue
        later = sorted({e for x in claims if x.point == c.point for e in x.ev if e in items and _n(e) > c.text_at}, key=_n)
        if later:
            out.append(f"{c.id} (point {c.point}; its text came before {', '.join(later)})")
    return out


def bookkeeping(s) -> str:
    """The settle step's lists (C5 'settle_lists'), for the model to act on as it sees fit; nothing waits
    on them: the measurements the READ call named (with data here) that no claim names or reaches through a result it
    cites; the opened results (not calculations) no claim cites; the claims still graded hypothesis; the claims whose
    text came before results their point's claims cite (written_before). Empty when all four are."""
    from petroharness.agent.claims import _item_names
    if s.claims is None:
        return ""
    reg, known = s.f.view.reg.curves, list(s.f.inv.curves)
    claims = list(s.claims.claims.values())
    items = {e.id: e for e in s.ledger.items}
    cited = {x for c in claims for x in c.ev}
    said = " ".join(f"{c.text} {c.means} {c.weak}" for c in claims)
    in_claims = {x.upper() for _, curves in vocabulary.in_text(said, reg, known) for x in curves}
    in_claims |= {x.upper() for x in vocabulary.written(said, known)}
    reached = {n for e in cited if e in items for n in _item_names(items[e])}
    named = []
    for n in (getattr(s, "reading", None) or {}).get("named") or []:
        curves = [c for c in vocabulary.resolve(n, reg, known) if c in s.f.inv.curves and s.f.view.available(c)]
        if not curves or {c.upper() for c in curves} & (in_claims | reached) or str(n).strip().lower() in said.lower():
            continue
        named.append(f"{str(n).strip()[:vocabulary.NAME_CHARS]} ({', '.join(curves)})")
    unused = [f"{e.id} {e.call_text()}" for e in s.ledger.items if e.id not in cited and e.tool != "calc"]
    if len(unused) > BOOK_ITEMS:
        unused = unused[:BOOK_ITEMS] + [f"and {len(unused) - BOOK_ITEMS} more"]
    hyp = [c.id for c in claims if c.grade == "hypothesis"]
    stale = written_before(claims, items)
    if len(stale) > BOOK_ITEMS:
        stale = stale[:BOOK_ITEMS] + [f"and {len(stale) - BOOK_ITEMS} more"]
    texts = C.text("C5", "settle_lists")
    lines = [C.fill_text(texts[k], items=sep.join(v)) for k, v, sep in
             (("named", named, "; "), ("unused", unused, "; "), ("hypotheses", hyp, ", "), ("written_before", stale, "; "))
             if v]
    return (texts["head"] + "\n" + "\n".join(lines) + "\n\n") if lines else ""


def settle(llm: LLM, s: Session, usage: Usage, max_tokens: int, trace: dict) -> None:
    """The final step: no lookups; the model sees its claims and every opened result and makes the answer final. The
    claim checks apply as in the steps; the trace keeps the reply, the edits and what changed."""
    if s.claims is None or not s.ledger.items:
        return
    from petroharness.agent.writer import opened_results
    absent = vocabulary.note(s)
    pts = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(s.points))
    book = bookkeeping(s)                         # lists for the model, never a check
    user = (f"QUESTION:\n{s.task.question}\n" + (f"{absent}\n" if absent else "")
            + (f"\n{s.earlier}\n" if s.earlier else "")
            + f"\nTHE MAP\n{s.map}\n\nYOUR POINTS:\n{pts}\n\nYOUR ANSWER:\n{s.claims.render()}\n\n"
            f"ALL RESULTS:\n{opened_results(s)}\n\n" + book
            + f"{SETTLE}" + SETTLE_WEAKNESSES + "\n- " + ASPECTS_RULE)
    rec = {"claims_before": len(s.claims.claims), "issues_before": s.claims.done_issues(), "bookkeeping": book}
    text = llm.chat("settle", [{"role": "system", "content": brief(s.library, _reach(s))}, {"role": "user", "content": user}],
                    usage, max_tokens)
    rec["reply"] = (text or "")[:6000]
    rec["prompt_chars"] = len(user)
    obj = parse(llm, 0, text, usage, max_tokens, rec, stage="settle")
    if obj is None:
        rec["error"] = "unreadable reply"
    else:
        edits = obj.get("edits") if isinstance(obj.get("edits"), list) else []
        rec["edits"], rec["edit_msgs"] = edits, s.claims.apply(edits)
        s.claims.refresh()
    rec["claims_after"], rec["issues_after"] = len(s.claims.claims), s.claims.done_issues()
    trace["settle"] = rec
    trace["claims"] = [c.__dict__ for c in s.claims.claims.values()]
    trace["dropped"] = [c.__dict__ for c in s.claims.dropped]
    trace["done_issues"] = s.claims.done_issues()


def investigate(llm: LLM, s: Session, usage: Usage, max_tokens: int, trace: dict, max_steps: int = MAX_STEPS) -> Optional[Claims]:
    """The investigation on a built session: the claims, or None when step 1 was unreadable. Its steps are the nodes of
    the question graph (petroharness.agent.graph, docs/GRAPH.md), run here as the investigation graph."""
    from petroharness.agent.graph import investigate as run_investigation
    return run_investigation(llm, s, usage, max_tokens, trace, max_steps)
