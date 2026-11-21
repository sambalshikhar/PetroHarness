"""The door a model's call goes through: argument names and values read, the shapes models send fitted to what a
tool takes, unknown arguments said back. The tools themselves are defined once, in petroharness.agent.toolset; this
module shows them as native tool-calling schemas (named)."""
from __future__ import annotations

import inspect
import json
import re

from petroharness.agent import components as C  # the texts: src/petroharness/agent/components
from petroharness.agent import engine as E
from petroharness.agent.engine import Formation, Result, ToolError
from petroharness.agent.toolset import TOOLS, TOOLSET
from petroharness.well import summary as S

LIBRARY_NAMES = tuple(t.name for t in TOOLSET if t.verb)      # the verbs over Petrophys


def named() -> list:
    """The tools the model is shown, as native tool-calling schemas, from their definitions."""
    return TOOLSET.schemas()


_NUMERIC = {"limit": int, "min_thickness": float, "max_thickness": float, "tolerance": float, "threshold": float, "k": float,
            "min_change": float, "window": int, "max_lag": float, "vcl_max": float, "phie_min": float,
            "vcl_cutoff": float, "phie_cutoff": float, "sw_cutoff": float, "rmf": float, "rmf_temp_f": float,
            "bht_f": float, "td": float}


def arguments(raw) -> dict:
    """The model's arguments as a dict: JSON text or a dict; empty values dropped; numbers sent as text read as numbers."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            raise ToolError(f"the arguments are not JSON ({e.msg}); send an object such as {{\"curves\": [\"PHIE\"]}}") from None
    if not isinstance(raw, dict):
        raise ToolError("the arguments must be an object of named values")
    out = {}
    for k, v in raw.items():
        if v is None or v == [] or (isinstance(v, str) and v.strip().lower() in ("", "null", "none")):
            continue
        if k in _NUMERIC and isinstance(v, str) and re.fullmatch(r"\s*[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?\s*", v):
            v = _NUMERIC[k](float(v))
        if k == "zones" and isinstance(v, bool):              # every zone (fit reads it)
            out[k] = v
            continue
        if k == "statistics" and v is True:                    # the default set
            continue
        if k == "zones" and isinstance(v, int):                # one zone by its number
            v = [v]
        if k in _LISTS:                                     # a list of names: one name as text is a list of one
            if isinstance(v, str) and v.strip().startswith("["):    # a list written as JSON text
                try:
                    v = json.loads(v)
                except json.JSONDecodeError:
                    v = v.strip().strip("[]").replace('"', "").replace("'", "")
            if isinstance(v, str):
                v = [x.strip() for x in v.split(",") if x.strip()]
            if not isinstance(v, list) or not all(isinstance(x, (str, int)) and not isinstance(x, bool) for x in v):
                raise ToolError(f"{k} must be a list of names, e.g. {_LISTS[k]}, not {v!r}")
            if k == "statistics" and [str(x).lower() for x in v] in (["all"], ["*"]):
                continue                                    # "all": the default set
        elif k == "curve" and isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            pass                                            # several curves where one belongs: fit reads it per tool
        elif k in _TEXTS and isinstance(v, list) and len(v) == 1 and isinstance(v[0], str):
            v = v[0]                                        # text sent as a list of one: that text (the mirror of a
            #                                                 list's one name sent as text; question suite B10)
        elif k in _TEXTS and not isinstance(v, str):
            raise ToolError(f"{k} must be text, e.g. {_TEXTS[k]}, not {v!r}")
        elif k in _NUMERIC and (isinstance(v, bool) or not isinstance(v, (int, float))):
            raise ToolError(f"{k} must be a number, not {v!r}")
        out[k] = v
    return out


_LISTS = {"curves": '["PHIE", "SW"]', "zones": '["Z1", "Z3"]', "statistics": '["mean", "median"]', "inputs": '["VCL", "PHIE"]'}
_TEXTS = C.text("C4", "argument_texts")


# --- what a model means by the shapes it sends (from the failed calls of 912 traced investigations) ------------------

_ALL = {"all", "*", "all zones", "each", "every", "every zone", "each zone", "pooled", "true", "yes"}
_NO_CONDITION = {"all", "*", "none", "all samples", "all zones", "whole interval", "full interval", "the whole interval",
                 "entire interval", "pooled", "both finite", "top to bottom", "by depth from top", "everywhere", "zones",
                 "true", "any"}
_SCOPE_WORDS = {"all", "whole", "entire", "every", "each", "full", "both", "pooled", "zone", "zones", "interval",
                "intervals", "sample", "samples", "available", "curve", "curves", "over", "the", "of", "for", "in", "across",
                "formation", "completeness", "data", "valid", "finite", "values", "logged", "and", "with", "within",
                "lithology", "zoned", "gross", "thickness", "always", "everywhere", "incl", "including", "inclusive"}
_ASIDES = ("find", "reason", "note", "notes", "purpose", "why", "comment", "intent")    # words about a call, not arguments
_ZONE_RANGE = re.compile(r"^Z(\d+)\s*(?:-|–|to|\.\.|…)\s*Z?(\d+)$", re.I)


def _zone_list(v):
    """True, "all", "pooled" -> None (all zones); 2 -> Z2; "Z1-Z3" -> Z1, Z2, Z3; "Z1 LIMESTONE" -> Z1."""
    if v is True or v is False or (isinstance(v, str) and v.strip().lower() in _ALL):
        return None
    items = v if isinstance(v, list) else [v]
    if len(items) == 1 and isinstance(items[0], str) and items[0].strip().lower() in _ALL:
        return None
    out = []
    for z in items:
        if isinstance(z, int) and not isinstance(z, bool):
            out.append(f"Z{z}")
            continue
        t = str(z).strip()
        m = _ZONE_RANGE.match(t)
        if m and 0 <= int(m.group(2)) - int(m.group(1)) < 200:
            out += [f"Z{i}" for i in range(int(m.group(1)), int(m.group(2)) + 1)]
            continue
        m = re.match(r"^(Z\d+)\b[\s(]", t + " ", re.I)
        out.append(m.group(1).upper() if m else t)
    return out


def _stat(v: str) -> str:
    return S.statistic_name(v)                              # the summary layer's names (summary.ALIASES)


# statistic names of several words, read as one ("coefficient of variation", "standard deviation")
_STAT_PHRASE = re.compile(r"\b(" + "|".join(sorted((k.replace("_", r"\s+") for k in list(S.ALIASES) + list(S.DERIVATIONS)
                                                     if "_" in k), key=len, reverse=True)) + r")\b", re.I)


_DEFAULT_WORDS = ("default", "none", "null", "")
_NO_COUNT = ("lithology_stats",)                           # the workflow's table has no count statistic (it shows n anyway)


def _plain_args(name: str, a: dict) -> None:
    """statistics given as one string ("mean, median" or "mean median min max") as a list; a count
    asked of a table that always shows it dropped; a baseline or scale given as "default" left to the default; an op
    in words (lt, gte, "less than") as its sign."""
    st = a.get("statistics")
    if isinstance(st, str):
        st = [st]
    if isinstance(st, list):
        two = lambda v: _STAT_PHRASE.sub(lambda m: re.sub(r"\s+", "_", m.group(1)), v)   # one name
        st = [x for v in st for x in (re.split(r"[,;\s]+", two(v).strip()) if isinstance(v, str) else [v]) if x != ""]
        if name in _NO_COUNT:
            st = [x for x in st if str(x).strip().lower() not in ("n", "count")]
        if st:
            a["statistics"] = st
        else:
            a.pop("statistics")
    for k in ("baseline", "scale", "rule"):
        if k in a and (a[k] is None or (isinstance(a[k], str) and a[k].strip().lower() in _DEFAULT_WORDS)):
            a.pop(k)
    if isinstance(a.get("op"), str) and E.op_sign(a["op"]):
        a["op"] = E.op_sign(a["op"])                         # the condition grammar's table (engine.OP_WORDS)


def fit(name: str, args: dict) -> dict:
    """A call's arguments as the tool reads them, from the shapes models send: every zone (true, "all", "pooled"), zone
    numbers and ranges, statistics in any case and their usual names, no condition said in words ("all samples"),
    words about the call (find, reason) left out, one curve where a list belongs, runs given a where, limit 0."""
    a = {k: v for k, v in args.items() if k not in _ASIDES}
    if "zones" in a:
        z = _zone_list(a["zones"])
        if z is None:
            a.pop("zones")
        else:
            a["zones"] = z
    _plain_args(name, a)                                     # spellings whose meaning is plain (each refused call
                                                             #   would be a lost action)
    if isinstance(a.get("statistics"), list):
        a["statistics"] = list(dict.fromkeys(_stat(x) for x in a["statistics"]))
    if isinstance(a.get("where"), str):
        w = a["where"].strip()
        words = re.findall(r"[A-Za-z_]+\d*", w)
        zids = [x.upper() for x in words if re.fullmatch(r"[Zz]\d+", x)]
        scope = [x for x in words if not re.fullmatch(r"[Zz]\d+", x)]
        if w.lower() in _NO_CONDITION or (not re.search(r"[<>=]", w) and words
                                          and all(x.lower() in _SCOPE_WORDS for x in scope)):
            a.pop("where")                                   # "all zones pooled", "all curves over Z2": no condition
            if zids and "zones" not in a:
                a["zones"] = zids
    fn = TOOLS.get(name)
    params = set(inspect.signature(fn).parameters) if fn else set()
    if "curves" in params and "curve" not in params and "curves" not in a and "curve" in a:    # one curve where a list belongs
        c = a.pop("curve")
        a["curves"] = c if isinstance(c, list) else [c]
    if "curve" in params and "curves" not in params and "curve" not in a and isinstance(a.get("curves"), (list, str)):
        cs = a["curves"] if isinstance(a["curves"], list) else [a["curves"]]
        if len(cs) == 1:                                                           # a list of one where one belongs
            a.pop("curves")
            a["curve"] = cs[0]
        elif len(cs) > 1:
            raise ToolError(f"{name} takes one curve, not {len(cs)}; call it once per curve, or stats for several")
    if isinstance(a.get("curve"), list):
        if len(a["curve"]) != 1:
            raise ToolError(f"{name} takes one curve, not {len(a['curve'])}; stats takes several")
        a["curve"] = a["curve"][0]
    if name == "overlap" and ("a" not in a or "b" not in a):                   # the two conditions as a list
        pair_ = next((a.pop(k) for k in ("conditions", "curves", "condition") if isinstance(a.get(k), list)
                      and len(a[k]) == 2), None)
        if pair_ is not None:
            a.setdefault("a", str(pair_[0]))
            a.setdefault("b", str(pair_[1]))
    if name == "runs":
        if isinstance(a.get("where"), str) and "condition" not in a:            # the condition given as where
            a["condition"] = a.pop("where")
        if isinstance(a.get("where"), str) and isinstance(a.get("condition"), str):
            if not re.search(r"\bor\b", a["condition"] + " " + a["where"], re.I):     # 'and' needs no brackets
                a["condition"] = f"{a['condition']} and {a.pop('where')}"
        if isinstance(a.get("limit"), float) and a["limit"].is_integer():
            a["limit"] = int(a["limit"])
        if a.get("limit") == 0:
            a.pop("limit")
    return a


from petroharness.agent.selection import WHOLE_WELL as WHOLE_WELL_TOOLS   # zones do not apply (dropped, said)


def _verb_run(name: str) -> bool:
    """A verb over Petrophys (its run reaches every Petrophys function it serves)."""
    from petroharness.agent.toolset import TOOLSET
    t = TOOLSET.get(name)
    return bool(t is not None and t.verb)


def _tool_named(name: str, raw):
    """A verb asked for one of the other tools by name where its object belongs ({"check": {"what":
    "threshold_exceedance", ...}}: the tool is listed under the verb's own heading): (that tool, the call's other
    arguments); None otherwise. Benchmark N3/N4 and question suite B05: the count asked was refused as "no check"."""
    if not (_verb_run(name) and isinstance(raw, dict)):
        return None
    from petroharness.agent.library_api import _objects
    a = arguments(raw)
    for k in ("what", "property", "parameter", "run"):          # run: {"calibrate": {"run": "core_vs_log"}} (N6: 4)
        v = a.get(k)
        if isinstance(v, str) and v.strip() in TOOLS and v.strip() != name and v.strip() not in _objects(name):
            rest = {x: y for x, y in a.items() if x != k}
            if k == "run" and isinstance(rest.get("args"), dict):      # a run's arguments are the tool's own
                rest = {**{x: y for x, y in rest.items() if x != "args"}, **rest["args"]}
            return v.strip(), rest
    return None


def call(f: Formation, name: str, raw) -> Result:
    """Run one tool call; a ToolError's message is what the model reads back."""
    fn = TOOLS.get(str(name).strip())
    if fn is None:
        raise ToolError(f"no tool {name!r}; tools: {', '.join(TOOLS)}")
    routed = _tool_named(str(name).strip(), raw)
    if routed is not None:                                   # the tool it names, its own call (said, so the next is)
        r = call(f, *routed)
        note = f"({routed[0]} is a tool of its own: run as {{\"{routed[0]}\": {{...}}}})"
        return Result(note + "\n" + r.text, list(r.numbers), [(note, [])] + list(r.rows))
    if getattr(f.view, "reach", "focus") == "well" and isinstance(raw, dict) and raw.get("where") is not None:
        from petroharness.agent import selection
        selection.where_names_stretches(f, raw["where"], raw.get("zones"))   # a stretch written as a condition: zones
    args = fit(name, arguments(raw))
    original = f                                             # the question's formation (what any call writes reaches it)
    merged = []                                              # the union's notes (selection.resolve)
    frame = args.pop("by", None)                             # by lithology: the lithology zones under the user's
    if frame is not None:
        from petroharness.agent import selection
        f = selection.by(f, frame)
    params = [p for p in inspect.signature(fn).parameters if p != "f"]
    if (args.get("zones") and getattr(f.view, "reach", "focus") == "well" and ("zones" not in params or args.get("run"))
            and name not in WHOLE_WELL_TOOLS):
        # a tool that does not read zones itself, or a verb's run: it computes on the selection, focus zones included
        # (a tool that reads the workflow's results for the focus: focus zones as today, elsewhere refused)
        from petroharness.agent import selection
        on, _ = selection.resolve(f, args["zones"])
        if not (on is f and name in selection.FOCUS_ONLY):
            selection.refuse_focus_only(name, f)
            on, _ = selection.resolve(f, args["zones"], force=True, notes=merged)
            f, args = on, {k: v for k, v in args.items() if k != "zones"}
    curated_where = (not args.get("run") and not args.get("search") and _verb_run(name)
                     and "where" not in getattr(fn, "curated_params", {"where"}))
    if (args.get("where") is not None and "where" in params and _verb_run(name)
            and (args.get("run") or (curated_where and getattr(f.view, "reach", "focus") == "well"))):
        # a verb's run on the samples where a condition holds (agent.selection.where_view; reach well only)
        if getattr(f.view, "reach", "focus") != "well":
            raise ToolError(f"{name} takes no where here; select by zones")
        from petroharness.agent import selection
        f, args = selection.where_view(f, str(args["where"])), {k: v for k, v in args.items() if k != "where"}
    unknown = [a for a in args if a not in params]
    args = {k: v for k, v in args.items() if k in params}
    if args.get("zones"):                                    # a unit or a depth range anywhere in the well: the call
        from petroharness.agent import selection             # runs on that selection (docs/designs/zones-and-intervals.md)
        on, zones = selection.resolve(f, args["zones"], notes=merged)
        if on is not f:
            selection.refuse_focus_only(name, f)
            f, args = on, {k: v for k, v in args.items() if k != "zones"}
        elif zones is None:                                  # the interval's own samples: the interval, its own zones
            args = {k: v for k, v in args.items() if k != "zones"}
    held = {n: id(a) for n, a in original.view.calculated.items()} if f is not original else {}
    asked = E.ADVISED.set([])                                # the inputs Petrophys's messages ask for in this call
    try:
        try:
            r = fn(f, **args)
        except ToolError as e:                                   # Petrophys's advice in its refusal: the calls that take it
            E.advised(e)                                         #   (its own error is the refusal's context)
            said = advice(E.ADVISED.get(), name, params, args)
            if said:
                raise ToolError(f"{e} ({said})") from None
            raise
        except TypeError:
            need = [p for p, q in inspect.signature(fn).parameters.items() if p != "f" and q.default is q.empty]
            raise ToolError(f"{name} needs {', '.join(need)}; it takes {', '.join(params)}") from None
        finally:
            if f is not original:                                # what it wrote, for the question's later calls
                from petroharness.agent import selection as _sel
                _sel.carry_back(original, f, [n for n, a in f.view.calculated.items() if held.get(n) != id(a)])
        if getattr(f.view, "selection", None) or merged:         # what the rows of this result are, and what the zones
            from petroharness.agent import selection             #   asked became (an item part of another, joined)
            head = selection.header(f, merged) if getattr(f.view, "selection", None) else selection.merges(f, merged)
            r = Result(head + "\n" + r.text, list(r.numbers), [(head, [])] + list(r.rows))
        if unknown:                                              # run without them, and say so
            note = f"(ignored {', '.join(unknown)}: {name} takes {', '.join(params) or 'no arguments'})"
            r = Result(note + "\n" + r.text, list(r.numbers), [(note, [])] + list(r.rows))
        names = E.ADVISED.get() or []
    finally:                                                 # reset whatever the call raised
        E.ADVISED.reset(asked)
    said = advice(names, name, params, args)               # Petrophys's advice in the result: the calls that take it
    if said:
        line = f"  {said}"
        r = Result(r.text + "\n" + line, list(r.numbers), list(r.rows) + [(line, [])])
    return r


def advice(names: list, name: str, params: list, args: dict) -> str:
    """The calls that take the inputs Petrophys's messages in this call asked for (their Advice inputs, collected by
    engine.advised; library.advice_calls): this tool's own arguments first, then the calculate property (the call's
    own). No sentence is read for them."""
    if not names:
        return ""
    from petroharness.agent.library import advice_calls, kind_of
    try:
        kind = kind_of(args["property"]) if isinstance(args.get("property"), str) else None
    except Exception:  # noqa: BLE001  (not a property: no preference)
        kind = None
    takes = [p for p in params if p not in ("parameters",)]
    if isinstance(args.get("run"), str):                     # a Petrophys function run by name: its own inputs too
        try:
            from petroharness.agent.library_api import lookup
            takes += [p for p in lookup(args["run"]).params if p not in takes]
        except Exception:  # noqa: BLE001  (an unknown function: the tool's own arguments)
            pass
    return advice_calls(list(names), takes=takes, kind=kind)


def known_args(name: str, args: dict) -> dict:
    """The arguments a tool takes (the others are ignored by call, with a note)."""
    fn = TOOLS.get(name)
    params = set(inspect.signature(fn).parameters) - {"f"} if fn else set()
    return {k: v for k, v in args.items() if k in params}
