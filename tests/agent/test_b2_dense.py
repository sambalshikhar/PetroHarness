"""Dense tool tests (T9-T13) on every formation of the configured dataset.

    .venv/bin/python -m pytest tests/agent/test_b2_dense.py -q   (PETROHARNESS_DATA selects the dataset)

T9  generated queries against b2_reference (its own parser, run finder and statistics)
T10 invariants over every generated output
T11 hand-written edge and adversarial cases
T12 mutations of real wells
T13 information needs a petrophysicist has when reading one formation
"""
import json
import keyword
import math
import random
import re
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
import b2_reference as R  # noqa: E402
from petroharness.well.summary import curve_kind  # noqa: E402
from test_b2_tools import F, Mutated  # noqa: E402
from petroharness.agent import options  # noqa: E402
from petroharness.agent.engine import max_chars  # noqa: E402
from petroharness.agent.map import num  # noqa: E402
from petroharness.agent.schemas import call  # noqa: E402
call = R.plain_tool(call)  # noqa: E305
from petroharness.agent.tools import STATISTICS, Formation, ToolError, compare, profile, runs, section, stats, step  # noqa: E402
compare, profile, runs, section, stats = map(R.plain_tool, (compare, profile, runs, section, stats))  # added labels read plain

TARGET = 3000                      # generated queries per dataset at least
FRACTION = {"v/v", "frac", "fraction", "dec", "decimal", "ft3/ft3", "m3/m3", "cm3/cm3", "cfcf"}


# --- the reference over a formation's arrays ------------------------------------------------------------------------

def values(f):
    return lambda c: np.asarray(f.view.values(c), dtype=float)


def layer(f):
    """A curve's values as the summary layer reads them: a flag is not computed where an input it is computed from has
    no value (the rule itself is tested in test_plumbing.py)."""
    from petroharness.agent import engine as E
    return lambda c: np.where(E.uncomputed(f, c)[0], np.nan, np.asarray(f.view.values(c), dtype=float))


def ref_mask(f, cond: str) -> np.ndarray:
    return R.condition_mask(cond.strip(), values(f), lambda c: c in f.view.reg.flags)


def same_scale(f, a, b) -> bool:
    ca, cb = f.inv.curves[a], f.inv.curves[b]
    ua, ub = (ca.unit or "").strip().lower(), (cb.unit or "").strip().lower()
    unit_ok = (ua == ub and ua != "") or (ua in FRACTION and ub in FRACTION)
    return unit_ok and ca.percent == cb.percent


def blocks(text: str) -> list:
    """A stats output -> [(curve, [lines])]: a block starts at a line that does not start with two spaces."""
    out = []
    for ln in text.splitlines():
        if ln.startswith("Samples where"):
            continue
        if not ln.startswith("  "):
            out.append((ln.split(" ", 1)[0].split("[", 1)[0], [ln]))
        elif out:
            out[-1][1].append(ln)
    return out


# --- generated queries ----------------------------------------------------------------------------------------------

def threshold(rng, x) -> str:
    x = x[np.isfinite(x)]
    if x.size == 0:
        return "0"
    pick = rng.randrange(8)
    if pick == 0:
        return repr(float(rng.choice(x.tolist())))                     # a sample value: ties
    if pick == 1:
        return repr(float(x.min()))
    if pick == 2:
        return repr(float(x.max()))
    if pick == 3:
        return repr(float(x.min()) - 1.0)
    if pick == 4:
        return repr(float(x.max()) + 1.0)
    if pick == 5:
        return rng.choice(["0", "-0.5", "0.0"])
    return f"{float(np.quantile(x, rng.random())):.3g}"                  # may come in exponent form


def condition(f, rng) -> str:
    cs = list(f.inv.curves)
    terms = []
    for _ in range(rng.choice([1, 1, 2, 2, 3])):
        c = rng.choice(cs)
        op = rng.choice(["<", "<=", ">", ">=", "==", "!="])
        if rng.random() < 0.2:
            rhs = rng.choice(cs)
        else:
            rhs = threshold(rng, values(f)(c))
        name = c if keyword.iskeyword(c.lower()) else rng.choice([c, c.lower()])
        if op == "==" and rng.random() < 0.5:
            op = "="                                                    # the form K2H writes most
        if rng.random() < 0.15:
            terms.append(name)                                          # a name alone: a flag set, a curve with a value
        else:
            terms.append(f"{name} {op} {rhs}")
    out = terms[0]
    for t in terms[1:]:
        out += f" {rng.choice(['and', 'or', 'AND', 'Or'])} {t}"
    return out


def queries(f, rng, n: int) -> list:
    cs = list(f.inv.curves)
    ids = [z.zone_id for z in f.view.zones]
    flags = [c for c in cs if c in f.view.reg.flags]
    out = []
    for _ in range(n):
        kind = rng.random()
        if kind < 0.35:
            kw = {"curves": rng.sample(cs, rng.randint(1, min(4, len(cs))))}
            if rng.random() < 0.4 and ids:
                z = rng.sample(ids, rng.randint(1, min(4, len(ids))))
                kw["zones"] = [rng.choice([q, q.lower(), f" {q} "]) for q in z]
            if rng.random() < 0.4:
                kw["statistics"] = rng.sample(list(STATISTICS), rng.randint(1, 5))
            if rng.random() < 0.3:
                kw["where"] = rng.choice(flags) if flags and rng.random() < 0.4 else condition(f, rng)
            out.append(("stats", kw))
        elif kind < 0.7:
            kw = {"condition": rng.choice(flags) if flags and rng.random() < 0.2 else condition(f, rng)}
            if rng.random() < 0.2:
                kw["limit"] = rng.choice([1, 3, 5, 50])
            if rng.random() < 0.15:
                kw["max_thickness" if rng.random() < 0.5 else "min_thickness"] = rng.choice([0.5, 1.0, 2.0, 5.0])
            if rng.random() < 0.2 and ids:
                kw["zones"] = rng.sample(ids, rng.randint(1, min(3, len(ids))))
            out.append(("runs", kw))
        elif kind < 0.85 and len(cs) >= 2:
            a, b = rng.sample(cs, 2)
            kw = {"a": a, "b": b, "tolerance": rng.choice([None, None, 0, 0.01, 0.05, 10.0])}
            extra(kw, f, rng, flags, ids)
            out.append(("compare", kw))
        else:
            kw = {"curve": rng.choice(cs)}
            extra(kw, f, rng, flags, ids)
            out.append(("profile", kw))
    return out


def extra(kw, f, rng, flags, ids):
    if rng.random() < 0.3:
        kw["where"] = rng.choice(flags) if flags and rng.random() < 0.5 else condition(f, rng)
    if rng.random() < 0.2 and ids:
        kw["zones"] = rng.sample(ids, rng.randint(1, min(3, len(ids))))


TOOLS = {"stats": stats, "runs": runs, "compare": compare, "profile": profile}



@lru_cache(maxsize=1)
def generated() -> list:
    """(task, formation, tool, kwargs, Result or ToolError) for the dataset's generated queries."""
    forms = F()
    per = max(30, math.ceil(TARGET / len(forms)))
    out = []
    for t, f in forms:
        rng = random.Random(f"{t.well}|{t.formation}|dense")
        for tool, kw in queries(f, rng, per):
            try:                                                   # a fifth through the model's door, as JSON
                r = call(f, tool, json.dumps(kw)) if rng.random() < 0.2 else TOOLS[tool](f, **kw)
            except ToolError as e:
                r = e
            out.append((t, f, tool, kw, r))
    return out


# --- T9 checks ------------------------------------------------------------------------------------------------------

def check_stats(f, kw, r) -> list:
    bad = []
    keep = ref_mask(f, kw["where"]) if kw.get("where") else None
    d = f.view.depth
    want_zones = list(dict.fromkeys(z.strip().upper() for z in kw["zones"])) if kw.get("zones") else [z.zone_id for z in f.view.zones]
    zones = {z.zone_id: z for z in f.view.zones}
    curves = list(dict.fromkeys(c.upper() for c in kw["curves"]))
    table = R.zone_table(r.text)                         # the zones in one table, checked cell by cell
    got = blocks(R.without_table(r.text) if table else r.text)
    if [c for c, _ in got] != curves:
        return [("blocks", [c for c, _ in got], curves)]
    if table:
        vals = {c: (np.where(keep, layer(f)(c), np.nan) if keep is not None else layer(f)(c)) for c in curves}
        bad += [("table",) + b for b in R.check_zone_table(r.text, zones, want_zones, vals, d, f.view.reg.flags,
                                                           {c: layer(f)(c) for c in curves}, kw.get("statistics"))]
    for c, lines in got:
        names = (["n"] + list(kw["statistics"])) if kw.get("statistics") else R.names(values(f)(c))   # the default
        log = R.log_shaped(values(f)(c))                                                             #   set by shape
        x = layer(f)(c)
        if keep is not None:
            x = np.where(keep, x, np.nan)
        text = "\n".join(lines)
        away = ~np.asarray(f.view.zoned)                          # the whole interval only where a sample
        parts = []                                                #   outside the zones has a value, then those samples
        if np.isfinite(x[away]).any():
            parts += [("  whole interval (", x, d), ("  outside any zone (", x[away], d[away])]
        elif any(l.startswith(("  whole interval (", "  outside any zone (")) for l in lines):
            bad.append(("whole interval shown where it is the zones pooled", c))
        name, idx = pooled_group(f, kw)
        parts.append((f"  {name}:", x[idx], d[idx]))
        shown_z = R.zone_lines(text)
        gone = R.left_out(text)
        for zid in ([] if table else want_zones):
            if zid in shown_z:
                z = zones[zid]
                parts.append((f"  {zid} ", x[z.indices], d[z.indices]))
            elif zid not in gone:
                bad.append(("zone missing, not said", c, zid))
        kind = curve_kind(f.view, c).kind                          # by the shape of the values
        for head, xs, ds in parts:
            ln = next((l for l in lines if l.startswith(head)), None)
            if ln is None:
                bad.append(("line missing", c, head))
                continue
            if kind == "flag":                                     # a flag: set samples, their share and thickness
                bad += check_flag(f, c, kw, head, ln, x)
                continue
            if kind != "values":                                   # class codes: the samples of each class
                bad += check_classes(c, head, ln, xs)
                continue
            got_f, want = R.fields(ln), R.summary(xs, log)
            if got_f.get("n") != want["n"] or got_f.get("n_of") != xs.size:
                bad.append(("n", c, head, got_f.get("n"), got_f.get("n_of"), want["n"], xs.size))
                continue
            ok = np.isfinite(xs)
            few = [s for s in names if s in ("n", "mean", "min", "max")]          # the outside samples' line
            for s in (few if head.startswith("  outside any zone (") and len(few) > 1 else names):
                if s == "n":
                    continue
                if s not in want:
                    if s in got_f:
                        bad.append(("shown without a value", c, head, s))
                    continue
                if s not in got_f or not R.agrees(got_f[s], want[s]):
                    bad.append((s, c, head, got_f.get(s), want[s]))
                if s in ("min", "max"):
                    at = float(ds[ok][np.argmin(xs[ok]) if s == "min" else np.argmax(xs[ok])])
                    if not R.agrees(got_f.get(s + "_at", float("nan")), at):
                        bad.append((s + " depth", c, head, got_f.get(s + "_at"), at))
            extra = set(got_f) - set(names) - {"n", "n_of", "min_at", "max_at"}
            if extra:
                bad.append(("not asked", c, head, extra))
    return bad


def asked(f, kw) -> list:
    if not kw.get("zones"):
        return list(f.view.zones)
    want = list(dict.fromkeys(z.strip().upper() for z in kw["zones"]))
    return [next(z for z in f.view.zones if z.zone_id == w) for w in want]


def pooled_group(f, kw):
    zs = asked(f, kw)
    every = {z.zone_id for z in zs} == {z.zone_id for z in f.view.zones}
    return ("zones pooled" if every else "these zones pooled"), np.unique(np.concatenate([np.asarray(z.indices) for z in zs]))


def check_flag(f, c, kw, head, ln, x) -> list:
    g = R.fields(ln)
    with np.errstate(invalid="ignore"):
        on = np.isfinite(x) & (x > 0.5)
    zs = asked(f, kw)
    if head.startswith("  whole interval"):
        idx, th = np.arange(x.size), f.inv.gross * on.sum() / x.size
    elif head.startswith("  outside any zone"):                    # the samples outside the zones
        idx = np.flatnonzero(~np.asarray(f.view.zoned))
        th = f.inv.gross * on[idx].sum() / x.size
    elif "pooled" in head:
        idx = pooled_group(f, kw)[1]
        th = sum(R.thickness(z, int(on[z.indices].sum())) for z in zs)
    else:
        z = next(z for z in f.view.zones if head.strip() == z.zone_id)
        idx, th = np.asarray(z.indices), R.thickness(z, int(on[z.indices].sum()))
    have = int(np.isfinite(x[idx]).sum())
    if "not computed (" in ln:                                     # not computed (no value of an input) there
        return [] if g.get("n") == have == 0 and g.get("n_of") == idx.size else [("not computed", c, head, g.get("n"), have)]
    want = {"n": have, "n_of": idx.size, "set": int(on[idx].sum()), "thickness": th}
    out = [("flag " + k, c, head, g.get(k), v) for k, v in want.items() if k not in g or not R.agrees(g[k], v)]
    share = 100 * on[idx].sum() / have if have else 0.0
    if abs(g.get("set_share", np.nan) - share) > 0.0501:
        out.append(("flag share", c, head, g.get("set_share"), share))
    return out


def check_classes(c, head, ln, xs) -> list:
    """A class-codes line against numpy: n, and each class's samples and share of those with a value (no statistic)."""
    ok = np.isfinite(xs)
    g = R.fields(ln)
    out = [] if g.get("n") == ok.sum() else [("classes n", c, head, g.get("n"), int(ok.sum()))]
    want = {float(v): int(np.sum(xs[ok] == v)) for v in np.unique(xs[ok])}
    got = R.class_shares(ln)
    if "every value" in ln:
        return out + ([] if len(want) <= 1 else [("one value", c, head, want)])
    if {k: v[1] for k, v in got.items()} != want:
        out.append(("class samples", c, head, got, want))
    out += [("class share", c, head, k, p) for k, (p, m) in got.items() if abs(p - 100 * m / ok.sum()) > 0.051]
    if re.search(r"\b(mean|median|min|max|p10|p90) -?\d", ln):
        out.append(("statistics of codes", c, head, ln[:80]))
    return out


def ref_runs(f, kw) -> list:
    """(top depth, base depth, samples, thickness, zone position) as runs() should list them, depth order."""
    zs = asked(f, kw)
    d = f.view.depth
    out = []
    for a, b, k in R.zone_runs(ref_mask(f, kw["condition"]), zs):
        n = int(b - a + 1)
        out.append((float(d[a]), float(d[b]), n, R.thickness(zs[k], n), k))
    lo, hi = kw.get("min_thickness"), kw.get("max_thickness")
    if lo is not None or hi is not None:
        out = [r for r in out if (lo or 0.0) <= r[3] <= (math.inf if hi is None else hi)]
    return sorted(out, key=lambda r: r[0])                                # depth order (ties among the longest too)


def check_runs(f, kw, r) -> list:
    bad = []
    zs = asked(f, kw)
    want = ref_runs(f, kw)
    got = R.runs_output(r.text)
    if got["count"] != len(want):
        bad.append(("count", got["count"], len(want)))
    if not kw.get("zones") and kw.get("min_thickness") is None and kw.get("max_thickness") is None:
        mask = ref_mask(f, kw["condition"])
        n_all = int(mask.sum())
        w = got["whole"]
        if not (mask & ~np.asarray(f.view.zoned)).any():          # the whole interval only where it differs
            if w is not None:
                bad.append(("whole shown where it is the zones", w))
        elif w is None or not R.agrees(w[0], f.inv.gross * n_all / f.view.depth.size) or abs(w[1] - 100 * n_all / f.view.depth.size) > 0.0501:
            bad.append(("whole", w, n_all))
    total = 0.0
    for k, z in enumerate(zs):
        n = sum(w[2] for w in want if w[4] == k)
        th, share = R.thickness(z, n), 100 * n / z.n_samples
        total += th
        g = got["zones"].get(z.zone_id)
        if g is None or not R.agrees(g[0], th) or abs(g[1] - share) > 0.05 + 1e-9:
            bad.append(("zone", z.zone_id, g, th, share))
    if got["total"] is None or not R.agrees(got["total"], total):
        bad.append(("total", got["total"], total))
    base = sum(z.base - z.top for z in zs) if kw.get("zones") else f.view.zoned_thickness
    zshare = 100 * total / base if base else 0.0
    if got["share"] is None or abs(got["share"] - zshare) > 0.05 + 1e-9:
        bad.append(("share", got["share"], zshare))
    if want:
        m = re.search(rf"shallowest top ({R.NUM}) \S+ \((Z\d+)\); deepest base ({R.NUM}) \S+ \((Z\d+)\)", r.text)
        first, last = min(want, key=lambda w: w[0]), max(want, key=lambda w: w[1])
        if not m or not R.agrees(float(m.group(1)), first[0]) or not R.agrees(float(m.group(3)), last[1]):
            bad.append(("first/last", m.groups() if m else None, first[0], last[1]))
    limit = kw.get("limit", 20)
    listed = sorted(sorted(want, key=lambda w: -w[2])[:limit], key=lambda w: w[0])
    if len(got["listed"]) != len(listed):
        bad.append(("listed", len(got["listed"]), len(listed)))
    else:
        for g, w in zip(got["listed"], listed):
            if not (R.agrees(g[0], w[0]) and R.agrees(g[1], w[1]) and R.agrees(g[2], w[3]) and g[3] == zs[w[4]].zone_id):
                bad.append(("run", g, w))
                break
    if len(want) > limit and got["of"] != (limit, len(want)):
        bad.append(("of", got["of"], limit, len(want)))
    return bad


def check_compare(f, kw, r) -> list:
    bad = []
    a, b = kw["a"].upper(), kw["b"].upper()
    same = same_scale(f, a, b)
    head = next(l for l in r.text.splitlines() if not l.startswith("Samples where"))
    if ("(difference " in head) != same:
        return [("scale", head, same)]
    keep = ref_mask(f, kw["where"]) if kw.get("where") else None
    xa, xb = layer(f)(a), layer(f)(b)
    if keep is not None:
        xa, xb = np.where(keep, xa, np.nan), np.where(keep, xb, np.nan)
    shown = R.zone_lines(r.text)
    gone = R.left_out(r.text)
    name, idx = pooled_group(f, kw)
    parts = [(f"  {name}:", idx)]
    for z in asked(f, kw):
        if z.zone_id in shown:
            parts.append((f"  {z.zone_id} ", z.indices))
        elif z.zone_id not in gone:
            bad.append(("zone missing, not said", z.zone_id))
    for head, idx in parts:
        ln = next((l for l in r.text.splitlines() if l.startswith(head)), None)
        pa, pb = xa[idx], xb[idx]
        ok = np.isfinite(pa) & np.isfinite(pb)
        g = R.fields(ln) if ln else {}
        if g.get("n") != ok.sum():
            bad.append(("n", head, g.get("n"), int(ok.sum())))
            continue
        if not ok.any():
            continue
        want = {f"mean {a}": float(np.mean(pa[ok])), f"mean {b}": float(np.mean(pb[ok]))}
        if same:
            dd = pa[ok] - pb[ok]
            want["difference mean"] = float(np.mean(dd))
            want["sd"] = float(np.std(dd))
            # above, below and within the tolerance (0 when none)
            tol = float(kw.get("tolerance") or 0.0)
            want["above"] = 100 * float(np.mean(dd > tol))
            want["below"] = 100 * float(np.mean(dd < -tol))
            want["within"] = 100 * float(np.mean(np.abs(dd) <= tol) if tol else np.mean(dd == 0))
        rho = R.rank_corr(pa, pb)
        if np.isfinite(rho):
            want["rank correlation"] = rho
        for k, v in want.items():
            tol_ok = (abs(g.get(k, np.nan) - v) <= 0.05 + 1e-9) if k in ("beyond", "above", "below", "within") \
                else R.agrees(g.get(k, np.nan), v)
            if k not in g or not tol_ok:
                bad.append((k, head, g.get(k), v))
        if "rank correlation" in g and "rank correlation" not in want:
            bad.append(("rank shown without a value", head))
    return bad


def check_profile(f, kw, r) -> list:
    bad = []
    c = kw["curve"].upper()
    shown = R.zone_lines(r.text)
    keep = ref_mask(f, kw["where"]) if kw.get("where") else None
    full = layer(f)(c) if keep is None else np.where(keep, layer(f)(c), np.nan)
    meds = []
    table = R.zone_table(r.text)                                   # many zones: one table, checked cell by cell
    if table:
        zs = {z.zone_id: z for z in f.view.zones}
        want = [z.zone_id for z in sorted(asked(f, kw), key=lambda z: z.top)]
        bad += [("table",) + b for b in R.check_zone_table(r.text, zs, want, {c: full}, f.view.depth, (),
                                                           {c: values(f)(c)}, kw.get("statistics"))]
    for z in sorted(asked(f, kw), key=lambda z: z.top):
        x = full[z.indices]
        if table:
            if np.isfinite(x).any():
                meds.append((z, float(np.nanmedian(x))))
            continue
        ln = shown.get(z.zone_id)
        if ln is None:
            bad.append(("zone missing", z.zone_id))
            continue
        if not np.isfinite(x).any():
            if not ln.endswith("no data"):
                bad.append(("no data", z.zone_id, ln))
            continue
        if curve_kind(f.view, c).kind == "flag":                    # a flag: its share, as stats gives it (test_t9 stats)
            continue
        if curve_kind(f.view, c).kind != "values":                  # class codes: their samples by class
            bad += check_classes(c, z.zone_id, ln, x)
            continue
        s = R.summary(x)
        g = R.fields(ln)
        meds.append((z, s["median"]))
        if not (R.agrees(g.get("median", np.nan), s["median"]) and R.agrees(g.get("mean", np.nan), s["mean"])):
            bad.append(("zone", z.zone_id, g, s["median"], s["mean"]))
    hi_line = next((ln for ln in r.text.splitlines() if ln.startswith("  highest zone by each statistic:")), "")
    if curve_kind(f.view, c).kind != "values":                     # flags and codes are not ranked
        return bad + ([("ranked codes or flag", hi_line[:80])] if hi_line else [])
    if len(meds) >= 2 and len({m for _, m in meds}) > 1:                # ranked by each statistic shown
        top = max(m for _, m in meds)
        his = ", ".join(z.zone_id for z, m in meds if m == top)
        if f"median {his} (" not in hi_line:
            bad.append(("highest", his, hi_line[:120]))
    elif "median " in hi_line:
        bad.append(("highest median with fewer than two zones that differ",))
    rho = R.rank_corr([(z.top + z.base) / 2 for z, _ in meds], [m for _, m in meds]) if len(meds) >= 3 else float("nan")
    depth = next((ln for ln in r.text.splitlines() if ln.startswith("  with depth (rank correlation")), "")
    said = re.search(r"; median (-?[\d.]+)|: median (-?[\d.]+)", depth)
    if np.isfinite(rho):                                                  # the coefficient, no tier words
        got = float(next(g for g in said.groups() if g)) if said else None
        if got is None or abs(got - rho) > 5e-4 * max(1, abs(rho)):
            bad.append(("depth order", got, rho))
    elif said:
        bad.append(("depth order without three zones that differ", said.group(0)))
    if re.search(r"increases|decreases|steady change", r.text):
        bad.append(("tier words",))
    return bad


CHECKS = {"stats": check_stats, "runs": check_runs, "compare": check_compare, "profile": check_profile}


@pytest.mark.data
def test_t9_generated_queries_match_the_reference():
    got = generated()
    assert len(got) >= TARGET, len(got)
    bad, kinds, errors = [], Counter(), []
    for t, f, tool, kw, r in got:
        kinds[tool] += 1
        if isinstance(r, ToolError):
            codes = [c for c in (kw.get("a"), kw.get("b")) if c and curve_kind(f.view, str(c).upper()).kind == "classes"]
            if tool == "compare" and codes and "holds class codes" in str(r):
                continue                                           # class codes are labels, not quantities
            errors.append((t.well, tool, kw, str(r)[:160]))
            continue
        for b in CHECKS[tool](f, kw, r):
            bad.append((t.well, t.formation, tool, kw, b))
    assert not errors, (len(errors), errors[:8])
    assert not bad, (len(bad), dict(kinds), bad[:8])


@pytest.mark.data
def test_t9_every_section_and_step():
    from petroharness.agent import options
    from petroharness.agent.tools import _zone_cells, _store_runs
    bad = []
    for t, f in F():
        for s in f.inv.sections:
            r = section(f, s.key)
            if len(r.shown) > max_chars():                            # the text shown (the item keeps every row)
                bad.append((t.well, s.key, "size", len(r.shown)))
            for k in s.classes:
                ln = next((l for l in r.text.splitlines() if l.startswith(f"  {k.name}:") or l.startswith(f"  {k.name} (")), None)
                if ln is None:
                    bad.append((t.well, s.key, k.name, "missing"))
                    continue
                size = next((l for l in r.text.splitlines() if l.startswith(f"    {k.name} in all: ")), "")   # its size after it
                if k.thickness is not None and f"{num(k.thickness)} {f.inv.depth_unit}" not in ln + size:
                    bad.append((t.well, s.key, k.name, "thickness"))
                every = _store_runs(f, s.key, k.name)
                whole = every and ln.endswith(f"; runs: {_zone_cells(f, every)}")       # every run, top to base
                if k.runs not in ln and not whole and f"(every run: condition {s.key}:{k.name})" not in ln:
                    bad.append((t.well, s.key, k.name, "runs shortened without saying so"))
            sec = f.store.sections.get(s.key)
            for label, rs in (sec.classes.items() if sec else []):     # the class as a condition gives its runs
                if not rs:
                    continue
                out = R.runs_output(runs(f, f"{s.key}:{label}").text)
                want = sum(x.thickness for x in rs)
                if out["total"] is None or abs(out["total"] - want) > max(0.01 * want, f.inv.step):
                    bad.append((t.well, s.key, label, "class runs", out["total"], want))
        from petroharness.record.card import plain_inputs         # a fallback input in plain words
        for m in f.inv.methods:
            text = step(f, m.step).text
            for e in m.equations_here:
                if plain_inputs(e, m.inputs) not in text:
                    bad.append((t.well, m.step, "equation", e[:50]))
            for dl in m.decisions_here:
                if plain_inputs(dl, m.inputs) not in text and "more lines left out" not in text:
                    bad.append((t.well, m.step, "record", dl[:50]))
    assert not bad, (len(bad), bad[:10])


# --- T10 invariants -------------------------------------------------------------------------------------------------

def shown_numbers(text: str) -> list:
    return [float(x) for x in re.findall(rf"(?<![\w.]){R.NUM}", re.sub(r"\b[A-Z][A-Z0-9_]*\d[A-Z0-9_]*\b|Z\d+", " ", text))]


@pytest.mark.data
def test_t10_invariants():
    bad = []
    for t, f, tool, kw, r in generated():
        if isinstance(r, ToolError):
            continue
        # every number handed to the ledger is in the text
        shown = shown_numbers(r.text)
        for v in r.numbers:
            if not any(R.agrees(s, float(v)) or abs(s - float(v)) <= 0.0501 for s in shown):   # shares: one decimal
                bad.append((t.well, tool, "number not shown", v))
                break
        if tool == "stats":
            table = R.zone_table(r.text)                 # zone counts from the table's cells
            for c, lines in blocks(R.without_table(r.text) if table else r.text):
                zn = 0
                if table and c in table["curves"]:
                    j = table["curves"].index(c)
                    for n0, cells in table["rows"].values():
                        own = re.match(r"^n (\d+): ", cells[j])
                        zn += int(own.group(1)) if own else (0 if cells[j] == "-" else n0)
                for ln in lines[1:]:
                    g = R.fields(ln)
                    seq = [g[k] for k in ("min", "p10", "median", "p90", "max") if k in g]
                    if any(b < a - 1e-4 * max(1, abs(a)) for a, b in zip(seq, seq[1:])):
                        bad.append((t.well, c, "order", ln[:120]))
                    if "geo_mean" in g and "mean" in g and g["geo_mean"] > g["mean"] * (1 + 1e-3) + 1e-9:
                        bad.append((t.well, c, "geo_mean > mean", ln[:120]))
                    if re.match(r"  Z\d+ ", ln):
                        zn += g.get("n", 0)
                whole = next((R.fields(l) for l in lines if l.startswith("  whole interval")), None)
                pooled = next((R.fields(l) for l in lines if l.startswith("  zones pooled:")), None)
                if whole and pooled and whole["n"] < pooled["n"]:
                    bad.append((t.well, c, "whole n < pooled n"))
                if pooled and not R.left_out("\n".join(lines)) and not (table and R.left_out(r.text)) and zn != pooled["n"]:
                    bad.append((t.well, c, "pooled n != sum of zones", zn, pooled["n"]))
        if tool == "runs":
            got = R.runs_output(r.text)
            zones = {z.zone_id: z for z in f.view.zones}
            prev = None
            for top, base, th, zid in got["listed"]:
                z = zones[zid]
                if not (z.top - 1e-6 <= top <= base <= z.base + 1e-6):
                    bad.append((t.well, "run outside its zone", top, base, zid))
                if prev is not None and top <= prev:
                    bad.append((t.well, "runs overlap or unsorted", prev, top))
                prev = base
            for zid, (th, share) in got["zones"].items():
                if not (0 <= share <= 100) or th > zones[zid].base - zones[zid].top + 1e-6:
                    bad.append((t.well, "zone share", zid, th, share))
        if tool == "compare" and same_scale(f, kw["a"].upper(), kw["b"].upper()):
            back = compare(f, kw["b"], kw["a"], tolerance=kw.get("tolerance"), zones=kw.get("zones"), where=kw.get("where"))
            k = 4 if kw.get("where") else 3
            for l1, l2 in zip(r.text.splitlines()[k:], back.text.splitlines()[k:]):
                g1, g2 = R.fields(l1), R.fields(l2)
                if "difference mean" in g1 and abs(g1["difference mean"] + g2.get("difference mean", np.nan)) > 2e-4 * max(1, abs(g1["difference mean"])):
                    bad.append((t.well, "a-b != -(b-a)", l1[:80], l2[:80]))
                    break
                if g1.get("rank correlation") != g2.get("rank correlation"):
                    bad.append((t.well, "rank correlation not symmetric", l1[:80], l2[:80]))
                    break
    assert not bad, (len(bad), bad[:10])


@pytest.mark.data
def test_t10_complements_add_up():
    """'X op t' and its complement cover exactly the zone samples where X has a value."""
    pairs = [("<", ">="), ("<=", ">"), ("==", "!=")]
    bad = []
    for t, f in F():
        rng = random.Random(f"{t.well}|{t.formation}|complement")
        for _ in range(5):
            c = rng.choice(list(f.inv.curves))
            th = threshold(rng, values(f)(c))
            op, back = rng.choice(pairs)
            a, b = R.runs_output(runs(f, f"{c} {op} {th}").text), R.runs_output(runs(f, f"{c} {back} {th}").text)
            for z in f.view.zones:
                have = int(np.isfinite(values(f)(c)[z.indices]).sum())
                if abs(a["zones"][z.zone_id][1] + b["zones"][z.zone_id][1] - 100 * have / z.n_samples) > 0.11:
                    bad.append((t.well, c, op, th, z.zone_id, a["zones"][z.zone_id], b["zones"][z.zone_id], have))
    assert not bad, bad[:10]


@pytest.mark.data
def test_t10_same_call_same_text():
    for t, f, tool, kw, r in generated()[::17]:
        if not isinstance(r, ToolError):
            assert TOOLS[tool](f, **kw).text == r.text, (t.well, tool, kw)


@pytest.mark.data
def test_t10_cutoffs_are_monotone():
    """Net thickness can only grow as a saturation cutoff loosens."""
    for t, f in F():
        if "SW" not in f.inv.curves:
            continue
        tot = [R.runs_output(runs(f, f"SW < {c}").text)["total"] for c in (0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0)]
        assert all(b >= a - 1e-9 for a, b in zip(tot, tot[1:])), (t.well, tot)


# --- T11 hand-written edge and adversarial cases --------------------------------------------------------------------

def first(pred):
    for t, f in F():
        if pred(f):
            return t, f
    pytest.skip("no formation in this dataset has what this case needs")


@pytest.mark.data
def test_t11_names_in_any_case_and_with_spaces():
    t, f = first(lambda f: "PHIE" in f.inv.curves and len(f.view.zones) >= 2)
    z = f.view.zones[1].zone_id
    assert stats(f, "phie", zones=[f" {z.lower()} "]).text == stats(f, "PHIE", zones=[z]).text
    assert runs(f, "phie > 0.1 AND phie < 0.3").text.split("\n", 1)[1] == runs(f, "PHIE > 0.1 and PHIE < 0.3").text.split("\n", 1)[1]


@pytest.mark.data
def test_t11_duplicates_are_one():
    t, f = first(lambda f: "PHIE" in f.inv.curves)
    z = f.view.zones[0].zone_id
    assert stats(f, ["PHIE", "phie"], zones=[z, z]).text == stats(f, "PHIE", zones=[z]).text


@pytest.mark.data
def test_t11_empty_requests():
    t, f = F()[0]
    with pytest.raises(ToolError, match="name at least one curve"):
        stats(f, [])
    assert stats(f, list(f.inv.curves)[:1], zones=[]).text == stats(f, list(f.inv.curves)[:1]).text


@pytest.mark.data
def test_t11_no_geometric_mean_for_zero_or_negative_values():
    t, f = first(lambda f: any(np.nanmin(values(f)(c)) <= 0 for c in f.inv.curves))
    c = next(c for c in f.inv.curves if np.nanmin(values(f)(c)) <= 0)
    assert "geo_mean" not in stats(f, c).text.splitlines()[1]


@pytest.mark.data
def test_t11_flags_and_analyzer_curves_have_stats():
    t, f = first(lambda f: any(c in f.view.reg.flags for c in f.inv.curves))
    flag = next(c for c in f.inv.curves if c in f.view.reg.flags)
    out = stats(f, flag, statistics=["n", "mean"]).text
    assert "set in" in out and "thickness" in out and "mean" not in out
    an = [c for c, cv in f.inv.curves.items() if cv.source == "analyzer"]
    if an:
        assert stats(f, an[0]).text.startswith(an[0])


@pytest.mark.data
def test_t11_large_and_tiny_values_print_without_exponents():
    for t, f in F():
        for c in f.inv.curves:
            text = stats(f, c, statistics=["min", "max", "mean"]).text
            assert not re.search(r"\d[eE][-+]?\d", text), (t.well, c, text[:200])


@pytest.mark.data
def test_t11_conditions_that_never_and_always_hold():
    t, f = first(lambda f: "PHIE" in f.inv.curves)
    x = values(f)("PHIE")
    never = R.runs_output(runs(f, f"PHIE > {float(np.nanmax(x)) + 1}").text)
    assert never["count"] == 0 and never["total"] == 0 and "shallowest" not in runs(f, f"PHIE > {float(np.nanmax(x)) + 1}").text
    always = R.runs_output(runs(f, f"PHIE >= {float(np.nanmin(x))}").text)
    for z in f.view.zones:
        have = np.isfinite(x[z.indices]).mean() * 100
        assert abs(always["zones"][z.zone_id][1] - have) <= 0.05


@pytest.mark.data
def test_t11_threshold_on_sample_values_separates_lt_from_le():
    t, f = first(lambda f: "PHIE" in f.inv.curves)
    x = values(f)("PHIE")
    z = x[f.view.zoned]
    z = z[np.isfinite(z)]
    v = Counter(np.round(z, 12).tolist()).most_common(1)[0][0]
    exact = float(z[np.argmin(np.abs(z - v))])
    lt, le = R.runs_output(runs(f, f"PHIE < {exact!r}").text), R.runs_output(runs(f, f"PHIE <= {exact!r}").text)
    ties = int((x[f.view.zoned] == exact).sum())
    assert ties >= 1
    assert le["total"] > lt["total"] or ties == 0


@pytest.mark.data
def test_t11_and_binds_before_or():
    t, f = first(lambda f: {"PHIE", "SW", "VCL"} <= set(f.inv.curves))
    a = R.runs_output(runs(f, "SW < 0.3 or PHIE > 0.2 and VCL < 0.2").text)["total"]
    b = R.runs_output(runs(f, "PHIE > 0.2 and VCL < 0.2 or SW < 0.3").text)["total"]
    assert a == b


@pytest.mark.data
def test_t11_runs_stop_at_zone_edges():
    t, f = first(lambda f: len(f.view.zones) >= 2 and "PHIE" in f.inv.curves)
    out = R.runs_output(runs(f, f"PHIE >= {float(np.nanmin(values(f)('PHIE')))}", limit=10_000).text)
    zones = {z.zone_id: z for z in f.view.zones}
    for top, base, th, zid in out["listed"]:
        assert zones[zid].top - 1e-6 <= top and base <= zones[zid].base + 1e-6


@pytest.mark.data
def test_t11_limit_counts_what_it_leaves_out():
    for t, f in F():
        if "PHIE" not in f.inv.curves:
            continue
        r = R.runs_output(runs(f, "PHIE > 0.1", limit=1).text)
        if r["count"] > 1:
            assert len(r["listed"]) == 1 and r["of"] == (1, r["count"])
            return
    pytest.skip("no formation with two runs")


@pytest.mark.data
def test_t11_exponent_and_signed_thresholds():
    t, f = first(lambda f: "PERM" in f.inv.curves)
    assert runs(f, "PERM > 1e-3").text.split("\n", 1)[1] == runs(f, "PERM > 0.001").text.split("\n", 1)[1]
    assert runs(f, "PERM > -1").text.split("\n", 1)[1] == runs(f, "PERM > -1.0").text.split("\n", 1)[1]
    assert runs(f, "PERM > +1").text.split("\n", 1)[1] == runs(f, "PERM > 1").text.split("\n", 1)[1]


@pytest.mark.data
def test_t11_curve_against_curve():
    t, f = first(lambda f: {"NPHI", "PHID"} <= set(f.inv.curves))
    out = R.runs_output(runs(f, "NPHI < PHID").text)
    want = R.condition_mask("NPHI < PHID", values(f))
    for z in f.view.zones:
        assert abs(out["zones"][z.zone_id][1] - 100 * want[z.indices].mean()) <= 0.05


@pytest.mark.data
@pytest.mark.parametrize("cond", ["SW <", "SW << 0.5", "SW < 0.5 and", "SW < abc def", "SW < 0.5 xor PHIE > 0.1",
                                  "and SW < 0.5", "SW < 0.5 and and PHIE > 0.1", "(SW < 0.5)", "SW < 1,5", "", "SW - < 0.5",
                                  "SW < 0.5 -", "0.5 > 0.3"])
def test_t11_malformed_conditions(cond):
    t, f = F()[0]
    with pytest.raises(ToolError):
        runs(f, cond)


@pytest.mark.data
@pytest.mark.parametrize("flipped,plain", [("0.5 > SW", "SW < 0.5"), ("0.1 <= PHIE", "PHIE >= 0.1")])
def test_t11_a_number_on_the_left_reads_as_the_same_condition(flipped, plain):    # a form models send
    from petroharness.agent.engine import select
    t, f = first(lambda f: {"SW", "PHIE"} <= set(f.inv.curves))
    assert (select(f, flipped).mask == select(f, plain).mask).all()


@pytest.mark.data
def test_t11_single_equals_is_equality():
    t, f = first(lambda f: "NET_PAY" in f.inv.curves)
    body = lambda c: runs(f, c).text.split("\n", 1)[1]
    assert body("NET_PAY = 1") == body("NET_PAY == 1") == body("NET_PAY=1")


@pytest.mark.data
def test_t11_names_as_terms():
    t, f = first(lambda f: {"NET_PAY", "PHIE", "RDEP"} <= set(f.inv.curves))
    a = R.runs_output(runs(f, "NET_PAY and PHIE > 0.1").text)["total"]
    want = R.condition_mask("NET_PAY and PHIE > 0.1", values(f), lambda c: c in f.view.reg.flags)
    assert R.agrees(a, sum(R.thickness(z, int(want[z.indices].sum())) for z in f.view.zones))
    cover = runs(f, "RDEP").text
    assert cover.startswith("Runs where RDEP has a value")


@pytest.mark.data
def test_t11_section_keys_with_other_separators():
    t, f = first(lambda f: bool(f.inv.sections))
    s = f.inv.sections[0]
    fam, name = s.key.split(".", 1)
    for k in (f"{fam}:{name}", f"{fam}/{name}", f"{fam} {name}"):
        assert section(f, k).text == section(f, s.key).text


@pytest.mark.data
def test_t11_the_door_reads_json_and_numbers_sent_as_text():
    t, f = first(lambda f: "PHIE" in f.inv.curves and "PHIT" in f.inv.curves)
    assert call(f, "compare", '{"a": "PHIE", "b": "PHIT", "tolerance": "0.02"}').text == compare(f, "PHIE", "PHIT", tolerance=0.02).text
    assert call(f, "stats", {"curves": "PHIE", "zones": None, "where": ""}).text == stats(f, "PHIE").text
    assert call(f, "stats", '{"curve": "PHIE"}').text == stats(f, "PHIE").text          # one curve where a list belongs
    assert call(f, "stats", '{"curves": ["PHIE"], "bins": 5}').text.startswith("(ignored bins: stats takes")   # run, and say so
    with pytest.raises(ToolError, match="needs"):
        call(f, "compare", '{"a": "PHIE"}')
    with pytest.raises(ToolError, match="not JSON"):
        call(f, "stats", '{"curves": [PHIE]}')
    with pytest.raises(ToolError, match="no tool"):
        call(f, "statistics", "{}")
    assert call(f, "stats", {"curves": ["PHIE"], "where": "null"}).text == stats(f, "PHIE").text
    steps = [m.step for m in f.inv.methods]
    if steps:                            # a step named as a section opens the step
        assert section(f, steps[0]).text == step(f, steps[0]).text
    elif steps:
        with pytest.raises(ToolError, match="is a workflow step: call step"):
            section(f, steps[0])


@pytest.mark.data
def test_t11_unknown_names_in_conditions_say_what_exists():
    t, f = F()[0]
    with pytest.raises(ToolError, match="curves with data"):
        runs(f, "NOSUCH < 0.5")
    with pytest.raises(ToolError, match="curves with data"):
        runs(f, f"{list(f.inv.curves)[0]} < NOSUCH")
    with pytest.raises(ToolError, match="no class"):
        runs(f, "hydrocarbon.nosuch:NOSUCH")


@pytest.mark.data
def test_t11_class_by_short_key():
    for t, f in F():
        for key, sec in f.store.sections.items():
            for label, rs in sec.classes.items():
                if rs:
                    short = key.split(".", 1)[1]
                    assert runs(f, f"{key}:{label}").text.split("\n", 1)[1] == runs(f, f"{short}:{label}").text.split("\n", 1)[1]
                    return
    pytest.skip("no class with runs")


@pytest.mark.data
def test_t11_section_by_short_key_and_unknown():
    t, f = first(lambda f: bool(f.inv.sections))
    shorts = Counter(s.key.split(".", 1)[1] for s in f.inv.sections)
    s = next(s for s in f.inv.sections if shorts[s.key.split(".", 1)[1]] == 1)
    assert section(f, s.key.split(".", 1)[1]).text == section(f, s.key).text
    with pytest.raises(ToolError, match="sections: "):
        section(f, "nosuch")


@pytest.mark.data
def test_t11_a_short_key_two_families_share_asks_which():
    for t, f in F():
        shorts = Counter(s.key.split(".", 1)[1] for s in f.inv.sections)
        twice = [k for k, n in shorts.items() if n > 1]
        if twice:
            with pytest.raises(ToolError, match="give the full key"):
                section(f, twice[0])
            return
    pytest.skip("no short key shared by two families")


@pytest.mark.data
def test_t11_compare_edge_cases():
    t, f = first(lambda f: "PHIE" in f.inv.curves and "PERM" in f.inv.curves)
    with pytest.raises(ToolError, match="two different curves"):
        compare(f, "PHIE", "phie")
    with pytest.raises(ToolError, match="at least 0"):
        compare(f, "PHIE", "PERM", tolerance=-1)
    head = compare(f, "PHIE", "PERM").text.splitlines()[0]
    assert "no difference" in head and "difference mean" not in compare(f, "PHIE", "PERM").text


@pytest.mark.data
def test_t11_compare_without_overlap_says_n_0():
    t, f = first(lambda f: "KH_CORE" in f.inv.curves or "PHIC" in f.inv.curves)
    core = "KH_CORE" if "KH_CORE" in f.inv.curves else "PHIC"
    log = "PERM" if core == "KH_CORE" else "PHIE"
    text = compare(f, log, core).text
    for z in f.view.zones:
        has = (np.isfinite(values(f)(log)[z.indices]) & np.isfinite(values(f)(core)[z.indices])).any()
        ln = R.zone_lines(text).get(z.zone_id)
        if ln is not None and not has:
            assert re.search(rf": n 0 of \d+, no sample where both {log} and {core} have values$", ln), ln


@pytest.mark.data
def test_t11_profile_on_one_zone():
    t, f = first(lambda f: len(f.view.zones) == 1)
    text = profile(f, list(f.inv.curves)[0]).text
    assert "highest zone by" not in text and "with depth" not in text


@pytest.mark.data
def test_t11_thickness_filters():
    t, f = first(lambda f: "PHIE" in f.inv.curves)
    allr = ref_runs(f, {"condition": "PHIE > 0.05"})
    thin = R.runs_output(runs(f, "PHIE > 0.05", max_thickness=1.0).text)
    thick = R.runs_output(runs(f, "PHIE > 0.05", min_thickness=1.0).text)
    assert thin["count"] == sum(1 for r in allr if r[3] <= 1.0)
    assert thick["count"] == sum(1 for r in allr if r[3] >= 1.0)
    with pytest.raises(ToolError, match="at least 0"):
        runs(f, "PHIE > 0.05", max_thickness=-1)


@pytest.mark.data
def test_t11_where_restricts_the_samples():
    t, f = first(lambda f: {"PHIE", "NET_PAY"} <= set(f.inv.curves))
    text = stats(f, "PHIE", where="NET_PAY").text
    assert text.startswith("Samples where NET_PAY > 0.5")
    pooled = R.fields(next(l for l in text.splitlines() if l.startswith("  zones pooled:")))
    x, pay = values(f)("PHIE"), values(f)("NET_PAY") > 0.5
    sel = x[f.view.zoned & pay]
    assert pooled["n"] == np.isfinite(sel).sum()
    if np.isfinite(sel).any():
        assert R.agrees(pooled["mean"], float(np.nanmean(sel)))


# --- T12 mutations --------------------------------------------------------------------------------------------------

def mutate(f, c, fn):
    return Formation(f.inv, Mutated(f.view, c, fn), f.store)


@pytest.mark.data
def test_t12_negating_a_curve_flips_its_direction_and_extremes():
    flipped = 0
    for t, f in F():
        for c in ("PHIE", "SW", "VCL", "PERM"):
            if c not in f.inv.curves or len(f.view.zones) < 3:
                continue
            text = profile(f, c).text
            a = re.search(r"with depth \(rank correlation[^)]*\): .*?\bmedian (-?[\d.]+)", text)
            hi = re.search(r"highest zone by each statistic: .*?\bmedian (Z\d+) \(", text)
            if not a or not hi or float(a.group(1)) == 0:
                continue
            b_text = profile(mutate(f, c, lambda x: -x), c).text
            b = re.search(r"with depth \(rank correlation[^)]*\): .*?\bmedian (-?[\d.]+)", b_text)
            assert b and abs(float(b.group(1)) + float(a.group(1))) <= 2e-4, (t.well, c, a.group(1), b and b.group(1))
            assert re.search(r"lowest zone by each statistic: .*?\bmedian (Z\d+) \(", b_text).group(1) == hi.group(1), (t.well, c)
            flipped += 1
    assert flipped


@pytest.mark.data
def test_t12_doubling_doubles_means_and_keeps_rank_correlations():
    t, f = first(lambda f: {"PHIE", "PHIT"} <= set(f.inv.curves))
    g = mutate(f, "PHIE", lambda x: 2 * x)
    m0 = R.fields(next(l for l in stats(f, "PHIE").text.splitlines() if l.startswith("  zones pooled:")))["mean"]
    m1 = R.fields(next(l for l in stats(g, "PHIE").text.splitlines() if l.startswith("  zones pooled:")))["mean"]
    assert R.agrees(m1, 2 * m0) or abs(m1 - 2 * m0) <= 2e-4
    r0 = R.fields(compare(f, "PHIE", "PHIT").text.splitlines()[3]).get("rank correlation")
    r1 = R.fields(compare(g, "PHIE", "PHIT").text.splitlines()[3]).get("rank correlation")
    assert r0 == r1


@pytest.mark.data
def test_t12_a_nan_gap_splits_a_run():
    t, f = first(lambda f: "PHIE" in f.inv.curves)
    base = ref_runs(f, {"condition": f"PHIE >= {float(np.nanmin(values(f)('PHIE')))}"})
    top, bot, n, th, k = max(base, key=lambda r: r[2])
    if n < 5:
        pytest.skip("no run of five samples")
    i = int(np.flatnonzero(np.isclose(f.view.depth, top))[0]) + n // 2

    def gap(x):
        x[i] = np.nan
        return x
    g = mutate(f, "PHIE", gap)
    c0 = R.runs_output(runs(f, f"PHIE >= {float(np.nanmin(values(f)('PHIE')))}").text)["count"]
    c1 = R.runs_output(runs(g, f"PHIE >= {float(np.nanmin(values(f)('PHIE')))}").text)["count"]
    assert c1 == c0 + 1


@pytest.mark.data
def test_t12_values_at_the_threshold_move_between_lt_and_le():
    t, f = first(lambda f: "SW" in f.inv.curves)
    g = mutate(f, "SW", lambda x: np.where(np.isfinite(x), 0.5, np.nan))
    assert R.runs_output(runs(g, "SW < 0.5").text)["total"] == 0
    have = sum(R.thickness(z, int(np.isfinite(values(f)("SW")[z.indices]).sum())) for z in f.view.zones)
    assert R.agrees(R.runs_output(runs(g, "SW <= 0.5").text)["total"], have)


@pytest.mark.data
def test_t12_removing_one_zone_changes_only_that_zone_and_the_pooled_lines():
    t, f = first(lambda f: "PHIE" in f.inv.curves and len(f.view.zones) >= 2)
    z = f.view.zones[0]

    def drop(x):
        x[z.indices] = np.nan
        return x
    g = mutate(f, "PHIE", drop)
    a, b = stats(f, "PHIE").text.splitlines(), stats(g, "PHIE").text.splitlines()
    for la, lb in zip(a, b):
        if la.startswith(f"  {z.zone_id} ") or la.startswith("  zones pooled:") or la.startswith("  whole interval"):
            continue
        assert la == lb


# --- T13 information needs ------------------------------------------------------------------------------------------

def pooled(text: str) -> dict:
    return R.fields(next(l for l in text.splitlines() if l.startswith("  zones pooled:")))


def need_net_flag(f, flag):
    out = R.runs_output(runs(f, flag).text)
    want = ref_runs(f, {"condition": flag})
    tot = sum(r[3] for r in want)
    return R.agrees(out["total"], tot), (out["total"], tot)


def need_cutoffs(f):
    cond = "PHIE >= 0.1 and VCL <= 0.4 and SW <= 0.5"
    out = R.runs_output(runs(f, cond).text)
    tot = sum(r[3] for r in ref_runs(f, {"condition": cond}))
    return R.agrees(out["total"], tot), (out["total"], tot)


def need_pay_average(f, c):
    text = stats(f, c, where="NET_PAY").text
    x = values(f)(c)[f.view.zoned & (values(f)("NET_PAY") > 0.5)]
    p = pooled(text)
    if not np.isfinite(x).any():
        return p["n"] == 0, (p, "no pay")
    return R.agrees(p["mean"], float(np.nanmean(x))), (p.get("mean"), float(np.nanmean(x)))


def need_best_zone(f, c):
    text = profile(f, c).text
    meds = [(z.zone_id, float(np.nanmedian(values(f)(c)[z.indices]))) for z in f.view.zones
            if np.isfinite(values(f)(c)[z.indices]).any()]
    line = next((ln for ln in text.splitlines() if ln.startswith("  highest zone by each statistic:")), "")
    if len(meds) < 2 or len({m for _, m in meds}) < 2:
        return "median " not in line, ("one zone",)
    top = max(m for _, m in meds)
    his = ", ".join(z for z, m in meds if m == top)                     # ranked by each statistic shown
    return f"median {his} (" in line and "best" not in text.lower(), (his,)


def need_first_last(f, cond):
    text = runs(f, cond).text
    want = ref_runs(f, {"condition": cond})
    if not want:
        return "shallowest" not in text, ("none",)
    m = re.search(rf"shallowest top ({R.NUM}) \S+ \(Z\d+\); deepest base ({R.NUM})", text)
    top, base = min(w[0] for w in want), max(w[1] for w in want)
    return bool(m) and R.agrees(float(m.group(1)), top) and R.agrees(float(m.group(2)), base), (m and m.groups(), top, base)


def need_log_vs_core(f, a, b):
    text = compare(f, a, b).text
    xa, xb = values(f)(a), values(f)(b)
    ok = f.view.zoned & np.isfinite(xa) & np.isfinite(xb)
    p = pooled(text)
    if not ok.any():
        return p["n"] == 0, ("no overlap",)
    return p["n"] == ok.sum() and R.agrees(p["difference mean"], float(np.mean(xa[ok] - xb[ok]))), (p, int(ok.sum()))


def need_relation(f, a, b):
    text = compare(f, a, b).text
    xa, xb = values(f)(a)[f.view.zoned], values(f)(b)[f.view.zoned]
    rho = R.rank_corr(xa, xb)
    p = pooled(text)
    return "difference mean" not in text and (not np.isfinite(rho) or R.agrees(p["rank correlation"], rho)), (p, rho)


def need_peak(f, c):
    lines = stats(f, c, statistics=["max"]).text.splitlines()          # the whole interval where it differs
    w = R.fields(next((l for l in lines if l.startswith("  whole interval")), None)
                 or next(l for l in lines if l.startswith("  zones pooled")))
    x = values(f)(c)
    ok = np.isfinite(x)
    at = float(f.view.depth[ok][np.argmax(x[ok])])
    return R.agrees(w["max"], float(x[ok].max())) and R.agrees(w["max_at"], at), (w, at)


def need_coverage(f, c):
    text = stats(f, c, statistics=["n"]).text
    shown = R.zone_lines(text)
    for z in f.view.zones:
        if z.zone_id in shown:
            g = R.fields(shown[z.zone_id])
            if g["n"] != np.isfinite(values(f)(c)[z.indices]).sum() or g["n_of"] != z.n_samples:
                return False, (z.zone_id, g)
    return True, ()


def need_class_per_zone(f):
    for key, sec in f.store.sections.items():
        if not key.startswith("hydrocarbon."):
            continue
        for label, rs in sec.classes.items():
            if not rs:
                continue
            out = R.runs_output(runs(f, f"{key}:{label}").text)
            for zid in {r.zone for r in rs}:
                want = sum(r.thickness for r in rs if r.zone == zid)
                got = out["zones"].get(zid, (None,))[0]
                if got is None or abs(got - want) > max(0.01 * want, f.inv.step):
                    return False, (key, label, zid, got, want)
            return True, ()
    return True, ("no hydrocarbon class",)


def need_step_value(f, name, p):
    m = next((m for m in f.inv.methods if m.step == name), None)
    if m is None or not isinstance(m.parameters.get(p), (int, float)):
        return True, ("not recorded",)
    return f"  {p}: {num(m.parameters[p])}" in step(f, name).text, (p, m.parameters[p])


def need_thin_beds(f, flag, t):
    out = R.runs_output(runs(f, flag, max_thickness=t).text)
    want = [r for r in ref_runs(f, {"condition": flag}) if r[3] <= t]
    return out["count"] == len(want) and R.agrees(out["total"], sum(r[3] for r in want)), (out["count"], len(want))


NEEDS = [
    ("net pay per zone and in total", {"NET_PAY"}, lambda f: need_net_flag(f, "NET_PAY")),
    ("net reservoir", {"RESFLAG"}, lambda f: need_net_flag(f, "RESFLAG")),
    ("net pay under other cutoffs", {"PHIE", "VCL", "SW"}, need_cutoffs),
    ("mean porosity over pay", {"PHIE", "NET_PAY"}, lambda f: need_pay_average(f, "PHIE")),
    ("mean saturation over pay", {"SW", "NET_PAY"}, lambda f: need_pay_average(f, "SW")),
    ("mean clay over pay", {"VCL", "NET_PAY"}, lambda f: need_pay_average(f, "VCL")),
    ("best zone for porosity", {"PHIE"}, lambda f: need_best_zone(f, "PHIE")),
    ("best zone for permeability", {"PERM"}, lambda f: need_best_zone(f, "PERM")),
    ("shallowest and deepest pay", {"NET_PAY"}, lambda f: need_first_last(f, "NET_PAY")),
    ("water-bearing rock", {"SW", "PHIE"}, lambda f: need_first_last(f, "SW > 0.8 and PHIE > 0.1")),
    ("gas from neutron-density", {"NPHI", "PHID"}, lambda f: need_first_last(f, "NPHI < PHID")),
    ("log against core-calibrated porosity", {"PHIE", "PHIE_CC"}, lambda f: need_log_vs_core(f, "PHIE", "PHIE_CC")),
    ("log against plug permeability", {"PERM", "KH_CORE"}, lambda f: need_log_vs_core(f, "PERM", "KH_CORE")),
    ("relation of porosity and permeability", {"PHIE", "PERM"}, lambda f: need_relation(f, "PHIE", "PERM")),
    ("where permeability peaks", {"PERM"}, lambda f: need_peak(f, "PERM")),
    ("coverage of the deep resistivity", {"RDEP"}, lambda f: need_coverage(f, "RDEP")),
    ("coverage of the neutron", {"NPHI"}, lambda f: need_coverage(f, "NPHI")),
    ("a hydrocarbon class per zone", set(), need_class_per_zone),
    ("the Archie exponent", set(), lambda f: need_step_value(f, "saturation", "m")),
    ("thin pay beds", {"NET_PAY"}, lambda f: need_thin_beds(f, "NET_PAY", 1.0)),
]


@pytest.mark.data
@pytest.mark.parametrize("name, curves, check", NEEDS, ids=[n[0] for n in NEEDS])
def test_t13_need(name, curves, check):
    ran, bad = 0, []
    for t, f in F():
        if not curves <= set(f.inv.curves):
            continue
        ran += 1
        try:
            ok, detail = check(f)
        except ToolError as e:
            ok, detail = False, ("ToolError", str(e)[:200])
        if not ok:
            bad.append((t.well, t.formation, detail))
    if not ran:
        pytest.skip(f"no formation has {sorted(curves)}")
    assert not bad, (name, len(bad), ran, bad[:5])
