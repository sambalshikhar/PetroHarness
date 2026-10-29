import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

# Tests that read wells need a data settings file (configs/data.local.yaml or PETROHARNESS_DATA). Without one, the
# harness raises its "no data settings" error; such a test, or a module that fails to load for that reason, is
# reported as skipped with the reason instead of as an error.
NO_DATA = "WHAT: no data settings"
REASON = "no data settings file (configs/data.local.yaml or PETROHARNESS_DATA)"


def _no_data(text) -> bool:
    return NO_DATA in str(text)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.failed and call.excinfo is not None and _no_data(call.excinfo.value):
        rep.outcome = "skipped"
        rep.longrepr = (str(item.path), item.location[1] or 0, f"Skipped: {REASON}")


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    rep = outcome.get_result()
    if rep.failed and _no_data(rep.longrepr):
        rep.outcome = "skipped"
        rep.longrepr = (str(getattr(collector, "path", "")), 0, f"Skipped: {REASON}")
