"""The one summary layer (docs/DESIGN.md, G6): every tool that summarises a curve takes its bases, statistics,
rankings, thresholds and class views from here, so that no tool picks a convention of its own.

- Where: each zone, the zones pooled, the whole interval (with the count of samples outside any zone); always all
  three, in that order, each labelled with what it covers.
- Which statistics: the ones asked for; when none are named, the default set (n of N, mean, median, P10, P90, min,
  max). The shape of the data, never the curve's name, adds one statistic: positive values spanning more than two
  orders of magnitude also get the geometric mean, and their percentiles are read on log10 values.
- Rankings: zones ranked by each statistic shown, side by side; no ranking is called the best.
- Thresholds: the threshold used and where it came from (the workflow's, with its rule, or the model's).
- Class views: the class each zone takes from its mean and the share of samples in each class, per zone and overall.
- What the values are, by their shape over all the curve's samples, never by its name: whole numbers that are 0
  or 1 are a flag (the share set); a few distinct whole numbers are class codes (the share of each class, never a
  mean or a range of codes); one whole number only is that value; anything else is values (the statistics above).

The statistics are Petrophys's (petroharness.well.stats, curve_statistics)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from petroharness.well.stats import statistics as library_statistics

DEFAULT = ("n", "mean", "median", "p10", "p90", "min", "max")
SHAPE_DECADES = 2.0                 # positive values spanning more than this many orders of magnitude: log-shaped
_LIBRARY = {"mean": "mean", "median": "median", "min": "min", "max": "max", "std": "std", "geo_mean": "geometric_mean",
            "variance": "var", "harmonic_mean": "harmonic_mean", "mode": "mode"}
# every statistic the layer computes from the samples (and any percentile pNN)
STATISTICS = ("n", "mean", "median", "geo_mean", "harmonic_mean", "mode", "min", "max", "range", "std", "variance",
              "cv", "iqr")
# the usual names of the statistics, as a caller may write them
ALIASES = {"count": "n", "average": "mean", "avg": "mean", "arithmetic_mean": "mean", "geometric_mean": "geo_mean",
           "geomean": "geo_mean", "gmean": "geo_mean", "harmonic": "harmonic_mean", "hmean": "harmonic_mean",
           "minimum": "min", "maximum": "max", "sd": "std", "stdev": "std", "stddev": "std", "std_dev": "std",
           "standard_deviation": "std", "var": "variance", "coefficient_of_variation": "cv", "cov": "cv",
           "interquartile_range": "iqr", "p50": "median", "percentile_50": "median"}
# how a statistic the layer does not compute follows from those it does (shown with the calc action)
DERIVATIONS = {"sum": "n * mean", "standard_error": "std / sqrt(n)", "sem": "std / sqrt(n)",
               "midrange": "(min + max) / 2", "semi_iqr": "iqr / 2", "p0": "min", "p100": "max"}


def statistic_name(name) -> str:
    """A statistic's name as the layer writes it: lower case, its usual names read ('standard deviation' is std,
    'var' variance, 'percentile 25' p25)."""
    import re
    t = re.sub(r"[\s-]+", "_", str(name).strip().lower())
    t = ALIASES.get(t, t)
    m = re.fullmatch(r"p(?:ercentile)?_?(\d{1,3})", t)
    return f"p{int(m.group(1))}" if m else t


def known(name) -> bool:
    """Whether the layer computes the statistic (any percentile p1-p99 included)."""
    return name in STATISTICS or _percentile(name) is not None


def derivation(name: str) -> str:
    """The line for a statistic the layer does not compute: what it computes, and how one that follows from those is
    computed with calc (a statistic not computed here is not missing from the record)."""
    how = DERIVATIONS.get(statistic_name(name))
    head = f"no statistic {name!r} in this tool (it computes {', '.join(STATISTICS)} and any percentile p1-p99)"
    if how:
        return f"{head}: {name} = {how}; compute it with calc from the values shown"
    return (f"{head}; one that follows from these is computed with calc from the values shown (e.g. sum = n * mean, "
            f"standard error = std / sqrt(n)); one that needs the samples themselves is not offered here, which does "
            f"not make it missing from the record")


# --- which statistics ------------------------------------------------------------------------------------------------

def decades(x) -> Optional[float]:
    """How many orders of magnitude a curve's values span (log10 of max / min), when every finite value is positive;
    None otherwise (a value at or below 0, or fewer than two values)."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 2 or not np.all(x > 0):
        return None
    return float(np.log10(x.max() / x.min()))


def log_shaped(x) -> bool:
    """Positive values spanning more than SHAPE_DECADES orders of magnitude (the data's shape, whatever the curve)."""
    d = decades(x)
    return d is not None and d > SHAPE_DECADES


def names(asked, x) -> list:
    """The statistics to show for a curve with values x: the asked ones (n first), or the default set, with the
    geometric mean after the median when x is log-shaped."""
    if asked:
        return ["n"] + [s for s in dict.fromkeys(asked) if s != "n"]
    out = list(DEFAULT)
    if log_shaped(x):
        out.insert(out.index("median") + 1, "geo_mean")
    return out


def shape_note(x) -> str:
    """The label that says a curve is log-shaped and what that changes (empty when it is not)."""
    d = decades(x)
    if d is None or d <= SHAPE_DECADES:
        return ""
    return (f"positive values spanning {d:.1f} orders of magnitude: the geometric mean is added and the percentiles "
            "are read on log10 values")


def compute(x, wanted, log: bool = False) -> dict:
    """{name: value} of the finite samples of x (Petrophys curve_statistics): any of STATISTICS and any percentile
    pNN; cv, range and iqr from the library's std / mean, max - min and p75 - p25; on a log-shaped curve (log) the
    percentiles (and iqr) are interpolated on log10 values. The geometric and harmonic means are shown only where every
    value is positive. NaN where a statistic has no value."""
    bad = [w for w in wanted if not known(w)]
    if bad:
        raise ValueError(f"no statistic {bad[0]!r}")
    x = np.asarray(x, dtype=float)
    fin = x[np.isfinite(x)]
    out = {w: float("nan") for w in wanted}
    if "n" in out:
        out["n"] = float(fin.size)
    if not fin.size:
        return out
    need = list(dict.fromkeys(list(wanted) + [w for d in wanted for w in {"cv": ("std", "mean"), "range": ("min", "max"),
                                                                           "iqr": ("p25", "p75")}.get(d, ())]))
    pct = sorted({_percentile(w) for w in need if _percentile(w) is not None})
    in_log = bool(log and pct and np.all(fin > 0))
    s = library_statistics(fin, list(dict.fromkeys(_LIBRARY[w] for w in need if w in _LIBRARY))
                           + ([] if in_log else [f"p{p}" for p in pct if f"p{p}" in _PCT]))
    for w in need:
        if w in _LIBRARY:
            s[w] = float(s.get(_LIBRARY[w], np.nan))
    for w in wanted:
        if w in _LIBRARY:
            out[w] = s[w]
    for w in ("geo_mean", "harmonic_mean"):
        if w in out and not np.all(fin > 0):
            out[w] = float("nan")
    rest = [p for p in pct if in_log or f"p{p}" not in _PCT]
    if rest:
        from petrophys.evaluation.summaries import curve_statistics, percentile_key
        t = curve_statistics(np.log10(fin) if in_log else fin, percentiles=rest)
        for p in rest:
            s[f"p{p}"] = float(10 ** t[percentile_key(p)]) if in_log else float(t[percentile_key(p)])
    for w in wanted:
        if _percentile(w) is not None:
            out[w] = float(s[f"p{_percentile(w)}"])
    if "cv" in out:
        out["cv"] = float(s["std"] / s["mean"]) if s["mean"] != 0 and np.isfinite(s["mean"]) else float("nan")
    if "range" in out:
        out["range"] = float(s["max"] - s["min"])
    if "iqr" in out:
        out["iqr"] = float(s["p75"] - s["p25"])
    return out


_PCT = ("p10", "p25", "p75", "p90")          # the percentiles petroharness.well.stats names


# --- what the values are --------------------------------------------------------------------------------------------

CLASS_MAX = 30           # class codes: at most this many distinct whole numbers,
CLASS_SHARE = 0.05       #   and fewer than this share of the curve's samples


@dataclass(frozen=True)
class Kind:
    """What a curve's values are: "values" (statistics), "flag" (0 and 1: the share set), "classes" (whole-number
    codes: the share of each), "one value" (a single whole number); codes: its distinct values, in order."""
    kind: str
    codes: tuple = ()


def kind_of(x) -> Kind:
    """The kind of a curve from its finite values: whole numbers only, either 0 and 1 (a flag, whatever its count), or
    2 to CLASS_MAX distinct values that are fewer than CLASS_SHARE of the samples (class codes), or one value; else
    values (a measured or computed quantity, whatever its name)."""
    x = np.asarray(x, dtype=float)
    fin = x[np.isfinite(x)]
    if not fin.size or not np.all(fin == np.round(fin)):
        return Kind("values")
    codes = tuple(float(c) for c in np.unique(fin))
    if len(codes) == 1:
        return Kind("one value", codes)
    if codes == (0.0, 1.0):
        return Kind("flag", codes)
    if len(codes) <= CLASS_MAX and len(codes) < CLASS_SHARE * fin.size:
        return Kind("classes", codes)
    return Kind("values")


def curve_kind(view, c: str) -> Kind:
    """The kind of curve c, read on its values over all the well's samples (view.well_values), so that every interval
    of the well reads the curve alike; once per view and curve."""
    cache = view.__dict__.setdefault("_kinds", {})
    if c not in cache:
        x = view.well_values(c)
        cache[c] = kind_of(x) if x is not None else Kind("values")
    return cache[c]


def code_labels(view, c: str) -> dict:
    """{code: label} where the record maps a curve's codes to labels: the lithology log, by the code table the zones
    are read with (the data's nomenclature); any other class curve by the labels Petrophys keeps with it, in the one
    field its own analyzer and log viewer read (metadata.custom["category_labels"]: LITHO, LITHO_CLASS,
    NET_EXCLUSION); {} for a curve without them, whose codes are shown as they are."""
    table = getattr(view, "code_table", None) or {}
    if table and c == getattr(view, "lithology_curve", None):
        return {float(k): str(v) for k, v in table.items()}
    well = getattr(getattr(view, "prep", None), "well", None)
    curve = well.get(c) if well is not None and c in set(getattr(well, "curves", {}) or {}) else None
    custom = getattr(getattr(curve, "metadata", None), "custom", None) or {}
    labels = custom.get("category_labels") or {}
    return {float(k): str(v) for k, v in labels.items()}


def screened(view, c: str) -> str:
    """What the preparation's range screening removed of a measured curve over the whole well, where Petrophys judges
    the curve mostly implausible (metadata.custom["range_screening"]: masked of finite at least its
    RANGE_SCREENING_WARNING_FRACTION, the share at which it warns of a wrong label, scale or curve type; a few spikes
    it masks without a word, and so does this): "range screening removed 4914 of its 9427 readings over the well
    (outside 38.5-300 us/ft); the rest is left out too" (the last where Petrophys left the whole curve out); ""
    otherwise (DTC had no values in the interval and the answer said the well had no sonic
    log)."""
    from petrophys.preprocessing.standardization.curve_standardizer import RANGE_SCREENING_WARNING_FRACTION
    well = getattr(getattr(view, "prep", None), "well", None)
    curve = well.get(c) if well is not None and c in set(getattr(well, "curves", {}) or {}) else None
    rs = (getattr(getattr(curve, "metadata", None), "custom", None) or {}).get("range_screening") or {}
    k, n = int(rs.get("masked") or 0), int(rs.get("finite") or 0)
    if not k or not n or k / n < RANGE_SCREENING_WARNING_FRACTION:
        return ""
    lo, hi, unit = rs.get("low"), rs.get("high"), str(rs.get("unit") or "").strip()
    span = f" (outside {float(lo):g}-{float(hi):g}{' ' + unit if unit else ''})" if lo is not None and hi is not None else ""
    hint = f"; {rs['hint']}" if rs.get("hint") else ""
    rest = "; the rest is left out too" if rs.get("whole_curve") else ""
    return f"range screening removed {k} of its {n} readings over the well{span}{hint}{rest}"


def _code(c) -> str:
    return str(int(c)) if float(c).is_integer() else str(c)


def code_text(code, labels: dict) -> str:
    """A class as written: '5 (SILT)' with the record's label, else '5'; codes the labels name alike, one class:
    '9, 12 (LIMESTONE)' (class_groups)."""
    if isinstance(code, tuple):
        lab = (labels or {}).get(float(code[0]))
        return f"{', '.join(_code(c) for c in code)}" + (f" ({lab})" if lab else "")
    lab = (labels or {}).get(float(code))
    return f"{_code(code)} ({lab})" if lab else _code(code)


def class_groups(codes, labels: dict = None) -> list:
    """The classes of a curve's codes: codes the record's labels name alike are one class (a tuple of them, question
    the data's code table names 9 and 12 LIMESTONE, listed twice), every other code its own; in the order of
    each class's first code."""
    by = {}
    for c in codes:
        lab = (labels or {}).get(float(c))
        by.setdefault(("label", str(lab).strip().upper()) if lab else ("code", float(c)), []).append(c)
    return [cs[0] if len(cs) == 1 else tuple(cs) for cs in by.values()]


def in_class(x, key) -> np.ndarray:
    """The samples of x in a class (one code, or the codes of one label)."""
    x = np.asarray(x, dtype=float)
    return np.isin(x, list(key)) if isinstance(key, tuple) else x == key


def class_counts(x, codes, labels: dict = None) -> tuple:
    """(n with a value, [(class, count)] of the classes present in x, in code order): with the record's labels, codes
    named alike are one class (class_groups)."""
    x = np.asarray(x, dtype=float)
    fin = x[np.isfinite(x)]
    out = [(k, int(np.count_nonzero(in_class(fin, k)))) for k in class_groups(codes, labels)]
    return int(fin.size), [(k, m) for k, m in out if m]


def kind_note(k: Kind, labels: dict) -> str:
    """The label line's note on what a curve's values are and how they are summarised (empty for values)."""
    if k.kind == "flag":
        return "0/1 values over the well: each basis gives the share set to 1"
    if k.kind == "classes":
        return (f"class codes ({len(k.codes)} integer values over the well: "
                + ", ".join(code_text(c, labels) for c in class_groups(k.codes, labels))
                + "): each basis gives the share of each class (codes are labels, not quantities)")
    if k.kind == "one value":
        return f"one value over the well: {code_text(k.codes[0], labels)}"
    return ""


def statistic(x, name: str, log: bool = False) -> float:
    return compute(x, [name], log)[name]


def _percentile(name) -> Optional[int]:
    t = str(name)
    if len(t) in (2, 3) and t[0] == "p" and t[1:].isdigit() and 1 <= int(t[1:]) <= 99:
        return int(t[1:])
    return None


# --- where ----------------------------------------------------------------------------------------------------------

@dataclass
class Basis:
    kind: str                         # "zone", "pooled" or "whole"
    label: str                        # what it covers ("" for a zone: the caller names it)
    idx: np.ndarray                   # interval sample indices
    zone: object = None               # the zone, for kind "zone"


def in_a_zone(view) -> np.ndarray:
    """The interval's samples inside any of the formation's lithology zones: all of them, also on a view narrowed to
    some (FormationView.of_zones), where `zoned` is the named zones' samples."""
    every = getattr(view, "all_zones", None)
    if not every:
        return np.asarray(view.zoned, dtype=bool)
    out = np.zeros(np.asarray(view.depth).size, dtype=bool)
    for z in every:
        out[np.asarray(z.indices)] = True
    return out


def outside(view) -> int:
    """The interval's samples outside every lithology zone."""
    return int(np.asarray(view.depth).size - np.count_nonzero(in_a_zone(view)))


def count_share(k: int, n: int, what: str = "samples") -> str:
    """A share of samples written with its count: "2 of 768 samples (0.3%)". A share alone left a question asking how
    many with no count to quote ("the absolute sample counts are not stated")."""
    from petroharness.well.view import fmt_pct
    return f"{int(k)} of {int(n)} {what} ({fmt_pct(100.0 * k / n, 1) if n else 'n/a'})"


def pooled_label(view, zs) -> str:
    every = {z.zone_id for z in zs} == {z.zone_id for z in (getattr(view, "all_zones", None) or view.zones)}
    if getattr(view, "selection", None):                 # a selection's rows (agent.selection)
        return "rows pooled" if every else "these rows pooled"
    return "zones pooled" if every else "these zones pooled"


def whole_label(view) -> str:
    return whole_text(view, outside(view))


def selection_name(view) -> str:
    """A selection by its name and depths, each once (a depth range is its own name)."""
    iv, unit = view.interval, getattr(view, "depth_unit", "") or ""
    span = f"{iv.top:g}-{iv.base:g} {unit}"
    return view.selection if span in view.selection else f"{view.selection} {span}"


def whole_text(view, count) -> str:
    """The whole interval's label with `count` (a number, or its text as a result writes it) samples outside any zone;
    a selection (agent.selection) names itself with its depths, and its samples outside any row."""
    if getattr(view, "selection", None):
        return f"{selection_name(view)} ({count} samples outside any row)"
    return f"whole interval ({count} samples outside any zone)"


def pooled_word(view) -> str:
    """What a view's rows are called in its pooled lines: zones, or the rows of a selection."""
    return "rows" if getattr(view, "selection", None) else "zones"


def outside_mask(view) -> np.ndarray:
    """The interval's samples outside every lithology zone (True there)."""
    return ~in_a_zone(view)


def what_outside(view) -> str:
    """What the samples outside the zones are: the runs of the zones' reading (the lithology log, or the
    shale-volume bands) no thicker than the zone minimum - a labelled gap, not a zone."""
    unit = getattr(view, "depth_unit", "") or ""
    try:
        least = float(view.policy["zones"]["min_thickness_m"])
        least = view.to_unit(least) if hasattr(view, "to_unit") else least
        size = f" no thicker than the zone minimum of {float(f'{least:.4g}'):g} {unit}".rstrip()
    except (KeyError, TypeError, AttributeError):
        size = " thinner than a zone"
    what = "lithology-log runs" if getattr(view, "lithology_curve", None) else "runs of the zones' reading"
    return f"{what}{size}; not a zone"


def kept_outside(view, keep=None) -> int:
    """The samples outside every zone (or row), of those `keep` keeps (a where's samples; all when None)."""
    away = outside_mask(view)
    return int(away.sum()) if keep is None else int((away & np.asarray(keep, dtype=bool)).sum())


def whole_label_of(view, i=str, keep=None, where: str = "") -> str:
    """The whole selection's label as every result line writes it, its counts written by i (a result's Out.i, so
    they are numbers of the result): with its samples outside any zone or row; under a where (keep: its samples,
    where: the condition as read), every sample where it holds, how many, and how many of them lie outside any zone
    ('whole interval (201 samples outside any zone)' over the 158 samples of a where was read
    as the whole interval)."""
    if keep is None:
        return whole_text(view, i(outside(view)))
    m = np.asarray(keep, dtype=bool)
    word = "row" if getattr(view, "selection", None) else "zone"
    return f"every sample where {where} ({i(int(m.sum()))} samples, {i(kept_outside(view, m))} of them outside any {word})"


def outside_label(view, short: bool = False, keep=None) -> str:
    """The basis label of the samples outside the zones: their count (of a where's samples, keep) and what they are
    (short: a value line's label, 'not a zone' only; the tool's description and its other lines say what they
    are)."""
    n = kept_outside(view, keep)
    if getattr(view, "selection", None):                 # a selection's samples between its rows
        return f"outside any row ({n} samples; not a row)"
    if short:
        return f"outside any zone ({n} samples; not a zone)"
    return f"outside any zone ({n} samples, {what_outside(view)})"


OUTSIDE_STATISTICS = ("n", "mean", "min", "max")     # what the samples outside the zones hold, on a value line


def differs(view, x, idx=None) -> bool:
    """Whether the whole interval differs from the zones pooled for values x (over the interval's samples): some sample
    outside the zones has a value (idx: the samples a selection keeps, all when None)."""
    out = outside_mask(view)
    if idx is not None:
        keep = np.zeros(out.size, dtype=bool)
        keep[np.asarray(idx, dtype=int)] = True
        out &= keep
    return bool(np.isfinite(np.asarray(x, dtype=float)[out]).any())


def bases(view, zs=None) -> list:
    """Each zone (of zs, all when None), the zones pooled and the whole interval, in that order."""
    zs = list(view.zones) if zs is None else list(zs)
    out = [Basis("zone", "", np.asarray(z.indices), z) for z in zs]
    idx = np.unique(np.concatenate([np.asarray(z.indices) for z in zs])) if zs else np.array([], dtype=int)
    out.append(Basis("pooled", pooled_label(view, zs), idx))
    out.append(Basis("whole", whole_label(view), np.arange(np.asarray(view.depth).size)))
    return out


# --- rankings -------------------------------------------------------------------------------------------------------

def rankings(rows: list, shown: list, v: Callable[[float], str], of: str = "") -> list:
    """Zones ranked by each statistic shown, side by side: [highest line, lowest line]. rows: [(zone id, {name:
    value})]; ties list every zone that holds the value; a zone that tops several rankings is named under each. of:
    the curve the statistics are of (named in each line)."""
    stats = [s for s in shown if s != "n"]
    hi, lo = [], []
    for s in stats:
        vals = [(zid, _plain(d.get(s))) for zid, d in rows if d.get(s) is not None and np.isfinite(d.get(s))]
        if len(vals) < 2:
            continue
        top, bottom = max(x for _, x in vals), min(x for _, x in vals)
        if top == bottom:
            continue
        hi.append(f"{s} {', '.join(z for z, x in vals if x == top)} ({v(top)})")
        lo.append(f"{s} {', '.join(z for z, x in vals if x == bottom)} ({v(bottom)})")
    if not hi:
        return []
    of = f" of {of}" if of else ""
    return [f"highest zone by each statistic{of}: " + "; ".join(hi), f"lowest zone by each statistic{of}: " + "; ".join(lo)]


def depth_order(rows: list, mids: dict, shown: list, v: Callable[[float], str], rank_corr, of: str = "") -> str:
    """The rank correlation of each statistic's zone values with the zones' mid-depths (three zones at least; a
    positive value: higher deeper). Empty with fewer than three zones. of: the curve (named in the line)."""
    parts, k = [], 0
    for s in [s for s in shown if s != "n"]:
        vals = [(mids[zid], _plain(d.get(s))) for zid, d in rows if d.get(s) is not None and np.isfinite(d.get(s))]
        if len(vals) < 3:
            continue
        rc = rank_corr([m for m, _ in vals], [x for _, x in vals])
        if np.isfinite(rc):
            parts.append(f"{s} {v(rc)} ({order_words(rc, len(vals), direction_words)})")
            k = max(k, len(vals))
    legend = "" if k < ORDER_MIN_ZONES else "; positive: higher deeper, negative: higher upward"
    return (f"with depth (rank correlation of each zone's {of + ' ' if of else ''}value with its mid-depth over {k} "
            f"zones{legend}): " + "; ".join(parts)) if parts else ""


ORDER_MIN_ZONES = 5    # an exact rank test cannot reach p < 0.05 with fewer: 4 zones give at best p = 2/24 (two-sided)


def order_words(rc: float, k: int, words: Callable[[float], str]) -> str:
    """The words for a rank correlation over k zones: words(rc), or, with fewer than ORDER_MIN_ZONES zones, that the
    order cannot be told from chance."""
    if k < ORDER_MIN_ZONES:
        return f"{k} zones: too few to tell an order from chance; at least {ORDER_MIN_ZONES} are needed"
    return words(rc)


def direction_words(rc: float) -> str:
    """A rank correlation with depth in words: negative is higher upward, positive higher downward."""
    if not np.isfinite(rc) or rc == 0:
        return "no order with depth"
    return "higher downward" if rc > 0 else "higher upward"


def _plain(x: float) -> float:
    """A value to 10 significant figures: values equal but for float noise rank as ties."""
    return float(f"{float(x):.10g}")


# --- thresholds -----------------------------------------------------------------------------------------------------

def threshold_source(given_by_model: bool, workflow_rule: str = "") -> str:
    """Where a threshold came from: the model's, or the workflow's with its rule."""
    return "your threshold" if given_by_model else f"the workflow's: {workflow_rule}"


# --- class views ----------------------------------------------------------------------------------------------------

@dataclass
class ClassViews:
    """A classification both ways, in the order of the bases (texts with the numbers written in them)."""
    zones: list                       # [(zone, its class by mean or None, samples text, numbers)]
    pooled: tuple                     # (text, numbers): by zone mean over the zoned thickness; samples over the zones
    whole: Optional[tuple]            # (text, numbers): samples over every sample of the interval where a class is set
    #                                   outside the zones, else what the samples outside them hold; None: none outside


def class_views(view, zone_class: dict, masks: dict, background: list, v: Callable[[float], str],
                pct: Callable[[float], str], unit: str = "") -> ClassViews:
    """Both views of a classification: each zone's class from its mean and the share of its samples in each class;
    over the zones, each class's share of the zoned thickness by zone mean and of the zone samples; over the whole
    interval, each class's share of every sample. zone_class: {zone id: label} (empty: no zone-mean view); masks:
    {label: bool array over the interval's samples}; background: the labels that are the rest."""
    bg = ", ".join(background) or "no class"

    def shares(sel) -> tuple:
        got = sorted(((n, 100 * float(m[sel].mean())) for n, m in masks.items() if m[sel].size and m[sel].any()),
                     key=lambda x: -x[1])
        return (", ".join(f"{n} {pct(p)}" for n, p in got) or f"none ({bg} only)"), [p for _, p in got]

    zs = list(view.zones)
    per = []
    for z in zs:
        text, nums = shares(np.asarray(z.indices))
        per.append((z, zone_class.get(z.zone_id), text, nums))
    total = sum(z.thickness for z in zs) or 1.0
    parts, nums = [], []
    if zone_class:
        by = {}
        for z in zs:
            by.setdefault(zone_class.get(z.zone_id, "unresolved"), []).append(z)
        cells = []
        for lab, g in sorted(by.items(), key=lambda kv: -sum(z.thickness for z in kv[1])):
            t = sum(z.thickness for z in g)
            cells.append(f"{lab} {pct(100 * t / total)} ({v(t)}{(' ' + unit) if unit else ''}: "
                         f"{zone_ids([z.zone_id for z in g])})")
            nums += [100 * t / total, t]
        parts.append("by zone mean " + "; ".join(cells) + " of the zoned thickness")
    zoned = np.asarray(view.zoned)
    if zoned.any():
        text, got = shares(zoned)
        parts.append(f"samples {text} of the zone samples")
        nums += got
    pooled = (f"{pooled_label(view, zs)}: " + "; ".join(parts), nums)
    whole = None                     # the whole interval only where it differs, with what the rest holds
    away = outside_mask(view)
    if away.any():
        held = [n for n, m in masks.items() if m.size and m[away].any()]
        if held:
            text, got = shares(np.ones(np.asarray(view.depth).size, dtype=bool))
            rest, more = shares(away)
            whole = (f"{whole_label(view)}: samples {text} of every sample; the {outside(view)} samples outside any "
                     f"zone ({what_outside(view)}): {rest}", [float(outside(view))] + got + more)
        else:
            whole = (f"{outside_label(view)}: no class (the analyzers classify the zones' samples)",
                     [float(outside(view))])
    return ClassViews(per, pooled, whole)


def zone_ids(ids: list) -> str:
    """Z1, Z2, Z3, Z5 -> Z1-Z3, Z5."""
    nums = [int(i[1:]) for i in ids if len(i) > 1 and i[0] == "Z" and i[1:].isdigit()]
    if len(nums) != len(ids):
        return ", ".join(ids)
    runs, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            runs.append((start, prev))
            start = prev = n
    runs.append((start, prev))
    return ", ".join(f"Z{a}" if a == b else f"Z{a}-Z{b}" for a, b in runs)
