"""Guide recipes. Each test or comparison an area guide's Consider or Decide lines describe
has a Compare line with the harness call that runs it; the reviewed pairs are tests/agent/fixtures/guide_recipes.yaml.
A line that names a test no tool can run on the record says which tool comes closest (a guide names only methods the
harness can run), and its provenance row records the edit.

    PYTHONPATH=src python -m pytest tests/agent/test_recipes.py -q
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src")]
from petroharness.agent import direction  # noqa: E402
from petroharness.config import DEFAULT_SKILLS, RESOURCES  # noqa: E402

LIB = direction.load((RESOURCES / DEFAULT_SKILLS).resolve())          # the packaged researched library
REVIEW = yaml.safe_load((ROOT / "tests" / "agent" / "fixtures" / "guide_recipes.yaml").read_text())
AREA_GUIDES = [g for g in LIB.facets if g not in LIB.common]
PARTS = ("consider", "decide")
CLOSEST = re.compile(r" Closest here: [^.]+(?:\.[^ .][^.]*)*\.$")
# words that name a test or a comparison in a Consider or Decide line: every such line has a review entry, and the
# review pairs it with a Compare call or says why it has none
TEST_WORDS = re.compile(r"\b(crossplot|plot|compare|check|test|fit|screen|rank|correlat\w*|regress\w*|histogram|trend|"
                        r"cluster\w*|depth-match|recompute|separat\w*)\b", re.I)


def call(entry: str) -> str:
    """A Compare line's call: the text before its note."""
    return re.sub(r"\s{3}\([^()]*\)\s*$", "", entry).strip()


def test_every_consider_and_decide_line_has_its_review():
    """The review covers every Consider and Decide line of every area guide, in order (its first words), and nothing
    else; every line that names a test is in it."""
    assert sorted(REVIEW) == sorted(AREA_GUIDES)
    for g in AREA_GUIDES:
        for part in PARTS:
            lines, got = LIB.facets[g][part], REVIEW[g].get(part) or {}
            assert sorted(got) == list(range(1, len(lines) + 1)), (g, part, sorted(got), len(lines))
            for n, line in enumerate(lines, 1):
                assert line.startswith(got[n]["starts"]), (g, part, n, got[n]["starts"], line[:60])
                assert got[n].get("calls") or got[n].get("none"), (g, part, n)
    named = [(g, p, n) for g in AREA_GUIDES for p in PARTS for n, ln in enumerate(LIB.facets[g][p], 1) if TEST_WORDS.search(ln)]
    assert len(named) >= 60                                               # the review is about these lines, at least


def test_each_paired_call_is_a_compare_line_of_its_guide():
    """A pair names a call the guide (or the guide the line points to: 'see X') lists in its Compare section."""
    bad = []
    for g in AREA_GUIDES:
        for part in PARTS:
            for n, e in (REVIEW[g].get(part) or {}).items():
                where = e.get("see", g)
                if where != g:
                    assert f"(see {where})" in LIB.facets[g][part][n - 1], (g, part, n, where)
                have = {call(x) for x in LIB.facets[where]["compare"]}
                bad += [(g, part, n, c) for c in e.get("calls") or [] if c not in have]
    assert not bad, bad


def test_every_compare_line_of_an_area_guide_serves_a_reviewed_test():
    """No Compare line is listed for nothing: each is a call some review entry of its guide pairs, or a workflow
    section (the workflow's own reading of the guide's topic)."""
    for g in AREA_GUIDES:
        used = {c for part in PARTS for e in (REVIEW[g].get(part) or {}).values() for c in e.get("calls") or []}
        idle = [call(x) for x in LIB.facets[g]["compare"] if call(x) not in used and not call(x).startswith("section ")]
        assert not idle, (g, idle)


def test_the_closest_tool_edits():
    """Each line that names a test no tool can run on the record says which tool comes closest (one sentence at its
    end, 'Closest here: ...'), names a harness tool or the record's curve, and its provenance row records the edit."""
    tools = {"calc", "stats", "runs", "crossplot", "core_vs_log", "step", "profile"}
    edited = []
    for g in AREA_GUIDES:
        for part in PARTS:
            for n, line in enumerate(LIB.facets[g][part], 1):
                m = CLOSEST.search(line)
                if not m:
                    continue
                edited.append((g, part, n))
                assert any(t in m.group(0) for t in tools) or "ELECTROFACIES" in m.group(0), (g, part, n, m.group(0))
                if part in direction.ROWS:
                    row = LIB.sources["facets"][g][part][n - 1]
                    assert "The closest tool here is named" in str(row.get("note")), (g, part, n, row)
    assert len(edited) == 13, edited


@pytest.mark.parametrize("guide", AREA_GUIDES)
def test_each_area_guide_lists_its_key_recipes(guide):
    """Recipes an area's questions commonly need are Compare lines of the area's guide."""
    want = {"data_quality": ["adjacent_jumps CURVE threshold=VALUE", "spike_flags GR, RHOB, NPHI, DTC"],
            "porosity": ["stats CURVES where CONDITION"],
            "water_saturation": ["crossplot BVW PHIE"],
            "permeability_rock_quality": ["lithology_stats PERM, PHIE, FZI"],
            "fluid_contacts": ["runs CONDITION"],
            "log_facies_stratigraphy": ["crossplot GR DEPTH", "vertical_sequence"],
            "statistics_data_analysis": ["stats CURVES statistics NAMES where CONDITION"]}.get(guide, [])
    have = {call(x) for x in LIB.facets[guide]["compare"]}
    assert set(want) <= have, (guide, set(want) - have)
