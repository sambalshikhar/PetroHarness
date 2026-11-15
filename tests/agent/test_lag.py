"""lag_correlation (depth matching by cross-correlation) and the guide that names it.

    .venv/bin/python -m pytest tests/agent/test_lag.py -q        (PETROHARNESS_DATA selects the dataset)
"""
import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from test_b2_tools import F  # noqa: E402
from petroharness.agent.engine import ToolError  # noqa: E402


def _with(*curves, n=200):
    hit = [f for t, f in F() if all(c in f.inv.curves for c in curves) and f.view.mask.sum() >= n]
    if not hit:
        pytest.skip(f"no formation with {curves} and {n} samples")
    return hit[0]


def _peak(a, b, K):
    best = None
    for k in range(-K, K + 1):
        x, y = (a[:a.size - k], b[k:]) if k >= 0 else (a[-k:], b[:b.size + k])
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() < 10:
            continue
        r = float(np.corrcoef(x[ok], y[ok])[0, 1])
        if best is None or abs(r) > abs(best[1]):
            best = (k, r)
    return best


def _line(text, a, b):
    return next(ln for ln in text.splitlines() if ln.strip().startswith(f"{a} vs {b}") or
                re.match(rf"\s*{a}\b.* vs {b}\b", ln))


@pytest.mark.data
def test_a_planted_shift_is_found_with_its_size_and_sign(monkeypatch):
    from petroharness.agent.compute import lag_correlation
    f = _with("GR")
    gr = np.asarray(f.view.values("GR"), dtype=float)
    planted = np.full_like(gr, np.nan)
    planted[4:] = gr[:-4]                         # the same features 4 samples deeper
    real = f.view.values
    monkeypatch.setattr(f.view, "values", lambda c: planted if c == "RHOB" else real(c))
    if "RHOB" not in f.inv.curves:
        pytest.skip("RHOB not in this formation")
    step = float(np.median(np.diff(np.asarray(f.depth, dtype=float))))
    text = lag_correlation(f, ["GR", "RHOB"]).text
    ln = _line(text, "GR", "RHOB")
    dz = float(re.search(r"at dz (-?[\d.]+)", ln).group(1))
    assert abs(dz - (-4 * step)) < 1e-3 * max(1.0, step) and "shallower than RHOB" in ln, ln
    assert float(re.search(r"peak r (-?[\d.]+)", ln).group(1)) > 0.999


@pytest.mark.data
def test_the_peak_matches_an_independent_computation():
    from petroharness.agent.compute import lag_correlation
    f = _with("GR", "RHOB", n=400)
    d = np.asarray(f.depth, dtype=float)
    step = float(np.median(np.diff(d)))
    K = max(1, int(round(f.view.to_unit(3.0) / step)))
    a, b = (np.asarray(f.view.values(c), dtype=float) for c in ("GR", "RHOB"))
    k, r = _peak(a, b, K)
    ln = _line(lag_correlation(f, ["GR", "RHOB"]).text, "GR", "RHOB")
    if k == 0:
        assert "strongest at zero lag" in ln
    else:
        assert abs(float(re.search(r"at dz (-?[\d.]+)", ln).group(1)) - (-k * step)) < 1e-3 * max(1.0, step), ln
        assert abs(float(re.search(r"peak r (-?[\d.]+)", ln).group(1)) - r) < 5e-3, ln


@pytest.mark.data
def test_bad_arguments_are_messages():
    from petroharness.agent.compute import lag_correlation
    f = _with("GR")
    with pytest.raises(ToolError, match="two or more curves"):
        lag_correlation(f, ["GR"])
    with pytest.raises(ToolError, match="max_lag must be a positive depth"):
        lag_correlation(f, ["GR", "GR"] if "RHOB" not in f.inv.curves else ["GR", "RHOB"], max_lag=-1)


def test_the_tool_is_offered_and_its_skill_is_generic():
    """The tool is offered, and the general data_quality guide names it (no guide of its own)."""
    from petroharness.agent.direction import plugged
    from petroharness.agent.schemas import named
    assert "lag_correlation" in [t["function"]["name"] for t in named()]
    lib = plugged()                                                  # the plugged library (researched)
    assert lib.on("data_quality") == ["data_quality"] and "  data_quality: " in lib.index(["porosity"])
    assert any(e.startswith("lag_correlation ") for e in lib.facets["data_quality"]["compare"])


def test_every_tool_the_model_can_be_shown_is_one_the_loop_reads():
    """Every tool the model can be shown (crossplot, lag_correlation included) is in the parser's names: a call to a
    tool missing from them would be dropped without a word."""
    from petroharness.agent.loop import coerce_action
    from petroharness.agent.schemas import named
    for t in named():
        name = t["function"]["name"]
        assert coerce_action({name: {}}) is not None or coerce_action({name: "GR"}) is not None, name


@pytest.mark.data
@pytest.mark.parametrize('flex', [True])
def test_an_action_the_loop_cannot_read_is_said_back(flex):
    from petroharness.llm import Usage
    from test_b5_loop import Script, _session
    from petroharness.agent.loop import investigate
    s = _session()
    first = {"points": ["What is the mean GR?"], "intent": "value", "edits": [],
             "next": [{"no_such_tool": {"curves": ["GR"]}}, {"stats": {"curves": ["GR"]}}], "done": False}
    last = {"edits": [], "next": [], "done": True}
    trace = {}
    investigate(Script([first, last, last]), s, Usage(), 4000, trace, max_steps=2)
    rec = trace["steps"][0]
    assert ("unread" in rec) == flex and rec["actions"], rec
    if flex:
        assert "no_such_tool" in rec["unread"][0]
