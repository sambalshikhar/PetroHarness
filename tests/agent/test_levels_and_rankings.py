"""Levels and rankings: the workflow's flow roles pass through as the workflow's, and the zone table adds a curve's
geometric mean by the shape of its values.

    .venv/bin/python -m pytest tests/agent/test_levels_and_rankings.py -q        (PETROHARNESS_DATA selects the dataset)
"""
import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
import b2_reference as R  # noqa: E402
from test_b2_tools import F  # noqa: E402
from petroharness.well.view import fmt, sig  # noqa: E402

ON = {}             # no switches: the tests' 'with options.use(**ON)' blocks run the defaults


def _perm(f):
    return "PERM_CC" if "PERM_CC" in f.inv.curves and np.isfinite(np.asarray(f.view.values("PERM_CC"), float)).any() \
        else "PERM"


def _table(text):
    """unit_roles' rows -> {zone: (thickness, mean, k*h, role)} and its fact lines."""
    rows, facts = {}, [ln[2:] for ln in text.splitlines() if ln.startswith("- ")]
    for ln in text.splitlines():
        c = [x.strip() for x in ln.split(" | ")]
        c = c[:1] + [x.split(": ", 1)[-1] for x in c[1:]]               # each cell named by its column
        if len(c) == 5 and re.fullmatch(r"Z\d+", c[0]):
            num = lambda v: float("nan") if v == "n/a" else float(v)
            rows[c[0]] = (num(c[1]), num(c[2]), num(c[3]), c[4])
    return rows, facts


# --- unit_roles: the workflow's roles, passed through ----------------------------------------------------------------

@pytest.mark.data
def test_unit_roles_are_the_workflow_s_roles_not_reranked_or_added_to():
    from petroharness.agent.compute import unit_roles
    from petroharness.agent.engine import ToolError
    n = 0
    for t, f in F():
        if not any(c in f.inv.curves for c in ("PERM", "PERM_CC")):
            continue
        try:
            text = unit_roles(f).text
        except ToolError:
            continue
        kc = re.search(r"\((PERM\w*)\)", text).group(1)
        rows, facts = _table(text)
        assert rows and text.splitlines()[0].startswith("The workflow's flow roles"), (t.well, text[:300])
        assert "median" not in text and "highest mean" not in text and "strongest flow interval" not in text
        zones = {z.zone_id: z for z in f.view.zones}
        for zid, (thick, mean, kh, role) in rows.items():
            x = np.asarray(f.view.zone_values(zones[zid], kc), float)
            x = x[np.isfinite(x)]
            if x.size:
                assert mean == float(fmt(sig(float(np.mean(x))))), (t.well, zid, mean)      # the zone mean, as shown
        strongest = [z for z, r in rows.items() if r[3].startswith("strongest")]
        if strongest:
            assert any(x.startswith(f"the workflow's 'strongest' role: {strongest[0]} ") for x in facts)
        assert any(x.startswith("roles as the workflow assigns them (Petrophys flow_roles") for x in facts)
        n += 1
    assert n


# --- the zone table: a log-shaped curve's geometric mean beside its mean --------------------------------------------

@pytest.mark.data
def test_zone_table_adds_the_geometric_mean_by_the_shape_of_the_values_only():
    from types import SimpleNamespace as NS

    from petroharness.agent.claims import Claims
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.writer import zone_table
    from petroharness.well.summary import log_shaped
    n = 0
    for t, f in F()[:20]:
        kc = _perm(f)
        if kc not in f.inv.curves or "PHIE" not in f.inv.curves or len(f.view.zones) < 2:
            continue
        q = f"How does {kc} vary with PHIE between the zones?"
        s = NS(f=f, task=NS(question=q, well=t.well), topics=["permeability_rock_quality"])
        claims = Claims(["p"], Ledger(f), "", q, f.view, (t.well,))
        on = zone_table(s, claims, style="by_interval")
        cols = [c.strip() for c in on.splitlines()[0].strip("|").split("|")]
        named = [re.match(r"^Mean ([A-Z][A-Z0-9_]*)", c).group(1) for c in cols if re.match(r"^Mean [A-Z]", c)]
        for curve in named:
            geo = [i for i, c in enumerate(cols) if re.match(rf"^Geometric mean {curve}(?![A-Z0-9_])", c)]
            assert bool(geo) is log_shaped(f.view.values(curve)), (t.well, curve, cols)
            for i in geo:
                assert re.match(rf"^Mean {curve}(?![A-Z0-9_])", cols[i - 1])
                for ln, z in zip(on.splitlines()[2:], f.view.zones):
                    cell = [x.strip() for x in ln.strip("|").split("|")][i]
                    x = np.asarray(f.view.zone_values(z, curve), float)
                    x = x[np.isfinite(x)]
                    if x.size and (x > 0).all():
                        assert R.agrees(float(cell), float(np.exp(np.log(x).mean()))), (t.well, z.zone_id, cell)
        assert not any(c.startswith("Median ") for c in cols)
        n += 1
    assert n


# --- guides, writer rules, brief -------------------------------------------------------------------------------------


@pytest.mark.data
def test_the_brief_carries_the_level_and_ranking_lines(real):
    from petroharness.agent.loop import BRIEF_LEVELS, brief
    from petroharness.agent.writer import prompt
    system, _, _, _ = prompt(real, "default")
    assert "zone-mean permeability" not in system
    assert BRIEF_LEVELS in brief() and "log-normal" not in BRIEF_LEVELS


@pytest.fixture(scope="module")
def real():
    from test_b7_writer import _real_claims, _session
    s = _session(["Where is net pay?", "How thick is it?"], [])
    for c in _real_claims(s):
        s.claims.claims[c.id] = c
    s.claims._n = 4
    return s


# --- every guide is in the index, whatever the topics (the question's words select none) ----------------------------

@pytest.mark.parametrize("topics", [["permeability_rock_quality"], ["lithology_mineralogy"], []])
def test_the_index_lists_every_guide_whatever_the_topics(topics):
    from petroharness.agent.direction import plugged
    lib = plugged()                                                 # the plugged library (researched)
    text = lib.index(topics)
    for name, f in lib.facets.items():                              # one line per guide, under its area
        assert f"  {name}: {f['when']}" in text or f"    {name}: {f['when']}" in text


def test_no_guide_carries_question_words():
    """No guide carries 'names' (words in a question that would name a guide): the READ call routes by the model's
    topics."""
    from petroharness.agent.direction import plugged
    assert not [name for name, f in plugged().facets.items() if "names" in f]
