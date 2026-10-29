"""Zone segmentation reproduces the reference zone names and bounds."""

import pytest

from petroharness.well.formation import MISSING_LITHOLOGY, decode_lithology, interval_from_tops, lithology_table, segment_zones
from petroharness.well.view import FormationView

from _reference import CFG, benchmark_pairs, benchmark_tasks, reference_groups

_REF_MISSING = "No lithology information available"


def _key(name: str, lithology: str, top: float, base: float):
    # Unlabelled runs are named differently by the reference exporter; compare them by bounds.
    if lithology in (MISSING_LITHOLOGY, _REF_MISSING):
        name = MISSING_LITHOLOGY
    return (name, round(top, 2), round(base, 2))


@pytest.mark.data
def test_zones_match_reference_names_and_bounds():
    pairs = benchmark_pairs()
    bad = []
    n_ref = n_ok = 0
    for well, formation in pairs:
        interval = interval_from_tops(well, formation, CFG.data)
        view = FormationView.build(next(t for t in benchmark_tasks() if t.well == well and t.formation == formation), CFG)
        depth, mask = view.prep.depth, interval.contains(view.prep.depth)
        codes = view.prep.curve(view.lithology_curve) if view.lithology_curve else None
        labels = decode_lithology(None if codes is None else codes[mask], int(mask.sum()), names=lithology_table(CFG.data))
        zones = segment_zones(depth[mask], labels)
        got = {_key(z.name, z.lithology, z.top, z.base) for z in zones}
        want = {_key(g["name"], g["lithology"], g["top"], g["base"]) for g in reference_groups(well, formation)}
        n_ref += len(want)
        n_ok += len(got & want)
        if got != want:
            bad.append((well, formation, sorted(want - got)[:3], sorted(got - want)[:3]))
    assert not bad, f"{len(bad)}/{len(pairs)} pairs differ ({n_ok}/{n_ref} zones match), e.g. {bad[:3]}"
