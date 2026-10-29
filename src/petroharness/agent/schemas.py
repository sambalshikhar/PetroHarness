"""The tools as the model sees them (native tool-calling schemas) and the door a model's call goes through:
argument names and values read, unknown arguments said back."""
from __future__ import annotations

import inspect
import json
import re

from petroharness.agent.engine import STATISTICS, Formation, Result, ToolError
from petroharness.well import summary as S
from petroharness.agent.tools import TOOLS
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)

CONDITION = C.text("C4", "condition")
_ZONES = {"type": "array", "items": {"type": "string"}, "description": "zone ids, e.g. [\"Z2\", \"Z3\"]; all zones when left out"}
_WHERE = {"type": "string", "description": "only the samples where " + CONDITION}
_STATISTICS = {"type": "array", "items": {"type": "string"},
               "description": f"which statistics: {', '.join(STATISTICS)}, or any percentile p1-p99; left out: n, mean, "
                              "median, p10, p90, min, max (and geo_mean where the values are positive and span more "
                              "than two orders of magnitude)"}


def _fn(name: str, description: str, properties: dict, required: list) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": properties, "required": required}}}


D = C.text("C4", "tool_descriptions")    # each tool's description (src/petroharness/agent/components/C4_tools)
NAMED = [
    _fn("stats", D["stats"],
        {"curves": {"type": "array", "items": {"type": "string"}, "description": "curve names, e.g. [\"PHIE\", \"SW\"]"},
         "zones": _ZONES,
         "statistics": _STATISTICS,
         "where": _WHERE}, ["curves"]),
    _fn("runs", D["runs"],
        {"condition": {"type": "string", "description": CONDITION},
         "zones": _ZONES,
         "limit": {"type": "integer", "description": "how many of the longest runs to list (20)"},
         "min_thickness": {"type": "number", "description": "only runs at least this thick"},
         "max_thickness": {"type": "number", "description": "only runs at most this thick (thin beds)"}}, ["condition"]),
    _fn("compare", D["compare"],
        {"a": {"type": "string", "description": "a curve, e.g. PHIE"}, "b": {"type": "string", "description": "a curve, e.g. PHIE_CC"},
         "zones": _ZONES, "tolerance": {"type": "number", "description": "report the share of samples where |a - b| exceeds it"},
         "where": _WHERE}, ["a", "b"]),
    _fn("overlap", D["overlap"],
        {"a": {"type": "string", "description": "condition A: " + CONDITION},
         "b": {"type": "string", "description": "condition B, in the same grammar"},
         "zones": _ZONES,
         "limit": {"type": "integer", "description": "how many runs of each set to list before cutting to the thickest (12)"}},
        ["a", "b"]),
    _fn("profile", D["profile"],
        {"curve": {"type": "string", "description": "a curve, e.g. PHIE"}, "zones": _ZONES, "statistics": _STATISTICS,
         "where": _WHERE}, ["curve"]),
    _fn("section", D["section"],
        {"key": {"type": "string", "description": "the section key exactly as the description lists it (family.section)"}},
        ["key"]),
    _fn("step", D["step"],
        {"name": {"type": "string", "description": "the step name as the description lists it, e.g. saturation"}}, ["name"]),
]

_ZONES_OPT = {"type": "array", "items": {"type": "string"}, "description": "only these zones' rows (all when left out)"}
_CURVE = {"type": "string", "description": "a curve, e.g. DTC"}
_CURVES = {"type": "array", "items": {"type": "string"}, "description": "curve names, e.g. [\"GR\", \"VCL\"]"}
NAMED += [
    _fn("lithology_stats", D["lithology_stats"], {"curves": _CURVES, "statistics": {"type": "array", "items": {"type": "string"}},
                                                                 "zones": _ZONES_OPT}, ["curves"]),
    _fn("zone_contrast", D["zone_contrast"],
        {"curve": _CURVE, "inputs": _CURVES, "zones": _ZONES_OPT}, ["curve"]),
    _fn("curve_order", D["curve_order"], {"curves": _CURVES, "relation": {"type": "string", "enum": ["decreasing", "increasing", "between"]},
                                               "zones": _ZONES_OPT}, ["curves"]),
    _fn("threshold_exceedance", D["threshold_exceedance"],
        {"curve": _CURVE, "threshold": {"type": "number"}, "op": {"type": "string", "enum": [">", ">=", "<", "<="]},
         "absolute": {"type": "boolean"}, "zones": _ZONES_OPT}, ["curve"]),
    _fn("spike_flags", D["spike_flags"],
        {"curves": _CURVES, "k": {"type": "number"}, "baseline": {"type": "string", "enum": ["zoned", "interval", "zone"]},
         "zones": _ZONES_OPT}, ["curves"]),
    _fn("adjacent_jumps", D["adjacent_jumps"],
        {"curve": _CURVE, "threshold": {"type": "number"}, "zones": _ZONES_OPT}, ["curve", "threshold"]),
    _fn("vertical_sequence", D["vertical_sequence"],
        {"curves": _CURVES, "min_change": {"type": "number"}}, []),
    _fn("pay_summary", D["pay_summary"], {}, []),
    _fn("core_vs_log", D["core_vs_log"], {"zones": _ZONES_OPT}, []),
    _fn("zone_classes", D["zone_classes"], {"topic": {"type": "string", "description": "a classification topic, e.g. hc_indicators, porosity_quality, flow_units"}}, ["topic"]),
    _fn("formation_summary", D["formation_summary"], {"curves": _CURVES, "statistics": _STATISTICS}, []),
    _fn("data_record", D["data_record"],
        {"zones": _ZONES_OPT}, []),
    _fn("unit_roles", D["unit_roles"], {"zones": _ZONES_OPT}, []),
]

# a least-squares line of one curve on another or on depth (relations, matrix lines, depth trends)
CROSSPLOT = _fn("crossplot", D["crossplot"],
                {"y": {"type": "string", "description": "the curve on the vertical axis, e.g. RHOB"},
                 "x": {"type": "string", "description": "a curve, or DEPTH, e.g. NPHI"},
                 "zones": _ZONES, "log_y": {"type": "boolean", "description": "fit log10(y)"},
                 "log_x": {"type": "boolean", "description": "fit against log10(x)"}, "where": _WHERE}, ["y", "x"])


# the descriptions of the lookups whose output changed (signed compare shares, the per-zone spike
# screen) and the zone selector (lithology names, ALL)
V9_DESCRIPTIONS = C.text("C4", "v9_descriptions")
V9_ZONES = C.text("C4", "v9_zones")


# depth matching between logs by cross-correlation
LAG = _fn("lag_correlation", D["lag_correlation"],
          {"curves": _CURVES, "max_lag": {"type": "number", "description": "search half-width in depth units (3 m when "
                                                                            "left out)"}, "zones": _ZONES_OPT}, ["curves"])


def named() -> list:
    """The lookups the model is shown: NAMED, the crossplot and the lag correlation, with their descriptions."""
    out = NAMED + [CROSSPLOT, LAG]
    import copy
    out = copy.deepcopy(out)
    for t in out:
        fn = t["function"]
        fn["description"] = V9_DESCRIPTIONS.get(fn["name"], fn["description"])
        z = fn["parameters"]["properties"].get("zones")
        if z is not None:
            z["description"] = V9_ZONES
        b = fn["parameters"]["properties"].get("baseline")
        if fn["name"] == "spike_flags" and b is not None:
            b["enum"] = ["zone", "zoned", "interval"]
            fn["parameters"]["properties"]["scale"] = {"type": "string", "enum": ["linear", "log10"]}
            fn["parameters"]["properties"]["window"] = {"type": "integer", "description": "rolling window in samples"}
    return out


_NUMERIC = {"limit": int, "min_thickness": float, "max_thickness": float, "tolerance": float, "threshold": float, "k": float,
            "min_change": float, "window": int, "max_lag": float}


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


_OP_WORDS = {"gt": ">", "greater": ">", "greater than": ">", "above": ">", "ge": ">=", "gte": ">=", "at least": ">=",
             "lt": "<", "less": "<", "less than": "<", "below": "<", "le": "<=", "lte": "<=", "at most": "<="}
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
    if isinstance(a.get("op"), str) and a["op"].strip().lower() in _OP_WORDS:
        a["op"] = _OP_WORDS[a["op"].strip().lower()]


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


def call(f: Formation, name: str, raw) -> Result:
    """Run one tool call; a ToolError's message is what the model reads back."""
    fn = TOOLS.get(str(name).strip())
    if fn is None:
        raise ToolError(f"no tool {name!r}; tools: {', '.join(TOOLS)}")
    args = fit(name, arguments(raw))
    params = [p for p in inspect.signature(fn).parameters if p != "f"]
    unknown = [a for a in args if a not in params]
    args = {k: v for k, v in args.items() if k in params}
    try:
        r = fn(f, **args)
    except TypeError:
        need = [p for p, q in inspect.signature(fn).parameters.items() if p != "f" and q.default is q.empty]
        raise ToolError(f"{name} needs {', '.join(need)}; it takes {', '.join(params)}") from None
    if unknown:                                              # run without them, and say so
        note = f"(ignored {', '.join(unknown)}: {name} takes {', '.join(params) or 'no arguments'})"
        r = Result(note + "\n" + r.text, list(r.numbers), [(note, [])] + list(r.rows))
    return r


def known_args(name: str, args: dict) -> dict:
    """The arguments a tool takes (the others are ignored by call, with a note)."""
    fn = TOOLS.get(name)
    params = set(inspect.signature(fn).parameters) - {"f"} if fn else set()
    return {k: v for k, v in args.items() if k in params}
