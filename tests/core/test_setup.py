"""The setup record (petroharness.core.setup): what a run is made of, with one hash; printed by `petroharness setup`;
logged once per conversation and named in every trace and audit trail.

    .venv/bin/python -m pytest tests/core -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tests" / "agent"), str(ROOT / "tests" / "session")]
from petroharness.config import given_settings  # noqa: E402
from petroharness.core import setup as S  # noqa: E402


def one(**kw):
    cfg, given = S.config_for()
    with given_settings(given):
        return cfg, S.of(cfg, **kw)


def test_a_setup_names_every_part_and_hashes_the_same_twice():
    cfg, s = one()
    d = s.to_dict()
    assert set(d) == {"harness", "commit", "petrophys", "components", "functions", "skills", "model", "card", "data",
                      "policy", "writer", "fmt", "max_steps", "mode", "depth"}
    assert d["harness"] and "@" in d["petrophys"] and len(d["functions"]) == 12 and len(d["card"]) == 12
    assert set(d["components"]) >= {"C1", "C5", "C9"} and d["skills"]["library"] and d["max_steps"] > 0
    assert len(s.hash()) == 12 and s.hash() == one()[1].hash()
    json.dumps(d)                                                    # plain data: it goes in the session log


def test_what_answers_changes_the_hash_and_where_the_model_is_reached_does_not():
    cfg, s = one()
    _, other = one(writer="")
    assert other.hash() != s.hash() and S.differences(s.to_dict(), other.to_dict()) == ["writer"]
    moved = cfg.model_copy(deep=True)
    moved.model.base_url, moved.model.timeout_s = "http://elsewhere:9/v1", 5.0
    cfg2, given = S.config_for()
    with given_settings(given):
        assert S.of(moved).hash() == s.hash()                        # an endpoint or a timeout is not what answers
        warmer = cfg.model_copy(deep=True)
        warmer.model.temperature = cfg.model.temperature + 0.3
        hot = S.of(warmer)
    assert hot.hash() != s.hash() and S.differences(s.to_dict(), hot.to_dict()) == ["card"]
    a, b = s.to_dict(), s.to_dict()
    b["components"] = {**b["components"], "C9": "changed"}
    assert S.differences(a, b) == ["components.C9"] and S.differences(a, a) == []


def test_the_command_prints_the_record_and_its_hash(capsys):
    assert S.main([]) == 0
    out = capsys.readouterr().out
    _, s = one()
    assert out.startswith(f"setup {s.hash()}\n") and "  components:\n    C1: " in out and "  petrophys: " in out
    assert S.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["hash"] == s.hash()
    assert S.main(["--model-card", "no-such-card"]) == 2


def test_the_command_reads_the_settings_file_named_in_the_environment(tmp_path, monkeypatch, capsys):
    """--settings, else PETROHARNESS_DATA, else none (the help's promise); errors on stderr, nothing on stdout."""
    settings = tmp_path / "settings.yaml"
    settings.write_text("data:\n  zone_layout: formation\n")
    monkeypatch.delenv("PETROHARNESS_DATA", raising=False)

    def data(*argv):
        assert S.main(["--json", *argv]) == 0
        return json.loads(capsys.readouterr().out)["data"]

    bare, named = data(), data("--settings", str(settings))
    monkeypatch.setenv("PETROHARNESS_DATA", str(settings))
    assert named != bare and data() == named
    monkeypatch.setenv("PETROHARNESS_DATA", str(tmp_path / "missing.yaml"))
    assert S.main([]) == 2
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("petroharness setup: WHAT: no data settings file")
    assert S.main(["--formation", "A"]) == 2 and "--las" in capsys.readouterr().err
    with pytest.raises(SystemExit):                               # an endpoint is not part of a setup
        S.main(["--model-url", "http://x/v1"])


@pytest.mark.data
def test_the_command_given_the_well_prints_the_setup_its_conversation_logs(tmp_path, monkeypatch, capsys):
    from test_adopt import LAS, Q1, WINDOW, Model
    from petroharness.session import Conversation
    if not LAS.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS"):
        monkeypatch.delenv(key, raising=False)
    model = Model()
    c = Conversation.start(LAS, tmp_path / "s", **WINDOW, llm_factory=lambda cfg: model, figures=False, direct=False)
    c.ask(Q1)
    logged = c.log.events("setup")[-1]
    window = ["--top", "600", "--base", "700", "--depth-unit", "m", "--formation", WINDOW["formation"]]
    assert S.main(["--json", "--las", str(LAS), *window, "--investigate"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["hash"] == logged["hash"], S.differences(got, logged)
    assert S.main(["--json", "--investigate"]) == 0                  # no well: the settings file's data alone
    assert json.loads(capsys.readouterr().out)["data"] != logged["data"]


@pytest.mark.data
def test_a_conversation_logs_its_setup_once_and_every_trace_and_trail_names_it(tmp_path):
    from test_conversation import Model, first_steps, later_steps, Q2
    from test_conversation import formation as _formation  # noqa: F401  (the fixture's function)
    pytest.importorskip("petroharness.session")
    from petroharness.evidence import EvidenceGraph, audit
    from petroharness.session import Conversation
    import test_conversation as T
    task = _build(T)
    if task is None:
        pytest.skip("no formation with PHIE, VCL and two zones")
    llm = Model(first_steps() + later_steps())
    c = Conversation.on_tasks(tmp_path / "s", "k2-horizon-7b", llm_factory=lambda cfg: llm, max_steps=4)
    one_, two = c.ask_task(task), c.ask_task(task.model_copy(update={"task_id": "second", "question": Q2}))
    events = c.log.events("setup")
    assert len(events) == 1 and events[0]["hash"] == c.setup.hash() and events[0]["mode"] == "tasks"
    assert events[0]["writer"] == "open" and events[0]["max_steps"] == 4
    assert one_.trace["setup"] == two.trace["setup"] == c.setup.hash()
    g = EvidenceGraph.from_log(c.folder)
    assert g.nodes["session"]["setup"] == c.setup.hash() and g.nodes["session"]["setups"] == [c.setup.hash()]
    assert f"- Setup (petroharness setup; the session log's setup event holds its parts): {c.setup.hash()}" in audit.markdown(g, 1)
    again = Conversation.resume(c.folder, key="k2-horizon-7b", llm_factory=lambda cfg: Model(later_steps()))
    again.ask_task(task.model_copy(update={"task_id": "third", "question": Q2}))
    assert len(again.log.events("setup")) == 1                       # the same setup: not logged again


def _build(T):
    """The session tests' formation, without the fixture machinery: (task) with Session.build patched for this run."""
    from _support.formations import F
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.state import Session
    from petroharness.agent.map import render
    got = next(((t, f) for t, f in F() if {"PHIE", "VCL"} <= set(f.inv.curves) and len(f.view.zones) >= 2), None)
    if got is None:
        return None
    t, f = got
    _build.patch = pytest.MonkeyPatch()
    _build.patch.setattr(Session, "build", classmethod(lambda cls, task, cfg: Session(task, f, render(f.inv), Ledger(f))))
    return t.model_copy(update={"question": T.Q1})


@pytest.fixture(autouse=True)
def _undo():
    yield
    if getattr(_build, "patch", None) is not None:
        _build.patch.undo()
        _build.patch = None


def test_the_functions_hash_is_the_same_in_every_process():
    """Petrophys defaults include frozensets, whose order follows the process's hash seed: the hash must not."""
    import subprocess
    code = "from petroharness.core.setup import functions_hash; print(functions_hash())"
    root = Path(__file__).resolve().parents[2]
    out = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=root,
                          env={**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONHASHSEED": seed}).stdout.strip()
           for seed in ("1", "2", "3")}
    assert len(out) == 1, out


def test_stable_repr_orders_sets_and_drops_addresses():
    from petroharness.core.setup import stable_repr
    one, two = stable_repr(frozenset({"b", "a", "c"})), stable_repr(frozenset({"c", "b", "a"}))
    assert one == two and one.startswith("frozenset(") and one.index("'a'") < one.index("'b'") < one.index("'c'")
    d = stable_repr({"y": 1, "x": {2, 1}})
    assert d.index("'x'") < d.index("'y'") and d.index("1") < d.index("2")
    assert " at 0x" not in stable_repr(object())


def test_the_commit_is_the_harness_s_own_not_a_surrounding_repository_s(tmp_path):
    """An installed copy inside another git repository (its files untracked there) names no commit; a tracked
    source file names its checkout's. The commit every trace records (cli.COMMIT) is this one."""
    import importlib.util
    import shutil
    import subprocess
    repo = tmp_path / "other"
    (repo / "src" / "petroharness" / "core").mkdir(parents=True)
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)
    git("init", "-q")
    (repo / "README").write_text("another project\n", encoding="utf-8")
    git("add", "README")
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init")
    copy = repo / "src" / "petroharness" / "core" / "setup.py"
    shutil.copy(ROOT / "src" / "petroharness" / "core" / "setup.py", copy)

    def commit_of_copy():
        spec = importlib.util.spec_from_file_location("setup_copy", copy)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["setup_copy"] = mod                              # its dataclass looks its module up there
        try:
            spec.loader.exec_module(mod)
            return mod.harness_commit()
        finally:
            del sys.modules["setup_copy"]

    assert commit_of_copy() == ""                                    # untracked there: not this project's commit
    git("add", "src")
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "add")
    assert commit_of_copy() == git("rev-parse", "--short", "HEAD").stdout.strip()
    from petroharness import cli
    assert cli.COMMIT == S.harness_commit()


@pytest.mark.data
def test_the_setup_of_a_well_with_your_zones_is_the_one_its_conversation_logs(tmp_path, monkeypatch, capsys):
    """--zones reaches the setup's data settings as it reaches a conversation's: the same hash, and not the hash
    without them."""
    from test_adopt import LAS, Q1, WINDOW, Model
    from petroharness.session import Conversation
    if not LAS.exists():
        pytest.skip("no sample wells (PETROHARNESS_SAMPLE_LAS)")
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS"):
        monkeypatch.delenv(key, raising=False)
    zones = tmp_path / "zones.csv"
    zones.write_text("zone,top,bottom\nUpper,600,650\nLower,650,700\n")
    c = Conversation.start(LAS, tmp_path / "s", **WINDOW, llm_factory=lambda cfg: Model(), figures=False,
                           direct=False, zones=zones)
    c.ask(Q1)
    logged = c.log.events("setup")[-1]
    window = ["--top", "600", "--base", "700", "--depth-unit", "m", "--formation", WINDOW["formation"]]
    assert S.main(["--json", "--las", str(LAS), *window, "--zones", str(zones), "--investigate"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["hash"] == logged["hash"], S.differences(got, logged)
    assert S.main(["--json", "--las", str(LAS), *window, "--investigate"]) == 0
    assert json.loads(capsys.readouterr().out)["data"] != logged["data"]           # the zones are in the data part
