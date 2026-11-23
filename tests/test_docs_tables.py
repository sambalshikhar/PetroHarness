"""The reference pages agree with the code: their generated tables (tests/docs_tables.py: the tool reference's master
table, the Petrophys counts, the settings sheet's groups, the prompt components) are what the code gives, and every
file a page names exists.

    .venv/bin/python -m pytest tests/test_docs_tables.py -q
"""
import re
from pathlib import Path

import docs_tables

ROOT = Path(__file__).resolve().parents[1]
PAGES = [p for p in ROOT.glob("docs/**/*.md") if "designs" not in p.parts and not p.name.startswith("LOCK_")] \
    + [ROOT / "README.md", ROOT / "CONTRIBUTING.md"]


def test_every_generated_table_is_what_the_code_gives():
    assert not docs_tables.stale(), (f"{docs_tables.stale()}: WHY: a table the code generates has drifted from it. "
                                     "FIX: .venv/bin/python tests/docs_tables.py --write")


def test_every_file_a_page_names_exists():
    """A test file by its name, a repository path (tests/..., src/petroharness/...) or a package path (agent/map.py)."""
    tests = {p.name for p in (ROOT / "tests").rglob("*.py")}
    missing = []
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        for m in re.finditer(r"`((?:tests|src/petroharness)/[\w/.-]+\.py|test_\w+\.py)(?:::\w+)?`", text):
            ref = m.group(1)
            if not ((ROOT / ref).exists() if "/" in ref else ref in tests):
                missing.append((page.name, ref))
        for m in re.finditer(r"`((?:agent|record|well|session|ui|core|evidence|tools|basis)/[\w/]+\.py)`", text):
            if not (ROOT / "src" / "petroharness" / m.group(1)).exists():
                missing.append((page.name, m.group(1)))
    assert not missing, missing
