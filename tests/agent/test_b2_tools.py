"""Tool tests, offline part (T1-T6, T8), on every formation of the configured dataset.

    .venv/bin/python -m pytest tests/agent/test_b2_tools.py -q   (PETROHARNESS_DATA selects the dataset)

The expected values are computed here from the view's arrays with numpy/scipy, not with the tools' helpers.
"""
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import spearmanr

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from test_b0_inventory import formations  # noqa: E402
from test_b1_map import advisory  # noqa: E402
from petroharness.agent import options  # noqa: E402
from petroharness.agent import engine as E  # noqa: E402
from petroharness.agent.engine import Result, max_chars  # noqa: E402
from petroharness.agent.map import num  # noqa: E402
from petroharness.agent.tools import _BOOKKEEPING, Formation, ToolError, compare, profile, runs, section, stats, step  # noqa: E402
import b2_reference as R  # noqa: E402
from petroharness.well import summary as S  # noqa: E402
compare, profile, runs, section, stats = map(R.plain_tool, (compare, profile, runs, section, stats))  # added labels read plain

KEY = ("SW", "PHIE", "PHIT", "PHIE_CC", "PERM", "PERM_CC", "VCL", "BVW", "SO", "KH_CORE", "PHIC", "SWC", "RDEP", "RT",
       "NPHI", "RHOB", "GR", "NET_PAY", "RESFLAG")
REL = 1e-9


@lru_cache(maxsize=1)
def F() -> list:
    return [(t, Formation(inv, v, s)) for t, v, s, inv in formations()]


def keys(f) -> list:
    return [c for c in KEY if c in f.inv.curves]


def finite(x):
    x = np.asarray(x, dtype=float)
    return x[np.isfinite(x)]


def holds(numbers, v) -> bool:
    return any(abs(x - v) <= max(REL * abs(v), 1e-12) for x in numbers if isinstance(x, (int, float)) and np.isfinite(x))


def line(text, head):
    hit = [ln for ln in text.splitlines() if ln.startswith(head)]
    assert hit, (head, text[:500])
    return hit[0]


def field(ln, name):
    m = re.search(rf"(?:^|[:,] ){re.escape(name)} (-?[\d.]+|n/a)", ln)
    return m.group(1) if m else None


# --- T1 correct -----------------------------------------------------------------------------------------------------

def expected_stats(x, names=None, log=False):
    """numpy's statistics of x: those named (all when None); on a log-shaped curve (log) the percentiles are taken on
    log10 values (the summary layer's shape rule, src/petroharness/well/summary.py)."""
    x = finite(x)
    if x.size == 0:
        return {"n": 0}
    out = {"n": x.size, "mean": x.mean(), "median": np.median(x), "min": x.min(), "max": x.max(),
           "p10": np.quantile(x, 0.1), "p90": np.quantile(x, 0.9), "std": x.std()}
    if (x > 0).all():
        out["geo_mean"] = float(np.exp(np.log(x).mean()))
        if log:
            out["p10"], out["p90"] = (float(10 ** np.quantile(np.log10(x), q)) for q in (0.1, 0.9))
    return {k: v for k, v in out.items() if names is None or k in names}


@pytest.mark.data
def test_t1_stats_match_numpy():
    bad = []
    for t, f in F():
        for c in [c for c in keys(f) if c not in f.view.reg.flags]:     # flags: test_b2_dense checks set and thickness
            r = stats(f, c)
            x = f.view.values(c)
            names, log = S.names(None, x), S.log_shaped(x)        # the default set by the curve's shape
            if R.zone_table(r.text):                       # the zones in one table, cell by cell
                zs = {z.zone_id: z for z in f.view.zones}
                bad += [(t.well, c, "table") + b for b in R.check_zone_table(r.text, zs, list(zs), {c: x}, f.view.depth)]
                r = Result(R.without_table(r.text), r.numbers, r.rows)
                blocks = []
            else:
                blocks = [(f"  {z.zone_id} ", x[z.indices], z.zone_id) for z in f.view.zones]
            blocks += [("  zones pooled:", x[f.view.zoned], None)]
            away = ~np.asarray(f.view.zoned)
            if np.isfinite(np.asarray(x, dtype=float)[away]).any():      # the whole interval where it differs
                blocks.append(("  whole interval (", x, None))
            else:
                assert "  whole interval (" not in r.text, (t.well, c)
            for head, xs, zid in blocks:
                src = r
                if zid and not any(ln.startswith(head) for ln in r.text.splitlines()):
                    if "zones left out to keep this short" not in r.text:
                        bad.append((t.well, c, zid, "missing without a left-out line"))
                    src = stats(f, c, zones=[zid])                   # asked for, it comes
                ln = line(src.text, head)
                for name, v in expected_stats(xs, names, log).items():
                    shown = field(ln, name)
                    if shown != num(int(v) if name == "n" else float(v)) or not holds(src.numbers, float(v)):
                        bad.append((t.well, t.formation, c, head.strip(), name, shown, v))
    assert not bad, bad[:10]


def conditions(f) -> list:
    """Real conditions on this formation: one threshold term per key curve (at its pooled median), and one pair."""
    out = []
    for c in keys(f)[:4]:
        x = finite(f.view.values(c)[f.view.zoned])
        if x.size:
            out.append((f"{c} > {num(float(np.median(x)))}", [(c, ">", float(num(float(np.median(x)))))]))
    if "SW" in f.inv.curves and "PHIE" in f.inv.curves:
        out.append(("SW < 0.5 and PHIE > 0.1", [("SW", "<", 0.5), ("PHIE", ">", 0.1)]))
    return out


@pytest.mark.data
def test_t1_runs_match_numpy():
    bad = []
    for t, f in F():
        for text, terms in conditions(f):
            r = runs(f, text)
            m = np.ones(f.depth.size, dtype=bool)
            for c, op, v in terms:
                x = f.view.values(c)
                with np.errstate(invalid="ignore"):
                    m &= np.isfinite(x) & ((x > v) if op == ">" else (x < v))
            total = 0.0
            for z in f.view.zones:
                n = int(m[z.indices].sum())
                th = (z.base - z.top) * n / z.n_samples
                total += th
                ln = line(r.text, f"  {z.zone_id} ")
                if f"{num(th)} {f.inv.depth_unit} ({100 * n / z.n_samples:.1f}% of the zone)" not in ln:
                    bad.append((t.well, t.formation, text, z.zone_id, ln, th))
            if not holds(r.numbers, total):
                bad.append((t.well, t.formation, text, "total", total))
            # run count: consecutive True samples within one zone
            count = 0
            for z in f.view.zones:
                zm = m[z.indices].astype(int)
                count += int(zm[0]) + int(np.sum(np.diff(zm) == 1)) if zm.size else 0
            if f"({count} runs)" not in r.text.splitlines()[0]:
                bad.append((t.well, t.formation, text, "count", r.text.splitlines()[0], count))
    assert not bad, bad[:10]


@pytest.mark.data
def test_t1_compare_matches_numpy_and_scipy():
    bad = []
    for t, f in F():
        pairs = [(a, b) for a, b in (("PHIE", "PHIE_CC"), ("PERM", "PERM_CC"), ("PHIE", "PHIT"), ("SW", "SWC"),
                                    ("PHIE_CC", "PHIC"), ("PERM_CC", "KH_CORE")) if a in f.inv.curves and b in f.inv.curves]
        for a, b in pairs:
            r = compare(f, a, b, tolerance=0.02)
            xa, xb = f.view.values(a), f.view.values(b)
            for head, idx in [(f"  {z.zone_id} ", z.indices) for z in f.view.zones] + [("  zones pooled:", f.view.zoned)]:
                pa, pb = xa[idx], xb[idx]
                ok = np.isfinite(pa) & np.isfinite(pb)
                if not any(ln.startswith(head) for ln in r.text.splitlines()):
                    if "zones left out to keep this short" not in r.text:
                        bad.append((t.well, a, b, head, "missing without a left-out line"))
                    continue
                ln = line(r.text, head)
                if ok.sum() == 0:
                    if "n 0" not in ln:
                        bad.append((t.well, a, b, head, ln))
                    continue
                d = pa[ok] - pb[ok]
                if "(difference " not in r.text.splitlines()[0]:            # different scales: no difference shown
                    want = {"n": int(ok.sum())}
                    if "difference mean" in ln:
                        bad.append((t.well, a, b, head.strip(), "difference shown across scales"))
                    continue
                want = {"n": int(ok.sum()), "difference mean": d.mean(), "sd": d.std()}
                for name, v in want.items():
                    if field(ln, name) != num(v) or not holds(r.numbers, float(v)):
                        bad.append((t.well, a, b, head.strip(), name, field(ln, name), v))
                share = 100 * np.mean(np.abs(d) > 0.02)
                # which way it differs, and how often
                want_text = (f"{a} > {b} + 0.02 in {100 * np.mean(d > 0.02):.1f}%, {a} < {b} - 0.02 in "
                             f"{100 * np.mean(d < -0.02):.1f}%, within 0.02 in {100 * np.mean(np.abs(d) <= 0.02):.1f}%")
                if want_text not in ln:
                    bad.append((t.well, a, b, head.strip(), "direction", ln, want_text))
                if ok.sum() >= 3 and np.std(pa[ok]) > 0 and np.std(pb[ok]) > 0:
                    rho = spearmanr(pa[ok], pb[ok]).statistic
                    if np.isfinite(rho) and abs(float(field(ln, "rank correlation")) - rho) > 5e-4 * max(1, abs(rho)):
                        bad.append((t.well, a, b, head.strip(), "rank", ln, rho))
    assert not bad, bad[:10]


@pytest.mark.data
def test_t1_profile_matches_numpy():
    bad = []
    for t, f in F():
        for c in keys(f)[:6]:
            r = profile(f, c)
            meds = []
            table = R.zone_table(r.text)                         # many zones: one table, checked cell by cell
            if table:
                zs = {z.zone_id: z for z in f.view.zones}
                bad += [(t.well, c, "table") + b for b in R.check_zone_table(r.text, zs, list(zs), {c: f.view.values(c)},
                                                                            f.view.depth)]
            for z in f.view.zones:
                x = finite(f.view.zone_values(z, c))
                if table:
                    if x.size:
                        meds.append((z, float(np.median(x))))
                    continue
                ln = line(r.text, f"  {z.zone_id} ")
                if x.size == 0:
                    if "no data" not in ln:
                        bad.append((t.well, c, z.zone_id, ln))
                    continue
                meds.append((z, float(np.median(x))))
                if field(ln, "median") != num(float(np.median(x))) or field(ln, "mean") != num(float(x.mean())):
                    bad.append((t.well, c, z.zone_id, ln, np.median(x), x.mean()))
            hi_line = next((ln for ln in r.text.splitlines() if ln.startswith("  highest zone by each statistic:")), "")
            if len(meds) >= 2 and len({m for _, m in meds}) > 1:
                top = max(m for _, m in meds)
                his = [z.zone_id for z, m in meds if m == top]
                if not re.search(rf"median {', '.join(his)} \(", hi_line):
                    bad.append((t.well, c, "highest", his, hi_line))
            if len(meds) >= 3:                                   # each statistic's zone values against depth
                rho = spearmanr([(z.top + z.base) / 2 for z, _ in meds], [m for _, m in meds]).statistic
                depth = next((ln for ln in r.text.splitlines() if ln.startswith("  with depth (rank correlation")), "")
                m = re.search(r"median (-?[\d.]+)", depth)
                if np.isfinite(rho) and (not m or abs(float(m.group(1)) - rho) > 5e-4 * max(1, abs(rho))):
                    bad.append((t.well, c, "depth order", rho, depth))
    assert not bad, bad[:10]


@pytest.mark.data
def test_t1_section_and_step_show_the_inventory():
    bad = []
    for t, f in F():
        for s in f.inv.sections:
            text = section(f, s.key).text
            for k in s.classes:
                if f"  {k.name}" not in text:
                    bad.append((t.well, s.key, k.name))
                if k.thickness is not None and f"{num(k.thickness)} {f.inv.depth_unit}" not in text:
                    bad.append((t.well, s.key, k.name, "thickness"))
        for m in f.inv.methods:
            text = step(f, m.step).text
            if not text.startswith(f"step {m.step}: method {m.method}"):
                bad.append((t.well, m.step, "head"))
            from petroharness.record.card import plain_inputs     # a fallback input in plain words
            for e in m.equations_here:
                if plain_inputs(e, m.inputs) not in text:
                    bad.append((t.well, m.step, "equation", e[:60]))
            for d in m.decisions_here:
                if plain_inputs(d, m.inputs) not in text:
                    bad.append((t.well, m.step, "record", d[:60]))
            for k, v in m.parameters.items():
                if k.endswith(_BOOKKEEPING):
                    continue
                if isinstance(v, (int, float)) and not isinstance(v, bool) and f"  {k}: {num(v)}" not in text:
                    bad.append((t.well, m.step, k))
    assert not bad, bad[:10]


# --- T2 input situations --------------------------------------------------------------------------------------------

@pytest.mark.data
def test_t2_absent_curve_names_what_is_available():
    t, f = F()[0]
    with pytest.raises(ToolError, match="curves with data"):
        stats(f, "NO_SUCH_CURVE")
    with pytest.raises(ToolError, match="curves with data"):
        compare(f, "NO_SUCH_CURVE", keys(f)[0])
    with pytest.raises(ToolError, match="zones: Z1"):
        stats(f, keys(f)[0], zones=["Z999"])
    first = stats(f, keys(f)[0], statistics=["skewness"]).shown.splitlines()[0]          # said, with how to derive it
    assert first.startswith("no statistic 'skewness' in this tool (it computes n, mean") and "calc" in first
    with pytest.raises(ToolError, match="sections: "):
        section(f, "no.such")
    with pytest.raises(ToolError, match="steps: "):
        step(f, "no_such_step")


@pytest.mark.data
@pytest.mark.parametrize("cond", ["SW <", "SW << 0.5", "SW < 0.5 and", "SW < abc def", "NOT_A_FLAG", "SW < 0.5 xor PHIE > 0.1"])
def test_t2_malformed_condition_says_how_to_write_one(cond):            # "0.5 > SW" is not malformed: it reads as SW < 0.5
    t, f = F()[0]
    with pytest.raises(ToolError, match="CURVE OP NUMBER"):
        runs(f, cond)


@pytest.mark.data
def test_t2_a_zone_without_data_says_n_0():
    seen = 0
    for t, f in F():
        for c in keys(f):
            for z in f.view.zones:
                if not np.isfinite(f.view.zone_values(z, c)).any():
                    seen += 1
                    assert re.search(r": n 0 of \d+(,|$)", line(stats(f, c, zones=[z.zone_id]).text, f"  {z.zone_id} "))
                    ln = line(profile(f, c).text, f"  {z.zone_id} ")
                    assert ln.endswith("no data") or ln.endswith("| 0 | -"), ln          # a row, or a table cell
    if not seen:
        pytest.skip("every key curve has data in every zone")


@pytest.mark.data
def test_t2_one_zone_and_many_zones():
    by_zones = sorted(F(), key=lambda tf: len(tf[1].view.zones))
    for t, f in (by_zones[0], by_zones[-1]):
        for c in keys(f)[:3]:
            for r in (stats(f, c), profile(f, c), runs(f, conditions(f)[0][0])):
                assert len(r.shown) <= max_chars()                       # the text shown; the item keeps every row
    if len(by_zones[-1][1].view.zones) < 10:
        pytest.skip("no formation with ten or more zones in this dataset")


@pytest.mark.data
def test_t2_no_lithology_zone_is_named_plainly():
    hit = [(t, f, z) for t, f in F() for z in f.view.zones if z.lithology.upper() == "NO_LITHOLOGY_DATA"]
    if not hit:
        pytest.skip("no zone without lithology data in this dataset")
    for t, f, z in hit[:20]:
        assert f"  {z.zone_id} no lithology data " in stats(f, keys(f)[0], zones=[z.zone_id]).text


@pytest.mark.data
def test_t2_flags_and_classes_are_conditions():
    done = 0
    for t, f in F():
        flags = [c for c in f.inv.curves if c in f.view.reg.flags]
        for c in flags[:2]:
            r = runs(f, c)
            assert r.text.startswith(f"Runs where {c} > 0.5"), r.text[:80]
            done += 1
        for key, sec in list(f.store.sections.items())[:3]:
            for label, rs in list(sec.classes.items())[:1]:
                r = runs(f, f"{key}:{label}")
                total = sum(x.thickness for x in rs)
                shown = float(re.search(r"all zones: ([\d.]+)", r.text).group(1))
                assert abs(shown - total) <= max(0.01 * total, f.inv.step), (t.well, key, label, shown, total)
                done += 1
    assert done


@pytest.mark.data
def test_t2_a_class_name_in_several_sections_asks_which():
    for t, f in F():
        seen = {}
        for key, sec in f.store.sections.items():
            for label in sec.classes:
                seen.setdefault(str(label).upper(), []).append(key)
        twice = [k for k, v in seen.items() if len(v) > 1 and k not in f.inv.curves]
        if twice:
            with pytest.raises(ToolError, match="sections: "):
                runs(f, twice[0])
            return
    pytest.skip("no class name shared by two sections")


@pytest.mark.data
def test_t2_percent_curves_say_so():
    hit = [(t, f, c) for t, f in F() for c, cv in f.inv.curves.items() if cv.percent]
    if not hit:
        pytest.skip("no percent curve in this dataset")
    for t, f, c in hit[:20]:
        head = stats(f, c).text.splitlines()[0]
        assert "percent" in head or "%" in head, head


# --- T3 bounded, T4 plain, T5 labelled ------------------------------------------------------------------------------

def outputs(f):
    """(tool, argument, the text shown, the whole result) of each lookup (the item keeps the rows cut from the text
    shown)."""
    shown = lambda r: (getattr(r, "shown", r.text), r.text)
    for c in keys(f):
        yield ("stats", c) + shown(stats(f, c))
        yield ("profile", c) + shown(profile(f, c))
    yield ("stats all", "") + shown(stats(f, keys(f)[:6]))
    for text, _ in conditions(f):
        yield ("runs", text) + shown(runs(f, text))
    for s in f.inv.sections:
        yield ("section", s.key) + shown(section(f, s.key))
    for m in f.inv.methods:
        yield ("step", m.step) + shown(step(f, m.step))
    if "PHIE" in f.inv.curves and "PHIE_CC" in f.inv.curves:
        yield ("compare", "PHIE") + shown(compare(f, "PHIE", "PHIE_CC"))


@pytest.mark.data
def test_t3_t4_bounded_and_plain():
    big, hits = [], []
    for t, f in F():
        for tool, arg, text, whole in outputs(f):
            if len(text) > max_chars():
                big.append((t.well, t.formation, tool, arg, len(text)))
            hits += [(t.well, tool, arg, h) for h in advisory(text + "\n" + whole)]
    assert not big, big[:10]
    assert not hits, hits[:10]


@pytest.mark.data
def test_t5_labelled():
    bad = []
    for t, f in F():
        for c in keys(f):
            cv = f.inv.curves[c]
            for r in (stats(f, c), profile(f, c)):
                text = R.without_table(r.text)                        # a zone table comes first, then the curve
                head = text.splitlines()[0]
                if not head.startswith(f"{c}{f' [{cv.unit}]' if cv.unit else ''} = {cv.meaning} ({E.status(f, c)}"):
                    bad.append((t.well, c, head[:80]))
                for ln in text.splitlines()[1:]:
                    if not re.match(r"  (Z\d+ |zones pooled:|these zones pooled:|whole interval \(\d+ samples outside any zone\):|"
                                    r"outside any zone \(\d+ samples; not a zone\):|"
                                    r"highest zone by each statistic:|lowest zone by each statistic:|with depth \(rank|"
                                    r"  (upper|middle|lower) third )", ln):     # a single zone's thirds
                        bad.append((t.well, c, ln[:80]))
    assert not bad, bad[:10]


# --- T6 mutations ---------------------------------------------------------------------------------------------------

class Mutated:
    """A view whose curve c returns changed values; everything else is the real view."""
    def __init__(self, view, c, fn):
        self._v, self._c, self._fn = view, c, fn

    def __getattr__(self, k):
        return getattr(self._v, k)

    def values(self, curve):
        x = self._v.values(curve)
        return self._fn(x.copy()) if curve == self._c and x is not None else x

    def zone_values(self, zone, curve):
        x = self.values(curve)
        return None if x is None else x[zone.indices]


def real(c):
    for t, f in F():
        if c in f.inv.curves and len(f.view.zones) >= 2 and np.isfinite(f.view.zone_values(f.view.zones[0], c)).any():
            return t, f
    pytest.skip(f"no formation with {c} and two zones")


@pytest.mark.data
def test_t6_nan_zone():
    c = next(k for k in ("SW", "PHIE", "VCL") if any(k in f.inv.curves for _, f in F()))
    t, f = real(c)
    z1 = f.view.zones[0]

    def drop(x):
        x[z1.indices] = np.nan
        return x
    g = Formation(f.inv, Mutated(f.view, c, drop), f.store)
    before, after = stats(f, c).text, stats(g, c).text
    assert re.search(r": n 0 of \d+$", line(after, f"  {z1.zone_id} "))
    n_before = int(field(line(before, "  zones pooled:"), "n"))
    n_after = int(field(line(after, "  zones pooled:"), "n"))
    assert n_before - n_after == int(np.isfinite(f.view.zone_values(z1, c)).sum())
    assert line(after, f"  {f.view.zones[1].zone_id} ") == line(before, f"  {f.view.zones[1].zone_id} ")


@pytest.mark.data
def test_t6_flat_curve():
    t, f = real("PHIE")
    g = Formation(f.inv, Mutated(f.view, "PHIE", lambda x: np.where(np.isfinite(x), 0.15, np.nan)), f.store)
    r = stats(g, "PHIE").text
    r = stats(g, "PHIE", statistics=["mean", "std"]).text
    assert field(line(r, "  zones pooled:"), "std") == "0" and field(line(r, "  zones pooled:"), "mean") == "0.15"
    p = profile(g, "PHIE").text                                   # equal values: no ranking, no order with depth
    assert "highest zone by" not in p and "with depth" not in p


@pytest.mark.data
def test_t6_shift_moves_means_and_differences():
    t, f = real("PHIE")
    g = Formation(f.inv, Mutated(f.view, "PHIE", lambda x: x + 0.05), f.store)
    a = float(field(line(stats(f, "PHIE").text, "  zones pooled:"), "mean"))
    b = float(field(line(stats(g, "PHIE").text, "  zones pooled:"), "mean"))
    assert abs(b - a - 0.05) < 1e-3
    other = next((c for c in ("PHIE_CC", "PHIT") if c in f.inv.curves), None)
    if other:
        d0 = float(field(line(compare(f, "PHIE", other).text, "  zones pooled:"), "difference mean"))
        d1 = float(field(line(compare(g, "PHIE", other).text, "  zones pooled:"), "difference mean"))
        assert abs(d1 - d0 - 0.05) < 1e-3


@pytest.mark.data
def test_t6_condition_follows_the_data():
    t, f = real("SW")
    g = Formation(f.inv, Mutated(f.view, "SW", lambda x: x - 10.0), f.store)
    z = f.view.zones[0]
    share = 100 * np.isfinite(f.view.zone_values(z, "SW")).mean()
    assert f"({share:.1f}% of the zone)" in line(runs(g, "SW < 0").text, f"  {z.zone_id} ")
    g2 = Formation(f.inv, Mutated(f.view, "SW", lambda x: x + 10.0), f.store)
    assert "(0 runs)" in runs(g2, "SW < 1").text


# --- T8 fast --------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_t8_each_call_under_a_second():
    t, f = max(F(), key=lambda tf: tf[1].inv.samples * max(len(tf[1].view.zones), 1))
    slow = []
    calls = [("stats", lambda: stats(f, keys(f)[:6]))]
    calls += [(f"runs {c}", lambda c=c: runs(f, c)) for c, _ in conditions(f)]
    calls += [(f"profile {c}", lambda c=c: profile(f, c)) for c in keys(f)[:3]]
    calls += [(f"section {s.key}", lambda k=s.key: section(f, k)) for s in f.inv.sections[:5]]
    calls += [(f"step {m.step}", lambda k=m.step: step(f, k)) for m in f.inv.methods]
    for name, call in calls:
        t0 = time.perf_counter()
        call()
        dt = time.perf_counter() - t0
        if dt >= 1.0:
            slow.append((name, round(dt, 2)))
    assert not slow, (t.well, t.formation, f.inv.samples, slow)
