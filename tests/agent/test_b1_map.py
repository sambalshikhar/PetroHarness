"""Map tests, offline part (M1-M4), on every formation of the configured dataset.

    PYTHONPATH=src:. .venv/bin/python -m pytest tests/agent/test_b1_map.py -q        (PETROHARNESS_DATA selects the dataset)
"""
import re
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from test_b0_inventory import formations  # noqa: E402
from petroharness.agent.map import num, primary_absent, render  # noqa: E402

ADVISORY = re.compile(r"not independent|by construction|caveat|unvalidated|not validated|should|note that|cannot be|"
                      r"limit(?:s|ed|ation)|uncertain|reliab|quicklook[^)\n;]*not|supplied in the LAS|not computed by", re.I)


def advisory(text: str) -> list:
    """Advisory phrases in prose; names (curves, classes, steps in capitals, e.g. a class LIMITED) are not prose."""
    return [h.group(0) for h in ADVISORY.finditer(re.sub(r"\b[A-Z][A-Z0-9_]{2,}\b", " ", text))]


def maps():
    return [(t, inv, render(inv)) for t, v, s, inv in formations()]


@pytest.mark.data
def test_m1_size():
    big = [(t.well, t.formation, len(m)) for t, inv, m in maps() if len(m) > 24500]     # the limit holds the route lines, the notes, a context profile's record in compartments and the curve catalog's lines (about 2,200-3,800)
    assert not big, big


@pytest.mark.data
def test_m2_essentials():
    for t, inv, m in maps():
        raw = m.split("Raw input")[1].split("After the workflow")[0]
        after = m.split("After the workflow")[1].split("Analyzer sections")[0]
        for z in inv.zones:
            assert f"  {z.id} " in m, (t.well, z.id)
        for c in inv.curves.values():
            here = raw if c.source == "input" else after
            assert re.search(rf"(?<![A-Z0-9_]){re.escape(c.name)}(?![A-Z0-9_])", here), (t.well, c.name, c.source)
        for meth in inv.methods:
            assert f"  step {meth.step}: method {meth.method}" in after, (t.well, meth.step)
        for c in primary_absent(inv):                                 # petrophys's list
            assert c in raw, (t.well, c)
        for s in inv.sections:
            assert s.key.split(".", 1)[1] in m, (t.well, s.key)
        for k in inv.header:
            assert re.search(rf"(?<![A-Z0-9_]){re.escape(k)} ", raw), (t.well, k)


@pytest.mark.data
def test_m3_plain():
    """Plain outside the notes (general advisories live in the map's Notes block only)."""
    hits = [(t.well, h) for t, inv, m in maps() for h in advisory(m.split("\nNotes on this interval")[0])]
    assert not hits, hits[:10]


def _inventory_numbers(inv) -> list:
    vals = []
    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            vals.append(float(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for s in re.findall(r"-?\d+(?:\.\d+)?", x):
                vals.append(float(s))
    walk(inv.to_dict())
    return vals


@pytest.mark.data
def test_m4_every_number_in_the_map_is_in_the_inventory():
    bad = []
    for t, inv, m in maps():
        known = _inventory_numbers(inv)
        well = r"[_/ -]".join(re.escape(p) for p in re.split(r"[_/ -]", inv.well))
        text = re.sub(well, " ", m).replace(inv.formation, " ")             # names (any separator spelling), not numbers
        text = re.sub(r"^(  [a-z_]+) \(\d+\):", r"\1:", text, flags=re.M)     # section counts: the map counts the list
        text = re.sub(r"\b[A-Z][A-Z0-9_]*\d[A-Z0-9_]*\b|Z\d+", " ", text)   # curve/zone names with digits are names
        for s in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text):
            x = float(s)
            if x in (0.0, 1.0, 100.0):
                continue
            if not any(abs(x - k) <= max(1e-9, 5e-4 * abs(k)) for k in known):
                if not re.search(rf"{re.escape(s)}%", m):                     # the zone-cover share is computed here
                    bad.append((t.well, s))
    assert not bad, bad[:15]


@pytest.mark.parametrize("x, want", [(14150.0, "14150"), (8234.5, "8234.5"), (7912.0, "7912"), (1.7304, "1.7304"),
                                     (0.021769802835, "0.02177"), (240.4506908, "240.4507"), (0.2, "0.2"), (3, "3"),
                                     (0.00012346, "0.0001235"), (-0.02, "-0.02"), (float("nan"), "n/a")])
def test_numbers_keep_their_precision_without_exponents(x, want):
    assert num(x) == want and "e" not in num(x)
