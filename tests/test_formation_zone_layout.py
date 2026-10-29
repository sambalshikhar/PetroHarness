"""data.zone_layout "formation": the whole formation interval as one zone (data whose context lays out one group per
formation); the default layout is unchanged."""
import numpy as np

from petroharness.config import DataPaths
from petroharness.well.formation import MISSING_LITHOLOGY, formation_zone, segment_zones


def test_one_zone_with_every_sample_and_the_majority_label():
    depth = np.arange(100.0, 110.0, 0.5)
    labels = np.array(["SHALE"] * 15 + [MISSING_LITHOLOGY] * 3 + ["CHALK"] * 2, dtype=object)
    z, = formation_zone(depth, labels)
    assert (z.zone_id, z.name, z.lithology, z.n_samples) == ("Z1", "SHALE_GROUP_1", "SHALE", 20)
    assert (z.top, z.base) == (100.0, 109.5) and list(z.indices) == list(range(20))


def test_a_thin_formation_is_kept_and_no_label_gives_missing():
    depth = np.array([10.0, 10.5, 11.0, 11.5])
    assert formation_zone(depth, np.array(["CHALK"] * 4, dtype=object))[0].n_samples == 4      # segment_zones drops it
    assert segment_zones(depth, np.array(["CHALK"] * 4, dtype=object), 2.0) == []
    assert formation_zone(depth, np.array([MISSING_LITHOLOGY] * 4, dtype=object))[0].lithology == MISSING_LITHOLOGY
    assert formation_zone(np.array([]), np.array([], dtype=object)) == []


def test_the_default_layout_is_lithology_runs():
    assert DataPaths(las_dir="x").zone_layout == "lithology_runs"
    assert DataPaths(las_dir="x", zone_layout="formation").zone_layout == "formation"
    try:
        DataPaths(las_dir="x", zone_layout="formations")
        raise AssertionError("a misspelt layout must be refused")
    except ValueError:
        pass


def test_the_log_names_the_zone_and_a_stated_lithology_it_does_not_read_is_kept():
    depth = np.arange(100.0, 102.0, 0.5)
    labels = np.array(["SHALE"] * 3 + [MISSING_LITHOLOGY], dtype=object)
    z, = formation_zone(depth, labels, "limestone")
    assert (z.name, z.lithology, z.n_samples, z.stated) == ("SHALE_GROUP_1", "SHALE", 4, "LIMESTONE")
    assert formation_zone(depth, labels, "Shale")[0].stated == ""                 # the same reading: nothing to add
    assert formation_zone(depth, labels)[0].stated == ""


def test_a_stated_formation_lithology_names_a_zone_without_a_lithology_log():
    depth = np.arange(100.0, 102.0, 0.5)
    z, = formation_zone(depth, np.array([MISSING_LITHOLOGY] * 4, dtype=object), "limestone")
    assert (z.name, z.lithology, z.stated) == ("LIMESTONE_GROUP_1", "LIMESTONE", "")


def test_the_task_reads_a_formation_lithology():
    from petroharness.tasks import _formation_depths
    assert _formation_depths({"name": "X", "top": 1, "base": 2, "lithology": "Marl"})["formation_lithology"] == "MARL"
    assert _formation_depths({"name": "X", "top": 1, "base": 2})["formation_lithology"] is None
