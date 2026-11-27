import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

# Tests that read wells need a data settings file (configs/data.local.yaml or PETROHARNESS_DATA) and are marked
# data. Without one, the harness raises its "no data settings" error; such a test, or a module that fails to load for
# that reason, is reported as skipped with the reason instead of as an error. A test not marked data, or an assertion
# whose message holds the words, fails as it is.
NO_DATA = "WHAT: no data settings"
REASON = "no data settings file (configs/data.local.yaml or PETROHARNESS_DATA)"


def _no_data(text) -> bool:
    return NO_DATA in str(text)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if (rep.failed and call.excinfo is not None and item.get_closest_marker("data") is not None
            and not isinstance(call.excinfo.value, AssertionError) and _no_data(call.excinfo.value)):
        rep.outcome = "skipped"
        rep.longrepr = (str(item.path), item.location[1] or 0, f"Skipped: {REASON}")


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    rep = outcome.get_result()
    if rep.failed and _no_data(rep.longrepr):
        rep.outcome = "skipped"
        rep.longrepr = (str(getattr(collector, "path", "")), 0, f"Skipped: {REASON}")


@pytest.fixture(autouse=True)
def _own_petroharness_home(tmp_path_factory, monkeypatch):
    """Each test has its own empty PetroHarness folder (petroharness.connect.home): no model chosen in the web UI,
    no key kept on this machine, reaches a test."""
    monkeypatch.setenv("PETROHARNESS_HOME", str(tmp_path_factory.mktemp("petroharness-home")))


@pytest.fixture
def plain_settings(tmp_path):
    """Data settings for a test that reads no well (a model client, the configuration's defaults): an empty LAS folder
    and nothing else, so it runs with no data settings file."""
    from petroharness.config import given_settings
    with given_settings({"data": {"las_dir": str(tmp_path)}, "eval": {}}):
        yield
