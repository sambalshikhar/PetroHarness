"""The switch framework (petroharness.agent.options): no switches; a name that is not a switch raises."""
import pytest

from petroharness.agent import options


def test_no_switches_and_an_empty_setting_parses():
    assert options.as_dict() == {}
    assert options.parse("") == options.Options()


@pytest.mark.parametrize("text", ["contract=named", "v9_views=true", "anything"])
def test_a_name_that_is_not_a_switch_raises(text):
    with pytest.raises(ValueError, match="no option"):
        options.parse(text)


def test_a_gate_on_no_switch_raises():
    from petroharness.agent.direction import switch_on
    with pytest.raises(KeyError):
        switch_on("v9_views")
