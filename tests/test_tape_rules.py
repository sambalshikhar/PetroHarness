"""Two rules of the tape comparison (src/petroharness/tape.py compare_run): a switch the code does not have passes only
when it was recorded at the value fixed in code; the per-call attribution key `calls` is skipped when only the replay
has it. Everything else is compared."""
import copy

from petroharness.tape import compare_run


def run(options, **extra):
    trace = {"options": dict(options), "steps": [{"prompt_chars": 10}], "usage": [{"stage": "step_1", "seconds": 1.0}]}
    trace.update(extra)
    return {"answer": "A", "status": "ok", "trace": trace}


REC = run({"notes": True, "native": False, "k12": False})


def test_identical_runs_pass():
    assert compare_run(copy.deepcopy(REC), REC) == ""


def test_a_removed_switch_at_its_fixed_value_passes():
    got = run({"k12": False})
    assert compare_run(got, REC, fixed={"notes": True, "native": False}) == ""


def test_a_removed_switch_recorded_at_another_value_fails():
    got = run({"k12": False})
    msg = compare_run(got, REC, fixed={"notes": False, "native": False})
    assert "notes=True" in msg and "fixed False" in msg


def test_a_removed_switch_without_a_fixed_value_fails():
    got = run({"k12": False, "native": False})
    assert "notes" in compare_run(got, REC, fixed={})
    assert "notes" in compare_run(got, REC)


def test_a_new_switch_must_be_off():
    got = run({"notes": True, "native": False, "k12": False, "contract": "candidates"})
    assert "new switches on" in compare_run(got, REC)
    got = run({"notes": True, "native": False, "k12": False, "contract": ""})
    assert compare_run(got, REC) == ""


def test_calls_only_in_the_replay_is_skipped_but_compared_when_both_have_it():
    calls = [{"stage": "step_1", "messages": [{"role": "user", "segments": [["C5", "abc", 0, 10]]}]}]
    assert compare_run(run(REC["trace"]["options"], calls=calls), REC) == ""
    rec2 = run(REC["trace"]["options"], calls=calls)
    other = copy.deepcopy(calls)
    other[0]["messages"][0]["segments"][0][1] = "def"
    assert "calls" in compare_run(run(REC["trace"]["options"], calls=other), rec2)


def test_other_new_keys_and_changes_still_fail():
    assert "only in the replay" in compare_run(run(REC["trace"]["options"], extra_key=1), REC)
    got = copy.deepcopy(REC)
    got["trace"]["steps"][0]["prompt_chars"] = 11
    assert "prompt_chars" in compare_run(got, REC)


def test_the_behaviour_verdict_leaves_the_version_stamps_out():
    calls = [{"stage": "step_1", "messages": [{"role": "user", "segments": [["C5", "abc", 0, 10]]}]}]
    rec = run(REC["trace"]["options"], calls=calls, components={"C5": "abc"})
    moved = run(REC["trace"]["options"], calls=[{"stage": "step_1", "messages": [{"role": "user", "segments": [["C5", "xyz", 0, 10]]}]}],
                components={"C5": "xyz"})
    assert "components" in compare_run(moved, rec) or "calls" in compare_run(moved, rec)      # the stamps differ
    assert compare_run(moved, rec, versions=False) == ""                                       # the behaviour does not
    other = run(REC["trace"]["options"], calls=[{"stage": "step_1", "messages": [{"role": "user", "segments": [["C7", "abc", 0, 10]]}]}],
                components={"C5": "abc"})
    assert "calls" in compare_run(other, rec, versions=False)                                  # another owner is behaviour
