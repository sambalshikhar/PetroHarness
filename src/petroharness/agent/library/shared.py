"""What the verbs share: Petrophys's catalog of steps and methods, the record's parameters, running a step again with
changed parameters, curves of the question (register, free_name), and the helpers the verbs read curves and zones
with."""

from __future__ import annotations

import copy
import re
import threading
from functools import lru_cache
from typing import Optional
import numpy as np
from petroharness.agent import engine as E
from petroharness.agent.engine import Formation, Out, ToolError
from petroharness.agent.map import num
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


def free_name(f: Formation, name: str) -> str:
    """The name a curve of the question is written under: its own, unless the well's record or its analyzers hold a
    curve of that name (a lookup reads theirs first, so the new curve would be hidden); then NAME_LIB (NAME_LIB2, ...).
    A curve computed on request before keeps its name: computing it again replaces it."""
    view = f.view
    prep = getattr(view, "prep", None)

    def taken(n: str) -> bool:
        return n not in view.calculated and (n in f.inv.curves or n in getattr(view, "analyzer_curves", {})
                                             or (prep is not None and prep.curve(n) is not None))
    out, k = name, 1
    while taken(out):
        out, k = f"{name}_LIB" + (str(k) if k > 1 else ""), k + 1
    return out


def register(f: Formation, name: str, full: np.ndarray, meaning: str, unit: str, step: str) -> str:
    """A curve of the question: over the well's samples, read by every lookup and condition. -> the name it is
    written under (free_name: never one the record holds)."""
    name = free_name(f, name)
    f.view.calculated[name] = full
    if unit == "flag":                                  # read as a flag by runs, stats and conditions
        f.view.calc_flags.add(name)
    vals = full[f.view.mask]
    ok = np.isfinite(vals)
    f.inv.curves[name] = Curve(name=name, unit=unit or "", meaning=meaning, meaning_from="step", source="computed",
                               step=step, coverage=float(ok.mean()) if ok.size else 0.0, n=int(ok.sum()),
                               zone_coverage={z.zone_id: float(ok[np.asarray(z.indices)].mean())
                                              for z in f.view.zones if np.asarray(z.indices).size})
    return name


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
    the zones as its breakdown (what_if gave zones pooled only, and every net-reservoir sample lay
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
    # change in a table or a summary, away from the pair it was read from ("0.6621 (-0.0294)")
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
        r_out = out.child()            #   off the pairs, a range took one side's end and the other's

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
    is the name (the label SW_ARCHIE_A1 on SW was written SW_SW_ARCHIE_A1)."""
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


def _zone_means(f: Formation, x: np.ndarray, keep: np.ndarray, row: Out, stat=np.nanmedian) -> str:
    """A per-sample curve's value (median by default) over the bases every tool reports by, the whole selection first
    (engine.over_bases), each with its count."""
    return E.over_bases(f, np.where(keep, np.asarray(x, dtype=float), np.nan), row, stat, n=True)


def _full(f: Formation, x: np.ndarray) -> np.ndarray:
    """Interval values placed over the well's samples (NaN elsewhere), as register takes them."""
    full = np.full(np.asarray(f.view.prep.depth).size, np.nan)
    full[f.view.mask] = x
    return full
