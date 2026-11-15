"""The settle prompt lists, for the model to act on as it sees fit, the measurements the READ call named that no claim
covers, the opened results no claim cites (asking whether each bears on what the question asks), and the claims still
graded hypothesis; the lists block nothing. No prompt asks the model to report then qualify, or to put each opened
section's result in a claim.

    PYTHONPATH=src:tests:tests/agent python -m pytest tests/agent/test_settle_lists.py -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness.agent import components as C  # noqa: E402
from petroharness.agent.claims import Claims  # noqa: E402
from petroharness.agent.loop import ASPECTS_RULE, bookkeeping, settle  # noqa: E402
from petroharness.llm import Usage  # noqa: E402

REMOVED = ("first say what the record flags or measures",            # report then qualify
           "For each opened analyzer section that bears on a point")  # settle: each opened section's result in a claim
MEANS = "the zone holds the formation's hydrocarbon-bearing rock"


def test_no_report_then_qualify_or_section_line():
    """No component holds the report-then-qualify sentence or a settle line that puts each opened section's result in
    a claim, and the writer's rules end with the aspects rule, then the reading rules."""
    from petroharness.agent import loop, writer
    texts = [s for cid in C.COMPONENTS for e in C.meta(cid).get("texts") or {} for s in C.strings(C.text(cid, e))]
    assert not [t for t in texts for r in REMOVED if r in t]
    assert "report_rule" not in C.meta("C9")["texts"] and not hasattr(loop, "REPORT_RULE")
    assert not hasattr(writer, "REPORT_RULE")


def _session(named=()):
    from test_b5_loop import _session as base
    s = base()
    s.reading = {"topics": list(s.topics), "asks": "", "readings": [], "named": list(named)}
    return s


@pytest.mark.data
def test_the_lists_render_and_the_settle_step_carries_both_texts():
    """BVW named and in no claim; a result opened and not cited; a claim still a hypothesis: three lines under
    BOOKKEEPING (the unused results asked whether each bears on the question), the aspects rule last after the settle
    text, and the settle step runs as usual."""
    from test_b5_loop import Script
    s = _session(named=["bulk volume water", "SW"])
    if "BVW" not in s.f.inv.curves:
        pytest.skip("no BVW here")
    cited, _ = s.ledger.open("stats", {"curves": ["SW"]})
    unused, _ = s.ledger.open("runs", {"condition": "NET_PAY"})
    s.points = ["Where is SW low?"]
    s.claims = Claims(s.points, s.ledger, s.map, s.task.question, s.f.view, (s.task.well,))
    s.claims.apply([{"op": "add", "point": 1, "text": "SW is lowest in the upper zones", "ev": [cited.id],
                     "grade": "moderate", "means": MEANS},
                    {"op": "add", "point": 1, "text": "Pay may sit in the upper zones", "grade": "hypothesis"}])
    book = bookkeeping(s)
    texts = C.text("C5", "settle_lists")
    assert book.startswith(texts["head"] + "\n")
    assert "- named in your reading, and in no claim or result a claim cites: bulk volume water (BVW)" in book
    assert "SW" not in book.split("named in your reading")[1].split("\n")[0].replace("(BVW)", "")   # SW is covered
    assert f"- opened, cited by no claim (does each bear on what the question asks?): {unused.id} {unused.call_text()}" in book
    assert f"{cited.id} " not in book.split("opened, cited by no claim")[1].split("\n")[0]
    assert "- still graded hypothesis: C2 (support, grade or drop each)" in book
    llm, trace = Script(['{"edits": [], "done": true}']), {}
    before = [(c.id, c.text, c.grade, list(c.flags)) for c in s.claims.claims.values()]
    settle(llm, s, Usage(), 4000, trace)
    user = llm.sent[0][1][-1]["content"]
    assert book in user and user.index("ALL RESULTS") < user.index("BOOKKEEPING") < user.index("FINAL STEP")
    assert user.rstrip().endswith(ASPECTS_RULE.rstrip()) and trace["settle"]["bookkeeping"] == book
    assert not [r for r in REMOVED if r in user]
    assert [(c.id, c.text, c.grade, list(c.flags)) for c in s.claims.claims.values()] == before   # nothing changed


@pytest.mark.data
def test_with_everything_covered_there_are_no_lists():
    s = _session(named=["SW"])
    item, _ = s.ledger.open("stats", {"curves": ["SW"]})
    s.points = ["Where is SW low?"]
    s.claims = Claims(s.points, s.ledger, s.map, s.task.question, s.f.view, (s.task.well,))
    s.claims.apply([{"op": "add", "point": 1, "text": "SW is lowest in the upper zones", "ev": [item.id],
                     "grade": "moderate", "means": MEANS}])
    assert bookkeeping(s) == ""


@pytest.mark.data
def test_the_writer_reads_no_removed_rule():
    from petroharness.agent.writer import prompt
    s = _session()
    item, _ = s.ledger.open("stats", {"curves": ["SW"]})
    s.points = ["Where is SW low?"]
    s.claims = Claims(s.points, s.ledger, s.map, s.task.question, s.f.view, (s.task.well,))
    s.claims.apply([{"op": "add", "point": 1, "text": "SW is lowest in the upper zones", "ev": [item.id],
                     "grade": "moderate", "means": MEANS}])
    system, _, _, _ = prompt(s)
    assert not [r for r in REMOVED if r in system]
