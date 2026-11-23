"""Every key the code writes into a question's trace is documented in docs/reference/RECORDS.md (section 5).

    .venv/bin/python -m pytest tests/test_records_doc.py -q
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITES = (re.compile(r'\btrace\[\s*"([a-z_0-9]+)"\s*\]\s*(?:=|\+=)'),       # trace["key"] = ...
          re.compile(r'\btrace\.setdefault\(\s*"([a-z_0-9]+)"'))           # trace.setdefault("key", ...)


def _written() -> dict:
    keys = {}
    for path in sorted((ROOT / "src" / "petroharness").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for rx in WRITES:
            for key in rx.findall(text):
                keys.setdefault(key, path.relative_to(ROOT).as_posix())
        for call in re.findall(r"\btrace\.update\(([^)]*)\)", text):
            for key in re.findall(r"\b([a-z_0-9]+)=", call):
                keys.setdefault(key, path.relative_to(ROOT).as_posix())
    return keys


def _documented() -> set:
    text = (ROOT / "docs" / "reference" / "RECORDS.md").read_text(encoding="utf-8")
    out = set()
    for first in re.findall(r"^\| ([^|]+) \|", text, re.M):          # a row's first cell: `key` or `key`, `key`
        out |= set(re.findall(r"`([a-z_0-9]+)`", first))
    return out


def test_every_trace_key_the_code_writes_is_documented():
    written, documented = _written(), _documented()
    assert len(written) > 30                                          # the scan finds the writes
    missing = {k: where for k, where in written.items() if k not in documented}
    assert not missing, (f"{missing}: WHY: a trace key the reader cannot look up. FIX: add a row for it to "
                         "docs/reference/RECORDS.md, section 5.")
