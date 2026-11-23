"""Measured how and grouped how: the bases (each zone, the zones pooled, the whole selection), statistics, class and
flag values, thicknesses, rank correlation, pairs and line fits."""

from __future__ import annotations

from typing import Optional
import numpy as np
from petroharness.agent.map import num
from petroharness.well import summary as S
from petroharness.agent.engine.conditions import Selection
from petroharness.agent.engine.base import Formation, ToolError
from petroharness.agent.engine.curves import kind, zone_at
from petroharness.agent.engine.output import Out


# --- grouped how ----------------------------------------------------------------------------------------------------

def bases(f: Formation, zs: list = None) -> list:
    """Each zone, the zones pooled and the whole interval, in that order (petroharness.well.summary.bases); under
    data.basis "zones" the tools show each zone and the zones pooled only (the record's computations keep all three)."""
    out = S.bases(f.view, zs)
    return [b for b in out if b.kind != "whole"] if getattr(f.view, "basis", "all") == "zones" else out


def scopes(f: Formation, keep=None, i=str, sel: Optional["Selection"] = None) -> list:
    """(label, interval sample indices) of each basis a tool reports a per-sample result by, the headline first: the
    whole selection (where samples outside the zones hold a value: else it is the zones pooled), the zones pooled,
    then each zone (one zone: that zone, no pooled line). Built on bases (data.basis "zones" leaves the whole out).
    keep: the samples with a value; sel: a where, whose samples the bases are cut to and the whole label names; i
    writes a count into the result (Out.i): a tool that reported zones only read 0 where every
    sample with a value lay outside the zones."""
    n = int(np.asarray(f.depth).size)
    keep = np.ones(n, dtype=bool) if keep is None else np.asarray(keep, dtype=bool)
    if sel is not None:
        keep = keep & np.asarray(sel.mask, dtype=bool)
    whole, pooled, each = [], [], []
    for b in bases(f):
        idx = np.asarray(b.idx, dtype=int)
        idx = idx[keep[idx]]
        if not idx.size:
            continue
        if b.kind == "whole":
            if (keep & S.outside_mask(f.view)).any():
                whole.append((S.whole_label_of(f.view, i, None if sel is None else sel.mask,
                                                "" if sel is None else sel.read), idx))
        elif b.kind == "pooled":
            pooled.append((b.label, idx))
        else:
            each.append((b.zone.zone_id, idx))
    return whole + (pooled if len(each) != 1 else []) + each


def over_bases(f: Formation, x, row, stat=np.nanmedian, sel: Optional["Selection"] = None, n: bool = False) -> str:
    """A per-sample result over scopes(), as one line's text, the whole selection first: "whole interval (12 samples
    outside any zone) 2.65; zones pooled 2.64; Z1 2.63 (n 40); ..." (stat of each basis's finite values; n: each
    basis's count beside it)."""
    x = np.asarray(x, dtype=float)
    return "; ".join(f"{label} {row.v(stat(x[idx]))}" + (f" (n {row.i(int(idx.size))})" if n else "")
                     for label, idx in scopes(f, np.isfinite(x), row.i, sel))


# --- measured how ---------------------------------------------------------------------------------------------------

def statistic(x: np.ndarray, name: str, log: bool = False) -> float:
    """One statistic of the finite samples (petroharness.well.summary.compute); log: percentiles on log10 values."""
    try:
        return S.statistic(x, S.statistic_name(name), log)
    except ValueError:
        raise ToolError(S.derivation(name)) from None


def statistics(names) -> tuple:
    """(the statistics asked for that the summary layer computes, n first, or None when none are: each curve then takes
    the default set; a line for each one it does not compute, saying how to derive it with calc)."""
    asked = list(dict.fromkeys(S.statistic_name(s) for s in (names or [])))
    good = [s for s in asked if S.known(s)]
    notes = [S.derivation(s) for s in asked if not S.known(s)]
    return (["n"] + [s for s in good if s != "n"] if good else None), notes   # n always: a mean of three samples says so


def no_codes(f: Formation, tool: str, *cs) -> None:
    """Class codes are labels, not quantities: a tool that averages, fits or screens values does not take them (by the
    shape of the values, summary.curve_kind); the error says where their shares are."""
    for c in cs:
        if c in f.inv.curves and kind(f, c).kind == "classes":
            raise ToolError(f"{c} holds class codes (labels, not quantities): {tool} of codes means nothing; its "
                            f"class shares are in stats {c}, and another curve class by class is stats <curve> where "
                            f"{c} == <code> (a class of several codes, as stats {c} names it: each code, joined "
                            f"with or)")


def class_values(out: Out, x: np.ndarray, k, labels: dict, thick) -> str:
    """Class codes over one group: n of the group's samples, then each class present with its share of those with a
    value, its samples and its thickness (thick(code)); one value over the well: that value."""
    n, counts = S.class_counts(x, k.codes, labels if k.kind == "classes" else None)
    head = f"n {out.i(n)} of {out.i(x.size)}"
    if k.kind == "one value":
        return head + (f", every value {S.code_text(k.codes[0], labels)}" if n else "")
    u = out.f.inv.depth_unit
    return head + "".join(f", class {S.code_text(c, labels)} {out.pct(100 * m / n)} ({out.i(m)} samples, "
                          f"{out.v(thick(c))} {u})" for c, m in counts)


def curve_statistics(f: Formation, c: str, asked) -> tuple:
    """(names, log) for a curve: the asked statistics or the default set, the geometric mean and log10 percentiles by
    the shape of the curve's values over the interval (petroharness.well.summary)."""
    x = np.asarray(f.view.values(c), dtype=float)
    return S.names(asked, x), S.log_shaped(x)


def flag_values(out: Out, x: np.ndarray, thick: float) -> str:
    """A flag over one group: n of the group's samples, how many are set, their share and thickness."""
    ok = np.isfinite(x)
    on = int((x[ok] > 0.5).sum())
    return (f"n {out.i(ok.sum())} of {out.i(x.size)}, set in {out.i(on)} samples "
            f"({out.pct(100 * on / ok.sum() if ok.any() else 0.0)} of those with a value), "
            f"thickness {out.v(thick)} {out.f.inv.depth_unit}")


def set_thickness(f: Formation, on: np.ndarray, kind: str, zs: list) -> float:
    """The thickness of the set samples of a basis, in the zones' convention (a zone's thickness x its share): the
    whole interval scales the gross; zones pooled add their zones."""
    if kind == "whole":
        return f.inv.gross * float(on.sum()) / max(on.size, 1)
    return float(sum(thickness(z, int(on[z.indices].sum())) for z in zs))


def values(out: Out, x: np.ndarray, d: np.ndarray, names, log: bool = False, at: bool = True, zone: bool = True,
           span: bool = False) -> str:
    """Values of one curve over one group: n of the group's samples, the statistics, the depths of min and max (at),
    each with the zone its sample is in (zone; left out where every sample of the group lies outside the zones).
    `span` (a selection's whole line): a curve with values at part of its samples says its first and last sample
    with a value (where a log is recorded was read off a row's base)."""
    parts = []
    ok = np.isfinite(x)
    got = S.compute(x, list(names), log)
    for s in names:
        v = got[s]
        if s == "n":
            parts.append(f"n {out.i(v)} of {out.i(x.size)}")
            if span and 0 < int(ok.sum()) < x.size:
                parts.append(f"values from {out.depth(float(d[ok][0]))} to {out.depth(float(d[ok][-1]))}")
        elif np.isfinite(v):
            text = f"{s} {out.v(v)}"
            if s in ("min", "max") and at:
                where = float(d[ok][np.argmin(x[ok]) if s == 'min' else np.argmax(x[ok])])
                text += f" at {out.depth(where)}"
                if zone:
                    text += f" ({zone_at(out.f, where)})"    # which zone the sample is in
            parts.append(text)
    return ", ".join(parts)


def thickness(z, n: int) -> float:
    """n samples of zone z as thickness, the analyzer sections' convention: the zone's thickness x its share."""
    return z.thickness * n / max(z.n_samples, 1)


def extent(f: Formation, mask: np.ndarray, zs: list) -> list:
    """(top, base, samples, zone) for each run of consecutive selected samples inside one of the zones zs."""
    found = []
    for z in zs:
        idx = np.asarray(z.indices)
        on = mask[idx]
        k = 0
        while k < idx.size:
            if on[k]:
                j = k
                while j + 1 < idx.size and on[j + 1] and idx[j + 1] == idx[j] + 1:
                    j += 1
                found.append((float(f.depth[idx[k]]), float(f.depth[idx[j]]), j - k + 1, z))
                k = j + 1
            else:
                k += 1
    return sorted(found, key=lambda r: r[0])


def _ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    r = np.empty(x.size)
    r[order] = np.arange(x.size)
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)       # ties take their average rank
    return (np.bincount(inv, weights=r) / counts)[inv]


def rank_correlation(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    ra, rb = _ranks(a[ok]), _ranks(b[ok])
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def span_text(out: Out, x: np.ndarray) -> str:
    """A curve's range over the samples shown: 'min-max' ('min to max' when a value is negative)."""
    lo, hi = float(np.min(x)), float(np.max(x))
    return f"{out.v(lo)} to {out.v(hi)}" if lo < 0 or hi < 0 else f"{out.v(lo)}-{out.v(hi)}"


def coefficient_basis(out: Out, kind: str, k: int, ranges: list) -> str:
    """What a coefficient was computed on: its kind and transform, its n and each variable's range over the
    samples used; ranges: [(name, values used)]."""
    return f"({kind}; n {out.i(k)}; " + ", ".join(f"{n} {span_text(out, x)}" for n, x in ranges) + ")"


def pair(out: Out, xa: np.ndarray, xb: np.ndarray, a: str, b: str, same: bool, tolerance) -> str:
    """Two curves over one group: n of the group's samples where both have values, both means, a - b on one scale,
    the rank correlation with what it was computed on (its n, each curve's range, on ranks)."""
    ok = np.isfinite(xa) & np.isfinite(xb)
    if not ok.any():
        return f"n {out.i(0)} of {out.i(xa.size)}, no sample where both {a} and {b} have values"
    parts = [f"n {out.i(ok.sum())} of {out.i(xa.size)}", f"mean {a} {out.v(np.mean(xa[ok]))}",
             f"mean {b} {out.v(np.mean(xb[ok]))}"]
    if same:
        dd = xa[ok] - xb[ok]
        parts += [f"difference mean {out.v(np.mean(dd))}", f"sd {out.v(np.std(dd))}"]
        if np.std(dd) > 0:                                             # the mean against its spread
            parts.append(f"mean / sd {out.v(np.mean(dd) / np.std(dd))}")
        # which way the difference goes, and how often
        t = float(tolerance or 0.0)
        tt = num(t)
        parts.append(f"{a} > {b}{f' + {tt}' if t else ''} in {out.pct(100 * np.mean(dd > t))}, "
                     f"{a} < {b}{f' - {tt}' if t else ''} in {out.pct(100 * np.mean(dd < -t))}"
                     + (f", within {tt} in {out.pct(100 * np.mean(np.abs(dd) <= t))}" if t else
                        f", equal in {out.pct(100 * np.mean(dd == 0))}"))
    rc = rank_correlation(xa, xb)
    if np.isfinite(rc):
        parts.append(f"rank correlation {out.v(rc)} "
                     + coefficient_basis(out, "Spearman, on ranks", int(ok.sum()), [(a, xa[ok]), (b, xb[ok])]))
    return ", ".join(parts)


def line_fit(out: Out, x: np.ndarray, y: np.ndarray, names: tuple = None, raw: tuple = None) -> str:
    """A least-squares line y = intercept + slope * x over one group: n of the group's samples where both have values,
    slope, intercept, R2 and the correlation, with what the correlation was computed on (names: (y, x) as fitted, a
    transform in the name; raw: (y, x) values before any transform, whose ranges are shown); fewer than 3 samples or a
    constant x give no line."""
    ok = np.isfinite(x) & np.isfinite(y)
    n = int(ok.sum())
    if n < 3:
        return f"n {out.i(n)} of {out.i(x.size)} (too few samples for a line)"
    xs, ys = x[ok], y[ok]
    if np.ptp(xs) == 0:
        return f"n {out.i(n)} of {out.i(x.size)} (x is constant: no line)"
    slope, intercept = np.polyfit(xs, ys, 1)
    r = float(np.corrcoef(xs, ys)[0, 1]) if np.ptp(ys) > 0 else 0.0
    text = (f"n {out.i(n)} of {out.i(x.size)}, slope {out.v(slope)}, intercept {out.v(intercept)}, R2 {out.v(r * r)}, "
            f"correlation {out.v(r)}")
    if names:
        yn, xn = names
        ry, rx = raw if raw is not None else (y, x)
        bare = lambda s: s[6:-1] if s.startswith("log10(") else s
        text += " " + coefficient_basis(out, f"Pearson on {yn} and {xn}", n,
                                        [(bare(yn), np.asarray(ry)[ok]), (bare(xn), np.asarray(rx)[ok])])
        if bare(xn) == "DEPTH":                                      # a trend with depth, in words
            text += f"; {yn} {S.direction_words(r)}"
    return text


def together(rc: float, a: str, b: str) -> str:
    """A coefficient between two curves in words: '<a> higher where <b> is higher' (positive) or '... lower'."""
    if not np.isfinite(rc) or rc == 0:
        return f"no rank order between {a} and {b}"
    return f"{a} higher where {b} is {'higher' if rc > 0 else 'lower'}"
