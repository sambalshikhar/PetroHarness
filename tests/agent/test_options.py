"""The switch framework (petroharness.agent.options): no switches; a name that is not a switch raises (the six switches
of the measured build are the code since the 3.5.6 lock, and the others it ran without are removed)."""
import pytest

from petroharness.agent import options


def test_no_switch_is_under_test_and_an_empty_setting_parses():
    assert options.as_dict() == {}                             # depth, measured in 4.0, is the code (direct=False is a setting)
    assert options.parse("") == options.Options()


@pytest.mark.parametrize("text", ["contract=named", "v9_views=true", "anything",
                                  "zone_order=true", "see_first=true", "stop_check=true",      # built in at the lock
                                  "writer_points=true", "writer_fresh=true", "fresh_doubts=true",
                                  "new_budget=true", "writer_decide=true", "writer_parts=true",   # removed at the lock
                                  "depth=true"])                                                  # the code since 4.0
def test_a_name_that_is_not_a_switch_raises(text):
    with pytest.raises(ValueError, match="no option"):
        options.parse(text)


def test_use_takes_no_name_either():
    with pytest.raises(TypeError), options.use(zone_order=True):
        pass
    with options.use() as o:                                   # no switch: the options in force are the empty set
        assert o == options.Options() and options.get() == o


def test_a_gate_on_no_switch_raises():
    from petroharness.agent.direction import switch_on
    with pytest.raises(KeyError):
        switch_on("v9_views")
