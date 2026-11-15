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


def test_the_petrophys_build_named_is_petrophys_own_not_the_enclosing_repository():
    """An installed petrophys in a virtual environment inside this repository must not be given this repository's
    commit (git answers for any folder inside a repository)."""
    import subprocess
    from pathlib import Path
    import petrophys
    from petroharness.well.prepare import _installed_build, library_identity
    version, build = library_identity().split("@", 1)
    assert version == getattr(petrophys, "__version__", "?") and build
    root = Path(__file__).resolve().parents[1]
    here = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    src = Path(petrophys.__file__).resolve().parent
    tracked = subprocess.run(["git", "-C", str(src), "ls-files", "--error-unmatch", "__init__.py"],
                             capture_output=True, text=True).returncode == 0
    if not tracked:                                   # an installed package: its own build, never this repository's
        assert build.split("+")[0] != here and build == (_installed_build("petrophys") or "no-git")
    assert _installed_build("no-such-distribution-here") == ""

