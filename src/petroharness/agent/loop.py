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
from petroharness.agent.schemas import CROSSPLOT, LAG, LIBRARY_NAMES, NAMED, named

NEW_CHARS = 12000          # NEW's results at most (about 3k tokens); results beyond come first at the next step (the
#   guides read are not in NEW: they have their own block, GUIDES)
OPENED_CHARS = 6000        # digests of earlier results at most
ACTIONS = 6                 # lookups per step: the cap and the prompt's stated limit
MAX_GUIDES = 2             # guides read in a step, beside the actions
MAX_CALCS = 3              # calculations in a step, beside the actions
MAX_STEPS = 8
POLISH_STEPS = 2           # settled and only rephrasing this many steps in a row: converged
STEP_KEYS = {"asks", "points", "intent", "focus", "edits", "next", "done"}
TOOLS = {t["function"]["name"] for t in NAMED + [CROSSPLOT, LAG]} | set(LIBRARY_NAMES)   # every lookup the model can be shown (named()
#   adds the optional ones while their switch is on; a shown tool the parser does not know is dropped unread)
from petroharness.agent.compute import MAIN as _COMPUTED_MAIN  # noqa: E402
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)
_MAIN = {"section": "key", "step": "name", "runs": "condition", "profile": "curve", "crossplot": "y",
         "calculate": "property", "estimate": "parameter", "check": "what", "classify": "what",
         "summarize": "what", "calibrate": "what", **_COMPUTED_MAIN}
_EDIT_KEY = re.compile(r'"op"\s*:')
_ACT_KEY = re.compile(r'\{\s*"(?:' + "|".join(sorted(TOOLS | {"get", "find", "guide", "calc", "tool", "action"}, key=len, reverse=True))
                      + r')"\s*:')
_WRAPS = ("step", "reply", "response", "answer", "output", "result")


# the tools by what users ask (docs/TOOLS.md), as the brief groups them: the record's lookups are members of their
# verb, and the verbs over Petrophys fill what they lack
VERBS = (("DESCRIBE: what the record holds", ("stats", "profile", "runs", "section", "step", "formation_summary")),
         ("COMPARE AND GROUP", ("compare", "crossplot", "overlap", "lithology_stats", "zone_contrast", "curve_order",
                                "vertical_sequence")),
         ("CHECK: data quality", ("check", "spike_flags", "adjacent_jumps", "threshold_exceedance", "data_record",
                                  "lag_correlation")),
         ("CALCULATE: recompute with Petrophys", ("calculate", "what_if", "estimate")),
         ("CLASSIFY", ("classify", "zone_classes", "unit_roles")),
         ("SUMMARIZE", ("summarize", "pay_summary")),
         ("CALIBRATE: against core, elastic properties", ("calibrate", "core_vs_log")))


def _tool_line(t: dict) -> str:
    fn = t["function"]
    args = ", ".join(f'"{k}": ...' for k in fn["parameters"]["properties"])
    return f'  {{"{fn["name"]}": {{{args}}}}}   {fn["description"]}'


def tools_text() -> str:
    """The tools as the brief lists them, from the tool schemas (src/petroharness/agent/schemas.py), grouped by verb
    under the line that says where Petrophys's functions are."""
    tools = named()
    by = {t["function"]["name"]: t for t in tools}
    out, placed = [C.text("C4", "library")], set()
    for head, names in VERBS:
        here = [by[n] for n in names if n in by]
        if here:
            out.append(f"  {head}")
            out += [_tool_line(t) for t in here]
            placed |= {t["function"]["name"] for t in here}
    rest = [t for t in tools if t["function"]["name"] not in placed]
    if rest:
        out.append("  OTHER")
        out += [_tool_line(t) for t in rest]
    # the zone selector the engine reads
    out.append('  zones (any lookup that takes them): zone ids ["Z2", "Z3"], a lithology ["SILT"] for its zones, '
               'or ["ALL"]; left out, every zone')
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
    if "get" in d or kind == "get":
        eid = d.get("get") if "get" in d else (d.get("id") or d.get("item"))
        eid = (eid[0] if eid else "") if isinstance(eid, list) else eid
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
    name = kind if kind in TOOLS else next((k for k in d if k in TOOLS), None)
    if name is None:
        return None
    body = d.pop(name, None) if name in d else None
    args = dict(d.get("args") or {}) if isinstance(d.get("args"), dict) else {k: v for k, v in d.items() if k != "args"}
    if isinstance(body, dict):
        args = {**body, **args}
    elif isinstance(body, str):
        args.setdefault(_MAIN.get(name, "curves"), body)
    elif isinstance(body, list):
        if name == "compare" and len(body) == 2:
            args.setdefault("a", body[0]), args.setdefault("b", body[1])
        elif name == "crossplot" and len(body) == 2:
            args.setdefault("y", body[0]), args.setdefault("x", body[1])
        else:
            args.setdefault("curves", body)
    return ("tool", name, args)


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


def parse(llm: LLM, k: int, text: str, usage: Usage, max_tokens: int, rec: dict) -> Optional[dict]:
    try:
        return read_reply(text)
    except ValueError as exc:
        rec["repaired"] = {"error": str(exc)[:200], "broken": (text or "")[:20000]}
        try:
            sal = salvage(text)
        except ValueError:
            sal = None
        complete = lambda o: (len(o.get("edits") or []) >= len(_EDIT_KEY.findall(text or ""))
                              and len(o.get("next") or []) >= len(_ACT_KEY.findall(text or "")))
        if sal and complete(sal) and (k > 1 or sal.get("points")):
            rec["repaired"]["by"] = "salvage"
            return sal
        if "{" in (text or ""):
            fixed = llm.chat(f"step_{k}_fix", [{"role": "user", "content": FIX.format(error=str(exc)[:120], text=text)}],
                             usage, min(max_tokens, len(text) // 2 + 3000))
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

    @classmethod
    def build(cls, task, cfg) -> "Session":
        from petroharness.well.view import FormationView
        from petroharness.record.store import build as build_store
        from petroharness.agent.inventory import from_view
        view = FormationView.build(task, cfg)
        store = build_store(view)
        f = Formation(from_view(view, store), view, store)
        return cls(task, f, render(f.inv), Ledger(f), library=direction.plugged(cfg))

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
            return self.ledger.get(act[1], act[2]), (item if whole else None)
        if act[0] == "find":
            return self.ledger.find(act[1]), None
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
        try:
            item, new = self.ledger.open(act[1], act[2])
        except ToolError as e:
            return f"{act[1]} not run: {e}", None
        except Exception as e:                       # never lose the question to one malformed call
            return f"{act[1]} not run: the arguments could not be used ({type(e).__name__}: {str(e)[:120]})", None
        return self.ledger.show(item, new), item

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
            if used + len(d) > OPENED_CHARS:
                break
            lines.append(d)
            used += len(d)
        return "\n\n".join(lines)


_PLUGGED = object()            # brief() and step1() given no library: the plugged one (direction.plugged())


def _library(library):
    return direction.plugged() if library is _PLUGGED else library


def brief(library=_PLUGGED) -> str:
    """The system prompt of the READ call, a step and the settle step. With a skill library it names DIRECTION and the
    guide action (C1's guide fragments); with none (None), neither."""
    on = _library(library) is not None
    text = C.fill("C1", "brief", direction=C.text("C1", "brief_direction") if on else "",
                  guide_action=C.text("C1", "brief_guide") if on else "")
    text = text.rstrip() + "\n\n" + V9_BRIEF + "\n"
    text = text.rstrip() + "\n\n" + V10_BRIEF + "\n"
    return text.replace("{TOOLS}", tools_text()).replace("{ACTIONS}", str(ACTIONS))


# what turns a weakness into a verdict (e.g. "flow units not distinct" after opening three FZI classes; "clay is
# not a control" from one pooled crossplot)
V9_BRIEF = C.text("C10", "v9_brief")


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
V10_BRIEF = C.text("C10", "v10_brief")


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
POINTS = ("Your reply has no points. Reply with only the points your edits refer to, as JSON: {{\"points\": [\"...\"], "
          "\"intent\": \"...\"}} - {n} questions the answer must settle, numbered as your edits number them.")


# --- the READ call: the model reads the question and chooses its topics ------------------------------------------------

READ = C.text("C5", "read")


def read_schema() -> dict:
    """The READ reply's JSON schema: the topics from the index's areas and the measurements the question names (nothing
    that frames the question before the evidence is in view)."""
    return {"type": "object",
            "properties": {"topics": {"type": "array", "items": {"enum": list(direction.areas())}, "minItems": 1,
                                      "maxItems": 4},
                           "named": {"type": "array", "items": {"type": "string"}, "maxItems": 12}},
            "required": ["topics", "named"]}


def _reading(text: str) -> Optional[dict]:
    """The READ reply as {topics, named}; None when it is not the JSON object the schema asks for (topics not one of
    the areas). Other keys are not read."""
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
    return {"topics": topics,
            "named": [str(x).strip() for x in named if str(x).strip()][:12] if isinstance(named, list) else []}


def read_question(llm: LLM, s: Session, usage: Usage, max_tokens: int, trace: dict) -> None:
    """The READ call, before the first look: one schema-guided call (one retry of the same call when the reply is not
    readable). The model's topics key the first look, the index, the sections a guide opens and the map's notes; no
    readable reply leaves no topics (the general first look, the index in its own order). How the question is read
    is step 1's, with the evidence in view."""
    user = (READ + f"\n\nQUESTION:\n{s.task.question}\n\nTHE MAP\n{s.map}\n\nTOPIC AREAS:\n"
            + "\n".join(f"{name} - {a['when']}" for name, a in direction.areas().items()))
    messages = [{"role": "system", "content": brief(s.library)}, {"role": "user", "content": user}]
    got, how = None, "ok"
    for stage in ("read", "read_retry"):
        text = llm.chat(stage, messages, usage, max_tokens, json_schema=read_schema())
        got = _reading(text)
        if got is not None:
            break
        how = "retry"
    if got is None:
        got, how = {"topics": [], "named": []}, "failed"
    s.reading = got
    s.choose(got["topics"])
    trace["read"] = {"reply": (text or "")[:3000], "parse": how, **got}
    trace["topics"] = list(s.topics)


def topics_text(s: Session) -> str:
    """Step 1's reminder of the topics the READ call chose (empty when none were read)."""
    if not s.topics:
        return ""
    return "YOUR TOPICS: " + ", ".join(s.topics) + "\n\n"


SETTLE = C.text("C5", "settle")
MAX_GUIDE_STATS = 2          # workflow-curve stats a guide opens with it (direction.Library.workflow_stats)


# the settle step is where claims become final; the readings rules are restated there, with the one rule for bases
# and conventions (C9 aspects_rule, the writer's too)
SETTLE_V9 = C.text("C10", "settle_v9")
ASPECTS_RULE = C.text("C9", "aspects_rule")
BOOK_ITEMS = 12            # results named in the unused list at most (the rest counted)


def bookkeeping(s) -> str:
    """The settle step's lists (C5 'settle_lists'), for the model to act on as it sees fit; nothing waits
    on them: the measurements the READ call named (with data here) that no claim names or reaches through a result it
    cites; the opened results (not calculations) no claim cites; the claims still graded hypothesis. Empty when all
    three are."""
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
    texts = C.text("C5", "settle_lists")
    lines = [C.fill_text(texts[k], items=sep.join(v)) for k, v, sep in
             (("named", named, "; "), ("unused", unused, "; "), ("hypotheses", hyp, ", ")) if v]
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
            + f"\nTHE MAP\n{s.map}\n\nYOUR POINTS:\n{pts}\n\nYOUR ANSWER:\n{s.claims.render()}\n\n"
            f"ALL RESULTS:\n{opened_results(s)}\n\n" + book
            + f"{SETTLE}" + SETTLE_V9 + "\n- " + ASPECTS_RULE)
    rec = {"claims_before": len(s.claims.claims), "issues_before": s.claims.done_issues(), "bookkeeping": book}
    text = llm.chat("settle", [{"role": "system", "content": brief(s.library)}, {"role": "user", "content": user}],
                    usage, max_tokens)
    rec["reply"] = (text or "")[:6000]
    rec["prompt_chars"] = len(user)
    obj = parse(llm, 0, text, usage, max_tokens, rec)
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
