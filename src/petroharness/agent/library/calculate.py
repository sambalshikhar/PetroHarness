"""The calculate and what_if verbs: a property computed again by Petrophys with another method or parameters, and
the menus the brief shows for them."""

from __future__ import annotations

import json
from typing import Optional
import numpy as np
from petroharness.agent import engine as E
from petroharness.agent.engine import Formation, Out, Result, ToolError, said_whole
from petroharness.well import summary as S
from petroharness.agent.library.shared import MAX_VALUES, PROPERTIES, TARGETS, _changes, _coerce, _effect, _flag, _label, _method, _pooled, _ran, _reproduction, _shown, _sources, _stat, _values, _whole, catalog, choices, defaults, joined_name, kind_of, parameters, register, run, unlisted_method


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
        shown = _shown(val, row)                                   # a number, or a number with its unit
        src = "record" if p in rec else "library default"
        if p in ("model", "method") and unlisted_method(f, kind):     # the record's method is not a choice
            src = f"library default; the record's {unlisted_method(f, kind)} is not one of the choices"
        opts = f"; choices: {', '.join(n + (' (' + ', '.join(o) + ')' if o else '') for n, o in ch[p])}" if p in ch else ""
        desc = d.get("description", "") if isinstance(d, dict) else ""
        out.add(f"  {p} = {shown} ({src}){': ' + desc if desc else ''}{opts}", row)
    return out.result()


def advice_calls(names, takes=(), kind: Optional[str] = None) -> str:
    """The inputs Petrophys's advice asks for (its Advice inputs: "add steps.mud_filtrate(rmf=..., rmf_meas_temp=...)"
    asks for rmf and rmf_meas_temp), as the calls of this harness that take each - the tool's own argument first (`takes`),
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
        unit = "flag" if f.view.is_flag(c) else (f.inv.curves[c].unit if c in f.inv.curves else "")
        written.append(register(f, joined_name(c, lab), a_full, f"{c} recomputed by Petrophys ({kind}: {asked})", unit,
                                f"{kind} ({asked}, on request)"))
        m = f.view.mask
        _effect(out, f, c, a_full[m], None if b_full is None else b_full[m], basis)
        if basis == "baseline":
            _reproduction(out, f, c, None if b_full is None else b_full[m])
    out.add(f"  written: {', '.join(written) or 'nothing'}"
            + (f" (curves of this question: use them in any lookup, e.g. stats {written[0]}, or compare {written[0]} "
               f"{computed[0]})" if written else ""))
    return out.result()


def what_if(f: Formation, property: str, parameter: str, values, target: Optional[str] = None,
            parameters: Optional[dict] = None) -> Result:
    """parameters: inputs held at a given value for every run beside the one varied (Rw's temperature: rw_meas_temp)."""
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
    rec_v = _shown(rec_v)                                             # (230.0, "degF") as 230 degF
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
