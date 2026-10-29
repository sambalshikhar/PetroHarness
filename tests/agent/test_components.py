"""The harness's components (src/petroharness/agent/components.py, src/petroharness/agent/components/README.md): entries
load as their exact bytes, templates fill in one pass, versions follow the files, and every character of every model
call is attributed to one component (on golden replays: the calls aligned with the usage log, the spans covering each
message exactly).

    .venv/bin/python -m pytest tests/agent/test_components.py -q
"""
import gzip
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness.agent import components as C  # noqa: E402


def test_every_component_has_its_folder_and_every_entry_loads_exactly():
    assert set(C.COMPONENTS) == {f"C{i}" for i in range(1, 11)}
    for cid in C.COMPONENTS:
        m = C.meta(cid)
        assert m["id"] == cid and m["name"] == C.COMPONENTS[cid] and m["purpose"]
        for entry, name in (m.get("texts") or {}).items():
            raw = (C.folder(cid) / name).read_text(encoding="utf-8")
            assert C.text(cid, entry) == (json.loads(raw) if name.endswith(".json") else raw)


def test_no_text_is_in_two_components():
    seen = {}
    for cid in C.COMPONENTS:
        for entry in C.meta(cid).get("texts") or {}:
            for s in C.strings(C.text(cid, entry)):
                if len(s) >= C.MIN_MATCH:
                    assert seen.get(s, cid) == cid, (s[:60], seen.get(s), cid)
                    seen[s] = cid


def test_the_former_constants_are_the_entries():
    from petroharness.agent import loop, writer
    assert loop.STEP1 == C.text("C5", "step1") and loop.SETTLE_V9 == C.text("C10", "settle_v9")
    assert writer.RULES == C.text("C9", "rules") and writer.NO_REVERSAL_RULE == C.text("C10", "no_reversal_rule")


@pytest.mark.parametrize("template, values, want", [
    ("a {x} b", {"x": "1"}, "a 1 b"),
    ("a {x} b {y}", {"x": "{y}"}, "a {y} b {y}"),                # a value is never read as a slot
    ("{X} and {x}", {"X": "up"}, "up and {x}"),                  # a slot without a value stays as written
    ('{"points": [...]} - {n} questions', {"n": 3}, '{"points": [...]} - 3 questions'),   # JSON braces are not slots
])
def test_fill_is_one_pass(template, values, want):
    assert C.fill_text(template, **values) == want


def test_a_version_follows_its_files(tmp_path, monkeypatch):
    copy = tmp_path / "components"
    shutil.copytree(C.HERE, copy)
    monkeypatch.setattr(C, "HERE", copy)
    for f in (C.meta, C.text, C.version):
        f.cache_clear()
    try:
        before = C.versions()
        p = C.folder("C10") / C.meta("C10")["texts"]["settle_v9"]
        p.write_text(p.read_text() + " ")
        C.version.cache_clear()
        after = C.versions()
        assert after["C10"] != before["C10"] and {k: v for k, v in after.items() if k != "C10"} == \
            {k: v for k, v in before.items() if k != "C10"}
    finally:
        for f in (C.meta, C.text, C.version):
            f.cache_clear()


def _covers(spans, n):
    assert spans and spans[0][2] == 0 and spans[-1][3] == n
    assert all(a[3] == b[2] for a, b in zip(spans, spans[1:]))                  # contiguous, no gap or overlap
    assert all(s[0] in C.COMPONENTS and s[1] == C.version(s[0]) for s in spans)


def test_attribution_covers_the_message_and_finds_the_entries():
    rule, step = C.text("C10", "settle_v9"), C.text("C5", "settle")
    msg = "QUESTION:\nWhat is the pay?\n\n" + step + rule + "\n\nsome data 1.234"
    spans = C.attribute(msg, "C5")
    _covers(spans, len(msg))
    i = msg.index(rule.strip()[:40])
    assert any(s[0] == "C10" and s[2] <= i < s[3] for s in spans)
    assert all(s[0] in ("C5", "C10") for s in spans)


@pytest.mark.parametrize("stage, n, want", [
    ("read", 2, ["C1", "C5"]), ("read_retry", 2, ["C1", "C5"]), ("step_1", 2, ["C1", "C5"]), ("step_7_retry", 2, ["C1", "C5"]), ("step_3_fix", 1, ["C2"]),
    ("step_1_points", 4, ["C1", "C5", "C3", "C5"]), ("settle", 2, ["C1", "C5"]),
    ("writer_again", 2, ["C9", "C9"]), ("repair_1_again", 4, ["C9", "C9", "C3", "C2"]),
])
def test_owners_by_stage(stage, n, want):
    assert C.owners(stage, n) == want


GOLDEN = ROOT / "tests" / "golden"
DATA = Path(os.environ["WELLLOGBENCH"]) if os.environ.get("WELLLOGBENCH") else None   # the folder of <dataset>.yaml data configs


@pytest.mark.data
@pytest.mark.skipif(DATA is None, reason="WELLLOGBENCH is not set (the folder of the datasets' data configs)")
@pytest.mark.skipif(not GOLDEN.exists(), reason="no golden tapes in this checkout")
@pytest.mark.parametrize("ds", ["geolink", "costa", "danish"])
def test_every_call_of_a_golden_replay_is_attributed_whole(ds, monkeypatch):
    from petroharness import tape
    from petroharness.config import HarnessConfig
    from petroharness.tasks import load_tasks
    from petroharness.llm import LLM
    monkeypatch.setenv("PETROHARNESS_DATA", str(DATA / f"{ds}.yaml"))
    monkeypatch.setenv("PETROHARNESS_SET", "")
    from petroharness.agent import graph
    sel = json.loads((GOLDEN / ds / "selection.json").read_text())
    q = sel["questions"][0]
    cfg = HarnessConfig()
    tasks, _ = load_tasks(cfg.eval.questions, cfg.data.las_dir)
    task = next(t for t in tasks if t.task_id == q["task_id"])
    rec = [json.loads(ln) for ln in gzip.open(GOLDEN / ds / f"{q['task_id']}.tape.jsonl.gz", "rt")]

    class Taped(LLM):
        def __init__(self, c):
            super().__init__(c)
            tape.replay(self, rec)

    got = graph.answer(task, sel["model"], 1, graph.MAX_STEPS, "open", "profile", llm_factory=Taped)
    tr = got["trace"]
    assert not tr.get("error"), tr.get("error")
    calls, usage = tr["calls"], tr["usage"]
    assert [c["stage"] for c in calls] == [u["stage"] for u in usage]          # one record per call, in order
    assert tr["components"] == C.versions()
    for c, r in zip(calls, rec):
        msgs = r["request"]["messages"]
        assert len(c["messages"]) == len(msgs)
        for att, m in zip(c["messages"], msgs):
            _covers(att["segments"], len(m.get("content") or ""))
    first_user = calls[0]["messages"][1]["segments"]
    assert {"C5", "C7"} <= {s[0] for s in first_user}                         # the READ call: its frame and the map
