"""Every public Petrophys function, reachable from the verb it serves (docs/TOOLS.md).

The registry is generated from the installed library: each public function of its interpretation, evaluation and
preprocessing packages, with its signature, its docstring's summary and parameter lines, and the verb its package
serves (PACKAGES). A function added to Petrophys appears here with no change to the harness.

One binder calls any of them on the question's interval. The model names each input; the binder reads it as the
kind Petrophys declares for it (petrophys.function_schema: a curve name for a curve gives its values, a condition a
mask, a choice is checked against its choices) and adds only the question's scope: a copy of the prepared well, the
interval's window and depths. Every other input keeps Petrophys's default. A required input left out is asked for,
with what this interval offers for it (the curves Petrophys reads as its quantity, the record's value of that name).
A function Petrophys declares samplewise is applied at each sample. Each input is said with its source.

Outputs: an array over the interval becomes a curve of the question (<FUNCTION>_<PART>), a number a value, a
dataclass, dict or tuple its parts, a table its first rows.
"""
from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import pkgutil
import re
import warnings
from functools import lru_cache
from typing import Optional

import numpy as np

from petroharness.agent import library as L
from petroharness.agent import engine as E
from petroharness.agent.engine import Formation, Out, Result, ToolError, advised, said_whole
from petroharness.well import summary as S

# Petrophys package -> the verb whose requests it serves (the first prefix that matches wins)
PACKAGES = (("preprocessing.quality", "check"), ("preprocessing.imputation", "check"),
            ("preprocessing.normalization", "check"), ("interpretation.core_analysis.depth_matching", "check"),
            ("evaluation.sensitivity", "what_if"), ("evaluation.uncertainty", "what_if"),
            ("interpretation.core_analysis", "calibrate"), ("interpretation.nmr.calibration", "calibrate"),
            ("interpretation.saturation.height", "calibrate"), ("interpretation.saturation.sonic", "calibrate"),
            ("interpretation.rock_physics", "calibrate"),
            ("interpretation.electrical.rw", "estimate"), ("interpretation.electrical.cementation", "estimate"),
            ("interpretation.electrical.rmf", "estimate"), ("interpretation.temperature", "estimate"),
            ("interpretation.lithology.apparent_matrix", "estimate"), ("interpretation.lithology.matrix", "estimate"),
            ("interpretation.clay_volume.rcl", "estimate"), ("interpretation.clay_volume.nd_method", "estimate"),
            ("interpretation.lithology", "classify"), ("interpretation.geochemistry", "classify"),
            ("evaluation.flow_units", "classify"), ("evaluation.rock_quality", "classify"), ("evaluation.mhi", "classify"),
            ("evaluation.zonation", "classify"), ("evaluation.heterogeneity", "classify"),
            ("evaluation.net_pay", "summarize"), ("evaluation.summaries", "summarize"),
            ("evaluation.volumetrics", "summarize"), ("evaluation.bvw", "summarize"),
            ("interpretation", "calculate"))
SKIP = ("._", "borehole_imaging", ".classification")    # private modules; image logs (no LAS curves); label tables
_PATH = re.compile(r"\bPath(?:Like)?\b")                 # a parameter typed as a file or folder path
MAX_FOUND = 8


@dataclasses.dataclass
class Fn:
    name: str               # the function's name
    path: str               # its module, petrophys.<...>
    verb: str
    summary: str            # the docstring's first sentence
    params: dict            # name -> (annotation text, default or inspect.Parameter.empty, description)
    returns: str = ""       # the docstring's Returns section, in short
    kinds: dict = dataclasses.field(default_factory=dict)  # name -> Petrophys's declaration (function_schema)
    samplewise: bool = False                                # Petrophys declares it computes one sample

    @property
    def qualified(self) -> str:
        return f"{self.path}.{self.name}"

    def call(self):
        return getattr(importlib.import_module(self.path), self.name)


def _param_docs(doc: str) -> dict:
    """A numpy-style docstring's Parameters section: name -> its description (first lines). A line naming several
    parameters ("a, b : float") gives each of them the description under it."""
    out, cur = {}, []
    m = re.search(r"Parameters\n\s*-{3,}\n(.*?)(?:\n\s*\n\s*(?:Returns|Raises|Notes|Examples|See Also|Yields)\n|\Z)", doc, re.S)
    for line in (m.group(1).splitlines() if m else []):
        h = re.match(r"^\s{0,4}(\*{0,2}\w+(?:\s*,\s*\*{0,2}\w+)*)\s*(?::.*)?$", line)
        if h and not line.startswith(" " * 6):
            cur = [n.strip().lstrip("*") for n in h.group(1).split(",")]
            out.update({n: "" for n in cur})
        elif cur and line.strip():
            for n in cur:
                out[n] = (out[n] + " " + line.strip()).strip()[:200]
    return out


def _verb(module: str) -> Optional[str]:
    rel = module.split(".", 1)[1]
    return next((v for p, v in PACKAGES if rel.startswith(p)), None)


@lru_cache(maxsize=None)
def registry() -> tuple:
    """Every public function of the library's interpretation, evaluation and preprocessing packages, with its verb.
    A function that needs a file or folder path is left out, and an optional path parameter is not offered: a call
    never reads or writes a file of the server's."""
    import petrophys
    from petrophys import function_schema
    out = []
    for m in pkgutil.walk_packages(petrophys.__path__, "petrophys."):
        if not m.name.startswith(("petrophys.interpretation", "petrophys.evaluation", "petrophys.preprocessing")) \
                or any(s in m.name for s in SKIP):
            continue
        verb = _verb(m.name)
        if verb is None:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                mod = importlib.import_module(m.name)
            except Exception:  # noqa: BLE001  (a module that will not import offers nothing)
                continue
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if name.startswith("_") or fn.__module__ != mod.__name__:
                continue
            doc = inspect.getdoc(fn) or ""
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            pdoc = _param_docs(doc)
            params = {p: (str(q.annotation) if q.annotation is not q.empty else "", q.default, pdoc.get(p, ""))
                      for p, q in sig.parameters.items() if q.kind not in (q.VAR_POSITIONAL, q.VAR_KEYWORD)}
            paths = {p for p, (ann, _, _) in params.items() if _PATH.search(ann)}
            if any(params[p][1] is inspect.Parameter.empty for p in paths):
                continue                    # it reads or writes a file: the question's data come from the well only
            params = {p: v for p, v in params.items() if p not in paths}      # an optional path keeps its default
            summary = re.split(r"(?<=\.)\s", doc.strip().split("\n\n")[0].replace("\n", " "), maxsplit=1)[0][:160]
            r = re.search(r"Returns\n\s*-{3,}\n(.*?)(?:\n\s*\n\s*[A-Z][a-z]+\n\s*-{3,}|\Z)", doc, re.S)
            returns = " ".join(ln.strip() for ln in (r.group(1).splitlines() if r else []) if ln.strip())[:300]
            decl = function_schema.declaration(fn)
            kinds = {p: k for p, k in (decl.parameters if decl else {}).items() if p not in paths}
            out.append(Fn(name, m.name, verb, summary, params, returns, kinds, bool(decl and decl.samplewise)))
    return tuple(out)


def functions(verb: str) -> list:
    return [fn for fn in registry() if fn.verb == verb]


def lookup(name: str, verb: Optional[str] = None) -> Fn:
    n = str(name or "").strip().rsplit(".", 1)[-1]
    hits = [fn for fn in registry() if fn.name == n]
    if not hits:
        raise ToolError(f"no Petrophys function {name!r}; search lists them, e.g. {{\"{verb or 'calculate'}\": "
                        f"{{\"search\": \"<words>\"}}}}")
    return next((fn for fn in hits if fn.verb == verb), hits[0])


# --- find -----------------------------------------------------------------------------------------------------------

def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1}


def _takes(d) -> str:
    """What a parameter takes, in a few words, from its declaration."""
    if d is None:
        return "undeclared"
    unit = f", {d.unit}" if d.unit else ""
    return {"curve": f"curve{' ' + d.curve if d.curve else ''}{unit}",
            "curve_name": f"curve name{'s' if d.many else ''}{' (' + d.curve + ')' if d.curve else ''}",
            "value": f"number{unit}", "values": f"numbers{unit}",
            "choice": ("any of " if d.many else "one of ") + "/".join(d.choices),
            "switch": "true or false", "per_zone": "one value per zone", "mask": "condition",
            "window": d.role or "depth", "text": "text"}.get(d.kind, d.kind)


COMPUTES_SHOWN = 3          # the functions a "not in this record" note names for a quantity Petrophys may compute


def computes(query: str, k: int = COMPUTES_SHOWN) -> list:
    """The functions whose name holds every word of the query that is not a stop word ("irreducible water
    saturation": estimate_swirr ...), best first, as "verb name"; [] when none does or the registry cannot load."""
    words = _words(query) - {"of", "the", "and", "in", "from", "at", "to", "for"}
    if not words:
        return []
    try:
        fns = registry()
    except Exception:  # noqa: BLE001  (no Petrophys to search: no names)
        return []
    scored = []
    for fn in fns:
        name, text = _words(fn.name.replace("_", " ")), _words(fn.name.replace("_", " ") + " " + fn.summary)
        if words <= text:
            scored.append((-(3 * len(words & name) + len(words & text)), fn.name, fn.verb))
    return [f"{verb} {name}" for _, name, verb in sorted(scored)[:k]]


def _score(words: set, fn) -> int:
    """How well a function matches the words: its name's words count three times, its summary's and parameters' once."""
    text = _words(fn.name.replace("_", " ") + " " + fn.summary + " " + " ".join(fn.params))
    return 3 * len(words & _words(fn.name.replace("_", " "))) + len(words & text)


def best_verb(query: str) -> str:
    """The verb of the function the words match best: a search that names no verb runs under it (calculate, the
    verb that recomputes, when none matches)."""
    words = _words(query)
    best = sorted(((-_score(words, fn), fn.name, fn.verb) for fn in registry() if _score(words, fn)), key=lambda x: x[:2])
    return best[0][2] if best else "calculate"


def find(f: Formation, verb: str, query: str) -> Result:
    """The functions matching the words: this verb's first, then any other verb's that match better (Petrophys files
    some by the property they compute: gas detection sits with porosity)."""
    words = _words(query)
    scored = []
    for fn in registry():
        score = _score(words, fn)
        if score:
            scored.append((score + (2 if fn.verb == verb else 0), fn))
    scored.sort(key=lambda s: (-s[0], s[1].name))
    out = Out(f)
    total = len(functions(verb))
    if not scored:
        out.add(f"no {verb} function of Petrophys matches {query!r} (of {total}); try other words, or one of: "
                + ", ".join(sorted(fn.name for fn in functions(verb))[:40]))
        return out.result()
    out.add(f"{verb}: Petrophys functions matching {query!r} ({len(scored)} found; {total} serve {verb}); run one with "
            f"{{\"{verb}\": {{\"run\": \"<name>\", \"args\": {{...}}}}}}")
    for _, fn in scored[:MAX_FOUND]:
        scope = ("well", "depth", "window")
        need = [_facts(f, fn, p) for p, (ann, d, _) in fn.params.items()
                if d is inspect.Parameter.empty and (fn.kinds.get(p) is None or fn.kinds[p].kind not in scope)]
        opt = [_facts(f, fn, p) for p, (ann, d, _) in fn.params.items()
               if d is not inspect.Parameter.empty and (fn.kinds.get(p) is None or fn.kinds[p].kind not in scope)]
        takes = [q for q, d in fn.kinds.items() if d.kind == "well"]
        well = ("" if not takes else " It reads the well's curves itself." if fn.params[takes[0]][1] is
                inspect.Parameter.empty else " It reads the well's curves itself unless given curves.")
        out.add(f"  {fn.name}{'' if fn.verb == verb else ' (' + fn.verb + ')'}: {fn.summary}{well} Needs "
                f"{'; '.join(need) or 'nothing'}. Optional: {'; '.join(opt[:8]) or '-'}"
                + ("; ..." if len(opt) > 8 else ""))
    return out.result()


# --- binding: the model names each input; code adds the question's scope --------------------------------------------

def _record_params(f: Formation) -> dict:
    """The record's numeric parameters by name (the last step that states one), with the step."""
    out = {}
    for m in f.inv.methods:
        for k, v in (m.parameters or {}).items():
            if L._num(v):
                out[str(k)] = (float(v), m.step)
    return out


def _depths(f: Formation) -> np.ndarray:
    """The interval's sample depths, in the LAS depth unit (what Petrophys reads)."""
    return np.asarray(f.view.prep.depth, dtype=float)[f.view.mask]


def _curve_values(f: Formation, name: str) -> Optional[np.ndarray]:
    """The interval values of a curve of this well, or of DEPTH (the sample depths); None for another name."""
    c = str(name).strip().upper()
    if c == "DEPTH":
        return _depths(f)
    if c in f.inv.curves:
        v = f.view.values(c)
        return None if v is None else np.asarray(v, dtype=float)
    return None


def _condition(f: Formation, text: str) -> Optional[np.ndarray]:
    from petroharness.agent import engine as E
    try:
        sel = E.select(f, text)
    except Exception:  # noqa: BLE001  (not a condition)
        return None
    mask = getattr(sel, "mask", None)
    return None if mask is None else np.asarray(mask, dtype=bool)


def _same_scale(declared: Optional[str], recorded: Optional[str]) -> bool:
    """Whether values in unit `recorded` can go where Petrophys declares `declared`, as they are: the same unit, or
    units Petrophys's unit registry gives the same factor (v/v and fraction; not pu and fraction). Units the registry
    does not relate are not stopped."""
    a, b = str(declared or "").strip().lower(), str(recorded or "").strip().lower()
    if not a or not b or a == b:
        return True
    from petrophys.model.units import UnitRegistry as R
    for table in (R.DEPTH_TO_M, R.DENSITY_TO_G_CM3, R.POROSITY_TO_FRACTION, R.SLOWNESS_TO_US_FT,
                  R.RESISTIVITY_TO_OHM_M):
        factors = {str(k).lower(): v for k, v in table.items()}
        if a in factors and b in factors:
            return factors[a] == factors[b]
    return True


def _here(f: Formation, curve: str) -> list:
    """The curves of this well Petrophys reads as `curve`: the curve itself, and any its alias map counts as it (RT
    and RDEP for deep resistivity), each with its unit."""
    from petrophys.preprocessing.standardization.alias_map import get_standard_mnemonic
    target = str(curve).upper()
    out = []
    for c, info in f.inv.curves.items():
        if (c == target or get_standard_mnemonic(c) == target) and f.view.available(c):
            out.append(f"{c} {info.unit}".strip() if getattr(info, "unit", "") else c)
    return out


def _shown_default(value) -> str:
    """A default as the model reads it, the same in every process: a set's members in order (a set's own repr follows
    the process's string hashing, so a prompt showing it differed from run to run)."""
    if isinstance(value, (set, frozenset)):
        return "{" + ", ".join(repr(x) for x in sorted(value, key=repr)) + "}"
    return repr(value)


@lru_cache(maxsize=None)
def _numbers_of(quantity: str) -> frozenset:
    """The names Petrophys's functions give a number of this quantity (rcl, r_shale: shale resistivity)."""
    return frozenset(p for fn in registry() for p, d in fn.kinds.items()
                     if d is not None and d.kind in ("value", "values") and str(d.curve or "").upper() == quantity.upper())


def _facts(f: Formation, fn: Fn, p: str) -> str:
    """One input as the model chooses it: what it takes (kind, unit, choices), the curves here Petrophys reads as its
    quantity, the record's value of that name, Petrophys's default."""
    d, default = fn.kinds.get(p), fn.params[p][1]
    rec = _record_params(f)
    same = []
    if d is not None and d.curve and d.kind in ("value", "values"):    # a number of a quantity: no curve is asked
        parts = [("numbers" if d.kind == "values" else "number") + (f", {d.unit}" if d.unit else "")]
        same = [n for n in sorted(_numbers_of(d.curve)) if n in rec and n != p]   # the record's, under other names
    elif d is not None and d.curve:
        from petrophys.preprocessing.standardization.alias_map import find_curve_type
        here = _here(f, d.curve)
        what = find_curve_type(d.curve) or d.curve
        kind = {"curve": "curve", "curve_name": "curve names" if d.many else "curve name"}[d.kind]
        parts = [kind + (f", {d.unit}" if d.unit else ""),
                 f"{what} here: {', '.join(here)}" if here else f"no {what} curve here"]
    else:
        parts = [_takes(d)]
    if p in rec:
        parts.append(f"the record's: {L._shown(rec[p][0])} ({rec[p][1]})")
    parts += [f"the record's {n}: {L._shown(rec[n][0])} ({rec[n][1]})" for n in same[:2]]
    if default is not inspect.Parameter.empty and default is not None and not callable(default):
        parts.append(f"default {_shown_default(default)}"[:40])
    return f"{p} ({'; '.join(parts)})"


def _asked(f: Formation, fn: Fn, p: str, v):
    """A value the call gives, as the parameter's declared kind takes it."""
    d = fn.kinds.get(p)
    kind = d.kind if d else None
    if kind in ("curve", "mask") and isinstance(v, str):
        values = _curve_values(f, v)
        if kind == "mask":
            values = (values > 0.5) if values is not None else _condition(f, v)
        if values is None:
            raise ToolError(f"{fn.name}: {v!r} is not a curve here" + (" nor a condition" if kind == "mask" else "")
                            + f"; {_facts(f, fn, p)}")
        name = str(v).strip().upper()
        unit = getattr(f.inv.curves.get(name), "unit", "") if name in f.inv.curves else ""
        if kind == "curve" and not _same_scale(d.unit, unit):
            raise ToolError(f"{fn.name}: {p} takes {d.unit}; {name} is in {unit}")
        return values
    if kind == "curve_name":
        names = list(v) if isinstance(v, (list, tuple)) else [v]
        if d.many:
            return names
        if len(names) != 1:
            raise ToolError(f"{fn.name}: {p} takes one curve name, not {len(names)}")
        return names[0]
    if kind == "choice":
        asked = list(v) if d.many and isinstance(v, (list, tuple)) else [v]
        hits = [next((c for c in d.choices if str(c).lower() == str(a).strip().lower()), None) for a in asked]
        if None in hits:
            keep = (f"; leave it out for Petrophys's default ({fn.params[p][1]!r})"
                    if fn.params[p][1] is not inspect.Parameter.empty else "")
            raise ToolError(f"{fn.name}: {p} is {'any' if d.many else 'one'} of {', '.join(d.choices)}, "
                            f"not {v!r}{keep}")
        return hits if d.many else hits[0]
    if kind == "text" and d.many:
        return list(v) if isinstance(v, (list, tuple)) else [v]
    if kind in ("value", "window") and isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            raise ToolError(f"{fn.name}: {p} takes {_takes(d)}, not {v!r}") from None
    if kind == "switch" and isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "on")
    return v


DOOR_ARGS = ("zones", "where", "by", "label")            # a call's own arguments (schemas.call), not a function's


def bind(f: Formation, fn: Fn, args: dict) -> tuple:
    """The call's keyword arguments and the source of each -> (kwargs, sources). The model names each input; code
    reads it as the kind Petrophys declares (petrophys.function_schema) and adds the question's scope: a copy of the
    prepared well (when the function requires it, or the call gives no curve of values: it then reads its curves
    itself), the interval's window, and its depths beside the curves the call gives. Every other input keeps
    Petrophys's default; a required input the call leaves out is asked for, with what this interval offers for it."""
    args = {str(k): v for k, v in (args or {}).items()}
    unknown = [k for k in args if k not in fn.params]
    door = [k for k in unknown if k in DOOR_ARGS]           # the call's own arguments, written inside args
    if door:
        fixed = {"run": fn.name, "args": {k: v for k, v in args.items() if k in fn.params},
                 **{k: args[k] for k in door}}
        other = [k for k in unknown if k not in door]
        raise ToolError(f"{', '.join(door)} {'goes' if len(door) == 1 else 'go'} beside run, not inside args"
                        + (f", and {fn.name} takes no {', '.join(other)}" if other else "")
                        + f": send {json.dumps({fn.verb: fixed}, default=str)}")
    if unknown:
        raise ToolError(f"{fn.name} takes {', '.join(fn.params)}; not {', '.join(unknown)}. The call's shape: "
                        f"{{\"run\": \"{fn.name}\", \"args\": {{<the function's arguments>}}, \"label\": \"<name>\"}}")
    arrays = any(fn.kinds.get(p) is not None and fn.kinds[p].kind == "curve" and isinstance(v, str)
                 for p, v in args.items())
    kw, src, missing = {}, [], []
    for p, (ann, default, doc) in fn.params.items():
        d = fn.kinds.get(p)
        kind = d.kind if d else None
        required = default is inspect.Parameter.empty
        if kind == "well":
            if p in args:
                src.append("well: the prepared well, not the name given")
            if required or not arrays:
                kw[p] = L.scratch_well(f)
                src.insert(0, "well (the prepared well)")
        elif p in args and isinstance(args[p], str) and args[p].strip().lower() == "default" and not required:
            src.append(f"{p} Petrophys's default ({_shown_default(default)}, asked)")      # the word asks for the default itself
        elif p in args:
            kw[p] = _asked(f, fn, p, args[p])
            src.append(f"{p} {args[p]} (asked)")
        elif kind == "window":
            kw[p] = float(_depths(f).min() if d.role == "top" else _depths(f).max())
            src.append(f"{p} (the interval's)")
        elif kind == "depth" and (required or arrays):
            kw[p] = _depths(f)
            src.append(f"{p} (the interval's)")
        elif kind == "choice" and getattr(d, "role", None) == "lithology":    # the rock's lithology: the record's
            value, said = _record_lithology(f, fn, p)
            if value is not _UNSET:
                kw[p] = value
            src.append(f"{p} {said}")
        elif kind == "choice" and not required and default is not None:     # a choice left to Petrophys: said
            src.append(f"{p} {_shown_default(default)} (Petrophys's default; {'any' if d.many else 'one'} of "
                       f"{'/'.join(str(c) for c in d.choices)})")
        elif required:
            missing.append(p)
    curves = [p for p in kw if fn.kinds.get(p) is not None and fn.kinds[p].kind == "curve"]
    numbers = [p for p in curves if isinstance(kw[p], (int, float)) and not isinstance(kw[p], bool)]
    if numbers and len(numbers) < len(curves):          # one call's values are the same samples: all curves, or a point
        raise ToolError(f"{fn.name}: {', '.join(p for p in curves if p not in numbers)} "
                        f"{'is a curve' if len(curves) - len(numbers) == 1 else 'are curves'} over the interval, so "
                        + "; ".join(f"{p} must be one too, not the number {args[p]!r}: {_facts(f, fn, p)}"
                                    for p in numbers))
    if missing:          # the call to send again: what this call gave, with the inputs it left out (in one args)
        whole = [f"{json.dumps(k)}: {json.dumps(v, default=str)}" for k, v in args.items()]
        raise ToolError(f"{fn.name} needs " + "; ".join(_facts(f, fn, p) for p in missing)
                        + f". Send the whole call again, every input in one args: {{\"run\": \"{fn.name}\", "
                        + "\"args\": {" + ", ".join(whole + [f'\"{p}\": ...' for p in missing]) + "}}")
    return kw, src


# --- outputs --------------------------------------------------------------------------------------------------------

def _parts(value, prefix: str = "", depth: int = 0) -> list:
    """(label, value) pairs of a result: a dataclass's fields, a dict's items, a tuple's members, an object's public
    attributes, down two levels."""
    if depth > 2:
        return [(prefix, value)]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        items = [(f.name, getattr(value, f.name)) for f in dataclasses.fields(value)]
    elif isinstance(value, dict):
        items = list(value.items())
    elif isinstance(value, (tuple, list)) and value and not isinstance(value, str):
        items = [(str(i), x) for i, x in enumerate(value)]
    elif hasattr(value, "__dict__") and not isinstance(value, (np.ndarray, type)) and type(value).__module__.startswith("petrophys"):
        items = [(k, v) for k, v in vars(value).items() if not k.startswith("_")]
    else:
        return [(prefix, value)]
    out = []
    for k, v in items:
        out += _parts(v, f"{prefix}.{k}" if prefix else str(k), depth + 1)
    return out


def _label(fn: Fn, part: str, label: Optional[str], whole: bool = False) -> str:
    """The curve name of a result part: the call's label (else the function's name) and the part's, cut to 10
    characters unless `whole` (two parts of one result that start alike: the pore pressure and its mud-weight form)."""
    base = (label or fn.name).upper()
    base = re.sub(r"[^A-Z0-9]+", "_", base).strip("_")[:20]
    p = re.sub(r"[^A-Z0-9]+", "_", part.upper()).strip("_")[:None if whole else 10]
    name = L.joined_name(base, p) if p else base       # the part named once (library.joined_name)
    return name if re.match(r"[A-Z]", name) else f"X{name}"


class _ByLithology(np.ndarray):
    """A lithology choice filled per sample (one option per interval sample, None where no option names the sample's
    rock): run calls the function once per lithology (_by_lithology)."""


_UNSET = object()          # a lithology parameter the record cannot fill: left at Petrophys's default, said


def _gaps(gaps: dict, default) -> str:
    """The samples a lithology fill leaves at Petrophys's default, by their rock ("" when none)."""
    if not gaps:
        return ""
    rocks = ", ".join(f"{v} {k if k == 'no lithology recorded' else k + ', no option names it'}"
                      for k, v in sorted(gaps.items(), key=lambda kv: -kv[1]))
    at = f"at Petrophys's default {_shown_default(default)}" if default is not inspect.Parameter.empty else "left empty"
    return f"; {sum(gaps.values())} samples {at}: {rocks}"


def _record_lithology(f: Formation, fn: Fn, p: str) -> tuple:
    """A parameter Petrophys declares to take the rock's lithology (role "lithology"), left unset: each sample's option
    from the record (library.sample_lithology: the sample's rock, taken to an option by Petrophys). One option over
    these samples: that option. Several: per sample (_ByLithology); run calls the function once per lithology and puts
    a per-sample result together, or gives each lithology's result. None recorded, or none an option names: the
    parameter is left at Petrophys's default (_UNSET). (value, what the Inputs line says)."""
    d, default = fn.kinds[p], fn.params[p][1]
    choice, counts, gaps, basis = L.sample_lithology(f, [str(c).lower() for c in d.choices])
    if not counts:
        why = ", ".join(gaps) or "no lithology recorded"
        return _UNSET, f"{_shown_default(default)} (Petrophys's default: no option of {p} names the rock here: {why})"
    n = int(choice.size)
    shares = ", ".join(f"{k} {m} of {n} samples" for k, m in sorted(counts.items(), key=lambda kv: -kv[1]))
    if len(counts) == 1 and not gaps:
        one = next(iter(counts))
        return ([one] if d.many else one), f"{one} (the record's lithology over these samples: {basis})"
    return choice.view(_ByLithology), f"each lithology of these samples ({shares}{_gaps(gaps, default)}; {basis})"


def _by_lithology(fn: Fn, call, kw: dict) -> tuple:
    """call once per lithology of the per-sample lithology choices (_ByLithology; several such parameters: once per
    combination); a sample no option names takes the parameter's default (a required one: left out). A result one per
    sample is computed on each lithology's samples and put together sample by sample (each sample its own lithology).
    Any other result (a point, a set of parameters) rests on all the samples: it is computed on all of them once per
    lithology present, and each is given for the model to read the one it needs (G6). A lithology the function refuses
    is said, the others kept. (value, True when given per lithology, {lithology: its refusal})."""
    ps = [k for k, v in kw.items() if isinstance(v, _ByLithology)]
    n = int(np.asarray(kw[ps[0]]).size)
    keys = [tuple(kw[q][i] for q in ps) for i in range(n)]
    order = sorted(set(keys), key=lambda k: -keys.count(k))
    name = lambda key: "/".join(f"{fn.params[q][1]} (default)" if v is None else str(v) for q, v in zip(ps, key))

    def one(key, on):
        part = {k: (np.asarray(v)[on] if on is not None and isinstance(v, np.ndarray) and v.ndim == 1 and v.size == n
                    and k not in ps else v) for k, v in kw.items() if k not in ps}
        for q, v in zip(ps, key):
            if v is None:                                # no option names the rock: Petrophys's default
                if fn.params[q][1] is inspect.Parameter.empty:
                    return None
                continue
            part[q] = [v] if fn.kinds[q].many else v
        return call(**part)

    refused, runs = {}, []
    for key in order:                                    # each lithology on its own samples
        on = np.array([k == key for k in keys], dtype=bool)
        try:
            got = one(key, on)
        except Exception as e:  # noqa: BLE001  (a lithology it refuses is said; the others are kept)
            advised(e)                                   # the inputs its refusal asks for, for the call
            refused[name(key)] = f"{type(e).__name__}: {str(e)[:160]}"
            continue
        if got is None:
            continue
        arr = np.asarray(got) if isinstance(got, (np.ndarray, list)) else None
        if arr is None or arr.ndim != 1 or arr.size != int(on.sum()):
            runs = None                                  # not one per sample: every lithology on all the samples
            break
        runs.append((on, arr))
    if runs is not None and (runs or refused):
        if not runs:
            raise ToolError("; ".join(f"{k}: {v}" for k, v in refused.items()))
        out = None
        for on, arr in runs:
            if out is None:
                out = np.full(n, np.nan) if arr.dtype.kind in "fiub" else np.full(n, "", dtype=object)
            out[on] = arr
        return out, False, refused
    each, refused = {}, {}
    for key in order:
        try:
            got = one(key, None)
        except Exception as e:  # noqa: BLE001
            advised(e)                                   # the inputs its refusal asks for, for the call
            refused[name(key)] = f"{type(e).__name__}: {str(e)[:160]}"
            continue
        if got is not None:
            each[name(key)] = got
    if not each:
        raise ToolError("; ".join(f"{k}: {v}" for k, v in refused.items()) or f"{fn.name}: no lithology to run on")
    return each, True, refused


def _per_sample(fn: Fn, kw: dict) -> list:
    """The curves given to a function Petrophys declares samplewise (it computes one sample from single values): it
    is applied at each sample."""
    return [p for p, v in kw.items() if isinstance(v, np.ndarray) and v.ndim == 1] if fn.samplewise else []


def _each_sample(call, kw: dict, per: list) -> np.ndarray:
    """call applied at each sample: numbers -> a curve, words -> one label per sample. A sample with a missing input,
    or one the function refuses, is left empty; when it refuses every sample, its refusal is the result."""
    n, out, refusal = len(kw[per[0]]), [], None
    for i in range(n):
        x = {p: (kw[p][i] if np.asarray(kw[p]).dtype == object else float(kw[p][i])) for p in per}
        if not all(np.isfinite(v) for v in x.values() if not isinstance(v, str)):
            out.append(None)
            continue
        try:
            out.append(call(**{**kw, **x}))
        except Exception as e:  # noqa: BLE001  (a sample it refuses is left empty)
            refusal = refusal or e
            out.append(None)
    if refusal is not None and all(v is None for v in out):
        raise refusal
    if all(v is None or (isinstance(v, (int, float, np.number)) and not isinstance(v, bool)) for v in out):
        return np.array([np.nan if v is None else float(v) for v in out])
    return np.array(["" if v is None else str(v) for v in out], dtype=object)


def run(f: Formation, verb: str, function: str, args: Optional[dict] = None, label: Optional[str] = None) -> Result:
    fn = lookup(function, verb)
    if str(getattr(f.view, "selection", None) or "").startswith("where "):
        reads = [p for p, d in fn.kinds.items() if d.kind in ("well", "window")]
        if reads:                                    # its samples are not in depth order (selection.where_view)
            raise ToolError(f"{fn.name} reads the well over a depth window ({', '.join(reads)}): under where its "
                            "samples are not in depth order; select by zones or a depth range instead")
    kw, src = bind(f, fn, args or {})
    per = _per_sample(fn, kw)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            grouped = [k for k, v in kw.items() if isinstance(v, _ByLithology)]
            per = [q for q in per if q not in grouped]  # a lithology filled per sample is run lithology by lithology
            if grouped:
                call = (lambda **k: _each_sample(fn.call(), k, per)) if per else fn.call()
                value, each, refused = _by_lithology(fn, call, kw)
                if each:                                 # not one value per sample: each lithology's result, said
                    src.append("its result is not one per sample, so it is given for each lithology, computed on all "
                               "these samples: read the lithology you need, or select one by a zone or a where")
                if refused:
                    src.append("not computed for " + "; ".join(f"{k} ({v})" for k, v in refused.items()))
            elif per:
                value = _each_sample(fn.call(), kw, per)
            else:
                value = fn.call()(**kw)
        except Exception as e:  # noqa: BLE001  (the library's refusal is the model's to read)
            raise ToolError(f"Petrophys {fn.name}: {type(e).__name__}: {str(e)[:400]}") from None
    if per:
        src.append(f"applied sample by sample (it takes one value of {' and '.join(per)})")
    said = [str(v).strip() for k, v in _parts(value) if re.search(r"(^|\.)errors?$", k) and isinstance(v, str)
            and v.strip()]
    if said:      # a result that carries its own error: what else it holds is its defaults, not a computation
        raise ToolError(f"Petrophys {fn.name} could not compute it: {said[0][:300]}. Inputs: {'; '.join(src) or 'none'}")
    out = Out(f)
    out.add(f"Petrophys {fn.qualified}: {fn.summary} Inputs: {'; '.join(src) or 'none'}"
            + (f" (it is filed under {fn.verb})" if fn.verb != verb else "")
            + (f". It returns: {fn.returns}" if fn.returns else ""))
    n_int, n_well = int(f.view.mask.sum()), int(np.asarray(f.view.prep.depth).size)
    written, named, shown = [], set(), 0
    for part, v in _parts(value) or [("", value)]:
        if shown >= 24:
            break
        arr = np.asarray(v) if isinstance(v, (np.ndarray, list)) and not isinstance(v, str) else None
        if arr is not None and arr.dtype.kind in "OUS" and arr.ndim == 1 and arr.size in (n_int, n_well):
            words = np.array([str(x) for x in (arr if arr.size == n_int else arr[f.view.mask])], dtype=object)
            every = words[words != ""]                                  # the whole selection: the headline
            if every.size:                                              # one label per sample
                row = out.child()
                kinds = sorted(set(every), key=lambda w: (-int(np.sum(every == w)), w))[:12]
                shares = "; ".join(f"{w} {row.pct(100 * float(np.mean(every == w)))}" for w in kinds)
                out.add(f"  {part or 'result'}: one label per sample; share of the samples of the "
                        f"{S.whole_label_of(f.view, row.i)}: {shares}", row)
                shown += 1
                continue
        if arr is not None and arr.dtype.kind in "biuf" and arr.ndim == 1 and arr.size in (n_int, n_well):
            full = np.full(n_well, np.nan)
            if arr.size == n_int:
                full[f.view.mask] = arr.astype(float)
            else:
                full = arr.astype(float)
            name = _label(fn, part, label)
            name = _label(fn, part, label, whole=True) if name in named else name   # one part never replaces another
            named.add(name)
            vals = full[f.view.mask]
            k = S.kind_of(full)                                        # over the well, as curve_kind reads it
            name = L.register(f, name, full, f"{fn.name} {part}".strip() + " (Petrophys, on request)",
                              "flag" if k.kind == "flag" else "", f"{fn.name} (on request)")
            written.append(name)
            flag = k.kind == "flag"
            row = out.child()
            ok = vals[np.isfinite(vals)]
            codes = np.unique(ok)
            if k.kind == "classes":                                    # class codes
                every = vals[np.isfinite(vals)]                         # the whole selection: the headline
                shares = "; ".join(f"{int(c)} {row.pct(100 * float(np.mean(every == c)))}" for c in codes if every.size)
                out.add(f"  {part or 'result'}: written as {name}; classes, share of the samples of the "
                        f"{S.whole_label_of(f.view, row.i)}: {shares}", row)
            else:
                over = E.over_bases(f, vals, row, lambda a: L._stat(a, flag))
                out.add(f"  {part or 'result'}: written as {name}; {'share set (%)' if flag else 'mean'}: {over}", row)
        elif arr is not None and arr.dtype.kind in "biuf" and arr.size:
            row = out.child()
            a = arr.astype(float).ravel()
            a = a[np.isfinite(a)]
            out.add(f"  {part or 'result'}: {arr.size} values" + (f", min {row.v(a.min())}, median "
                                                                  f"{row.v(np.median(a))}, max {row.v(a.max())}"
                                                                  if a.size else ""), row)
        elif L._num(v):
            row = out.child()
            out.add(f"  {part or 'result'}: {row.v(v)}", row)
        elif hasattr(v, "to_string") and hasattr(v, "head"):              # a table
            out.add(f"  {part or 'result'} (first rows):\n" + v.head(12).to_string()[:1500])
        elif v is not None and not callable(v):
            out.add(f"  {part or 'result'}: {str(v)[:200]}")
        else:
            continue
        shown += 1
    notes = said_whole(w.message for w in caught)
    if notes:
        out.add("  Petrophys said: " + "; ".join(notes))
    if written:
        out.add(f"  curves of this question: {', '.join(written)} (every lookup reads them)")
    return out.result()


def groups(verb: str) -> list:
    """The verb's functions by their Petrophys module (saturation height, core calibration, ...), named from the
    module: what the verb reaches, in a line."""
    out = []
    for fn in functions(verb):
        parts = fn.path.split(".")
        leaf = re.sub(r"_(module|method)$", "", parts[-1])
        name = (leaf if leaf not in ("calibration", "classification", "flags", "cutoffs", "statistics") else
                f"{parts[-2]} {leaf}").replace("_", " ")
        if name not in out:
            out.append(name)
    return out


def menu_line(verb: str) -> str:
    fns = functions(verb)
    return (f"    search / run: any of Petrophys's {len(fns)} {verb} functions ({', '.join(groups(verb))}): "
            f"{{\"search\": \"<words>\"}} lists them with what each input takes and what this well has for it; "
            f"{{\"run\": \"<name>\", \"args\": {{...}}}} calls one with the inputs you name (the rest keep Petrophys's "
            f"defaults)")


def _objects(verb: str) -> set:
    """The names a verb's curated objects answer to (properties, estimates, objects)."""
    if verb == "calculate" or verb == "what_if":
        return set(L.PROPERTIES) | set(L.PROPERTIES.values()) | set(L.ALIASES)
    if verb == "estimate":
        return set(L.ESTIMATES)
    if verb in ("check", "classify", "summarize", "calibrate"):       # each verb's module of the package: its objects
        return set(importlib.import_module(f"petroharness.agent.library.{verb}").OBJECTS)
    return set()


def _is_function(name: str) -> bool:
    n = name.strip().rsplit(".", 1)[-1]
    return any(fn.name == n for fn in registry())


def verb_tool(verb: str, curated):
    """The verb as the model calls it: find / run over every Petrophys function it serves, else its curated objects
    (the tested shortcuts). The curated function's arguments stay; search, run, args and label are added."""
    sig = inspect.signature(curated)
    names = set(sig.parameters)
    own = [q.replace(default=None) if q.default is q.empty and n != "f" else q for n, q in sig.parameters.items()]
    extra = [inspect.Parameter(n, inspect.Parameter.KEYWORD_ONLY, default=None)
             for n in ("search", "run", "args", "label", "where") if n not in names]

    def tool(f, **kw):
        if kw.get("search"):
            return find(f, verb, str(kw["search"]))
        if kw.get("run"):
            args = dict(kw.get("args") or {})
            label = kw.get("label") or args.pop("label", None)        # the call's own argument, sent inside args
            return run(f, verb, str(kw["run"]), args, label)          # where: at the call door (schemas.call)
        named = next((str(kw[k]) for k in ("property", "what", "parameter") if isinstance(kw.get(k), str)), None)
        if named and named not in _objects(verb) and _is_function(named):
            # a Petrophys function named where an object belongs: run it, its parameters as the function's arguments
            args = {k: v for k, v in {**(kw.get("parameters") or {}), **(kw.get("args") or {})}.items() if k != "label"}
            return run(f, verb, named, args, kw.get("label"))
        given = {k: v for k, v in kw.items() if k in names and v is not None}
        missing = [n for n, q in sig.parameters.items() if n != "f" and q.default is q.empty and n not in given]
        if missing:
            raise ToolError(f"{verb} needs {', '.join(missing)} (one of its objects), or search (words) to list "
                            f"Petrophys's {verb} functions, or run (a function's name) with args")
        return curated(f, **given)
    tool.__signature__ = sig.replace(parameters=own + extra)
    tool.__name__ = verb
    tool.curated_params = frozenset(names)          # what its curated objects take themselves (where: the call door's)
    tool.curated = curated                          # the verb's own function, over its curated objects
    return tool
