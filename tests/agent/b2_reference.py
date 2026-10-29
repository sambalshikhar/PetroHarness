"""The tool reference: what each tool should return, written apart from src/petroharness/agent/tools.py (its own condition parser on Python's
ast, its own run finder and statistics), and parsers that read a tool's text back into numbers.

Nothing here imports petroharness.agent.tools; the tests compare the two.
"""
from __future__ import annotations

import ast
import math
import re

import numpy as np
from scipy.stats import spearmanr

# --- conditions -----------------------------------------------------------------------------------------------------

_OPS = {ast.Lt: np.less, ast.LtE: np.less_equal, ast.Gt: np.greater, ast.GtE: np.greater_equal, ast.Eq: np.equal,
        ast.NotEq: np.not_equal}


def condition_mask(text: str, values, is_flag=lambda c: False) -> np.ndarray:
    """Evaluate terms joined by and/or (any case) over interval samples; values(curve) -> array. A term is CURVE OP
    NUMBER, CURVE OP CURVE ('=' is '=='), or a name: a flag (> 0.5), a curve (has a value). A missing value never
    satisfies a comparison."""
    expr = re.sub(r"\b(and|or)\b", lambda m: m.group(1).lower(), text, flags=re.I)
    expr = re.sub(r"(?<![<>=!])=(?!=)", "==", expr)
    tree = ast.parse(expr.strip(), mode="eval").body

    def ev(node):
        if isinstance(node, ast.BoolOp):
            parts = [ev(v) for v in node.values]
            out = parts[0]
            for p in parts[1:]:
                out = (out & p) if isinstance(node.op, ast.And) else (out | p)
            return out
        if isinstance(node, ast.Name):
            x = np.asarray(values(node.id.upper()), dtype=float)
            with np.errstate(invalid="ignore"):
                return (x > 0.5) if is_flag(node.id.upper()) else np.isfinite(x)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            x = np.asarray(values(node.left.id.upper()), dtype=float)
            rhs = node.comparators[0]
            v = np.asarray(values(rhs.id.upper()), dtype=float) if isinstance(rhs, ast.Name) else _number(rhs)
            with np.errstate(invalid="ignore"):
                return _OPS[type(node.ops[0])](x, v) & np.isfinite(x) & np.isfinite(v)
        raise ValueError(f"not a condition: {ast.dump(node)}")
    return ev(tree)


def _number(node) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _number(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    raise ValueError("not a number")


def zone_runs(mask: np.ndarray, zones) -> list:
    """(top index, base index, zone position) for each stretch of consecutive True samples inside one zone."""
    out = []
    for k, z in enumerate(zones):
        idx = np.asarray(z.indices)
        start = None
        for j in range(idx.size):
            if mask[idx[j]]:
                if start is not None and idx[j] != idx[j - 1] + 1:
                    out.append((idx[start], idx[j - 1], k))
                    start = None
                if start is None:
                    start = j
            elif start is not None:
                out.append((idx[start], idx[j - 1], k))
                start = None
        if start is not None:
            out.append((idx[start], idx[-1], k))
    return out


def thickness(z, n: int) -> float:
    return (z.base - z.top) * n / z.n_samples


# --- statistics -----------------------------------------------------------------------------------------------------

def log_shaped(x) -> bool:
    """The summary layer's shape rule, written apart: positive values spanning more than two orders of magnitude."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return bool(x.size >= 2 and (x > 0).all() and math.log10(x.max() / x.min()) > 2)


def names(x) -> list:
    """The default statistics of a curve with values x (n, mean, median, p10, p90, min, max; geo_mean by shape)."""
    return ["n", "mean", "median"] + (["geo_mean"] if log_shaped(x) else []) + ["p10", "p90", "min", "max"]


def summary(x, log: bool = False) -> dict:
    """numpy's statistics of x; on a log-shaped curve (log) p10 and p90 on log10 values."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    x = x[np.isfinite(x)]
    if x.size == 0:
        return {"n": 0}
    s = sorted(x.tolist())
    out = {"n": len(s), "mean": math.fsum(s) / len(s), "median": float(np.median(s)), "min": s[0], "max": s[-1],
           "p10": float(np.quantile(s, 0.1)), "p90": float(np.quantile(s, 0.9)),
           "p25": float(np.quantile(s, 0.25)), "p75": float(np.quantile(s, 0.75)),
           "std": math.sqrt(math.fsum((v - math.fsum(s) / len(s)) ** 2 for v in s) / len(s))}
    out["variance"] = out["std"] ** 2                                  # every statistic the layer serves
    out["range"] = s[-1] - s[0]
    vals, counts = np.unique(np.round(np.asarray(s), 4), return_counts=True)
    out["mode"] = float(vals[int(np.argmax(counts))])                  # the most frequent value to 4 decimals
    if out["mean"] != 0:
        out["cv"] = out["std"] / out["mean"]
    if s[0] > 0:
        out["geo_mean"] = math.exp(math.fsum(math.log(v) for v in s) / len(s))
        out["harmonic_mean"] = len(s) / math.fsum(1 / v for v in s)
        if log:
            out["p10"], out["p90"], out["p25"], out["p75"] = (float(10 ** np.quantile(np.log10(s), q))
                                                              for q in (0.1, 0.9, 0.25, 0.75))
    out["iqr"] = out["p75"] - out["p25"]
    return out


def class_shares(line: str) -> dict:
    """{code: (share %, samples)} of a class-codes line ('class 5 (SILT) 88.3% (106 samples, 15.9 m)')."""
    return {float(c): (float(p), int(k)) for c, p, k in re.findall(r"class (-?\d+)(?: \([^)]*\))? ([\d.]+)% \((\d+) samples", line)}


def rank_corr(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3 or np.std(a[ok]) == 0 or np.std(b[ok]) == 0:
        return float("nan")
    return float(spearmanr(a[ok], b[ok]).statistic)


# --- reading outputs back -------------------------------------------------------------------------------------------

NUM = r"-?\d+(?:\.\d+)?"


_ZONE_MEAN_DROP = ("  by zone mean:",)


def plain(text: str) -> str:
    """A tool's text with its added labels read as the default ones (test_views_and_scope.py checks the additions
    themselves): the whole interval's between-zones note, the zone after an extreme's depth, the words after a
    coefficient, the display-size note and the zone-mean verdict lines."""
    text = re.sub(r"; positive values spanning [\d.]+ orders of magnitude: the geometric mean is added and the "
                  r"percentiles are read on log10 values", "", text)
    text = re.sub(rf"( at {NUM} \S+) \((?:Z\d+|between zones)\)", r"\1", text)
    text = re.sub(r" \((?:negligible|(?:weak|moderate|fairly strong|strong) (?:positive|negative))\)", "", text)
    text = text.replace("not shown in this view (its size limit; the data are there):", "left out to keep this short:")
    # each value line names its curve after its basis ("  Z1 SILT ... m, PHIE: ", "  zones pooled, PERM on
    # PHIE: "), each ranking and depth order the curve, each third its zone: read as the block's lines
    text = _LABEL.sub(r"\1: ", text)
    text = re.sub(r"\b(highest|lowest) zone by each statistic of \S+:", r"\1 zone by each statistic:", text)
    text = re.sub(r"each zone's \S+ value with its mid-depth", "each zone's value with its mid-depth", text)
    text = re.sub(r"(?m)^    Z\d+ (upper|middle|lower) third", r"    \1 third", text)
    # the direction in words (test_tool_lines.py checks these; a coefficient's label is read past by fields)
    text = re.sub(r" \((?:higher upward|higher downward|no order with depth)\)", "", text)
    text = re.sub(r"; \S+ (?:higher upward|higher downward|no order with depth)$", "", text, flags=re.M)
    text = re.sub(r" over \d+ zones; positive: higher deeper, negative: higher upward\)", "; positive: higher deeper)", text)
    return "\n".join(ln for ln in text.split("\n") if not ln.startswith(_ZONE_MEAN_DROP))


_COEF = re.compile(r" \((?:Spearman|Pearson)[^()]*(?:\([^()]*\)[^()]*)*\)")


_LABEL = re.compile(r"(?m)^(  [^:\n]*?), (?:log10\()?[A-Z][A-Za-z0-9_]*\)?(?: \([a-z][a-z ,]*\))?"
                    r"(?: on (?:log10\()?[A-Z][A-Za-z0-9_]*\)?)?: ")
_SHORT = re.compile(r"^  Z\d+, ")                 # a zone's shorter row, shown when the full rows do not fit
_TAILS = ("  zones pooled, ", "  these zones pooled, ", "  whole interval (", "  outside any zone (")


def plain_tool(fn):
    """A tool whose Result text is plain() and holds the whole result (every full row the item keeps, the
    shorter rows and the cut line of the text shown left out); the text shown is kept as .shown."""
    import functools

    from petroharness.agent.engine import Result

    @functools.wraps(fn)
    def run(*a, **kw):
        r = fn(*a, **kw)
        if not isinstance(r, Result):
            return r
        lines = [ln for ln, _ in r.rows if not _SHORT.match(ln)]
        # with shorter rows shown, the tail lines are shown short too and their full lines held after them: read the
        # full one
        head = lambda ln: ln.split(": ", 1)[0] if ln.startswith(_TAILS) else None
        later = [head(ln) for ln in lines]
        lines = [ln for i, ln in enumerate(lines) if head(ln) is None or head(ln) not in later[i + 1:]]
        out = Result(plain("\n".join(lines)), r.numbers, r.rows)
        out.shown = r.text
        return out
    return run


def fields(line: str) -> dict:
    """'name value' pairs after the line's colon: 'n 12, mean 0.1, difference mean -0.02' -> {..}."""
    body = line.split(": ", 1)[1] if ": " in line else line
    body = _COEF.sub("", body)                     # a coefficient's label (its kind, n and ranges)
    out = {}
    for part in body.split(", "):
        part = part.strip()
        m = re.match(r"^n (\d+) of (\d+)$", part)
        if m:
            out["n"], out["n_of"] = float(m.group(1)), float(m.group(2))
            continue
        m = re.match(rf"^(min|max) ({NUM}) at ({NUM}) \S+$", part)
        if m:
            out[m.group(1)], out[m.group(1) + "_at"] = float(m.group(2)), float(m.group(3))
            continue
        m = re.match(rf"^set in (\d+) samples \(({NUM})% of those with a value\)$", part)
        if m:
            out["set"], out["set_share"] = float(m.group(1)), float(m.group(2))
            continue
        m = re.match(rf"^thickness ({NUM}) \S+$", part)
        if m:
            out["thickness"] = float(m.group(1))
            continue
        m = re.match(rf"^beyond ({NUM}): ({NUM})%$", part)
        if m:
            out["beyond"] = float(m.group(2))
            continue
        m = re.match(rf"^\S+ ([<>]) \S+(?: [+-] {NUM})? in ({NUM})%$", part)      # which way it differs
        if m:
            out["above" if m.group(1) == ">" else "below"] = float(m.group(2))
            continue
        m = re.match(rf"^(?:within {NUM}|equal) in ({NUM})%$", part)
        if m:
            out["within"] = float(m.group(1))
            continue
        m = re.match(rf"^(.*?) ({NUM}|n/a)$", part)
        if m:
            out[m.group(1)] = float("nan") if m.group(2) == "n/a" else float(m.group(2))
    return out


def zone_lines(text: str) -> dict:
    """Zone id -> its line, for lines '  Zk ...'."""
    return {m.group(1): ln for ln in text.splitlines() for m in [re.match(r"^  (Z\d+) ", ln)] if m}


def left_out(text: str) -> list:
    m = re.search(r"\((\d+) zones left out to keep this short: ([^;]+);", text)
    if not m:
        return []
    which = m.group(2)
    r = re.fullmatch(r"Z(\d+) to Z(\d+)", which)
    return [f"Z{i}" for i in range(int(r.group(1)), int(r.group(2)) + 1)] if r else [w.strip() for w in which.split(",")]


def runs_output(text: str) -> dict:
    lines = text.splitlines()
    head = re.search(r"\((\d+) runs\)", lines[0])
    out = {"count": int(head.group(1)), "zones": {}, "total": None, "share": None, "listed": [], "of": None,
           "whole": None}
    for ln in lines[1:]:
        m = re.match(rf"^  whole interval(?: \(\d+ samples outside any zone\))?: ({NUM}) \S+ \(({NUM})% of the gross\)$", ln)
        if m:
            out["whole"] = (float(m.group(1)), float(m.group(2)))
        m = re.match(rf"^  (Z\d+) .*: ({NUM}) \S+ \(({NUM})% of the zone\)$", ln)
        if m:
            out["zones"][m.group(1)] = (float(m.group(2)), float(m.group(3)))
        m = re.match(rf"^  (?:all zones|zones asked): ({NUM}) \S+ \(({NUM})% of (?:the zoned|their) thickness\)$", ln)
        if m:
            out["total"], out["share"] = float(m.group(1)), float(m.group(2))
        m = re.match(rf"^    ({NUM})-({NUM}) \S+, ({NUM}) \S+, (Z\d+)$", ln)
        if m:
            out["listed"].append((float(m.group(1)), float(m.group(2)), float(m.group(3)), m.group(4)))
        m = re.search(r"longest runs .*?, (\d+) of (\d+):", ln)
        if m:
            out["of"] = (int(m.group(1)), int(m.group(2)))
    return out


def agrees(shown: float, want: float) -> bool:
    """A shown number agrees with the reference at the precision it is shown (petroharness.agent.map.num: 4 decimals at or above 1,
    4 significant figures below 1)."""
    if not (np.isfinite(shown) and np.isfinite(want)):
        return np.isnan(shown) and np.isnan(want)
    a = abs(want)
    half = 0.5e-4 if a >= 1 else (0.5 * 10 ** (math.floor(math.log10(a)) - 3) if a >= 1e-12 else 1e-12)
    return abs(shown - want) <= half * 1.001 + 1e-12 + 1e-9 * a


# --- the zone table (every zone in one table when per-curve zone rows would not fit) ---------------------------------

TABLE_HEAD = "Each zone, a column per curve (n = samples with a value of the first curve"


def zone_table(text: str):
    """A stats output's zone table -> {"stats": [...], "at": bool, "curves": [...], "rows": {zone id: (n, [cell, ...])}}
    (None without a table); a cell is the text between the bars."""
    lines = text.splitlines()
    i = next((k for k, ln in enumerate(lines) if ln.startswith(TABLE_HEAD)), None)
    if i is None:
        return None
    spec = [s.strip() for s in re.search(r"a cell: ([^;]+);", lines[i]).group(1).split(" / ")]
    curves = [c.strip() for c in lines[i + 1].split("|")[2:]]
    rows = {}
    for ln in lines[i + 2:]:
        m = re.match(r"^  (Z\d+)\b[^|]*\| (\d+) \| (.*)$", ln)
        if m:
            rows[m.group(1)] = (int(m.group(2)), [c.strip() for c in m.group(3).split(" | ")])
    return {"stats": [s.split("@")[0] for s in spec], "at": any("@" in s for s in spec), "curves": curves, "rows": rows}


def without_table(text: str) -> str:
    """The output without its zone table (the per-curve blocks after it: their pooled and whole-interval lines)."""
    lines = text.splitlines()
    i = next((k for k, ln in enumerate(lines) if ln.startswith(TABLE_HEAD)), None)
    if i is None:
        return text
    rows, k = {i, i + 1}, i + 2
    while k < len(lines) and re.match(r"^  Z\d+\b[^|]*\| ", lines[k]):
        rows.add(k)
        k += 1
    return "\n".join(ln for j, ln in enumerate(lines) if j not in rows or (ln.startswith("  (") and "zones" in ln))


def check_zone_table(text: str, zones: dict, want_zones: list, curves: dict, depth, flags=(), full: dict = None,
                     asked=None) -> list:
    """Every cell of a zone table against numpy: each zone shown or named as not shown; a row's n is the first curve's
    count, a cell's own n where it differs; each statistic (and its depth) at the precision shown; a flag's share of the
    zone set. curves: name -> values (a selection already applied); full: name -> the curve's values over the interval,
    whose shape decides the geometric mean and log10 percentiles (curves when left out); asked: the statistics the call
    named (the default set by shape when none)."""
    tab = zone_table(text)
    bad = []
    if tab is None:
        return [("no zone table",)]
    if tab["curves"] != list(curves):
        return [("table curves", tab["curves"], list(curves))]
    gone = left_out(text)
    d = np.asarray(depth, dtype=float)
    for zid in want_zones:
        if zid not in tab["rows"]:
            if zid not in gone:
                bad.append(("zone missing, not said", zid))
            continue
        n0, cells = tab["rows"][zid]
        idx = np.asarray(zones[zid].indices)
        first = True
        for (c, x), cell in zip(curves.items(), cells):
            xz = np.asarray(x, dtype=float)[idx]
            ok = np.isfinite(xz)
            k = int(ok.sum())
            if first and n0 != k:
                bad.append(("row n", zid, c, n0, k))
            first = False
            own = re.match(r"^n (\d+): (.*)$", cell)
            body = own.group(2) if own else cell
            if (int(own.group(1)) if own else n0) != k and k:
                bad.append(("cell n", zid, c, cell[:40], k))
            if not k:
                if body != "-":
                    bad.append(("value without samples", zid, c, cell[:40]))
                continue
            if c in flags:
                share = 100 * float((xz[ok] > 0.5).mean())
                if not body.endswith("%") or abs(float(body[:-1]) - share) > 0.051:
                    bad.append(("flag share", zid, c, body, round(share, 2)))
                continue
            whole = np.asarray((full or curves)[c], dtype=float)
            log = log_shaped(whole)
            mine = (["n"] + list(asked)) if asked else names(whole)
            ref = {k: v for k, v in summary(xz, log).items() if k in mine}
            for s in tab["stats"]:                           # a percentile beyond p10/p90: numpy's
                if s in mine and s not in ref and re.fullmatch(r"p\d{1,2}", s):
                    q = xz[ok]
                    ref[s] = float(10 ** np.percentile(np.log10(q), int(s[1:]))) if log and (q > 0).all() else \
                        float(np.percentile(q, int(s[1:])))
            shown = [s for s in tab["stats"] if s in ref]
            parts = body.split(" / ")
            if len(parts) != len(shown):
                bad.append(("cell statistics", zid, c, body[:60], shown))
                continue
            for s, p in zip(shown, parts):
                v, _, at = p.partition("@")
                if not agrees(float(v), ref[s]):
                    bad.append((s, zid, c, v, ref[s]))
                if tab["at"] and s in ("min", "max"):
                    want_at = float(d[idx][ok][np.argmin(xz[ok]) if s == "min" else np.argmax(xz[ok])])
                    if not at or not agrees(float(at), want_at):
                        bad.append((s + " depth", zid, c, at, want_at))
    return bad
