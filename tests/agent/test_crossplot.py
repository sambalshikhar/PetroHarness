"""The crossplot lookup: a least-squares line of y on x, or on depth, pooled and per zone. Values are checked against
numpy computed here from the view's arrays.
    .venv/bin/python -m pytest tests/agent/test_crossplot.py -q   (PETROHARNESS_DATA selects the dataset)
"""
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from test_b0_inventory import formations  # noqa: E402
from petroharness.agent import options  # noqa: E402
from petroharness.agent.direction import parse_source  # noqa: E402
from petroharness.agent.ledger import Ledger, normalize  # noqa: E402
from petroharness.agent.loop import coerce_action, tools_text  # noqa: E402
from petroharness.agent.schemas import call  # noqa: E402
from petroharness.agent.tools import Formation, ToolError, crossplot  # noqa: E402
import b2_reference as R  # noqa: E402
crossplot = R.plain_tool(crossplot)  # the whole result, each line read as its block's (no ", Y on X")

PAIRS = (("RHOB", "NPHI"), ("PERM", "PHIE"), ("PERM_CC", "PHIE_CC"), ("SW", "PHIE"), ("BVW", "PHIE"), ("GR", "VCL"))


@lru_cache(maxsize=1)
def F() -> list:
    return [(t, Formation(inv, v, s)) for t, v, s, inv in formations()]


def fields(ln: str) -> dict:
    return {k: float(v) for k, v in re.findall(r"\b(n|slope|intercept|R2|correlation) (-?[\d.]+)", ln)}


def expected(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3 or np.ptp(x[ok]) == 0:
        return None
    slope, intercept = np.polyfit(x[ok], y[ok], 1)
    r = np.corrcoef(x[ok], y[ok])[0, 1] if np.ptp(y[ok]) > 0 else 0.0
    return {"n": ok.sum(), "slope": slope, "intercept": intercept, "R2": r * r, "correlation": r}


def close(got: dict, want: dict) -> bool:
    """Each shown value equals the numpy value at the precision num() writes (4 decimals, or 4 significant figures)."""
    for k, w in want.items():
        g = got.get(k)
        if g is None:
            return False
        tol = 0.6e-4 * max(1.0, abs(w)) if abs(w) >= 1 else max(abs(w) * 1e-3, 1e-12)
        if abs(g - w) > tol:
            return False
    return True


def check(f, r, x, y) -> list:
    bad = []
    lines = r.text.splitlines()
    for head, idx in [(f"  {z.zone_id} ", z.indices) for z in f.view.zones] + [("  zones pooled:", f.view.zoned)]:
        hit = [ln for ln in lines if ln.startswith(head)]
        if not hit:
            if "left out to keep this short" not in r.text:
                bad.append((head, "missing"))
            continue
        want = expected(x[idx], y[idx])
        if want is None:
            if "no line" not in hit[0] and "too few samples" not in hit[0]:
                bad.append((head, hit[0]))
        elif not close(fields(hit[0]), want):
            bad.append((head, hit[0], want))
    return bad


@pytest.mark.data
def test_lines_match_numpy_on_every_formation():
    bad, done = [], 0
    for t, f in F():
        for yc, xc in [(a, b) for a, b in PAIRS if a in f.inv.curves and b in f.inv.curves][:3]:
            r = crossplot(f, yc, xc)
            bad += [(t.well, yc, xc, *b) for b in check(f, r, f.view.values(xc), f.view.values(yc))]
            done += 1
    assert done and not bad, bad[:8]


@pytest.mark.data
def test_depth_axis_is_the_trend_with_depth():
    bad = []
    for t, f in F()[:12]:
        c = next(c for c in ("PHIE", "GR", "RHOB", "SW") if c in f.inv.curves)
        r = crossplot(f, c, "DEPTH")
        assert f"per {f.inv.depth_unit}" in r.text.splitlines()[0] and "DEPTH [" in r.text
        bad += [(t.well, c, *b) for b in check(f, r, f.depth, f.view.values(c))]
    assert not bad, bad[:8]


@pytest.mark.data
def test_log_y_fits_log10_of_the_positive_values():
    bad, done = [], 0
    for t, f in F():
        c = next((c for c in ("PERM", "PERM_CC") if c in f.inv.curves), None)
        p = next((c for c in ("PHIE", "PHIE_CC") if c in f.inv.curves), None)
        if not (c and p):
            continue
        y = f.view.values(c)
        with np.errstate(invalid="ignore", divide="ignore"):
            ly = np.where(y > 0, np.log10(np.where(y > 0, y, 1.0)), np.nan)
        r = crossplot(f, c, p, log_y="true")                  # a flag sent as text reads as a flag
        assert r.text.splitlines()[0].startswith(f"Least-squares line log10({c}) = intercept + slope * {p}")
        bad += [(t.well, *b) for b in check(f, r, f.view.values(p), ly)]
        done += 1
    if not done:
        pytest.skip("no permeability and porosity pair in this dataset")
    assert not bad, bad[:8]


@pytest.mark.data
def test_bad_calls_say_what_is_wrong():
    from petroharness.agent import engine as E
    t, f = F()[0]
    c = next(iter(f.inv.curves))
    with pytest.raises(ToolError, match="two different axes"):
        crossplot(f, c, c)
    with pytest.raises(ToolError, match="did you mean|is not a curve"):
        crossplot(f, "QQXZ_NOT_A_CURVE", c)
    other = next((x for x in f.inv.curves if x != c and len(x) >= 4), None)
    if other is not None:                                # a misspelt name with one clear match is that curve,
        typo = other + other[-1]                         #   labelled by its own name (never a KeyError)
        try:
            text = crossplot(f, typo, c).text
        except ToolError:                           # two close matches: the message says so
            text = ""
        assert not text or E.label(f, other) in text
    with pytest.raises(ToolError, match="log_y must be true or false"):
        crossplot(f, c, "DEPTH", log_y="maybe")
    with pytest.raises(ToolError, match="no zone"):
        crossplot(f, c, "DEPTH", zones=["Z999"])


@pytest.mark.data
def test_too_few_samples_and_a_constant_axis_give_no_line():
    t, f = F()[0]
    c = next(c for c in ("GR", "RHOB", "PHIE") if c in f.inv.curves)
    x, d = f.view.values(c), f.depth
    z = f.view.zones[0]
    k = [i for i in np.asarray(z.indices) if np.isfinite(x[i])][:2]      # a depth window over two samples of a zone
    r = crossplot(f, c, "DEPTH", where=f"{d[k[0]]}-{d[k[1]]}")
    pooled = [ln for ln in r.text.splitlines() if ln.startswith("  zones pooled:")][0]
    assert fields(pooled)["n"] == 2 and "too few samples for a line" in pooled, pooled
    flag = next((g for g in f.view.reg.flags if g in f.inv.curves and np.nansum(f.view.values(g) > 0.5) >= 3), None)
    if flag:                                                              # where a flag is set it is constant
        r = crossplot(f, c, flag, where=flag)
        pooled = [ln for ln in r.text.splitlines() if ln.startswith("  zones pooled:")][0]
        assert "x is constant: no line" in pooled, pooled


@pytest.mark.data
def test_numbers_are_recorded_for_citing():
    t, f = F()[0]
    yc, xc = next((a, b) for a, b in PAIRS + (("GR", "RHOB"),) if a in f.inv.curves and b in f.inv.curves)
    r = crossplot(f, yc, xc)
    pooled = fields([ln for ln in r.text.splitlines() if ln.startswith("  zones pooled:")][0])
    for k in ("slope", "intercept", "R2"):
        assert any(abs(v - pooled[k]) <= 1e-4 * max(1, abs(pooled[k])) for v in r.numbers if isinstance(v, float)), k


@pytest.mark.data
def test_the_brief_lists_the_crossplot_and_the_ledger_opens_it_once():
    t, f = F()[0]
    yc, xc = next((a, b) for a, b in PAIRS + (("GR", "RHOB"),) if a in f.inv.curves and b in f.inv.curves)
    assert '{"crossplot": {"y": ..., "x": ..., "zones": ..., "log_y": ..., "log_x": ..., "where": ...}}' in tools_text()
    led = Ledger(f)
    item, new = led.open("crossplot", {"y": yc.lower(), "x": xc})
    again, new2 = led.open("crossplot", {"y": yc, "x": xc.lower()})
    assert new and not new2 and again is item
    assert item.call_text().upper().startswith(f"CROSSPLOT {yc} ON {xc}")


def test_the_shapes_models_send():
    assert coerce_action({"crossplot": ["RHOB", "NPHI"]}) == ("tool", "crossplot", {"y": "RHOB", "x": "NPHI"})
    assert coerce_action({"crossplot": {"y": "PERM", "x": "PHIE", "log_y": True}}) == \
        ("tool", "crossplot", {"y": "PERM", "x": "PHIE", "log_y": True})
    assert coerce_action({"tool": "crossplot", "args": {"y": "GR", "x": "DEPTH"}}) == \
        ("tool", "crossplot", {"y": "GR", "x": "DEPTH"})
    assert parse_source("crossplot RHOB NPHI   (the matrix line)") == ("crossplot", {"y": "RHOB", "x": "NPHI"})
    assert normalize("crossplot", {"y": "rhob", "x": "nphi"}) == normalize("crossplot", {"y": "RHOB", "x": "NPHI"})


@pytest.mark.data
def test_call_through_the_door_reads_text_flags_and_ignores_unknowns():
    t, f = F()[0]
    yc, xc = next((a, b) for a, b in PAIRS + (("GR", "RHOB"),) if a in f.inv.curves and b in f.inv.curves)
    r = call(f, "crossplot", '{"y": "%s", "x": "%s", "log_y": "false", "reason": "matrix line", "colour": "red"}' % (yc, xc))
    assert r.text.splitlines()[0].startswith("(ignored colour") and f"Least-squares line {yc} =" in r.text
