"""The cache of interpreted wells: a cached well is read only from a file this user wrote (a pickle placed by someone
else could run their code), and questions on one well in several threads interpret it once, the others waiting for
the cache.

    .venv/bin/python -m pytest tests/test_well_cache.py -q
"""
import threading
import time

from petroharness.well import prepare as P


def test_a_cache_file_is_read_only_when_this_user_wrote_it(tmp_path, monkeypatch):
    f = tmp_path / "well.pkl"
    f.write_bytes(b"not a pickle")
    assert P._owned(f)
    uid = f.stat().st_uid
    monkeypatch.setattr(P.os, "getuid", lambda: uid + 1)       # the file is someone else's
    assert not P._owned(f)


def test_one_well_is_prepared_once_at_a_time_per_cache_folder(tmp_path, monkeypatch):
    inside, most = [0], [0]
    guard = threading.Lock()

    def slow(las, policy, cache_dir, *a, **k):
        with guard:
            inside[0] += 1
            most[0] = max(most[0], inside[0])
        time.sleep(0.05)
        with guard:
            inside[0] -= 1
        return las

    monkeypatch.setattr(P, "_prepare_well", slow)
    las = tmp_path / "w.las"
    las.write_text("x")
    threads = [threading.Thread(target=P.prepare_well, args=(las, {}, tmp_path / "cache")) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert most[0] == 1                                          # one at a time on one well
    other = tmp_path / "v.las"
    other.write_text("y")
    threads = [threading.Thread(target=P.prepare_well, args=(x, {}, tmp_path / "cache")) for x in (las, other)]
    most[0] = 0
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert most[0] == 2                                          # two wells at once
