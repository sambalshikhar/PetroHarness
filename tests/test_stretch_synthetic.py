"""On synthetic wells: a stand-in prepared well of depths and codes
chosen by hand (tests/_synthetic.py), so every zone a view or a stretch must hold is typed here. Library codes: 1 and
2 SAND, 3 CROSSBEDDED SAND, 5 SILT, 7 SHALE, 9 LIMESTONE. The zone minimum is 2 m, kept only when strictly thicker.

    .venv/bin/python -m pytest tests/test_stretch_synthetic.py -q
"""
import numpy as np
import pytest

from _synthetic import runs_of, view


def _z(v):
    return [(z.zone_id, z.lithology, z.top, z.base, z.n_samples, int(z.indices[0]), int(z.indices[-1])) for z in v.zones]


# 0.5 m samples from 0 m: SAND 0-2.0 (exactly 2 m: no zone), SHALE 2.5-5.0 (2.5 m), SAND by codes 1 then 2 5.5-8.5
# (one run: both codes read SAND), one SILT sample 9.0, LIMESTONE 9.5-14.0; 29 samples
DEPTH = np.arange(29) * 0.5
CODES = runs_of([(1, 5), (7, 6), (1, 3), (2, 4), (5, 1), (9, 10)])


def test_the_whole_well_has_the_runs_strictly_thicker_than_the_minimum():
    v = view(DEPTH, lithology=CODES)
    assert _z(v) == [("Z1", "SHALE", 2.5, 5.0, 6, 5, 10), ("Z2", "SAND", 5.5, 8.5, 7, 11, 17),
                     ("Z3", "LIMESTONE", 9.5, 14.0, 10, 19, 28)]
    assert int(v.zoned.sum()) == 23


def test_a_stretch_that_cuts_a_run_to_the_minimum_drops_it():
    """3.0-12.0 m: the SHALE run is cut to 3.0-5.0 (2.0 m: no zone), SAND whole, the SILT sample, LIMESTONE cut to
    9.5-12.0 (2.5 m: a zone). Indices are the stretch's: its first sample is 3.0 m."""
    s = view(DEPTH, lithology=CODES).stretch(3.0, 12.0)
    assert int(s.mask.sum()) == 19 and s.depth[0] == 3.0 and s.depth[-1] == 12.0
    assert _z(s) == [("Z1", "SAND", 5.5, 8.5, 7, 5, 11), ("Z2", "LIMESTONE", 9.5, 12.0, 6, 13, 18)]


def test_limits_between_samples_take_the_samples_inside():
    s = view(DEPTH, lithology=CODES).stretch(2.6, 8.4)        # 3.0 .. 8.0 m
    assert s.depth[0] == 3.0 and s.depth[-1] == 8.0 and int(s.mask.sum()) == 11
    assert _z(s) == [("Z1", "SAND", 5.5, 8.0, 6, 5, 10)]


def test_a_lithology_that_changes_at_every_sample_gives_no_zone():
    s = view(np.arange(40) * 0.5, lithology=np.tile([1.0, 7.0], 20)).stretch(0.0, 19.5)
    assert s.zones == [] and int(s.zoned.sum()) == 0 and int(s.mask.sum()) == 40


def test_samples_with_no_lithology_code_make_a_run_of_no_lithology_data():
    codes = runs_of([(1, 10), (np.nan, 10), (7, 10)])
    v = view(np.arange(30) * 0.5, lithology=codes)
    assert [(z.lithology, z.top, z.base) for z in v.zones] == [("SAND", 0.0, 4.5), ("NO_LITHOLOGY_DATA", 5.0, 9.5),
                                                                ("SHALE", 10.0, 14.5)]


def test_a_changing_sample_rate_is_read_by_depth_not_by_count():
    """0.1524 m samples to 3.048 m (21 samples), then 0.5 m samples from 3.5 m: a SAND run of 14 fine samples is
    1.9812 m (no zone); a SHALE run of 5 coarse samples is exactly 2.0 m (no zone: strictly thicker); a LIMESTONE run
    of 6 coarse samples is 2.5 m (a zone). The coarse depths are exact in binary, so 2.0 m is 2.0."""
    fine = np.round(np.arange(21) * 0.1524, 4)
    coarse = 3.5 + np.arange(12) * 0.5
    depth = np.r_[fine, coarse]
    codes = np.r_[np.full(14, 1.0), np.full(7, 5.0), np.full(5, 7.0), np.full(1, 5.0), np.full(6, 9.0)]
    v = view(depth, lithology=codes)
    assert [(z.lithology, z.n_samples) for z in v.zones] == [("LIMESTONE", 6)]
    assert v.zones[0].top == 6.5 and v.zones[0].base == 9.0


def test_a_well_of_three_samples_has_no_zone_and_stretches_of_it_work():
    v = view(np.array([100.0, 100.5, 101.0]), lithology=np.array([1.0, 1.0, 1.0]))
    assert v.zones == []
    s = v.stretch(100.5, 101.0)
    assert int(s.mask.sum()) == 2 and s.zones == []


def test_a_feet_log_reported_in_metres_measures_the_minimum_in_metres():
    """Samples every 1 ft from 0 ft, reported in metres (x 0.3048): SAND 0-7 ft is 2.1336 m (a zone); SHALE 8-14 ft is
    1.8288 m (no zone); LIMESTONE 15-29 ft is 4.2672 m (a zone)."""
    ft = np.arange(30, dtype=float)
    codes = runs_of([(1, 8), (7, 7), (9, 15)])
    v = view(ft, lithology=codes, depth_scale=0.3048, report_unit="m", m_per_unit=1.0)
    assert [(z.lithology, z.n_samples) for z in v.zones] == [("SAND", 8), ("LIMESTONE", 15)]
    s = v.stretch(0.3048 * 3, 0.3048 * 20)                      # 3 to 20 ft, in metres
    assert int(s.mask.sum()) == 18
    assert s.zones == []            # SAND 3-7 ft is 1.2192 m, LIMESTONE 15-20 ft is 1.524 m: both under 2 m


def test_a_feet_log_reported_in_feet_measures_the_minimum_in_feet():
    """The same log reported in feet: the 2 m minimum is 6.5617 ft. SAND 0-7 ft (7 ft, a zone), SHALE 8-14 ft (6 ft,
    no zone), LIMESTONE 15-29 ft (14 ft, a zone); a stretch 3-20 ft: SAND 3-7 (4 ft, no zone), LIMESTONE 15-20 ft
    (5 ft, no zone)."""
    ft = np.arange(30, dtype=float)
    codes = runs_of([(1, 8), (7, 7), (9, 15)])
    v = view(ft, lithology=codes, depth_scale=1.0, report_unit="ft", m_per_unit=0.3048)
    assert [(z.lithology, z.top, z.base) for z in v.zones] == [("SAND", 0.0, 7.0), ("LIMESTONE", 15.0, 29.0)]
    s = v.stretch(3.0, 20.0)
    assert int(s.mask.sum()) == 18 and s.zones == []


def test_shale_volume_bands_without_a_lithology_log():
    """No lithology log: bands at VCL 0.3 and 0.6, each run of 6 samples 2.5 m thick."""
    vcl = runs_of([(0.1, 6), (0.45, 6), (0.8, 6)])
    v = view(np.arange(18) * 0.5, vcl=vcl)
    assert len(v.zones) == 3 and v.vcl_bands == (0.3, 0.6)
    labels = [z.lithology for z in v.zones]
    assert len(set(labels)) == 3 and all("BAND" in x for x in labels)
    s = v.stretch(3.0, 8.5)                                     # the middle and last bands, both whole
    assert [z.lithology for z in s.zones] == labels[1:]


def test_the_formation_layout_makes_one_zone_of_any_stretch_with_its_majority_lithology():
    v = view(DEPTH, lithology=CODES, layout="formation")
    assert len(v.zones) == 1 and v.zones[0].n_samples == 29
    s = v.stretch(9.0, 14.0)                                    # one SILT sample and ten LIMESTONE
    assert [(z.zone_id, z.lithology, z.n_samples, z.top, z.base) for z in s.zones] == [("Z1", "LIMESTONE", 11, 9.0, 14.0)]


@pytest.mark.xfail(strict=True, reason="the view assumes depth increasing: a LAS stored bottom up is refused where it "
                                       "is read (well.prepare.depth_order), so no question reaches a view like this")
def test_a_well_stored_bottom_up_has_the_same_zones_as_stored_top_down():
    v = view(DEPTH[::-1].copy(), lithology=CODES[::-1].copy())
    assert [(z.lithology, z.top, z.base) for z in v.zones] == [("SHALE", 2.5, 5.0), ("SAND", 5.5, 8.5),
                                                                ("LIMESTONE", 9.5, 14.0)]


def test_a_stretch_reaching_past_the_well_is_clipped_to_its_samples_and_keeps_what_was_asked():
    s = view(DEPTH, lithology=CODES).stretch(-5.0, 3.0)
    assert s.interval.top == 0.0 and s.interval.base == 3.0 and s.requested == (-5.0, 3.0)
    assert int(s.mask.sum()) == 7
    inside = view(DEPTH, lithology=CODES).stretch(1.0, 3.0)
    assert inside.requested is None and inside.interval.top == 1.0


def test_a_stretch_as_long_as_the_focus_reads_its_own_labels():
    """Focus 0-7.0 m (15 samples); a stretch 5.0-12.0 m (15 samples too) holds SHALE 5.0, SAND 5.5-8.5, SILT 9.0,
    LIMESTONE 9.5-12.0: its own samples' labels, not the focus's."""
    v = view(DEPTH, lithology=CODES, focus=(0.0, 7.0))
    s = v.stretch(5.0, 12.0)
    assert int(v.mask.sum()) == int(s.mask.sum()) == 15
    assert [str(x) for x in s.labels] == ["SHALE"] + ["SAND"] * 7 + ["SILT"] + ["LIMESTONE"] * 6
    assert _z(s) == [("Z1", "SAND", 5.5, 8.5, 7, 1, 7), ("Z2", "LIMESTONE", 9.5, 12.0, 6, 9, 14)]


def test_a_synthetic_feet_log_through_the_pipeline_measures_the_minimum_in_feet(tmp_path):
    """A LAS in feet, 0.5 ft samples from 1000 ft, interpreted by the real pipeline and reported in feet: the 2 m
    minimum is 6.5617 ft. SAND 7.5 ft (16 samples: a zone), SHALE 6 ft (13 samples: no zone), SAND 10 ft (21 samples:
    a zone), SHALE to the end."""
    from _synthetic import plausible_logs, write_las
    from _wells import Case, focus_view
    depth = 1000.0 + np.arange(100) * 0.5
    codes = runs_of([(1, 16), (7, 13), (1, 21), (7, 50)])
    logs = plausible_logs(depth, codes == 1)
    logs["LITHOLOGY"] = ("", codes)
    las = write_las(tmp_path / "synth-ft.las", depth, logs, unit="F", well="SYNTH-FT")
    v = focus_view(Case(str(las)))
    assert v.report_unit == "ft" and v.m_per_unit == pytest.approx(0.3048)
    assert [(z.lithology, z.top, z.base, z.n_samples) for z in v.zones[:2]] == [("SAND", 1000.0, 1007.5, 16),
                                                                               ("SAND", 1014.5, 1024.5, 21)]


def test_a_stretch_with_an_open_base_leaves_out_a_sample_on_it():
    """A unit whose base is the next unit's top (not a stated base) ends before it: 0-7.0 m open holds 0-6.5."""
    v = view(DEPTH, lithology=CODES)
    s = v.stretch(0.0, 7.0, closed=False)
    assert int(s.mask.sum()) == 14 and s.depth[-1] == 6.5 and not s.interval.closed
    assert int(v.stretch(0.0, 7.0).mask.sum()) == 15
