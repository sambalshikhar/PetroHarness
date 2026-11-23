"""The switch framework (petroharness.options): every switch is off by default, and a name that is not a switch
raises."""
import pytest

from petroharness import options


def test_every_switch_is_off_by_default_and_an_empty_setting_parses():
    assert options.parse("") == options.Options()
    assert options.as_dict() and not any(options.as_dict().values())     # every switch is off
    assert options.parse("tight_numbers=true").tight_numbers is True
    assert options.parse("cell_thickness=true").cell_thickness is True


@pytest.mark.parametrize("text", ["contract=named", "v9_views=true", "anything",
                                  "zone_order=true", "see_first=true", "stop_check=true",      # once switches:
                                  "writer_points=true", "writer_fresh=true", "fresh_doubts=true",    # the code's
                                  "new_budget=true", "writer_decide=true", "writer_parts=true",      # behaviour now,
                                  "depth=true", "one_runs=true", "pay_labels=true",                  # or removed
                                  "kind_rule=true", "verb_bases=true", "analyzer_notes=true",
                                  "strip_reasoning=true", "writer_budget=true", "check_prompt=true",
                                  "own_results=true", "tops_once=true"])
def test_a_name_that_is_not_a_switch_raises(text):
    with pytest.raises(ValueError, match="no option"):
        options.parse(text)


def test_use_takes_no_name_either():
    with pytest.raises(TypeError), options.use(zone_order=True):
        pass
    with pytest.raises(TypeError), options.use(strip_reasoning=True):     # a switch once, the code's behaviour now
        pass
    with options.use() as o:                                   # none named: the defaults
        assert o == options.Options() and options.get() == o


def test_a_gate_on_no_switch_raises():
    from petroharness.agent.direction import switch_on
    with pytest.raises(KeyError):
        switch_on("v9_views")
