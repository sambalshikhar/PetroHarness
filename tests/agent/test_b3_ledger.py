"""Ledger tests, offline part (L1-L8), on every formation of the configured dataset.

    .venv/bin/python -m pytest tests/agent/test_b3_ledger.py -q   (PETROHARNESS_DATA selects the dataset)

Sessions: per formation, calls drawn from the dense tests' generator (test_b2_dense.queries) plus every section and step, opened in
one ledger. Expected selections are computed here with plain token regexes, not with the ledger's helpers.
"""
import json
import random
import re
import sys
from functools import lru_cache
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from test_b2_dense import queries  # noqa: E402
from test_b2_tools import F  # noqa: E402
from petroharness.agent.engine import ToolError  # noqa: E402
from petroharness.agent.ledger import DIGEST_CHARS, SECTION_DIGEST_CHARS, VIEW_CHARS, Ledger, shown_values  # noqa: E402
from petroharness.agent.map import num  # noqa: E402
from petroharness.agent.toolset import TOOLS  # noqa: E402
from petroharness.agent.engine import CUT_GET  # noqa: E402

PER_FORMATION = 25


def calls(t, f, n=PER_FORMATION) -> list:
    rng = random.Random(f"{t.well}|{t.formation}|ledger")
    out = [(tool, kw) for tool, kw in queries(f, rng, n)]
    out += [("section", {"key": s.key}) for s in f.inv.sections]
    out += [("step", {"name": m.step}) for m in f.inv.methods]
    return out


@lru_cache(maxsize=1)
def sessions() -> list:
    """(task, formation, ledger, [(tool, kwargs, item)]) per formation."""
    out = []
    for t, f in F():
        led, opened = Ledger(f), []
        for tool, kw in calls(t, f):
            try:
                item, new = led.open(tool, kw)
            except ToolError:
                continue
            if new:
                opened.append((tool, kw, item))
        out.append((t, f, led, opened))
    return out


def token(z: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(z)}(?![A-Za-z0-9_])", text) is not None


# --- L1 store -------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_l1_items_are_the_tools_results():
    bad = []
    for t, f, led, opened in sessions():
        for k, (tool, kw, item) in enumerate(opened):
            r = TOOLS[tool](f, **kw)
            text = r.text.replace(CUT_GET, f"get {item.id} with find")          # a cut text's get names the item
            if item.text != text or [float(x) for x in item.numbers] != [float(x) for x in r.numbers]:
                bad.append((t.well, item.id, tool))
        ids = [e.id for e in led.items]
        if ids != [f"E{i + 1}" for i in range(len(ids))]:
            bad.append((t.well, "ids", ids[:5]))
    assert not bad, bad[:10]


def variants(tool, kw, rng) -> list:
    """The same call written differently: key order, case, spacing, defaults written out."""
    out = [dict(reversed(list(kw.items())))]
    v = {}
    for k, x in kw.items():
        if k in ("curves", "zones") and isinstance(x, list):
            v[k] = [f" {str(s).lower()} " for s in x]
        elif k in ("condition", "where") and isinstance(x, str):
            v[k] = re.sub(r"\s*(<=|>=|==|!=|<|>)\s*", r"\1", x)
        elif k in ("a", "b", "curve"):
            v[k] = str(x).lower()
        else:
            v[k] = x
    out.append(v)
    if tool == "runs" and "limit" not in kw:
        out.append(dict(kw, limit=20))
    if tool in ("stats", "compare", "profile") and "zones" not in kw:
        out.append(dict(kw, zones=None))
    out.append(json.dumps(kw))
    return out


@pytest.mark.data
def test_l1_a_repeated_call_returns_the_item_it_opened():
    bad = []
    for t, f, led, opened in sessions():
        rng = random.Random(t.well)
        n = len(led.items)
        for tool, kw, item in opened[:12]:
            for v in variants(tool, kw, rng):
                again, new = led.open(tool, v)
                if new or again is not item:
                    bad.append((t.well, tool, kw, v, again.id, item.id))
        if len(led.items) != n:
            bad.append((t.well, "items grew", n, len(led.items)))
    assert not bad, bad[:10]


@pytest.mark.data
def test_l1_a_rejected_call_is_an_error_not_an_item():
    t, f = F()[0]
    led = Ledger(f)
    for tool, raw in [("stats", {"curves": ["NOSUCH"]}), ("runs", {"condition": "SW <"}), ("nosuch", {}),
                      ("compare", '{"a": "PHIE"}'), ("stats", "{not json")]:
        with pytest.raises(ToolError):
            led.open(tool, raw)
    assert not led.items and len(led.errors) == 5


# --- L2 digest ------------------------------------------------------------------------------------------------------

SUMMARY = ("  whole interval", "  zones pooled:", "  these zones pooled:", "  all zones:", "  zones asked:",
           "  shallowest top", "  highest zone by", "  classes (")


@pytest.mark.data
def test_l2_digests():
    bad = []
    for t, f, led, opened in sessions():
        for tool, kw, item in opened:
            d = led.digest(item)
            full = f"[{item.id}] {item.text}"
            section = item.tool == "section"              # a section keeps its classes
            if len(d) > (SECTION_DIGEST_CHARS if section else DIGEST_CHARS) and d != full:
                bad.append((t.well, item.id, "size", len(d)))
            if len(d) > len(full):
                bad.append((t.well, item.id, "larger than the item"))
            if d == full:
                continue
            lines = item.lines
            for ln in d.split("\n")[1:-1]:
                if ln not in lines and not (ln.endswith(" ...") and any(x.startswith(ln[:-4]) for x in lines)):
                    bad.append((t.well, item.id, "not verbatim", ln[:80]))
            if "get " + item.id not in d.split("\n")[-1]:
                bad.append((t.well, item.id, "no fetch hint"))
            if section:                                     # the classes over the zones (both views) come first when they fit
                zl = next((ln for ln in item.lines if ln.startswith("    zones pooled: ") and len(ln) <= 200), None)
                if zl and len(item.lines[0][:200]) + len(zl) < SECTION_DIGEST_CHARS - 200 and zl not in d:
                    bad.append((t.well, item.id, "zone classes dropped", zl[:60]))
                continue
            # the first curve keeps its label and pooled line; an item without curve labels keeps its first summary line
            labels = [i for i, ln in enumerate(lines) if re.match(r"^[A-Z][A-Z0-9_]* (\[|=)", ln)]
            if labels:
                i = labels[0]
                pooled = next((ln for ln in lines[i + 1:] if ln.startswith(("  zones pooled:", "  these zones pooled:"))), None)
                for ln in [lines[i]] + ([pooled] if pooled else []):
                    if len(ln) <= 200 and len(lines[0]) + len(lines[i]) + len(pooled or "") < DIGEST_CHARS - 200 and ln not in d:
                        bad.append((t.well, item.id, "first curve's summary dropped", ln[:60]))
            else:
                summ = [ln for ln in lines if ln.startswith(SUMMARY) and len(ln) <= 200]
                if summ and len(lines[0][:200]) + len(summ[0]) + 1 < DIGEST_CHARS - 200 and summ[0] not in d:
                    bad.append((t.well, item.id, "summary dropped", summ[0][:60]))
    assert not bad, (len(bad), bad[:10])


# --- L3 get, L4 find ------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_l3_get_by_zone_is_exact_and_complete():
    from petroharness.agent.ledger import zones_in
    bad = []
    for t, f, led, opened in sessions():
        ids = [z.zone_id for z in f.view.zones]
        for tool, kw, item in opened:
            for z in ids[:3] + ids[-2:]:
                got = led.get(item.id, z)
                want = [ln for ln in item.lines if token(z, ln) and not ln.startswith(("  classes (", "  ("))
                        and not re.match(r"^  [A-Z][A-Z0-9_]*(?: \([^)]*\))?: .*; runs: ", ln)
                        and not re.match(r"^  .*other runs in Z\d+: ", ln)]   # the other runs of a cut list
                #   of runs or overlap, fetched by the get its shown line names (test_tool_lines.py), not by a zone alone
                for ln in want:
                    if ln not in got:
                        bad.append((t.well, item.id, z, "missing", ln[:70]))
                body = got.split("\n")[1:]
                for ln in body:
                    if ln.startswith("    ") or re.match(r"^  Z\d+ ", ln):
                        if not token(z, ln) and z not in zones_in(ln):          # a range (Z1-Z4) names it too
                            bad.append((t.well, item.id, z, "other zone", ln[:70]))
    assert not bad, (len(bad), bad[:10])


@pytest.mark.data
def test_l3_zone_2_is_not_zone_26():
    for t, f, led, opened in sessions():
        if len(f.view.zones) >= 26:
            for tool, kw, item in opened:
                if token("Z26", item.text):
                    got = led.get(item.id, "Z2")
                    assert not any(token("Z26", ln) and not token("Z2", ln) for ln in got.split("\n")[1:]), (t.well, item.id)
                    return
    pytest.skip("no formation with 26 zones")


@pytest.mark.data
def test_l3_words_are_token_bounded():
    bad = []
    for t, f, led, opened in sessions():
        for tool, kw, item in opened:
            if tool != "section":
                continue
            names = [ln.split()[0] for ln in item.lines if re.match(r"^  [A-Z][A-Z0-9_]+[ :(]", ln)]
            for a in names:
                for b in names:
                    if a != b and a in b:                                   # LOW_SW inside VERY_LOW_SW
                        got = led.get(item.id, a).split("\n")[1:]
                        if any(ln.strip().startswith(b) and not token(a, ln.replace(b, "")) for ln in got):
                            bad.append((t.well, item.id, a, b))
    assert not bad, bad[:10]


@pytest.mark.data
def test_l3_zone_and_word_together():
    """A class asked by name and zone gives its runs listed there; never "none" where the class has a run in the zone
    (its every run, from the analyzer store); "none" only where it has none and the list is whole. (A cut list of the
    thickest runs, a list of runs over several zones and the runs of one zone written without its id are each read as
    runs, never as none.)"""
    bad, cut = [], 0
    for t, f, led, opened in sessions():
        zs = [z.zone_id for z in f.view.zones]
        for tool, kw, item in opened:
            if tool != "section" or f.store is None:
                continue
            sec = f.store.sections.get(item.lines[0].split(":", 1)[0])
            for ln in item.lines:
                m = re.match(r"^  ([A-Z][A-Z0-9_]*)(?: \([^)]*\))?: .*; runs: (.*)$", ln)
                if not m or sec is None or m.group(1) not in sec.classes:
                    continue
                label = m.group(1)
                whole = "every run" not in ln and not m.group(2).startswith("thickest")
                cut += not whole
                for z in zs[:3]:
                    got = led.get(item.id, f"{label}, {z}")
                    own = next((g for g in got.split("\n") if g.startswith(f"  {label} (") or g.startswith(f"  {label}:")), "")
                    has = any(r.zone == z for r in sec.classes[label])
                    if has and (f"none in {z}" in own or not own):
                        bad.append((t.well, item.id, label, z, "said none"))
                    if not has and whole and f"none in {z}" not in own:
                        bad.append((t.well, item.id, label, z, "did not say none"))
                    if not whole and "none in" in own:
                        bad.append((t.well, item.id, label, z, "none from a cut list"))
    assert not bad, bad[:10]
    assert cut


@pytest.mark.data
def test_l3_no_match_says_so_and_long_output_is_cut():
    t, f, led, opened = sessions()[0]
    item = opened[0][2]
    assert "nothing in" in led.get(item.id, "NOSUCHWORD")
    assert led.get(item.id, "").endswith(item.text)                    # get alone: the whole result
    assert "no such item" in led.get("E999", "Z1")
    for t, f, led, opened in sessions():
        for tool, kw, item in opened:
            assert len(led.get(item.id, "Z1, n")) <= 3000 + 120


@pytest.mark.data
def test_l4_find_is_get_over_every_item():
    bad = []
    for t, f, led, opened in sessions():
        for z in [z.zone_id for z in f.view.zones][:2]:
            text = led.find(z)
            want = [e.id for e in led.items if "nothing in" not in led.get(e.id, z)]
            named = re.match(rf"^{z} is in (.*)$", text.split("\n", 1)[0])
            listed = named.group(1).split(", ") if named else []
            shown = re.findall(r"^\[(E\d+)\]", text, re.M)
            left = re.findall(r"E\d+", (re.search(r"\(not shown here: ([^;]*);", text) or re.match("", "")).group(0) or "")
            if listed != want or sorted(shown + left, key=lambda x: int(x[1:])) != want or len(text) > 6000:
                bad.append((t.well, z, listed[:5], want[:5], len(text)))
    assert not bad, bad[:10]


# --- L5 reachable ---------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_l5_every_line_is_reachable():
    bad = []
    for t, f, led, opened in sessions():
        for tool, kw, item in opened:
            d = led.digest(item)
            for ln, nums in item.rows:
                if not nums or ln in d:
                    continue
                finds = sorted({m for m in re.findall(r"(?<![A-Za-z0-9_])Z\d+(?![A-Za-z0-9_])", ln)})
                first = re.match(r"^\s*([A-Za-z][A-Za-z0-9_.]*)", ln)
                if first:
                    finds.append(first.group(1))
                finds += [c for c in re.findall(r"[A-Z][A-Z0-9_]+", ln) if c in f.inv.curves]   # its curve
                if not any(ln in led.get(item.id, q) for q in finds):
                    bad.append((t.well, item.id, ln[:70]))
    assert not bad, (len(bad), bad[:10])


# --- L6 verify, locate ----------------------------------------------------------------------------------------------

def decimals(v: float) -> int:
    """The decimals a number is shown with (petroharness.agent.map.num)."""
    s = num(float(v))
    return len(s.split(".", 1)[1]) if "." in s else 0


@pytest.mark.data
def test_l6_shown_numbers_verify_and_others_do_not():
    bad, n = [], 0
    for t, f, led, opened in sessions():
        rng = random.Random(t.well)
        for tool, kw, item in opened[:15]:
            vals = shown_values(item)
            for v in rng.sample(vals, min(8, len(vals))):
                n += 1
                for k in range(decimals(v), -1, -1):                          # its precision, then coarser
                    c = round(v, k)
                    if not led.verify(f"{c:.{k}f}", [item.id]):
                        bad.append((t.well, item.id, v, k, "should verify"))
                        break
                k = decimals(v) or 1
                written = f"{v + 0.6 * 10 ** (-k):.{k}f}"                   # past half a unit of the last digit
                want = any(abs(float(written) - w) <= 0.5 * 10 ** (-k) * (1 + 1e-9) + 1e-12 * max(1.0, abs(w)) for w in vals)
                if led.verify(written, [item.id]) != want:
                    bad.append((t.well, item.id, v, written, "off", want))
    assert n > 1000 and not bad, (n, bad[:10])


@pytest.mark.data
def test_l6_locate_finds_exactly_the_items_that_show_a_number():
    bad = []
    for t, f, led, opened in sessions()[:20]:
        for tool, kw, item in opened[:5]:
            for ln, nums in item.rows[:4]:
                for v in nums[:2]:
                    k = decimals(float(v))
                    claim = f"{float(v):.{k}f}"
                    hits = {i for i, _ in led.locate(claim)}
                    if item.id not in hits:
                        bad.append((t.well, item.id, claim))
                    for e in led.items:
                        if (e.id in hits) != led.verify(claim, [e.id]):
                            bad.append((t.well, e.id, claim, "locate and verify disagree"))
    assert not bad, bad[:10]


# --- L7 budget ------------------------------------------------------------------------------------------------------

@pytest.mark.data
@pytest.mark.parametrize("n", [10, 30, 60])
def test_l7_the_view_stays_within_budget(n):
    big = sorted(F(), key=lambda tf: -(tf[1].inv.samples * max(len(tf[1].view.zones), 1)))[:3]
    bad = []
    for t, f in big:
        led = Ledger(f)
        for tool, kw in calls(t, f, n * 2):
            try:
                led.open(tool, kw)
            except ToolError:
                pass
            if len(led.items) >= n:
                break
        v = led.view()
        if len(v) > VIEW_CHARS:
            bad.append((t.well, n, len(v)))
        if f"[{led.items[-1].id}] {led.items[-1].text}" not in v:
            bad.append((t.well, n, "newest not in full"))
        for e in led.items:
            if f"  {e.id} " not in v:
                bad.append((t.well, n, e.id, "not listed"))
    assert not bad, bad[:10]


# --- L8 adversarial -------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_l8_ids_in_any_form():
    t, f, led, opened = sessions()[0]
    item = opened[2][2]
    want = led.get(item.id, "Z1")
    for form in (item.id.lower(), f"[{item.id}]", f" {item.id} ", f"[{item.id.lower()}] "):
        assert led.get(form, "Z1") == want


@pytest.mark.data
def test_l8_zone_ranges():
    for t, f, led, opened in sessions():
        if len(f.view.zones) >= 5:
            item = next((it for _, _, it in opened if it.tool in ("stats", "profile") and token("Z5", it.text)), None)
            if item is None:
                continue
            got = led.get(item.id, "Z3-Z5")
            for z in ("Z3", "Z4", "Z5"):
                assert any(token(z, ln) for ln in got.split("\n")[1:]), (t.well, z, got[:300])
            assert not any(token("Z6", ln) and not token("Z5", ln) for ln in got.split("\n")[1:]
                           if not ln.strip().startswith(("zones pooled", "whole interval", "highest zone by",
                                                         "lowest zone by")))   # extremes and rankings name other zones
            return
    pytest.skip("no formation with five zones and a matching item")


@pytest.mark.data
def test_l8_a_depth_finds_its_lines_but_not_a_longer_number():
    for t, f, led, opened in sessions():
        for tool, kw, item in opened:
            if tool != "runs":
                continue
            m = re.search(r"^    (\d+)(?:\.\d+)?-", item.text, re.M)
            if not m:
                continue
            d = m.group(1)
            got = [ln for ln in led.get(item.id, d).split("\n")[1:] if ln.startswith(" ")]     # the block head is context
            assert got and all(token(d, ln) or re.search(rf"(?<![\d.]){d}(?![\d])", ln) for ln in got), (t.well, d, got[:3])
            assert not any(re.search(rf"\d{d}|{d}\d", ln) and not re.search(rf"(?<![\d.]){d}(?![\d])", ln) for ln in got)
            return
    pytest.skip("no runs item with a listed run")
