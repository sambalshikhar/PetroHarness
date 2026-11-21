"""Record the public mini set: a short conversation on a sample well that ships with Petrophys, answered live by the
default model. Its tapes (every model request and reply) are kept in tests/gate/mini/<name>/, and tests/gate/
test_mini.py replays them with no model server and no private data: the same requests must be built, byte for byte,
and the same answers come out.

    PETROHARNESS_MODEL_URL=http://HOST:PORT/v1 python tests/gate/record_mini.py [NAME ...]
    python tests/gate/record_mini.py --replay [NAME ...]

Record again when a change is meant to alter what the model is sent or how a conversation runs (the same rule as the
golden tapes: tests/agent/record_golden.py). Run from a clean checkout of the commit the tapes are for.
--replay keeps the tapes and rewrites what each question must reproduce (its answer, the results it opened, the number
links, the steps, the figures) as this code gives it from the tapes, with no model server: for a change to what is
done with the model's replies, not to what the model is sent. It stops, and writes nothing, at the first request a
tape does not hold.
"""
import gzip
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MINI = Path(__file__).resolve().parent / "mini"
sys.path[:0] = [str(ROOT / "src")]

# name -> the sample well and its tops table (petrophys.sample), the formation, the questions in order. The Brent Group
# of GeoLink 30/6-5: a lithology log to zone by, and core to compare with.
SETS = {
    "brent": {"sample": "30/6-5", "tops": "formations_30_6-5.csv", "formation": "BRENT GP.",
              "questions": ["What are the porosity and water saturation of the Brent Group, and is any of it "
                            "hydrocarbon-bearing?",
                            "Which zone has the best reservoir quality, and how does the log permeability compare with "
                            "the core?",
                            "What water resistivity did the saturation use?"]},
}


def sample_files(spec: dict) -> tuple:
    """(the LAS file, the tops table) of a set, from the installed Petrophys."""
    import petrophys
    return Path(petrophys.sample(spec["sample"])), Path(petrophys.sample(spec["tops"]))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def expected(c, turn) -> dict:
    """What a replay must reproduce of one question (beside its requests)."""
    rec = c.turns[turn.number - 1]
    return {"status": turn.status, "answer_sha256": sha(turn.answer), "opened": rec["opened"], "cited": rec["cited"],
            "shows": rec["shows"], "basis": rec["basis"], "reply": (turn.trace.get("session") or {}).get("reply"),
            "figures": [[g["kind"], g["source"]] for g in turn.figures]}


def other_build(recorded: str) -> str:
    """Why a set recorded with Petrophys `recorded` (version@build) cannot be replayed here ("" when it can): another
    build of the same version may compute other curves, and so other prompts."""
    from petroharness.well.prepare import library_identity
    here = library_identity()
    if here == recorded:
        return ""
    if here.split("@")[0] != recorded.split("@")[0]:
        return f"recorded with Petrophys {recorded}; this is {here}: the curves, and so the prompts, differ"
    return f"recorded with another build of Petrophys {here.split('@')[0]} ({recorded}; this is {here}): its curves may differ"


def record(name: str) -> None:
    """Record a set live into a new folder; it replaces the set's folder only when every question was answered (a
    failed question leaves the earlier recording as it was)."""
    from petroharness.session import Conversation
    from petroharness.well.prepare import library_identity
    spec = SETS[name]
    las, tops = sample_files(spec)
    out, new = MINI / name, MINI / f".{name}.recording"
    shutil.rmtree(new, ignore_errors=True)
    (new / "turns").mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            c = Conversation.start(las, Path(tmp) / "session", formation=spec["formation"], tops=tops)
            turns = {}
            for q in spec["questions"]:
                turn = c.ask(q)
                n = f"{turn.number:02d}"
                print(f"{name} question {turn.number}: {turn.status}, {len(turn.trace.get('steps') or [])} steps",
                      flush=True)
                if turn.status.startswith("error"):
                    raise SystemExit(f"{name}: question {turn.number} failed ({turn.trace.get('error')}); the earlier "
                                     "recording is kept")
                with (turn.folder / "tape.jsonl").open("rb") as src, \
                        gzip.open(new / "turns" / f"{n}.tape.jsonl.gz", "wb") as dst:
                    shutil.copyfileobj(src, dst)
                (new / "turns" / f"{n}.answer.md").write_text(turn.answer, encoding="utf-8")
                turns[n] = expected(c, turn)
            (new / "set.json").write_text(json.dumps(
                {"name": name, **spec, "interval": c.p.used, "petrophys": library_identity(),
                 "setup": {"hash": c.setup.hash(), **c.setup.to_dict()}, "turns": turns}, indent=1), encoding="utf-8")
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise
    shutil.rmtree(out, ignore_errors=True)
    new.rename(out)
    print(f"{name}: kept in {out}")


def replay(name: str) -> None:
    from petroharness import tape
    from petroharness.llm import LLM
    from petroharness.session import Conversation
    from petroharness.well.prepare import library_identity
    out = MINI / name
    old = json.loads((out / "set.json").read_text(encoding="utf-8"))
    las, tops = sample_files(old)
    served = {}

    def factory(cfg):                                     # the harness's own client, answered from the tape
        llm = LLM(cfg)
        llm.client.chat.completions.create = served["replayer"]
        return llm
    with tempfile.TemporaryDirectory() as tmp:
        c = Conversation.start(las, Path(tmp) / "session", formation=old["formation"], tops=tops, llm_factory=factory)
        turns, answers = {}, {}
        for n, question in enumerate(old["questions"], 1):
            key = f"{n:02d}"
            served["replayer"] = tape.Replayer(tape.load(out / "turns" / f"{key}.tape.jsonl.gz"))
            turn = c.ask(question)
            figure_errors = (turn.trace.get("figures") or {}).get("errors") or []   # the figures step never fails a turn
            if turn.trace.get("error") or served["replayer"].left() or any("TapeMismatch" in e for e in figure_errors):
                why = turn.trace.get("error") or next((e for e in figure_errors if "TapeMismatch" in e), None) \
                    or "fewer calls than the tape"
                raise SystemExit(f"{name} question {n}: the code no longer builds the recorded requests ({why[:300]}); "
                                 "nothing written. Record it again live.")
            turns[key], answers[key] = expected(c, turn), turn.answer
            changed = "changed" if turn.answer != (out / "turns" / f"{key}.answer.md").read_text(encoding="utf-8") else "unchanged"
            print(f"{name} question {n}: {turn.status}, answer {changed}", flush=True)
        for key, text in answers.items():
            (out / "turns" / f"{key}.answer.md").write_text(text, encoding="utf-8")
        (out / "set.json").write_text(json.dumps(
            {**old, "interval": c.p.used, "petrophys": library_identity(),
             "setup": {"hash": c.setup.hash(), **c.setup.to_dict()}, "turns": turns}, indent=1), encoding="utf-8")
    print(f"{name}: expectations rewritten from the tapes in {out}")


if __name__ == "__main__":
    args = sys.argv[1:]
    run = replay if args[:1] == ["--replay"] else record
    for name in [a for a in args if a != "--replay"] or list(SETS):
        run(name)
