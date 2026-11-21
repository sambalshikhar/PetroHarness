"""The evidence catalog: small deterministic queries over a formation view (zone statistics, lithology tables,
class runs, flags, relations), each a petrophys call or a listed generic data operation."""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional, Union


import re

import numpy as np
from pydantic import BaseModel, Field

from petroharness.well.calculations import calculations
from petroharness.record.card import cutoff_fact, invasion_route, last_step, recorded_inputs, sxo_route
from petroharness.well.stats import statistic
from petroharness.well import summary as S
from petrophys.evaluation.net_pay import lithology_in  # noqa: F401  (petrophys; re-exported for the confidence rules)
from petroharness.well.view import FormationView, fmt, fmt_depth, fmt_pct, sig

# geometric and harmonic means (over the positive samples, petrophys curve_statistics) for log-normal curves such as
# permeability; the third-power average and the mode, the rest of the statistics the workflow of record reports per
# group. Lookups ask for them, so every summarising lookup offers them.
STATS = ("mean", "median", "min", "max", "std", "var", "max_abs", "p10", "p25", "p50", "p75", "p90", "iqr",
         "geometric_mean", "harmonic_mean", "third_power_average", "mode")
NOT_EXPORTED = "computed from the log samples of this interval"


class EvidenceError(ValueError):
    pass



class Evidence(BaseModel):
    id: str
    call: str
    args: dict[str, Any]
    title: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Union[str, float, int, None]]] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)   # every number shown, for the verifier
    coefficients: list[tuple[float, int]] = Field(default_factory=list)   # sample-level coefficients shown, with n
    runs: list[dict[str, Any]] = Field(default_factory=list)   # flagged_runs: every run, for the code-composed block

    def render(self) -> str:
        out = [f"[{self.id}] {self.title}"]
        if self.columns:
            out.append(" | ".join(self.columns))
            for r in self.rows:
                out.append(" | ".join("n/a" if v is None else (fmt(v) if isinstance(v, float) else str(v)) for v in r))
        out.extend(f"- {f}" for f in self.facts)
        return "\n".join(out)


def _stat(x: np.ndarray, name: str) -> float:
    """One statistic of a curve's finite samples, from petrophys (petroharness.well.stats)."""
    return statistic(x, name)


_WHERE = re.compile(r"^\s*([A-Za-z_]+)\s*(<=|>=|==|!=|=|<|>)\s*(p\d{1,2}|-?\d+(?:\.\d+)?)\s*$")


def _where_mask(view: FormationView, where: Optional[str]) -> tuple[np.ndarray, str]:
    """Sample mask for a simple condition 'CURVE OP VALUE' where VALUE is a number or pNN of that curve."""
    n = int(view.mask.sum())
    if not where:
        return np.ones(n, dtype=bool), ""
    m = _WHERE.match(where)
    if not m:
        raise EvidenceError(f"WHAT: cannot read where={where!r}. FIX: use 'CURVE OP VALUE', e.g. 'GR < p25', 'VCL < 0.3' or 'NET_PAY == 1'.")
    curve, op, value = m.group(1).upper(), m.group(2), m.group(3)
    data = view.values(curve)
    if data is None or not np.isfinite(data).any():
        raise EvidenceError(f"WHAT: {curve} has no data here. FIX: use a curve listed on the formation card.")
    thr = float(np.nanpercentile(data, int(value[1:]))) if value.startswith("p") else float(value)
    with np.errstate(invalid="ignore"):
        mask = {"<": data < thr, "<=": data <= thr, ">": data > thr, ">=": data >= thr,
                "==": np.isclose(data, thr), "=": np.isclose(data, thr), "!=": ~np.isclose(data, thr)}[op]
    return mask & np.isfinite(data), f"where {curve} {op} {fmt(thr)}" + (f" ({value} of {curve})" if value.startswith("p") else "")


def _missing_text(view: FormationView, missing: list[str]) -> str:
    """The curves asked for that have no data here, each with the closest curve that has (a misspelt mnemonic)."""
    import difflib
    names = list(getattr(getattr(view.prep, "well", None), "_curves", {}) or {})
    have = [c for c in names if view.available(c)]
    out = []
    for c in missing:
        near = difflib.get_close_matches(c, have, n=1, cutoff=0.6)
        out.append(f"{c} (did you mean {near[0]}?)" if near and near[0] != c else c)
    return "not available in this interval: " + ", ".join(out)


def _check_curves(view: FormationView, curves: list[str]) -> tuple[list[str], list[str]]:
    if not curves:
        raise EvidenceError("WHAT: no curves given. WHY: statistics need at least one curve. "
                            "FIX: pass curves=[...] using mnemonics from the formation card.")
    bad = [c for c in curves if not isinstance(c, str)]
    if bad:
        raise EvidenceError(f"WHAT: {bad!r} is not a curve mnemonic. WHY: each curve argument is one mnemonic string. "
                            "FIX: pass single mnemonics (one call per curve pair for correlation).")
    curves = view.resolve_curves(curves)         # "measured" / a log family name -> the curves present
    if not curves:
        raise EvidenceError("WHAT: no curve of the named log family has data in this interval. "
                            "FIX: choose curves listed on the formation card.")
    ok, missing = [], []
    for c in curves:
        (ok if view.available(c.upper()) else missing).append(c.upper())
    if not ok:
        raise EvidenceError(f"WHAT: none of {curves} has data in this interval. WHY: absent or all null. "
                            "FIX: choose curves listed as present/available on the formation card.")
    return ok, missing


def _check_stats(stats: list[str]) -> list[str]:
    stats = [s.lower() for s in (stats or ["mean"])]
    bad = [s for s in stats if s not in STATS]
    if bad:
        raise EvidenceError(f"WHAT: unknown statistic(s) {bad}. FIX: use any of {list(STATS)}.")
    return stats


def _zones(view: FormationView, zones: Optional[list[str]]):
    if not zones or zones == "all":
        return view.zones
    picked = [view.zone(z) for z in zones]
    unknown = [z for z, p in zip(zones, picked) if p is None]
    if unknown:
        raise EvidenceError(f"WHAT: unknown zone ids {unknown}. FIX: use ids Z1..Z{len(view.zones)} from the card.")
    return picked


def _differs(a: float, b: float, view: FormationView) -> bool:
    """Whether two figures of one quantity on two sample bases differ materially (catalog limit
    basis_note_min_relative_difference, relative to the larger): only then is the second basis worth a note."""
    if a is None or b is None or not (np.isfinite(a) and np.isfinite(b)):
        return False
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) > view.reg.limit("basis_note_min_relative_difference", 0.02) * scale


def flag_runs(depth: np.ndarray, flag: np.ndarray) -> list[tuple[int, int]]:
    """The flagged runs as (first, last) sample indices, from petrophys evaluation.intervals.flag_intervals
    (consecutive flagged samples, never joined across a depth gap of more than 1.5 sampling steps). The library
    reports each run's cell boundaries; the harness shows the first and last flagged samples, like its zones."""
    from petrophys.evaluation.intervals import flag_intervals as library_intervals

    depth = np.asarray(depth, dtype=float)
    on = np.isfinite(np.asarray(flag, dtype=float)) & (np.asarray(flag, dtype=float) > 0.5)
    if not on.any():
        return []
    out = []
    for top, bottom in zip(*library_intervals(on, depth)[["top", "bottom"]].to_numpy().T):
        idx = np.flatnonzero(on & (depth >= top) & (depth <= bottom))
        out.append((int(idx[0]), int(idx[-1])))
    return out


def _runs(depth: np.ndarray, flag: np.ndarray, step: float = 0.0) -> list[tuple[float, float]]:
    """The flagged runs as (first, last) sample depths (flag_runs)."""
    return [(float(depth[a]), float(depth[b])) for a, b in flag_runs(depth, flag)]


def grade_interval(view: FormationView, top: float, base: float) -> tuple[str, str, str, list[str]]:
    """(zone id, lithology, confidence, reasons) for a screen-flag interval: petrophys net_pay.grade_interval under the
    policy's confidence rules, on the majority lithology-log label of the interval's own samples (majority_label;
    none: unknown), its bad-hole share and its thickness."""
    from petroharness.well.formation import MISSING_LITHOLOGY
    from petrophys.evaluation.net_pay import grade_interval as library_grade, majority_label

    rules = view.policy.get("confidence", {})
    sel = (view.depth >= top - 1e-6) & (view.depth <= base + 1e-6)
    mid = (top + base) / 2
    zone = next((z for z in view.zones if z.top - 1e-6 <= mid <= z.base + 1e-6), None)
    lith = majority_label(list(view.labels[sel]), missing=(MISSING_LITHOLOGY,))
    bh = view.values("BAD_HOLE")
    bad_hole = float(np.nanmean(bh[sel] > 0.5)) if bh is not None and sel.any() else None
    min_m = rules.get("min_thickness_m", 1.0)
    conf, reasons = library_grade(lith, bad_hole, (base - top + view.step) * view.m_per_unit,     # graded in metres,
                                  non_reservoir_lithologies=rules.get("non_reservoir_lithologies", []),
                                  marginal_lithologies=rules.get("marginal_lithologies", []),
                                  max_bad_hole_fraction=rules.get("max_bad_hole_fraction", 0.5),
                                  min_thickness=min_m)
    thin = f"thinner than {min_m} m"                                  # the library's reason, shown in the reporting unit
    reasons = [f"thinner than {length_m(view, min_m)}" if r == thin else r for r in reasons]
    return (zone.zone_id if zone else "-", lith, conf, reasons)


def pay_confidence(view: FormationView) -> dict:
    data = view.values("NET_PAY")
    out = {"higher_m": 0.0, "low_m": 0.0, "low_reasons": {}}
    if data is None:
        return out
    for a, b in _runs(view.depth, data, view.step):
        _, _, conf, reasons = grade_interval(view, a, b)
        thick = b - a + view.step
        out[f"{conf}_m"] += thick
        for r in reasons:
            key = r.split(" ")[0] if r.startswith("bad hole") else r
            out["low_reasons"][key] = out["low_reasons"].get(key, 0.0) + thick
    return out


# --- catalog -----------------------------------------------------------------------------------

# The largest per-zone table a lookup returns (values = curves x statistics x zones, about 2.8 tokens each): every
# curve and statistic on a 30-zone formation is about 100k tokens, which would push the next step's prompt past the
# model's context and leave the answer empty.
MAX_ZONE_VALUES = 5000


def length_m(view: FormationView, metres: float) -> str:
    """A length stated in metres (a policy threshold, a tool argument): as stated when depths are shown in metres, else
    in the reporting unit."""
    return f"{metres} m" if view.depth_unit == "m" else f"{fmt(view.to_unit(metres))} {view.depth_unit}"

def zone_stats(view: FormationView, curves: list[str], stats: list[str] = None, zones=None) -> dict:
    (curves, missing), stats = _check_curves(view, curves), _check_stats(stats)
    n = len(curves) * len(stats) * len(_zones(view, zones))
    if n > MAX_ZONE_VALUES:
        raise EvidenceError(f"WHAT: a table of {n} values ({len(curves)} curves x {len(stats)} statistics x "
                            f"{len(_zones(view, zones))} zones, about {round(2.8 * n / 1000)}k tokens) is too large to read. "
                            f"FIX: ask for at most {MAX_ZONE_VALUES} values - fewer curves or statistics per call (split the "
                            f"curves over several calls), or interval_stats for formation values.")
    cols = ["zone", "lithology", f"depth ({view.depth_unit})"] + [f"{s} {c}" + (f" ({view.unit(c)})" if view.unit(c) else "")
                                                 for c in curves for s in stats]
    rows, values = [], []
    for z in _zones(view, zones):
        row = [z.zone_id, z.lithology, f"{fmt_depth(z.top)}–{fmt_depth(z.base)}"]
        for c in curves:
            data = view.zone_values(z, c)
            for s in stats:
                v = sig(_stat(data, s))
                row.append(v)
                values.append(v)
        rows.append(row)
    return {"facts": [_missing_text(view, missing)] if missing else [],
            "title": f"Zone {', '.join(stats)} of {', '.join(curves)}"
            + (" (flag curves: mean = fraction of zone flagged)" if any(view.is_flag(c) for c in curves) else ""),
            "columns": cols, "rows": rows, "values": values + [z.top for z in view.zones] + [z.base for z in view.zones]}


def _stat_names(stats: Optional[list[str]], x) -> tuple[list[str], bool]:
    """The statistics of a table column set (the summary layer's names) and whether percentiles are read on log10
    values: the asked ones the layer computes, or its default set with the geometric mean added by the shape of x."""
    if stats:
        asked = [S.statistic_name(n) for n in stats]
        return list(dict.fromkeys(n for n in asked if S.known(n) and n != "n")) or ["mean"], False
    return [n for n in S.names(None, x) if n != "n"], S.log_shaped(x)


def _stats_of(data, names: list[str], log: bool) -> list:
    """The named statistics of data (the summary layer); percentiles on log10 values for a log-shaped curve."""
    got = S.compute(data, names, log)
    return [sig(got[n]) for n in names]


def _class_cell(view: FormationView, c: str, data) -> str:
    """A flag's or class codes' cell (summary.curve_kind): the share of the samples with a value set, in each class,
    or at the one value; never a statistic of codes."""
    k = S.curve_kind(view, c)
    labels = S.code_labels(view, c)
    n, counts = S.class_counts(data, k.codes, labels if k.kind == "classes" else None)
    if not n:
        return "-"
    if k.kind == "flag":
        return f"set {fmt_pct(100 * dict(counts).get(1.0, 0) / n, 1, sign=False)}%"
    return ", ".join(f"{S.code_text(code, labels)} {fmt_pct(100 * m / n, 1, sign=False)}%" for code, m in counts)


def lithology_stats(view: FormationView, curves: list[str], stats: list[str] = None) -> dict:
    """Per lithology of the zones: its share of the zoned thickness (runs above the zone minimum) and of the whole
    interval (every sample with that lithology-log label), with statistics pooled over its zone samples
    (sample-weighted); then the zones pooled and the whole interval where samples lie outside the zones, with what
    those samples hold (a labelled gap: a rock type found only there is never a row of its own). Statistics: the asked
    ones, or the default set (the summary layer)."""
    from petroharness.well.formation import MISSING_LITHOLOGY

    (curves, missing) = _check_curves(view, curves)
    by_lith: dict[str, list] = {}
    for z in view.zones:
        by_lith.setdefault(z.lithology, []).append(z)
    labels = np.asarray(view.labels)
    n_all = labels.size
    names = {c: _stat_names(stats, view.values(c)) if S.curve_kind(view, c).kind == "values" else (["shares"], False)
             for c in curves}                                 # a flag's or class codes' shares, never their statistics
    cols = (["lithology", "zones", f"zoned thickness ({view.depth_unit})", "share of zoned (%)", f"interval thickness ({view.depth_unit})",
             "share of interval (%)"] + [f"{s} {c}" for c in curves for s in ["n"] + names[c][0]])
    stats_of = lambda c, data: [_class_cell(view, c, data)] if names[c][0] == ["shares"] else _stats_of(data, *names[c])
    rows, values = [], []
    zoned = view.zoned_thickness
    for lith, zones in by_lith.items():
        n_lith = int(np.sum(labels == lith))
        interval_thick = sig(view.gross * n_lith / n_all) if n_all else None
        interval_share = round(100 * n_lith / n_all, 1) if n_all else None
        if n_lith and interval_share == 0:
            interval_share = fmt_pct(100 * n_lith / n_all, 1, sign=False)      # "<0.1": present, not absent
        thick = sig(sum(z.thickness for z in zones)) if zones else 0.0
        share = round(100 * thick / zoned, 1) if zoned > 0 else None
        if thick and share == 0:
            share = fmt_pct(100 * thick / zoned, 1, sign=False)
        row = [lith, ", ".join(z.zone_id for z in zones) or "-", thick, share, interval_thick, interval_share]
        for c in curves:
            if zones:
                data = view.values(c)[np.concatenate([z.indices for z in zones])]
                row.append(int(np.isfinite(data).sum()))
                row.extend(stats_of(c, data))
            else:
                row.extend(None for _ in range(1 + len(names[c][0])))
        values.extend(v for v in row[2:] if isinstance(v, (int, float)))
        rows.append(row)
    for b in S.bases(view)[-2:]:                              # the zones pooled, the whole interval where it differs
        if b.kind == "whole" and not S.outside(view):
            continue
        row = [b.label, "-", sig(zoned) if b.kind == "pooled" else None, 100.0 if b.kind == "pooled" else None,
               sig(view.gross) if b.kind == "whole" else None, 100.0 if b.kind == "whole" else None]
        for c in curves:
            data = view.values(c)[b.idx]
            row.append(int(np.isfinite(data).sum()))
            row.extend(stats_of(c, data))
        values.extend(v for v in row[2:] if isinstance(v, (int, float)))
        rows.append(row)
    cover = 100 * zoned / view.gross if view.gross > 0 else 0.0
    unlabelled = 100 * float(np.sum(labels == MISSING_LITHOLOGY)) / n_all if n_all else 0.0
    facts = [f"share of zoned: fraction of the zoned thickness {fmt(zoned)} {view.depth_unit} ({fmt_pct(cover, 1)} of the gross; the "
             f"rest is runs thinner than the zone minimum and transitions); a rock type's statistics are pooled over its "
             f"zone samples",
             f"share of interval: fraction of all {n_all} samples of the gross {fmt(view.gross)} {view.depth_unit}"
             + (f" ({fmt_pct(unlabelled, 1)} have no lithology-log label)" if unlabelled else "")]
    values += [sig(zoned), round(cover, 1), sig(view.gross)] + ([round(unlabelled, 1)] if unlabelled else [])
    away = S.outside_mask(view)
    if away.any():                       # the samples outside the zones, a labelled gap, never a rock-type row
        held = {}
        for lith in labels[away].tolist():
            held[lith] = held.get(lith, 0) + 1
        cells = []
        for lith, k in sorted(held.items(), key=lambda kv: -kv[1]):
            t = sig(view.gross * k / n_all)
            cells.append(f"{lith} {k} samples ({fmt(t)} {view.depth_unit}"
                         + ("; no zone of this rock type" if lith not in by_lith and lith != MISSING_LITHOLOGY else "") + ")")
            values += [k, t]
        facts.append(f"{S.outside_label(view)}: " + ", ".join(cells))
        values.append(int(away.sum()))
    facts += [f"{c}: {note}" for c in curves for note in [S.shape_note(view.values(c))] if note and not stats
              and names[c][0] != ["shares"]]
    facts += [f"{c}: {S.kind_note(S.curve_kind(view, c), S.code_labels(view, c))}" for c in curves
              if names[c][0] == ["shares"]]
    if missing:
        facts.append(_missing_text(view, missing))
    return {"title": f"By lithology, then the zones pooled and the whole interval: thickness, shares and statistics of "
                     f"{', '.join(curves)}",
            "columns": cols, "rows": rows, "values": values, "facts": facts}


def interval_stats(view: FormationView, curves: list[str], stats: list[str] = None,
                   scope: Literal["both", "interval", "zoned"] = "both", where: Optional[str] = None) -> dict:
    """Formation statistics with their sample basis: the lithology zones (the characterised rock) and the whole
    interval. The zoned basis comes first: thin runs and the transitions between zones mix two rock types, so sound
    practice leaves them out of formation statistics. The whole interval is always given alongside when the zones do
    not cover it all (scope "both" or "interval"); scope="zoned" gives the zones only."""
    (curves, missing), stats = _check_curves(view, curves), _check_stats(stats)
    n_all = int(view.mask.sum())
    zoned = view.zoned
    bases = {"interval": [("whole interval", np.ones(n_all, dtype=bool))], "zoned": [("lithology zones", zoned)]}
    partial = bool(view.zones) and not zoned.all()
    if scope == "zoned":
        picked = bases["zoned"]
    else:
        picked = (bases["zoned"] + bases["interval"]) if partial else bases["interval"]
    wmask, wtext = _where_mask(view, where)
    rows, values = [], []
    for c in curves:
        for label, sel in picked:
            data = view.values(c)[sel & wmask]
            n = int(np.isfinite(data).sum())
            row = [c, label, view.unit(c) or "-", n] + [sig(_stat(data, s_)) for s_ in stats]
            values.extend(row[4:])
            rows.append(row)
    facts = [f"lithology zones cover {fmt(view.zoned_thickness)} {view.depth_unit} of the {fmt(view.gross)} {view.depth_unit} interval; the zoned "
             "basis leaves out thin runs and transitions between zones"] if len(picked) > 1 else []
    if missing:
        facts.append(_missing_text(view, missing))
    return {"title": f"Formation statistics ({fmt_depth(view.top)}–{fmt_depth(view.base)} {view.depth_unit})" + (f", {wtext}" if wtext else ""),
            "columns": ["curve", "basis", "unit", "n"] + stats, "rows": rows, "values": values, "facts": facts}


# --- curves related by construction -------------------------------------------------------------

def construction(view: FormationView) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Derived curve -> the curves the step record says it was computed from (rules/curves.yaml construction), and a
    note per curve on what the record holds fixed (e.g. one SWIRR value for the well). A curve whose record states
    nothing is absent: no relation is assumed."""
    graph, notes = {}, {}
    for curve, spec in (view.reg.curves.get("construction") or {}).items():
        if spec.get("sxo_quicklook"):
            continue                       # route-dependent: only the SXO pair itself (construction_relation)
        inputs = recorded_inputs(view.prep.steps, spec)
        if not inputs:
            continue
        graph[curve] = [c for c in inputs if c != curve]
        params = (last_step(view.prep.steps, (spec.get("steps") or [""])[0]).get("parameters") or {})
        fixed = [name for name, key in (spec.get("constants") or {}).items()
                 if isinstance(params.get(key), (int, float)) and not isinstance(params.get(key), bool)]
        if fixed:
            notes[curve] = f"one {', '.join(fixed)} value for the well"
    from petroharness.record.card import curve_origin

    steps = getattr(getattr(view, "prep", None), "steps", None) or {}
    listed = any("outputs" in (rec or {}) for rec in steps.values())     # the record names what each step wrote
    for curve in view.reg.derived_order if listed else []:
        if curve not in graph and view.available(curve):     # no recorded step computed it: the supplied curve it repeats
            origin = curve_origin(view, curve)
            if origin and origin[0] == "copy":
                graph[curve] = [origin[1]]
                notes[curve] = "the same values (no model in the record)"
    return graph, notes


def construction_relation(view: FormationView, a: str, b: str) -> Optional[dict]:
    """How two curves are related by the workflow's own arithmetic, read from the step record: "derived" when one is
    computed from the other (or both from the same curve) with no other curve input, "partial" when one is among the
    other's inputs. None when the record shows no relation. {kind, derived, base, text, chain}."""
    for curve, spec in (view.reg.curves.get("construction") or {}).items():
        sources = spec.get("sxo_quicklook") or []
        if sources and {a, b} == {curve, *sources[:1]} and sxo_route(view) == "quicklook":
            base = sources[0]
            return {"kind": "derived", "derived": curve, "base": base, "chain": [curve],
                    "text": f"{curve} is the quicklook transform of {base} in this interval"}
    graph, notes = construction(view)

    def det(c, base, seen=frozenset()):
        if c == base:
            return True
        ins = graph.get(c)
        return bool(ins) and c not in seen and all(det(i, base, seen | {c}) for i in ins)

    def deps(c, seen=frozenset()):
        out = set()
        for i in graph.get(c, []):
            if i not in seen:
                out |= {i} | deps(i, seen | {c})
        return out

    def chain(tops, base):
        """The construction steps from the derived curve(s) down to base, in breadth-first order."""
        order, queue = [], list(tops)
        while queue:
            c = queue.pop(0)
            if c in graph and c != base and c not in order and det(c, base):
                order.append(c)
                queue.extend(graph[c])
        return order

    def describe(order):
        return "; ".join(f"{c} from {', '.join(graph[c])}" + (f" with {notes[c]}" if c in notes else "") for c in order)

    for derived, base in ((b, a), (a, b)):
        if derived != base and det(derived, base):
            order = chain([derived], base)
            if order == [derived] and graph[derived] == [base]:          # one step: say it once
                text = f"{derived} is computed from {base}" + (f" with {notes[derived]}" if derived in notes else "")
            else:
                text = f"{derived} is computed from {base} ({describe(order)})"
            return {"kind": "derived", "derived": derived, "base": base, "chain": order, "text": text}
    common = sorted((c for c in deps(a) & deps(b) if det(a, c) and det(b, c)), key=lambda c: -len(deps(c)))
    if common:
        base = common[0]
        order = chain([a, b], base)
        return {"kind": "derived", "derived": b, "base": base, "chain": order,
                "text": f"{a} and {b} are both computed from {base} ({describe(order)})"}
    for derived, other in ((b, a), (a, b)):
        if other in deps(derived):
            via, queue, parent = [], [derived], {derived: None}
            while queue:                                   # shortest path derived -> other
                c = queue.pop(0)
                for i in graph.get(c, []):
                    if i not in parent:
                        parent[i] = c
                        queue.append(i)
            node = parent.get(other)
            while node is not None and node != derived:
                via.insert(0, node)
                node = parent.get(node)
            return {"kind": "partial", "derived": derived, "base": other, "chain": [derived] + via,
                    "text": f"{derived} is computed partly from {other}" + (f" (through {', '.join(via)})" if via else "")
                            + f"; {derived} also has inputs besides {other}"}
    return None


def _zone_means(view: FormationView, curve: str) -> dict:
    return {z.zone_id: _stat(view.zone_values(z, curve), "mean") for z in view.zones}


def _ranks(x: np.ndarray) -> np.ndarray:
    """Ranks 1..n (ties share their average rank)."""
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    ranks[order] = np.arange(1, len(x) + 1)
    for v in np.unique(x):
        same = x == v
        if same.sum() > 1:
            ranks[same] = ranks[same].mean()
    return ranks


def _contrast(view: FormationView, curve: str, inputs: list[str]) -> tuple[list, list[str], list]:
    """Zones with higher vs lower zone-mean `curve` (top and bottom half by rank; the middle zone of an odd count is
    left out), with their thickness-weighted inputs and lithology mix. Rows, facts, values."""
    means = _zone_means(view, curve)
    zs = sorted((z for z in view.zones if np.isfinite(means[z.zone_id])), key=lambda z: -means[z.zone_id])
    if len(zs) < 2:
        return [], [f"{curve}: fewer than 2 zones have values; no zone contrast"], []
    half = len(zs) // 2
    inputs = [c for c in inputs if c != curve and view.available(c)]
    rows, values, parts = [], [], []
    for label, group in ((f"higher {curve}", zs[:half]), (f"lower {curve}", zs[-half:])):
        thick = sum(z.thickness for z in group)

        def wmean(c):
            ms = [(_stat(view.zone_values(z, c), "mean"), z.thickness) for z in group]
            ms = [(m, t) for m, t in ms if np.isfinite(m)]
            return sig(sum(m * t for m, t in ms) / sum(t for _, t in ms)) if ms else None

        lith: dict[str, float] = {}
        for z in group:
            lith[z.lithology] = lith.get(z.lithology, 0.0) + z.thickness
        mix = ", ".join(f"{l} {fmt_pct(100 * t / thick)}" for l, t in sorted(lith.items(), key=lambda kv: -kv[1])[:3])
        row = [label, ", ".join(z.zone_id for z in sorted(group, key=lambda z: z.top)), sig(thick), wmean(curve)]
        row += [wmean(c) for c in inputs] + [mix]
        rows.append(row)
        values += [v for v in row[2:-1] if v is not None] + [round(100 * t / thick) for t in lith.values()]
        parts.append(f"{label} zones ({row[1]}; {fmt(row[2])} {view.depth_unit}): " + ", ".join(
            f"{c} {fmt(v)}" for c, v in zip([curve] + inputs, row[3:-1]) if v is not None) + f"; {mix}")
    return rows, parts, values


def zone_contrast(view: FormationView, curve: str, inputs: Optional[list[str]] = None) -> dict:
    """What differs between the zones with higher and lower values of a curve: thickness-weighted shale volume,
    porosity (or the inputs given) and lithology mix. Evidence for what controls a property, where a correlation
    between a derived curve and its own inputs would only restate the workflow's arithmetic."""
    (curves, _), = [_check_curves(view, [curve])]
    c = curves[0]
    inputs = [str(i).upper() for i in (inputs or view.reg.curves.get("control_inputs", ["VCL", "PHIE"]))]
    rows, parts, values = _contrast(view, c, inputs)
    shown = [i for i in inputs if i != c and view.available(i)]
    facts = ["zones ranked by zone-mean " + c + "; the higher and lower halves (the middle zone of an odd count left "
             "out); values are thickness-weighted zone means; lithology as share of the group's thickness"] + parts
    for i in shown:                 # an input the curve is computed from: the contrast shows arithmetic for that input
        relation = construction_relation(view, c, i)
        if relation:
            facts.append(f"{'related' if relation['kind'] == 'derived' else 'partly related'} by construction: "
                         f"{relation['text']}")
    return {"title": f"Zone contrast: zones with higher vs lower {c}",
            "columns": ["group", "zones", f"thickness ({view.depth_unit})", f"{c}"] + shown + ["lithology"] if rows else [],
            "rows": rows, "facts": facts, "values": values}


def _within_zone(view: FormationView, cx: str, cy: str, zones) -> tuple[list[str], list, list[str], list]:
    """How cy moves with cx inside each of the given zones, over the zone's own samples (one rock type): the mean of cy
    in the lower, middle and upper third of cx, so the direction reads without a coefficient, over good-hole samples
    away from a model or tool limit. A zone with too few good-hole samples (mostly bad hole) is read over all its
    samples away from limits, with a caveat (still the logs we have). A zone without a lithology-log label is not known
    to be one rock type, and says so. Where either curve's p10-p90 inside the zone is narrower than one of its library
    classes, the order inside the zone is not informative and no thirds are given. The within-zone Spearman rank
    correlation is sample-level detail: returned apart (detail lines and coefficients), shown only when a coefficient is
    asked for. (facts, values, detail, coefficients)"""
    from petroharness.well.formation import MISSING_LITHOLOGY

    a, b = view.values(cx), view.values(cy)
    present = np.isfinite(a) & np.isfinite(b) & ~view.at_bound(cx) & ~view.at_bound(cy)
    usable = present & view.good_hole()
    facts, values, detail, coefficients = [], [], [], []
    if not zones:
        return ["within a zone: no lithology zone has both curves, so no within-zone relation"], values, detail, coefficients
    for z in zones:
        idx, caveat = z.indices[usable[z.indices]], ""
        if idx.size < 8:
            idx = z.indices[present[z.indices]]
            caveat = " - most samples flagged bad hole: relation over all samples, read with caution"
        if idx.size < 8:
            facts.append(f"within {z.zone_id} ({z.lithology}, {fmt_depth(z.top)}-{fmt_depth(z.base)} {view.depth_unit}): only "
                         f"{idx.size} samples with both curves away from limits - too few for a within-zone relation")
            values.append(int(idx.size))
            continue
        xa, ya = a[idx], b[idx]
        narrow = [r for r in (_narrow_range(view, c, d, [10, 90]) for c, d in ((cx, xa), (cy, ya))) if r]
        if narrow:
            facts.append(f"within {z.zone_id} ({z.lithology}, {fmt_depth(z.top)}-{fmt_depth(z.base)} {view.depth_unit}, n={idx.size}): "
                         + "; ".join(f"{c} p10-p90 {fmt(lo)}-{fmt(hi)}{u} is narrower than one of its classes ({w})"
                                     for c, lo, hi, u, w, _ in narrow)
                         + ", so the order inside the zone is not informative")
            values += [int(idx.size)] + [v for r in narrow for v in r[5]]
            continue
        rho = float(np.corrcoef(_ranks(xa), _ranks(ya))[0, 1]) if np.ptp(xa) > 0 and np.ptp(ya) > 0 else float("nan")
        cuts = np.quantile(xa, [1 / 3, 2 / 3])
        thirds = [ya[xa <= cuts[0]], ya[(xa > cuts[0]) & (xa <= cuts[1])], ya[xa > cuts[1]]]
        means = [float(np.mean(t)) if t.size else float("nan") for t in thirds]
        trend = (f"{cy} rises with {cx}; " if np.isfinite(rho) and rho >= 0.3 else
                 f"{cy} falls as {cx} rises; " if np.isfinite(rho) and rho <= -0.3 else "")
        basis = ("no lithology-log label, so the samples may mix rock types: read with caution"
                 if z.lithology == MISSING_LITHOLOGY else "one rock type, so the samples are not a mix of lithologies")
        facts.append(f"within {z.zone_id} ({z.lithology}, {fmt_depth(z.top)}-{fmt_depth(z.base)} {view.depth_unit}, n={idx.size}; "
                     f"{basis}): {trend}mean {cy} in the lower/middle/upper third of {cx}: "
                     + " / ".join(fmt(sig(m)) for m in means) + caveat)
        values += [int(idx.size)] + [sig(m) for m in means]
        if np.isfinite(rho):
            detail.append(f"{z.zone_id} Spearman {fmt(rho)} (n={idx.size})")
            coefficients.append((sig(rho), int(idx.size)))
    return facts, values, detail, coefficients


def correlation(view: FormationView, x: str, y: str, coefficient: bool = False) -> dict:
    """How two curves relate, as a petrophysicist reads it, in this order. (a) The class-level verdict: the class
    concordance of the two curves' library classes per zone against the expected relation (rules/relations.yaml:
    positive, inverse or requires; neutral without one), the class pairs with their rock types where the classes split,
    and the classes of the highest and lowest zone. (b) The zone order (zone means ranked, the direction over the zones
    with its pair counts and Spearman over the zone means) only where it is informative: both curves' zone means fall in
    two or more classes and span at least one class width, and the zones' p25-p75 ranges mostly separate; otherwise a
    line saying why it is not, with no direction. With fewer than 3 zones, the relation inside each zone (one rock
    type; _within_zone), except for a necessary condition (requires) or a pair related by construction. (c) Construction,
    read from the step record: a pair computed from one another gets its class agreement and this caveat, never a zone
    order (inside a class the formula's other terms can reorder it); and the physical mechanisms (rules/relations.yaml).
    (d) A sample coefficient only when asked (coefficient=True, set by rule expansion when the question or the spec's
    statistics name one): a note where it is not informative (fewer than 3 zones, a sample range inside one class,
    mixed rock types), then the Pearson r over zoned, good-hole samples away from a model or tool limit, with n."""
    (pair, _), = [_check_curves(view, [x, y])]
    if len(pair) < 2:
        raise EvidenceError(f"WHAT: need two curves with data, got {pair}. FIX: choose two curves from the card.")
    cx, cy = pair
    a, b = view.values(cx), view.values(cy)
    if (np.isfinite(a) & np.isfinite(b)).sum() < 3:
        raise EvidenceError("WHAT: fewer than 3 samples have both curves. FIX: choose curves that overlap.")
    mx, my = _zone_means(view, cx), _zone_means(view, cy)
    zs = [z for z in view.zones if np.isfinite(mx[z.zone_id]) and np.isfinite(my[z.zone_id])]
    facts, values, detail, wcoef, coefficients = [], [], [], [], []
    relation = construction_relation(view, cx, cy)
    derived = bool(relation) and relation["kind"] == "derived"
    expected = None if derived else expected_relation(view, cx, cy)
    requires = (expected or {}).get("direction") == "requires"
    n = len(zs)
    vx, vy = np.array([mx[z.zone_id] for z in zs]), np.array([my[z.zone_id] for z in zs])

    # (a) the class-level verdict
    concordance = _class_concordance(view, cx, cy, expected, mx)
    if concordance:
        facts += concordance[0]
        values += concordance[1]

    # (b) the zone order, only where it is informative (never for a pair computed from one another)
    rho = float("nan")
    if n >= 3 and not derived:
        pcts = view.reg.relation_limit("zone_range_percentiles", [25, 75])
        pairs = n * (n - 1) // 2
        sep = {c: _separated_zone_pairs(view, zs, c, pcts) for c in (cx, cy)}
        reasons, rvalues = [], []
        for c in (cx, cy):
            why, wvalues = _zone_order_reasons(view, c, zs, sep[c], pairs, pcts)
            reasons += why
            rvalues += wvalues
        if reasons:
            sources = [w for w, has in (("the classes", bool(concordance)), ("the mechanism", bool(_mechanisms(view, cx, cy))))
                       if has]
            facts.append("zone order not informative: " + "; ".join(reasons) + ", so no zone-level direction is given"
                         + (f"; the relation reads from {' and '.join(sources)}" if sources else ""))
            values += rvalues
        else:
            rx, ry = _ranks(-vx), _ranks(-vy)                                    # rank 1 = highest zone mean
            order = list(np.argsort(rx, kind="mergesort"))
            most = view.reg.limit("correlation_max_ranked_zones", 12)
            shown = order if len(order) <= most else order[: most // 2] + order[-(most // 2):]
            entry = lambda i: f"{zs[i].zone_id} {fmt(vx[i])}/{fmt(vy[i])} ({fmt(ry[i])})"
            listing = "; ".join(entry(i) for i in shown) if shown is order else (
                "; ".join(entry(i) for i in shown[: most // 2]) + f"; ... {len(order) - len(shown)} zones ...; "
                + "; ".join(entry(i) for i in shown[most // 2:]))
            rho = float(np.corrcoef(_ranks(vx), _ranks(vy))[0, 1]) if np.ptp(vx) > 0 and np.ptp(vy) > 0 else 0.0
            sx, sy = np.sign(vx[:, None] - vx[None, :]), np.sign(vy[:, None] - vy[None, :])
            iu = np.triu_indices(n, 1)
            same, opposite = int(np.sum(sx[iu] * sy[iu] > 0)), int(np.sum(sx[iu] * sy[iu] < 0))
            counted = same + opposite
            word = "higher" if rho >= 0 else "lower"
            agree = same if rho >= 0 else opposite
            phrase = next((w for t, w in view.reg.relation_limit("direction_words", [[0.5, "generally have"],
                                                                                     [0.2, "weakly tend to have"]])
                           if abs(rho) >= t), None)
            if phrase:
                direction = (f"higher-{cx} zones {phrase} {word} {cy}: in {agree} of {counted} zone pairs the zone "
                             f"with higher {cx} has {word} {cy}")
            else:          # weak: say how the pairs split, never "no relationship"
                direction = (f"{cy} follows the {cx} ranking only weakly: in {same} of {counted} zone pairs the zone "
                             f"with higher {cx} has higher {cy}, in {opposite} lower")
            facts.append(f"zone means ranked by {cx}, highest first ({cx}/{cy}, {cy} rank of {n} in brackets): {listing}")
            facts.append(f"zone p{pcts[0]}-p{pcts[1]} ranges separate {cx} in {sep[cx]} and {cy} in {sep[cy]} of "
                         f"{pairs} zone pairs (the rest overlap)")
            facts.append(f"zone level ({n} zones, zone means): {direction}; Spearman rank correlation over the zone "
                         f"means {fmt(rho)}")
            values += [v for i in shown for v in (sig(vx[i]), sig(vy[i]), sig(ry[i]))]
            values += [sep[cx], sep[cy], pairs, sig(rho), same, opposite, counted, n]
    elif n < 3:
        inside = not (requires or derived)
        facts.append(f"{n} zone(s) have both curves: the relation is not resolvable at zone level; it reads from the "
                     "classes and the construction or mechanism" + (", and the relation inside the zone below" if inside else ""))
        # Few zones is not "no relation": inside one rock type the samples are not a mix of lithologies, so their
        # relation is meaningful. Not for a
        # necessary condition (no order is implied) or a computed pair (the formula's other terms can reorder it).
        if inside:
            within, wvalues, detail, wcoef = _within_zone(view, cx, cy, zs)
            facts += within
            values += wvalues

    # (c) construction (step record) and mechanism (registry)
    if relation:
        kind = "related by construction" if derived else "partly related by construction"
        facts.append(f"{kind}: {relation['text']}; not independent evidence: their co-variation follows from how the "
                     "workflow computed them and does not show what controls either curve"
                     + ("; their class agreement above is arithmetic too, and no zone order is given (inside a class "
                        "the formula's other terms can reorder it)" if derived else ""))
        for c in relation["chain"]:
            spec = (view.reg.curves.get("construction") or {}).get(c, {})
            params = last_step(view.prep.steps, (spec.get("steps") or [""])[0]).get("parameters") or {}
            clip, data = params.get(spec.get("clip", "")), view.values(c)
            if not isinstance(clip, (int, float)) or isinstance(clip, bool) or data is None:
                continue
            at = np.isfinite(data) & (data >= float(clip) * (1 - 1e-9))
            if at.any():
                facts.append(f"{c} is held at its recorded clip ({fmt(float(clip))} {view.unit(c)}) in {int(at.sum())} "
                             f"samples of this interval")
                values += [float(clip), int(at.sum())]
        if derived and n >= 3:
            # what differs between higher and lower zones of the computed curve, only where its zones span classes
            target = relation["derived"] if relation["derived"] in (cx, cy) else cy
            pcts = view.reg.relation_limit("zone_range_percentiles", [25, 75])
            spans = not _zone_order_reasons(view, target, zs, _separated_zone_pairs(view, zs, target, pcts),
                                            n * (n - 1) // 2, pcts)[0]
            if spans:
                inputs = list(dict.fromkeys(view.reg.curves.get("control_inputs", ["VCL", "PHIE"]) + [relation["base"]]))
                _, parts, cvalues = _contrast(view, target, inputs)
                facts.append("inputs contrast (what differs between zones, for a question about controls): "
                             + " | ".join(parts))
                values += cvalues
    facts += _mechanism_facts(view, cx, cy, rho)

    # (d) a sample coefficient only when asked for, last
    if coefficient:
        valid = np.isfinite(a) & np.isfinite(b)
        zoned, good = view.zoned, view.good_hole()
        used = valid & zoned
        sample_line, sample_values = None, []
        if n >= 3:
            # Sample r: zoned, good-hole samples away from a limit of either curve or of a derived curve they come from.
            limited = view.at_bound(cx) | view.at_bound(cy)
            for c in set((relation or {}).get("chain", [])) | {cx, cy}:
                if c in (view.reg.curves.get("construction") or {}) and c not in (cx, cy):
                    limited |= view.at_bound(c)
            unzoned, bad = valid & ~zoned, valid & zoned & ~good
            clipped = valid & zoned & good & limited
            used = valid & zoned & good & ~limited
            k = int(used.sum())
            left = [f"{int(m.sum())} {what}" for m, what in ((unzoned, "outside the zones"), (bad, "bad hole"),
                                                              (clipped, "at a model or tool limit")) if m.any()]
            if k >= 3 and np.ptp(a[used]) > 0 and np.ptp(b[used]) > 0:
                r = float(np.corrcoef(a[used], b[used])[0, 1])
                sample_line = (f"sample level (supporting detail only): Pearson r = {fmt(r)} over {k} zoned good-hole "
                               "samples" + (f" (left out: {', '.join(left)})" if left else ""))
                sample_values = [sig(r), k]
                coefficients.append((sig(r), k))
            else:
                sample_line = f"sample level: too few usable samples ({k}) for a correlation coefficient"
                sample_values = [k]
            sample_values += [int(m.sum()) for m in (unzoned, bad, clipped)]
        reasons, rvalues = _range_restriction(view, cx, cy, a[used], b[used], n)
        if reasons:
            facts.append("a sample coefficient is not informative here: " + "; ".join(reasons))
            values += rvalues
        if sample_line:
            facts.append(sample_line)
            values += sample_values
        if detail:
            facts.append(f"sample level inside the zone (supporting detail only): {cy} against {cx}: " + "; ".join(detail))
            values += [c for c, _ in wcoef]
            coefficients += wcoef
    facts.append(NOT_EXPORTED)
    return {"title": f"Relation of {cx} and {cy} (class level first; zone order only where informative)",
            "facts": facts, "values": values, "coefficients": coefficients}


# --- relation helpers (rules/relations.yaml) -----------------------------------------------------------------------

def _separated_zone_pairs(view: FormationView, zones, curve: str, pcts) -> int:
    """Zone pairs whose percentile ranges of the curve (e.g. p25-p75 of each zone's samples) do not overlap."""
    spans = []
    for z in zones:
        v = view.zone_values(z, curve)
        v = v[np.isfinite(v)]
        spans.append(tuple(np.percentile(v, pcts)) if v.size else (np.nan, np.nan))
    return sum(1 for i in range(len(spans)) for j in range(i + 1, len(spans))
               if spans[i][1] < spans[j][0] or spans[j][1] < spans[i][0])


def _bands(entry: dict, view: Optional[FormationView] = None):
    """The petrophys Bands a rules/relations.yaml class entry names ('Analyzer.NAME', e.g.
    PermeabilityAnalysis.DISTRIBUTION_BANDS): the analyzer's own classes, edges and edge sides, from the table set the
    view's policy classifies with (analyzers.class_tables, as make_analyzer); without one, the library's default set."""
    import inspect
    from petrophys.evaluation import diagnostics

    analyzer, name = entry["bands"].split(".")
    klass = getattr(diagnostics, analyzer)
    tables = (view.policy.get("analyzers") or {}).get("class_tables") if view is not None else None
    accepts = "class_tables" in inspect.signature(klass.__init__).parameters
    return diagnostics.bands_of(klass(class_tables=tables) if tables and accepts else klass(), name)


def _class_width(entry: dict, value: float, view: Optional[FormationView] = None) -> tuple[float, bool]:
    """(width of the class holding value, on the class scale: decades for a log-scaled curve; an open class takes its
    neighbour's width, log-scaled). The class of a value on an edge is the library's (Bands.label_of)."""
    bands = _bands(entry, view)
    log = entry.get("scale") == "log"
    t = np.log10 if log else (lambda q: q)
    widths = np.diff(t(np.asarray(bands.edges, dtype=float)))
    label = bands.label_of(value) if (value > 0 or not log) else bands.labels[0]
    k = bands.labels.index(label) if label in bands.labels else 0
    return float(widths[min(max(k - 1, 0), widths.size - 1)]), log


def _narrow_range(view: FormationView, curve: str, data: np.ndarray, pcts) -> Optional[tuple]:
    """(curve, low, high, unit, width text, values) when the curve's percentile range of data is narrower than one of
    its own library classes (rules/relations.yaml classes); None otherwise or without class thresholds."""
    source, entry = _class_entry(view, curve)
    if entry is None or source != curve or len(_bands(entry, view).edges) < 2:
        return None
    log = entry.get("scale") == "log"
    v = np.asarray(data, dtype=float)
    v = v[np.isfinite(v)]
    v = v[v > 0] if log else v
    if v.size < 2:
        return None
    lo, hi = (float(q) for q in np.percentile(v, pcts))
    width, _ = _class_width(entry, float(np.median(v)), view)
    t = np.log10 if log else (lambda q: q)
    if t(hi) - t(lo) >= width:
        return None
    unit = f" {view.unit(curve)}" if view.unit(curve) else ""
    return curve, lo, hi, unit, (f"{fmt(width)} decade" if log else f"{fmt(width)}{unit}"), [sig(lo), sig(hi), sig(width)]


def _zone_order_reasons(view: FormationView, curve: str, zones, separated: int, pairs: int, pcts) -> tuple[list[str], list]:
    """Why the zone order of a curve is not informative: its zone means fall in one of its library classes or span
    less than one class width, or its zones' p25-p75 ranges mostly overlap (relations.yaml limits min_separated_share).
    Empty when it is informative."""
    reasons, values = [], []
    source, entry = _class_entry(view, curve)
    if entry is not None and source == curve:
        _, labels = zone_labels(view, curve)
        classes = sorted({labels[z.zone_id] for z in zones if z.zone_id in labels})
        if len(classes) == 1:
            reasons.append(f"the zones fall in one class of {curve} ({classes[0]})")
        else:
            means = [_stat(view.zone_values(z, curve), "mean") for z in zones]
            narrow = _narrow_range(view, curve, np.asarray(means), [0, 100])
            if narrow:
                _, lo, hi, unit, width, nums = narrow
                reasons.append(f"the zone means of {curve} span {fmt(lo)}-{fmt(hi)}{unit}, less than one of its classes "
                               f"({width})")
                values += nums
    share = float(view.reg.relation_limit("min_separated_share", 0.5))
    if pairs and separated < share * pairs:
        reasons.append(f"the zone p{pcts[0]}-p{pcts[1]} ranges of {curve} overlap in {pairs - separated} of {pairs} "
                       "zone pairs")
        values += [pairs - separated, pairs]
    return reasons, values


def _zone_list(view: FormationView, ids) -> str:
    """Zone ids in depth order, consecutive zones joined (Z1-Z4, Z7)."""
    pos = {z.zone_id: i for i, z in enumerate(view.zones)}
    runs: list[list[int]] = []
    for i in sorted(pos[z] for z in ids):
        if runs and i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    zs = view.zones
    return ", ".join(zs[a].zone_id if a == b else f"{zs[a].zone_id}-{zs[b].zone_id}" for a, b in runs)


def _class_entry(view: FormationView, curve: str) -> tuple[Optional[str], Optional[dict]]:
    """(the curve whose classes grade this curve, its rules/relations.yaml class entry), or (None, None)."""
    rel = view.reg.relations
    source = (rel.get("class_from") or {}).get(curve, curve)
    entry = (rel.get("classes") or {}).get(source)
    return (source, entry) if entry and view.available(source) else (None, None)


def _library_grades(view: FormationView, entry: dict, source: str) -> bool:
    """Whether the library section grades this very curve here: it is the first of the section's inputs present (a
    section that forms its quantity itself, reads empty, grades its own ratio, not the workflow's curve)."""
    present = [c for c in entry.get("reads", []) if view.available(c)]
    return bool(present) and present[0] == source


def zone_labels(view: FormationView, curve: str) -> tuple[Optional[str], dict[str, str]]:
    """One class per zone for a curve (rules/relations.yaml classes): the library's own zone class (zone_classes_raw,
    the zone_classes machinery) where its section grades this very curve; elsewhere, and for zones it leaves
    unclassed, the section's petrophys Bands applied to the curve's zone mean (Bands.label_of: the library's edges and
    edge sides). (the graded curve, {zone_id: label}); _band_basis says when the classes are the bands only."""
    source, entry = _class_entry(view, curve)
    if entry is None:
        return None, {}
    bands = _bands(entry, view)
    library = (zone_classes_raw(view, entry["topic"])["classes"].get(entry["section"], {})
               if _library_grades(view, entry, source) else {})
    labels = {}
    for z in view.zones:
        label = library.get(z.zone_id)
        if label not in bands.labels:
            label = bands.label_of(_stat(view.zone_values(z, source), "mean"))
        if label:
            labels[z.zone_id] = label
    return source, labels


def _band_basis(view: FormationView, curve: str) -> Optional[str]:
    """How a curve's classes were formed when its section does not grade it: in the section's bands, and what the
    section grades instead. None when the classes are the section's own."""
    source, entry = _class_entry(view, curve)
    if entry is None or _library_grades(view, entry, source):
        return None
    reads = entry.get("reads", [])
    present = [c for c in reads if view.available(c)]
    why = ("the section forms its own ratio" if not reads else f"the section grades {present[0]}" if present
           else "the section has none of its inputs here")
    return f"{source} in the {entry['section']} bands ({why})"


def _mechanisms(view: FormationView, cx: str, cy: str) -> list[dict]:
    """The rules/relations.yaml mechanisms that match the pair (one curve in each group)."""
    out = []
    for m in view.reg.relations.get("mechanisms") or []:
        g1, g2 = (set(g) for g in m["between"])
        if cx != cy and ((cx in g1 and cy in g2) or (cx in g2 and cy in g1)):
            out.append(m)
    return out


def expected_relation(view: FormationView, cx: str, cy: str) -> Optional[dict]:
    """The expected relation of the pair from the first matching mechanism that states one: {direction: positive or
    inverse}, or for a necessary condition {direction: requires, dependent, required, words, caveat} when the pair is
    one of the mechanism's dependent and required curves (other pairs of that mechanism get none)."""
    for m in _mechanisms(view, cx, cy):
        direction = m.get("direction")
        if direction == "requires":
            spec = m.get("requires") or {}
            dep, req = set(spec.get("dependent", [])), set(spec.get("required", []))
            pair = (cx, cy) if cx in dep and cy in req else (cy, cx) if cy in dep and cx in req else None
            if pair:
                return {"direction": direction, "dependent": pair[0], "required": pair[1],
                        "words": spec.get("words") or {}, "caveat": spec.get("caveat", "")}
        elif direction:
            return {"direction": direction}
    return None



def _class_concordance(view: FormationView, cx: str, cy: str, expected: Optional[dict] = None,
                       means_x: Optional[dict] = None) -> Optional[tuple[list[str], list]]:
    """The class-level verdict: the shares of the classed zone thickness (classes counted high: rules/relations.yaml
    classes) read against the expected relation (expected_relation): consistent with it or against it, so zones that
    follow an inverse relation are not called discordant; for a necessary condition (requires) only dependent-high
    zones with a low required curve are against it; without one, neutrally as both high, both low and discordant.
    Then the class pairs per zone, with their rock types where the classes split, and the classes of the zones with the
    highest and lowest cx."""
    direction = (expected or {}).get("direction")
    (sx, lx), (sy, ly) = zone_labels(view, cx), zone_labels(view, cy)
    if not lx or not ly or sx == sy:
        return None
    both = [zid for zid in lx if zid in ly]
    if not both:
        return None
    classes = view.reg.relations["classes"]
    ex, ey = classes[sx], classes[sy]
    thick = {z.zone_id: z.thickness for z in view.zones}
    total = sum(thick[z] for z in both) or 1.0
    groups: dict[tuple[str, str], list[str]] = {}
    for zid in both:
        groups.setdefault((lx[zid], ly[zid]), []).append(zid)
    graded = [f"{c} graded by {s}" for c, s in ((cx, sx), (cy, sy)) if c != s]
    graded += [b for b in dict.fromkeys(_band_basis(view, c) for c in (cx, cy)) if b]       # classes from the bands only
    parts, pair_values = [], []
    ranked = sorted(groups.items(), key=lambda kv: -sum(thick[z] for z in kv[1]))
    most = int(view.reg.relation_limit("max_class_pairs", 4))
    lith = {z.zone_id: z.lithology for z in view.zones}
    split = len(groups) > 1 and len({lith[z] for z in both}) > 1       # the rock-type contrast between the classes

    def rocks(ids):
        mix: dict[str, float] = {}
        for z in ids:
            mix[lith[z]] = mix.get(lith[z], 0.0) + thick[z]
        size = sum(mix.values()) or 1.0
        top = sorted(mix.items(), key=lambda kv: -kv[1])[:3]
        pair_values.extend(round(100 * m / size) for _, m in top)
        return "; " + ", ".join(f"{l} {fmt_pct(100 * m / size)}" for l, m in top)

    for (gx, gy), ids in ranked[:most]:
        m = sum(thick[z] for z in ids)
        pair_values.append(sig(m))
        parts.append(f"{gx} with {gy}: {_zone_list(view, ids)} ({fmt(m)} {view.depth_unit}{rocks(ids) if split else ''})")
    if len(ranked) > most:              # the thinnest combinations, summed (the pack budget is shared)
        rest = sum(thick[z] for _, ids in ranked[most:] for z in ids)
        parts.append(f"{len(ranked) - most} other class pairs ({fmt(rest)} {view.depth_unit})")
        pair_values.append(sig(rest))
    classes_line = (f"library classes of the zone means ({cx} with {cy}" + "".join(f"; {g}" for g in graded) + "): "
                    + "; ".join(parts))
    ends = sorted((z for z in both if means_x and np.isfinite(means_x.get(z, np.nan))), key=lambda z: means_x[z])
    if len(ends) >= 2:
        unit = f" {view.unit(cx)}" if view.unit(cx) else ""
        classes_line += "".join(f"; {end} {cx}: {z} ({fmt(means_x[z])}{unit}) in {lx[z]} with {ly[z]}"
                                for end, z in (("highest", ends[-1]), ("lowest", ends[0])))
        pair_values += [sig(means_x[ends[-1]]), sig(means_x[ends[0]])]
    facts, values = [], []
    hx, hy = set(ex.get("high", [])), set(ey.get("high", []))
    cells: dict[str, list[str]] = {"hh": [], "ll": [], "hl": [], "lh": []}
    for zid in both:
        cells[("h" if lx[zid] in hx else "l") + ("h" if ly[zid] in hy else "l")].append(zid)
    m = {k: sum(thick[z] for z in ids) for k, ids in cells.items()}
    m["disc"] = m["hl"] + m["lh"]
    word = lambda e, k: (e.get("names") or {}).get("high" if k == "h" else "low", "high" if k == "h" else "low")
    share = lambda k: fmt_pct(100 * m[k] / total)
    head = f"class concordance by classed zone thickness (high = {cx} {word(ex, 'h')}, {cy} {word(ey, 'h')}): "
    if direction == "requires":
        facts.append(head + _requirement_text(view, expected, cx, cells, thick, total, values))
        return facts + [classes_line], values + pair_values
    if direction in ("positive", "inverse"):
        follow = ("hh", "ll") if direction == "positive" else ("hl", "lh")
        ids = {"with": [z for k in follow for z in cells[k]], "against": [z for k in cells if k not in follow for z in cells[k]]}
        frac = {k: sum(thick[z] for z in v) / total for k, v in ids.items()}
        zones = lambda k: f" ({_zone_list(view, ids[k])})" if ids[k] else ""
        against = "both high or both low" if direction == "inverse" else "one high, the other low"
        facts.append(head + f"consistent with the expected {direction} relation {fmt_pct(100 * frac['with'])}"
                     + zones("with") + f"; against it ({against}) {fmt_pct(100 * frac['against'])}" + zones("against"))
        values += [round(100 * frac["with"]), round(100 * frac["against"])]
        return facts + [classes_line], values + pair_values
    disc = [f"{cx} {'high' if k[0] == 'h' else 'low'} with {cy} {'high' if k[1] == 'h' else 'low'} in "
            f"{_zone_list(view, cells[k])}" for k in ("hl", "lh") if cells[k]]
    facts.append(head + f"both high {share('hh')}, both low {share('ll')}, discordant {share('disc')}"
                 + (f" ({'; '.join(disc)})" if disc else ""))
    values += [round(100 * m[k] / total) for k in ("hh", "ll", "disc")]
    return facts + [classes_line], values + pair_values


def _requirement_text(view: FormationView, expected: dict, cx: str, cells: dict, thick: dict, total: float,
                      values: list) -> str:
    """The concordance of a necessary condition: of the dependent-high thickness, how much has the required curve high
    (consistent) or low (against it); and the required-high zones with a low dependent, which do not contradict it.
    Appends the percentages shown to values."""
    dep, req, w = expected["dependent"], expected["required"], expected["words"]
    first = dep == cx                           # cell keys are (cx, cy): put them as (dependent, required)
    cell = lambda d, r: cells[(d + r) if first else (r + d)]
    hh, hl, lh = cell("h", "h"), cell("h", "l"), cell("l", "h")
    size = lambda ids: sum(thick[z] for z in ids)
    zones = lambda ids: f" ({_zone_list(view, ids)})" if ids else ""
    dh, dl = w.get("dependent_high", f"{dep} high"), w.get("dependent_low", f"{dep} low")
    rh, rl = w.get("required_high", f"{req} high"), w.get("required_low", f"{req} low")
    base = size(hh) + size(hl)
    if base > 0:
        tested = (f"{dh} zones are {rh} in {fmt_pct(100 * size(hh) / base)} of the {dh} thickness{zones(hh)}; {dh} but "
                  f"{rl} (against it): {fmt_pct(100 * size(hl) / base)}{zones(hl)}")
        values += [round(100 * size(hh) / base), round(100 * size(hl) / base)]
    else:
        tested = f"no zone is {dh}, so the requirement is not tested"
    other = (f"; {rh} but {dl}: {fmt_pct(100 * size(lh) / total)} of the classed thickness{zones(lh)}, which does not "
             f"contradict it" + (f" ({expected['caveat']})" if expected.get("caveat") else ""))
    values.append(round(100 * size(lh) / total))
    return f"consistent with {dep} requiring {req}: {tested}{other}"


def _mechanism_facts(view: FormationView, cx: str, cy: str, rho: float) -> list[str]:
    """Physical mechanisms for the pair (rules/relations.yaml mechanisms), with whether the zone-level direction
    agrees where the registry gives one."""
    facts = []
    words = view.reg.relation_limit("direction_words", [[0.5, ""], [0.2, ""]])
    weak = min(t for t, _ in words) if words else 0.0
    for m in _mechanisms(view, cx, cy):
        text = f"mechanism: {m['fact']}"
        expected = m.get("direction")
        if expected in ("positive", "inverse") and np.isfinite(rho):        # requires: no zone-level direction
            if abs(rho) < weak:
                text += f"; expected {expected} at zone level, and the zone ranking is too weak to test it"
            else:
                agrees = (rho > 0) == (expected == "positive")
                text += f"; expected {expected} at zone level, and the zone ranking {'agrees' if agrees else 'runs against it'}"
        facts.append(text)
    return facts


def _range_restriction(view: FormationView, cx: str, cy: str, a: np.ndarray, b: np.ndarray,
                       n: int) -> tuple[list[str], list]:
    """Reasons a sample coefficient is not informative here: fewer than 3 zones, a sample range (p10-p90 of the samples
    the coefficient would use) inside one class width of a curve's library classes, or samples pooled over several
    rock types."""
    reasons, values = [], []
    if n < 3:
        reasons.append(f"only {n} zone(s) have both curves, so a coefficient describes the spread inside a zone, not a "
                       "change between zones")
    pcts = view.reg.relation_limit("sample_range_percentiles", [10, 90])
    for c, data in ((cx, a), (cy, b)):
        narrow = _narrow_range(view, c, data, pcts)
        if narrow:
            _, lo, hi, unit, width, nums = narrow
            reasons.append(f"{c} p{pcts[0]}-p{pcts[1]} {fmt(lo)}-{fmt(hi)}{unit} is narrower than one of its classes ({width})")
            values += nums
    share_min = float(view.reg.relation_limit("rock_type_min_share", 0.1))
    thick: dict[str, float] = {}
    for z in view.zones:
        thick[z.lithology] = thick.get(z.lithology, 0.0) + z.thickness
    total = sum(thick.values())
    mixed = [(l, m / total) for l, m in sorted(thick.items(), key=lambda kv: -kv[1]) if total > 0 and m / total >= share_min]
    if len(mixed) >= 2:
        reasons.append(f"{len(mixed)} rock types pooled (" + ", ".join(f"{l} {fmt_pct(100 * s)}" for l, s in mixed)
                       + " of the zoned thickness)")
        values += [round(100 * s) for _, s in mixed]
    return reasons, values


def threshold_exceedance(view: FormationView, curve: str, threshold: Optional[float] = None,
                         absolute: Optional[bool] = None, op: str = ">") -> dict:
    """The share of samples beyond a threshold in each zone (with whether the zone's mean is beyond it), over the zones
    pooled and over the whole interval; the threshold given, or the workflow policy's QC level for the curve (said so)."""
    curve = curve.upper()
    if isinstance(absolute, (int, float)) and not isinstance(absolute, bool):
        threshold, absolute = (float(absolute) if threshold is None else threshold), True   # 'absolute': 0.15 means |curve| > 0.15
    qc = view.policy.get("qc_thresholds", {}).get(curve, {})
    given = threshold is not None
    threshold = qc.get("threshold") if threshold is None else threshold
    absolute = qc.get("absolute", False) if absolute is None else absolute
    if threshold is None:
        raise EvidenceError(f"WHAT: no threshold given for {curve}, and the workflow policy sets none for it. "
                            "FIX: pass threshold=<value>.")
    data = view.values(curve)
    if data is None or not np.isfinite(data).any():
        raise EvidenceError(f"WHAT: {curve} has no data here. FIX: use a curve listed on the formation card.")
    x = np.abs(data) if absolute else data
    ops = {">": np.greater, ">=": np.greater_equal, "<": np.less, "<=": np.less_equal}
    if op not in ops:
        raise EvidenceError(f"WHAT: unknown operator {op!r}. FIX: use one of {list(ops)}.")
    with np.errstate(invalid="ignore"):
        hit = ops[op](x, threshold)
    shown = f"{'|' + curve + '|' if absolute else curve}"
    label = f"{shown} {op} {threshold}"
    source = S.threshold_source(given, f"the policy's QC level for {curve} (qc_thresholds)")
    rows, values = [], []
    fin = np.isfinite(x)
    for z in view.zones:
        zx, zf = hit[z.indices], fin[z.indices]
        frac = float(np.mean(zx[zf])) if zf.any() else float("nan")
        m = float(np.mean(x[z.indices][zf])) if zf.any() else float("nan")
        by_mean = ("yes" if ops[op](m, threshold) else "no") if np.isfinite(m) else "-"
        k = int(zx[zf].sum())
        rows.append([z.zone_id, z.lithology, f"{fmt_depth(z.top)}–{fmt_depth(z.base)}",
                     f"{k} of {int(zf.sum())}" if zf.any() else None,
                     sig(100 * frac) if np.isfinite(frac) else None, sig(m) if np.isfinite(m) else None, by_mean])
        values += [v for v in ((k, int(zf.sum())) if zf.any() else ()) + (sig(100 * frac) if np.isfinite(frac) else None,
                                                                            sig(m) if np.isfinite(m) else None)
                   if v is not None]
    facts = [f"threshold {label} ({source})"]
    for b in S.bases(view)[-2:]:                          # the zones pooled, the whole interval
        sel = fin[b.idx]
        if not sel.any():
            facts.append(f"{b.label}: no {curve} values")
            continue
        total, peak = float(np.mean(hit[b.idx][sel])), float(np.nanmax(x[b.idx]))
        k = int(hit[b.idx][sel].sum())
        runs = _runs(view.depth[b.idx], hit[b.idx].astype(float), view.step)
        facts.append(f"{b.label}: {S.count_share(k, int(sel.sum()))}; {len(runs)} contiguous runs; "
                     f"max {shown} = {fmt(peak)}")
        values += [k, round(100 * total, 1), sig(peak), int(sel.sum()), S.outside(view)]
    return {"title": f"Threshold exceedance {label}: each zone (% of its samples, and its mean), the zones pooled, the "
                     "whole interval",
            "columns": ["zone", "lithology", f"depth ({view.depth_unit})", "samples beyond", "% samples", f"mean {shown}",
                        "mean beyond"], "rows": rows, "facts": facts, "values": [v for v in values if v is not None]}


def zone_relation(view: FormationView, curves: list[str]) -> dict:
    """Per-zone ordering of curve means, e.g. RSHA >= RMED >= RDEP (descending in the given order)."""
    curves, missing = _check_curves(view, curves)
    if len(curves) < 2:
        raise EvidenceError("WHAT: need at least two curves with data. FIX: pass curves in the order to test.")
    rows, values, holds, reverse = [], [], 0, 0
    for z in view.zones:
        means = [_stat(view.zone_values(z, c), "mean") for c in curves]
        ok = all(np.isfinite(means)) and all(means[i] >= means[i + 1] for i in range(len(means) - 1))
        holds += ok
        reverse += all(np.isfinite(means)) and all(means[i] <= means[i + 1] for i in range(len(means) - 1))
        rows.append([z.zone_id, z.lithology, f"{fmt_depth(z.top)}–{fmt_depth(z.base)}"] + [sig(m) for m in means] + ["yes" if ok else "no"])
        values += [sig(m) for m in means if np.isfinite(m)]
    rel = " >= ".join(curves)
    # The test is "decreasing in the given order"; the reverse order is stated too, so a planner that lists the curves
    # shallow-to-deep cannot turn "the deep curve reads highest" into "the expected order does not hold".
    facts = [f"{rel} holds in {holds} of {len(view.zones)} zones (zone means)",
             f"the reverse order {' >= '.join(reversed(curves))} holds in {reverse} of {len(view.zones)} zones (zone means)"]
    if missing:
        facts.append(_missing_text(view, missing))
    return {"title": f"Zone relation {rel}", "columns": ["zone", "lithology", f"depth ({view.depth_unit})"] + [f"mean {c}" for c in curves] + ["holds"],
            "rows": rows, "facts": facts, "values": values}


ORDER_RELATIONS = ("decreasing", "increasing", "between")


def _invasion_expectation(view: FormationView, curves: list[str], means: np.ndarray) -> Optional[dict]:
    """The order of the shallowest and the deepest resistivity curve that invasion physics expects in each zone
    (petrophys interpretation.electrical.invasion: mud_regime from Rmf/Rw, expected_resistivity_order for the zone's
    fluid, by zone-mean SW against the policy SW cutoff), and whether the zone means (curves by zones) match it. None
    when the curves are not all resistivity readings of known depth of investigation or there are no zones. Which
    workflow curves are Rmf and Rw, and which Rw routes are assumed: rules/curves.yaml invasion_profile."""
    from petrophys.interpretation.electrical.invasion import (EXPECTED_ORDER, MUD_REGIMES, expected_resistivity_order,
                                                               mud_regime, shallowest_and_deepest)

    inv = view.reg.curves.get("invasion_profile") or {}
    pair = shallowest_and_deepest(curves) if view.zones else None
    if pair is None:
        return None
    shallow, deep = pair
    medians = {}
    for key in ("rmf_curve", "rw_curve"):
        x = view.values(inv[key])
        x = x[np.isfinite(x) & (x > 0)] if x is not None else np.array([])
        medians[inv[key]] = sig(float(np.median(x))) if x.size else None
    absent = [name for name, v in medians.items() if v is None]
    if absent:
        return {"facts": [f"invasion profile expected from Rmf and Rw: not assessed ({' and '.join(absent)} not "
                          "available in this interval)"], "columns": [], "cells": None, "values": []}
    prep = getattr(view, "prep", None)
    route = (last_step(prep.steps, "rw") or {}).get("method") if prep is not None else None
    if route and route in (inv.get("rw_assumed_routes") or []):
        return {"facts": [f"invasion profile expected from Rmf and Rw: not assessed (Rw is an assumed value, route "
                          f"{route}, not derived from the logs)"], "columns": [], "cells": None, "values": []}
    rmf, rw = medians[inv["rmf_curve"]], medians[inv["rw_curve"]]
    ratio, mud = rmf / rw, mud_regime(rmf, rw)
    table = EXPECTED_ORDER[mud]
    cut = float(view.policy["cutoffs"]["sw_max"])
    conf = view.policy.get("confidence", {})
    tight, bh_max = set(conf.get("non_reservoir_lithologies", [])), conf.get("max_bad_hole_fraction")
    say = {"shallow": f"{shallow} > {deep}", "deep": f"{deep} > {shallow}", "equal": f"{shallow} = {deep}"}
    i_s, i_d = curves.index(shallow), curves.index(deep)
    cells, values, judged, matched, tight_seen = [], [rmf, rw, sig(ratio), cut], 0, 0, []
    differs: dict[str, list[str]] = {}       # observed order -> zones that differ from the expected one
    bad_hole: list[str] = []                 # differing zones with bad hole above the policy limit
    for j, z in enumerate(view.zones):
        s, d = means[i_s, j], means[i_d, j]
        sw = sig(_stat(view.zone_values(z, "SW"), "mean")) if view.available("SW") else float("nan")
        fluid = ("water" if sw >= cut else "hydrocarbon") if np.isfinite(sw) else None
        label = f"{'water' if fluid == 'water' else 'HC'} {fmt(sw)}" if fluid else "n/a"
        values += [sw] if np.isfinite(sw) else []
        if z.lithology in tight:
            tight_seen += [z.lithology] if z.lithology not in tight_seen else []
            cells.append([label, "not invaded"])
            continue
        want = expected_resistivity_order(mud, fluid)      # SW unknown: where water and hydrocarbon agree
        if want == "either" or not (np.isfinite(s) and np.isfinite(d)):
            cells.append([label, "either way" if want == "either" else "no data"])
            continue
        seen = "shallow" if s > d else "deep" if d > s else "equal"
        judged += 1
        matched += seen == want
        cells.append([label, "yes" if seen == want else "no"])
        if seen != want:
            differs.setdefault(seen, []).append(z.zone_id)
            bh = view.zone_values(z, "BAD_HOLE")
            if bh_max is not None and bh is not None and np.isfinite(bh).any() and float(np.nanmean(bh > 0.5)) > bh_max:
                bad_hole.append(z.zone_id)
    head = "against the invasion profile expected from Rmf and Rw"
    if judged:
        verdict = (f"{head}: {shallow} vs {deep} zone means match it in {matched} of {judged} zones with a definite "
                   "expectation" + ("; differ in " + "; ".join(f"{', '.join(ids)} ({say[seen]} observed)"
                                                                for seen, ids in differs.items()) if differs else "")
                   + (f"; bad hole above {fmt_pct(100 * bh_max)} in {', '.join(bad_hole)} of these" if bad_hole else ""))
        values += [round(100 * bh_max)] if bad_hole else []
    else:
        verdict = f"{head}: no zone has a definite expected order of {shallow} and {deep}"
    expect = lambda fl: (("either order" if table[fl]["order"] == "either" else say[table[fl]["order"]])
                         + f" ({table[fl]['why']})")
    basis = (f"expected profile: Rmf {fmt(rmf)} and Rw {fmt(rw)} ohm.m (interval medians at formation temperature; "
             f"Rmf/Rw = {fmt(ratio)}, {MUD_REGIMES[mud]}): water-bearing rock (zone SW >= {fmt(cut)}) {expect('water')}; "
             f"HC-bearing rock (SW < {fmt(cut)}) {expect('hydrocarbon')}"
             + (f"; {', '.join(tight_seen).lower()} zones {inv['not_invaded']}" if tight_seen else ""))
    return {"facts": [verdict, basis], "columns": ["fluid (zone SW)", f"matches expected {shallow} vs {deep}"],
            "cells": cells if judged else None, "values": values}


def curve_order(view: FormationView, curves: list[str], relation: str = "decreasing") -> dict:
    """Whether curves keep an order, zone by zone and then sample by sample, in both directions.

    relation: "decreasing" (each curve above the next, in the given order: c1 > c2 > c3), "increasing" (c1 < c2 < c3)
    or "between" (the middle curves lie between the first and the last, either way round). Both directions are
    always reported, so the finding says which order holds whatever order the curves were listed in (resistivities
    listed shallow-to-deep test the opposite profile to deep-to-shallow). Both views, in the order of the bases: each
    zone by its means (which order holds in how many zones, and which zones) and by its samples, then the zone samples
    pooled and the whole interval; the depth runs where the asked relation holds and fails and the typical margins
    between adjacent curves locate and size it.

    The zone level also gives each order's share of the zoned thickness and whether the middle curves lie between
    the first and the last; resistivity curves get the invasion profile expected from Rmf, Rw and each zone's SW
    (rules/curves.yaml invasion_profile) and whether each zone matches it, before any sample-level figure."""
    curves, missing = _check_curves(view, curves)
    relation = str(relation).strip().lower()
    if len(curves) < 2:
        raise EvidenceError("WHAT: need at least two curves with data. FIX: pass the curves in the order to test.")
    if relation not in ORDER_RELATIONS or (relation == "between" and len(curves) < 3):
        raise EvidenceError(f"WHAT: cannot test relation {relation!r} on {len(curves)} curves. FIX: use one of "
                            f"{list(ORDER_RELATIONS)} ('between' needs three or more curves).")
    X = np.vstack([view.values(c) for c in curves])
    valid = np.all(np.isfinite(X), axis=0)
    with np.errstate(invalid="ignore"):
        d = X[:-1] - X[1:]
        dec = valid & np.all(d > 0, axis=0)
        inc = valid & np.all(d < 0, axis=0)
        tie = valid & np.any(d == 0, axis=0)
        lo, hi = np.minimum(X[0], X[-1]), np.maximum(X[0], X[-1])
        between = valid & np.all((X[1:-1] > lo) & (X[1:-1] < hi), axis=0)
    holds = {"decreasing": dec, "increasing": inc, "between": between}[relation]
    zoned = view.zoned if view.zones else np.ones(valid.size, dtype=bool)
    down, up = " > ".join(curves), " < ".join(curves)
    between_text = f"{', '.join(curves[1:-1])} between {curves[0]} and {curves[-1]}"
    asked = {"decreasing": down, "increasing": up, "between": between_text}[relation]

    def pct(mask, sel):
        n = int((valid & sel).sum())
        return (100 * float((mask & sel).sum()) / n if n else float("nan")), n

    p_z, n_z = pct(holds, zoned)
    p_i, n_i = pct(holds, np.ones(valid.size, dtype=bool))
    k_z, k_i = int((holds & zoned & valid).sum()), int((holds & valid).sum())
    if n_z == 0:
        raise EvidenceError("WHAT: no sample has all of these curves. FIX: choose curves that overlap.")
    # Zone by zone first: the zone-mean order of each zone and the share of its samples where the asked order holds.
    means = np.array([[_stat(view.zone_values(z, c), "mean") for z in view.zones] for c in curves],
                     dtype=float).reshape(len(curves), len(view.zones))
    rows, zone_values, by_order = [], [], {"decreasing": [], "increasing": [], "mixed": [], "n/a": []}
    within = []                                   # zones whose middle curves lie between the first and the last
    for j, z in enumerate(view.zones):
        m = list(means[:, j])
        zsel = np.zeros(valid.size, dtype=bool)
        zsel[z.indices] = True
        zp = pct(holds, zsel)[0]
        if not all(np.isfinite(m)):
            order = "n/a"
        else:
            order = ("decreasing" if all(m[i] > m[i + 1] for i in range(len(m) - 1)) else
                     "increasing" if all(m[i] < m[i + 1] for i in range(len(m) - 1)) else "mixed")
            lo_m, hi_m = min(m[0], m[-1]), max(m[0], m[-1])
            if len(m) >= 3 and all(lo_m < v < hi_m for v in m[1:-1]):
                within.append(z.zone_id)
        by_order[order].append(z.zone_id)
        rows.append([z.zone_id, z.lithology, f"{fmt_depth(z.top)}–{fmt_depth(z.base)}"] + [sig(v) for v in m]
                    + [sig(zp) if np.isfinite(zp) else None, order])
        zone_values += [sig(v) for v in m if np.isfinite(v)] + ([sig(zp)] if np.isfinite(zp) else [])
    facts = []
    if view.zones:
        thick = {z.zone_id: z.thickness for z in view.zones}

        def share(ids):
            """The zones' share of the zoned thickness (zones of one order may be few but thick, or many but thin)."""
            if not ids or view.zoned_thickness <= 0:
                return ""
            p = 100 * sum(thick[i] for i in ids) / view.zoned_thickness
            zone_values.append(round(p))
            return f", {fmt_pct(p)} of the zoned thickness"

        listed = lambda ids: f" ({', '.join(ids)})" if ids else ""
        group = lambda ids: f"{len(ids)}{listed(ids)}{share(ids)}"
        line = (f"zone means, zone by zone (of {len(view.zones)} zones): {down} in {group(by_order['decreasing'])}; "
                f"{up} in {group(by_order['increasing'])}; mixed in {group(by_order['mixed'])}")
        if len(curves) >= 3:                      # with three curves, "between" is decreasing or increasing
            line += (f"; {between_text} (either way round"
                     f"{', asked' if relation == 'between' else ''}) in {len(within)}"
                     f"{listed(within) if len(curves) > 3 else ''}{share(within)}")
        line += (f"; no mean of every curve in {len(by_order['n/a'])}{listed(by_order['n/a'])}" if by_order["n/a"] else "")
        facts.append(line)
    expectation = _invasion_expectation(view, curves, means)
    if expectation:
        facts += expectation["facts"]
        zone_values += expectation["values"]
        if expectation["cells"] is not None:      # before the zone-mean order column, which stays last
            rows = [r[:-1] + c + r[-1:] for r, c in zip(rows, expectation["cells"])]
    shares = {name: pct(m, zoned)[0] for name, m in (("decreasing", dec), ("increasing", inc), ("tie", tie))}
    neither = 100 - shares["decreasing"] - shares["increasing"]
    dominant = ("decreasing" if shares["decreasing"] >= 50 else "increasing" if shares["increasing"] >= 50 else None)
    basis = "zoned samples" if view.zones else "samples"
    facts += [f"asked, sample by sample: {asked} holds in {S.count_share(k_z, n_z, basis)} with all {len(curves)} "
              f"curves" + (f"; {S.whole_label(view)}: {S.count_share(k_i, n_i)}" if view.zones else ""),
              f"both directions, sample by sample: {down} in {fmt_pct(shares['decreasing'], 1)}, {up} in "
              f"{fmt_pct(shares['increasing'], 1)}, neither (the curves cross) in {fmt_pct(neither, 1)}"
              + (f"; equal values in {fmt_pct(shares['tie'], 1)}" if shares["tie"] > 0 else "") + "; "
              + (f"the {'decreasing' if dominant == 'decreasing' else 'increasing'} order "
                 f"({down if dominant == 'decreasing' else up}) holds in most samples" if dominant
                 else "neither order holds in most samples")]
    values = [k_z, k_i, round(p_z, 1), n_z, round(p_i, 1), n_i, round(shares["decreasing"], 1), round(shares["increasing"], 1),
              round(neither, 1), round(shares["tie"], 1)]
    margins = []
    sel = valid & zoned
    for i in range(len(curves) - 1):
        diff = float(np.median(X[i][sel] - X[i + 1][sel]))
        text = f"{curves[i]} - {curves[i + 1]} = {fmt(diff)} {view.unit(curves[i])}".rstrip()
        values.append(sig(diff))
        if np.all(X[i][sel] > 0) and np.all(X[i + 1][sel] > 0):
            ratio = float(np.median(X[i][sel] / X[i + 1][sel]))
            text += f" ({curves[i]}/{curves[i + 1]} = {fmt(ratio)})"
            values.append(sig(ratio))
        margins.append(text)
    facts.append("typical margins (medians over the " + basis + "): " + "; ".join(margins))
    most = view.reg.limit("curve_order_max_runs", 8)
    min_run = view.reg.limit("curve_order_min_run_m", None)          # tool resolution (rules/catalog.yaml limits)
    min_run = None if min_run is None else view.to_unit(min_run)

    def zone_at(a, b):
        """The zones an interval overlaps (first–last when it crosses a contact)."""
        hit = [z.zone_id for z in view.zones if z.top - 1e-6 <= b and a <= z.base + 1e-6]
        return "outside the zones" if not hit else hit[0] if len(hit) == 1 else f"{hit[0]}–{hit[-1]}"

    for label, mask in (("holds", valid & holds), ("fails", valid & ~holds)):
        runs = _runs(view.depth, mask.astype(float), view.step)
        if not runs:
            facts.append(f"{asked} {'holds in no sample' if label == 'holds' else 'holds in every sample'} with all curves")
            continue
        total = sum(b - a + view.step for a, b in runs)
        resolved = sum(b - a + view.step >= min_run for a, b in runs) if min_run is not None else None
        shown = sorted(sorted(runs, key=lambda r: -(r[1] - r[0]))[:most])          # the thickest, in depth order
        facts.append(f"{asked} {label} sample by sample over {len(runs)} depth intervals ({fmt(total)} {view.depth_unit} in all"
                     + (f"; {resolved} at least {fmt(min_run)} {view.depth_unit} thick" if min_run is not None else "") + ")"
                     + (f"; the {len(shown)} thickest" if len(runs) > len(shown) else "") + ": "
                     + ", ".join(f"{fmt_depth(a)}–{fmt_depth(b)} {view.depth_unit} ({fmt(b - a + view.step)} {view.depth_unit}, {zone_at(a, b)})"
                                 for a, b in shown))
        values += [len(runs), sig(total)] + ([resolved, float(min_run)] if min_run is not None else []) \
            + [v for a, b in shown for v in (a, b, sig(b - a + view.step))]
    values += zone_values
    if missing:
        facts.append(_missing_text(view, missing))
    return {"title": f"Curve order of {', '.join(curves)} (asked: {relation}), by zone, then sample by sample",
            "columns": ["zone", "lithology", f"depth ({view.depth_unit})"] + [f"mean {c}" for c in curves] + [f"% samples {relation}"]
                       + (expectation["columns"] if expectation and expectation["cells"] is not None else [])
                       + ["zone-mean order"],
            "rows": rows, "facts": facts, "values": values}


def spike_flags(view: FormationView, curves: list[str], k: float = 3.0,
                baseline: Literal["zoned", "interval", "zone"] = "zoned") -> dict:
    """Samples beyond mean +/- k standard deviations (bounds in curve units), with counts per zone and the largest
    deviations, and adjacent-sample jumps above k sigma of the jumps.

    baseline: "zoned" (default) screens the lithology-zone samples against their own mean and std: thin runs and the
    transitions between zones mix two rock types and would inflate the std and flag ordinary contacts. The whole-
    interval figures follow as a labelled note only where they differ materially. "interval" screens every sample
    against the interval statistics; "zone" screens each zone against its own statistics."""
    curves, _ = _check_curves(view, curves)
    if baseline not in ("zoned", "interval", "zone"):
        raise EvidenceError(f"WHAT: unknown baseline {baseline!r}. FIX: use zoned, interval or zone.")
    n_all = int(view.mask.sum())
    zoned = view.zoned
    if baseline == "zoned" and not zoned.any():
        baseline = "interval"                       # no zones: the interval is the only baseline
    pool = zoned if baseline in ("zoned", "zone") else np.ones(n_all, dtype=bool)
    zone_of = np.full(n_all, -1)
    for i, z in enumerate(view.zones):
        zone_of[z.indices] = i
    rows, values, facts = [], [], []

    def screen(x, sel):
        mu, sd = float(np.nanmean(x[sel])), float(np.nanstd(x[sel]))
        lo, hi = mu - k * sd, mu + k * sd
        with np.errstate(invalid="ignore"):
            return mu, sd, lo, hi, sel & ((x < lo) | (x > hi))

    for c in curves:
        x = view.values(c)
        ok = np.isfinite(x)
        if baseline == "zone":
            out = np.zeros_like(ok)
            for z in view.zones:
                zx = x[z.indices]
                if np.isfinite(zx).sum() >= 3:
                    mu, sd = float(np.nanmean(zx)), float(np.nanstd(zx))
                    out[z.indices] = np.isfinite(zx) & (np.abs(zx - mu) > k * sd) if sd > 0 else False
            mu, sd = float(np.nanmean(x[pool & ok])), float(np.nanstd(x[pool & ok]))
            lo = hi = None
        else:
            mu, sd, lo, hi, out = screen(x, ok & pool)
        dx = np.abs(np.diff(x))
        if baseline == "interval":
            pair = np.ones(dx.size, dtype=bool)
        else:                                       # jumps within a zone, not across a lithology contact
            pair = (zone_of[:-1] == zone_of[1:]) & (zone_of[:-1] >= 0)
        dxs = np.where(pair, dx, np.nan)
        dsd = float(np.nanstd(dxs)) if np.isfinite(dxs).any() else 0.0
        jumps = int(np.nansum(dxs > k * dsd)) if dsd > 0 else 0
        runs = _runs(view.depth, out.astype(float), view.step)
        top = ", ".join(f"{fmt_depth(a)}–{fmt_depth(b)}" for a, b in runs[:5])
        per_zone = "; ".join(f"{z.zone_id} {int(out[z.indices].sum())}" for z in view.zones if out[z.indices].any())
        n_screened = int((ok & pool).sum())
        rows.append([c, sig(mu), sig(sd), sig(lo) if lo is not None else "per zone", sig(hi) if hi is not None else "per zone",
                     int(out.sum()), sig(100 * out.sum() / max(n_screened, 1)), jumps, top or "-"])
        values += [sig(mu), sig(sd), int(out.sum()), sig(100 * out.sum() / max(n_screened, 1)), jumps, n_screened]
        values += [v for v in (lo, hi) if v is not None and np.isfinite(v)]
        values += [sig(v) for v in (lo, hi) if v is not None and np.isfinite(v)]
        if out.any():
            dev = np.where(out, np.abs(x - mu), -1.0)
            worst = np.argsort(dev)[::-1][: min(3, int(out.sum()))]
            facts.append(f"{c}: flagged by zone: {per_zone or 'none'}; largest deviations "
                         + ", ".join(f"{fmt(float(x[w]))} at {fmt_depth(float(view.depth[w]))} {view.depth_unit}" for w in sorted(worst)))
            values += [sig(float(x[w])) for w in worst] + [float(view.depth[w]) for w in worst]
        if baseline == "zoned" and not zoned.all():
            mu_i, sd_i, lo_i, hi_i, out_i = screen(x, ok)
            if _differs(mu, mu_i, view) or _differs(sd, sd_i, view) or _differs(float(out.sum()), float(out_i.sum()), view):
                facts.append(f"{c} whole interval ({int(ok.sum())} samples, thin runs and transitions included): mean "
                             f"{fmt(mu_i)}, std {fmt(sd_i)}, bounds {fmt(lo_i)} to {fmt(hi_i)}, {int(out_i.sum())} "
                             "samples beyond")
                values += [sig(mu_i), sig(sd_i), sig(lo_i), sig(hi_i), int(out_i.sum()), int(ok.sum())]
    basis = {"zone": "each zone's own mean and std", "interval": "the interval mean and std",
             "zoned": "the mean and std of the lithology-zone samples"}[baseline]
    if baseline == "zoned":
        facts.insert(0, f"screened: the lithology-zone samples ({int(zoned.sum())} of {n_all}; thin runs and "
                        "transitions left out); jumps counted within zones")
        values += [int(zoned.sum()), n_all]
    return {"title": f"Spike screen (beyond mean +/- {k} std of {basis}; adjacent jumps > {k} std of the jumps)",
            "columns": ["curve", "mean", "std", f"lower bound", f"upper bound", "samples beyond", "% samples",
                        "adjacent jumps", f"first runs ({view.depth_unit})"],
            "rows": rows, "facts": facts + [NOT_EXPORTED], "values": values}


def adjacent_jumps(view: FormationView, curve: str, threshold: float) -> dict:
    """Changes between adjacent samples larger than a threshold in curve units (e.g. sonic cycle skips), the model's
    threshold: each zone (pairs inside it), the zones pooled, and the whole interval (every adjacent pair, across
    contacts and between the zones too): the largest change, how many exceed the threshold, where."""
    (curves, _), = [_check_curves(view, [curve])]
    if not curves:
        raise EvidenceError(f"WHAT: {curve} has no data here. FIX: use a curve listed on the formation card.")
    c = curves[0]
    x, d = view.values(c), view.depth
    dx = np.diff(x)
    ok = np.isfinite(dx)
    if not ok.any():
        raise EvidenceError(f"WHAT: {c} has no adjacent valid samples. FIX: choose another curve.")
    big = ok & (np.abs(dx) > float(threshold))
    inside = np.zeros(dx.size, dtype=bool)
    rows = []
    for z in view.zones:
        zi = z.indices[:-1] if len(z.indices) > 1 else z.indices[:0]
        inside[zi] = True
        rows.append([z.zone_id, z.lithology, f"{fmt_depth(z.top)}–{fmt_depth(z.base)}", int(big[zi].sum()),
                     sig(float(np.nanmax(np.abs(dx[zi])))) if zi.size and np.isfinite(dx[zi]).any() else None])
    facts = [f"threshold {fmt(float(threshold))} {view.unit(c)} ({S.threshold_source(True)})"]
    values = [float(threshold)] + [r[4] for r in rows if r[4] is not None]
    for label, sel in ((S.pooled_label(view, view.zones), ok & inside), (S.whole_label(view), ok)):
        if not sel.any():
            facts.append(f"{label}: no adjacent valid samples")
            continue
        imax = int(np.nanargmax(np.abs(np.where(sel, dx, 0.0))))
        hits = np.flatnonzero(big & sel)
        where = [f"{fmt_depth(float(d[i]))}–{fmt_depth(float(d[i + 1]))} {view.depth_unit} ({fmt(float(dx[i]))})" for i in hits[:10]]
        facts.append(f"{label}: largest adjacent change {fmt(float(dx[imax]))} {view.unit(c)} at "
                     f"{fmt_depth(float(d[imax]))}–{fmt_depth(float(d[imax + 1]))} {view.depth_unit}; {len(hits)} changes "
                     f"exceed {fmt(float(threshold))} {view.unit(c)}" + (": " + "; ".join(where) if where else ""))
        values += [sig(float(dx[imax])), sig(abs(float(dx[imax]))), len(hits), S.outside(view)]
    return {"title": f"Adjacent-sample changes of {c} larger than {fmt(float(threshold))} {view.unit(c)}: each zone, the "
                     "zones pooled, the whole interval",
            "columns": ["zone", "lithology", f"depth ({view.depth_unit})", "changes beyond threshold", "largest |change|"],
            "rows": rows, "facts": facts, "values": values}


def vertical_sequence(view: FormationView, curves: list[str] = None, min_change: Optional[float] = None) -> dict:
    """Zones from base to top with the change of each curve named (default: GR, else VCL) from the zone below, grouped
    into packages of steps in one direction. GR/VCL decreasing upward = cleaning-up (coarsening-upward); increasing
    upward = dirtying-up (fining-upward). Steps smaller than min_change (default: 10% of the curve's zone-mean range, at
    least 3 API for GR or 0.03 for VCL) count as no change, so weak trends are not called sequences. min_change is in
    one curve's units: given with several curves, it is refused."""
    named = bool(curves)
    curves, _ = _check_curves(view, curves or ["GR", "VCL"])
    if not curves or len(view.zones) < 2:
        raise EvidenceError("WHAT: need a curve with data and at least two zones. FIX: use depth_trend or zone_stats.")
    if not named:
        curves = curves[:1]                                           # the default: GR, else VCL
    if min_change is not None and len(curves) > 1:
        raise EvidenceError(f"WHAT: min_change with {len(curves)} curves. WHY: it is a change in one curve's units. "
                            "FIX: ask one curve at a time with min_change, or leave min_change out (each curve's "
                            "default threshold applies).")
    from petrophys.evaluation.intervals import stacking_pattern

    zs = list(reversed(view.zones))                                   # base first
    kinds = {"cleaning_up": "cleaning-up (coarsening-upward)", "dirtying_up": "dirtying-up (fining-upward)",
             "abrupt_decrease": "abrupt decrease upward", "abrupt_increase": "abrupt increase upward"}
    src = (S.threshold_source(True) if min_change is not None else
           "the workflow's: petrophys stacking_pattern's default, 10% of the curve's zone-mean range, at least 3 API for "
           "GR or 0.03 for VCL")
    one = len(curves) == 1
    rows = [[z.zone_id, z.lithology, f"{fmt_depth(z.top)}–{fmt_depth(z.base)}"] for z in zs]
    columns = ["zone", "lithology", f"depth ({view.depth_unit})"]
    facts, values = [], []
    for c in curves:
        means = np.array([_stat(view.zone_values(z, c), "mean") for z in zs])
        pattern = stacking_pattern(means, c, min_change)              # petrophys: steps and packages, base to top
        thr = pattern["threshold"]
        for i in range(len(zs)):
            ch, step = pattern["changes"][i], pattern["steps"][i]
            rows[i] += [sig(means[i]), sig(ch) if np.isfinite(ch) else None, step]
            values += [sig(means[i])] + ([sig(ch)] if np.isfinite(ch) else [])
        values.append(sig(thr))
        columns += [f"mean {c}", "change from zone below" if one else f"{c} change from zone below",
                    "step" if one else f"{c} step"]
        packages = [f"{zs[p['start']].zone_id}→{zs[p['end']].zone_id} {kinds[p['kind']]}, {c} "
                    f"{fmt(means[p['start']])}→{fmt(means[p['end']])}" for p in pattern["packages"]]
        facts += [f"read from base to top; a step counts when {c} changes by at least {fmt(thr)} ({src})",
                  ("packages: " + "; ".join(packages)) if packages else
                  f"no zone-to-zone change of {c} reaches {fmt(thr)}: no robust sequence"]
    return {"title": f"Vertical sequence of zone-mean {', '.join(curves)}, base to top", "rows": rows, "facts": facts,
            "values": values, "columns": columns}


def flag_intervals(view: FormationView, flag: str, min_thickness_m: float = 0.0, max_items: int | None = None) -> dict:
    max_items = max_items or view.reg.limit("flag_intervals_max_items", 25)
    flag = flag.upper()
    if not view.is_flag(flag):
        raise EvidenceError(f"WHAT: {flag} is not a flag curve. FIX: use one of {sorted(view.reg.flags | view.calc_flags)}.")
    data = view.values(flag)
    if data is None or not np.isfinite(data).any():
        return {"title": f"{flag} intervals", "facts": [f"{flag} is not available in this interval"], "values": []}
    gross, of = view.gross, "the interval"
    runs = [(a, b) for a, b in _runs(view.depth, data, view.step) if b - a + view.step >= view.to_unit(min_thickness_m)]
    total = float(np.nansum(data > 0.5) * view.step)
    facts = [f"{flag} total {fmt(total)} {view.depth_unit} = {fmt_pct(100 * total / max(gross, 1e-9), 1)} of {of}; {len(runs)} interval(s)"]
    graded = flag in set(view.policy.get("confidence", {}).get("applies_to", []))
    rows = []
    shown = runs if len(runs) <= max_items else \
        sorted(sorted(runs, key=lambda r: -(r[1] - r[0]))[:max_items])       # the thickest, listed in depth order
    for a, b in shown:
        if graded:
            zid, lith, conf, reasons = grade_interval(view, a, b)
            rows.append([f"{fmt_depth(a)}–{fmt_depth(b)}", sig(b - a + view.step), zid, lith,
                         conf + (f" ({'; '.join(reasons)})" if reasons else "")])
        else:
            rows.append([f"{fmt_depth(a)}–{fmt_depth(b)}", sig(b - a + view.step)])
    if len(runs) > max_items:
        facts.append(f"{len(runs) - max_items} further intervals not listed (the thinnest)")
    values = [total, 100 * total / max(gross, 1e-9)] + [v for a, b in shown for v in (a, b, b - a + view.step)]
    return {"title": f"{flag} intervals (min thickness {length_m(view, min_thickness_m)})" + (" with screening confidence" if graded else ""),
            "columns": [f"depth ({view.depth_unit})", f"thickness ({view.depth_unit})"] + (["zone", "lithology", "confidence"] if graded else []),
            "rows": rows, "facts": facts, "values": values}


def _limiting_cutoffs(view: FormationView, values: list) -> list[str]:
    """Which cutoff removes how much rock, in order (shale, then porosity, then saturation), and the zones that hold
    net pay: a pay verdict names the first cutoff that fails, not a zone-mean class."""
    from petrophys.evaluation.net_pay import cutoff_attrition

    flags = {f: view.values(f) for f in ("NET_ROCK", "NET_RES", "NET_PAY")}
    if any(v is None for v in flags.values()):
        return []
    pay = flags["NET_PAY"] > 0.5
    n = pay.size
    if n == 0:
        return []
    label = {"shale_volume": "shale-volume cutoff (not NET_ROCK)", "porosity": "porosity cutoff (NET_ROCK but not NET_RES)",
             "saturation": "saturation cutoff (NET_RES but not NET_PAY)"}
    # what the net-pay step left out of NET_RES and NET_PAY whatever the cutoffs: its NET_EXCLUSION curve, per sample
    # the kind of exclusion that removed it (Petrophys's codes: bad hole, coal, ...); without it, the kinds its record
    # lists are named beside the porosity cutoff
    from petroharness.well.summary import code_labels
    kinds = code_labels(view, "NET_EXCLUSION") if view.values("NET_EXCLUSION") is not None else {}
    why = np.asarray(view.values("NET_EXCLUSION"), dtype=float) if kinds else None
    listed = [k.replace("_", " ") for k in ((last_step(view.prep.steps, "net_pay") or {}).get("parameters") or {})
              .get("excluded_from_net_reservoir_and_pay") or {}]
    parts = []
    for step in cutoff_attrition(flags["NET_ROCK"], flags["NET_RES"], flags["NET_PAY"]):      # petrophys
        share = step["fails"]
        values.append(round(100 * share))                       # as displayed (whole percent)
        of = 'the interval' if step['tested'] == n else 'the rock passing the previous cutoff'
        if step["cutoff"] == "porosity" and share > 0 and (why is not None or listed):
            gap = (flags["NET_ROCK"] > 0.5) & ~(flags["NET_RES"] > 0.5)
            tested = max(int(step["tested"]), 1)
            if why is not None:                                 # each kind its share, the rest the porosity cutoff
                from petroharness.well.summary import class_groups, in_class
                cells = []
                for key in class_groups(sorted(kinds), kinds):  # codes the labels name alike: one kind (O4)
                    codes = key if isinstance(key, tuple) else (key,)
                    kind = kinds[codes[0]]
                    k = int((gap & in_class(why, key)).sum()) if all(codes) else int((gap & ~(why > 0)).sum())
                    if not k:
                        continue
                    pct = 100 * k / tested
                    values.append(round(pct))
                    cells.append(f"{fmt_pct(pct)} fails the porosity cutoff" if not all(codes) else
                                 f"{fmt_pct(pct)} is left out as {kind.replace('_', ' ')} (whatever its porosity)")
                parts.append(f"{fmt_pct(100 * share)} of {of} is not NET_RES: " + ", ".join(cells))
            else:
                parts.append(f"{fmt_pct(100 * share)} of {of} is not NET_RES: it fails the porosity cutoff or is left "
                             f"out as the step records ({', '.join(listed)})")
            continue
        parts.append(f"{fmt_pct(100 * share)} of {of} fails the {label[step['cutoff']]}")
    facts = ["cutoffs in order: " + "; ".join(parts)] if parts else []
    zones = [(z.zone_id, float(np.mean(pay[z.indices]))) for z in view.zones if pay[z.indices].any()]
    if view.zones:
        if zones:
            values.extend(sig(f) for _, f in zones)
            facts.append("NET_PAY fraction by zone: " + ", ".join(f"{zid} {fmt(sig(f))}" for zid, f in zones)
                         + f"; the other {len(view.zones) - len(zones)} zones have none")
        else:
            facts.append(f"none of the {len(view.zones)} zones holds NET_PAY samples")
    return facts


def pay_summary(view: FormationView) -> dict:
    """The workflow's net flags summarised by petrophys: calculate_net_gross (each sample counts its own depth cell,
    gaps capped) and calculate_pay_averages over NET_PAY (geometric mean for PERM, as the library does)."""
    import warnings

    from petrophys.evaluation.summaries.averages import calculate_pay_averages
    from petrophys.evaluation.summaries.net_gross import calculate_net_gross

    well = view.interval_well()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ng = calculate_net_gross(well)
    gross = ng.gross_thickness
    rows, values = [], []
    thickness = {"NET_ROCK": ng.net_rock_thickness, "NET_RES": ng.net_reservoir_thickness, "NET_PAY": ng.net_pay_thickness}
    for flag, thick in thickness.items():
        if view.values(flag) is None:
            continue
        rows.append([flag, sig(thick), sig(thick / gross if gross else float("nan"))])
        values += [sig(thick), sig(thick / gross if gross else float("nan"))]
    facts = []
    if all(view.values(f) is not None for f in thickness) and ng.net_rock_thickness > 0:
        facts.append(f"net reservoir / net rock = {fmt(sig(ng.ntg_res_rock))}"
                     + (f"; net pay / net reservoir = {fmt(sig(ng.ntg_pay_res))}" if ng.net_reservoir_thickness > 0 else ""))
        values += [sig(ng.ntg_res_rock), sig(ng.ntg_pay_res)]
    pay = view.values("NET_PAY")
    if pay is not None and np.nansum(pay > 0.5) > 0:
        curves = [c for c in view.reg.curves["pay_summary_curves"] if view.prep.well.get(c) is not None]
        averages = calculate_pay_averages(well, curves=curves)
        for c in curves:
            v = averages.get(c)
            if v is not None and np.isfinite(v):
                v = sig(float(v))
                kind = "geometric mean" if c.upper() in ("PERM", "K", "PERMEABILITY") else "mean"
                facts.append(f"{kind} {c} in NET_PAY samples = {fmt(v)} (the workflow's pay average: Petrophys "
                             f"calculate_pay_averages, geometric for permeability)")
                values.append(v)
        pc = pay_confidence(view)
        cr = view.policy.get("confidence", {})
        facts.append(f"NET_PAY screening confidence: higher {fmt(pc['higher_m'])} {view.depth_unit} (not non-reservoir or marginal rock, "
                     f"bad hole <= {100 * cr.get('max_bad_hole_fraction', 0.5):.0f}%, >= {length_m(view, cr.get('min_thickness_m', 1.0))}); "
                     f"low {fmt(pc['low_m'])} {view.depth_unit}"
                     + (" — " + ", ".join(f"{k}: {fmt(v)} {view.depth_unit}" for k, v in pc["low_reasons"].items()) if pc["low_reasons"] else ""))
        values += [sig(pc["higher_m"]), sig(pc["low_m"])] + [sig(v) for v in pc["low_reasons"].values()]
    else:
        facts.append("no NET_PAY samples in the interval")
    facts.extend(_limiting_cutoffs(view, values))
    # the cutoffs as the net-pay step that wrote the flags applied them (its own operators: the pinned engine's are
    # strict, the installed library's inclusive), from the record as the card states them
    facts.append(f"gross {fmt(sig(gross))} {view.depth_unit} (the interval's sample cells); "
                 + cutoff_fact(last_step(view.prep.steps, "net_pay"), view.policy))
    values.append(sig(gross))
    return {"title": f"Net-to-gross summary (thickness {view.depth_unit}, fraction of gross)", "columns": ["flag", f"thickness ({view.depth_unit})", "fraction"],
            "rows": rows, "facts": facts, "values": values}


_ANALYZERS = {
    "hydrocarbon": ("petrophys.evaluation.diagnostics.hydrocarbon_analysis", "HydrocarbonAnalysis"),
    "saturation": ("petrophys.evaluation.diagnostics.saturation_analysis", "SaturationAnalysis"),
    "permeability": ("petrophys.evaluation.diagnostics.permeability_analysis", "PermeabilityAnalysis"),
    "porosity": ("petrophys.evaluation.diagnostics.porosity_analysis", "PorosityAnalysis"),
    "lithology": ("petrophys.evaluation.diagnostics.lithology_analysis", "LithologyAnalysis"),
    "numerical": ("petrophys.evaluation.diagnostics.numerical_statistical_analysis", "NumericalStatisticalAnalysis"),
}


_SECTION_META = ("description", "methodology", "calculation_thresholds")


def make_analyzer(view: FormationView, family: str):
    """A family's petrophys analyzer with the policy's class tables (policy analyzers.class_tables: the library's
    current set, or the set a data config names in data.analyzer_class_tables, FormationView.build). Analyzers that
    take no class_tables argument (the numerical one, or any in a library without class-table sets) are built with
    their defaults."""
    import importlib
    import inspect
    module, cls = _ANALYZERS[family]
    klass = getattr(importlib.import_module(module), cls)
    tables = (view.policy.get("analyzers") or {}).get("class_tables")
    if tables and "class_tables" in inspect.signature(klass.__init__).parameters:
        return klass(class_tables=tables)
    return klass()

def zone_results(view: FormationView, family: str) -> list[tuple[Any, Any]]:
    """(zone, CategoryAnalysisResult): the library analyzer of a family run on exactly each zone's samples (as the
    workflow of record), once per view; the store and every class lookup read the same results."""
    import warnings

    family = family.lower()
    if family not in _ANALYZERS:
        raise EvidenceError(f"WHAT: unknown family {family!r}. FIX: use one of {sorted(_ANALYZERS)}.")
    cache = view.__dict__.setdefault("_analyzer_results", {})
    if family not in cache:
        analyzer = make_analyzer(view, family)
        out = []
        for z in view.zones:
            # with the calculations the well was interpreted with (petroharness.well.calculations)
            with warnings.catch_warnings(), calculations(getattr(view.prep, "context_profile", None)):
                warnings.simplefilter("ignore")
                out.append((z, analyzer.analyze(view.zone_well(z), add_curves=False)))
        cache[family] = out
    return cache[family]


def label_runs(depth: np.ndarray, labels) -> dict[str, list[tuple[float, float]]]:
    """Each label's runs as (first, last) sample depths, in first-appearance order; missing labels (None, NaN, '')
    have none. Runs from flag_runs (petrophys flag_intervals)."""
    labels = np.asarray(labels, dtype=object)
    out: dict[str, list[tuple[float, float]]] = {}
    for label in dict.fromkeys(labels.tolist()):
        if label is None or label == "" or (isinstance(label, float) and np.isnan(label)):
            continue
        out[str(label)] = [(float(depth[a]), float(depth[b])) for a, b in flag_runs(depth, (labels == label).astype(float))]
    return out


def _shown(x: float) -> float:
    """A depth at the analyzers' display precision (0.1, as their interval text): class listings keep it."""
    return float(f"{x:.1f}")



def classify_raw(view: FormationView, family: str, sections: Optional[list[str]] = None):
    """All threshold classes per zone from the library analyzer's per-sample labels:
    {section: {label: [(zone_id, top, base)]}}, depths at the analyzers' display precision (0.1)."""
    merged: dict[str, dict[str, list[tuple[str, float, float]]]] = {}
    thresholds: dict[str, str] = {}
    for z, result in zone_results(view, family):
        zd = view.depth[z.indices]
        for sec, section in result.sections.items():
            if sections and sec not in sections:
                continue
            thresholds.setdefault(sec, section.calculation_thresholds or "")
            for label, runs in label_runs(zd, section.raw_labels).items():
                merged.setdefault(sec, {}).setdefault(label, []).extend((z.zone_id, _shown(a), _shown(b)) for a, b in runs)
    return merged, thresholds


def _summary_fields(body) -> list[tuple[str, Any]]:
    """The scalar fields of an analyzer's summary (its result metadata, values not class intervals), e.g.
    reservoir_fraction of formation_level_summary; empty for anything else."""
    if not isinstance(body, dict):
        return []
    return [(k, v) for k, v in body.items()
            if k not in _SECTION_META and not isinstance(v, (list, dict)) and v not in (None, "")]


def section_summaries(view: FormationView, family: str, section: str) -> list[tuple[str, list[float]]]:
    """Analyzer sections that report values per zone instead of class intervals (e.g. formation_level_summary,
    mhi_confirmation): one line per zone with its scalar fields, and the numbers shown (for the verifier).
    Without it a verdict topic whose section is a summary would show nothing."""
    out = []
    for z, result in zone_results(view, family):
        fields, nums = [], []
        for k, v in _summary_fields(result.metadata.get(section)):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                nums.append(sig(float(v)))
                fields.append(f"{k} {fmt(sig(float(v)))}")
            else:
                fields.append(f"{k}: {v}")
        if fields:
            out.append((f"{section} — {z.zone_id} ({z.lithology}, {fmt_depth(z.top)}-{fmt_depth(z.base)} {view.depth_unit}): "
                        + "; ".join(fields), nums))
    return out



def classify(view: FormationView, topic=None, family: Optional[str] = None, sections: Optional[list[str]] = None,
             max_per_class: int | None = None) -> dict:
    """Threshold classes from the library analyzers for a domain topic, run per zone (as the workflow of record)."""
    max_per_class = max_per_class or view.reg.limit("classify_max_per_class", 8)
    topics = view.reg.resolve_topics(topic if topic is not None else family)
    if not topics:
        raise EvidenceError(f"WHAT: unknown topic {topic or family!r}. "
                            f"FIX: use one of {sorted(view.reg.topics['topics'])} (or a judgement name).")
    facts, values = [], []
    for name in topics:
        for fam, secs in view.reg.topics["topics"][name]:
            merged, thresholds = classify_raw(view, fam, sections or secs)
            for sec, classes in merged.items():
                facts.append(f"{sec} — thresholds: {thresholds.get(sec, '')[:300]}")
                for label, items in classes.items():
                    spans = [(zid, f"{a:.1f}-{b:.1f} {view.depth_unit}", a, b) for zid, a, b in items]
                    total = sum(b - a + view.step for _, _, a, b in spans)
                    shown = sorted(sorted(spans, key=lambda s: -(s[3] - s[2]))[:max_per_class], key=lambda s: s[2])
                    more = len(spans) - len(shown)
                    facts.append(f"  {label} ({len(spans)} intervals, {fmt(total)} {view.depth_unit}): "
                                 + "; ".join(f"{zid}:{it}" for zid, it, _, _ in shown)
                                 + (f"; +{more} thinner intervals not listed" if more > 0 else ""))
                    values.append(sig(total))
                    values.extend(v for _, _, a, b in shown for v in (a, b))
            for sec in (s for s in (sections or secs) if s not in merged):
                for line, nums in section_summaries(view, fam, sec):   # summary-shaped (values, not classes)
                    facts.append(line)
                    values.extend(nums)
    if not facts:
        facts.append("no classes assigned in the lithology zones")
    return {"title": f"Classes for {', '.join(topics)} by zone (zone:depth interval; thickest first, listed in depth order)",
            "facts": facts, "values": values}


def _zone_mean_well(view: FormationView):
    """A petrophys Well with one sample per zone holding the zone means (codes as the zone's mode)."""
    from petrophys.model.well import Well

    full = view.prep.well
    w = Well(name=full.name)
    w.depth = np.array([(z.top + z.base) / 2 for z in view.zones], dtype=float)
    w._depth_unit = view.depth_unit                     # zone mid-points are in metres whatever the LAS unit
    w.header, w._parameters = full.header, full._parameters
    for mnemonic in full.curves:
        data = view.values(mnemonic)
        if data is None:
            continue
        vals = []
        for z in view.zones:
            x = data[z.indices]
            x = x[np.isfinite(x)]
            if x.size == 0:
                vals.append(np.nan)
            elif mnemonic == view.lithology_curve or mnemonic.startswith("LITHOLOGY"):
                u, c = np.unique(np.round(x), return_counts=True)
                vals.append(float(u[np.argmax(c)]))
            else:
                vals.append(float(np.mean(x)))
        w.add_curve(mnemonic, vals, view.unit(mnemonic))
    return w


def zone_classes_raw(view: FormationView, topic) -> dict:
    """{section: {zone_id: label}} from the analyzer run on zone means, plus thresholds."""
    import warnings

    topics = view.reg.resolve_topics(topic)
    if not topics:
        raise EvidenceError(f"WHAT: unknown topic {topic!r}. FIX: use one of {sorted(view.reg.topics['topics'])}.")
    w = _zone_mean_well(view)                         # one sample per zone, in zone order
    out, thresholds, summaries, families = {}, {}, [], {}
    for name in topics:
        for fam, secs in view.reg.topics["topics"][name]:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = make_analyzer(view, fam).analyze(w, add_curves=False)
            for sec in [k for k in list(result.sections) + list(result.metadata) if k in secs]:   # the result's order
                if _summary_fields(result.metadata.get(sec)):
                    # A summary (values, not classes) has no class per zone mean: it would read "unresolved" in every
                    # zone. zone_classes gives its values per zone instead (section_summaries).
                    summaries.append((fam, sec))
                    continue
                if sec not in result.sections:
                    continue
                section = result.sections[sec]
                thresholds[sec] = section.calculation_thresholds or ""
                families[sec] = fam
                out[sec] = {z.zone_id: str(lab) for z, lab in zip(view.zones, section.raw_labels)
                            if not (lab is None or lab == "" or (isinstance(lab, float) and np.isnan(lab)))}
    return {"classes": out, "thresholds": thresholds, "summaries": summaries, "families": families}


def sample_labels(view: FormationView, family: str, section: str) -> np.ndarray:
    """Each interval sample's label in a section, from the analyzer run on each zone's samples (None outside the zones
    and where the analyzer gives none)."""
    out = np.full(np.asarray(view.depth).size, None, dtype=object)
    for z, result in zone_results(view, family):
        if section in result.sections:
            labs = np.asarray(result.sections[section].raw_labels, dtype=object)
            if labs.size == len(z.indices):
                out[z.indices] = labs
    return out


def _net_rock_status(view: FormationView) -> dict[str, str]:
    """Each zone's net-rock status by the policy shale cutoff: the NET_ROCK fraction where the workflow wrote the flag,
    else the zone-mean VCL against the cutoff."""
    vcl_max = (view.policy.get("cutoffs") or {}).get("vcl_max")
    out = {}
    for z in view.zones:
        net = view.zone_values(z, "NET_ROCK")
        vcl = view.zone_values(z, "VCL")
        v = float(np.nanmean(vcl)) if vcl is not None and np.isfinite(vcl).any() else None
        if net is not None and np.isfinite(net).any():
            out[z.zone_id] = "pass" if float(np.nanmean(net)) >= 0.5 else ("fail" + (f" (VCL {v:.2f})" if v is not None else ""))
        elif v is not None and vcl_max is not None:
            out[z.zone_id] = "pass" if v <= vcl_max else f"fail (VCL {v:.2f})"
    return out


def zone_classes(view: FormationView, topic, net_rock: bool = True) -> dict:
    """A topic's classes both ways (the summary layer's class views): each zone's class from its zone means (the
    analyzer run on zone means) and the share of its samples in each class (the analyzer run on its samples); then over
    the zones and over the whole interval. The thresholds are the workflow's analyzers'."""
    raw = zone_classes_raw(view, topic)
    background = list(view.reg.topics.get("background_classes", []))
    cols = ["zone", "lithology", f"depth ({view.depth_unit})"]
    for sec in raw["classes"]:
        cols += [f"{sec} (zone mean)", f"{sec} (samples)"]
    rows = [[z.zone_id, z.lithology, f"{fmt_depth(z.top)}–{fmt_depth(z.base)}"] for z in view.zones]
    facts, values = [], []
    pct = lambda p: fmt_pct(p, 1)
    for sec, labels in raw["classes"].items():
        lab = sample_labels(view, raw["families"][sec], sec)
        names = [str(x) for x in dict.fromkeys(lab.tolist()) if x is not None and str(x) not in background
                 and not (isinstance(x, float) and np.isnan(x)) and str(x) != ""]
        masks = {n: np.asarray([str(v) == n for v in lab.tolist()], dtype=bool) for n in names}
        cv = S.class_views(view, labels, masks, [b for b in background if b in set(map(str, lab.tolist()))],
                           fmt, pct, view.depth_unit)
        for row, (z, by_mean, text, nums) in zip(rows, cv.zones):
            row += [by_mean or "unresolved", text]
            values += [sig(v) for v in nums]
        facts.append(f"{sec} (the workflow's thresholds: {raw['thresholds'].get(sec, '')[:200]})")
        for text, nums in [v for v in (cv.pooled, cv.whole) if v]:
            facts.append(f"{sec}, {text}")
            values += [sig(v) for v in nums]
    grading = set(view.reg.topics.get("reservoir_grading", [])) & set(view.reg.resolve_topics(topic))
    status = _net_rock_status(view) if net_rock and grading and raw["classes"] else {}
    if status:                    # a class grades one property of the zone mean; the cutoffs decide reservoir rock
        cols.append("net rock (cutoffs)")
        for row, z in zip(rows, view.zones):
            row.append(status.get(z.zone_id, "no data"))
        failing = [z.zone_id for z in view.zones if status.get(z.zone_id, "").startswith("fail")]
        vcl_max = (view.policy.get("cutoffs") or {}).get("vcl_max")
        facts.append("classes grade one property; net rock (the workflow's: its NET_ROCK flag, else the policy's VCL "
                     f"cutoff {vcl_max}): " + (f"{', '.join(failing)} fail, so a high class there is not reservoir rock"
                                               if failing else "all zones pass"))
    for fam, sec in raw["summaries"]:            # summary sections: their values per zone, from each zone's samples
        for line, nums in section_summaries(view, fam, sec):
            facts.append(line)
            values.extend(nums)
    return {"title": "Classes both ways: each zone's class from its mean values and the share of its samples in each "
                     "class; then the zones pooled and the whole interval",
            "columns": cols, "rows": rows, "facts": facts, "values": values}


def formation_summary(view: FormationView, curves: list[str] = None, stats: list[str] = None) -> dict:
    """The formation in brief, on the summary layer: lithology shares of the zoned thickness and of the gross; for each
    curve and statistic (the asked ones, or the default set with the geometric mean by the curve's shape), the zones
    ranked high to low by that statistic, then the zones pooled and the whole interval; the zones in bad hole above
    the policy's confidence limit, named."""
    zones = view.zones
    total = sum(z.thickness for z in zones) or 1.0
    facts, values = [], []
    by_lith: dict[str, float] = {}
    for z in zones:
        by_lith[z.lithology] = by_lith.get(z.lithology, 0.0) + z.thickness
    facts.append("Lithology by thickness: " + "; ".join(
        f"{lith} {fmt(m)} {view.depth_unit} ({fmt_pct(100 * m / total)} of zoned, "
        f"{fmt_pct(100 * m / max(view.gross, 1e-9))} of gross)"
        for lith, m in sorted(by_lith.items(), key=lambda kv: -kv[1])))
    values += [v for m in by_lith.values() for v in (sig(m), round(100 * m / total), round(100 * m / max(view.gross, 1e-9)))]
    curves, missing = _check_curves(view, curves or ["PHIE"])
    rows = []
    bases = S.bases(view)
    for c in curves:
        x = view.values(c)
        k = S.curve_kind(view, c)
        if k.kind != "values":                                  # a flag's or class codes' shares, never their statistics
            r, v = _share_rows(view, c, k, bases)
            rows += r
            values += v
            facts.append(f"{c}: {S.kind_note(k, S.code_labels(view, c))}")
            continue
        asked = [S.statistic_name(n) for n in stats or []]
        asked = list(dict.fromkeys(n for n in asked if S.known(n) and n != "n"))
        names, log = (["n"] + asked, False) if asked else (S.names(None, x), S.log_shaped(x))
        got = {b.label or b.zone.zone_id: S.compute(x[b.idx], names, log) for b in bases}
        note = S.shape_note(x) if not stats else ""
        if note:
            facts.append(f"{c}: {note}")
        for n in names:
            zone_vals = [(z.zone_id, got[z.zone_id][n]) for z in zones if np.isfinite(got[z.zone_id][n])]
            ordered = zone_vals if n == "n" else sorted(zone_vals, key=lambda kv: -kv[1])
            cells = [f"{zid} {fmt(sig(v))}" for zid, v in ordered]
            pooled, whole = got[bases[-2].label][n], got[bases[-1].label][n]
            rows.append([c, n, ", ".join(cells) or "-", sig(pooled) if np.isfinite(pooled) else None,
                         sig(whole) if np.isfinite(whole) else None])
            values += [sig(v) for _, v in zone_vals] + [sig(v) for v in (pooled, whole) if np.isfinite(v)]
    bh_max = view.policy.get("confidence", {}).get("max_bad_hole_fraction", 0.5)
    if view.available("BAD_HOLE"):
        bh = [(z.zone_id, float(np.nanmean(view.zone_values(z, "BAD_HOLE") > 0.5))) for z in zones]
        over = [(zid, f) for zid, f in bh if f > bh_max]
        facts.append(f"zones with bad hole above {100 * bh_max:.0f}% of their samples (the policy's confidence limit): "
                     + (", ".join(f"{zid} ({fmt_pct(100 * f)})" for zid, f in over) if over else "none"))
        values += [round(100 * f) for _, f in over]
    if missing:
        facts.append(_missing_text(view, missing))
    return {"title": "Formation summary: each statistic with the zones ranked high to low (n in zone order), the zones "
                     "pooled and the whole interval",
            "columns": ["curve", "statistic", "each zone, high to low", bases[-2].label, bases[-1].label], "rows": rows,
            "facts": facts, "values": values}


def _share_rows(view: FormationView, c: str, k, bases: list) -> tuple[list, list]:
    """formation_summary's rows of a flag (the share set), class codes (the share of each class the interval holds) or
    one value (the share at it): each zone high to low, the zones pooled and the whole interval; shares of the samples
    with a value."""
    labels = S.code_labels(view, c)
    grouped = labels if k.kind == "classes" else None                              # codes named alike: one class
    here = [code for code, _ in S.class_counts(view.values(c), k.codes, grouped)[1]]  # the classes the interval holds
    codes = (1.0,) if k.kind == "flag" else here
    rows, values = [], []
    for code in codes:
        name = ("share set" if k.kind == "flag" else f"share at {S.code_text(code, labels)}" if k.kind == "one value"
                else f"share of class {S.code_text(code, labels)}")
        share = {}
        for b in bases:
            n, counts = S.class_counts(view.values(c)[b.idx], k.codes, grouped)
            share[b.label or b.zone.zone_id] = round(100 * dict(counts).get(code, 0) / n, 1) if n else None
        zone_vals = sorted(((z.zone_id, share[z.zone_id]) for z in view.zones if share[z.zone_id] is not None),
                           key=lambda kv: -kv[1])
        pooled, whole = share[bases[-2].label], share[bases[-1].label]
        rows.append([c, name, ", ".join(f"{zid} {v}%" for zid, v in zone_vals) or "-",
                     f"{pooled}%" if pooled is not None else None, f"{whole}%" if whole is not None else None])
        values += [v for _, v in zone_vals] + [v for v in (pooled, whole) if v is not None]
    return rows, values


def _supplied_reference(view: FormationView, core: str, logs: list) -> Optional[str]:
    """The core-corrected curve the LAS supplies in place of a plug curve with no samples here (the registry's
    core_substitution pair among the curve's log pairs, card.curve_origin "supplied"), or None."""
    from petroharness.record.card import curve_origin
    for log, corrected in view.reg.expansion["core_substitution"]["pairs"].items():
        if corrected in logs and log in logs and view.available(corrected) and curve_origin(view, corrected) == ("supplied",):
            return corrected
    return None


def _against_reference(view: FormationView, ref: str, logs: list, tolerance: float) -> tuple[list, list]:
    """Each log curve against the reference in each zone, the zones pooled and the whole interval: n, mean difference
    (log - reference), its spread, and the share of samples beyond the tolerance; a curve holding the reference's
    values is named as such."""
    from petroharness.record.card import curve_origin
    facts, values = [], []
    r = view.values(ref)
    for lc in logs:
        ld = view.values(lc)
        if lc == ref or ld is None or not np.isfinite(ld).any():
            continue
        if (curve_origin(view, lc) or ("",))[0] == "copy":
            facts.append(f"{lc}: the same values as {ref} (no separate log estimate to compare)")
            continue
        rows = []
        for b in S.bases(view):
            a, c = ld[b.idx], r[b.idx]
            ok = np.isfinite(a) & np.isfinite(c)
            if ok.sum() < 3:
                continue
            d = a[ok] - c[ok]
            share = 100.0 * float(np.mean(np.abs(d) > tolerance))
            head = f"{b.zone.zone_id} {b.zone.lithology}" if b.zone is not None else b.label
            rows.append(f"{head} n={int(ok.sum())} {fmt(np.mean(c[ok]))} vs {fmt(np.mean(a[ok]))}, "
                        f"difference mean {fmt(np.mean(d))} sd {fmt(np.std(d))}, beyond {fmt(tolerance)} in {fmt_pct(share)}")
            values += [sig(np.mean(c[ok])), sig(np.mean(a[ok])), sig(np.mean(d)), sig(np.std(d)), int(ok.sum())]
        if rows:
            facts.append(f"{lc} against {ref} by zone, then the zones pooled and the whole interval ({ref} mean vs {lc} "
                         f"mean): " + "; ".join(rows))
    return facts, values


def core_vs_log(view: FormationView) -> dict:
    """Core plug statistics against the log values at the core depths, in each zone with core samples, the zones pooled
    and the whole interval (one row each, the core curve then each log at the core depths): the summary layer's default
    statistics, with the geometric mean added by the shape of the core values (positive values spanning more than two
    orders of magnitude), not by the curve's name. A core fraction stored in percent (core analyses report saturations
    either way) is converted to the log curve's unit first, so SWC 45 and SW 0.45 read as the same saturation. Where a
    plug curve has no samples here but the LAS supplies its core-corrected substitute (e.g. PHIE_CC for core porosity),
    that curve is the core reference: each log curve is compared with it (rules/curves.yaml
    core.reference_tolerance)."""
    facts, values, rows = [], [], []
    core_cfg = view.reg.curves["core"]
    cols = [n for n in S.DEFAULT[:3]] + ["geo_mean"] + list(S.DEFAULT[3:])
    for core, logs in core_cfg["log_pairs"].items():
        cd = view.values(core)
        if cd is None or not np.isfinite(cd).any():
            ref = _supplied_reference(view, core, logs)
            if ref is None:
                facts.append(f"{core}: no core samples in the interval")
                continue
            extra = [c for c in (core_cfg.get("reference_logs") or {}).get(core, []) if c not in logs]
            facts.append(f"{core}: no core plug samples in the interval; {ref}, the core-corrected curve the LAS "
                         f"supplies, is the core reference")
            f, v = _against_reference(view, ref, list(logs) + extra, float((core_cfg.get("reference_tolerance") or {}).get(core, 0)))
            facts += f
            values += v
            continue
        converted = ""
        if view.in_percent(core) and not any("%" in view.unit(lc) for lc in logs if view.available(lc)):
            from petrophys.model.units import core_saturation_to_fraction
            cd, _ = core_saturation_to_fraction(cd, view.unit(core), mnemonic=core, source_unit="%")
            unit = next((view.unit(lc) for lc in logs if view.available(lc) and view.unit(lc)), "v/v")
            converted = f" (core values in %, converted to {unit})"
        sel = np.isfinite(cd)
        names, log = S.names(None, cd[sel]), S.log_shaped(cd[sel])
        note = S.shape_note(cd[sel])
        facts.append(f"{core}{converted}: core statistics and the logs at the core depths" + (f"; {note}" if note else ""))
        for b in S.bases(view):
            here = sel[b.idx]
            if b.zone is not None and not here.any():
                continue
            where = b.zone.zone_id if b.zone is not None else b.label
            for c, x in [(core, cd)] + [(lc, view.values(lc)) for lc in logs]:
                if x is None or not np.isfinite(np.asarray(x, dtype=float)[b.idx][here]).any():
                    continue
                got = S.compute(np.asarray(x, dtype=float)[b.idx][here], names, log)
                cells = [(int(got[n]) if n == "n" else sig(got[n])) if n in names and np.isfinite(got[n]) else "-"
                         for n in cols]
                rows.append([core, where, c if c == core else f"{c} at core depths"] + cells)
                values += [v for v in cells if isinstance(v, (int, float))]
    facts.append("PHIE_CC/PERM_CC " + ("available (same-well core calibration)" if view.available("PHIE_CC")
                                       else "not available"))
    values.append(S.outside(view))
    return {"title": "Core vs log comparison: each zone with core samples, the zones pooled and the whole interval",
            "columns": ["core curve", "where", "curve"] + cols if rows else [], "rows": rows, "facts": facts,
            "values": values}


# A step's record lines describe the whole well's run; they are shown as written, under one label, and the interval's
# own facts come from the step's output curves (interval_facts), not from rewriting the lines.
RECORD_LABEL = "record (the whole well's run; its counts are the well's)"


def interval_facts(view: FormationView, outputs) -> tuple[list[str], list[float]]:
    """What a step's output curves hold in this interval, read from the curves: each flag's samples set here (and
    their thickness); the range here of a step's one curve of values (a temperature, an Rw: the record's is the whole
    well's); an output with values at only part of the interval's samples; and, where the analyzers filled
    an output the step left empty (the view's values against its own_values), the step's samples and the analyzers'
    apart: the record may say the step did not compute a curve the interval holds. (lines, their numbers)."""
    from petroharness.well.summary import curve_kind
    n_all, step, unit = int(view.mask.sum()), float(view.step), view.depth_unit
    lines, nums = [], []
    outs = [str(o) for o in dict.fromkeys(outputs or ()) if view.available(str(o))]
    values = [c for c in outs if curve_kind(view, c).kind == "values"]
    if len(values) == 1:                               # a step that writes one curve of values (a temperature, an
        c = values[0]                                  #   Rw): its range here, as a flag gives its count (question
        x = np.asarray(view.values(c), dtype=float)    #   suite X06: the record's range is the whole well's)
        if np.isfinite(x).any():
            lo, hi, u = float(np.nanmin(x)), float(np.nanmax(x)), (view.unit(c) or "").strip()
            lines.append(f"{c} from {fmt(sig(lo))} to {fmt(sig(hi))}{' ' + u if u else ''}")
            nums += [sig(lo), sig(hi)]
    for c in dict.fromkeys(str(o) for o in outputs or ()):
        if not view.available(c):
            continue
        x = np.asarray(view.values(c), dtype=float)
        have = int(np.isfinite(x).sum())
        own = view.own_values(c)
        k = have if own is None else int(np.isfinite(np.asarray(own, dtype=float)).sum())
        added = f" ({k} from the step; the analyzers add {have - k} where the step left it empty)" if have > k else ""
        if curve_kind(view, c).kind == "flag":         # by the shape of its values, as every tool reads it
            n = int(np.nansum(x > 0.5))
            lines.append(f"{c} set at {n} of {have} samples ({fmt(n * step)} {unit})" + added)
            nums += [n, have, sig(n * step)] + ([k, have - k] if added else [])
        elif 0 < have < n_all or added:
            lines.append(f"{c} has values at {have} of {n_all} samples" + added)
            nums += [have, n_all] + ([k, have - k] if added else [])
    return lines, nums


_SXO_ROUTE_TEXT = {"quicklook": "the quicklook transform of SW", "measured": "from measured shallow resistivity",
                   "mixed": "from measured shallow resistivity where valid, the quicklook transform of SW elsewhere"}


def provenance(view: FormationView, topics: list[str]) -> dict:
    """How the workflow of record computed a quantity: each step's method and its first decisions, scoped to the
    interval's own facts from its curves (interval_facts), plus the routes read from this interval's curves where the record describes the
    whole well (which resistivity pair INVASION_RATIO uses, how SXO was obtained)."""
    facts, values = [], []
    table, aliases = view.reg.topics["provenance"], view.reg.topics.get("provenance_aliases", {})
    asked = ([topics] if isinstance(topics, str) else topics) or ["rw"]           # a single topic may come as a string
    unknown = [t for t in asked if table.get(aliases.get(str(t).lower(), str(t).lower())) is None]
    if len(unknown) == len(asked):
        raise EvidenceError(f"WHAT: unknown topic {unknown[0]!r}. FIX: use any of {sorted(table)}.")
    for topic in [t for t in asked if t not in unknown]:         # the known topics run; the unknown ones are named below
        steps = table.get(aliases.get(topic.lower(), topic.lower()))
        for s in steps:
            st = view.prep.steps.get(s) or {}
            if not st:
                continue
            said = [d for d in (st.get("decisions") or []) if isinstance(d, str)][:4]
            decisions = [f"{RECORD_LABEL}: " + "; ".join(said)] if said else []     # whole: a verdict's alternatives
            here, nums = interval_facts(view, st.get("outputs") or [])                #   are its end
            if here:
                decisions.append("in this interval: " + "; ".join(here))
                values += nums
            if s == "invasion" and invasion_route(view):
                decisions.append(f"in this interval INVASION_RATIO = {invasion_route(view)}")
            if s in ("mhi", "saturation") and sxo_route(view) in _SXO_ROUTE_TEXT:
                decisions.append(f"in this interval SXO is {_SXO_ROUTE_TEXT[sxo_route(view)]}")
            if s == "porosity":
                from petroharness.record.card import porosity_parameters
                params = porosity_parameters(st, [z.lithology for z in view.zones])
                if params:
                    decisions.append(params)
            facts.append(f"{s}: method={st.get('method')}; " + " | ".join(decisions))
    if unknown:
        facts.append(f"unknown topics left out: {', '.join(map(str, unknown))} (topics: {', '.join(sorted(table))})")
    return {"title": "How the workflow of record computed it", "facts": facts, "values": values}


def depth_trend(view: FormationView, curves: list[str]) -> dict:
    curves, _ = _check_curves(view, curves)
    res = zone_stats(view, curves, ["mean"])
    facts = []
    mids = np.array([(z.top + z.base) / 2 for z in view.zones])
    for j, c in enumerate(curves):
        ys = np.array([r[3 + j] for r in res["rows"]], dtype=float)
        ok = np.flatnonzero(np.isfinite(ys))
        if ok.size >= 3:
            hi, lo = ok[np.argmax(ys[ok])], ok[np.argmin(ys[ok])]
            slope10 = 10 * np.polyfit(mids[ok], ys[ok], 1)[0]
            facts.append(f"{c}: top zone {view.zones[ok[0]].zone_id} {fmt(ys[ok[0]])}, bottom zone "
                         f"{view.zones[ok[-1]].zone_id} {fmt(ys[ok[-1]])}; highest {view.zones[hi].zone_id} {fmt(ys[hi])}, "
                         f"lowest {view.zones[lo].zone_id} {fmt(ys[lo])}; linear trend {fmt(slope10)} per 10 {view.depth_unit} of depth "
                         f"({'increasing' if slope10 > 0 else 'decreasing'} downward, i.e. {'decreasing' if slope10 > 0 else 'increasing'} upward)")
    res["title"] = f"Top-down zone means of {', '.join(curves)}"
    res["facts"] = facts
    return res



# Measured logs a completeness record lists per zone (the primary logs of petrophys' completeness list that are
# measured, not computed by the workflow)
_COMPLETENESS_COMPUTED = {"TEMP", "RMF", "RW"}
# derived curves the numerical analyzer builds from shear sonic (its methodology: Vs = 304800 / DTS)
_SHEAR_BASED = ("POISSON_RATIO", "YOUNG_MOD", "BRITTLENESS_INDEX", "SH_MIN", "VP_VS_RATIO")


def data_record(view: FormationView) -> dict:
    """The workflow's data-completeness record per lithology zone, as the group files of the workflow of record state
    it (petrophys reference_export): the primary logs missing from the well (PRIMARY_LOGS_FOR_COMPLETENESS against the
    input curves, the record's display names); per zone, the lithology labels' validity (_build_reference_lithology_info
    on the zone's samples: valid, NaN and sentinel counts), each measured log's share of samples with a value and its
    gaps, and the derived curves with no value in the zone with the inputs the step record builds them from."""
    from petrophys.reporting.reference_export import (CORE_ONLY_CONTEXT_CURVES, PRIMARY_LOGS_FOR_COMPLETENESS,
                                                      _build_reference_lithology_info, _canonical_delivery_curve_name,
                                                      _display_curve_name)
    inputs = {str(c).upper() for c in view.prep.input_curves}
    missing = [_display_curve_name(n) for n in PRIMARY_LOGS_FOR_COMPLETENESS
               if _canonical_delivery_curve_name(n) not in CORE_ONLY_CONTEXT_CURVES and n.upper() not in inputs]
    measured = [n for n in PRIMARY_LOGS_FOR_COMPLETENESS if n.upper() in inputs and n.upper() not in _COMPLETENESS_COMPUTED
                and view.available(n) and _canonical_delivery_curve_name(n) not in CORE_ONLY_CONTEXT_CURVES
                and n.upper() != str(view.lithology_curve or "").upper()]
    from petrophys.reporting.reference_export import (CATEGORY_CONTEXT_SPECS, CONTEXT_NOTE_OMIT_CURVES,
                                                      _derived_status_target_list)
    graph, _ = construction(view)
    graph = {**{c: ["DTS"] for c in _SHEAR_BASED}, **{"ACOUSTIC_IMPEDANCE": ["RHOB", "DTC"]}, **graph}
    # the record's own list: petrophys' derived-log targets with the numerical category's, in its order
    targets = _derived_status_target_list(extra_targets=sorted(CATEGORY_CONTEXT_SPECS["numerical"]["targets"]))
    derived = [c for c in targets if c.upper() not in inputs and c not in CONTEXT_NOTE_OMIT_CURVES
               and not (c == "LITHO" and view.lithology_curve)]     # the computed lithology is a fallback for no log
    facts = [f"primary logs missing from the well: {', '.join(missing) if missing else 'none'}"]
    if view.analyzer_curves:
        analyzer = view.analyzer_curves
    else:
        from petroharness.record.sections import analyzer_sections
        analyzer = analyzer_sections(view)[1].new           # the analyzers' derived curves, over the well's samples
    rows, values = [], []
    for z in view.zones:
        li = _build_reference_lithology_info(view.zone_well(z))
        n = len(z.indices)
        cover, gaps = [], []
        for c in measured:
            x = view.zone_values(z, c)
            ok = np.isfinite(x) if x is not None else np.zeros(n, dtype=bool)
            share = 100.0 * ok.mean() if n else 0.0
            cover.append(f"{c} {fmt_pct(share, 0)}")
            if 0 < ok.sum() < n:
                runs = _runs(view.depth[z.indices], (~ok).astype(float), view.step)
                gaps.append(f"{c} {', '.join(f'{fmt_depth(a)}-{fmt_depth(b)}' for a, b in runs[:3])}"
                            + (f" (+{len(runs) - 3})" if len(runs) > 3 else ""))
            elif not ok.any():
                gaps.append(f"{c} no value")
        empty = []
        for c in derived:
            x = view.zone_values(z, c) if view.available(c) else None
            if x is None and c in analyzer:                # an analyzer curve before the store has added it to the view
                x = np.asarray(analyzer[c][0], dtype=float)[np.flatnonzero(view.mask)][z.indices]
            if x is None or not np.isfinite(x).any():
                ins = [i for i in graph.get(c, []) if not (view.zone_values(z, i) is not None and np.isfinite(view.zone_values(z, i)).any())]
                empty.append(c + (f" (no {', '.join(ins)})" if ins else ""))
        rows.append([z.zone_id, z.lithology, f"{fmt_depth(z.top)}–{fmt_depth(z.base)}", n,
                     f"{li.get('valid_lithology_count', 0)}/{li.get('total_rows', n)} ({fmt_pct(li.get('valid_lithology_percentage', 0.0), 1)}); "
                     f"NaN {li.get('nan_count', 0)}, sentinel {li.get('sentinel_count', 0)}",
                     "; ".join(cover), "; ".join(gaps) or "none", ", ".join(empty) or "none"])
        values += [n, li.get("valid_lithology_count", 0), li.get("nan_count", 0), li.get("sentinel_count", 0)]
    return {"title": "Data-completeness record per lithology zone (the workflow's group record)",
            "columns": ["zone", "lithology", f"depth ({view.depth_unit})", "samples", "lithology labels valid", "measured logs with a value",
                        "gaps in measured logs", "derived curves with no value"],
            "rows": rows, "facts": facts, "values": values}

def unit_roles(view: FormationView) -> dict:
    """The workflow's flow roles (Petrophys flow_roles), as it gives them: zones ranked by mean permeability
    (core-calibrated where available), the highest given the role 'strongest'; the largest permeability-thickness as
    flow capacity; a zone a possible baffle when shale-dominated (seal flag), poor (at or below the policy's poor
    permeability) or decades below the 'strongest' zone. Qualifiers, not roles: bad hole above the confidence limit,
    permeability held at the model limit, a zone failing the shale cutoff with good modelled permeability, and SW above
    the cutoff. Every threshold is the policy's (flow_roles, cutoffs, confidence), named with its value."""
    pol = view.policy
    cut, conf, fr = pol.get("cutoffs") or {}, pol.get("confidence") or {}, pol.get("flow_roles") or {}
    sw_max, vcl_max = cut.get("sw_max"), cut.get("vcl_max")
    max_bh = conf.get("max_bad_hole_fraction", 0.5)
    good_k, poor_k = fr.get("good_perm_md", 10.0), fr.get("poor_perm_md", 1.0)
    decades, seal_frac = fr.get("baffle_decades_below_strongest", 2.0), fr.get("seal_fraction", 0.5)
    kc = "PERM_CC" if view.available("PERM_CC") else "PERM"
    bound = view.at_bound(kc)
    from petrophys.evaluation.flow_units import flow_roles

    def mean(z, c):
        v = _stat(view.zone_values(z, c), "mean") if view.zone_values(z, c) is not None else float("nan")
        return v if np.isfinite(v) else None

    info = []
    for z in view.zones:
        info.append({"z": z, "k": mean(z, kc), "sw": mean(z, "SW"), "vcl": mean(z, "VCL"), "bh": mean(z, "BAD_HOLE"),
                     "seal": mean(z, "SEALFLAG"), "clip": bool(bound.size) and float(bound[z.indices].mean()) > 0.5})
    roles = flow_roles([i["k"] for i in info], [i["z"].thickness for i in info],              # petrophys
                       sw=[i["sw"] for i in info], vcl=[i["vcl"] for i in info], bad_hole=[i["bh"] for i in info],
                       seal=[i["seal"] for i in info], at_limit=[i["clip"] for i in info], good_perm=good_k,
                       poor_perm=poor_k, baffle_decades=decades, seal_fraction=seal_frac, sw_max=sw_max,
                       vcl_max=vcl_max, max_bad_hole_fraction=max_bh)
    strongest = info[roles["strongest"]] if roles["strongest"] is not None else None
    capacity = info[roles["capacity"]] if roles["capacity"] is not None else None
    say = {"bad_hole": lambda v: f"bad hole {100 * v:.0f}%: low confidence", "at_model_limit": lambda v: f"{kc} at the model limit: a bound",
           "shaly": lambda v: f"shaly (VCL {v:.2f}): the well's SWIRR comes from cleaner rock, so modelled {kc} is less certain", "water_bearing": lambda v: "water-bearing"}
    role_text = {"strongest": "strongest", "baffle": "possible baffle", "flow": "flow interval",
                 None: f"no role (no {kc} value in the zone)"}         # Petrophys flow_roles: None without a permeability
    conservative = []
    for i, r in zip(info, roles["zones"]):
        quals = [say[code](v) for code, v in r["qualifiers"]]
        i["kh"], i["role"], i["quals"] = r["kh"], role_text[r["role"]], quals
        for q in quals:
            if not q.startswith("water"):
                key = q.split(" (")[0] if q.startswith("shaly") else q.split(":")[0].rstrip("0123456789% ").strip()
                conservative.append((key, i["z"].zone_id))
    rows, facts, values = [], [], []
    for i in info:
        z = i["z"]
        rows.append([z.zone_id, sig(z.thickness), sig(i["k"]) if i["k"] is not None else None,
                     sig(i["kh"]) if i["kh"] is not None else None,
                     i["role"] + (f" ({'; '.join(i['quals'])})" if i["quals"] else "")])
        values += [v for v in (i["k"], i["kh"]) if v is not None]
    facts.append(f"roles as the workflow assigns them (Petrophys flow_roles on each zone's mean {kc}, with the policy's "
                 f"thresholds: good {good_k:g} mD, poor {poor_k:g} mD, baffle {decades:g} decades below the 'strongest' "
                 f"zone, seal fraction {seal_frac:g}); the workflow's ranking, by the zone mean")
    if strongest:
        z = strongest["z"]
        facts.append(f"the workflow's 'strongest' role: {z.zone_id} {z.lithology} "
                     f"{fmt_depth(z.top)}–{fmt_depth(z.base)} {view.depth_unit}, {kc} {fmt(strongest['k'])} mD"
                     + (f", VCL {fmt(strongest['vcl'])}" if strongest["vcl"] is not None else "")
                     + (f", SW {fmt(strongest['sw'])}" if strongest["sw"] is not None else "")
                     + (f"; {'; '.join(strongest['quals'])}" if strongest["quals"] else ""))
    if capacity and capacity is not strongest:
        z = capacity["z"]
        facts.append(f"the workflow's largest flow capacity (mean {kc} x thickness): {z.zone_id} ({fmt(capacity['kh'])} "
                     f"mD*{view.depth_unit} over {fmt(z.thickness)} {view.depth_unit})")
    baffles = [i["z"].zone_id for i in info if i["role"] == "possible baffle"]
    facts.append("possible baffles: " + (", ".join(baffles) if baffles else "none by these criteria")
                 + f" (the workflow's: shale-dominated, {kc} at or below {poor_k:g} mD, or {decades:g} decades below the "
                   f"'strongest' zone)")
    if conservative:                              # grouped by reason: one line, not a qualifier per zone
        reasons = {"bad hole": f"bad hole above {100 * max_bh:.0f}% (low confidence)",
                   f"{kc} at the model limit": f"{kc} at the model limit (a bound)",
                   "shaly": f"shaly with good modelled {kc} (less certain: the well's SWIRR comes from cleaner rock)"}
        groups: dict[str, list[str]] = {}
        for key, zid in conservative:
            groups.setdefault(key, []).append(zid)
        facts.append("intervals requiring conservative interpretation: " + "; ".join(
            f"{reasons.get(k, k)}: {_zone_list(view, ids)}" for k, ids in groups.items()))
    facts.append("roles are log-indicated, from mean permeability and the policy thresholds")
    return {"title": f"The workflow's flow roles by permeability ({kc}): 'strongest', flow capacity, possible baffles",
            "columns": ["zone", f"thickness ({view.depth_unit})", f"mean {kc} (mD)", f"k*h (mD*{view.depth_unit})",
                        "role (the workflow's)"],
            "rows": rows, "facts": facts, "values": values}


def _plain(label: str) -> str:
    """A library class label in plain words (references write labels as words, not tokens)."""
    return label.replace("_", " ").lower()


def flagged_runs(view: FormationView, topics=None, flags=None) -> dict:
    """Where the analyzers flag something: for each non-background class of the given topics and each
    flag curve, every run inside the zones with depth, thickness and zone, the run count, the summed thickness and the
    largest continuous run. Rows are summaries for the writer; `runs` holds every run for the code-composed block
    (writer.render_flag_block). Background classes (registry topics.yaml background_classes) are left out."""
    background = set(view.reg.topics.get("background_classes", []))
    zone_of = lambda a, b: next((z.zone_id for z in view.zones if z.top - 0.06 <= (a + b) / 2 <= z.base + 0.06), "-")
    groups = []                                   # (section, label, [(a, b, zone)])
    for name in view.reg.resolve_topics(topics or []):
        for fam, secs in view.reg.topics["topics"][name]:
            merged, _ = classify_raw(view, fam, secs)
            for sec, classes in merged.items():
                for label, items in classes.items():
                    if label in background:
                        continue
                    runs = sorted({(a, b, zid) for zid, a, b in items})
                    if runs:
                        groups.append((sec, label, runs))
    for flag in [str(f).upper() for f in (flags or [])]:
        data = view.values(flag)
        if not view.is_flag(flag) or data is None or not np.isfinite(data).any():
            continue
        runs = []
        for z in view.zones:
            idx = z.indices
            runs += [(a, b, z.zone_id) for a, b in _runs(view.depth[idx], data[idx], view.step)]
        if runs:
            groups.append(("flag", flag, sorted(runs)))
    rows, facts, values, full = [], [], [], []
    seen = set()
    for sec, label, runs in groups:
        key = (label, tuple(runs))
        if key in seen:                                   # the same class reached through two topics
            continue
        seen.add(key)
        thick = [(b - a + view.step, a, b, zid) for a, b, zid in runs]
        total = sum(t for t, *_ in thick)
        big = max(thick)
        zones = sorted({zid for *_, zid in thick if zid != "-"}, key=lambda z: [v.zone_id for v in view.zones].index(z))
        name = _plain(label) if sec != "flag" else f"{label} flag"
        rows.append([name, len(runs), sig(total), f"{fmt_depth(big[1])}–{fmt_depth(big[2])} {view.depth_unit} ({fmt(big[0])} {view.depth_unit}, {big[3]})",
                     _zone_list(view, zones) if zones else "-"])
        full.append({"class": name, "section": sec.replace("_", " "), "runs": [(a, b, t, zid) for t, a, b, zid in thick],
                     "total": total, "largest": big})
        values += [total, big[0], big[1], big[2]] + [v for t, a, b, _ in thick for v in (a, b, t)]
    if not rows:
        facts.append("no flagged class or flag runs in the lithology zones for these topics")
    return {"title": "Flagged intervals (log-indicated screening classes and flags; every run listed in the answer block)",
            "columns": ["class or flag", "runs", f"total ({view.depth_unit})", "largest continuous run", "zones"],
            "rows": rows, "facts": facts, "values": values, "runs": full}


CATALOG: dict[str, Callable[..., dict]] = {
    "zone_stats": zone_stats, "lithology_stats": lithology_stats, "interval_stats": interval_stats, "flag_intervals": flag_intervals,
    "pay_summary": pay_summary, "classify": classify, "zone_classes": zone_classes,
    "formation_summary": formation_summary, "core_vs_log": core_vs_log,
    "provenance": provenance, "depth_trend": depth_trend, "correlation": correlation,
    "threshold_exceedance": threshold_exceedance, "zone_relation": zone_relation, "spike_flags": spike_flags,
    "adjacent_jumps": adjacent_jumps, "vertical_sequence": vertical_sequence, "curve_order": curve_order,
    "zone_contrast": zone_contrast, "unit_roles": unit_roles, "flagged_runs": flagged_runs, "data_record": data_record,
}


