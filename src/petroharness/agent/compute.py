"""The computations a petrophysicist runs beyond zone statistics, as named tools (lithology tables, zone
contrasts, curve order, thresholds, the spike screen, vertical sequence, pay summary, core vs log, lag, ...)."""
from __future__ import annotations

import re
from typing import Optional

import numpy as np

from petroharness.record.catalog import CATALOG, Evidence, EvidenceError, fmt

from petroharness.agent import engine as E
from petroharness.agent.engine import Formation, Result, ToolError
from petroharness.well import summary as S

_NUM = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])")


def _check(name: str, value, choices) -> str:
    v = str(value).strip().lower()
    if v not in choices:
        raise ToolError(f"{name} must be one of {', '.join(choices)}, not {value!r}")
    return v


def _cell_numbers(cells) -> list:
    out = []
    for v in cells:
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            out.append(float(v))
        else:
            out += [float(x) for x in _NUM.findall(re.sub(r"\bZ\d+\b|[A-Za-z_]+\d[A-Za-z0-9_]*", " ", str(v)))]
    return out


def _zone_cells(row) -> set:
    return {str(v).strip().upper() for v in row if isinstance(v, str) and re.fullmatch(r"\s*Z\d+\s*", v)}


def _labelled(columns: list, row: list) -> str:
    """A table row as one line, each cell after the first named by its column ("Z1 | lithology: SILT | mean PHIE:
    0.2"), so that a line fetched alone says what each value is."""
    cell = lambda v: "n/a" if v is None else (fmt(v) if isinstance(v, float) else str(v))
    if not columns:
        return " | ".join(cell(v) for v in row)
    return " | ".join([cell(row[0])] + [f"{c}: {cell(v)}" for c, v in zip(columns[1:], row[1:])])


def _result(f: Formation, d: dict, zones=None) -> Result:
    """The computation's evidence as an item: its title, then each row as one line under it with every cell named by
    its column, then its facts; rows of other zones left out when zones are named; rows past the size limit held in
    the item, named at the end of the text with the find that fetches them."""
    ev = Evidence(id="E0", call="", args={}, **{k: d[k] for k in ("title", "columns", "rows", "facts", "values") if k in d})
    keep_zones = {z.zone_id.upper() for z in E.zones(f, zones)} if zones else None
    out = E.Out(f)
    out.add(ev.title, _cell_numbers([ev.title]) + _cell_numbers(ev.columns))
    rows = []
    for r in ev.rows:
        zs = _zone_cells(r)
        if keep_zones is not None and zs and not (zs & keep_zones):
            continue
        rows.append((str(r[0]).strip() if r else "", "  " + _labelled(ev.columns, r), _cell_numbers(r)))
    facts = [(f"- {x}", _cell_numbers([x])) for x in ev.facts]
    out.fit(rows, E.max_chars() - sum(len(x) + 1 for x, _ in facts) + 140, what="rows")
    for x, ns in facts:
        out.add(x, ns)
    r = out.result()
    # tool lines that read as verdicts, reworded as what they are; a change of -0.11 is written as 0.11 too
    rows = [(_plain_line(x), ns + [abs(n) for n in ns if n < 0]) for x, ns in r.rows]
    return Result("\n".join(_plain_line(x) for x in r.text.split("\n")), [n for _, ns in rows for n in ns], rows)


_VERDICT_LINES = [
    (re.compile(r"(\S+(?:, \S+)*) fail, so a high class there is not reservoir rock"),
     r"\1 fail the net-rock cutoff: a high class there is limited by clay (a limit on the class, not a verdict on the rock)"),
    (re.compile(r"^- (partly )?related by construction: "), r"- \1related by construction (the formula ties them; that "
     r"qualifies, it does not deny, a control): "),
]


def _plain_line(line: str) -> str:
    """computation lines that answers copied as verdicts, reworded as what they establish."""
    for pat, rep in _VERDICT_LINES:
        line = pat.sub(rep, line)
    return line


# the workflow's tool names in its messages, as this harness's tools
V5_TOOL_NAMES = ((r"\bdepth_trend\b", "crossplot with x DEPTH (or profile)"), (r"\bzone_stats\b", "stats"),
                 (r"\binterval_stats\b", "stats with where"), (r"\bflag_intervals\b", "runs"),
                 (r"\bcorrelation\b(?= for| \(| call)", "compare"))


def harness_names(message: str) -> str:
    for pattern, name in V5_TOOL_NAMES:
        message = re.sub(pattern, name, message)
    return message


def _run(f: Formation, name: str, zones=None, notes=(), **args) -> Result:
    """A catalog computation as an item; notes: lines said first (a statistic not computed, and how to derive it)."""
    try:
        d = CATALOG[name](f.view, **args)
    except EvidenceError as e:
        raise ToolError(harness_names(str(e))) from None
    if notes:
        d = {**d, "facts": list(notes) + list(d.get("facts") or [])}
    return _result(f, d, zones)


# --- the tools ------------------------------------------------------------------------------------------------------

def lithology_stats(f: Formation, curves, statistics=None, zones=None) -> Result:
    cs = E.curves(f, curves)
    asked, notes = E.statistics(statistics)
    return _run(f, "lithology_stats", zones, notes, curves=cs, stats=_asked(asked))


def _asked(asked) -> Optional[list]:
    """The statistics asked for that the layer computes, without n (the tables show n): None for the default set."""
    return [s for s in asked or [] if s != "n"] or None


def zone_contrast(f: Formation, curve: str, inputs=None, zones=None) -> Result:
    E.no_codes(f, "a contrast of zone means", E.curve(f, curve), *(E.curves(f, inputs) if inputs else []))
    return _run(f, "zone_contrast", zones, curve=E.curve(f, curve), inputs=E.curves(f, inputs) if inputs else None)


def curve_order(f: Formation, curves, relation: str = "decreasing", zones=None) -> Result:
    cs = E.curves(f, curves)
    if len(cs) < 2:
        raise ToolError("curve_order needs at least two curves with data, in the order to test")
    E.no_codes(f, "an order of means", *cs)
    return _run(f, "curve_order", zones, curves=cs, relation=_check("relation", relation, ("decreasing", "increasing", "between")))


def threshold_exceedance(f: Formation, curve: str, threshold: Optional[float] = None, op: str = ">",
                         absolute: Optional[bool] = None, zones=None) -> Result:
    op = str(op).strip()
    if op not in (">", ">=", "<", "<="):
        raise ToolError(f"op must be one of > >= < <=, not {op!r}")
    E.no_codes(f, "a threshold", E.curve(f, curve))
    return _run(f, "threshold_exceedance", zones, curve=E.curve(f, curve), threshold=threshold, op=op, absolute=absolute)


def spike_flags(f: Formation, curves, k: float = None, baseline: str = None, zones=None, scale: str = None,
                window: int = None, rule: str = None) -> Result:
    """The spike screen as the model calls it (rule is accepted and not used: the screen is mean +/- k std). With no k
    and no baseline, the workflow's: its deviation rule (the numerical analyzer's statistical_deviation_detection)
    counts z-scores above 2 and 3 against each zone's own mean and std."""
    if k is not None and not (isinstance(k, (int, float)) and not isinstance(k, bool) and 0 < k <= 20):
        raise ToolError(f"k must be a number of standard deviations between 0 and 20, not {k!r}")
    if isinstance(window, float) and window.is_integer():
        window = int(window)
    if isinstance(baseline, str) and re.fullmatch(r"\s*[Zz]\d+\s*", baseline):
        zones, baseline = [baseline.strip().upper()], "zone"     # a zone named as the baseline: that zone's own
    if window is not None and not (isinstance(window, int) and not isinstance(window, bool) and 3 <= window <= 201):
        raise ToolError(f"window must be a whole number of samples from 3 to 201, not {window!r}")
    return spikes(f, curves, [float(k)] if k is not None else list(WORKFLOW_KS),
                  _check("baseline", baseline or "zone", ("zone", "zoned", "interval")), zones,
                  _check("scale", scale or "linear", ("linear", "log10")), window,
                  source=("k: yours" if k is not None else f"k: {WORKFLOW_RULE}")
                  + ("; baseline: yours" if baseline or window else "; baseline: the workflow's, each zone its own"))


# the workflow's deviation rule (petrophys numerical analyzer, statistical_deviation_detection): z-scores above 2 and 3
# against each zone's own mean and std
WORKFLOW_KS = (2.0, 3.0)
WORKFLOW_RULE = "the workflow's deviation rule, z-scores above 2 and 3"


# --- the spike screen -----------------------------------------------------------------------------------------------

def spikes(f: Formation, curves, ks: list, baseline: str, zones=None, scale: str = "linear", window=None,
           source: str = "") -> Result:
    """Samples beyond mean +/- k std at each k of ks, against each zone's own values ("zone", the default), the
    lithology-zone samples pooled ("zoned") or the whole interval ("interval"); on the curve's values (scale linear, the
    default) or on log10 (scale log10); or, with window, against a centred rolling median and MAD of that many samples
    inside each zone (a local, robust screen). Each zone first (every zone's baseline is shown, flagged or not), then
    the zones pooled and the whole interval; a bound beyond what the curve can take is said to be none; each listed
    sample carries its zone and its signed distance in std. Adjacent jumps beyond the largest k std of the jumps, within
    zones. source: where k and the baseline came from."""
    cs, zs = E.curves(f, curves), E.zones(f, zones)
    E.no_codes(f, "a spike screen", *cs)
    d = f.depth
    out = E.Out(f)
    kt = " and ".join(E.num(k) for k in ks)
    if window:
        basis = f"a centred rolling median and MAD of {window} samples inside each zone (std = 1.4826 MAD)"
    else:
        basis = {"zone": "each zone's own mean and std (each zone its own baseline)",
                 "zoned": "the mean and std of the lithology-zone samples pooled",
                 "interval": "the mean and std of every sample in the interval"}[baseline]
    out.add(f"Spike screen: samples beyond mean +/- {kt} std of {basis}" + (f" ({source})" if source else "")
            + ("; on log10 values (bounds shown in curve units)" if scale == "log10" else "; on the curves' values")
            + f"; adjacent jumps beyond {E.num(max(ks))} std of the jumps, within zones")
    zone_of = np.full(d.size, -1)
    for i, z in enumerate(f.view.zones):
        zone_of[np.asarray(z.indices)] = i
    for ci, c in enumerate(cs):
        used0 = out.shown_chars                               # this curve's share of the room left
        share = (E.max_chars() - 300 - used0) // (len(cs) - ci)
        x = np.asarray(f.view.values(c), dtype=float)
        log = scale == "log10"
        with np.errstate(invalid="ignore", divide="ignore"):
            y = np.where(x > 0, np.log10(np.where(x > 0, x, 1.0)), np.nan) if log else x.copy()
        fin = x[np.isfinite(x)]
        nonneg = fin.size > 0 and fin.min() >= 0
        frac = E._UNIT.get((f.inv.curves[c].unit or "").strip().lower()) == "fraction" and not f.inv.curves[c].percent
        back = (lambda v: 10 ** v) if log else (lambda v: v)
        unit = f.inv.curves[c].unit or ""

        def bound(row, v, low: bool) -> str:
            b = back(v)
            if low and ((nonneg and not log and b < 0) or (frac and b < 0)):
                return "none (below 0)"
            if not low and frac and b > 1:
                return "none (above 1)"
            return row.v(b)

        out.add(f"{E.label(f, c)}" + (" - screened on log10" if log else ""))
        groups = ([(z, np.asarray(z.indices)) for z in zs] if baseline == "zone" or window else
                  [(None, np.concatenate([np.asarray(z.indices) for z in zs]) if baseline == "zoned" or zones
                    else np.arange(d.size))])
        totals, quiet, rows, base, sparse, each, pooled_hits = {k: 0 for k in ks}, [], [], [], [], "", []
        for z, idx in groups:
            yz = y[idx]
            ok = np.isfinite(yz)
            if ok.sum() < 3:
                if z is not None:                     # too few values is no screen, not "none beyond"
                    sparse.append(z.zone_id)
                continue
            if window:
                mu_s, sd_s = _rolling(yz, window)
                dev = np.where(ok & (sd_s > 0), (yz - mu_s) / np.where(sd_s > 0, sd_s, 1.0), 0.0)
                mu, sd = float(np.nanmedian(yz[ok])), float(1.4826 * np.nanmedian(np.abs(yz[ok] - np.nanmedian(yz[ok]))))
            else:
                mu, sd = float(np.mean(yz[ok])), float(np.std(yz[ok]))
                dev = np.where(ok, (yz - mu) / sd, 0.0) if sd > 0 else np.zeros(yz.size)
            hits = {k: ok & (np.abs(dev) > k) for k in ks}
            for k in ks:
                totals[k] += int(hits[k].sum())
            low = hits[min(ks)]
            if z is not None and not low.any():               # an unflagged zone: its baseline on one shared line
                quiet.append(z.zone_id)
                base.append((z.zone_id, back(mu), sd))
                continue
            row = out.child()
            where = row.zone(z) if z is not None else (S.pooled_label(f.view, zs) if baseline == "zoned" or zones
                                                       else _whole_label(row, f))
            text = (f"  {where}, {c}: n {row.i(int(ok.sum()))}, {'median' if window else 'mean'} {row.v(back(mu))}"
                    + (f", std of log10 {row.v(sd)}" if log else f", {'robust std' if window else 'std'} {row.v(sd)}")
                    + ("" if window else "; bounds " + "; ".join(
                        f"at {E.num(k)} std {bound(row, mu - k * sd, True)} to {bound(row, mu + k * sd, False)}" for k in ks)
                        + (f" {unit}" if unit else ""))
                    + "; beyond: " + ", ".join(f"{row.i(int(hits[k].sum()))} at {E.num(k)} std" for k in ks))
            if low.any():
                worst = sorted(np.flatnonzero(low), key=lambda i: -abs(dev[i]))[:3]
                text += "; largest: " + ", ".join(
                    f"{row.v(float(x[idx][i]))} at {row.depth(float(d[idx][i]))} ({E.zone_at(f, float(d[idx][i]))}, "
                    f"{'+' if dev[i] > 0 else '-'}{row.v(abs(float(dev[i])))} std)" for i in sorted(worst))
            rows.append((z.zone_id if z is not None else "all", text, row))
            if z is None:                                     # one baseline for every zone: each zone's count
                per = []
                for zz in zs:
                    zi = np.isin(idx, np.asarray(zz.indices))
                    per.append(f"{zz.zone_id} " + "/".join(str(int((hits[k] & zi).sum())) for k in ks))
                each = f"  each zone, {c} samples beyond {' / '.join(E.num(k) for k in ks)} std: " + "; ".join(per)
                zi = np.isin(idx, np.flatnonzero(np.asarray(f.view.zoned)))
                pooled_hits = [int((hits[k] & zi).sum()) for k in ks]
        tail = []
        outside = S.outside(f.view)
        if baseline == "zone" or window:
            if base:
                brow, parts, room = out.child(), [], max(160, share // 3)
                for k_, (zid, m_, s_) in enumerate(base):
                    piece = f"{zid} {num_short(m_)} +/- {num_short(s_)}"
                    if sum(len(p) + 2 for p in parts) + len(piece) > room:
                        parts.append(f"... ({len(base) - k_} more zones)")
                        break
                    brow.v(m_), brow.v(s_)
                    parts.append(piece)
                tail.append((f"  each unflagged zone's {'median +/- robust std' if window else 'mean +/- std'} of {c}"
                             + (" (log10 std)" if log else "") + ": " + "; ".join(parts), brow))
            prow = out.child()
            tail.append((f"  {S.pooled_label(f.view, zs)}, {c}: beyond: "
                         + ", ".join(f"{prow.i(totals[k])} samples at {E.num(k)} std" for k in ks)
                         + (f"; none beyond {E.num(min(ks))} std in {len(quiet)} zones: {_ids(quiet)}" if quiet
                            else f"; every zone has samples beyond {E.num(min(ks))} std" if not sparse else "")
                         + (f"; too few values to screen in {len(sparse)} zones: {_ids(sparse)}" if sparse else ""), prow))
            wrow = out.child()
            tail.append((f"  whole interval ({wrow.i(outside)} samples outside any zone), {c}: "
                         + ("the samples outside the zones have no zone baseline and are not screened" if outside
                            else "every sample is in a zone"), wrow))
        else:                                                 # one baseline: each zone's count, then its basis
            before, after = ([(each, None)] if rows and each else []), []
            if baseline == "zoned" or zones:
                wrow = out.child()
                after.append((f"  whole interval ({wrow.i(outside)} samples outside any zone), {c}: the screen is over the "
                              f"zones' samples", wrow))
            elif pooled_hits:
                prow = out.child()
                before.append((f"  {S.pooled_label(f.view, zs)}, {c}: beyond: "
                               + ", ".join(f"{prow.i(n)} samples at {E.num(k)} std" for n, k in zip(pooled_hits, ks)), prow))
            for t, r in before:
                out.add(t, r)
            out.fit(rows, used0 + share - 120 - sum(len(t) + 1 for t, _ in after), what="zones", label=c)
            tail = after
            rows = []
        if rows:
            out.fit(rows, used0 + share - 120 - sum(len(t) + 1 for t, _ in tail), what="zones", label=c)
        for t, r in tail:
            out.add(t, r)
        dy = np.abs(np.diff(y))
        same = (zone_of[:-1] == zone_of[1:]) & (zone_of[:-1] >= 0)
        inside = np.zeros(d.size - 1, dtype=bool)
        for z in zs:
            idx = np.asarray(z.indices)
            inside[idx[:-1][idx[:-1] < d.size - 1]] = True
        dy = np.where(same & inside & np.isfinite(dy), dy, np.nan)
        if np.isfinite(dy).sum() >= 3:
            sdj, kj = float(np.nanstd(dy)), max(ks)
            jumps = np.flatnonzero(np.isfinite(dy) & (dy > kj * sdj)) if sdj > 0 else np.array([], dtype=int)
            text = (f"  {S.pooled_label(f.view, zs)}, {c}: adjacent jumps within zones beyond {E.num(kj)} std of the "
                    f"jumps: {out.i(len(jumps))}")
            if len(jumps):
                top = sorted(jumps, key=lambda i: -dy[i])[:3]
                text += "; largest: " + ", ".join(
                    f"{out.v(float(x[i]))} to {out.v(float(x[i + 1]))} at {out.depth(float(d[i]))} ({E.zone_at(f, float(d[i]))})"
                    for i in sorted(top))
            out.add(text)
    return out.result()


def _whole_label(row, f: Formation) -> str:
    return f"whole interval ({row.i(S.outside(f.view))} samples outside any zone)"


def num_short(x: float) -> str:
    """A baseline value as the map writes numbers (the shared line keeps them short)."""
    return E.num(float(f"{x:.4g}"))


def _rolling(y: np.ndarray, window: int) -> tuple:
    """Centred rolling median and robust std (1.4826 MAD) of y over window samples (fewer at the ends)."""
    h = window // 2
    med, sd = np.full(y.size, np.nan), np.full(y.size, np.nan)
    for i in range(y.size):
        w = y[max(0, i - h): i + h + 1]
        w = w[np.isfinite(w)]
        if w.size >= 3:
            m = float(np.median(w))
            med[i], sd[i] = m, float(1.4826 * np.median(np.abs(w - m)))
    return med, sd


def _ids(ids: list) -> str:
    return ", ".join(ids) if len(ids) <= 10 else f"{', '.join(ids[:8])} and {len(ids) - 8} more"


def adjacent_jumps(f: Formation, curve: str, threshold: float, zones=None) -> Result:
    if not (isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and threshold > 0):
        raise ToolError(f"threshold must be a positive change in the curve's units, not {threshold!r}")
    E.no_codes(f, "a change between samples", E.curve(f, curve))
    return _run(f, "adjacent_jumps", zones, curve=E.curve(f, curve), threshold=float(threshold))


def vertical_sequence(f: Formation, curves=None, min_change: Optional[float] = None) -> Result:
    E.no_codes(f, "a sequence of means", *(E.curves(f, curves) if curves else []))
    if len(f.view.zones) == 1:                                   # one zone: its sequence inside it, by thirds
        return _sequence_in_zone(f, E.curves(f, curves) if curves else [c for c in ("GR", "VCL") if c in f.inv.curves])
    if len(f.view.zones) < 1:
        raise ToolError("vertical_sequence needs a zone with data; this interval has none")
    return _run(f, "vertical_sequence", None, curves=E.curves(f, curves) if curves else None, min_change=min_change)


def _sequence_in_zone(f: Formation, curves: list) -> Result:
    """a one-zone formation's vertical sequence inside it - each curve's mean in the zone's lower, middle
    and upper thirds (by depth, base first) and the direction of each step upward, as vertical_sequence reads zones."""
    from petroharness.agent.engine import Out
    if not curves:
        raise ToolError("vertical_sequence needs a curve with data (GR or VCL by default)")
    z = f.view.zones[0]
    idx = np.asarray(z.indices)
    parts = [p for p in np.array_split(idx, 3) if p.size]
    if len(parts) < 3:
        raise ToolError(f"{z.zone_id} has too few samples ({idx.size}) for a sequence inside it")
    out = Out(f)
    out.add(f"Vertical sequence inside {z.zone_id} (one zone: its thirds by depth, base first; mean of each third)")
    d = f.depth
    for c in curves[:4]:
        x = np.asarray(f.view.values(c), dtype=float)
        means = [float(np.nanmean(x[p])) if np.isfinite(x[p]).any() else float("nan") for p in reversed(parts)]
        spans = [out.span(float(d[p[0]]), float(d[p[-1]])) for p in reversed(parts)]
        cells = [f"{name} {sp}: {out.v(m) if np.isfinite(m) else 'no data'}"
                 for name, sp, m in zip(("lower third", "middle third", "upper third"), spans, means)]
        steps = [b - a for a, b in zip(means, means[1:]) if np.isfinite(a) and np.isfinite(b)]
        way = ("increasing upward" if steps and all(s > 0 for s in steps) else
               "decreasing upward" if steps and all(s < 0 for s in steps) else "no single direction")
        out.add(f"  {E.label(f, c)}: " + "; ".join(cells) + f" ({way})")
    return out.result()


def lag_correlation(f: Formation, curves, max_lag: Optional[float] = None, zones=None) -> Result:
    """depth matching by cross-correlation. For each pair of the curves (up to five), the Pearson
    correlation at zero lag and its strongest value within +/- max_lag (depth units; 3 m by default), with the
    apparent shift dz = z_a - z_b at that peak (positive: a's features read deeper than b's), over the interval's
    samples or over each zone asked for."""
    from itertools import combinations
    from petroharness.agent.engine import Out
    cs = E.curves(f, curves)[:5]
    if len(cs) < 2:
        raise ToolError("lag_correlation needs two or more curves, e.g. [\"GR\", \"RHOB\", \"NPHI\"]")
    E.no_codes(f, "a correlation", *cs)
    d = np.asarray(f.depth, dtype=float)
    step = float(np.median(np.diff(d))) if d.size > 1 else 0.0
    if step <= 0:
        raise ToolError("the interval has too few samples for a lag")
    span = f.view.to_unit(3.0) if max_lag is None else float(max_lag)
    if not span > 0:
        raise ToolError(f"max_lag must be a positive depth in {f.inv.depth_unit}, not {max_lag!r}")
    K = max(1, int(round(span / step)))
    groups = [(None, np.arange(d.size))] if not zones else [(z, np.asarray(z.indices)) for z in E.zones(f, zones)]
    out = Out(f)
    out.add(f"Lag correlation (depth matching by cross-correlation; dz = z_a - z_b at the peak, positive when a's "
            f"features read deeper than b's; search +/- {K} samples = {out.v(K * step)} {f.inv.depth_unit}, step "
            f"{out.v(step)} {f.inv.depth_unit})")
    vals = {c: np.asarray(f.view.values(c), dtype=float) for c in cs}
    for z, idx in groups:
        head = out.span(float(d[idx[0]]), float(d[idx[-1]])) if idx.size else "no samples"
        out.add(f"  {z.zone_id + ' ' if z is not None else ''}{head}")
        for a_, b_ in combinations(cs, 2):
            a, b = vals[a_][idx], vals[b_][idx]
            best, r0 = None, None
            for k in range(-K, K + 1):
                x, y = (a[:a.size - k], b[k:]) if k >= 0 else (a[-k:], b[:b.size + k])
                ok = np.isfinite(x) & np.isfinite(y)
                if ok.sum() < 10 or np.std(x[ok]) == 0 or np.std(y[ok]) == 0:
                    continue
                r = float(np.corrcoef(x[ok], y[ok])[0, 1])
                if k == 0:
                    r0 = (r, int(ok.sum()))
                if best is None or abs(r) > abs(best[1]):
                    best = (k, r, int(ok.sum()))
            name = f"{E.label(f, a_)} vs {E.label(f, b_)}"
            if best is None:
                out.add(f"    {name}: fewer than 10 samples where both have values")
                continue
            k, r, n = best
            dz = -k * step
            zero = f"r at zero lag {out.v(r0[0])} (n {out.i(r0[1])})" if r0 else "no zero-lag overlap"
            if k == 0:
                out.add(f"    {name}: {zero}; strongest at zero lag (aligned within a sample)")
                continue
            side = "deeper" if dz > 0 else "shallower"
            edge = "; the peak is at the search edge (a larger max_lag may move it)" if abs(k) == K else ""
            out.add(f"    {name}: {zero}; peak r {out.v(r)} at dz {out.v(dz)} {f.inv.depth_unit} ({a_} reads "
                    f"{out.v(abs(dz))} {f.inv.depth_unit} {side} than {b_}; n {out.i(n)}){edge}")
    return out.result()


def pay_summary(f: Formation) -> Result:
    return _run(f, "pay_summary")


def core_vs_log(f: Formation, zones=None) -> Result:
    return _run(f, "core_vs_log", zones)


def zone_classes(f: Formation, topic: str) -> Result:
    from petroharness.registry import load
    topics = list(load().topics["topics"])
    t = str(topic).strip().lower()
    if t not in topics:
        close = [x for x in topics if t and (t in x or x in t)]
        raise ToolError(f"no topic {topic!r}" + (f" (did you mean {', '.join(close[:3])}?)" if close else "")
                        + f"; topics: {', '.join(topics)}")
    return _run(f, "zone_classes", topic=t)


def formation_summary(f: Formation, curves=None, statistics=None) -> Result:
    asked, notes = E.statistics(statistics)
    return _run(f, "formation_summary", None, notes, curves=E.curves(f, curves) if curves else None, stats=_asked(asked))


def data_record(f: Formation, zones=None) -> Result:
    try:
        d = CATALOG["data_record"](f.view)
    except EvidenceError as e:
        raise ToolError(harness_names(str(e))) from None

    def plain(fact: str) -> str:                      # a primary log the workflow computed is not missing
        m = re.match(r"^primary logs missing from the well: (.*)$", fact)
        if m and m.group(1).strip() != "none":
            names = [x.strip() for x in m.group(1).split(",") if x.strip()]
            made = [x for x in names if x.upper() in f.inv.curves and np.isfinite(np.asarray(f.view.values(x.upper()), dtype=float)).any()]
            gone = [x for x in names if x not in made]
            fact = f"primary logs not in the input: {', '.join(gone) if gone else 'none'}" + (
                f"; computed by the workflow, with values here: {', '.join(made)}" if made else "")
        return fact
    return _result(f, {**d, "facts": [plain(x) for x in d.get("facts") or []]}, zones)


def unit_roles(f: Formation, zones=None) -> Result:
    """The workflow's flow roles (Petrophys flow_roles), as the workflow gives them: not re-ranked, re-labelled or added
    to."""
    return _run(f, "unit_roles", zones)


COMPUTED = {"lithology_stats": lithology_stats, "zone_contrast": zone_contrast, "curve_order": curve_order,
            "threshold_exceedance": threshold_exceedance, "spike_flags": spike_flags, "adjacent_jumps": adjacent_jumps,
            "vertical_sequence": vertical_sequence, "pay_summary": pay_summary, "core_vs_log": core_vs_log,
            "zone_classes": zone_classes, "formation_summary": formation_summary, "data_record": data_record,
            "unit_roles": unit_roles, "lag_correlation": lag_correlation}
# the main argument of each, for one-line listings and for a bare value ({"adjacent_jumps": "DTC"})
MAIN = {"lithology_stats": "curves", "zone_contrast": "curve", "curve_order": "curves", "threshold_exceedance": "curve",
        "spike_flags": "curves", "adjacent_jumps": "curve", "vertical_sequence": "curves", "zone_classes": "topic",
        "formation_summary": "curves", "lag_correlation": "curves"}
