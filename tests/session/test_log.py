"""The session log's blobs (src/petroharness/session/log.py): a text kept under its SHA-256 is whole or not there.

    python -m pytest tests/session/test_log.py -q
"""
import hashlib
from pathlib import Path

from petroharness.session.log import SessionLog

TEXT = "Z1 590–873 m: porosity 0.21\n" * 200


def test_a_blob_write_cut_short_leaves_no_blob_and_the_next_keep_writes_it(tmp_path, monkeypatch):
    """A write stopped half way (a full disk, a killed process) leaves nothing under the blob's name, so the text is
    written whole the next time it is kept."""
    log = SessionLog(tmp_path)

    def cut(self, data, *a, **k):
        data = data.encode("utf-8") if isinstance(data, str) else data
        with open(self, "wb") as f:
            f.write(data[:100])
        raise OSError("the disk is full")
    with monkeypatch.context() as m:
        m.setattr(Path, "write_text", cut)
        m.setattr(Path, "write_bytes", cut)
        try:
            log.blob(TEXT)
        except OSError:
            pass
    sha = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
    assert not (tmp_path / "blobs" / sha).exists()
    assert log.blob(TEXT) == sha and log.read(sha) == TEXT


def test_a_blob_cut_short_before_is_written_again(tmp_path):
    """A blob left cut short (by a write before blobs were written whole) is written again when its text is kept."""
    log = SessionLog(tmp_path)
    sha = log.blob(TEXT)
    path = tmp_path / "blobs" / sha
    path.write_bytes(TEXT.encode("utf-8")[:100])
    assert log.blob(TEXT) == sha and log.read(sha) == TEXT
