"""Every public Petrophys function, reachable from the verb it serves (docs/TOOLS.md).

The registry is generated from the installed library: each public function of its interpretation, evaluation and
preprocessing packages, with its signature, its docstring's summary and parameter lines, and the verb its package
serves (PACKAGES). A function added to Petrophys appears here with no change to the harness.

One binder calls any of them on the question's interval:
  - an array parameter takes the curve the call names, else a condition (`VCL > 0.6` as a 0/1 mask), else the curve
    its name stands for (ROLES: rt -> RT or RDEP, phi -> PHIE, ...);
  - a number takes the call's value, else the record's parameter of that name, else the library's default;
  - a function that reads a whole well gets the prepared well with the interval's top and bottom.
Each input is said with its source. Outputs: an array over the interval becomes a curve of the question
(<FUNCTION>_<PART>), a number a value, a dataclass, dict or tuple its parts, a table its first rows.
"""
from __future__ import annotations

import dataclasses
import importlib
import inspect
import pkgutil
import re
import warnings
from functools import lru_cache
from typing import Optional

import numpy as np

from petroharness.agent import library as L
from petroharness.agent.engine import Formation, Out, Result, ToolError

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
# a parameter's name -> the curves it stands for, in order of preference
ROLES = {"rt": ["RT", "RDEP"], "rdep": ["RDEP", "RT"], "rild": ["RDEP", "RT"], "rxo": ["RXO", "RSHA"], "rmed": ["RMED"],
         "phi": ["PHIE"], "phie": ["PHIE"], "porosity": ["PHIE"], "phit": ["PHIT"], "phid": ["PHID"],
         "phin": ["PHIN", "NPHI"], "nphi": ["NPHI", "PHIN"], "neutron": ["NPHI", "PHIN"], "rhob": ["RHOB"],
         "density": ["RHOB"], "bulk_density": ["RHOB"], "vcl": ["VCL"], "vsh": ["VCL"], "vclay": ["VCL"],
         "gr": ["GR"], "gamma_ray": ["GR"], "sp": ["SP"], "dt": ["DTC", "DT"], "dtc": ["DTC", "DT"],
         "dts": ["DTS"], "pef": ["PEF"], "pe": ["PEF"], "sw": ["SW"], "sxo": ["SXO"], "perm": ["PERM"],
         "k": ["PERM"], "permeability": ["PERM"], "temperature": ["TEMP"], "temp": ["TEMP"], "cali": ["CALI"],
         "caliper": ["CALI"], "bs": ["BS"], "bit_size": ["BS"], "rw": ["RW"], "bvw": ["BVW"], "swirr": ["SWIRR"]}
MAX_FOUND = 8


@dataclasses.dataclass
class Fn:
    name: str               # the function's name
    path: str               # its module, petrophys.<...>
    verb: str
    summary: str            # the docstring's first sentence
    params: dict            # name -> (annotation text, default or inspect.Parameter.empty, description)
    returns: str = ""       # the docstring's Returns section, in short

    @property
    def qualified(self) -> str:
        return f"{self.path}.{self.name}"

    def call(self):
        return getattr(importlib.import_module(self.path), self.name)


def _param_docs(doc: str) -> dict:
    """A numpy-style docstring's Parameters section: name -> its description (first lines)."""
    out, cur = {}, None
    m = re.search(r"Parameters\n\s*-{3,}\n(.*?)(?:\n\s*\n\s*(?:Returns|Raises|Notes|Examples|See Also|Yields)\n|\Z)", doc, re.S)
    for line in (m.group(1).splitlines() if m else []):
        h = re.match(r"^\s{0,4}(\*{0,2}\w+)\s*(?::.*)?$", line)
        if h and not line.startswith(" " * 6):
            cur = h.group(1).lstrip("*")
            out[cur] = ""
        elif cur and line.strip():
            out[cur] = (out[cur] + " " + line.strip()).strip()[:200]
    return out


def _verb(module: str) -> Optional[str]:
    rel = module.split(".", 1)[1]
    return next((v for p, v in PACKAGES if rel.startswith(p)), None)


@lru_cache(maxsize=None)
def registry() -> tuple:
    """Every public function of the library's interpretation, evaluation and preprocessing packages, with its verb."""
    import petrophys
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
            summary = re.split(r"(?<=\.)\s", doc.strip().split("\n\n")[0].replace("\n", " "), maxsplit=1)[0][:160]
            r = re.search(r"Returns\n\s*-{3,}\n(.*?)(?:\n\s*\n\s*[A-Z][a-z]+\n\s*-{3,}|\Z)", doc, re.S)
            returns = " ".join(ln.strip() for ln in (r.group(1).splitlines() if r else []) if ln.strip())[:300]
            out.append(Fn(name, m.name, verb, summary, params, returns))
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


def _binds(f: Formation, fn: Fn) -> list:
    """The parameters the binder fills on its own here (curves by role, the record's numbers)."""
    rec = _record_params(f)
    out = []
    for p, (ann, default, _) in fn.params.items():
        if (_array_param(p, ann) or _name_param(p, ann, default)) and _role_curve(f, p):
            out.append(f"{p}={_role_curve(f, p)}")
        elif p in rec:
            out.append(f"{p}=record")
    return out


def find(f: Formation, verb: str, query: str) -> Result:
    """The functions matching the words: this verb's first, then any other verb's that match better (Petrophys files
    some by the property they compute: gas detection sits with porosity)."""
    words = _words(query)
    scored = []
    for fn in registry():
        text = _words(fn.name.replace("_", " ") + " " + fn.summary + " " + " ".join(fn.params))
        name = _words(fn.name.replace("_", " "))
        score = 3 * len(words & name) + len(words & text)
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
        need = [p for p, (ann, d, _) in fn.params.items() if d is inspect.Parameter.empty]
        opt = [p for p, (ann, d, _) in fn.params.items() if d is not inspect.Parameter.empty]
        auto = _binds(f, fn)
        out.add(f"  {fn.name}{'' if fn.verb == verb else ' (' + fn.verb + ')'}: {fn.summary} (needs "
                f"{', '.join(need) or 'nothing'}; also {', '.join(opt[:8]) or '-'}"
                + (f"; bound here: {', '.join(auto)}" if auto else "") + ")")
    return out.result()


# --- binding --------------------------------------------------------------------------------------------------------

def _name_param(p: str, ann: str, default) -> bool:
    """A parameter that takes a curve's name (sw_curve="SW"), not its values."""
    return p.endswith("_curve") and ("str" in ann or isinstance(default, str) or default is None)


def _array_param(p: str, ann: str) -> bool:
    return not p.endswith("_curve") and (bool(re.search(r"ndarray|ArrayLike|Sequence\[float\]|array", ann))
                                         or bool(_role(p)))


def _role(p: str) -> list:
    key = re.sub(r"_(curve|log|values|array|data)$", "", p.lower())
    return ROLES.get(key) or ROLES.get(key.replace("_", "")) or []


def _role_curve(f: Formation, p: str) -> Optional[str]:
    for c in _role(p):
        if c in f.inv.curves and f.view.available(c):
            return c
    return None


def _record_params(f: Formation) -> dict:
    """The record's numeric parameters by name (the last step that states one), with the step."""
    out = {}
    for m in f.inv.methods:
        for k, v in (m.parameters or {}).items():
            if L._num(v):
                out[str(k)] = (float(v), m.step)
    return out


def _curve_values(f: Formation, name: str) -> Optional[np.ndarray]:
    c = str(name).strip().upper()
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


def _text_arg(v: str, ann: str):
    """A text argument as the function takes it: a number written as text is the number; a name keeps its case (a
    curve's mnemonic); one name where the function takes a list of them is a list of one."""
    try:
        return float(v)
    except ValueError:
        pass
    return [v] if re.search(r"Sequence|List|list|Tuple|tuple|Iterable", ann) and "str" in ann else v


def bind(f: Formation, fn: Fn, args: dict) -> tuple:
    """The call's keyword arguments and the source of each -> (kwargs, sources)."""
    args = {str(k): v for k, v in (args or {}).items()}
    unknown = [k for k in args if k not in fn.params]
    if unknown:
        raise ToolError(f"{fn.name} takes {', '.join(fn.params)}; not {', '.join(unknown)}. The call's shape: "
                        f"{{\"run\": \"{fn.name}\", \"args\": {{<the function's arguments>}}, \"label\": \"<name>\"}}")
    rec, kw, src = _record_params(f), {}, []
    whole_well = "well" in fn.params and not any(_array_param(p, a) and _role_curve(f, p)
                                                 for p, (a, d, _) in fn.params.items() if p != "well")
    for p, (ann, default, _) in fn.params.items():
        if p == "well" and p in args:                    # the well is the binder's to give (the prepared well)
            args.pop(p)
            src.append("well: the prepared well, not the name given")
        if p in args:
            v = args[p]
            if isinstance(v, str) and _array_param(p, ann):
                arr = _curve_values(f, v)
                arr = arr if arr is not None else _condition(f, v)
                if arr is None:
                    raise ToolError(f"{fn.name}: {p} {v!r} is neither a curve here nor a condition")
                kw[p] = arr
                src.append(f"{p} {v} (asked)")
            else:
                kw[p] = _text_arg(v, ann) if isinstance(v, str) else v
                src.append(f"{p} {v} (asked)")
            continue
        if p == "well":
            if whole_well:
                kw[p] = f.view.prep.well
                src.append("well (the prepared well)")
            continue
        if p == "depth":
            kw[p] = np.asarray(f.view.prep.depth, dtype=float)[f.view.mask]
            src.append("depth (the interval's)")
            continue
        if p in ("top", "bottom", "top_depth", "bottom_depth", "base") and whole_well:
            d = np.asarray(f.view.prep.depth, dtype=float)[f.view.mask]
            kw[p] = float(d.min() if p.startswith("top") else d.max())
            src.append(f"{p} (the interval's)")
            continue
        if _name_param(p, ann, default) and whole_well:
            c = _role_curve(f, p)
            if c is not None:
                kw[p] = c
                src.append(f"{p} {c}")
            continue
        if _array_param(p, ann):
            c = _role_curve(f, p)
            if c is not None and not whole_well:
                kw[p] = _curve_values(f, c)
                src.append(f"{p} {c}")
                continue
        if p in rec:
            kw[p] = rec[p][0]
            src.append(f"{p} {L._shown(rec[p][0])} (record, {rec[p][1]})")
            continue
        if default is inspect.Parameter.empty:
            raise ToolError(f"{fn.name} needs {p}" + (f" ({fn.params[p][2]})" if fn.params[p][2] else "")
                            + "; give it in args (a curve name, a condition, or a value)")
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


def _label(fn: Fn, part: str, label: Optional[str]) -> str:
    base = (label or fn.name).upper()
    base = re.sub(r"[^A-Z0-9]+", "_", base).strip("_")[:20]
    p = re.sub(r"[^A-Z0-9]+", "_", part.upper()).strip("_")[:10]
    name = f"{base}_{p}" if p else base
    return name if re.match(r"[A-Z]", name) else f"X{name}"


def run(f: Formation, verb: str, function: str, args: Optional[dict] = None, label: Optional[str] = None) -> Result:
    fn = lookup(function, verb)
    kw, src = bind(f, fn, args or {})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            value = fn.call()(**kw)
        except Exception as e:  # noqa: BLE001  (the library's refusal is the model's to read)
            raise ToolError(f"Petrophys {fn.name}: {type(e).__name__}: {str(e)[:400]}") from None
    out = Out(f)
    out.add(f"Petrophys {fn.qualified}: {fn.summary} Inputs: {'; '.join(src) or 'none'}"
            + (f" (it is filed under {fn.verb})" if fn.verb != verb else "")
            + (f". It returns: {fn.returns}" if fn.returns else ""))
    n_int, n_well = int(f.view.mask.sum()), int(np.asarray(f.view.prep.depth).size)
    written, shown = [], 0
    for part, v in _parts(value) or [("", value)]:
        if shown >= 24:
            break
        arr = np.asarray(v) if isinstance(v, (np.ndarray, list)) and not isinstance(v, str) else None
        if arr is not None and arr.dtype.kind in "biuf" and arr.ndim == 1 and arr.size in (n_int, n_well):
            full = np.full(n_well, np.nan)
            if arr.size == n_int:
                full[f.view.mask] = arr.astype(float)
            else:
                full = arr.astype(float)
            name = _label(fn, part, label)
            L.register(f, name, full, f"{fn.name} {part}".strip() + " (Petrophys, on request)", "",
                       f"{fn.name} (on request)")
            written.append(name)
            vals = full[f.view.mask]
            flag = L._flag(vals)
            row = out.child()
            ok = vals[np.isfinite(vals)]
            codes = np.unique(ok)
            if not flag and ok.size and np.all(ok == np.round(ok)) and 2 <= codes.size <= 12:    # class codes
                pooled = vals[L._pooled(f)]
                pooled = pooled[np.isfinite(pooled)]
                shares = "; ".join(f"{int(c)} {row.pct(100 * float(np.mean(pooled == c)))}" for c in codes if pooled.size)
                out.add(f"  {part or 'result'}: written as {name}; classes, share of the zones' samples: {shares}", row)
            else:
                per = "; ".join(f"{z.zone_id} {row.v(L._stat(vals[np.asarray(z.indices)], flag))}" for z in f.view.zones[:12])
                out.add(f"  {part or 'result'}: written as {name}; {'share set (%)' if flag else 'mean'} "
                        f"{row.v(L._stat(vals[L._pooled(f)], flag))} zones pooled; {per}", row)
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
    notes = [str(w.message)[:160] for w in caught][:3]
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
            f"{{\"search\": \"<words>\"}} lists them; {{\"run\": \"<name>\", \"args\": {{...}}}} calls one (curves "
            f"bind by role, numbers from the record)")


def _objects(verb: str) -> set:
    """The names a verb's curated objects answer to (properties, estimates, objects)."""
    if verb == "calculate" or verb == "what_if":
        return set(L.PROPERTIES) | set(L.PROPERTIES.values()) | set(L.ALIASES)
    if verb == "estimate":
        return set(L.ESTIMATES)
    mod = {"check": "library_check", "classify": "library_classify", "summarize": "library_summarize",
           "calibrate": "library_calibrate"}.get(verb)
    return set(importlib.import_module(f"petroharness.agent.{mod}").OBJECTS) if mod else set()


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
             for n in ("search", "run", "args", "label") if n not in names]

    def tool(f, **kw):
        if kw.get("search"):
            return find(f, verb, str(kw["search"]))
        if kw.get("run"):
            args = dict(kw.get("args") or {})
            label = kw.get("label") or args.pop("label", None)        # the call's own argument, sent inside args
            return run(f, verb, str(kw["run"]), args, label)
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
    return tool
