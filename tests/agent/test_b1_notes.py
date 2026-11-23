"""Map notes tests (N1-N3): the map's notes on this interval, on every formation of the dataset, against the record's
provenance facts and references computed from the curves; plus synthetic cases for the rules.

    .venv/bin/python -m pytest tests/agent/test_b1_notes.py -q   (PETROHARNESS_DATA selects the dataset)
"""
import re
import sys
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.agent.map import render  # noqa: E402
from petroharness.agent import notes as N  # noqa: E402
from petroharness.agent.notes import BAD_HOLE_SHOWN, bad_hole, not_run  # noqa: E402


@lru_cache(maxsize=1)
def cases():
    from _support.formations import formations
    return [(t, v, inv, render(inv)) for t, v, s, inv in formations()]


def _note(inv, head):
    return [x for x in inv.notes if x.startswith(head)]


# --- N1 facts ---------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_n1_provenance_facts_are_the_notes_built_from_data():
    """The card builds each fact from the record (the solver's minerals as this interval has them, the core fact with
    its plugs, no 'method not recorded' line, no core fact where the core-calibrated curves are supplied inputs); the
    notes take them as they are, reading no fact's text."""
    from petroharness.record.card import provenance_facts
    bad = []
    for t, v, inv, m in cases():
        core_input = any(inv.curves.get(c) is not None and inv.curves[c].source == "input" for c in ("PHIE_CC", "PERM_CC"))
        for x in provenance_facts(v):
            if x.endswith("method not recorded") or (x.startswith("Core-calibrated curves") and core_input):
                bad.append((t.well, "a kind the card no longer builds", x[:80]))
            if x not in inv.notes:
                bad.append((t.well, "fact missing", x[:80]))
        for x in inv.notes:
            assert f"  - {x}" in m.split("Notes on this interval")[1], (t.well, x[:80])
        assert not re.search(r"supplied in the LAS|not computed by", "\n".join(inv.notes)), t.well
    assert not bad, bad[:10]


# --- N2 references ------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_n2_quicklook_sxo_is_said_where_the_curves_show_it():
    checked, bad = 0, []
    for t, v, inv, m in cases():
        if not (v.available("SXO") and v.available("SW")):
            continue
        sw, sxo = (np.asarray(v.values(c), dtype=float) for c in ("SW", "SXO"))
        ok = np.isfinite(sw) & np.isfinite(sxo) & (sw > 0) & (sw < 0.999)
        if ok.sum() < 10:
            continue
        share = float((np.abs(sxo[ok] - sw[ok] ** 0.2) <= 1e-3 * np.maximum(1, sxo[ok])).mean())
        line = " ".join(_note(inv, "SXO:"))
        checked += 1
        if share >= 0.95 and "quicklook" not in line:
            bad.append((t.well, t.formation, "quicklook by the curves, not said", round(share, 3), line[:100]))
        if share <= 0.05 and re.search(r"SXO: quicklook", line):
            bad.append((t.well, t.formation, "measured by the curves, said quicklook", round(share, 3), line[:100]))
    print(f"\nN2 SXO: {checked} formations checked")
    assert not bad, bad[:10]


@pytest.mark.data
def test_n2_bad_hole_shares_match_numpy():
    checked, bad = 0, []
    for t, v, inv, m in cases():
        if not v.available("BAD_HOLE"):
            assert not _note(inv, "Bad hole"), t.well
            continue
        x = np.asarray(v.values("BAD_HOLE"), dtype=float)
        ref = {}
        for z in v.zones:
            y = x[z.indices]
            y = y[np.isfinite(y)]
            if y.size:
                ref[z.zone_id] = 100 * float((y > 0.5).mean())
        line = " ".join(_note(inv, "Bad hole"))
        assert line, t.well
        checked += 1
        said = {z: float(s) for z, s in re.findall(r"\b(Z\d+) ([\d.]+)%", line)}
        big = sorted([z for z, s in ref.items() if s >= BAD_HOLE_SHOWN], key=lambda z: -ref[z])
        for z in big[:8]:
            if z not in said or abs(said[z] - ref[z]) > 0.05 + 1e-9:
                bad.append((t.well, t.formation, z, ref[z], said.get(z)))
        for z in said:
            if ref.get(z, 0) < BAD_HOLE_SHOWN:
                bad.append((t.well, t.formation, "named below the threshold", z))
        if not big and "under" not in line:
            bad.append((t.well, t.formation, "no zone above the threshold, not said", line[:80]))
    print(f"\nN2 bad hole: {checked} formations checked")
    assert not bad, bad[:10]


@pytest.mark.data
def test_n2_the_geophysical_screen_without_dts_is_said_not_run():
    checked, bad = 0, []
    for t, v, inv, m in cases():
        sec = [s for s in inv.sections if s.key.endswith("geophysical_hydrocarbon_indicators")]
        if not sec:
            continue
        cls = {c.name: c for c in sec[0].classes}
        ni = cls.get("NO_INDICATION")
        share = float(re.sub(r"[^\d.]", "", ni.share_pct or "0") or 0) if ni else 0
        said = [x for x in inv.notes if x.startswith(sec[0].key + ":")]
        dts = v.available("DTS") and np.isfinite(np.asarray(v.values("DTS"), dtype=float)).any()
        checked += 1
        if not dts and share >= 99 and not (said and "DTS" in said[0]):
            bad.append((t.well, t.formation, "not said", share))
        if dts and said and "DTS" in said[0]:
            bad.append((t.well, t.formation, "said without DTS absent", said[0][:100]))
    print(f"\nN2 geophysical screen: {checked} formations checked")
    assert not bad, bad[:10]


@pytest.mark.data
def test_n2_solver_minerals_are_named_where_they_have_data():
    for t, v, inv, m in cases():
        minerals = [c for c in (v.reg.curves.get("minerals") or {}) if v.available(c)]
        line = [x for x in inv.notes if "non-unique solver output" in x or "mineral-solver volumes" in x]
        assert bool(minerals) == bool(line), (t.well, minerals, line)
        if minerals:
            assert line[0].startswith(", ".join(minerals) + ":"), (t.well, line[0][:80])


# --- N3 sizes ---------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_n3_sizes():
    big = [(t.well, t.formation, len("\n".join(inv.notes)), len(m)) for t, v, inv, m in cases()
           if len("\n".join(inv.notes)) > 2500 or len(m) > 24500]          # the map's limit holds the notes, the record's compartments and the curve catalog
    assert not big, big


# --- the rules on synthetic sections ------------------------------------------------------------------------------------

def _sec(key, share, method, name="NO_INDICATION"):
    return NS(key=key, method=method, classes=[NS(name=name, share_pct=share)])


@pytest.mark.parametrize("sec, curves, want", [
    (_sec("h.geo", "100%", "VP_VS_RATIO is calculated only when both DTS and DTC are present in plausible ranges"),
     {"DTC": 1}, [("h.geo", "NO_INDICATION", 100.0, ["DTS"])]),
    (_sec("h.geo", "100%", "VP_VS_RATIO is calculated only when both DTS and DTC are present"), {"DTC": 1, "DTS": 1}, []),
    (_sec("h.geo", "98.9%", "calculated only when both DTS and DTC are present"), {"DTC": 1}, []),          # not about all
    (_sec("p.inv", "100%", "Uses unavailable / RDEP; flushed priority RXO, RSHA", "NO_DATA"), {"RDEP": 1}, []),  # says it
    (_sec("s.fc", "100%", "Compares changes in SW and porosity (unavailable)", "NO_CONTACT_INDICATORS"), {"SW": 1},
     [("s.fc", "NO_CONTACT_INDICATORS", 100.0, ["an input it reads as unavailable"])]),
    (_sec("p.q", "100%", "Uses PHIT; fallback PHID=unavailable", "EXCELLENT_POROSITY"), {"PHIT": 1}, []),  # a result
    (_sec("h.rq", "100%", "porosity=unavailable", "UNDETERMINED"), {}, []),                              # says it
    (_sec("p.inv", "100%", "Uses RSHA / RDEP", "NO_INDICATION"), {"RDEP": 1, "RSHA": 1}, []),
    (_sec("x", None, "unavailable"), {}, []),                                                            # no share
    (_sec("x", "100%", None), {}, []),                                                                   # no method
    (NS(key="x", method="unavailable", classes=[]), {}, []),                                             # no classes
    (_sec("h.geo", "99.5 %", "only when DTS and DTC are present"), {}, [("h.geo", "NO_INDICATION", 99.5, ["DTS", "DTC"])]),
])
def test_not_run_rule(sec, curves, want):
    assert not_run([sec], curves) == want


def test_bad_hole_note_names_the_largest_zones_first_and_caps_at_eight():
    from petroharness.agent import notes as N
    zones = [NS(zone_id=f"Z{i}", indices=np.arange(i * 10, i * 10 + 10)) for i in range(1, 12)]
    x = np.zeros(200)
    for i in range(1, 11):                                         # Z1..Z10: i of 10 samples bad; Z11 none
        x[i * 10: i * 10 + i] = 1
    view = NS(zones=zones, available=lambda c: c == "BAD_HOLE", zone_values=lambda z, c: x[z.indices])
    assert bad_hole(view)[:2] == [("Z1", 10.0), ("Z2", 20.0)]
    line = N._bad_hole_note(view)
    assert line.startswith("Bad hole (BAD_HOLE > 0.5): Z10 100%, Z9 90%") and "(and 2 more zones)" in line
    x[:] = 0
    assert "under 5% of the samples in every zone" in N._bad_hole_note(view)
    assert N._bad_hole_note(NS(available=lambda c: False)) == ""


def _mineral_view(lithology_curve, labels):
    n = len(labels)
    vals = {"V_QUARTZ": np.linspace(0.1, 0.9, n)}
    return NS(mask=np.ones(n, dtype=bool), values=lambda c: vals.get(c), labels=np.array(labels, dtype=object),
              lithology_curve=lithology_curve, available=lambda c: c == "RHOB")


def test_a_well_zoned_by_shale_volume_bands_has_no_lithology_log_to_support_the_solver():
    v = _mineral_view(None, ["SHALE-PRONE (VCL BAND)", "CLEAN (VCL BAND)", "SHALY (VCL BAND)"])
    text = N.mineral_fact(v, ["V_QUARTZ"])
    assert "lithology log" not in text and "RHOB is present to support it" in text, text


def test_a_well_zoned_by_its_lithology_log_names_it_as_support():
    v = _mineral_view("LITH", ["SANDSTONE", "SHALE", "SANDSTONE"])
    text = N.mineral_fact(v, ["V_QUARTZ"])
    assert "the lithology log and RHOB are present to support it" in text, text
