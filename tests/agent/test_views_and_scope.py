"""What the tools and the writer show zone by zone, and what the model's topics scope: minus signs, thresholds in their
recorded form, routes, signed compares, the spike screen, zone selectors, class views, the writer's table and rules,
the guides and plain argument spellings. Real-input tests run over every formation of the dataset (PETROHARNESS_DATA
selects it); values are checked against numpy computed here from the view's arrays; adversarial cases are failures
seen in traced runs.
    .venv/bin/python -m pytest tests/agent/test_views_and_scope.py -q
"""
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.agent.checks import ascii_minus, number_provenance  # noqa: E402
from test_b2_tools import F  # noqa: E402
from test_b7_writer import real  # noqa: E402,F401  (the writer's session with claims)
from petroharness.agent import options, routes  # noqa: E402
from petroharness.agent.engine import Formation, ToolError, zone_at  # noqa: E402
from petroharness.agent import engine as E  # noqa: E402
from petroharness.agent.inventory import _banded, from_view  # noqa: E402

LOGNORMAL = ("RDEP", "RMED", "RSHA", "RXO", "PERM")


@lru_cache(maxsize=1)
def FI() -> list:
    """Every formation with its inventory built from its view (thresholds kept, routes in the step record)."""
    return [(t, Formation(from_view(f.view, f.store), f.view, f.store)) for t, f in F()]


# --- the minus sign (unconditional) ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,card,bad", [
    ("difference mean −0.419 and minimum −15.8146", "difference -0.419; minimum -15.8146", []),
    ("difference mean -0.419", "difference -0.419", []),                       # the ASCII minus too
    ("difference mean −0.42", "difference -0.419", []),                   # its own precision
    ("difference mean 0.419", "difference -0.419", ["0.419"]),                 # the sign still matters
    ("difference mean −0.5", "difference -0.419", ["-0.5"]),             # a wrong value is still caught
    ("porosity 0.20−0.40", "bands 0.20 and 0.40", []),                   # a range is no negative number
    ("RHOB －0.05 g/cc", "DRHO -0.05", []),                               # the full-width minus too
])
def test_minus_signs_are_read_as_minus(text, card, bad):
    assert number_provenance(text, card, [])[0] == bad
    assert ascii_minus("a − b") == "a - b" and ascii_minus(None) == ""


# --- thresholds in their recorded form ----------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,classes,want", [
    ("EXCELLENT < 0.20; GOOD 0.20-0.40; FAIR 0.40-0.60; WATER_BEARING >= 0.60.",
     ["EXCELLENT_HC_SATURATION", "GOOD_HC_SATURATION", "FAIR_HC_SATURATION", "WATER_BEARING"],
     {"EXCELLENT_HC_SATURATION": "EXCELLENT < 0.20", "GOOD_HC_SATURATION": "GOOD 0.20-0.40",
      "FAIR_HC_SATURATION": "FAIR 0.40-0.60", "WATER_BEARING": ">= 0.60"}),
    ("MEGA_PORES >=5; MACRO_PORES >=2 to <5; MESO_PORES >=0.5 to <2; MICRO_PORES <0.5.",
     ["MEGA_PORES", "MACRO_PORES", "MESO_PORES"], {"MEGA_PORES": ">=5", "MACRO_PORES": ">=2 to <5", "MESO_PORES": ">=0.5 to <2"}),
    ("SECONDARY > 0.05; PRIMARY between -0.05 and 0.05; MATRIX_EFFECT < -0.05.",
     ["MATRIX_EFFECT", "PRIMARY_POROSITY", "SECONDARY_POROSITY"],
     {"SECONDARY_POROSITY": "SECONDARY > 0.05", "PRIMARY_POROSITY": "PRIMARY between -0.05 and 0.05", "MATRIX_EFFECT": "< -0.05"}),
    ("MHI bands: HIGH_MOVEABLE_HC <0.5, MODERATE 0.5-0.7, LOW 0.7-0.9, MINIMAL >=0.9. Fallback invasion bands: conductive <0.7.",
     ["HIGH_MOVEABLE_HC", "MODERATE_MOVEABLE_HC", "MINIMAL_MOVEABLE_HC"],
     {"HIGH_MOVEABLE_HC": "<0.5", "MODERATE_MOVEABLE_HC": "MODERATE 0.5-0.7", "MINIMAL_MOVEABLE_HC": "MINIMAL >=0.9"}),
    # a rule in words is part of a longer rule: left to the recorded line, never a partial definition
    ("Quality base: FAIR when selected porosity >0.05, GOOD when >0.10, EXCELLENT when >0.15. When selected permeability "
     "is available, GOOD also requires >1 mD.", ["EXCELLENT_SANDSTONE_RESERVOIR", "GOOD_SANDSTONE_RESERVOIR"], {}),
    ("EXCELLENT_RESERVOIR, VERY_GOOD_RESERVOIR, GOOD_RESERVOIR, otherwise TIGHT_FORMATION.", ["GOOD_RESERVOIR"], {}),
    ("EXTREME when >= 2 z-scores exceed 3.0; SIGNIFICANT when >= 1 exceeds 3.0.", ["EXTREME_DEVIATION_ZONE"], {}),
    ("POOR_LOG_QUALITY if BAD_HOLE > 0.5 or |DRHO| > 0.1.", ["POOR_LOG_QUALITY", "GOOD_LOG_QUALITY"],
     {"POOR_LOG_QUALITY": "if BAD_HOLE > 0.5 or |DRHO| > 0.1"}),
    ("GOOD 0.1-0.2", ["GOOD_A", "GOOD_B"], {}),                                # a first word of two classes: ambiguous
])
def test_banded_thresholds(raw, classes, want):
    assert _banded(raw, classes) == want


@pytest.mark.data
def test_thresholds_kept_and_read():
    from petroharness.agent.tools import section
    kept = 0
    for t, fi in FI():
        for si in fi.inv.sections:
            kept += bool(si.thresholds)
        for si in fi.inv.sections[:6]:
            text = section(fi, si.key).text
            assert ("thresholds (as recorded)" in text) == bool(si.thresholds), (t.well, si.key)


# --- routes in this interval -------------------------------------------------------------------------------------------

def _pairs_numpy(view):
    ratio, deep = view.values("INVASION_RATIO"), view.values("RDEP")
    ok = np.isfinite(ratio)
    out, taken = {}, np.zeros(ratio.size, dtype=bool)
    for c in routes.SHALLOW:
        if not view.available(c):
            continue
        s = np.asarray(view.values(c), dtype=float)
        with np.errstate(invalid="ignore", divide="ignore"):
            fit = ok & ~taken & np.isclose(ratio, s / deep, rtol=1e-3, atol=1e-9) & (deep > 0)
        if fit.any():
            out[c] = int(fit.sum())
            taken |= fit
    return out, int(ok.sum())


@pytest.mark.data
def test_invasion_routes_match_numpy_and_reach_the_map():
    from petroharness.agent.map import render
    seen = 0
    for t, fi in FI():
        v = fi.view
        c = routes.invasion_counts(v)
        if not (v.available("INVASION_RATIO") and v.available("RDEP")) or c is None:
            assert c is None or c["n"] == 0
            continue
        seen += 1
        want, n = _pairs_numpy(v)
        assert c["n"] == n and sum(c.get(k, 0) for k in routes.SHALLOW) + c["other"] == n, (t.well, c)
        assert {k: c[k] for k in routes.SHALLOW if c.get(k)} == want, (t.well, c, want)
        mi = render(fi.inv)
        assert "in this interval INVASION_RATIO = " in mi, t.well
        inv_step = next(m for m in fi.inv.methods if m.step == "invasion")
        assert any(d.startswith("in this interval INVASION_RATIO") for d in inv_step.decisions_here)
        for m in fi.inv.methods:                             # a well-wide route line is labelled as such
            for d in m.decisions_here:
                if routes.WELL_WIDE.search(d) and not d.startswith("in this interval"):
                    assert d.startswith("well-wide record: "), (t.well, m.step, d)
    assert seen or pytest.skip("no INVASION_RATIO in this dataset")


@pytest.mark.data
def test_sxo_routes_add_up():
    for t, f in FI():
        s = routes.sxo_counts(f.view)
        if s is None:
            continue
        assert s["measured"] + s["quicklook"] + s["water"] == s["n"] > 0, (t.well, s)
        sxo, sw = (np.asarray(f.view.values(c), dtype=float) for c in ("SXO", "SW"))
        ok = np.isfinite(sxo) & np.isfinite(sw) & (sw >= 0)
        water = ok & (sw >= 0.999) & (sxo >= 0.999)
        quick = ok & ~water & (np.abs(sxo - np.clip(sw, 0, None) ** 0.2) < 1e-3)
        assert s["quicklook"] == int(quick.sum()) and s["water"] == int(water.sum()), t.well


@pytest.mark.data
def test_route_contradictions_flag_only_a_route_not_used_here():
    said = "INVASION_RATIO here is the RMED/RDEP fallback because RSHA was unavailable."
    negated = "INVASION_RATIO here is RSHA/RDEP, not the RMED/RDEP fallback."
    checked = 0
    for t, f in FI():
        c = routes.invasion_counts(f.view)
        if not c:
            continue
        fallback_unused = not c.get("RMED") and c["n"] - c["other"] > 0
        assert bool(routes.contradictions(said, f.view)) == fallback_unused, (t.well, c)
        assert routes.contradictions(negated, f.view) == []
        assert routes.contradictions("Porosity averages 0.21 in the sand.", f.view) == []
        checked += fallback_unused
    assert checked or pytest.skip("every interval here uses the fallback")


@pytest.mark.data
def test_a_route_not_used_here_is_flagged_by_k5():
    from petroharness.agent.claims import Claim, Claims
    from petroharness.agent.ledger import Ledger
    for t, f in FI():
        c = routes.invasion_counts(f.view)
        if not c or c.get("RMED") or c["n"] - c["other"] == 0:
            continue
        cl = Claim(id="C1", point=1, text="INVASION_RATIO is the RMED/RDEP fallback in this interval",
                   means="the separation is a medium/deep proxy", ev=["MAP"], grade="moderate")
        flags = Claims(["p"], Ledger(f), "", "q", f.view, (t.well,)).check(cl)
        assert any(x.startswith("K5 says INVASION_RATIO uses") for x in flags), flags
        return
    pytest.skip("no interval without the fallback")


# --- signed compare -------------------------------------------------------------------------------------------------------

def _pooled(text: str) -> str:
    return next(ln for ln in text.splitlines() if ln.strip().startswith("zones pooled:"))


@pytest.mark.data
def test_compare_shares_are_signed_and_match_numpy():
    from petroharness.agent.tools import compare
    done = 0
    for t, f in F():
        pair = next(((a, b) for a, b in (("RMED", "RDEP"), ("PHIT", "PHIE"), ("RSHA", "RDEP")) if a in f.inv.curves and b in f.inv.curves), None)
        if pair is None:
            continue
        a, b = pair
        xa, xb = (np.asarray(f.view.values(c), dtype=float)[f.view.zoned] for c in (a, b))
        ok = np.isfinite(xa) & np.isfinite(xb)
        d = xa[ok] - xb[ok]
        line = _pooled(compare(f, a, b).text)
        line_t = _pooled(compare(f, a, b, tolerance=0.01).text)
        hi = float(re.search(rf"{a} > {b} in ([\d.]+)%", line).group(1))
        lo = float(re.search(rf"{a} < {b} in ([\d.]+)%", line).group(1))
        assert abs(hi - 100 * np.mean(d > 0)) <= 0.051 and abs(lo - 100 * np.mean(d < 0)) <= 0.051, (t.well, line)
        shares = [float(x) for x in re.findall(r"in ([\d.]+)%", line_t)]
        assert len(shares) == 3 and abs(sum(shares) - 100) <= 0.2, line_t
        assert "beyond" not in line                                         # the signed shares, not the unsigned one
        done += 1
        if done >= 12:
            break
    assert done or pytest.skip("no pair of one scale")


# --- the spike screen -------------------------------------------------------------------------------------------------

def _spike_blocks(text):
    heads = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^([A-Z][A-Z0-9_]*)(?: \[[^\]]*\])? = ", text)]
    return {name: text[a:(heads[i + 1][0] if i + 1 < len(heads) else len(text))] for i, (a, name) in enumerate(heads)}


def _zone_counts(f, y, k):
    total = 0
    for z in f.view.zones:
        yz = y[np.asarray(z.indices)]
        ok = np.isfinite(yz)
        if ok.sum() < 3 or np.std(yz[ok]) == 0:
            continue
        total += int((ok & (np.abs(yz - np.mean(yz[ok])) > k * np.std(yz[ok]))).sum())
    return total


@pytest.mark.data
@pytest.mark.parametrize("scale", ["linear", "log10"])
def test_spikes_per_zone_tiers_match_numpy(scale):
    from petroharness.agent.compute import spike_flags
    done = 0
    for t, f in F():
        cs = [c for c in ("RDEP", "GR", "PHIE", "SW") if c in f.inv.curves]
        if "RDEP" not in cs:
            continue
        text = spike_flags(f, cs, scale=scale if scale == "log10" else None).text
        assert "each zone's own mean and std" in text and "2 and 3 std" in text
        blocks = _spike_blocks(text)
        for c in cs:
            block = blocks[c]
            x = np.asarray(f.view.values(c), dtype=float)
            y = np.where(x > 0, np.log10(np.where(x > 0, x, 1.0)), np.nan) if scale == "log10" else x
            m = re.search(rf"zones pooled, {c}: beyond: (\d+) samples at 2 std, (\d+) samples at 3 std", block)
            assert m and int(m.group(1)) == _zone_counts(f, y, 2) and int(m.group(2)) == _zone_counts(f, y, 3), (t.well, c, block[:300])
            if re.search(r"none beyond 2 std in \d+ zones", block) and "not shown here" not in text:   # unflagged
                #   zones show their baseline (unless the size limit cut lines)
                assert "each unflagged zone's mean +/- std" in block, (t.well, c, block[:300])
            for lo in re.findall(r"at \d std (\S+) to", block):             # never a negative bound for these curves
                assert lo == "none" or float(lo) >= 0 or np.nanmin(x) < 0, (t.well, c, lo)
            for val, dep, zid in re.findall(r"largest: ([\d.]+) at ([\d.]+) \w+ \((Z\d+|between zones)", block):
                assert zid == zone_at(f, float(dep)), (t.well, c, dep, zid)
        done += 1
        if done >= 8:
            break
    assert done or pytest.skip("no RDEP here")


@pytest.mark.data
def test_spikes_one_k_and_a_rolling_window():
    from petroharness.agent.compute import spike_flags
    t, f = next((t, f) for t, f in F() if "GR" in f.inv.curves)
    one = spike_flags(f, ["GR"], k=3).text
    assert "at 2 std" not in one and _zone_counts(f, np.asarray(f.view.values("GR"), dtype=float), 3) == \
        int(re.search(r"zones pooled, GR: beyond: (\d+) samples at 3 std", one).group(1))
    win = spike_flags(f, ["GR"], window=11).text
    assert "rolling median and MAD of 11 samples" in win and "robust std" in win or "median +/- robust std" in win
    with pytest.raises(ToolError):
        spike_flags(f, ["GR"], window=2)
    assert spike_flags(f, ["GR"], window=11.0).text == win


# --- zone tags, selectors, compact zone rows ---------------------------------------------------------------------------

@pytest.mark.data
def test_zone_at_reads_the_zones_samples():
    for t, f in F():
        d = f.depth
        for z in f.view.zones:
            idx = np.asarray(z.indices)
            assert zone_at(f, float(d[idx[0]])) == z.zone_id and zone_at(f, float(d[idx[-1]])) == z.zone_id, (t.well, z.zone_id)
        outside = np.setdiff1d(np.arange(d.size), np.concatenate([np.asarray(z.indices) for z in f.view.zones]))
        if outside.size:
            assert zone_at(f, float(d[outside[0]])) == "between zones"


@pytest.mark.data
def test_lithology_names_select_their_zones():
    for t, f in F():
        liths = sorted({E.zone_name(z).upper() for z in f.view.zones})
        assert [z.zone_id for z in E.zones(f, ["ALL"])] == [z.zone_id for z in f.view.zones]
        for lith in liths:
            want = [z.zone_id for z in f.view.zones if E.zone_name(z).upper() == lith]
            assert [z.zone_id for z in E.zones(f, [lith])] == want, (t.well, lith)
            assert [z.zone_id for z in E.zones(f, [lith.lower().replace(" ", "_")])] == want
            if len(lith) > 3:
                star = [z.zone_id for z in E.zones(f, [lith[:3] + "*"])]
                assert set(want) <= set(star)
        mixed = E.zones(f, [f.view.zones[0].zone_id, liths[0]])
        assert len(mixed) == len({z.zone_id for z in mixed})                      # each zone once
        with pytest.raises(ToolError, match="or a lithology"):
            E.zones(f, ["NO_SUCH_ROCK"])


@pytest.mark.data
def test_first_look_keeps_every_zone():
    """Every zone of every curve is shown, within the size limit: a full row, or a shorter row naming its
    zone and curve with the statistics that let every zone fit; the full rows stay in the result."""
    from petroharness.agent import direction
    from petroharness.agent.tools import stats
    t, f = max(F(), key=lambda tf: len(tf[1].view.zones))
    if len(f.view.zones) < 8:
        pytest.skip("no formation with many zones")
    curves = [c for c in direction.overview(["hydrocarbon_detection"]) if c in f.inv.curves][:8]
    r = stats(f, curves, statistics=["mean", "median", "min", "max"])
    for c in curves:                                            # its row of the curve, or its row of every curve
        for z in f.view.zones:
            assert re.search(rf"(?m)^\s+{z.zone_id}\b.*, {c}: n |^  {z.zone_id}: .*\b{c} ", r.text), (t.well, z.zone_id, c)
    assert len(r.text) <= E.WIDE_CHARS
    x = np.asarray(f.view.values(curves[0]), dtype=float)
    for z in f.view.zones[:5]:                                  # each shown mean is the zone mean
        ln = next(ln for ln in r.text.splitlines() if re.match(rf"^\s+{z.zone_id}\b.*, {curves[0]}: n |^  {z.zone_id}: ", ln))
        m = re.search(rf"(?:, |: |{curves[0]} )mean (-?[\d.]+)", ln)
        if m:
            want = float(np.nanmean(x[np.asarray(z.indices)]))
            assert abs(float(m.group(1)) - want) <= 1e-3 * max(1, abs(want)), (z.zone_id, ln, want)


@pytest.mark.data
def test_runs_refuses_a_zero_max_thickness():
    from petroharness.agent.tools import runs
    t, f = next((t, f) for t, f in F() if "NET_PAY" in f.inv.curves)
    with pytest.raises(ToolError, match="keeps no run"):
        runs(f, "NET_PAY", max_thickness=0)
    runs(f, "NET_PAY", max_thickness=0.5)


# --- the zone-mean class view -----------------------------------------------------------------------------------------

@pytest.mark.data
def test_zone_mean_classes_beside_the_sample_shares():
    """A section's classes both ways (the summary layer's class views): the zones pooled by zone mean (shares of the
    zoned thickness, summing to 100%) beside the share of the zone samples; no zone-mean view for classes that count
    samples (the numerical family)."""
    from petroharness.record.catalog import zone_classes_raw
    from petroharness.agent.tools import ZONE_MEAN_FAMILIES, section
    done = 0
    for t, f in F()[:12]:
        topics = f.view.reg.topics["topics"]
        for s in f.inv.sections:
            fam, _, name = s.key.partition(".")
            topic = next((k for k, specs in topics.items() if any(a == fam and name in b for a, b in specs)), None)
            text = section(f, s.key).text
            line = next((ln for ln in text.splitlines() if ln.startswith("    zones pooled: ")), None)
            if fam not in ZONE_MEAN_FAMILIES or topic is None:
                assert line is None or "by zone mean" not in line, (t.well, s.key)
                continue
            labels = zone_classes_raw(f.view, topic)["classes"].get(name)
            if not labels or line is None:
                continue
            by_mean = line.split("; samples ")[0]
            shares = [float(x) for x in re.findall(r" ([\d.]+)% \(", by_mean)]
            assert abs(sum(shares) - 100) <= 0.1 * len(shares), (t.well, s.key, line)
            for lab in set(labels.values()):
                assert lab in by_mean, (t.well, s.key, lab)
            assert "of the zone samples" in line
            done += 1
    assert done or pytest.skip("no zone-mean classes here")


# --- the writer sees its table ----------------------------------------------------------------------------------------

@pytest.mark.data
@pytest.mark.parametrize('on', [True])
def test_the_writer_is_shown_its_table(real, on):
    from petroharness.agent.writer import prompt, unsupported
    system, user, table, shape = prompt(real, "open", "default")
    assert table and ("THE ZONE TABLE" in user) is on and (table in user) is on
    n = re.search(r"\| (\d+\.\d{3,})", table)
    if n and on:                                             # a table value quoted alone is shown
        assert n.group(1) not in unsupported(f"The zone value is {n.group(1)}.", real, table)


@pytest.mark.parametrize("text,hits", [
    ("Zone rows were truncated in the records, so Z5 is not discussed.", True),
    ("Two zones were left out to keep this short.", True),
    ("The output size limit hid three zones.", True),
    ("The sonic log is truncated at casing above 2500 m.", False),        # a fact about the data
    ("Porosity is 0.21 in the sand.", False),
])
def test_display_limits_are_process_words(text, hits):
    from petroharness.agent.writer import process_words
    assert bool(process_words(text)) is hits, text


# --- scope: what the model's topics read ---------------------------------------------------------------------------

def _k8(f, t, families, text, weak="", on=True):
    from petroharness.agent.claims import Claim, Claims
    from petroharness.agent.ledger import Ledger
    cl = Claim(id="C1", point=1, text=text, means="it bears on the porosity of the sands", ev=["MAP"], grade="moderate",
               weak=weak)
    c = Claims(["p"], Ledger(f), "", "q", f.view, (t.well,))
    c.families = families
    return [x for x in c.check(cl) if x.startswith("K8")]


FLUID = ("hydrocarbon", "saturation")                 # hydrocarbon_detection's families


@pytest.mark.data
def test_k8_asks_only_about_the_families_the_topics_read():
    gas = re.compile(r"(STRONG|MODERATE|WEAK)_GAS_EFFECT|(STRONG_)?GAS_INDICATION|LOW_VPVS|GAS_SHOW|PRIME_GAS_TARGET")
    for t, f in F():
        keys = {k for k, sec in (f.store.sections if f.store is not None else {}).items()
                if any(gas.fullmatch(str(lab).upper()) and rs for lab, rs in sec.classes.items())}
        if not keys or any(k.split(".")[0] == "porosity" for k in keys):
            continue
        text = "No gas effect is seen in the sands"
        assert not _k8(f, t, ("porosity",), text, on=True), "porosity topics do not open gas sections"
        if any(k.split(".")[0] in FLUID for k in keys):
            assert _k8(f, t, FLUID, text, on=True), "hydrocarbon topics still check gas"
            assert _k8(f, t, (), text, on=True), "no topics: every family is checked"
        neutral = "PHIE averages 0.2 in the sands"
        assert not _k8(f, t, FLUID, neutral, weak="gas could lower the density porosity", on=True)
        return
    pytest.skip("no formation with gas classes outside the porosity family")


@pytest.mark.data
@pytest.mark.parametrize('on', [True])
def test_guide_sections_stay_in_the_families_of_the_topics(on):
    from test_b5_loop import Script, _session, chose
    from petroharness.llm import Usage
    from petroharness.agent.loop import investigate
    s = _session()
    keys = s.library.sections("invasion_movability", s.f)
    other = [k for k in keys if not k.startswith("permeability.")]
    if not other or len(other) == len(keys):
        pytest.skip("the invasion guide names no mix of families here")
    chose(s, "permeability_rock_quality")
    first = {"points": ["How does separation relate to permeability?"], "intent": "explain", "focus": "separation",
             "edits": [{"op": "add", "point": 1, "text": "Separation likely marks permeable sands", "grade": "hypothesis"}],
             "next": [{"guide": "invasion_movability"}], "done": False}
    llm, trace = Script([first]), {}
    investigate(llm, s, Usage(), 4000, trace, max_steps=2)
    opened = trace["steps"][0]["guide_sections"]
    assert (set(opened) & set(other) == set()) is on and set(opened) <= set(keys)
    assert all(k.startswith("permeability.") for k in opened) or not on
    step1 = llm.sent[0][1][-1]["content"]
    assert ("Each point is a part of this question" in step1) is on


# --- guides -------------------------------------------------------------------------------------------------------------

def test_guides_state_no_conclusion_as_a_rule():
    """No guide states a conclusion as a rule or chooses a basis for the model; the answer guide keeps its caveat
    guideline."""
    from petroharness.agent.direction import plugged
    lib = plugged()                                                 # the plugged library (researched)
    every = "\n".join(lib.guide(n) for n in lib.facets)
    for gone in ("each zone is a flow unit of its class", "One FZI class over all zones is a finding",
                 "Hydraulic flow units proven", "zones whose means meet it", "weakened by the narrow range"):
        assert gone not in every, gone
    assert "does not reverse the workflow's classes" in lib.guide("answer")


def test_the_brief_carries_the_readings_and_weaknesses_lines():
    from petroharness.agent.loop import V9_BRIEF, brief
    assert V9_BRIEF in brief()


@pytest.mark.data
def test_writer_rule_no_reversal(real):
    from petroharness.agent.writer import ASPECTS_RULE, NO_REVERSAL_RULE, prompt
    system, _, _, _ = prompt(real, "open", "default")
    assert NO_REVERSAL_RULE.split(".")[0] in system and ASPECTS_RULE in system


def test_tool_descriptions_say_signs_zone_values_and_the_zone_selector():
    from petroharness.agent.loop import tools_text
    on = tools_text()
    assert "a > b and with a < b" in on and "each zone's own values" in on and "a lithology" in on
    assert on.splitlines()[-1].startswith("  zones (any lookup that takes them)")      # the zone selector line, last


# --- the "not recorded" note -----------------------------------------------------------------------------------------

def test_well_wide_route_lines_drop_the_not_recorded_note():
    line = "Depth routing counts: archie, indonesia (routes used in the well; counts for this interval not recorded)"
    assert routes.well_wide(line) == "well-wide record: Depth routing counts: archie, indonesia (routes used in the well)"
    assert routes.well_wide("Perm range in this interval: 1 to 2 mD") == "Perm range in this interval: 1 to 2 mD"


# --- the record's basis first ------------------------------------------------------------------------------------------

def _zone_means(f, c):
    x = np.asarray(f.view.values(c), dtype=float)
    return {z.zone_id: (float(np.nanmean(x[np.asarray(z.indices)])) if np.isfinite(x[np.asarray(z.indices)]).any() else np.nan)
            for z in f.view.zones}


@pytest.mark.data
def test_conditions_read_on_zone_means():
    from petroharness.agent.tools import runs, stats
    done = 0
    for t, f in F():
        pair = next(((a, b) for a, b in (("RMED", "RDEP"), ("PHIT", "PHIE"), ("RHOB", "PHIE")) if a in f.inv.curves and b in f.inv.curves), None)
        if pair is None or len(f.view.zones) < 2:
            continue
        a, b = pair
        cond = f"{a} > {b}"
        ma, mb = _zone_means(f, a), _zone_means(f, b)
        want = [z.zone_id for z in f.view.zones if np.isfinite(ma[z.zone_id]) and np.isfinite(mb[z.zone_id]) and ma[z.zone_id] > mb[z.zone_id]]
        text = runs(f, cond).text
        st = stats(f, ["GR"] if "GR" in f.inv.curves else [a], where=cond).text
        line = next(ln for ln in text.splitlines() if "zones whose means meet it" in ln)
        got = re.search(rf"meet it \(on {', '.join(sorted({a, b}))}; each zone by its mean values\): ([^(]+) \((\d+) of "
                        r"(\d+)", line)
        names = [] if got.group(1).strip() == "none" else [
            f"Z{i}" for x in got.group(1).split(",") for a, b in [re.fullmatch(r"\s*Z(\d+)(?:-Z(\d+))?\s*", x).groups()]
            for i in range(int(a), int(b or a) + 1)]
        assert names == want and int(got.group(2)) == len(want), (t.well, line, want)
        assert "zones whose means meet it" in st
        done += 1
        if done >= 10:
            break
    assert done or pytest.skip("no pair")


@pytest.mark.data
def test_flags_and_classes_get_no_zone_mean_verdict():
    from petroharness.agent.tools import runs
    t, f = next((t, f) for t, f in F() if "NET_PAY" in f.inv.curves and len(f.view.zones) >= 2)
    assert "zones whose means meet it" not in runs(f, "NET_PAY").text
    assert "zones whose means meet it" not in runs(f, "NET_PAY and SW < 0.5").text


@pytest.mark.data
def test_compare_by_zone_mean_counts():
    from petroharness.agent.tools import compare
    for t, f in F():
        if not ("RMED" in f.inv.curves and "RDEP" in f.inv.curves) or len(f.view.zones) < 2:
            continue
        ma, mb = _zone_means(f, "RMED"), _zone_means(f, "RDEP")
        both = [z.zone_id for z in f.view.zones if np.isfinite(ma[z.zone_id]) and np.isfinite(mb[z.zone_id])]
        above = [z for z in both if ma[z] > mb[z]]
        line = next(ln for ln in compare(f, "RMED", "RDEP").text.splitlines() if "by zone mean" in ln)
        assert f"above RDEP in {len(above)} of {len(both)} zones" in line, (t.well, line)
        return
    pytest.skip("no RMED/RDEP")


@pytest.mark.data
def test_stats_give_each_zone_then_the_zones_pooled_then_the_whole_interval():
    """G6: the three bases in a fixed order, the whole interval with the count of samples outside any zone."""
    from petroharness.agent.tools import stats
    for t, f in F():
        k = int(f.depth.size - np.count_nonzero(f.view.zoned))
        if not k or "GR" not in f.inv.curves:
            continue
        lines = stats(f, ["GR"]).text.splitlines()
        z = next(i for i, ln in enumerate(lines) if ln.startswith(f"  {f.view.zones[0].zone_id} "))
        i = next(i for i, ln in enumerate(lines) if ln.startswith("  zones pooled, GR:"))
        j = next(i for i, ln in enumerate(lines) if ln.startswith("  whole interval"))
        assert z < i < j and lines[j].startswith(f"  whole interval ({k} samples outside any zone), GR:"), (t.well, lines[:4])
        return
    pytest.skip("no unzoned samples")


@pytest.mark.data
def test_section_digest_keeps_the_classes():
    from petroharness.agent.ledger import Ledger
    done = 0
    for t, f in FI():
        for s in f.inv.sections:
            if len(s.classes) < 2:
                continue
            led = Ledger(f)
            item, _ = led.open("section", {"key": s.key})
            if item is None or len(item.text) < 1700:
                continue
            dig = led.digest(item)
            assert "; runs: " in dig or "by zone mean" in dig, (t.well, s.key, dig[:400])
            assert len(dig) <= 1700
            done += 1
            break
        if done >= 5:
            break
    assert done or pytest.skip("no long section")


@pytest.mark.data
def test_writer_view_keeps_cited_and_newest_whole(real):
    from petroharness.agent.writer import opened_results
    items = real.ledger.items
    if len(items) < 3:
        pytest.skip("few items")
    cited = {x for c in real.claims.claims.values() for x in c.ev}
    small = sum(len(real.ledger.digest(e)) + 2 for e in items) + max(len(items[-1].text), 1) + 40
    text = opened_results(real, budget=small)
    newest = items[-1]
    if newest.id not in cited and len(newest.text) > len(real.ledger.digest(newest)):
        assert f"[{newest.id}] {newest.text}" in text                 # the newest kept whole within a tight budget


def test_scoped_notes():
    from petroharness.agent.map import scoped_notes
    notes = ["Rw: route=x", "SW model per sample", "SXO: quicklook", "MHI: from SXO", "PERM: Coates", "VCL: minimum",
             "hydrocarbon.geophysical_hydrocarbon_indicators: NO_INDICATION ...", "porosity.pore_system: NO_DATA ..."]
    assert scoped_notes(notes, ["porosity"]) == ["PERM: Coates", "VCL: minimum", "porosity.pore_system: NO_DATA ..."]
    assert scoped_notes(notes, list(FLUID)) == [n for n in notes if not n.startswith("porosity.")]
    assert "SXO: quicklook" in scoped_notes(notes, ["permeability"])
    assert scoped_notes(notes, []) == notes                                           # no topics: every note
    assert "SXO: quicklook" not in scoped_notes(notes, ["lithology", "porosity"])     # every family leaves it out
    assert "SXO: quicklook" in scoped_notes(notes, ["porosity", "saturation"])        # one family reads it


@pytest.mark.data
def test_map_values_labelled_and_primary_absent():
    from petroharness.agent.map import primary_absent, render
    t, f = FI()[0]
    m = render(f.inv)
    absent = primary_absent(f.inv)
    assert "values: " not in m and ("values (whole well, as recorded): " in m or "values" not in m)
    assert set(absent) <= set(f.inv.logs_absent)
    assert not {"THOR", "URAN", "POTA"} & set(absent)


@pytest.mark.data
def test_data_record_names_computed_primary_logs():
    from petroharness.agent.compute import _run, data_record
    for t, f in F():
        old = _run(f, "data_record", None).text                  # the workflow's record as it reads
        m = re.search(r"primary logs missing from the well: ([^\n]*)", old)
        if not m or m.group(1).strip() == "none":
            continue
        names = [x.strip() for x in m.group(1).split(",")]
        made = [x for x in names if x.upper() in f.inv.curves and np.isfinite(np.asarray(f.view.values(x.upper()), dtype=float)).any()]
        new = data_record(f).text
        assert "primary logs missing from the well" not in new
        if made:
            assert "computed by the workflow, with values here: " + ", ".join(made) in new, (t.well, made)
        return
    pytest.skip("no missing primary log")


@pytest.mark.data
def test_shear_label_checked_against_dtc():
    seen = 0
    for t, f in FI():
        for c, cv in f.inv.curves.items():
            if "shear" in cv.meaning.lower() and "DTC" in f.inv.curves and c != "DTC":
                x, d = (np.asarray(f.view.values(n), dtype=float) for n in (c, "DTC"))
                ok = np.isfinite(x) & np.isfinite(d) & (d > 0)
                if ok.sum() >= 10:
                    r = float(np.median(x[ok] / d[ok]))
                    assert ("its values track DTC" in cv.meaning) is (0.9 <= r <= 1.1), (t.well, c, r, cv.meaning)
                    seen += 1
    assert seen or pytest.skip("no shear-labelled curve beside DTC")


@pytest.mark.data
def test_the_writer_has_the_limits_rule_and_the_absent_rule_where_named(real):
    from petroharness.agent.writer import ABSENT_RULE, LIMITS_RULE, prompt
    system, user, _, _ = prompt(real, "open", "default")
    assert LIMITS_RULE in system and "In the limitations, say once which measured logs" not in system
    assert (ABSENT_RULE in system) == ("Named but not in this well's record: " in user)      # with what is named but absent


# --- stopping denials ----------------------------------------------------------------------------------------------

def test_no_strength_words():
    """G6: a coefficient is shown as a number; the harness applies no tier list of its own (negligible, weak,
    moderate, strong)."""
    from petroharness.agent import engine
    assert not hasattr(engine, "strength")


def test_guides_hold_no_ranking_tier_or_basis_line_of_the_harness():
    """No guide carries a ranking, tier or basis line of the harness's own (the flow-units ranking line:
    test_levels_and_rankings.py); the invasion guide keeps the review's quicklook line."""
    from petroharness.agent.direction import plugged
    lib = plugged()                                                 # the plugged library (researched)
    every = "\n".join(lib.guide(n) for n in lib.facets)            # every guide's text
    for gone in ("principal flow unit carries", "highest credible zone-mean permeability", "2 and 3 std tiers",
                 "each zone's own samples", "not assessed here"):
        assert gone not in every, gone
    assert "If SXO came from SW" in lib.guide("invasion_movability")       # a quicklook SXO restates SW (the review's line)


@pytest.mark.data
def test_zone_class_lines_carry_no_verdict_wording():
    from petroharness.agent.compute import zone_classes
    for t, f in F():
        new = zone_classes(f, "porosity_quality").text
        if "fail the net-rock cutoff" not in new:
            continue
        assert "is not reservoir rock" not in new                           # no verdict wording
        return
    pytest.skip("no failing zone")


# --- plain argument spellings (schemas.fit) ----------------------------------------------------------------------------

@pytest.mark.parametrize("name,args,want", [
    ("stats", {"curves": ["PHIE"], "statistics": "mean median min max"}, {"statistics": ["mean", "median", "min", "max"]}),
    ("stats", {"curves": ["PHIE"], "statistics": ["mean, std"]}, {"statistics": ["mean", "std"]}),
    ("stats", {"curves": ["PHIE"], "statistics": "geometric mean, standard deviation"}, {"statistics": ["geo_mean", "std"]}),
    ("stats", {"curves": ["PHIE"], "statistics": ["n", "mean"]}, {"statistics": ["n", "mean"]}),          # stats has n
    ("lithology_stats", {"curves": ["PHIE"], "statistics": ["n", "mean"]}, {"statistics": ["mean"]}),
    ("lithology_stats", {"curves": ["PHIE"], "statistics": ["count"]}, {}),                             # all dropped
    ("spike_flags", {"curves": ["GR"], "baseline": "default"}, {}),
    ("spike_flags", {"curves": ["GR"], "scale": "Default", "baseline": "zone"}, {"baseline": "zone"}),
    ("threshold_exceedance", {"curve": "GR", "threshold": 100, "op": "lt"}, {"op": "<"}),
    ("threshold_exceedance", {"curve": "GR", "threshold": 100, "op": "greater than"}, {"op": ">"}),
    ("threshold_exceedance", {"curve": "GR", "threshold": 100, "op": ">="}, {"op": ">="}),
])
def test_plain_argument_spellings(name, args, want):
    from petroharness.agent.schemas import fit
    got = fit(name, dict(args))
    for k in ("statistics", "baseline", "scale", "op"):
        if k in want:
            assert got.get(k) == want[k], (k, got)
        elif k in args:                                     # read as the default: left out
            assert k not in got, (k, got)


@pytest.mark.data
def test_plain_spellings_run_and_equal_the_canonical_call():
    from petroharness.agent.schemas import call
    n = 0
    for t, f in FI()[:12]:
        if "GR" not in f.inv.curves or "PHIE" not in f.inv.curves:
            continue
        pairs = [({"curves": ["GR"], "baseline": "default"}, {"curves": ["GR"]}, "spike_flags"),
                 ({"curve": "GR", "threshold": 100, "op": "lt"}, {"curve": "GR", "threshold": 100, "op": "<"},
                  "threshold_exceedance"),
                 ({"curves": ["PHIE"], "statistics": "n mean median"}, {"curves": ["PHIE"], "statistics": ["mean", "median"]},
                  "lithology_stats"),
                 ({"curves": ["PHIE"], "statistics": "mean median min max"},
                  {"curves": ["PHIE"], "statistics": ["mean", "median", "min", "max"]}, "stats")]
        for loose, canon, tool in pairs:
            try:
                want = call(f, tool, canon).text
            except ToolError:
                continue
            assert call(f, tool, loose).text == want, (t.well, tool, loose)
            n += 1
    assert n


@pytest.mark.data
def test_a_step_named_as_a_section_opens_the_step():
    from petroharness.agent.tools import section, step
    n = 0
    for t, f in FI()[:12]:
        for m in f.inv.methods[:3]:
            if any(s.key.split(".")[-1] == m.step for s in f.inv.sections):
                continue
            assert section(f, m.step).text == step(f, m.step).text
            n += 1
    assert n


@pytest.mark.parametrize("text,minus", [
    ("averages –0.1384 v/v", True), ("from –0.1692 to –0.1071", True), ("(–0.02996, 59%)", True),
    ("depths 2201–2210 m", False), ("PHID–PHIN", False), ("Z1–Z3", False), ("0.1–0.2 v/v", False),
])
def test_a_dash_before_a_number_is_its_minus(text, minus):
    from petroharness.agent.writer import _DASH_MINUS
    assert (_DASH_MINUS.sub("-", text) != text) == minus


@pytest.mark.data
def test_negative_results_written_with_a_dash_or_as_magnitudes_are_supported():
    from types import SimpleNamespace as NS

    from petroharness.agent.ledger import Ledger
    from petroharness.agent.map import render
    from petroharness.agent.writer import unsupported
    n = 0
    for t, f in FI()[:10]:
        if not all(c in f.inv.curves for c in ("PHIE", "PHIT")):
            continue
        led = Ledger(f)
        item = next(x for x in led.open("compare", {"a": "PHIE", "b": "PHIT"}) if hasattr(x, "text"))
        m = re.search(r"difference mean (-\d+\.\d+)", item.text)
        if not m:
            continue
        s = NS(f=f, ledger=led, task=NS(question="How does PHIE compare with PHIT?", well=t.well), map=render(f.inv))
        v = m.group(1)[1:]
        for draft, ok_on in ((f"PHIE sits {v} v/v below PHIT.", True), (f"The difference averages –{v} v/v.", True),
                             (f"The difference averages -{v} v/v.", True), (f"The difference averages +9{v} v/v.", False)):
            assert (not unsupported(draft, s)) == ok_on, (t.well, draft)
        n += 1
    assert n
