"""Tasks load without reference fields; intervals match the reference formation bounds."""

import numpy as np
import pytest

from petroharness.tasks import Task, load_tasks
from petroharness.well.formation import interval_from_tops
from petroharness.well.prepare import read_depth

from _reference import CFG, benchmark_pairs, reference_groups


@pytest.mark.data
def test_tasks_carry_no_reference_fields():
    tasks, index = load_tasks(CFG.eval.questions, CFG.data.las_dir)
    assert len(tasks) == 221
    assert set(Task.model_fields) == {"task_id", "question", "well", "formation", "las_path", "top", "base", "depth_unit",
                                      "base_closed", "formation_lithology"}  # inputs only (formation info may state its depths)
    for t in tasks:
        assert t.task_id.startswith("t") and len(t.task_id) == 11
        assert t.las_path.exists(), t.las_path
        # the opaque id must not reveal the reference zone label
        assert "GROUP" not in t.task_id
    assert all(v["qa_id"] for v in index.values())


@pytest.mark.data
def test_interval_bounds_match_reference_for_every_pair():
    mismatches = []
    pairs = benchmark_pairs()
    for well, formation in pairs:
        groups = reference_groups(well, formation)
        if not groups:
            mismatches.append((well, formation, "no reference zones"))
            continue
        ref = groups[0]["formation_info"]
        interval = interval_from_tops(well, formation, CFG.data)
        depth = read_depth(CFG.data.las_dir / f"{well}.las")
        inside = depth[interval.contains(depth)]
        got = (float(inside.min()), float(inside.max()))
        want = (ref["min_depth"], ref["max_depth"])
        if not np.allclose(got, want, atol=1e-3):
            mismatches.append((well, formation, got, want))
    assert not mismatches, f"{len(mismatches)}/{len(pairs)} pairs differ, e.g. {mismatches[:5]}"
