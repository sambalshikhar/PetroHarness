"""Petrophys by what users ask (docs/TOOLS.md): calculate a property with a method or
parameters, estimate a parameter from the well's own logs, and what_if: an input's effect on a target.

Petrophys calculates. The record is the default for every input, and each result says where each input came from.
Methods, parameters and their choices are read from the library's own step catalog
(petrophys.mcp.catalog.step_kinds: the library's description of its workflow steps, no server). The steps a change
carries into come from each step's requires and produces. A calculated curve becomes a curve of the question,
<CURVE>_<LABEL> (SW_SIMANDOUX), read by every lookup and condition.
"""
from __future__ import annotations

import copy
import json
import re
import warnings
import threading
from functools import lru_cache
from typing import Optional

import numpy as np

from petroharness.agent import engine as E
from petroharness.agent.engine import Formation, Out, Result, ToolError, limits, num, said_whole
from petroharness.agent.inventory import Curve
from petroharness.well import summary as S

# what users call a property -> the library's workflow step
PROPERTIES = {"clay_volume": "clay_volume", "porosity": "porosity", "water_resistivity": "formation_water",
              "mud_filtrate_resistivity": "mud_filtrate", "saturation": "saturation", "permeability": "permeability",
              "rock_quality": "rock_quality", "bvw": "bvw", "mhi": "mhi", "net_pay": "net_pay",
              "temperature": "temperature"}
ALIASES = {"vcl": "clay_volume", "shale_volume": "clay_volume", "vsh": "clay_volume", "phie": "porosity",
           "phit": "porosity", "rw": "water_resistivity", "formation_water": "water_resistivity",
           "rmf": "mud_filtrate_resistivity", "mud_filtrate": "mud_filtrate_resistivity", "sw": "saturation",
           "water_saturation": "saturation", "perm": "permeability", "pay": "net_pay", "net_reservoir": "net_pay",
           "cutoffs": "net_pay", "fzi": "rock_quality", "rqi": "rock_quality", "bulk_volume_water": "bvw",
           "temp": "temperature"}
CURVE_ARGS = {"gr_curve", "vcl_curve", "phie_curve", "phit_curve", "perm_curve", "sw_curve", "sxo_curve", "name"}
IMPLICIT = {"TEMP": ["formation_water", "mud_filtrate"]}                 # read without being listed in requires
TARGETS = {"clay_volume": "VCL", "porosity": "PHIE", "formation_water": "SW", "saturation": "SW",
           "permeability": "PERM", "net_pay": "NET_PAY", "bvw": "BVW", "mhi": "MHI", "rock_quality": "FZI",
           "temperature": "TEMP", "mud_filtrate": "MHI"}
MAX_VALUES = 6


# --- the library's catalog ------------------------------------------------------------------------------------------

@lru_cache(maxsize=None)
def catalog(kind: str) -> dict:
    """The library's description of one workflow step: what it does and its parameters (default, description,
    choices)."""
    from petrophys.mcp.catalog import step_kinds
    return step_kinds(kind)["kinds"][kind]


@lru_cache(maxsize=None)
def order() -> tuple:
    from petrophys.mcp.catalog import step_kinds
    return tuple(k for k in step_kinds()["kinds"] if k in set(PROPERTIES.values()))


def choices(kind: str) -> dict:
    """parameter -> its choices as (name, the options it takes), for the parameters the catalog gives choices."""
    out = {}
    for p, d in catalog(kind)["params"].items():
        for c in (d.get("choices") or []) if isinstance(d, dict) else []:
            m = re.match(r"\s*([\w-]+)\s*(?:\(options:\s*([^)]*)\))?", str(c))
            if m:
                out.setdefault(p, []).append((m.group(1), [o.strip() for o in (m.group(2) or "").split(",") if o.strip()]))
    return out


def parameters(kind: str) -> dict:
    return {p: d for p, d in catalog(kind)["params"].items() if p not in CURVE_ARGS}


def kind_of(prop) -> str:
    p = re.sub(r"[\s-]+", "_", str(prop or "").strip().lower())
    p = ALIASES.get(p, p)
    if p in PROPERTIES:
        return PROPERTIES[p]
    if p in PROPERTIES.values():
        return p
    raise ToolError(f"no property {prop!r}; properties: {', '.join(PROPERTIES)}")


def _library():
    from petrophys.workflow import Workflow, steps
    return Workflow, steps


def produces(kind: str, params: dict) -> list:
    try:
        return list(_step(kind, params).produces)
    except ToolError:
        return []


@lru_cache(maxsize=None)
def _requires(kind: str) -> tuple:
    _, S = _library()
    try:
        st = getattr(S, kind)(**({"rw": 0.1, "rw_temp_f": 75.0} if kind == "formation_water" else
                                 {"rmf": 0.1, "rmf_temp_f": 75.0} if kind == "mud_filtrate" else {}))
    except Exception:  # noqa: BLE001  (a step the library will not build without its inputs reads nothing listed)
        return ()
    return tuple(n.strip() for r in st.requires for n in str(r).split(" or "))


def downstream(kind: str, made: list) -> list:
    """The steps after `kind`, in the workflow's order, that read what it (or a step after it here) writes."""
    out, written = [], set(made)
    for k in order():
        if order().index(k) <= order().index(kind):
            continue
        if written & set(_requires(k)) or any(k in IMPLICIT.get(c, []) for c in written):
            out.append(k)
            written |= set(produces(k, {}) or [])
    return out


# --- the record's parameters ----------------------------------------------------------------------------------------

def _method(f: Formation, kind: str):
    from petrophys.workflow.steps import RECORD_STEP          # the record's name of a step (Petrophys's)
    step = RECORD_STEP.get(kind, kind)
    return next((m for m in f.inv.methods if m.step == step), None)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and bool(np.isfinite(float(v)))


def unlisted_method(f: Formation, kind: str) -> str:
    """The record's method of the step when it is none of the library step's choices (the record's clay volume
    min(GR, ND), the library's gr, sp, nd, ...): its words, "" when it is one of them or the record states none."""
    m = _method(f, kind)
    method = str(getattr(m, "method", "") or "").strip()
    names = {n for p, opts in choices(kind).items() if p in ("model", "method") for n, _ in opts}
    return method if method and names and method.lower() not in names else ""


def defaults(f: Formation, kind: str) -> dict:
    """The step's parameters as the record states them (only those it states), read by Petrophys
    (steps.recorded_arguments: the record's names of each argument, a word only where it is one of the argument's
    choices): a step run again starts from the record's run."""
    from petrophys.workflow.steps import recorded_arguments
    return recorded_arguments(kind, getattr(f.view.prep, "steps", None) or {})


_UNUSED = re.compile(r"-\s*(\w+) is not used by")


class _Dropped(threading.local):
    """The asked parameters the last _step of this thread left out (the chosen method does not take them). Per thread:
    questions run side by side, and one question's step must not read another's."""

    def __init__(self):
        self.names: list = []


DROPPED = _Dropped()


def _step(kind: str, params: dict, asked: tuple = ()):
    """The library step. Parameters the chosen method does not take are left out (the library refuses them), and the
    asked ones among them are kept in DROPPED for the result to say; any other refusal is the library's message."""
    _, S = _library()
    params = dict(params)
    DROPPED.names.clear()
    for _ in range(4):
        try:
            return getattr(S, kind)(**params)
        except (ValueError, TypeError) as e:
            unused = [p for p in _UNUSED.findall(str(e)) if p in params]
            if not unused:
                raise ToolError(f"Petrophys {kind}: {str(e).strip()[:500]}") from None
            DROPPED.names.extend(p for p in unused if p in asked)
            for p in unused:
                params.pop(p)
    raise ToolError(f"Petrophys {kind}: the parameters could not be reconciled with the step")


def _coerce(v):
    if isinstance(v, str):
        s = v.strip()
        try:
            return float(s)
        except ValueError:
            return s.lower()
    return v


# --- running a change -----------------------------------------------------------------------------------------------

def _owner(name: str) -> Optional[str]:
    """The property whose step takes a parameter (rw: water_resistivity)."""
    return next((prop for prop, kind in PROPERTIES.items() if name in parameters(kind)), None)


def _changes(kind: str, method, params) -> dict:
    ch = {str(k).strip(): _coerce(v) for k, v in (params or {}).items()}
    if method:
        m = str(method).strip().lower()
        hit = [p for p, opts in choices(kind).items() if m in [n for n, _ in opts]]
        if not hit:
            listed = "; ".join(f"{p}: {', '.join(n for n, _ in opts)}" for p, opts in choices(kind).items())
            routed = (f" A record method joining models with '+' ({method}) is the routing 'auto' runs."
                      if "+" in m and any("auto" in [n for n, _ in o] for o in choices(kind).values()) else "")
            alone = (f" To change {', '.join(str(k) for k in ch)} and keep the rest, give the parameters without a method: "
                     f"the step runs its default method with them, read against a baseline run of the same method."
                     if ch else "")
            raise ToolError(f"{kind} has no method {method!r}; methods: {listed or 'none (it takes parameters only)'}."
                            + routed + alone)
        ch[hit[0]] = m
    known = parameters(kind)
    bad = [k for k in ch if k not in known]
    if bad:
        moved = {k: _owner(k) for k in bad if _owner(k)}
        hint = "".join(f" {k} belongs to {prop}: {{\"calculate\": {{\"property\": \"{prop}\", \"parameters\": "
                       f"{{\"{k}\": {ch[k]}}}}}}}; its change carries into the steps that read it ({kind} among "
                       f"them)." for k, prop in moved.items())
        raise ToolError(f"{kind} takes {', '.join(known)}; not {', '.join(bad)}.{hint}")
    return ch


def run(f: Formation, kind: str, changes: dict, with_downstream: bool = True) -> dict:
    """The step with the record's parameters (baseline) and with the changes, each followed by the steps that read its
    outputs, on copies of the prepared well -> {base, alt (WorkflowRunResults), chain, base_p, alt_p, made}."""
    well = getattr(getattr(f.view, "prep", None), "well", None)
    if well is None:
        raise ToolError("no prepared well to run Petrophys on")
    base_p = defaults(f, kind)
    # a choice changed (matrix limestone) sets its own values (matrix_density, ...): the record's go unless asked too
    tied = [q for p, v in changes.items() if isinstance(v, str) for q in base_p if q.startswith(p + "_") and q not in changes]
    alt_p = {**{k: v for k, v in base_p.items() if k not in tied}, **changes}
    if kind == "formation_water" and not alt_p.get("rw") and not alt_p.get("salinity_ppm"):
        raise ToolError("water_resistivity needs rw (ohm.m) with rw_temp_f (degF), or salinity_ppm: the record states "
                        "no single Rw for this well")
    alt_first = _step(kind, alt_p, tuple(changes))
    dropped = list(DROPPED.names)
    made = list(alt_first.produces)
    chain = [kind] + (downstream(kind, made) if with_downstream else [])
    rest = [_step(k, defaults(f, k)) for k in chain[1:]]
    Workflow, _ = _library()
    try:
        base_first = _step(kind, base_p) if kind != "formation_water" or base_p.get("rw") or base_p.get("salinity_ppm") \
            else None
    except ToolError:
        base_first = None                                 # the record's own parameters do not rebuild: no baseline
    # the baseline: the step with the record's parameters, then the rest; when those do not rebuild the step (a record
    # made by a rule the step does not take), the rest alone on the record's own outputs of the step
    first = [base_first] if base_first else []
    try:
        base = Workflow(f"{kind} baseline", first + rest).run(well, strict=False) if first + rest else None
        alt = Workflow(f"{kind} changed", [alt_first] + rest).run(well, strict=False)
    except Exception as e:  # noqa: BLE001  (a library failure is the model's to read, not a crash)
        raise ToolError(f"Petrophys could not run {kind}: {type(e).__name__}: {str(e)[:300]}") from None
    for st in rest:
        made += [c for c in st.produces if c not in made]
    return {"base": base, "alt": alt, "chain": chain, "base_p": base_p, "alt_p": alt_p, "made": made,
            "first": list(alt_first.produces), "rebuilt": base_first is not None, "dropped": dropped}


def _ran(r: dict, f: Formation) -> bool:
    """Whether the asked step ran in the changed run: it wrote one of its own curves. When it did not, the steps after
    it ran on the record's inputs, so what they wrote is not an effect of the change."""
    return any(_values(r["alt"], f, c) is not None for c in r.get("first") or [])


def _values(res, f: Formation, c: str) -> Optional[np.ndarray]:
    """The curve over the well's samples as a run wrote it, None when the run did not write it (a step that did not
    run leaves the copied well's own curve, which is the record's, not a computation)."""
    if res is None:
        return None
    try:
        if c not in set(res.output_curves):
            return None
    except Exception:  # noqa: BLE001  (a run without its record of outputs: read the curve as before)
        pass
    try:
        cv = res.well.get(c)
    except Exception:  # noqa: BLE001  (no such curve in this run)
        return None
    vals = getattr(cv, "values", None) if cv is not None else None
    if vals is None:
        return None
    vals = np.asarray(vals, dtype=float)
    return vals if vals.size == np.asarray(f.view.prep.depth).size else None


def _flag(x: np.ndarray) -> bool:
    ok = x[np.isfinite(x)]
    return ok.size > 0 and bool(np.all((ok == 0) | (ok == 1)))


def scratch_well(f: Formation):
    """A copy of the prepared well, for a Petrophys call: some library functions change the well they are given
    (apply_value_range_qc clips the curves in place), and the record every later step reads is that well."""
    well = getattr(getattr(f.view, "prep", None), "well", None)
    if well is None:
        raise ToolError("no prepared well to run Petrophys on")
    return copy.deepcopy(well)


def register(f: Formation, name: str, full: np.ndarray, meaning: str, unit: str, step: str) -> None:
    """A curve of the question: over the well's samples, read by every lookup and condition."""
    f.view.calculated[name] = full
    if unit == "flag":                                  # read as a flag by runs, stats and conditions
        f.view.calc_flags.add(name)
    vals = full[f.view.mask]
    ok = np.isfinite(vals)
    f.inv.curves[name] = Curve(name=name, unit=unit or "", meaning=meaning, meaning_from="step", source="computed",
                               step=step, coverage=float(ok.mean()) if ok.size else 0.0, n=int(ok.sum()),
                               zone_coverage={z.zone_id: float(ok[np.asarray(z.indices)].mean())
                                              for z in f.view.zones if np.asarray(z.indices).size})


def _label(label, changes: dict) -> str:
    text = str(label or "").strip() or next((str(v) for k, v in changes.items() if k in ("model", "method")), "") \
        or "ALT"
    lab = re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")[:16] or "ALT"
    return lab if re.match(r"[A-Z]", lab) else f"X{lab}"


def _shown(v) -> str:
    return num(float(v)) if _num(v) else str(v)


def used(kind: str, params: dict) -> list:
    """The parameters the run's method takes, from the catalog: those no method lists as its own option, and the
    chosen method's options (saturation simandoux: model, a, m, n and rcl; not the north_sea model's vsh_exp)."""
    ch = choices(kind)
    own = {o for opts in ch.values() for _, os_ in opts for o in os_}
    picked = {o for p, opts in ch.items() for n, os_ in opts if params.get(p) == n for o in os_}
    return [p for p in parameters(kind) if p not in own or p in picked]


def _sources(kind: str, r: dict, changes: dict) -> str:
    """The inputs the changed run used, each with its source; a record value the asked choice replaced is said so."""
    out = []
    for p in used(kind, r["alt_p"]):
        if p in changes:
            out.append(f"{p} {_shown(changes[p])} (asked)")
        elif p in r["alt_p"]:
            out.append(f"{p} {_shown(r['alt_p'][p])} (record)")
        elif p in r["base_p"]:
            out.append(f"{p} from the asked choice (the record's {_shown(r['base_p'][p])} not used)")
    return ", ".join(out)


def _stat(x: np.ndarray, flag: bool) -> float:
    x = x[np.isfinite(x)]
    if not x.size:
        return float("nan")
    return 100.0 * float(np.mean(x > 0.5)) if flag else float(np.mean(x))


def _whole(f: Formation, row: Out) -> str:
    """The whole interval's (or selection's) label, as the summary layer writes it: the headline of a change, with
    the zones as its breakdown (question suite T04: what_if gave zones pooled only, and every net-reservoir sample lay
    outside the rows)."""
    return S.whole_label_of(f.view, row.i)


def _pooled(f: Formation) -> np.ndarray:
    zs = list(f.view.zones)
    return np.unique(np.concatenate([np.asarray(z.indices) for z in zs])) if zs else np.arange(int(f.view.mask.sum()))


def _effect(out: Out, f: Formation, c: str, a: np.ndarray, b: Optional[np.ndarray], basis: str = "baseline") -> None:
    """One curve: baseline -> changed, zones pooled and each zone (mean; a flag's share set). basis names what the
    change is set against: the baseline run, or the record's own curve."""
    flag = _flag(a)
    what = "share set (%)" if flag else "mean"
    idx = _pooled(f)
    row = out.child()
    if b is None:
        out.add(f"  {c}: {what}: {E.over_bases(f, a, row, lambda x: _stat(x, flag))} (nothing to set it against: "
                f"neither a baseline nor a record curve)", row)
        return
    b0, a0 = _stat(b[idx], flag), _stat(a[idx], flag)
    bw, aw = _stat(b, flag), _stat(a, flag)
    changed = int(np.sum(np.isfinite(a) & np.isfinite(b) & (np.abs(a - b) > 1e-9)))
    # every change stated beside its pair, and the count of changed samples with its total: an answer restates a
    # change in a table or a summary, away from the pair it was read from (question suite P5: "0.6621 (-0.0294)")
    out.add(f"  {c}: {what} {row.v(bw)} -> {row.v(aw)} ({_signed(row, aw - bw)}) {_whole(f, row)}"
            f"{'' if basis == 'baseline' else ' (against the record' + chr(39) + 's ' + c + ')'}; "
            f"{row.v(b0)} -> {row.v(a0)} ({_signed(row, a0 - b0)}) {S.pooled_word(f.view)} pooled; "
            f"{row.i(changed)} of {row.i(len(a))} samples changed", row)
    parts, rows, z_out = [], [], out.child()
    for z in f.view.zones:
        zi = np.asarray(z.indices)
        bz, az = _stat(b[zi], flag), _stat(a[zi], flag)
        if np.isfinite(bz) and np.isfinite(az):
            parts.append(f"{z.zone_id} {z_out.v(bz)} -> {z_out.v(az)} ({_signed(z_out, az - bz)})")
            rows.append((z.zone_id, bz, az, az - bz))
    if 1 < len(parts) <= 40:
        out.add(f"    each zone ({what}, {basis} -> changed): " + "; ".join(parts), z_out)
    if len(rows) > 1:                  # the zones' range on each side and of the change, each end with its zone: read
        r_out = out.child()            #   off the pairs, a range took one side's end and the other's (question suite P5)

        def span(k: int) -> str:
            lo, hi = min(rows, key=lambda r: r[k]), max(rows, key=lambda r: r[k])
            return f"{r_out.v(lo[k])} ({lo[0]}) to {r_out.v(hi[k])} ({hi[0]})"
        out.add(f"    the zones' range ({what}): {basis} {span(1)}; changed {span(2)}; change {span(3)}", r_out)


def _signed(out: Out, x: float) -> str:
    """A change with its sign: +0.01, -0.0294, 0."""
    return ("+" if x > 0 else "") + out.v(x)


def _reproduction(out: Out, f: Formation, c: str, b: Optional[np.ndarray]) -> None:
    rec = f.view.values(c) if c in f.inv.curves else None
    if b is None or rec is None:
        return
    rec = np.asarray(rec, dtype=float)
    ok = np.isfinite(b) & np.isfinite(rec)
    if not ok.any():
        return
    d = np.abs(b[ok] - rec[ok])
    near = d <= np.maximum(1e-3, 0.01 * np.abs(rec[ok]))
    row = out.child()
    if near.all():
        out.add(f"    the baseline reproduces the record's {c} (every sample within 1%)", row)
    else:          # a flag that differs at a few samples moves a small zone's share: never "reproduces"
        out.add(f"    the baseline differs from the record's {c} at {row.i(int((~near).sum()))} of {row.i(int(near.size))} "
                f"samples ({row.pct(100 * float(near.mean()))} within 1%): the record was made with settings the library "
                f"step does not take; read the change as its effect (baseline -> changed), not as a new value of the "
                f"record's {c}", row)


# --- the verbs ------------------------------------------------------------------------------------------------------

def menu(f: Formation, kind: str) -> Result:
    """The step's parameters: the record's value or the library's default, with the choices."""
    out = Out(f)
    cat, rec = catalog(kind), defaults(f, kind)
    out.add(f"{kind}: {cat.get('does', '')} No change was asked; its parameters (record's value, else the library's "
            f"default):")
    ch = choices(kind)
    for p, d in parameters(kind).items():
        row = out.child()
        val = rec.get(p, d.get("default") if isinstance(d, dict) else None)
        shown = row.v(val) if _num(val) else str(val)
        src = "record" if p in rec else "library default"
        if p in ("model", "method") and unlisted_method(f, kind):     # the record's method is not a choice
            src = f"library default; the record's {unlisted_method(f, kind)} is not one of the choices"
        opts = f"; choices: {', '.join(n + (' (' + ', '.join(o) + ')' if o else '') for n, o in ch[p])}" if p in ch else ""
        desc = d.get("description", "") if isinstance(d, dict) else ""
        out.add(f"  {p} = {shown} ({src}){': ' + desc if desc else ''}{opts}", row)
    return out.result()


def advice_calls(names, takes=(), kind: Optional[str] = None) -> str:
    """The inputs Petrophys's advice asks for (its Advice inputs: "add steps.mud_filtrate(rmf=..., rmf_temp_f=...)"
    asks for rmf and rmf_temp_f), as the calls of this harness that take each - the tool's own argument first (`takes`),
    then the calculate property whose parameters hold it (`kind`'s own first) - and the names no tool here takes; ""
    with none."""
    names = list(dict.fromkeys(str(n) for n in names or ()))
    if not names:
        return ""
    here = [n for n in names if n in set(takes or ())]
    owners = {}
    for prop in [p for p in PROPERTIES if kind and kind_of(p) == kind] + [p for p in PROPERTIES if not (kind and kind_of(p) == kind)]:
        for n in names:
            if n not in here and n not in owners and n in parameters(kind_of(prop)):
                owners[n] = prop
    parts = [f"{', '.join(here)}: {'arguments' if len(here) > 1 else 'an argument'} of this call"] if here else []
    for prop in dict.fromkeys(owners.values()):
        mine = {n: "..." for n, p in owners.items() if p == prop}
        parts.append(json.dumps({"calculate": {"property": prop, "parameters": mine}}).replace('"..."', "..."))
    none = [n for n in names if n not in here and n not in owners]
    out = ("as tool calls: " + "; ".join(parts)) if parts else ""
    if none:
        out += ("; " if out else "") + f"{', '.join(none)}: no tool here takes {'it' if len(none) == 1 else 'them'}"
    return out


def calculate(f: Formation, property: str, method: Optional[str] = None, parameters: Optional[dict] = None,
              label: Optional[str] = None, downstream: bool = True, parameter: Optional[str] = None,
              values=None) -> Result:
    if parameter is not None or values is not None:          # what_if's arguments sent to calculate
        raise ToolError("calculate takes one change (property, method, parameters); to try several values of one "
                        "input use what_if: {\"what_if\": {\"property\": ..., \"parameter\": ..., \"values\": [...]}}")
    kind = kind_of(property)
    changes = _changes(kind, method, parameters)
    if not changes:
        return menu(f, kind)
    r = run(f, kind, changes, bool(downstream) if downstream is not None else True)
    lab = _label(label, changes)
    out = Out(f)
    asked = ", ".join(f"{k} {v}" for k, v in changes.items())
    out.add(f"{kind} recomputed by Petrophys with {asked}; inputs: {_sources(kind, r, changes)}"
            + (f"; then {', '.join(r['chain'][1:])} (they read its outputs)" if r["chain"][1:] else ""))
    if r["dropped"]:
        out.add(f"  not used: {', '.join(r['dropped'])} (the {kind} method chosen does not take them)")
    alt = r["alt"]
    trouble = said_whole([*(alt.errors or []), *E.skipped_said(alt.steps_skipped)])
    if trouble:
        out.add("  Petrophys did not run: " + "; ".join(trouble))
    written = []
    if not r["rebuilt"]:
        out.add(f"  the record's {kind} parameters do not rebuild the step (method "
                f"{getattr(_method(f, kind), 'method', 'unknown')}): its own curves are set against the record's, and "
                f"the steps after it against a run of them on the record's {kind} outputs")
    computed = [c for c in r["made"] if _values(alt, f, c) is not None] if _ran(r, f) else []
    if not computed:
        raise ToolError(f"Petrophys did not compute {kind} with {asked}: " + ("; ".join(trouble) or "no step wrote "
                        + ", ".join(r["made"])) + f". Inputs: {_sources(kind, r, changes)}")
    missing = [c for c in r["made"] if c not in computed]
    if missing:
        out.add(f"  not computed: {', '.join(missing)} (the step that writes them did not run)")
    for c in computed:
        a_full = _values(alt, f, c)
        b_full, basis = _values(r["base"], f, c), "baseline"
        if b_full is None and c in f.inv.curves:
            b_full, basis = f.view.well_values(c), "record"
        name = joined_name(c, lab)
        unit = "flag" if f.view.is_flag(c) else (f.inv.curves[c].unit if c in f.inv.curves else "")
        register(f, name, a_full, f"{c} recomputed by Petrophys ({kind}: {asked})", unit, f"{kind} ({asked}, on request)")
        written.append(name)
        m = f.view.mask
        _effect(out, f, c, a_full[m], None if b_full is None else b_full[m], basis)
        if basis == "baseline":
            _reproduction(out, f, c, None if b_full is None else b_full[m])
    out.add(f"  written: {', '.join(written) or 'nothing'}"
            + (f" (curves of this question: use them in any lookup, e.g. stats {written[0]}, or compare {written[0]} "
               f"{written[0].rsplit('_', 1)[0]})" if written else ""))
    return out.result()


def what_if(f: Formation, property: str, parameter: str, values, target: Optional[str] = None,
            parameters: Optional[dict] = None) -> Result:
    """parameters: inputs held at a given value for every run beside the one varied (Rw's temperature: rw_temp_f)."""
    kind = kind_of(property)
    fixed = _changes(kind, None, parameters) if parameters else {}
    vals = values if isinstance(values, (list, tuple)) else [values]
    vals = [_coerce(v) for v in vals][:MAX_VALUES]
    if not vals:
        raise ToolError(f"give the values to try, e.g. \"values\": [0.4, 0.5, 0.6] (at most {MAX_VALUES})")
    runs = []
    for v in vals:
        changes = _changes(kind, v, None) if parameter in ("model", "method") else _changes(kind, None, {parameter: v})
        runs.append((v, run(f, kind, {**fixed, **changes}, True)))
    tgt = str(target or TARGETS.get(kind, "")).strip().upper()
    if not tgt or tgt not in runs[0][1]["made"]:
        raise ToolError(f"target {target!r} is not written by {kind} or the steps after it; it writes "
                        f"{', '.join(runs[0][1]['made'])}")
    m, idx = f.view.mask, _pooled(f)
    out = Out(f)
    base = _values(runs[0][1]["base"], f, tgt)
    wrote = [a for a in (_values(r["alt"], f, tgt) for _, r in runs if _ran(r, f)) if a is not None]
    if not wrote:
        said = said_whole([*(e for _, r in runs for e in (r["alt"].errors or [])),
                             *(m for _, r in runs for m in E.skipped_said(r["alt"].steps_skipped))])
        raise ToolError(f"Petrophys wrote no {tgt} for any {parameter} tried: " + ("; ".join(said) or "skipped"))
    flag = _flag(wrote[0][m])
    what = "share set (%)" if flag else "mean"
    rec_v = defaults(f, kind).get(parameter, "library default") if parameter not in ("model", "method") else \
        defaults(f, kind).get(next(iter(choices(kind)), "model"), "auto")
    held = ", ".join(f"{k} {_shown(v)}" for k, v in fixed.items())
    out.add(f"{kind}: {parameter} tried at {', '.join(str(v) for v in vals)} (the record's: {rec_v}); {tgt} "
            f"({what}), the whole interval, the {S.pooled_word(f.view)} pooled and each {S.pooled_word(f.view)[:-1]}; "
            + (f"held: {held}; " if held else "") + "every other input is the record's")
    if base is not None:
        row = out.child()
        zs = "; ".join(f"{z.zone_id} {row.v(_stat(base[m][np.asarray(z.indices)], flag))}" for z in f.view.zones)
        out.add(f"  baseline (record's parameters): {row.v(_stat(base[m], flag))} {_whole(f, row)}; "
                f"{row.v(_stat(base[m][idx], flag))} pooled; {zs}", row)
        _reproduction(out, f, tgt, base[m])
    for v, r in runs:
        a = _values(r["alt"], f, tgt) if _ran(r, f) else None
        row = out.child()
        if a is None:
            out.add(f"  {parameter} {v}: {tgt} not written (Petrophys: "
                    f"{'; '.join(said_whole(r['alt'].errors or [])) or 'skipped'})")
            continue
        zs = "; ".join(f"{z.zone_id} {row.v(_stat(a[m][np.asarray(z.indices)], flag))}" for z in f.view.zones)
        out.add(f"  {parameter} {v}: {row.v(_stat(a[m], flag))} {_whole(f, row)}; {row.v(_stat(a[m][idx], flag))} "
                f"pooled; {zs}", row)
    return out.result()


# --- estimate -------------------------------------------------------------------------------------------------------

ESTIMATES = {"rw": ["rwa", "pickett", "sp"], "archie_m": ["pickett"], "clay_point": ["neutron_density"],
             "gr_endpoints": ["percentiles"], "matrix": ["apparent"], "temperature": ["gradient"]}


def _curve(f: Formation, *names) -> tuple:
    for n in names:
        if n in f.inv.curves:
            v = f.view.values(n)
            if v is not None and np.isfinite(v).any():
                return n, np.asarray(v, dtype=float)
    raise ToolError(f"needs one of {', '.join(names)}; none has data here")


def sample_lithology(f: Formation, options) -> tuple:
    """Each interval sample's option for a lithology parameter (`options`: the choices Petrophys declares for it, role
    "lithology"). The sample's rock is the lithology the interpretation used (Petrophys interpreted_lithology_labels:
    the code curve it read, as its groups, else the lithology it computed), then the lithology log the zones are read
    from (the data's code table) where that names none; Petrophys takes each rock to an option (lithology_choice).
    (option per sample, None where no option names the rock or no lithology is recorded; {option: samples}; {rock no
    option names: samples}, with "no lithology recorded" for samples without one; what it rests on)."""
    from petrophys.interpretation.lithology.labels import lithology_choice
    from petrophys.interpretation.lithology.matrix_inference import interpreted_lithology_labels
    from petroharness.well.summary import code_labels
    mask = np.asarray(f.view.mask, dtype=bool)
    n = int(mask.sum())
    rock = np.full(n, None, dtype=object)
    sources = []
    try:
        got, curve = interpreted_lithology_labels(f.view.prep.well)
    except Exception:  # noqa: BLE001  (a well Petrophys reads no lithology from)
        got, curve = None, None
    if got is not None:
        sources.append((curve, np.asarray(got, dtype=object)[mask]))
    c = getattr(f.view, "lithology_curve", None)
    if c and c != curve and c in f.inv.curves and f.view.available(c):  # the data's own lithology log
        labels = code_labels(f.view, c)
        x = np.asarray(f.view.values(c), dtype=float)
        sources.append((c, np.array([labels.get(float(v)) if np.isfinite(v) else None for v in x], dtype=object)))
    used = []
    for name, per in sources:
        on = np.array([r is None and lab not in (None, "") for r, lab in zip(rock, per)], dtype=bool)
        if on.any():
            rock[on] = per[on]
            used.append(name)
    taken = {r: lithology_choice(r, options) for r in set(rock.tolist()) if r is not None}
    choice = np.array([taken.get(r) if r is not None else None for r in rock], dtype=object)
    counts, gaps = {}, {}
    for r, ch in zip(rock.tolist(), choice.tolist()):
        if ch is not None:
            counts[ch] = counts.get(ch, 0) + 1
        else:
            key = "no lithology recorded" if r is None else str(r)
            gaps[key] = gaps.get(key, 0) + 1
    basis = (f"{' then '.join(used)}, each rock taken to an option by Petrophys (lithology_choice)" if used
             else "no lithology recorded for these samples")
    return choice, counts, gaps, basis


def joined_name(head: str, label: str) -> str:
    """A curve name made of a name and a label, the name once: a label that already names it, at its start or its end,
    is the name (question suite T03: the label SW_ARCHIE_A1 on SW was written SW_SW_ARCHIE_A1)."""
    h, lab = str(head).upper(), str(label).upper()
    if not lab or h == lab or h.startswith(f"{lab}_") or h.endswith(f"_{lab}"):
        return h or lab                                   # the head already names the label
    if not h or lab.startswith(f"{h}_") or lab.endswith(f"_{h}"):
        return lab                                        # the label already names the head
    return f"{h}_{lab}"


def _zone_mask(f: Formation, zones) -> np.ndarray:
    """The samples an estimate or calibration computes on: the whole selection when the call names no zones (its
    lines then give the whole, the zones pooled and each zone: engine.scopes), else the zones it names. The union of
    the zones alone left out the samples between them, also where every sample with a value lay there."""
    n = int(f.view.mask.sum())
    if not zones:
        return np.ones(n, bool)
    keep = np.zeros(n, bool)
    for z in E.zones(f, zones):
        keep[np.asarray(z.indices)] = True
    return keep


def estimate(f: Formation, parameter: str, method: Optional[str] = None, zones=None,
             vcl_max: Optional[float] = None, phie_min: Optional[float] = None, rmf: Optional[float] = None,
             rmf_temp_f: Optional[float] = None, bht_f: Optional[float] = None, td: Optional[float] = None) -> Result:
    p = str(parameter or "").strip().lower()
    if p not in ESTIMATES:
        raise ToolError(f"no estimate of {parameter!r}; estimates: " + "; ".join(f"{k} ({', '.join(v)})" for k, v in ESTIMATES.items()))
    meth = str(method or ESTIMATES[p][0]).strip().lower()
    if meth not in ESTIMATES[p]:
        raise ToolError(f"{p} is estimated by {', '.join(ESTIMATES[p])}, not {method!r}")
    keep = _zone_mask(f, zones)
    (a, a_src), (mm, m_src) = _archie_am(f)
    vmax = float(vcl_max) if vcl_max is not None else 0.3
    pmin = float(phie_min) if phie_min is not None else 0.05
    out = Out(f)
    if p == "rw" and meth == "rwa":
        from petrophys.interpretation.electrical.rw.rwa import apparent_water_resistivity
        rn, rt = _curve(f, "RT", "RDEP")
        pn, phi = _curve(f, "PHIE")
        _, vcl = _curve(f, "VCL")
        rwa = np.asarray(apparent_water_resistivity(rt, phi, a=a, m=mm), dtype=float)
        use = keep & np.isfinite(rwa) & (rwa > 0) & np.isfinite(vcl) & (vcl < vmax) & (phi > pmin)
        if use.sum() < 10:
            raise ToolError(f"fewer than 10 clean, porous samples (VCL < {vmax}, {pn} > {pmin}) with {rn} here; "
                            "widen vcl_max or lower phie_min, or estimate over more zones")
        full = np.full(np.asarray(f.view.prep.depth).size, np.nan)
        full[f.view.mask] = rwa
        register(f, "RWA", full, f"apparent water resistivity {rn} * {pn}^m / a (Petrophys)", "ohm.m",
                 "apparent water resistivity (on request)")
        x = rwa[use]
        row = out.child()
        out.add(f"rw by apparent water resistivity (Petrophys apparent_water_resistivity: RWA = {rn} * {pn}^m / a, "
                f"a {row.v(a)} ({a_src}) and m {row.v(mm)} ({m_src})) over {row.i(x.size)} clean, porous samples (VCL < "
                f"{row.v(vmax)}, {pn} > {row.v(pmin)}), at formation temperature: min {row.v(x.min())}, p5 "
                f"{row.v(np.percentile(x, 5))}, p10 {row.v(np.percentile(x, 10))}, median {row.v(np.median(x))} ohm.m. "
                f"In water-bearing clean rock RWA equals Rw; hydrocarbons raise it, so Rw is read from the low end. "
                f"The record's Rw: {_rec_rw(f, row)}. Written: RWA (a curve of this question).", row)
        return out.result()
    if p in ("rw", "archie_m") and meth == "pickett":
        from petrophys.interpretation.electrical.cementation.pickett_analysis import pickett_analysis
        rn, rt = _curve(f, "RT", "RDEP")
        pn, phi = _curve(f, "PHIE")
        _, vcl = _curve(f, "VCL")
        use = keep & np.isfinite(rt) & np.isfinite(phi) & (phi > 0) & (rt > 0)
        try:
            with warnings.catch_warnings(record=True) as caught:      # Petrophys's own caution on the fit, shown
                warnings.simplefilter("always")
                params, info = pickett_analysis(rt[use], phi[use], sw_water=1.0, vcl_cutoff=vmax, vcl=vcl[use])
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Petrophys pickett_analysis: {type(e).__name__}: {str(e)[:300]}") from None
        said = str((info or {}).get("error") or "").strip()
        if said:      # its a, m and n are then the defaults it started from, not a fit
            raise ToolError(f"Petrophys pickett_analysis could not fit: {said[:200]} ({int(use.sum())} samples with "
                            f"{rn} and {pn}, clean below VCL {vmax}); widen vcl_max, or estimate over more zones")
        row = out.child()
        extra = {k: v for k, v in (info or {}).items() if _num(v)}
        out.add(f"Pickett analysis (Petrophys pickett_analysis on {rn} and {pn}, clean samples VCL < {row.v(vmax)}, "
                f"water line at SW 1): a {row.v(params.a)}, m {row.v(params.m)}, n {row.v(params.n)}"
                + ("; " + ", ".join(f"{k} {row.v(v)}" for k, v in extra.items()) if extra else "")
                + f" (for comparison: a {row.v(a)} ({a_src}), m {row.v(mm)} ({m_src}); the record's Rw "
                  f"{_rec_rw(f, row)})", row)
        notes = said_whole(w.message for w in caught if isinstance(w.message, UserWarning))
        if notes:
            out.add("  Petrophys said: " + "; ".join(notes))
            sel = str(getattr(f.view, "selection", "") or "")
            if getattr(f.view, "reach", "focus") == "well" and not sel.startswith("where "):
                out.add('  the water-bearing samples alone: this call again with "where" (e.g. "SW > 0.95"), the fit '
                        'then reads only the samples where it holds')
        return out.result()
    if p == "rw" and meth == "sp":
        return _rw_sp(f, keep, rmf, rmf_temp_f)
    if p == "gr_endpoints":
        return _gr_endpoints(f, keep)
    if p == "matrix":
        return _matrix(f, keep)
    if p == "temperature":
        return _temperature(f, bht_f, td)
    if p == "clay_point":
        from petrophys.interpretation.clay_volume.nd_method import nd_shale_point
        _, nphi = _curve(f, "NPHI")
        _, rhob = _curve(f, "RHOB")
        _, vcl = _curve(f, "VCL")
        shale = keep & np.isfinite(vcl) & (vcl > 0.6)
        try:
            r_sh, n_sh = nd_shale_point(nphi[keep], rhob[keep], shale[keep])   # Petrophys returns (den_clay, neu_clay)
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Petrophys nd_shale_point: {type(e).__name__}: {str(e)[:300]}") from None
        row = out.child()
        out.add(f"clay point (Petrophys nd_shale_point on {row.i(int(shale.sum()))} shale samples, VCL > 0.6): NPHI "
                f"{row.v(n_sh)}, RHOB {row.v(r_sh)}", row)
        return out.result()
    raise ToolError(f"{p} by {meth} is not available")


def _zone_means(f: Formation, x: np.ndarray, keep: np.ndarray, row: Out, stat=np.nanmedian) -> str:
    """A per-sample curve's value (median by default) over the bases every tool reports by, the whole selection first
    (engine.over_bases), each with its count."""
    return E.over_bases(f, np.where(keep, np.asarray(x, dtype=float), np.nan), row, stat, n=True)


def _full(f: Formation, x: np.ndarray) -> np.ndarray:
    """Interval values placed over the well's samples (NaN elsewhere), as register takes them."""
    full = np.full(np.asarray(f.view.prep.depth).size, np.nan)
    full[f.view.mask] = x
    return full


def _gr_endpoints(f: Formation, keep: np.ndarray) -> Result:
    """GR clean and shale lines by the clay-volume step's rule: P5 and P95 of the GR picks, bounded by Petrophys
    (bounded_gr_baselines), over the samples asked and over the whole well, against the record's."""
    from petrophys.interpretation.clay_volume.gr_method import GR_CLEAN_BOUND, GR_SHALE_BOUND, bounded_gr_baselines
    gn, gr = _curve(f, "GR")
    out, row = Out(f), None
    lines = []
    for what, x in (("the samples asked", gr[keep]), ("the whole well", f.view.well_values(gn))):
        x = np.asarray(x, dtype=float)
        x = x[np.isfinite(x)]
        if x.size < 10:
            continue
        p5, p95 = float(np.percentile(x, 5)), float(np.percentile(x, 95))
        clean, shale = bounded_gr_baselines(p5, p95)
        row = out.child()
        lines.append(((f"  over {what} ({row.i(x.size)} samples): P5 {row.v(p5)}, P95 {row.v(p95)} API -> clean "
                       f"{row.v(clean)}, shale {row.v(shale)} API"), row))
    if not lines:
        raise ToolError(f"fewer than 10 {gn} samples here")
    rec = (_method(f, "clay_volume").parameters or {}) if _method(f, "clay_volume") else {}
    bounds = out.child()
    out.add(f"GR endpoints by the clay-volume step's rule ({gn}: P5 for clean, P95 for shale, bounded by Petrophys "
            f"bounded_gr_baselines to a clean line of at most {bounds.v(GR_CLEAN_BOUND)} and a shale line of at least "
            f"{bounds.v(GR_SHALE_BOUND)} API):", bounds)
    for ln, r in lines:
        out.add(ln, r)
    picked = [k for k in ("gr_min", "gr_max", "gr_min_used", "gr_max_used") if _num(rec.get(k))]
    if picked:
        r = out.child()
        out.add("  the record's: " + ", ".join(f"{k} {r.v(rec[k])}" for k in picked) + " API", r)
    return out.result()


def _matrix(f: Formation, keep: np.ndarray) -> Result:
    """Apparent matrix density (RHOmaa) and volumetric photoelectric absorption (Umaa) by Petrophys, per zone,
    against the minerals' values from Petrophys's mineral table and the matrix the record's porosity used."""
    from petrophys.interpretation.lithology.apparent_matrix import (apparent_matrix_density,
                                                                    apparent_matrix_volumetric_pe,
                                                                    apparent_total_porosity)
    from petrophys.interpretation.lithology.matrix_properties import MINERAL_PROPERTIES
    _, rhob = _curve(f, "RHOB")
    _, nphi = _curve(f, "NPHI")
    phia = np.asarray(apparent_total_porosity(rhob, nphi), dtype=float)
    rhomaa = np.asarray(apparent_matrix_density(rhob, phia), dtype=float)
    register(f, "RHOMAA", _full(f, rhomaa), "apparent matrix density: RHOB with the pore fluid removed (Petrophys)",
             "g/cc", "apparent matrix (on request)")
    out = Out(f)
    row = out.child()
    out.add(f"apparent matrix by Petrophys (apparent_total_porosity from RHOB and NPHI on the limestone reference, then "
            f"apparent_matrix_density): RHOmaa (median, g/cc) {_zone_means(f, rhomaa, keep, row)}. Written: RHOMAA.", row)
    if "PEF" in f.inv.curves and f.view.available("PEF"):
        pef = np.asarray(f.view.values("PEF"), dtype=float)
        umaa = np.asarray(apparent_matrix_volumetric_pe(pef, rhob, phia), dtype=float)
        register(f, "UMAA", _full(f, umaa), "apparent matrix volumetric photoelectric absorption (Petrophys)", "b/cc",
                 "apparent matrix (on request)")
        row = out.child()
        out.add(f"  Umaa (median, b/cc; from PEF, apparent_matrix_volumetric_pe) {_zone_means(f, umaa, keep, row)}. "
                "Written: UMAA.", row)
    else:
        out.add("  no PEF here: Umaa (the RHOmaa-Umaa lithology plot) needs it")
    row = out.child()
    minerals = "; ".join(f"{m} {row.v(MINERAL_PROPERTIES[m]['density'])} g/cc, U {row.v(MINERAL_PROPERTIES[m]['u'])}"
                         for m in ("quartz", "calcite", "dolomite", "anhydrite") if m in MINERAL_PROPERTIES)
    rec = (_method(f, "porosity").parameters or {}) if _method(f, "porosity") else {}
    used = f"; the record's porosity used matrix density {row.v(rec['rho_ma'])} g/cc" if _num(rec.get("rho_ma")) else ""
    out.add(f"  minerals (Petrophys mineral table): {minerals}{used}", row)
    return out.result()


def _temperature_source(rec: dict, row) -> str:
    """Where the record's temperature comes from, from its step's parameters: the measured log with the gradient
    filling its gaps; a gradient anchored to a bottom-hole temperature; or the default gradient, no anchor."""
    g = f"{row.v(rec['gradient_f_per_100ft'])} degF/100ft" if _num(rec.get("gradient_f_per_100ft")) else ""
    surf = f" from a surface {row.v(rec['surface_temp_f'])} degF" if _num(rec.get("surface_temp_f")) else ""
    anchored = _num(rec.get("bht_f"))
    grad = (f"the gradient {g}{surf} to the bottom-hole {row.v(rec['bht_f'])} degF" if anchored else
            f"a default gradient {g}{surf} (no bottom-hole temperature anchors it)") if g else ""
    if _num(rec.get("temp_log_coverage")):
        gaps = rec.get("temp_log_gap_samples")
        fill = (f"; where the log has no value, {grad}" + (f", at {row.i(int(gaps))} samples" if _num(gaps) else "")
                if grad else "")
        return f": the measured temperature log at {row.pct(100 * float(rec['temp_log_coverage']))} of the well's samples{fill}"
    return f": {grad}" if grad else ""


def _temperature(f: Formation, bht_f: Optional[float], td: Optional[float]) -> Result:
    """Formation temperature as the record's temperature step has it (its TEMP and gradient), and the gradient from
    a bottom-hole temperature (given, else the LAS header's) by Petrophys estimate_gradient_from_bht."""
    from petrophys.interpretation.temperature.temp_gradient import estimate_gradient_from_bht
    m = _method(f, "temperature")
    rec = (m.parameters or {}) if m else {}
    out = Out(f)
    if "TEMP" in f.inv.curves and f.view.available("TEMP"):
        temp = np.asarray(f.view.values("TEMP"), dtype=float)
        keep = np.isfinite(temp)
        row = out.child()
        out.add(f"formation temperature (the record's TEMP; temperature step {m.method if m else 'unknown'}"
                f"{_temperature_source(rec, row)}): mean, degF: {_zone_means(f, temp, keep, row, np.nanmean)}"
                + "".join(f"; TEMP {x}" for x in limits(f, "TEMP")), row)     # what its values show (engine.limits)
    hdr = getattr(f.view.prep.well, "header", None)
    bht = bht_f if bht_f is not None else (getattr(hdr, "bht", None) if hdr is not None else None)
    bht_unit = "F" if bht_f is not None else str(getattr(hdr, "bht_unit", None) or "F")
    depth = td if td is not None else (getattr(hdr, "td", None) if hdr is not None else None)
    depth_unit = f.inv.depth_unit if td is not None else str(getattr(hdr, "td_source_unit", None) or f.inv.depth_unit)
    if not (_num(bht) and _num(depth)):
        out.add("  no bottom-hole temperature here (none given, none in the LAS header): give bht_f (degF) and td (the "
                f"total depth, {f.inv.depth_unit}) for a gradient from them")
        return out.result()
    try:
        g = estimate_gradient_from_bht(float(bht), float(depth), bht_unit=bht_unit, depth_unit=depth_unit)
    except Exception as e:  # noqa: BLE001  (the library refuses a temperature or depth it cannot use)
        raise ToolError(f"Petrophys estimate_gradient_from_bht: {str(e)[:300]}") from None
    row = out.child()
    src = "given" if bht_f is not None else "LAS header"
    vs = (f" (the record's: {row.v(rec['gradient_f_per_100ft'])})" if _num(rec.get("gradient_f_per_100ft")) else "")
    out.add(f"  gradient from BHT {row.v(bht)} {bht_unit} at TD {row.v(depth)} {depth_unit} ({src}; Petrophys "
            f"estimate_gradient_from_bht): {row.v(g)} degF/100ft{vs}", row)
    return out.result()


def _rw_sp(f: Formation, keep: np.ndarray, rmf: Optional[float], rmf_temp_f: Optional[float]) -> Result:
    """Rw from the static SP over the samples asked, by Petrophys sp_rw_in_window: its clean and shale SP lines, the
    mud-filtrate resistivity (given, else the LAS header's) and the record's formation temperature."""
    from petrophys.interpretation.electrical.rw.sp_window import sp_rw_in_window
    _curve(f, "SP")
    hdr = getattr(f.view.prep.well, "header", None)
    rm_f = rmf if rmf is not None else getattr(hdr, "rmf", None)
    rm_t = rmf_temp_f if rmf_temp_f is not None else getattr(hdr, "rm_temp", None)
    if not (_num(rm_f) and _num(rm_t)):
        raise ToolError("rw by sp needs the mud-filtrate resistivity: give rmf (ohm.m) and rmf_temp_f (degF), as this "
                        "LAS header states none")
    temp = f.view.prep.curve("TEMP")
    if temp is None:
        raise ToolError("rw by sp needs the formation temperature (TEMP), which the record does not have here")
    depth = np.asarray(f.view.prep.depth, dtype=float)[f.view.mask][keep]
    try:
        res = sp_rw_in_window(f.view.prep.well, rmf=float(rm_f), rmf_temp_f=float(rm_t),
                              temperature_f=np.asarray(temp, dtype=float), top=float(depth.min()),
                              bottom=float(depth.max()))
    except Exception as e:  # noqa: BLE001  (the library's own reason, said back)
        raise ToolError(f"Petrophys sp_rw_in_window: {str(e)[:300]}") from None
    out = Out(f)
    row = out.child()
    src = "given" if rmf is not None else "LAS header"
    out.add(f"rw from the static SP (Petrophys sp_rw_in_window over {row.i(res.n_samples)} samples, "
            f"{row.i(res.n_clean_samples)} clean): Rw {row.v(res.rw)} ohm.m at {row.v(res.reference_temp_f)} degF; SSP "
            f"{row.v(res.ssp_mv)} mV (clean line {row.v(res.sp_clean_mv)}, shale line {row.v(res.sp_shale_mv)} mV); Rmf "
            f"{row.v(rm_f)} ohm.m at {row.v(rm_t)} degF ({src}). A small SSP means water about as saline as the "
            f"filtrate: then read it as a consistency check. The record's Rw: {_rec_rw(f, row)}.", row)
    return out.result()


def _archie_am(f: Formation) -> list:
    """Archie's a and m with their source: the record's where it states a number, else the library's (a 1, m 2) with
    what the record states instead (lithology_dependent: one per lithology, no single number)."""
    sat, m = defaults(f, "saturation"), _method(f, "saturation")
    rec = (m.parameters or {}) if m else {}
    return [(sat[k], "record") if k in sat else
            (d, "library default" + (f"; the record's is {rec[k]}" if rec.get(k) not in (None, "") else ""))
            for k, d in (("a", 1.0), ("m", 2.0))]


def _rec_rw(f: Formation, row: Out) -> str:
    """The record's Rw as its formation_water step states it: the value with its reference temperature, and the
    range at formation temperature."""
    m = _method(f, "formation_water")
    rec = (m.parameters or {}) if m else {}
    one = next((k for k in ("rw", "rw_from_rwa", "rw_at_measured_temp") if _num(rec.get(k))), None)
    temp = next((rec[k] for k in ("reference_temp_f", "rwa_reference_temp_f", "measured_temp_f") if _num(rec.get(k))), None)
    parts = []
    if one:
        parts.append(f"{row.v(rec[one])} ohm.m ({one}{f' at {row.v(temp)} degF' if temp is not None else ''})")
    if _num(rec.get("rw_min")) and _num(rec.get("rw_max")):
        parts.append(f"{row.v(rec['rw_min'])}-{row.v(rec['rw_max'])} ohm.m at formation temperature")
    return "; ".join(parts) + f" (method {m.method})" if parts and m else "not stated"


def menu_text(kinds=None) -> str:
    """The properties with their methods, from the library's catalog (the calculate tool's description)."""
    lines = []
    for prop, kind in PROPERTIES.items():
        if kinds and kind not in kinds:
            continue
        ch = choices(kind)
        meth = "; ".join(f"{p}: {' | '.join(n for n, _ in opts)}" for p, opts in ch.items())
        params = ", ".join(p for p in parameters(kind) if p not in ch)
        lines.append(f"    {prop}: " + (meth + "; " if meth else "")
                     + (f"parameters {params}" if params else "no parameters (recomputed from its inputs)"))
    return "\n".join(lines)
