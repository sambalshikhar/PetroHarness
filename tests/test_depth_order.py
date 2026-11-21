"""A LAS whose depths are out of order (question suite L7): spliced logging runs leave the depth going back over the
overlap, which is then logged twice and counted twice in every result. The file is refused where a question first
reads it (the command, a conversation, the web UI), naming the line, the depths and the fix; a file that runs one way
(down or up) is read as it is.

    .venv/bin/python -m pytest tests/test_depth_order.py -q
"""
from pathlib import Path

import pytest

from petroharness.well.prepare import depth_order

HEAD = """~Version
VERS. 2.0 :
WRAP. NO :
~Well
STRT.M {first} :
STOP.M {last} :
STEP.M 0.5 :
NULL. -999.25 :
WELL. Test Well 1 :
~Curve
DEPT.M : depth
GR.API : gamma ray
~A
"""


def _las(tmp_path: Path, depths, name="w.las") -> Path:
    rows = "".join(f"{d} {50 + i}\n" for i, d in enumerate(depths))
    path = tmp_path / name
    path.write_text(HEAD.format(first=depths[0], last=depths[-1]) + rows)
    return path


def test_a_depth_going_back_is_said_with_its_line_depths_and_fix(tmp_path):
    las = _las(tmp_path, [1000.0, 1000.5, 1001.0, 1001.5, 1002.0, 1001.0, 1001.5, 1002.0, 1002.5])
    got = depth_order(las)
    first_data = HEAD.count("\n") + 1                    # the line of the first sample
    assert got.startswith(f"WHAT: the depth in w.las goes back at line {first_data + 5}, from 1002 to 1001 m: "
                          "1001-1002 m is logged twice (spliced runs or a repeated section)."), got
    assert "WHY: each depth is one sample" in got and "FIX: keep one run over the overlap" in got
    two = _las(tmp_path, [1000.0, 1001.0, 1000.5, 1001.5, 1001.0, 1002.0], "two.las")
    assert "(and 1 more place)" in depth_order(two)


def test_a_depth_given_twice_is_said(tmp_path):
    got = depth_order(_las(tmp_path, [1000.0, 1000.5, 1000.5, 1001.0]))
    first_data = HEAD.count("\n") + 1
    assert got.startswith(f"WHAT: the depth 1000.5 m is given twice in w.las, at line {first_data + 1} and line "
                          f"{first_data + 2}."), got


def test_a_file_that_runs_one_way_is_read_as_it_is(tmp_path):
    assert depth_order(_las(tmp_path, [1000.0, 1000.5, 1001.0, 1001.5])) == ""
    assert depth_order(_las(tmp_path, [1001.5, 1001.0, 1000.5, 1000.0], "up.las")) == ""     # logged bottom up
    assert depth_order(_las(tmp_path, [1000.0, 1000.5, -999.25, 1001.5], "null.las")) == ""  # a null depth is skipped


def test_a_depth_going_back_is_refused_where_a_question_reads_the_file(tmp_path):
    """The command and a conversation (ask.prepare) and the web UI (the LAS's header, the inputs before the queue)
    refuse it with the same message."""
    import petroharness.ask as A
    from petroharness.ui import adapter as U
    las = _las(tmp_path, [1000.0, 1000.5, 1001.0, 1001.5, 1002.0, 1001.0, 1001.5, 1002.0, 1002.5])
    said = depth_order(las)
    with pytest.raises(ValueError) as e:
        A.prepare(las, "k2-horizon-7b", top=1000.0, base=1002.0, cache=tmp_path / "cache")
    assert str(e.value) == said
    with pytest.raises(U.InputError) as e:
        U.las_info(str(las))
    assert str(e.value) == said
    with pytest.raises(U.InputError) as e:
        U.arguments({"las": str(las), "question": "What is the mean gamma ray?"})
    assert str(e.value) == said
    clean = _las(tmp_path, [1000.0, 1000.5, 1001.0, 1001.5], "clean.las")
    assert U.las_info(str(clean))["samples"] == 4
