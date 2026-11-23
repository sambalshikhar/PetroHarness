"""A section lookup ends with its classes both ways (the summary layer's class views): each zone's class from
its mean and the share of its samples in each class other than the background (from the store's runs), then the zones
pooled and the whole interval.
    .venv/bin/python -m pytest tests/agent/test_section_zones.py -q"""
import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from _support.formations import F  # noqa: E402
from petroharness.agent.tools import section  # noqa: E402


def expected(f, key):
    """{zone: {class: share %}} from the store's runs, counted here: a zone sample is in a class when a run of that
    class in that zone covers its depth."""
    d = f.depth
    out = {}
    sec = f.store.sections[key]
    bg = {c.name.upper() for s in f.inv.sections if s.key == key for c in s.classes if c.background}
    for z in f.view.zones:
        idx = np.asarray(z.indices)
        shares = {}
        for lab, rs in sec.classes.items():
            if str(lab).upper() in bg:
                continue
            hit = np.zeros(idx.size, dtype=bool)
            for r in rs:
                if r.zone == z.zone_id:
                    hit |= (d[idx] >= r.top - 1e-6) & (d[idx] <= r.base + 1e-6)
            if hit.any():
                shares[str(lab).upper()] = 100 * hit.mean()
        out[z.zone_id] = shares
    return out


def parsed(text):
    block = text.split("  class views (", 1)[1]
    out = {}
    for ln in block.splitlines()[1:]:
        m = re.match(r"^    (Z\d+) .*?: (?:by its mean \S+; )?samples (.*)$", ln)
        if not m:
            continue
        out[m.group(1)] = {} if m.group(2).startswith("none (") else \
            {k: float(v) for k, v in re.findall(r"([A-Z0-9_]+) ([\d.]+)%", m.group(2))}
    return out


@pytest.mark.data
def test_zone_shares_match_the_store_runs():
    bad, done = [], 0
    for t, f in F()[:25]:
        for s in [s for s in f.inv.sections if any(not c.background for c in s.classes)][:4]:
            on = section(f, s.key).text
            if "  class views (" not in on:
                bad.append((t.well, s.key, "no class views"))
                continue
            got, want = parsed(on), expected(f, s.key)
            for zid, shares in got.items():
                w = {k: round(v, 1) for k, v in want[zid].items()}
                if {k: round(v, 1) for k, v in shares.items()} != w:
                    bad.append((t.well, s.key, zid, shares, w))
            if not re.search(r"left out to keep this short|more lines left out|not shown in this view", on) and set(got) != set(want):
                bad.append((t.well, s.key, "zones missing", set(want) - set(got)))
            done += 1
    assert done and not bad, bad[:6]


@pytest.mark.data
def test_a_zone_without_any_class_says_so_with_the_background():
    for t, f in F():
        for s in f.inv.sections:
            bg = [c.name for c in s.classes if c.background]
            if not bg or not any(not c.background for c in s.classes):
                continue
            text = section(f, s.key).text
            lines = [ln for ln in text.split("  class views (", 1)[-1].splitlines() if ln.startswith("    Z")]
            empty = [ln for ln in lines if "samples none (" in ln]
            if empty:
                assert all(f"none ({', '.join(bg)} only)" in ln for ln in empty)
                return
    pytest.skip("no zone without a class in this dataset's sections")


@pytest.mark.data
def test_a_section_without_named_classes_gets_no_block():
    for t, f in F():
        for s in f.inv.sections:
            if not s.classes or all(c.background for c in s.classes):
                assert "  class views (" not in section(f, s.key).text
                return
    pytest.skip("every section has a named class here")
