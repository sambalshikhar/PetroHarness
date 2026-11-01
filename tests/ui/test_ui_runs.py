"""Questions asked through the web UI's API end to end, with a stand-in model on a sample well (data): the three
interval forms; the live events (each model call, the results the model read); the saved run (inputs, events,
answer, trace), its rating and the record its replay plays; the queue. And what the UI must not do: change a prompt,
or show a result other than the one the model read.

    PETROHARNESS_SAMPLE_LAS=<folder of tuhua-7.las> python -m pytest tests/ui -q
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ui_server import serve
from ui_stub import StubModel

from petroharness.ui import server as U

SAMPLES = Path(os.environ.get("PETROHARNESS_SAMPLE_LAS", "sample_las"))   # a folder of sample wells; tests skip without it
LAS, TOPS = SAMPLES / "tuhua-7.las", SAMPLES / "formations_tuhua-7.csv"
QUESTION = "How does porosity vary in this interval, and how shaly is it?"
WINDOW = {"mode": "depths", "top": 600, "base": 700, "unit": "m", "name": "test window"}

pytestmark = pytest.mark.data


@pytest.fixture(scope="module")
def env():
    if not LAS.exists() or not TOPS.exists():
        pytest.skip(f"no sample wells at {SAMPLES} (PETROHARNESS_SAMPLE_LAS)")
    mp = pytest.MonkeyPatch()
    for key in ("PETROHARNESS_DATA", "PETROHARNESS_SKILLS"):     # the settings are built from the LAS
        mp.delenv(key, raising=False)
    yield
    mp.undo()


@pytest.fixture(scope="module")
def ui(env, tmp_path_factory):
    app = U.App(tmp_path_factory.mktemp("ui") / "runs", workers=3, model_factory=lambda cfg: StubModel(cfg))
    srv, client = serve(app)
    yield app, client
    srv.shutdown()
    srv.server_close()


def wait(client, run_id, timeout=600):
    """Poll as the page does; the events gathered and the last view."""
    events, since, t0 = [], 0, time.time()
    while time.time() - t0 < timeout:
        status, view = client.json(f"/api/job/{run_id}?since={since}")
        assert status == 200, view
        events += view["events"]
        since = view["n_events"]
        if view["status"] not in ("queued", "running"):
            return events, view
        time.sleep(0.3)
    raise AssertionError(f"{run_id} did not finish in {timeout} s")


def ask(client, interval):
    status, got = client.json("/api/ask", {"las": str(LAS), "question": QUESTION, "interval": interval})
    assert status == 200, got
    events, view = wait(client, got["id"])
    assert view["status"] == "done", view.get("error")
    return got, events, view


@pytest.mark.parametrize("form", ["tops", "depths", "whole"])
def test_the_three_interval_forms(ui, form):
    app, c = ui
    interval = {"tops": {"mode": "tops", "tops": str(TOPS), "formation": "mount messenger"}, "depths": WINDOW,
                "whole": {"mode": "whole"}}[form]
    got, events, view = ask(c, interval)
    res = view["result"]
    iv = res["interval"]
    if form == "tops":
        assert (iv["name"], iv["top"], iv["base"], iv["unit"]) == ("Mount Messenger", 590.55, 873.8616, "m")
        assert iv["from"] == "tops file formations_tuhua-7.csv, base: stated base"
        assert view["label"] == "mount messenger"
    elif form == "depths":
        assert iv["name"] == "test window" and iv["unit"] == "m" and 600 <= iv["top"] < 601 and 699 < iv["base"] <= 700
        assert iv["from"] == "depths given"
    else:
        assert iv["name"] == "whole well" and iv["from"] == "the whole log (no formation or depths given)"
        assert view["label"] == "whole well"
    assert iv["samples"] > 100
    # the answer: the repaired draft with the zone table in place
    assert "Porosity is read zone by zone in the table." in view["answer"] and "{{ZONE_TABLE}}" not in view["answer"]
    assert res["read"]["topics"] == ["porosity", "shale_clay"] and res["claims"] and res["opened"]
    assert res["skills"]["library"] == "researched" and res["status"] == "ok" and res["usage"]["calls"] >= 6
    assert res["steps"][0]["edits"][0] == {"op": "add", "point": 1, "grade": "hypothesis", "text": "Porosity varies by zone"}
    assert res["steps"][0]["actions"] and res["points"][0].startswith("How porous is the interval")
    # the live events: each model call as it happened, the results the model read
    phases = [e["name"] for e in events if e["kind"] == "phase"]
    assert phases == ["queued", "started", "interpreting", "finished"]
    calls = [(e["type"], e.get("number")) for e in events if e["kind"] == "call"]
    assert calls[0] == ("read", None) and ("step", 1) in calls and ("step", 2) in calls
    assert ("settle", None) in calls and ("writer", None) in calls and ("repair", 1) in calls
    replies = {e["n"]: e for e in events if e["kind"] == "reply"}
    assert len(replies) == len(calls) and all("seconds" in r for r in replies.values())
    step1 = next(e for e in events if e["kind"] == "reply" and e["stage"] == "step_1")
    assert step1["focus"] == "porosity and shale by zone" and "guide porosity" in step1["next"]
    repair = next(e for e in events if e["kind"] == "call" and e["type"] == "repair")
    assert "0.987654" in repair["findings"]
    shown = {i["id"] for e in events if e["kind"] == "results" for i in e["items"]}
    assert {o["id"] for o in res["opened"]} <= shown                    # every opened result reached the page
    # the interval's logs, once Petrophys has read the well and before the first model call
    kinds = [e["kind"] for e in events]
    assert kinds.count("well") == 1 and kinds.index("well") < kinds.index("call")
    well = next(e for e in events if e["kind"] == "well")
    assert "error" not in well and well["samples"] == iv["samples"] and well["unit"] == iv["unit"]
    assert [(z["zone"], z["lithology"]) for z in well["zones"]] == [(z["zone"], z["lithology"]) for z in res["zones"]]
    plotted = {c["name"]: c for t in well["tracks"] for c in t["curves"]}
    assert {"VCL", "PHIE", "SW", "PERM"} <= set(plotted) and plotted["PHIE"]["source"] == "Petrophys"
    assert all(len(c["values"]) == len(well["depth"]) for c in plotted.values())
    assert well["depth"] == sorted(well["depth"]) and well["lithology"]
    ts = [e["t"] for e in events]
    assert ts == sorted(ts)
    # saved: the run's record, answer.md and trace.json (petroharness.ask's files)
    folder = app.store.root / got["id"]
    rec = json.loads((folder / "run.json").read_text())
    assert rec["status"] == "done" and rec["answer"] == view["answer"] and rec["events"] == events
    assert rec["inputs"]["interval"] == interval and rec["result"]["interval"] == iv
    trace = json.loads((folder / "trace.json").read_text())
    assert trace["ask"]["interval"] == iv and trace["answer"] == view["answer"]
    assert (folder / "answer.md").read_text().startswith("# tuhua-7: ")
    assert (folder / ".cache").is_symlink()                             # interpreted wells shared between runs


def test_a_run_is_listed_rated_and_replayable(ui):
    app, c = ui
    got, events, view = ask(c, WINDOW)
    run_id = got["id"]
    status, listed = c.json("/api/runs")
    assert status == 200 and run_id in [r["id"] for r in listed]
    status, rating = c.json(f"/api/rate/{run_id}", {"verdict": "partly", "note": "zone 2 is right"})
    assert status == 200 and rating["verdict"] == "partly"
    status, rec = c.json(f"/api/run/{run_id}")
    assert status == 200 and rec["rating"]["note"] == "zone 2 is right"
    assert next(r for r in c.json("/api/runs")[1] if r["id"] == run_id)["verdict"] == "partly"
    status, bad = c.json(f"/api/rate/{run_id}", {"verdict": "great"})
    assert status == 400 and "verdict" in bad["error"]
    # the replay (#replay=<id>&speed=N) plays the saved record's events: all of them, in order, then its answer
    app.jobs.pop(run_id)                                                 # as after a restart: read from the folder
    status, saved = c.json(f"/api/run/{run_id}")
    assert saved["events"] == events and saved["answer"] == view["answer"] and saved["result"] == view["result"]
    last = saved["events"][-1]
    assert (last["kind"], last["name"], last["status"]) == ("phase", "finished", "done")
    status, job = c.json(f"/api/job/{run_id}?since=3")
    assert job["events"] == events[3:] and job["n_events"] == len(events)
    for name, ctype in (("answer.md", "text/markdown"), ("trace.json", "application/json")):
        status, kind, body = c.get(f"/api/run/{run_id}/{name}")
        assert status == 200 and kind.startswith(ctype) and body


def test_the_queue(env, tmp_path):
    gate = threading.Event()
    app = U.App(tmp_path / "runs", workers=1, model_factory=lambda cfg: StubModel(cfg, gate=gate))
    srv, c = serve(app)
    try:
        ids = [c.json("/api/ask", {"las": str(LAS), "question": QUESTION, "interval": WINDOW})[1]["id"] for _ in range(2)]
        t0 = time.time()
        while not any(e["kind"] == "call" for e in app.jobs[ids[0]].events) and time.time() - t0 < 300:
            time.sleep(0.2)
        first, second = c.json(f"/api/job/{ids[0]}")[1], c.json(f"/api/job/{ids[1]}")[1]
        assert first["status"] == "running" and second["status"] == "queued" and second["queue_position"] == 1
        assert c.json("/api/config")[1]["queued"] == 1 and c.json("/api/config")[1]["running"] == 1
        gate.set()
        for run_id in ids:
            assert wait(c, run_id)[1]["status"] == "done"
    finally:
        gate.set()
        srv.shutdown()
        srv.server_close()


def _ask_window(llm_factory):
    from petroharness.ask import ask
    return ask(LAS, QUESTION, top=600, base=700, depth_unit="m", formation="test window", llm_factory=llm_factory)


def test_the_ui_changes_no_prompt(env):
    """The same question with the harness's client as it is and wrapped as the UI wraps it: every request the model
    gets is the same (stage, messages, token cap, schema), and so is the answer."""
    from petroharness.ui.progress import Observed
    from petroharness.ask import ask
    from petroharness.ui.wellplot import payload
    plain, observed, events, plots = [], [], [], []
    a = _ask_window(lambda cfg: StubModel(cfg, log=plain))
    b = ask(LAS, QUESTION, top=600, base=700, depth_unit="m", formation="test window",
            llm_factory=lambda cfg: Observed(StubModel(cfg, log=observed), events.append),
            on_view=lambda view: plots.append(payload(view)))
    assert len(plots) == 1 and plots[0]["tracks"]                       # the plot, built from the view, changes nothing
    assert {c["stage"] for c in plain} >= {"read", "step_1", "step_2", "settle", "writer", "repair_1"}
    assert plain == observed
    assert a.answer == b.answer and a.status == b.status == "ok"
    assert [e for e in events if e["kind"] == "call"]


def test_the_results_shown_are_the_ledger_items(env, monkeypatch):
    """Each opened result the page shows is the ledger's item as the model read it: its whole text, or its digest
    when the model only ever saw that."""
    from petroharness.agent import loop
    from petroharness.ui.progress import Observed
    sessions, clients = [], []
    build = loop.Session.build

    def capture(task, cfg):
        s = build(task, cfg)
        sessions.append(s)
        return s
    monkeypatch.setattr(loop.Session, "build", staticmethod(capture))

    def factory(cfg):
        clients.append(Observed(StubModel(cfg), lambda e: None))
        return clients[-1]
    assert _ask_window(factory).status == "ok"
    ledger, got = sessions[0].ledger, clients[0].results
    assert len(ledger.items) >= 5 and {e.tool for e in ledger.items} >= {"stats", "profile", "runs", "compare", "section"}
    assert set(got) == {e.id for e in ledger.items}
    for e in ledger.items:
        text, digest = got[e.id]
        want = e.text if not digest else ledger.digest(e)[len(e.id) + 3:]
        assert text == want, e.id
    assert sum(not d for _, d in got.values()) >= len(got) - 2           # nearly all were seen whole
