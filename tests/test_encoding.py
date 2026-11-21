"""Text the harness reads and writes is UTF-8 whatever the machine's locale: the session log and its blobs (named by
the SHA-256 of their UTF-8 bytes), answers, traces, settings and the packaged texts. A depth range is written with an
en dash ("590–873 m"), which a locale's default encoding (cp1252, ASCII) may not hold.

    .venv/bin/python -m pytest tests/test_encoding.py -q
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALL = re.compile(r"\.(read_text|write_text)\(")


def _calls_without_encoding(text: str) -> list:
    """The read_text/write_text calls in a source text that name no encoding (importlib.metadata's dist.read_text,
    which reads a distribution's file by name, aside)."""
    out = []
    for m in CALL.finditer(text):
        if text[max(0, m.start() - 4):m.start()] == "dist":
            continue
        depth, j = 1, m.end()
        while depth and j < len(text):
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
        if "encoding=" not in text[m.end():j]:
            out.append(text[:m.start()].count("\n") + 1)
    return out


def test_every_text_read_and_write_names_utf8():
    hits = []
    for p in sorted((ROOT / "src" / "petroharness").rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        hits += [f"{p.relative_to(ROOT)}:{n}" for n in _calls_without_encoding(text)]
        hits += [f"{p.relative_to(ROOT)}:{text[:m.start()].count(chr(10)) + 1}"
                 for m in re.finditer(r"\bopen\([^)]*\"(?:a|w|r|rt|wt|at)\"\)", text)]
    assert not hits, "text I/O without encoding=\"utf-8\": " + ", ".join(hits)


def test_the_session_log_keeps_text_as_utf8_under_any_locale(tmp_path):
    """Under the C locale with UTF-8 mode off (the locale's encoding is ASCII), a blob with an en dash is kept and
    read back, its bytes the UTF-8 its name hashes."""
    text = "Z1 590–873 m: porosity 0.21"
    t = ascii(text)                                    # the command line itself is ASCII under this locale
    code = ("import sys; from petroharness.session.log import SessionLog; "
            f"log = SessionLog(sys.argv[1]); sha = log.blob({t}); "
            f"assert log.read(sha) == {t}; log.append('note', 1, text={t}); print(sha)")
    env = {**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONPATH": str(ROOT / "src")}
    got = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, env=env,
                         timeout=120)
    assert got.returncode == 0, got.stderr[-1500:]
    sha = got.stdout.strip()
    assert sha == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert (tmp_path / "blobs" / sha).read_bytes() == text.encode("utf-8")
