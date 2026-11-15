"""The lookups the model calls (stats, runs, compare, profile, crossplot, section, step): which samples, grouped
how, measured how, on the framework in agent/engine.py."""

from __future__ import annotations

import re
from typing import Optional

import numpy as np

from petroharness.agent import engine as E
from petroharness.agent.engine import STATISTICS, Formation, Out, Result, ToolError, num  # noqa: F401
from petroharness.well import summary as S


def _where_line(out: Out, sel, condition=None) -> None:
    if sel is not None:                                            # with a flag it names that is not computed somewhere
        out.add(f"Samples where {sel.read}" + E.uncomputed_said(out.f, condition))


def stats(f: Formation, curves, zones=None, statistics=None, where=None) -> Result:
    """Each curve over each zone, the zones pooled and the whole interval, in that order (the one summary layer,
    petroharness.well.summary), one line per zone and curve, each naming both: the statistics asked for, or the
    default set with the geometric mean added by the shape of the curve's values; a flag's share set and class codes'
    shares by class, by the shape of the values (never a mean of codes); a statistic it does not compute, said with
    how to derive it."""
    asked, unknown = E.statistics(statistics)
    have = [c for c in ([curves] if isinstance(curves, str) else list(curves or [])) if str(c).strip().upper() in f.inv.curves]
    missing = list(dict.fromkeys(str(c).strip().upper() for c in ([curves] if isinstance(curves, str) else list(curves or []))
                                 if c not in have))
    cs = E.curves(f, have or curves)                       # none with data: the error names what exists
    zs = E.zones(f, zones)
    sel = E.where(f, where)
    out = Out(f)
    for note in unknown:
        out.add(note)
    if missing:                                            # a set named generically: some curves are not in this well
        known = E.known_names(f)
        nodata = [c for c in missing if c in known]
        unknown_names = [c for c in missing if c not in known]
        if nodata:
            out.add(f"No data in this interval for: {', '.join(nodata)}")
        if unknown_names:                                  # a name that is no curve (a typo is not an absence)
            out.add("No curve named " + "; ".join(f"{c}" + (f" (did you mean {E.near(f, c)}?)" if E.near(f, c) else "")
                                                     for c in unknown_names))
    _where_line(out, sel, where)
    blocks = _blocks(f, out, cs, zs, asked, sel)
    verdict = zone_mean_verdict(f, where, zs) if sel is not None else None
    _render(f, out, zs, blocks, [verdict] if verdict else [])
    return out.result()


def _thick(f: Formation, on: np.ndarray, b, zs: list) -> float:
    """The thickness of the set samples of a basis (the zones' convention: a zone's thickness x its share)."""
    return E.thickness(b.zone, int(on[b.idx].sum())) if b.zone is not None else E.set_thickness(f, on, b.kind, zs)


def _blocks(f: Formation, out: Out, cs: list, zs: list, asked, sel, suffix: str = "", empty: str = "") -> list:
    """Each curve's block on the summary layer: its label (with what its values are and its status), a row per zone,
    then the zones pooled, and the whole interval only where it differs from them (a sample outside the zones has a
    value), followed by what those outside samples hold; each row naming its basis and the curve (with its short
    cautions); (curve, values, kind, names, log, block, zone rows, tail lines). A flag gives the share set, class codes
    the share of each class (labelled where the record maps them; a class held only outside the zones says so), one
    value that value; values the statistics. empty: the text of a zone without values, after its n 0 of N (the
    statistics' n 0 when left out)."""
    d = f.depth
    blocks = []
    away = S.outside_mask(f.view)
    for c in cs:
        x = E.restricted(f, c, sel)
        k = E.kind(f, c)
        labels = E.codes(f, c)
        names, log = E.curve_statistics(f, c, asked)
        name = E.tagged(f, c)
        with np.errstate(invalid="ignore"):
            on = {code: np.isfinite(x) & (x == code) for code in k.codes} if k.kind in ("flag", "classes") else {}
        block = out.child()
        note = S.kind_note(k, labels) if k.kind != "values" else S.shape_note(np.asarray(f.view.values(c), dtype=float))
        lab = E.label(f, c)
        gone = E.uncomputed_note(f, c)                              # a flag whose inputs have no value somewhere
        if gone and "not computed" in lab:                          # its status tag already says so: one caution
            gone = ""
        block.add(lab + (f"; {note}" if note else "") + (f"; {gone}" if gone else "") + suffix)
        only_out = {code for code in on if on[code][away].any() and not on[code][~away].any()}
        rows, tail = [], []
        for b in E.bases(f, zs):
            if b.kind == "whole" and not S.differs(f.view, x):
                continue                                         # the whole interval is the zones pooled here
            row = out.child()
            text = _basis_values(f, c, row, x, k, labels, names, log, b.idx, b, zs, on, empty, only_out)
            if b.zone is not None:
                rows.append((b.zone.zone_id, f"  {row.zone(b.zone)}, {name}: " + text, row))
            else:
                head = f"  {_basis_label(row, b)}, {name}: "
                tail.append((head + text, row, (head, b.idx)))
            if b.kind == "whole":                                # what the samples outside the zones hold
                row = out.child()
                idx = np.flatnonzero(away)
                few = [n for n in names if n in S.OUTSIDE_STATISTICS]
                text = _basis_values(f, c, row, x, k, labels, few if len(few) > 1 else names, log, idx, None, zs, on,
                                     empty, set())
                head = f"  {S.outside_label(f.view, short=True)}, {name}: "
                tail.append((head + text, row, (head, idx)))
        blocks.append((c, x, k, names, log, block, rows, tail))
    return blocks


def _basis_values(f: Formation, c: str, row: Out, x, k, labels, names, log, idx, b, zs, on, empty, only_out) -> str:
    """One basis's values of curve c (b: the basis, None for the samples outside the zones). A flag computed from
    inputs with no value here reads "not computed", never 0."""
    idx = np.asarray(idx, dtype=int)
    away = b is None
    if not np.isfinite(x[idx]).any() and E.not_computed(f, c, idx):
        return f"n {row.i(0)} of {row.i(x[idx].size)}, {E.not_computed(f, c, idx)}"
    thick = (lambda m: f.inv.gross * float(m[idx].sum()) / max(f.depth.size, 1)) if away else \
        (lambda m: _thick(f, m, b, zs))
    if empty and not np.isfinite(x[idx]).any():                  # its counts too: every number is shown
        return f"n {row.i(0)} of {row.i(x[idx].size)}, {empty}"
    if k.kind == "flag":
        return E.flag_values(row, x[idx], thick(on[1.0]))
    if k.kind != "values":
        text = E.class_values(row, x[idx], k, labels, lambda code: thick(on[code]))
        for code in sorted(only_out):                           # a class the zones never hold: said in its cell
            cell = f"class {S.code_text(code, labels)} "
            text = re.sub(rf"({re.escape(cell)}[\d.]+% \(\d+ samples, [^)]*)\)", r"\1; only outside the zones)", text)
        return text
    return E.values(row, x[idx], f.depth[idx], names, log, zone=not away)


def _render(f: Formation, out: Out, zs: list, blocks: list, after: list) -> None:
    """The blocks into out: each curve's label, its zone rows, its zones pooled and whole interval, then after: (line,
    its numbers). When every zone's full row does not fit the size limit, each zone is shown on a shorter row: its id,
    the curve and fewer statistics (the richest set that lets every zone fit), or at last one row per zone naming each
    curve with its mean; the full rows are held in the result. When even those do not all fit, the first zones are
    shown. Every held row is named at the end of the text with the find that fetches it."""
    fixed = out.shown_chars + sum(len(ln) + 1 for b in blocks for ln in b[5].lines) \
        + sum(len(ln) + 1 for ln, _ in after)
    tails = {b[0]: [(ln, row) for ln, row, _ in b[7]] for b in blocks}       # the pooled, whole and outside lines
    full = tails
    lines = lambda ts: sum(len(ln) + 1 for t in ts.values() for ln, _ in t)
    room = E.max_chars() - 300 - fixed - lines(tails)
    size = lambda rows: sum(len(r[1]) + 1 for r in rows)
    shown = {b[0]: b[6] for b in blocks}                          # curve -> the zone rows shown under it
    across = []                                                   # or one row per zone, every curve in it
    if len(zs) > 1 and size([r for b in blocks for r in b[6]]) > room:
        for stats_ in _short_sets(blocks):                        # the shorter rows, the tail lines alike
            shown = {b[0]: [_short_row(f, b, z, stats_, out) for z in zs] for b in blocks}
            tails = {b[0]: _short_tail(f, b, stats_, out) for b in blocks}
            room = E.max_chars() - 300 - fixed - lines(tails)
            if size([r for rs in shown.values() for r in rs]) <= room:
                break
        else:
            if len(blocks) > 1:
                shown = {b[0]: [] for b in blocks}
                across = [_across_row(f, blocks, z, out) for z in zs]
    k = len(zs)
    while k and size([r for rs in ([across] if across else shown.values()) for r in rs[:k]]) > room - 120 * bool(across):
        k -= 1                                                    # the same zones of every curve
    if across:
        out.add("Each zone, every curve (its mean; a flag: the share set; class codes: each class's share):")
        for rid, ln, row in across[:k]:
            out.add(ln, row)
        for rid, ln, row in across[k:]:
            out.hold(ln, row, ("", rid, "zones {ids}"))
    for c, x, kind, names, log, block, rows, tail in blocks:
        short = shown[c] is not rows
        for rid, ln, row in shown[c][:k]:
            block.add(ln, row)
        for j, (rid, ln, row) in enumerate(rows):
            if short or j >= k:
                block.hold(ln, row, (c, rid, "the full rows of zones {ids}" if short and (across or j < k)
                                     else "zones {ids}"))
        for ln, row in tails[c]:
            block.add(ln, row)
        if tails[c] is not full[c]:                               # the full tail lines, held in the result
            for ln, row in full[c]:
                if (ln, row) not in tails[c]:
                    rid = next((w for w in ("these zones pooled", "zones pooled", "whole interval", "outside any zone")
                                if ln.strip().startswith(w)), "pooled")
                    block.hold(ln, row, (c, rid, "the full lines of {ids}"))
        out.extend(block)
    for ln, row in after:
        out.add(ln, row)


def _short_tail(f: Formation, b, stats_: list, out: Out) -> list:
    """A curve's pooled, whole-interval and outside lines with the shorter rows' statistics, no depths (values only;
    a flag's or class codes' lines are short already)."""
    c, x, kind, names, log = b[0], b[1], b[2], b[3], b[4]
    if kind.kind != "values":
        return [(ln, row) for ln, row, _ in b[7]]
    pick = [s for s in stats_ if s in names] or names[:2]
    rows = []
    for ln, row, (head, idx) in b[7]:
        r = out.child()
        few = [s for s in pick if s in S.OUTSIDE_STATISTICS] if head.startswith("  outside any zone") else pick
        rows.append((head + E.values(r, x[np.asarray(idx)], f.depth[np.asarray(idx)], few if len(few) > 1 else pick,
                                      log, at=False), r))
    return rows


def _across_row(f: Formation, blocks: list, z, out: Out) -> tuple:
    """One zone's row naming each curve with its mean (a flag: the share set; class codes: each class's share)."""
    row = out.child()
    parts = []
    for b in blocks:
        c, x, kind = b[0], b[1], b[2]
        xz = x[np.asarray(z.indices)]
        ok = np.isfinite(xz)
        if not ok.any():
            parts.append(f"{c} {E.not_computed(f, c, z.indices) or 'no data'}")
        elif kind.kind == "flag":
            parts.append(f"{c} set {row.pct(100 * float((xz[ok] > 0.5).mean()))}")
        elif kind.kind != "values":
            n, counts = S.class_counts(xz, kind.codes)
            parts.append(f"{c} " + ", ".join(f"class {S.code_text(code, E.codes(f, c))} {row.pct(100 * m / n)}"
                                             for code, m in counts))
        else:
            parts.append(f"{c} mean {row.v(S.statistic(xz, 'mean'))}")
    return z.zone_id, f"  {z.zone_id}: " + "; ".join(parts), row


def _short_sets(blocks: list) -> list:
    """The statistics of the shorter zone rows, richest first: those shown without the depths of min and max, then
    mean, median, min and max, then the mean (n always)."""
    union = list(dict.fromkeys(n for b in blocks if b[2].kind == "values" for n in b[3])) or ["n", "mean"]
    few = [n for n in union if n in ("n", "mean", "median", "min", "max")]
    mean = [n for n in union if n in ("n", "mean")]
    return [union, few if len(few) > 1 else union[:2], mean if len(mean) > 1 else union[:2]]


def _short_row(f: Formation, b, z, stats_: list, out: Out) -> tuple:
    """A zone's shorter row of one curve (zone id, curve, fewer statistics, no depths): (zone id, line, its Out)."""
    c, x, kind = b[0], b[1], b[2]
    row = out.child()
    xz = x[np.asarray(z.indices)]
    if not np.isfinite(xz).any() and E.not_computed(f, c, z.indices):
        text = f"n {row.i(0)}, {E.not_computed(f, c, z.indices)}"
    elif kind.kind == "flag":
        ok = np.isfinite(xz)
        text = f"n {row.i(ok.sum())}, set {row.pct(100 * float((xz[ok] > 0.5).mean()) if ok.any() else 0.0)}"
    elif kind.kind != "values":
        n, counts = S.class_counts(xz, kind.codes)
        labels = E.codes(f, c)
        text = f"n {row.i(n)}" + ((f", every value {S.code_text(kind.codes[0], labels)}" if n else "")
                                  if kind.kind == "one value" else
                                  "".join(f", class {S.code_text(code, labels)} {row.pct(100 * m / n)}" for code, m in counts))
    else:
        names = [s for s in stats_ if s in b[3]] or b[3][:2]
        text = E.values(row, xz, f.depth[np.asarray(z.indices)], names, b[4], at=False)
    return z.zone_id, f"  {z.zone_id}, {E.tagged(f, c)}: {text}", row


def _basis_label(out: Out, b) -> str:
    """A pooled basis by its name; the whole interval with the count of samples outside any zone (its extremes can sit
    there)."""
    if b.kind == "whole":
        return f"whole interval ({out.i(S.outside(out.f.view))} samples outside any zone)"
    return b.label


def zone_mean_verdict(f: Formation, condition: str, zs: list) -> Optional[tuple]:
    """(line, its numbers): the zones whose mean values meet a curve condition (each zone read by its means), with
    their share of the zones' thickness, for a condition of comparisons only (flags and classes are already counted
    sample by sample)."""
    if len(zs) < 2:                                              # one zone: its mean says nothing the samples do not
        return None
    cond = str(condition or "").strip()
    terms = [t for part in re.split(r"\s+or\s+", cond, flags=re.I) for t in re.split(r"\s+and\s+", part, flags=re.I)]
    if not cond or not terms or not all(E._TERM.match(t) for t in terms):
        return None
    means = _ZoneMeanView(f)
    try:
        sel = E.select(Formation(f.inv, means, f.store), cond)
    except ToolError:
        return None
    hit = [z for z in zs if np.asarray(z.indices).size and sel.mask[np.asarray(z.indices)].all()]
    row = Out(f)
    total = sum(z.thickness for z in zs) or 1.0
    names = S.zone_ids([z.zone_id for z in hit]) if hit else "none"
    on = ", ".join(sorted({t.upper() for t in re.findall(r"[A-Za-z][A-Za-z0-9_]*", cond)} & set(f.inv.curves)))
    text = (f"  zones whose means meet it (on {on}; each zone by its mean values): {names} ({row.i(len(hit))} of "
            f"{row.i(len(zs))} zones, {row.pct(100 * sum(z.thickness for z in hit) / total)} of their thickness)")
    return text, row


class _ZoneMeanView:
    """The view with each curve's samples replaced by their zone's mean (NaN between the zones)."""

    def __init__(self, f: Formation):
        self._f, self._cache = f, {}
        self.depth, self.zones = f.view.depth, f.view.zones

    def values(self, c):
        if c not in self._cache:
            x = np.asarray(self._f.view.values(c), dtype=float)
            out = np.full(x.size, np.nan)
            for z in self.zones:
                idx = np.asarray(z.indices)
                if idx.size and np.isfinite(x[idx]).any():
                    out[idx] = float(np.nanmean(x[idx]))
            self._cache[c] = out
        return self._cache[c]

    def __getattr__(self, name):
        return getattr(self._f.view, name)


def runs(f: Formation, condition: str, zones=None, limit: int = 20, min_thickness: Optional[float] = None,
         max_thickness: Optional[float] = None) -> Result:
    for name, v in (("min_thickness", min_thickness), ("max_thickness", max_thickness)):
        if v is not None and not (isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v) and v >= 0):
            raise ToolError(f"{name} must be a thickness of at least 0, not {v!r}")
    if max_thickness is not None and max_thickness <= 0:          # every run is thicker than 0: it would find none
        raise ToolError(f"max_thickness {max_thickness!r} keeps no run (every run is at least one sample thick); leave it "
                        "out for all runs, or give the largest thickness of the thin beds you want")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ToolError(f"limit must be a whole number of at least 1, not {limit!r}")
    sel = E.select(f, condition)
    zs, u = E.zones(f, zones), f.inv.depth_unit
    found = E.extent(f, sel.mask, zs)
    read = sel.read
    if min_thickness is not None or max_thickness is not None:      # thin beds, or only the thick ones
        lo, hi = min_thickness or 0.0, np.inf if max_thickness is None else max_thickness
        found = [r for r in found if lo <= E.thickness(r[3], r[2]) <= hi]
        read += "".join([f", runs at least {num(float(min_thickness))} {u} thick" if min_thickness is not None else "",
                         f", runs at most {num(float(max_thickness))} {u} thick" if max_thickness is not None else ""])
    out = Out(f)
    out.add(f"Runs where {read}, inside the zones ({out.i(len(found))} runs)" + E.uncomputed_said(f, condition))
    total = 0.0
    for z in zs:                                                  # each zone
        n = sum(r[2] for r in found if r[3] is z)
        t = E.thickness(z, n)
        total += t
        out.add(f"  {out.zone(z)}: {out.v(t)} {u} ({out.pct(100 * n / max(z.n_samples, 1))} of the zone)")
    verdict = zone_mean_verdict(f, condition, zs)                 # each zone by its mean values
    if verdict:
        out.add(*verdict)
    if zones:                                                     # the zones pooled
        whole = sum(z.thickness for z in zs)
        out.add(f"  zones asked: {out.v(total)} {u} ({out.pct(100 * total / whole if whole else 0.0)} of their thickness)")
    else:
        zt = f.view.zoned_thickness
        out.add(f"  all zones: {out.v(total)} {u} ({out.pct(100 * total / zt if zt else 0.0)} of the zoned thickness)")
    n_all = f.depth.size                                          # the whole interval, runs across zone boundaries too
    away = S.outside_mask(f.view)
    if (sel.mask & away).any() and getattr(f.view, "basis", "all") != "zones":    # only where it differs: then what
        every = _Whole(f)                                          #   the samples outside them hold, located
        whole_runs = E.extent(f, sel.mask, [every])
        if min_thickness is not None or max_thickness is not None:
            whole_runs = [r for r in whole_runs if lo <= E.thickness(every, r[2]) <= hi]
        n_sel = sum(r[2] for r in whole_runs)
        out.add(f"  whole interval ({out.i(S.outside(f.view))} samples outside any zone): "
                f"{out.v(f.inv.gross * n_sel / max(n_all, 1))} {u} ({out.pct(100 * n_sel / max(n_all, 1))} of the gross)")
        _outside_runs(f, out, sel.mask & away)
    if found:
        first, last = found[0], max(found, key=lambda r: r[1])
        out.add(f"  shallowest top {out.depth(first[0])} ({first[3].zone_id}); deepest base {out.depth(last[1])} "
                f"({last[3].zone_id})")
        cut = len(found) > limit
        listed = sorted(sorted(found, key=lambda r: -r[2])[:limit], key=lambda r: r[0]) if cut else found
        if cut:                                                    # a cut list says so, with the get of the others
            rest = [(z.zone_id, t, b, k, z) for t, b, k, z in found if (t, b, k, z) not in listed]
            kept, said = _keep_rest(f, EVERY_RUN, rest, lambda r: E.thickness(r[4], r[3]),
                                    lambda r: f"{num(r[1])}-{num(r[2])} ({num(E.thickness(r[4], r[3]))})")
            out.add(f"  longest runs (top-base, thickness, zone; {said}), top to base, {limit} of {len(found)}:")
        else:
            out.add(f"  every run, top to base (top-base, thickness, zone), {len(found)} of {len(found)}:")
        rows = []
        for top, base, n, z in listed:
            row = out.child()
            rows.append((f"{num(top)}-{num(base)}", f"    {row.span(top, base)}, {row.v(E.thickness(z, n))} {u}, {z.zone_id}", row))
        out.fit(rows, what="runs")
        if cut:
            for ln, nums in kept:                                  # the others, kept for the get, a zone a line
                out.keep(ln, nums + [E.thickness(z, k) for t, b, k, z in found if f"{num(t)}-{num(b)} (" in ln])
    return out.result()


EVERY_RUN = "other runs"


def _outside_runs(f: Formation, out: Out, mask) -> None:
    """The samples outside the zones where a selection holds, located: their thickness and the runs they form (a
    labelled gap, not a zone)."""
    d, u = f.depth, f.inv.depth_unit
    idx = np.flatnonzero(mask)
    if not idx.size:
        return
    breaks = np.flatnonzero(np.diff(idx) > 1)
    spans = [(int(a), int(b)) for a, b in zip(np.r_[idx[0], idx[breaks + 1]], np.r_[idx[breaks], idx[-1]])]
    row = out.child()
    cells = [row.v(d[a]) if a == b else f"{row.v(d[a])}-{row.v(d[b])}" for a, b in spans[:FULL_RUNS]]
    more = f" ... ({len(spans) - FULL_RUNS} more)" if len(spans) > FULL_RUNS else ""
    out.add(f"  {S.outside_label(f.view)}: {row.v(f.inv.gross * idx.size / max(d.size, 1))} {u} in "
            f"{row.i(len(spans))} runs: " + ", ".join(cells) + more, row)


class _Whole:
    """The whole interval as one group of samples (runs across zone boundaries and between the zones)."""

    def __init__(self, f: Formation):
        self.zone_id, self.indices = "whole interval", np.arange(f.depth.size)
        self.thickness, self.n_samples = f.inv.gross, max(f.depth.size, 1)


def compare(f: Formation, a: str, b: str, zones=None, tolerance: Optional[float] = None, where=None) -> Result:
    """Two curves where both have values: the zone level first (each zone's means: their rank correlation across the
    zones in words, and on one scale in how many zones a's mean is above b's), then each zone, the zones pooled and the
    whole interval where it differs (with the samples outside the zones): n of N, both means, a - b on one scale, the
    shares on each side, the rank correlation labelled with its n, the curves' ranges and its transform (ranks)."""
    a, b = E.curve(f, a), E.curve(f, b)
    if a == b:
        raise ToolError(f"compare needs two different curves; both are {a}")
    if tolerance is not None and not (isinstance(tolerance, (int, float)) and not isinstance(tolerance, bool)
                                      and np.isfinite(tolerance) and tolerance >= 0):
        raise ToolError(f"tolerance must be a number of at least 0, not {tolerance!r}")
    zs = E.zones(f, zones)
    sel = E.where(f, where)
    E.no_codes(f, "a comparison", a, b)
    same = E.same_scale(f, a, b)
    out = Out(f)
    _where_line(out, sel, where)
    out.add(f"{a} against {b}" + (f" (difference {a} - {b})" if same else
                                  " (different units or scales: means and rank correlation, no difference)"))
    out.add(f"  {E.label(f, a)}")
    out.add(f"  {E.label(f, b)}")
    xa, xb = E.restricted(f, a, sel), E.restricted(f, b, sel)
    _zone_level(f, out, zs, xa, xb, a, b, same)
    rows, tail = [], []
    away = S.outside_mask(f.view)
    for bs in E.bases(f, zs):
        if bs.kind == "whole" and not S.differs(f.view, np.where(np.isfinite(xa) & np.isfinite(xb), 0.0, np.nan)):
            continue
        row = out.child()
        text = E.pair(row, xa[bs.idx], xb[bs.idx], a, b, same, tolerance)
        if bs.zone is not None:
            rows.append((bs.zone.zone_id, f"  {row.zone(bs.zone)}: " + text, row))
        else:
            tail.append((f"  {_basis_label(row, bs)}: " + text, row))
        if bs.kind == "whole":
            row = out.child()
            tail.append((f"  {S.outside_label(f.view, short=True)}: " + E.pair(row, xa[away], xb[away], a, b, same,
                                                                              tolerance), row))
    out.fit(rows, E.max_chars() - sum(len(ln) + 1 for ln, _ in tail), label=f"{a} vs {b}")
    for ln, row in tail:
        out.add(ln, row)
    return out.result()


def _zone_level(f: Formation, out: Out, zs: list, xa, xb, a: str, b: str, same: bool, line=False) -> None:
    """The zone level, said first: each zone's mean of a and of b and how they move together across the
    zones - their rank correlation over the zones with its words, and on one scale in how many zones a's mean is above
    b's; line: also the least-squares line through the zone means (crossplot). One zone: none."""
    if len(zs) < 2:
        return
    pts = []
    for z in zs:
        idx = np.asarray(z.indices)
        ok = np.isfinite(xa[idx]) & np.isfinite(xb[idx])
        if ok.any():
            pts.append((z, float(np.mean(xa[idx][ok])), float(np.mean(xb[idx][ok]))))
    if len(pts) < 2:
        return
    depth = b == "DEPTH"                                              # a trend with depth: said as one
    row = out.child()
    head = (f"  zone level (each zone's mean of {a}" + (" and its depth" if depth else f" and of {b} where both have values")
            + f", {row.i(len(pts))} zones): ")
    if len(pts) >= 3:
        rc = E.rank_correlation([p[1] for p in pts], [p[2] for p in pts])
        words = S.order_words(rc, len(pts), lambda r: f"{a} {S.direction_words(r)}" if depth else E.together(r, a, b))
        text = (f"rank correlation of the zone means {row.v(rc)} over {row.i(len(pts))} zones ({words})"
                if np.isfinite(rc) else "the zone means hold no rank order")
        if line:
            ma, mb = np.array([p[1] for p in pts]), np.array([p[2] for p in pts])
            if np.ptp(mb) > 0:
                slope, icpt = np.polyfit(mb, ma, 1)
                r = float(np.corrcoef(mb, ma)[0, 1]) if np.ptp(ma) > 0 else 0.0
                text += (f"; the line through the zone means: slope {row.v(slope)}, intercept {row.v(icpt)}, R2 "
                         f"{row.v(r * r)} (n {row.i(len(pts))} zones)")
    else:
        (z1, a1, b1), (z2, a2, b2) = pts
        hi = z1 if a1 >= a2 else z2
        if a1 == a2:
            text = f"{z1.zone_id} and {z2.zone_id} have the same mean {a}"
        elif depth:
            text = f"{hi.zone_id}, the {'deeper' if hi is (z1 if b1 > b2 else z2) else 'shallower'} zone, has the higher mean {a}"
        else:
            text = (f"{hi.zone_id} has the higher mean {a} and the " + ("higher" if (a1 - a2) * (b1 - b2) > 0 else
                    "lower" if (a1 - a2) * (b1 - b2) < 0 else "same") + f" mean {b}")
    out.add(head + text, row)
    if same:                                                         # each zone by its means, on one scale
        hi = [z.zone_id for z, ma, mb in pts if ma > mb]
        lo = [z.zone_id for z, ma, mb in pts if ma <= mb]
        ok = np.isfinite(xa) & np.isfinite(xb)                       # the size beside the direction
        idx = np.unique(np.concatenate([np.asarray(z.indices) for z, _, _ in pts]))
        dd = (xa - xb)[idx][ok[idx]]
        md = float(np.mean([ma - mb for _, ma, mb in pts]))
        sd = float(np.std(dd)) if dd.size > 1 else float("nan")
        size = (f"; the zone means differ by {out.v(md)} on average, against an sd of {out.v(sd)} of {a} - {b} over the "
                f"zones' samples (mean / sd {out.v(md / sd)})" if np.isfinite(sd) and sd > 0 else "")
        out.add(f"  by zone mean: {a} above {b} in {len(hi)} of {len(pts)} zones"
                + (f" ({S.zone_ids(hi)})" if hi and len(hi) <= 12 else "")
                + (f"; below in {S.zone_ids(lo)}" if lo and len(lo) <= 12 else (f"; below in {len(lo)}" if lo else ""))
                + size)


def profile(f: Formation, curve: str, zones=None, statistics=None, where=None) -> Result:
    """One curve zone by zone from the top, then the zones pooled and the whole interval (as stats gives them); the zones
    ranked by each statistic shown, and each statistic's zone values against depth."""
    c = E.curve(f, curve)
    zs = sorted(E.zones(f, zones), key=lambda z: z.top)
    sel = E.where(f, where)
    out = Out(f)
    asked, unknown = E.statistics(statistics)
    for note in unknown:
        out.add(note)
    _where_line(out, sel, where)
    blocks = _blocks(f, out, [c], zs, asked, sel, ", zone by zone from the top", "no data")
    x, kind, names, log = blocks[0][1], blocks[0][2], blocks[0][3], blocks[0][4]
    after = []
    if kind.kind == "values":                                      # codes and flags have no statistics to rank
        ranked = [(z.zone_id, S.compute(x[np.asarray(z.indices)], names, log)) for z in zs
                  if np.isfinite(x[np.asarray(z.indices)]).any()]
        order = out.child()
        lines = S.rankings(ranked, names, order.v, c)
        after = [(f"  {ln}", order if k == len(lines) - 1 else None) for k, ln in enumerate(lines)]
        trend = out.child()
        depth = S.depth_order(ranked, {z.zone_id: (z.top + z.base) / 2 for z in zs}, names, trend.v,
                              E.rank_correlation, c)
        if depth:
            after.append((f"  {depth}", trend))
    _render(f, out, zs, blocks, after)
    if len(zs) == 1 and kind.kind == "values":                     # one zone: its trend inside it, by thirds of depth
        _thirds(f, out, zs[0], x, c)
    return out.result()


def _thirds(f: Formation, out, z, x, c: str) -> None:
    """a single zone's upper, middle and lower thirds (by sample order): depths, median and mean of curve c."""
    idx = np.asarray(z.indices)
    parts = [p for p in np.array_split(idx, 3) if p.size]
    if len(parts) < 3:
        return
    d = f.depth
    for name, p in zip(("upper third", "middle third", "lower third"), parts):
        xz = x[p]
        med = E.statistic(xz, "median")
        if np.isfinite(med):
            out.add(f"    {z.zone_id} {name} {out.span(float(d[p[0]]), float(d[p[-1]]))}, {c}: median {out.v(med)}, mean "
                    f"{out.v(E.statistic(xz, 'mean'))}, n {out.i(int(np.isfinite(xz).sum()))}")
        else:
            out.add(f"    {z.zone_id} {name} {out.span(float(d[p[0]]), float(d[p[-1]]))}, {c}: no data")


DEPTH_AXIS = ("DEPTH", "DEPT", "MD")


def _axis(f: Formation, name, sel, log: bool) -> tuple:
    """(name, values, unit) of a crossplot axis: a curve, or the sample depth (DEPTH) for a trend with depth; log10 of
    the values when asked (values at or below 0 have no logarithm and are left out)."""
    c = str(name).strip().upper()
    if c in DEPTH_AXIS and c not in f.inv.curves:
        c, x, unit = "DEPTH", f.depth.copy(), f.inv.depth_unit
        if sel is not None:
            x = np.where(sel.mask, x, np.nan)
    else:
        c = E.curve(f, name)
        x, unit = E.restricted(f, c, sel), f.inv.curves[c].unit or ""
    if log:
        with np.errstate(invalid="ignore", divide="ignore"):
            x = np.where(x > 0, np.log10(np.where(x > 0, x, 1.0)), np.nan)
        return f"log10({c})", x, f"log10 {unit}".strip()
    return c, x, unit


def _flag(v, name: str) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "yes", "1", "false", "no", "0", ""):
        return v.strip().lower() in ("true", "yes", "1")
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    raise ToolError(f"{name} must be true or false, not {v!r}")


def crossplot(f: Formation, y: str, x: str, zones=None, log_y=False, log_x=False, where=None) -> Result:
    """A least-squares line of y on x where both have values: the zone level first (each zone's means: their rank
    correlation across the zones in words and the line through them), then over each zone, the zones pooled and the
    whole interval where it differs (with the samples outside the zones): n of N, slope (y per unit of x), intercept,
    R2 and the correlation, labelled with its n, the ranges and the transform. x = DEPTH gives the trend with depth,
    in words; log_y fits log10(y), and the samples a logarithm leaves out are counted."""
    log_y, log_x = _flag(log_y, "log_y"), _flag(log_x, "log_x")
    sel = E.where(f, where)
    yn, yv, yu = _axis(f, y, sel, log_y)
    xn, xv, xu = _axis(f, x, sel, log_x)
    if yn == xn:
        raise ToolError(f"crossplot needs two different axes; both are {yn}")
    zs = E.zones(f, zones)
    bare = lambda n: n[6:-1] if n.startswith("log10(") else n
    E.no_codes(f, "a fitted line", *(bare(n) for n in (yn, xn)))
    out = Out(f)
    _where_line(out, sel, where)
    per = f" ({yu} per {xu})" if yu and xu else ""
    out.add(f"Least-squares line {yn} = intercept + slope * {xn}; slope{per}")
    for n in (yn, xn):                                   # the resolved names (a misspelt name is resolved:
        c = bare(n)                                      #   labelling the name as asked raised KeyError)
        out.add("  " + (f"DEPTH [{f.inv.depth_unit}] = sample depth" if c == "DEPTH"
                        else E.label(f, c) + (" (fitted as log10)" if n.startswith("log10(") else "")))
    ry, rx = (_axis(f, n, sel, False)[1] for n in (y, x))           # the values before any logarithm
    for n, raw, fitted in ((yn, ry, yv), (xn, rx, xv)):              # what a logarithm leaves out
        if n.startswith("log10("):
            gone = int((np.isfinite(raw) & ~np.isfinite(fitted)).sum())
            if gone:
                row = out.child()
                out.add(f"  log10 leaves out {row.i(gone)} of {row.i(int(np.isfinite(raw).sum()))} samples of "
                        f"{bare(n)} with a value (at or below 0)", row)
    _zone_level(f, out, zs, yv, xv, yn, xn, False, line=True)
    rows, tail = [], []
    away = S.outside_mask(f.view)
    fit = lambda row, idx: E.line_fit(row, xv[idx], yv[idx], (yn, xn), (ry[idx], rx[idx]))
    for bs in E.bases(f, zs):
        if bs.kind == "whole" and not S.differs(f.view, np.where(np.isfinite(xv) & np.isfinite(yv), 0.0, np.nan)):
            continue
        row = out.child()
        text = fit(row, bs.idx)
        if bs.zone is not None:
            rows.append((bs.zone.zone_id, f"  {row.zone(bs.zone)}, {yn} on {xn}: " + text, row))
        else:
            tail.append((f"  {_basis_label(row, bs)}, {yn} on {xn}: " + text, row))
        if bs.kind == "whole":
            row = out.child()
            tail.append((f"  {S.outside_label(f.view, short=True)}, {yn} on {xn}: " + fit(row, np.flatnonzero(away)),
                         row))
    out.fit(rows, E.max_chars() - sum(len(ln) + 1 for ln, _ in tail), label=f"{yn} on {xn}")
    for ln, row in tail:
        out.add(ln, row)
    return out.result()


def overlap(f: Formation, a: str, b: str, zones=None, limit: int = 12) -> Result:
    """Where two conditions or classes hold together and apart, each zone from the top: the thickness of A,
    of B, of A and B, of A without B and of B without A, with its share of the zone (a zone-by-class table); the zones
    where they hold together and apart; the samples outside the zones apart, labelled; then the runs of A and B, of A
    without B and of B without A, top to base by zone (every run up to limit, else the thickest with the get of every
    one). A and B: conditions in the runs grammar (a flag, a class section:CLASS, CURVE OP VALUE, joined by and/or)."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ToolError(f"limit must be a whole number of at least 1, not {limit!r}")
    if not str(a or "").strip() or not str(b or "").strip():
        raise ToolError(f"overlap needs two conditions, a and b; {E.GRAMMAR}")
    sa, sb = E.select(f, a), E.select(f, b)
    if re.sub(r"\s+", " ", str(a)).strip().upper() == re.sub(r"\s+", " ", str(b)).strip().upper():
        raise ToolError("overlap needs two different conditions; a and b are the same")
    zs = sorted(E.zones(f, zones), key=lambda z: z.top)
    u = f.inv.depth_unit
    A, B = sa.mask, sb.mask
    sets = [("A and B", A & B), ("A without B", A & ~B), ("B without A", B & ~A)]
    cols = [("A", A), ("B", B)] + sets
    out = Out(f)
    out.add(f"Overlap of A = {sa.read} and B = {sb.read}: each zone from the top, the thickness of each (in {u}) and "
            f"its share of the zone")
    for z in zs:
        idx = np.asarray(z.indices)
        row = out.child()
        cells = [f"{name} {row.v(E.thickness(z, int(m[idx].sum())))} ({row.pct(100 * m[idx].sum() / max(z.n_samples, 1))})"
                 for name, m in cols]
        out.add(f"  {row.zone(z)}: " + ", ".join(cells), row)
    total = sum(z.thickness for z in zs) or 1.0
    row = out.child()
    pooled = [(name, sum(E.thickness(z, int(m[np.asarray(z.indices)].sum())) for z in zs)) for name, m in cols]
    out.add(f"  {S.pooled_label(f.view, zs)}: " + ", ".join(f"{name} {row.v(t)} ({row.pct(100 * t / total)})"
                                                         for name, t in pooled), row)
    where = {name: [z.zone_id for z in zs if m[np.asarray(z.indices)].any()] for name, m in sets}
    none = [z.zone_id for z in zs if not (A | B)[np.asarray(z.indices)].any()]
    out.add("  zones: " + "; ".join(f"{name} in {len(ids)} of {len(zs)}" + (f" ({S.zone_ids(ids)})" if ids else "")
                                     for name, ids in where.items())
            + (f"; neither in {S.zone_ids(none)}" if none else ""))
    away = S.outside_mask(f.view)
    if ((A | B) & away).any():                                   # outside the zones: a labelled gap, not a zone
        row = out.child()
        n_all = max(f.depth.size, 1)
        out.add(f"  {S.outside_label(f.view)}: " + ", ".join(
            f"{name} {row.v(f.inv.gross * float((m & away).sum()) / n_all)}" for name, m in cols), row)
    kept = []
    for name, m in sets:                                         # where, located: top to base, zone by zone
        found = [(z.zone_id, top, base) for top, base, k, z in E.extent(f, m, zs)]
        if not found:
            out.add(f"  {name}: no run")
            continue
        head = f"  {name}, {out.i(len(found))} {_runs_word(len(found))}, top to base: "
        if len(found) <= limit:
            out.add(head + _zone_cells(f, found))
            continue
        pick = sorted(sorted(found, key=lambda r: -(r[2] - r[1]))[:limit], key=lambda r: r[1])
        step = float(getattr(f.view, "step", 0.0) or 0.0)
        lines, said = _keep_rest(f, f"{name} other runs", [r for r in found if r not in pick],
                                 lambda r: r[2] - r[1] + step, find=name)
        kept += lines
        out.add(head + _zone_cells(f, pick) + f"; {limit} of {len(found)} runs shown, the thickest; {said}")
    for ln, nums in kept:                                        # last: the shown lines come first in any get
        out.keep(ln, nums)
    return out.result()


# --- records --------------------------------------------------------------------------------------------------------

def section(f: Formation, key: str) -> Result:
    """One analyzer section as recorded, its classes as located runs: each class line starts with its label,
    then its criterion and its runs top to base, zone by zone (every run when the class has few, else the thickest,
    said so, with the runs call of every run), and its thickness and share last, on the line after; with few runs in
    the whole section, every run of every class top to base in one line; then the zones' value lines and the classes
    both ways."""
    k = re.sub(r"[:/\s]+", ".", str(key).strip())                   # hydrocarbon:x, hydrocarbon/x -> hydrocarbon.x
    match = [s for s in f.inv.sections if s.key == k] or [s for s in f.inv.sections if s.key.split(".", 1)[-1] == k] \
        or [s for s in f.inv.sections if s.key.split(".")[-1] == k.split(".")[-1]]     # its name under another family
    if not match:
        family = k.split(".", 1)[0]                                # a step's name, not a section's full key whose
        steps = [m.step for m in f.inv.methods if m.step == family    # family has no such section here
                 and ("." not in k or family not in {s.family for s in f.inv.sections})]
        if steps:                                                  # a step named as a section: its record (the call's
            return step(f, steps[0])                               #   meaning is plain; a refusal costs an action)
        hint = f"; {steps[0]} is a workflow step: call step" if steps else ""
        raise ToolError(f"no section {key!r}{hint}; sections: {', '.join(s.key for s in f.inv.sections)}")
    if len(match) > 1:
        raise ToolError(f"{key!r} names {len(match)} sections: {', '.join(s.key for s in match)}; give the full key")
    s = match[0]
    u = f.inv.depth_unit
    out = Out(f)
    out.add(f"{s.key}: {s.title}")
    if s.method:
        out.add(f"  method: {s.method}")
    if s.basis:
        out.add(f"  basis: {s.basis}")
    if s.thresholds:                                                 # the bands as recorded, unless they classified
        why = E.index_not_computed(f, s)                             #   nothing here
        out.add(f"  thresholds: none apply here ({why})" if why else f"  thresholds (as recorded): {s.thresholds}")
    if s.classes:                                                  # counted and named once, with the background
        bg = [c.name for c in s.classes if c.background]
        out.add(f"  classes ({out.i(len(s.classes))}): {', '.join(c.name for c in s.classes)}; background class "
                f"(a sample meeting no other class): {', '.join(bg) if bg else 'none'}; each class: its criterion, its "
                f"runs top to base zone by zone (depths in {u}), then its thickness and share")
    every = {c.name: _store_runs(f, s.key, c.name) for c in s.classes}
    total = sum(len(rs) for rs in every.values())
    if s.classes and 0 < total <= SEQUENCE_RUNS and len([c for c in s.classes if every[c.name]]) > 1:
        seq = sorted(((a, b, z, c) for c, rs in every.items() for z, a, b in rs), key=lambda r: (r[0], r[1]))
        out.add(f"  every run of every class, top to base ({out.i(total)} runs): "
                + "; ".join(f"{_depth_cell(f, a, b)} {c} ({z})" for a, b, z, c in seq))
    zone_rows = [o for o in s.other if re.match(r"^Z\d+ \(", o)]
    views = _class_views(f, s)                                       # each zone by its means and by its samples
    fixed = (sum(len(ln) + 1 for ln in out.lines) + sum(len(o) + 3 for o in s.other if o not in zone_rows)
             + min(sum(len(o) + 3 for o in zone_rows), 1500)        # zone value lines keep some room, the rest is named
             + sum(len(ln) + 1 for ln, _ in views)                   # the class views, and each class's size line
             + sum(len(c.name) + 70 for c in s.classes))
    room = max(160, (E.max_chars() - 200 - fixed) // max(len(s.classes), 1))
    for c in s.classes:
        _class_line(f, out, s, c, every[c.name], min(room, RUNS_ROOM) if len(every[c.name]) > FULL_RUNS else None)
    rows = []
    for o in s.other:
        m = re.match(r"^(Z\d+) \(", o)
        if m:                                                        # a zone's values: fitted, the rest named
            rows.append((m.group(1), f"  {o}", None))
        else:
            out.add(f"  {o}")
    out.fit(rows, E.max_chars() - sum(len(ln) + 1 for ln, _ in views), label=s.key)
    for ln, nums in views:
        out.add_numbers(ln, nums)
    return out.result()


FULL_RUNS = 12             # a class with at most this many runs is listed in full, whatever the room
RUNS_ROOM = 700            # characters for a longer class's run list (its thickest runs, with the runs call of every run)
SEQUENCE_RUNS = 16         # a section with at most this many runs over all its classes also lists them top to base


def _class_line(f: Formation, out: Out, s, c, every: list, room: Optional[int]) -> None:
    """One class as located runs: its label first, its criterion (the recorded definition), background or not, its runs
    top to base grouped by zone, written last on the line so the ledger's run reader takes each run's zone (every run;
    a long list cut to its thickest within room, said as "thickest k of N: ..." and ended with the condition that lists
    every run, "... (every run: condition KEY:NAME)"), then, on the next line, its thickness and share of the zoned
    thickness."""
    u = f.inv.depth_unit
    head = f"  {c.name}: " + (f"criterion {c.definition}; " if c.definition else "") \
        + ("background class; " if c.background else "")
    if not every:                                                    # no store: the record's own listing
        n = f"{out.i(c.intervals)} {_runs_word(c.intervals)}, top to base; " if c.intervals is not None else ""
        out.add(head + n + "runs: " + c.runs)
    else:
        cells = _zone_cells(f, every)
        if room is not None and len(head) + len(cells) + 80 > room:  # too many to show: the thickest, said so
            more = f" ... (every run: condition {s.key}:{c.name})"
            pick = _thickest(f, every, room - len(head) - len(more) - 60)
            cells = f"thickest {len(pick)} of {len(every)}: " + _zone_cells(f, pick, sized=True) + more
        out.add(head + f"{out.i(len(every))} {_runs_word(len(every))}, top to base; runs: " + cells)
    if c.thickness is not None or c.share_pct is not None:          # its size, last
        size = ", ".join(([f"{out.v(c.thickness)} {u}"] if c.thickness is not None else [])
                         + ([f"{c.share_pct}% of the zoned thickness"] if c.share_pct is not None else []))
        out.add(f"    {c.name} in all: {size}")


def _zone_shares(f: Formation, every: list) -> list:
    """[(zone id, share in % of the zone's samples)] of a class's runs (zone, top, base), one entry per zone it occurs in."""
    zones = {z.zone_id: z for z in f.view.zones}
    by = {}
    for z, a, b in every:
        by.setdefault(z, []).append((a, b))
    out = []
    for zid, rr in by.items():
        z = zones.get(zid)
        if z is None:
            continue
        idx = np.asarray(z.indices)
        if idx.size == 0:
            continue
        d = f.depth[idx]
        on = np.zeros(idx.size, dtype=bool)
        for a, b in rr:
            on |= (d >= a) & (d <= b)
        out.append((zid, round(100.0 * float(on.sum()) / idx.size, 1)))
    return out


KEPT_CHARS = 4500          # the other runs of a cut list kept for its get: what one get returns (the thickest first)


def _keep_rest(f: Formation, label: str, rest: list, thick, cell=None, find: str = None) -> tuple:
    """The runs a cut list does not show, kept for its get (Out.keep), a zone a line, as many as one get returns
    (the thickest first, each zone's in depth order): ([(line, its numbers)], the clause the shown line ends with).
    rest: [(zone id, top, base, ...)]; thick(run) its thickness; cell(run) its text (the depths as recorded); find: the
    words of the get (the label when none)."""
    cell = cell or (lambda r: _depth_cell(f, r[1], r[2]))
    keep, used = [], 0
    for r in sorted(rest, key=lambda r: -thick(r)):
        size = len(cell(r)) + 2
        if keep and used + size > KEPT_CHARS:
            break
        keep.append(r)
        used += size
    lines = []
    for zid in dict.fromkeys(r[0] for r in sorted(rest, key=lambda r: r[1])):
        mine = sorted((r for r in keep if r[0] == zid), key=lambda r: r[1])
        if mine:
            lines.append((f"  {label} in {zid}: " + ", ".join(cell(r) for r in mine),
                          [v for r in mine for v in ((r[1],) if r[1] == r[2] else (r[1], r[2]))]))
    left = [r for r in rest if r not in keep]
    u = f.inv.depth_unit
    said = f'the {"other runs" if not left else f"next {len(keep)} by thickness"}: {E.CUT_GET} "{find or label}"'
    if left:
        said += f"; the other {len(left)}, each at most {num(max(thick(r) for r in left))} {u} thick, are not listed"
    return lines, said


def _runs_word(n: int) -> str:
    return "run" if n == 1 else "runs"


def _depth_cell(f: Formation, a: float, b: float) -> str:
    """A run's depths as the record writes them (9306.0; a single sample is one depth)."""
    step = float(getattr(f.view, "step", 0.0) or 0.0)
    dec = len(f"{step:.6f}".rstrip("0").split(".")[1]) if step and step != int(step) else 0
    d = (lambda x: f"{x:.{dec}f}") if dec else num
    return d(a) if a == b else f"{d(a)}-{d(b)}"


def _zone_cells(f: Formation, runs: list, sized: bool = False) -> str:
    """Runs (zone, top, base) top to base, grouped by zone, each zone with its rock: 'Z1 (SAND) a, b-c; Z2 (SHALE) d-e'
    (a single sample is one depth); sized: each run with its thickness ('b-c (1.5 ft)'), for a list cut to its
    thickest runs."""
    step = float(getattr(f.view, "step", 0.0) or 0.0)
    by = {}
    for z, a, b in sorted(runs, key=lambda r: (r[1], r[2])):
        by.setdefault(z, []).append(_depth_cell(f, a, b) + (f" ({num(b - a + step)} {f.inv.depth_unit})" if sized else ""))
    lith = {z.zone_id: z.lithology for z in f.view.zones}          # each run's zone with its rock (a screen's gate)
    return "; ".join(f"{z}{f' ({lith[z]})' if z in lith else ''} {', '.join(cells)}" for z, cells in by.items())


def _thickest(f: Formation, every: list, room: int) -> list:
    """The thickest runs of a class that fit room characters (at least one), in depth order."""
    pick = []
    for r in sorted(every, key=lambda r: -(r[2] - r[1])):
        if pick and len(_zone_cells(f, pick + [r], sized=True)) > room:
            break
        pick.append(r)
    return sorted(pick, key=lambda r: r[1])


def _store_runs(f: Formation, key: str, label: str) -> list:
    """Every run of a section's class as (zone, top, base), from the analyzer store (the section record lists the
    first runs only); [] without a store."""
    sec = (f.store.sections.get(key) if f.store is not None else None)
    rs = (sec.classes.get(label) if sec is not None else None) or []
    return [(r.zone, float(r.top), float(r.base)) for r in rs]


ZONE_MEAN_FAMILIES = ("porosity", "permeability", "saturation", "lithology", "hydrocarbon")   # classes of a property's
# value; the numerical family's classes count samples (deviations, gradients), which a zone mean does not have


def zone_mean_labels(f: Formation, key: str) -> dict:
    """{zone id: label}: the section's analyzer run on each zone's mean values (one class per zone); {} where the
    family's classes count samples, or no zone-mean run is possible here."""
    fam, _, name = key.partition(".")
    if fam not in ZONE_MEAN_FAMILIES or f.view is None:
        return {}
    topics = (f.view.reg.topics or {}).get("topics") or {}
    topic = next((t for t, specs in topics.items() if any(fa == fam and name in secs for fa, secs in specs)), None)
    if topic is None:
        return {}
    cache = f.__dict__.setdefault("_zone_mean_cache", {})
    if topic not in cache:
        try:
            from petroharness.record.catalog import zone_classes_raw
            cache[topic] = zone_classes_raw(f.view, topic)
        except Exception:  # noqa: BLE001  (no zone-mean run here: the sample view stands alone)
            cache[topic] = None
    return dict(((cache[topic] or {}).get("classes", {}).get(name)) or {})


def sample_masks(f: Formation, key: str, classes: list) -> dict:
    """{label: the interval samples in that class's runs} for the named classes of a section (the analyzer store)."""
    if f.store is None or key not in f.store.sections:
        return {}
    labels = {str(lab).strip().upper(): rs for lab, rs in f.store.sections[key].classes.items()}
    return {c: E._class_mask(f, labels[c.upper()]) for c in classes if c.upper() in labels}


def _class_views(f: Formation, s) -> list:
    """[(line, numbers)]: the section's classes both ways (petroharness.well.summary.class_views): each zone's class
    from its mean values and the share of its samples in each class, then over the zones and the whole interval."""
    named = [c.name for c in s.classes if not c.background]
    masks = sample_masks(f, s.key, named)
    if not named or not masks:                                       # background only: no class to place
        return []
    by_mean = zone_mean_labels(f, s.key)
    bg = [c.name for c in s.classes if c.background]
    cv = S.class_views(f.view, by_mean, masks, bg, num, lambda p: f"{float(p):.1f}%", f.inv.depth_unit)
    out = [("  class views (each zone's class from its mean values, and the share of its samples in each class; then "
            "the zones pooled, and the samples outside the zones where there are any):", [])]
    for z, lab, text, nums in cv.zones:
        out.append((f"    {z.zone_id} {E.zone_name(z)} {num(z.top)}-{num(z.base)} {f.inv.depth_unit}: "
                    + (f"by its mean {lab}; " if lab is not None else "") + f"samples {text}", [z.top, z.base] + nums))
    return out + [(f"    {t}", n) for t, n in [v for v in (cv.pooled, cv.whole) if v]]


# where a value came from, requested against used, sample tallies: the record's bookkeeping, counted for the whole well
_BOOKKEEPING = ("_source", "_requested", "_count", "_counts", "_samples", "_reason", "_basis", "_metadata", "_sources",
                "_attempted_methods", "_rejected_models", "_used")
_TALLY = {"samples", "count", "counts", "n_samples", "sample_count"}


def _plain(v):
    """A nested parameter without its sample tallies (they count the whole well, not this interval)."""
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items() if str(k) not in _TALLY and not str(k).endswith(_BOOKKEEPING)}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def step(f: Formation, name: str) -> Result:
    m = next((m for m in f.inv.methods if m.step == str(name).strip()), None)
    if m is None:
        raise ToolError(f"no step {name!r} in the record; steps: {', '.join(x.step for x in f.inv.methods)}")
    from petroharness.agent.map import parameter
    from petroharness.record.card import input_text, plain_inputs
    out = Out(f)
    out.add(f"step {m.step}: method {m.method}")
    if m.inputs:                                   # a fallback input in plain words: "A where present, otherwise B"
        out.add(f"  inputs: {', '.join(input_text(i) for i in m.inputs)}")
    wrote = [c for c, cv in f.inv.curves.items() if cv.source == "computed" and cv.step == m.step]
    if wrote:                                      # a curve with one value for the whole well: a parameter
        cv = f.inv.curves
        par = [c for c in wrote if getattr(cv[c], "well_value", None) is not None]
        out.add("  curves: " + ("; " if par else ", ").join(parameter(cv[c], m.step) if c in par else c for c in wrote))
    for e in m.equations_here:
        out.add(f"  equation: {plain_inputs(e, m.inputs)}")
    for k, v in m.parameters.items():
        if k.endswith(_BOOKKEEPING):
            continue
        v = _plain(v)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.add(f"  {k}: {out.v(v)}")
        elif isinstance(v, str):
            out.add(f"  {k}: {v}")
        elif isinstance(v, (list, dict)) and v:
            out.add(f"  {k}: {v}")
    for d in m.decisions_here:
        out.add(f"  record: {plain_inputs(d, m.inputs)}")
    return out.result()
