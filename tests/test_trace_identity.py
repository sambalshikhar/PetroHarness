"""What a trace says about the harness and the model: the package's version, and the model's name as people read it,
never the registry key or the endpoints it is served from (traces are shared).

    .venv/bin/python -m pytest tests/test_trace_identity.py -q
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
from petroharness import __version__  # noqa: E402
from petroharness.agent import graph  # noqa: E402
from petroharness.models import DEFAULT_CARD, card_settings, register  # noqa: E402


def test_the_trace_names_the_package_version():
    assert graph.HARNESS == f"petroharness {__version__}"


def test_the_default_model_is_named_by_its_card_label():
    assert graph.public_model("k2-horizon-7b") == card_settings(DEFAULT_CARD).get("label")


def test_a_model_served_elsewhere_is_named_without_its_endpoints():
    key = register(["http://10.0.0.7:8000/v1", "http://10.0.0.8:8000/v1"], "generic", "my-org/served-model")
    assert "@" in key and "10.0.0.7" in key                  # the registry key carries the endpoints
    name = graph.public_model(key)
    assert name == "my-org/served-model" and "http" not in name and "10.0.0" not in name


def test_an_empty_answer_is_an_error_not_ok():
    assert graph.answer_status("", [{"unsupported": []}]) == graph.EMPTY_ANSWER
    assert graph.answer_status("  \n", [{"unsupported": []}]).startswith("error")
    assert graph.answer_status("Z2 is best.", [{"unsupported": []}]) == "ok"
    assert graph.answer_status("Z2 is 9.99.", [{"unsupported": ["9.99"]}]) == "unresolved_numbers"
