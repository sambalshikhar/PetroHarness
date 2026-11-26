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


def test_config_loads_with_defaults(plain_settings):
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



def test_one_release_is_one_build_on_every_python_and_in_every_environment():
    """An installed release is identified by its own files: the bytecode the installer compiles (named by the Python
    version), the scripts it writes beside the environment's Python, the installer's bookkeeping and the order of the
    lines do not change it (petrophys 3.0.0 from PyPI was two builds in two environments, 1.2.0)."""
    from petroharness.well.prepare import _own_files
    own = ["pkg/__init__.py,sha256=AAA,10", "pkg/data/a.las,sha256=BBB,20", "pkg-3.0.0.dist-info/METADATA,sha256=CCC,30",
           "pkg-3.0.0.dist-info/licenses/LICENSE,sha256=DDD,40"]
    py310 = own + ["pkg/__pycache__/__init__.cpython-310.pyc,,", "../../../bin/pkg-cli,sha256=EEE,278",
                   "pkg-3.0.0.dist-info/INSTALLER,sha256=FFF,4", "pkg-3.0.0.dist-info/RECORD,,"]
    py312 = list(reversed(own)) + ["pkg/__pycache__/__init__.cpython-312.pyc,,", "../../../bin/pkg-cli,sha256=GGG,337",
                                   "pkg-3.0.0.dist-info/REQUESTED,sha256=HHH,0", "pkg-3.0.0.dist-info/INSTALLER,sha256=III,3",
                                   "pkg-3.0.0.dist-info/RECORD,,"]
    assert _own_files("\n".join(py310)) == _own_files("\n".join(py312)) == sorted(own)
    assert _own_files("\n".join(own[:-1] + ["pkg-3.0.0.dist-info/licenses/LICENSE,sha256=XXX,40"])) != sorted(own)
