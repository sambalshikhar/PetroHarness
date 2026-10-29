"""Smoke test: the environment is wired correctly."""

import subprocess
import sys


def test_petrophys_3_is_the_imported_library():
    # Run from a neutral directory so no vendored petrophys can shadow the installed one.
    out = subprocess.run(
        [sys.executable, "-c", "import petrophys; print(petrophys.__version__)"],
        cwd="/tmp", capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip().startswith("3.")


def test_config_loads_with_defaults():
    from petroharness.config import HarnessConfig

    cfg = HarnessConfig.load()
    assert cfg.model.enable_thinking is False
    assert cfg.resources.policy_file.exists() and cfg.resources.rules_dir.is_dir()
