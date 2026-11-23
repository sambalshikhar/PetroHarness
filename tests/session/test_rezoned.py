"""EARLIER IN THIS SESSION after a change that cut the zones anew: the zones as they were, each with where its depths
lie in the zones now (petroharness.session.earlier.rezoned). Built from the two zonings alone."""
from petroharness.session import earlier as E


def z(i, lith, top, base):
    return {"zone": f"Z{i}", "lithology": lith, "top": top, "base": base}


THEN = [z(1, "SHALE", 10.0, 21.5), z(2, "SAND", 31.5, 48.5), z(3, "SAND", 50.0, 59.5), z(4, "SHALE", 60.0, 68.0)]
NOW = [z(1, "LIME", -7.5, 4.5), z(2, "LIME", 31.5, 51.0), z(3, "NONE", 60.0, 68.0)]


def test_each_zone_of_then_says_where_its_depths_lie_now():
    lines = E.rezoned(THEN, NOW, "ft", 0.5).splitlines()
    assert lines[0].startswith("The zones were cut anew: 4 before, 3 now.")
    assert "names the zone as it was then, and the same id may name another stretch now" in lines[0]
    assert lines[1:] == [
        "  then Z1 SHALE 10-21.5 ft: now outside any zone",
        "  then Z2 SAND 31.5-48.5 ft: now inside Z2 LIME (31.5-51 ft)",
        "  then Z3 SAND 50-59.5 ft: now Z2 LIME over 50-51 ft; the rest outside any zone",
        "  then Z4 SHALE 60-68 ft: now Z3 NONE (the same depths)"]


def test_a_zone_split_between_touching_zones_is_whole():
    """Two zones one sample step apart leave no sample between them: nothing of the old zone is outside."""
    now = [z(1, "A", 31.5, 40.0), z(2, "B", 40.5, 48.5)]
    line = E.rezoned([THEN[1]], now, "ft", 0.5).splitlines()[1]
    assert line == "  then Z2 SAND 31.5-48.5 ft: now Z1 A over 31.5-40 ft, Z2 B over 40.5-48.5 ft"
    apart = [z(1, "A", 31.5, 38.0), z(2, "B", 40.5, 48.5)]                # two steps and more between them
    assert E.rezoned([THEN[1]], apart, "ft", 0.5).splitlines()[1].endswith("; the rest outside any zone")
    assert E.rezoned([THEN[1]], apart, "", 0.5).splitlines()[1].startswith("  then Z2 SAND 31.5-48.5: now ")   # no unit


def test_many_zones_are_listed_to_a_limit_and_the_rest_counted():
    then = [z(i, "S", 10.0 * i, 10.0 * i + 5) for i in range(1, E.ZONES_THEN + 8)]
    lines = E.rezoned(then, then[:3], "m", 0.5).splitlines()
    assert len(lines) == 1 + E.ZONES_THEN + 1
    assert lines[-1].startswith("  (7 more zones of then, to ") and "states each zone's depths" in lines[-1]


def test_the_change_line_carries_it_only_when_the_zones_were_cut_anew():
    turns = [{"turn": 1, "question": "q", "opened": ["E1", "E2"], "status": "ok"}]
    change = {"turn": 2, "by": "user", "changes": [{"key": "m", "from": None, "to": 1.8}]}
    plain = E.changed(change, turns)
    assert plain.endswith("read again, a result says so.") and "cut anew" not in plain
    cut = E.changed({**change, "then": THEN, "now": NOW, "unit": "ft", "step": 0.5}, turns)
    assert cut.startswith(plain + "\nThe zones were cut anew: 4 before, 3 now.")
    zones = E.changed({"turn": 2, "by": "user", "kind": "zones", "zones": "/x/layers.csv", "then": THEN, "now": NOW,
                       "unit": "ft", "step": 0.5}, turns)
    assert zones.startswith("Zones changed before question 2 (by the user): your zones from layers.csv")
    assert "\nThe zones were cut anew: 4 before, 3 now." in zones
