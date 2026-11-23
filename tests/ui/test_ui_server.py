"""The web UI's server (src/petroharness/ui/server.py) without a model: the page and its images, uploads, a LAS file's
header, the formations a tops file names, the checks on the inputs, the model endpoints' health and choice, and the
`petroharness ui` command.

    python -m pytest tests/ui -q
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_stub import StubModel

from petroharness.ui import server as U

LAS = """~Version
VERS. 2.0 :
WRAP. NO :
~Well
STRT.M 1000.0 :
STOP.M 1004.0 :
STEP.M 0.5 :
NULL. -999.25 :
WELL. Test Well 1 :
UWI. 00-111-222 :
~Curve
DEPT.M : depth
GR.API : gamma ray
LITHO. : lithology code
~A
1000.0 50 1
1000.5 60 1
1001.0 70 2
1001.5 80 2
1002.0 90 2
1002.5 80 1
1003.0 70 1
1003.5 60 1
1004.0 50 1
"""
TOPS = "formation,top,bottom,depth_unit\nUpper,1000.0,1002.0,m\nLower,1002.0,,m\nRepeat,1000.5,,m\nRepeat,1003.0,,m\n"
WELLS = "well,zone,top\nTW1,Alpha,1000\nOTHER,Beta,1001\n"


class Client:
    def __init__(self, base):
        self.base = base

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=30) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def json(self, path, body=None, headers=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {"Content-Type": "application/json"},
                                     method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


def serve(app):
    srv = U.make_servers(app, "127.0.0.1", 0)[0]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, Client(f"http://127.0.0.1:{srv.server_address[1]}")


@pytest.fixture
def ui(tmp_path):
    app = U.App(tmp_path / "runs", workers=1, model_factory=lambda cfg: StubModel(cfg))
    srv, client = serve(app)
    yield app, client
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def files(tmp_path):
    las = tmp_path / "TW1.las"
    las.write_text(LAS)
    tops = tmp_path / "tops.csv"
    tops.write_text(TOPS)
    return las, tops


def test_the_page_and_its_images_are_served(ui):
    _, c = ui
    status, ctype, body = c.get("/")
    assert status == 200 and ctype.startswith("text/html")
    page = body.decode()
    assert "<title>PetroHarness</title>" in page and "/img/petroharness_logo.svg" in page
    assert "#replay=" in page and "window.__replay" in page                  # replay mode
    for name, kind in (("petroharness_logo.svg", "image/svg+xml"), ("petroharness_mark.png", "image/png"),
                       ("petroharness_logo_dark.png", "image/png"), ("petrophys_mark.png", "image/png")):
        status, ctype, body = c.get(f"/img/{name}")
        assert status == 200 and ctype == kind and body
    for bad in ("/img/../server.py", "/img/nothing.png", "/nothing", "/api/nothing"):
        with pytest.raises(urllib.error.HTTPError) as e:
            c.get(bad)
        assert e.value.code == 404


def test_a_404_says_what_is_missing_whole(ui):
    _, c = ui
    status, got = c.json("/api/run/20260101-000000-abcdef")
    assert status == 404 and got["error"] == "no run '20260101-000000-abcdef'"           # both quotes kept
    status, got = c.json("/api/run/20260101-000000-abcdef/conversation")
    assert status == 404 and got["error"].endswith("'20260101-000000-abcdef'")


def _js_function(page: str, name: str) -> str:
    """The source of one top-level function of the page's script, to the next top-level function or comment."""
    start = page.find(f"\nfunction {name}(")
    start = start if start >= 0 else page.index(f"\nasync function {name}(")
    end = min(i for i in (page.find("\nfunction ", start + 1), page.find("\n// ", start + 1), page.find("\nasync function ", start + 1)) if i > 0)
    return page[start:end]


def test_the_shown_tab_carries_the_answers_blocks():
    """What a finished answer brings beside its text (its figures, the methods it rests on, the audit trail) is drawn in
    the tab the page opens on, and every pane the page defines is one a tab shows (a pane no tab shows once hid all of
    these)."""
    page = (U.STATIC / "index.html").read_text()
    tabs = _js_function(page, "render")
    shown = set(re.findall(r"html \+= (\w+Pane)\(", tabs))
    defined = set(re.findall(r"\nfunction (\w+Pane)\(", page))
    assert defined <= shown, f"panes no tab shows: {sorted(defined - shown)}"
    assert re.search(r'S\.tab === "main"[^\n]*mainPane\(', tabs)
    main = _js_function(page, "mainPane")
    for block in ("figuresHtml(j, res)", "lineageHtml(j)", "basisHtml(res)", "auditHtml(j)"):
        assert block in main, block
    assert "lineageWire(j)" in _js_function(page, "wire")          # the computation graph is fetched and drawn


def test_the_earlier_questions_stay_on_screen():
    """A conversation's earlier questions are drawn above the question on screen, on every tab, each a box that opens
    to its whole answer (its first sentence shows while closed), with its figures and a way to its own page; what the
    page shows comes from the server's conversation route, fetched again when the run on screen changes status."""
    page = (U.STATIC / "index.html").read_text()
    tabs = _js_function(page, "render")
    assert tabs.index('<div id="turns">${turnsHtml(j)}</div>') < tabs.index('<div class="runhead">')
    assert tabs.index("turnsHtml(j)") < tabs.index('if (S.tab === "main"')       # above the tabs: on each of them
    assert "convLoad(j)" in tabs
    load = _js_function(page, "convLoad")
    assert "/conversation`" in load and "${j.id}|${j.status}" in load
    box = _js_function(page, "turnHtml")
    assert "<details" in box and "gist(t.answer)" in box and "answerSections(t.answer)" in box
    assert "t.figures" in box and "data-openrun" in box
    assert "before" in _js_function(page, "turnsHtml") and "threadHtml" not in page


def test_a_conversation_s_settings_change_from_the_composer():
    """In an open conversation the interpretation chip opens the settings for its next questions (the dialog on the
    conversation's own well and settings); the follow-up carries the settings to adopt; the run that changed them
    says so, and earlier questions say they rest on the earlier settings."""
    page = (U.STATIC / "index.html").read_text()
    chips = _js_function(page, "chipsRender")
    assert 'interpOpen("conv")' in chips and "S.pending" in chips
    opened = _js_function(page, "interpOpen")
    assert 'mode === "conv"' in opened and "convSettings(S.last)" in opened
    assert "S.iconv" in _js_function(page, "ipInputs") and "ipInputs()" in _js_function(page, "interpPreview")
    assert "interpretation: S.pending.settings" in _js_function(page, "ask")
    assert "settingsLine(j, m)" in _js_function(page, "render")
    assert 'e.kind === "settings"' in _js_function(page, "digest")       # the change named as soon as it is made
    line = _js_function(page, "settingsLine")
    assert "m.settings.changes" in line and "if (live && !live.length) return" in line
    assert "before the settings change at question" in _js_function(page, "turnHtml")


def test_field_notes_are_chosen_in_the_options_and_sent_with_the_question():
    """Options takes a field notes file (a path, or an upload of kind notes, checked by /api/notes); the form sends
    its path; the settings panel shows the notes' value of a setting they set."""
    page = (U.STATIC / "index.html").read_text()
    assert 'id="notespath"' in page and 'id="notesfile"' in page and 'upload("notes"' in page
    assert "/api/notes?path=" in _js_function(page, "loadNotes")
    assert "inputs.field_notes = S.notes.path" in _js_function(page, "formInputs")
    assert "Field notes: " in _js_function(page, "idHtml")


def test_the_composer_continues_the_open_conversation():
    """One question box, docked at the bottom: while a finished answer of a conversation is open, the question asked
    there is that conversation's next (the server's follow); otherwise it starts a new conversation with the composer's
    well, interval and settings. There is no second, follow-up box; Enter sends and Shift+Enter starts a new line."""
    page = (U.STATIC / "index.html").read_text()
    assert 'id="composer"' in page and 'id="question"' in page and 'id="followq"' not in page
    assert page.index('id="composer"') > page.index('<main class="main">')             # after the answer, at the bottom
    assert "composerFor(j)" in _js_function(page, "render")
    follow = _js_function(page, "composerFor")
    assert 'j.status === "done"' in follow and "j.conversation" in follow and "S.followId" in follow
    ask = _js_function(page, "ask")
    assert "S.followId ? {follow: S.followId, question: q" in ask and ": formInputs();" in ask
    assert 'e.key === "Enter" && !e.shiftKey' in page
    fresh = _js_function(page, "newConversation")
    assert "S.followId = null" in fresh and "emptyPage()" in fresh


def test_the_page_names_no_benchmark_or_version_history():
    page = (U.STATIC / "index.html").read_text().lower()
    for word in ("benchmark", "category", "playbook", "classify", "legacy", "v3.", "v5", "judge"):
        assert word not in page, word


def test_config(ui):
    _, c = ui
    status, cfg = c.json("/api/config")
    assert status == 200 and cfg["workers"] == 1 and cfg["endpoints"] == [] and cfg["max_steps"] >= 1
    assert "porosity" in cfg["topics"] and isinstance(cfg["profiles"], list)


def test_upload_a_las_and_read_its_header(ui):
    app, c = ui
    status, got = c.json("/api/upload?kind=las", raw=LAS.encode(), headers={"X-Filename": "my well.las"})
    assert status == 200, got
    assert Path(got["path"]).parent == app.store.uploads and Path(got["path"]).name == "my_well.las"
    assert got["well"] == "Test Well 1" and got["uwi"] == "00-111-222" and got["depth_unit"] == "m"
    assert (got["top"], got["base"], got["samples"], got["step"]) == (1000.0, 1004.0, 9, 0.5)
    assert [x["mnemonic"] for x in got["curves"]] == ["GR", "LITHO"] and got["lithology_candidates"] == ["LITHO"]
    assert got["curves"][0] == {"mnemonic": "GR", "unit": "API", "description": "gamma ray"}
    # the same name, other bytes: kept beside it
    status, again = c.json("/api/upload?kind=las", raw=LAS.replace("50 1", "55 1").encode(),
                           headers={"X-Filename": "my well.las"})
    assert status == 200 and again["path"] != got["path"] and Path(again["path"]).name.startswith("my_well_")
    status, by_path = c.json(f"/api/las?path={got['path']}")
    assert status == 200 and by_path["curves"] == got["curves"]


@pytest.mark.parametrize("name, body, says", [("notes.txt", b"x", "is not a LAS file"), ("w.las", b"", "is empty"),
                                              ("w.las", b"this is not a log", "could not be read as a LAS file")])
def test_bad_uploads_are_refused(ui, name, body, says):
    app, c = ui
    status, got = c.json("/api/upload?kind=las", raw=body, headers={"X-Filename": name})
    assert status == 400 and says in got["error"], got
    assert not list(app.store.uploads.glob("w*.las"))                    # a file that is no LAS is not kept


def test_the_same_upload_again_leaves_the_kept_file_as_it_is(tmp_path):
    """A file uploaded again with the same bytes is the file already kept (a running question may be reading it): its
    path, the file not written again."""
    store = U.Store(tmp_path / "runs")
    first = store.upload("las", "my well.las", LAS.encode())
    os.utime(first, ns=(10 ** 18, 10 ** 18))                             # a write now would change the time
    before = first.stat()
    again = store.upload("las", "my well.las", LAS.encode())
    after = again.stat()
    assert again == first and (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_two_files_of_one_name_uploaded_at_once_are_both_kept(tmp_path, monkeypatch):
    """Different files of one name uploaded at the same time each keep their own path and bytes (a slow disk widens
    the moment between choosing the name and writing the file)."""
    store = U.Store(tmp_path / "runs")
    write = Path.write_bytes

    def slow(self, data):
        time.sleep(0.05)
        return write(self, data)
    monkeypatch.setattr(Path, "write_bytes", slow)
    bodies = [LAS.replace("50 1", f"{50 + i} 1").encode() for i in range(4)]
    start, got = threading.Barrier(len(bodies)), {}

    def upload(i):
        start.wait()
        got[i] = store.upload("las", "my well.las", bodies[i])
    threads = [threading.Thread(target=upload, args=(i,)) for i in range(len(bodies))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({got[i] for i in got}) == len(bodies)
    assert all(got[i].read_bytes() == bodies[i] for i in got)


def test_the_tops_listing(ui, files):
    _, c = ui
    las, tops = files
    status, got = c.json(f"/api/tops?path={tops}&las={las}")
    assert status == 200, got
    rows = {r["name"]: r for r in got["formations"]}
    assert list(rows) == ["Upper", "Lower", "Repeat"]
    assert (rows["Upper"]["top"], rows["Upper"]["base"], rows["Upper"]["base_from"]) == (1000.0, 1002.0, "stated base")
    assert (rows["Lower"]["base"], rows["Lower"]["base_from"]) == (1003.0, "next top Repeat")
    rep = rows["Repeat"]["repeated"]                     # a name listed twice: each listing, chosen by its top
    assert [(r["top"], r["base"], r["base_from"]) for r in rep] == [(1000.5, 1002.0, "next top Lower"),
                                                                    (1003.0, None, "end of log")]
    # a table of several wells: this well's rows only
    wells = tops.parent / "wells.csv"
    wells.write_text(WELLS)
    status, got = c.json(f"/api/tops?path={wells}&las={las}")
    assert status == 200 and [r["name"] for r in got["formations"]] == ["Alpha"] and got["wells"] == ["TW1"]
    status, got = c.json(f"/api/tops?path={tops.parent / 'none.csv'}")
    assert status == 400 and "no tops file" in got["error"]


def test_upload_a_tops_file(ui, files):
    app, c = ui
    las, _ = files
    status, got = c.json("/api/upload?kind=tops", raw=TOPS.encode(), headers={"X-Filename": "tops.csv"})
    assert status == 200 and Path(got["path"]).parent == app.store.uploads
    status, listed = c.json(f"/api/tops?path={got['path']}&las={las}")
    assert status == 200 and len(listed["formations"]) == 3


def _ask(path, **over):
    return {"las": str(path), "question": "What is the porosity?", **over}


@pytest.mark.parametrize("over, says", [
    ({"las": "/no/such/file.las"}, "no LAS file at /no/such/file.las"),
    ({"question": "   "}, "the question is empty"),
    ({"interval": {"mode": "depths"}}, "no depths given"),
    ({"interval": {"mode": "depths", "top": 1003, "base": 1001}}, "is not below the top"),
    ({"interval": {"mode": "depths", "top": "deep"}}, "is not a number"),
    ({"interval": {"mode": "depths", "top": 1001, "unit": "furlong"}}, "is not m or ft"),
    ({"interval": {"mode": "tops", "formation": "Upper"}}, "no tops file given"),
    ({"interval": {"mode": "tops", "tops": "TOPS"}}, "no formation chosen"),
    ({"interval": {"mode": "tops", "tops": "TOPS", "formation": "Uper"}}, "Did you mean 'Upper'?"),
    ({"interval": {"mode": "tops", "tops": "TOPS", "formation": "Repeat"}}, "listed 2 times"),
    ({"interval": {"mode": "sideways"}}, "interval mode"),
    ({"skills": "/no/such/library"}, "no skill library folder"),
    ({"max_steps": 0}, "max steps 0"),
    ({"max_steps": "many"}, "not a whole number"),
    ({"depth": "deep"}, "depth 'deep'"),
    ({"profile": "no-such-profile"}, "no context profile"),
])
def test_wrong_inputs_are_said_before_the_queue(ui, files, over, says):
    app, c = ui
    las, tops = files
    if "interval" in over and over["interval"].get("tops") == "TOPS":
        over = {"interval": {**over["interval"], "tops": str(tops)}}
    if over.get("profile") and not U.A.context_profiles():
        pytest.skip("this Petrophys lists no context profiles")
    status, got = c.json("/api/ask", _ask(las, **over))
    assert status == 400 and says in got["error"], got
    assert not app.jobs


def test_the_inputs_as_ask_arguments(files, tmp_path):
    las, tops = files
    A = U.A
    assert A.arguments(_ask(las)) == {"las": las.resolve(), "question": "What is the porosity?"}
    got = A.arguments(_ask(las, interval={"mode": "tops", "tops": str(tops), "formation": "upper", "unit": ""},
                           lithology_curve="LITHO", formation_lithology="sandstone", skills="none", max_steps="5"))
    assert got == {"las": las.resolve(), "question": "What is the porosity?", "tops": tops.resolve(),
                   "formation": "upper", "depth_unit": None, "lithology_curve": "LITHO",
                   "formation_lithology": "sandstone", "skills": "none", "max_steps": 5}
    got = A.arguments(_ask(las, interval={"mode": "tops", "tops": str(tops), "formation": "Repeat", "top": 1003}))
    assert (got["formation"], got["top"]) == ("Repeat", 1003.0)       # one listing of a name the file lists twice
    with pytest.raises(A.InputError, match="no row with top 1001"):
        A.arguments(_ask(las, interval={"mode": "tops", "tops": str(tops), "formation": "Repeat", "top": 1001}))
    got = A.arguments(_ask(las, interval={"mode": "depths", "top": "1001", "base": "", "unit": "M", "name": " sand "},
                           skills="default"))
    assert (got["top"], got["base"], got["depth_unit"], got["formation"]) == (1001.0, None, "m", "sand")
    assert "skills" not in got and "direct" not in got                 # the model decides the depth of the answer
    assert A.arguments(_ask(las, depth="investigate"))["direct"] is False
    assert "direct" not in A.arguments(_ask(las, depth="auto"))
    lib = tmp_path / "lib"
    lib.mkdir()
    assert A.arguments(_ask(las, skills=str(lib)))["skills"] == str(lib.resolve())
    assert A.interval_label(_ask(las, interval={"mode": "depths", "top": 1001, "unit": "m"})) == "1001-log base m"
    assert A.interval_label(_ask(las)) == "whole well"


# --- the model endpoints ---------------------------------------------------------------------------------------------

def _models_server(ids):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({"object": "list", "data": [{"id": i} for i in ids]}).encode()
            self.send_response(200 if self.path == "/v1/models" else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


def test_endpoint_health_and_choice():
    model = U.served_model()
    good1, u1 = _models_server([model])
    good2, u2 = _models_server([model])
    other, u3 = _models_server(["another-model"])
    dead = "http://127.0.0.1:9/v1"
    try:
        ep = U.Endpoints([u1, u2, u3, dead], model)
        rows = {r["url"]: r for r in ep.health()}
        assert rows[u1]["ok"] and rows[u2]["ok"] and rows[u1]["models"] == [model]
        assert not rows[u3]["ok"] and "another-model" in rows[u3]["error"]
        assert not rows[dead]["ok"] and rows[dead]["error"]
        first = ep.acquire()
        second = ep.acquire()
        assert {first, second} == {u1, u2}                             # the least busy of the healthy ones
        ep.release(first)
        assert ep.acquire() == first
        assert {r["url"]: r["busy"] for r in ep.health()}[second] == 1
        none = U.Endpoints([u3, dead], model)
        with pytest.raises(RuntimeError, match="no endpoint serves"):
            none.acquire()
        with pytest.raises(RuntimeError, match="no model endpoint"):
            U.Endpoints([], model).acquire()
    finally:
        for s in (good1, good2, other):
            s.shutdown()
            s.server_close()


def test_the_model_is_the_harness_model_card():
    assert U.served_model() == "k2-horizon-7b"
    assert U.served_model("Qwen/Qwen3-32B") == "Qwen/Qwen3-32B"            # any chat model, by its served name


def test_the_page_names_the_model_from_its_card(tmp_path):
    app = U.App(tmp_path / "runs", workers=1, model_factory=lambda cfg: None)
    assert app.config()["label"] == "K2-Horizon-7B" and app.choice == {}
    other = U.App(tmp_path / "runs2", workers=1, model_factory=lambda cfg: None, model="Qwen/Qwen3-32B")
    assert other.config()["label"] == "Qwen/Qwen3-32B" and other.choice == {"model": "Qwen/Qwen3-32B"}


# --- the command ---------------------------------------------------------------------------------------------------

def test_petroharness_ui_is_a_subcommand(monkeypatch, capsys):
    from petroharness import cli
    monkeypatch.setattr(sys, "argv", ["petroharness", "ui", "--help"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: petroharness ui") and "--runs RUNS" in out and "--workers" in out
    args = U.parser().parse_args([])
    assert (args.host, args.port, args.runs, args.workers) == ("127.0.0.1", 7860, Path("petroharness-ui-runs"), 4)


def test_a_port_in_use_is_said(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(U, "served_model", lambda *a: "m")
    busy = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    try:
        assert U.main(["--port", str(busy.server_address[1]), "--runs", str(tmp_path / "r")]) == 2
        assert "cannot listen" in capsys.readouterr().err
    finally:
        busy.server_close()


def test_runs_a_stopped_server_left_are_marked_interrupted(tmp_path):
    from petroharness.ui.store import Store
    store = Store(tmp_path / "runs")
    store.save({"id": "20260101-000000-abcdef", "status": "running", "inputs": {"question": "q", "las": "/x/w.las"},
                "events": []})
    assert store.interrupted() == 1
    assert store.load("20260101-000000-abcdef")["status"] == "interrupted"
    assert store.history()[0]["status"] == "interrupted" and store.history()[0]["las"] == "w.las"
    with pytest.raises(KeyError):
        store.load("../../etc/passwd")


def test_a_card_that_names_no_model_needs_the_model_s_name(tmp_path):
    with pytest.raises(ValueError, match="names no model. FIX: give the served model's name"):
        U.App(tmp_path / "runs", workers=1, urls=["http://127.0.0.1:9/v1"], model_card="generic")
    app = U.App(tmp_path / "runs", workers=1, urls=["http://127.0.0.1:9/v1"], model_card="generic", model="my-llm")
    assert app.endpoints.model == "my-llm"


def test_a_conversation_keeps_every_question_however_many_runs_came_after(tmp_path):
    """The run list shows the newest runs; a conversation's view reads all of its own (an old conversation followed up
    after many other runs keeps its first question)."""
    app = U.App(tmp_path / "runs", workers=1, model_factory=lambda cfg: StubModel(cfg))
    root, follow = "20260101-000000-aaaaaa", "20260103-000000-cccccc"

    def run(rid, question, conversation=None):
        app.store.save({"id": rid, "status": "done", "created": rid, "inputs": {"question": question, "las": "/x/w.las"},
                        "events": [], **({"conversation": conversation} if conversation else {})})

    run(root, "first", {"root": root, "turn": 1})
    for i in range(501):
        run(f"20260102-{i // 3600:02d}{i // 60 % 60:02d}{i % 60:02d}-bbbbbb", "another conversation")
    run(follow, "second", {"root": root, "turn": 2})
    assert root not in [r["id"] for r in app.runs()]                    # the run list: the newest 500
    assert [(t["turn"], t["question"]) for t in app.conversation(follow)["turns"]] == [(1, "first"), (2, "second")]
    assert [b["id"] for b in app.store.conversation(root)] == [root, follow]


def test_the_run_list_is_read_while_questions_come_and_go(tmp_path):
    """The run list is read while other threads add questions to the job table (submit) and drop finished ones
    (_forget): it is read from a copy taken under the table's lock, so it never fails mid-read."""
    from petroharness.ui import adapter as A
    app = U.App(tmp_path / "runs", workers=1, model_factory=lambda cfg: StubModel(cfg))
    for n in range(300):                                                 # questions still running: listed
        app.jobs[f"live{n}"] = A.Job(f"live{n}", {}, {})
    stop, errors = threading.Event(), []

    def come_and_go():
        n = 0
        while not stop.is_set():
            job = A.Job(f"done{n}", {}, {})
            job.finished = time.time()
            with app._lock:
                app.jobs[job.id] = job
            app._forget(keep=0)
            n += 1
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)                                          # the threads take turns often
    t = threading.Thread(target=come_and_go)
    t.start()
    try:
        t0 = time.time()
        while time.time() - t0 < 1.0 and not errors:
            try:
                assert len(app.runs()) == 300
            except RuntimeError as exc:                                  # dictionary changed size during iteration
                errors.append(exc)
    finally:
        stop.set()
        t.join()
        sys.setswitchinterval(old)
    assert not errors, errors[0]


def test_a_follow_up_of_a_question_forgotten_meanwhile_is_read_from_its_record(tmp_path):
    """A follow-up's question may be dropped from the job table (a worker's _forget) between being looked up and
    being read: the job table is read once, and a job not there is read from its saved record."""
    from petroharness.ui import adapter as A

    class Forgetting(dict):                                              # forgets a job right after saying it has it
        def __contains__(self, key):
            found = dict.__contains__(self, key)
            self.pop(key, None)
            return found
    app = U.App(tmp_path / "runs", workers=1, model_factory=lambda cfg: StubModel(cfg))
    job = A.Job(app.store.new_id(), {"question": "q", "las": "/x/w.las"}, {})
    app.store.save(job.record())                                         # still queued: no answer to follow up yet
    app.jobs = Forgetting({job.id: job})
    with pytest.raises(A.InputError, match="that question has no answer yet"):
        app.submit({"follow": job.id, "question": "and then?"})


# --- requests another site's page could send through the user's browser -------------------------------------------

def test_a_request_from_another_site_is_refused(ui):
    _, client = ui
    port = client.base.rsplit(":", 1)[1]
    code, body = client.json("/api/ask", {"las": "/etc/hostname", "question": "q"},
                             headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
    assert code == 403 and "another site" in body["error"]
    code, body = client.json("/api/config", None, headers={"Origin": f"http://127.0.0.1:{port}"})
    assert code == 200                                       # the server's own page


def test_a_post_the_page_does_not_send_is_refused(ui):
    _, client = ui
    code, body = client.json("/api/ask", None, raw=b'{"question": "q"}', headers={"Content-Type": "text/plain"})
    assert code == 403 and "does not send" in body["error"]


def test_a_loopback_server_answers_its_own_host_names_only(ui):
    _, client = ui
    port = client.base.rsplit(":", 1)[1]
    code, body = client.json("/api/config", None, headers={"Host": f"evil.example:{port}"})
    assert code == 403 and "host" in body["error"]
    code, _ = client.json("/api/config", None, headers={"Host": f"localhost:{port}"})
    assert code == 200


def test_a_proxys_host_name_is_answered_when_allowed(tmp_path):
    app = U.App(tmp_path / "runs", workers=1, model_factory=lambda cfg: StubModel(cfg))
    srv = U.make_servers(app, "127.0.0.1", 0, allow_hosts=["proxy.example"])[0]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client = Client(f"http://127.0.0.1:{srv.server_address[1]}")
        code, _ = client.json("/api/config", None, headers={"Host": "proxy.example"})
        assert code == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_context_profiles_offered_are_petrophys_s():
    """The page offers every context profile Petrophys has (petrophys.reporting.context_profiles; the top-level
    petrophys.list_context_profiles is gone from Petrophys 0b31d72)."""
    from petrophys.reporting.context_profiles import list_context_profiles
    assert U.A.context_profiles() == list(list_context_profiles())
    assert U.A.context_profiles()


def test_the_notes_before_the_answer_are_worded_for_the_reader():
    """The notes under the question reach the page as data (agent.vocabulary.facts), worded for the person reading
    the answer, without the model's instructions; a run saved before shows the lines the model was given."""
    A = U.A
    trace = {"question_notes": "Your zones with no sample here: ... Name them when the question is about your zones.",
             "reader_notes": [
                 {"kind": "absent", "name": "shear sonic", "curves": ["DTS"], "computes": []},
                 {"kind": "empty", "name": "DTC", "curves": [{"curve": "DTC", "why": "range screening removed 12%"}]},
                 {"kind": "absent_unit", "names": ["Hugin"], "units": ["Brent", "Ness", "Etive"]},
                 {"kind": "zones_left", "zones": [{"name": "Below TD", "top": 3600.0, "base": 3700.0, "unit": "m",
                                                   "why": "no sample of the log, which runs 176.61-3556.08 m"}]}]}
    assert A._notes(trace) == [
        "Not in this well's record: shear sonic (no DTS curve).",
        "In this well's record but with no value in this interval: DTC (DTC: range screening removed 12%).",
        "Not a unit of the tops file: Hugin. No value of another stretch is given for it; the file lists Brent, Ness, "
        "Etive.",
        "Your zone Below TD, 3600–3700 m: no sample of the log, which runs 176.61-3556.08 m. Nothing is computed for it."]
    assert not any("Name them" in n for n in A._notes(trace))
    assert A._notes({"question_notes": "line one\n\nline two"}) == ["line one", "line two"]


def test_a_zones_file_is_checked_as_it_loads(ui, files):
    """The user's zones (zone, top, bottom) are listed with what is wrong in them before any question is asked: zones
    that overlap (a question would refuse the file) and zones beyond the log (no sample; said with every answer)."""
    _, c = ui
    las, _ = files
    zones = las.parent / "zones.csv"
    zones.write_text("zone,top,bottom\nUpper,1000,1002\nMiddle,1001.5,1003\nDeep,2000,2100\n")
    status, got = c.json(f"/api/zones?path={zones}&las={las}")
    assert status == 200, got
    assert [(z["name"], z["top"], z["base"]) for z in got["zones"]] == [
        ("Upper", 1000.0, 1002.0), ("Middle", 1001.5, 1003.0), ("Deep", 2000.0, 2100.0)]
    assert [z.get("outside", False) for z in got["zones"]] == [False, False, True]
    assert any(p.startswith("Upper and Middle overlap (1001.5-1002)") for p in got["problems"]), got["problems"]
    assert any(p.startswith("Deep (2000-2100) lies beyond the log (1000-1004 m)") for p in got["problems"]), got["problems"]
    status, up = c.json("/api/upload?kind=zones", raw=zones.read_bytes(), headers={"X-Filename": "zones.csv"})
    assert status == 200 and up["name"].endswith("zones.csv"), up
    assert c.json(f"/api/zones?path={up['path']}&las={las}")[1]["zones"] == got["zones"]   # the stored copy reads the same
    status, bad = c.json(f"/api/zones?path={las.parent / 'none.csv'}")
    assert status == 400 and "no zones file" in bad["error"]
    assert got["overlaps"] == got["problems"][:1]
    # overlapping zones would be refused when the question runs: refused before it waits for a worker
    status, bad = c.json("/api/ask", {"las": str(las), "question": "Mean GR of each of my zones?", "zones": str(zones)})
    assert status == 400 and "zones of zones.csv overlap: Upper and Middle overlap" in bad["error"], bad
    zones.write_text("zone,top,bottom\nUpper,1000,1002\nDeep,2000,2100\n")         # a zone beyond the log: said, not refused
    assert U.A.arguments({"las": str(las), "question": "q?", "zones": str(zones)})["zones"] == str(zones.resolve())
    status, bad = c.json("/api/upload?kind=zones", raw=b"x", headers={"X-Filename": "zones.las"})
    assert status == 400 and "is not a zones file" in bad["error"]


def test_a_scope_is_a_list_of_stretches_or_refused(ui, files):
    """The stretches a question is on, as the user chose them (a choice's scope): a list of texts, for a first question
    or a follow-up; anything else is refused before the queue."""
    A = U.A
    assert A.scope_input(None) is None and A.scope_input([]) is None
    assert A.scope_input([" 874-1250 m ", "Ness Fm."]) == ["874-1250 m", "Ness Fm."]
    for bad in ("874-1250 m", [874, 1250], [""], ["x"] * 13, ["x" * 201]):
        with pytest.raises(A.InputError):
            A.scope_input(bad)
    _, c = ui
    las, _ = files
    status, got = c.json("/api/ask", {"las": str(las), "question": "Mean GR?", "scope": "1000-1002 m"})
    assert status == 400 and "scope must be a list" in got["error"]
    assert A.interval_label({"interval": {"mode": "tops", "formation": "Repeat", "top": "1003.0"}}) == "Repeat from 1003"
    assert A.interval_label({"interval": {"mode": "tops", "formation": "Upper"}}) == "Upper"


def test_a_tops_file_in_feet_labelled_metres_is_said_as_it_loads(ui, files):
    """Formations wholly beyond the log are marked, and when most are but would fit read in the other unit, the file's
    depth unit is said to be the likely fault (question suite U18), before a question waits for a worker."""
    _, c = ui
    las, _ = files
    tops = las.parent / "feet.csv"
    tops.write_text("formation,top,bottom,depth_unit\nA,3281,3287,m\nB,3287,3294,m\nC,1000,1001,m\n")
    status, got = c.json(f"/api/tops?path={tops}&las={las}")
    assert status == 200, got
    assert [r.get("outside", False) for r in got["formations"]] == [True, True, False]
    assert got["fits"]["outside"] == 2 and got["fits"]["of"] == 3
    assert "read in ft they fit it" in got["fits"]["hint"] and "depth unit (m) may be wrong" in got["fits"]["hint"]
    tops.write_text("formation,top,bottom,depth_unit\nA,1000,1002,m\nB,1002,1004,m\n")
    assert "hint" not in c.json(f"/api/tops?path={tops}&las={las}")[1]["fits"]      # on the log: nothing said


def test_the_run_summary_carries_the_question_back_its_notes_and_scope():
    """What the page shows of a run that asked back (status ask_user or outside): the text and the choices to click,
    each a question with the stretch to set first; of any run, the notes before the answer and the stretch it was
    computed on, and whether the user chose it."""
    A = U.A
    choices = [{"label": "Manganui 874-1250 m", "question": "q?", "scope": ["874-1250 m"]}, {"label": "no question"}]
    trace = {"ask_user": "Which Manganui?", "ask_choices": choices}
    got = A.summary(trace, {}, "ask_user")
    assert got["ask"] == {"text": "Which Manganui?", "outside": False, "choices": choices[:1]}
    assert A.summary(trace, {}, "done")["ask"] is None
    trace = {"scope": {"used": ["874-1250 m"], "by": "user"}, "scope_chosen": True}
    assert A.summary(trace, {}, "done")["scope"]["by"] == "your choice"
    trace = {"scope": {"used": ["874-1250 m"]}}
    assert A.summary(trace, {}, "done")["scope"] == {"used": ["874-1250 m"], "by": "the question", "merged": "", "note": ""}


def test_the_page_sends_a_chosen_listing_and_checks_zones_against_the_well():
    """A listing of a name the tops file lists twice is sent with its top; zones loaded for one well are checked again
    when another LAS is loaded."""
    page = (U.STATIC / "index.html").read_text()
    assert "inputs.interval.top = f.row" in _js_function(page, "formInputs")
    assert "loadZones(S.zones.path)" in _js_function(page, "showLas")
    assert "S.formOpts[value] = f" in _js_function(page, "showTops") and "f.repeated.map(" in _js_function(page, "showTops")


def test_config_gives_questions_to_start_with_and_how_long_a_question_takes(ui):
    """The start page's questions are the harness's own examples (C9 outside_examples, with {interval}); the time a
    question usually takes is the median of this server's answered runs of the same kind, once there are three."""
    app, c = ui
    cfg = c.json("/api/config")[1]
    assert cfg["examples"] and all("{interval}" in q for q in cfg["examples"]) and cfg["typical"] == {}
    for k, (secs, route) in enumerate([(30, "direct"), (50, "direct"), (40, "direct"), (600, "investigation"),
                                       (20, "direct")]):
        f = app.store.root / f"20260101-00000{k}-abcdef"
        f.mkdir(parents=True)
        status = "error" if k == 4 else "done"                  # a run that failed does not count
        (f / "run.json").write_text(json.dumps({"id": f.name, "status": status, "elapsed": secs,
                                                "result": {"status": "ok", "route": route}}))
    app._typical = None
    assert c.json("/api/config")[1]["typical"] == {"direct": [40, 3]}      # an investigation needs three runs too


def test_the_sample_wells_come_from_petrophys_each_with_the_tops_that_list_it():
    """The one-click start lists Petrophys's log samples (the harness names none); a tops sample pairs with a well
    when the tops reader finds rows for it: a well column naming it, or the file's name holding the well's."""
    from petrophys.datasets import list_samples
    from petroharness.ask import _las_header
    from petroharness.well.tops import read_tops
    got = U.A.samples()
    assert {r["name"] for r in got} == set(list_samples("logs"))              # every log sample, as Petrophys names it
    for r in got:
        assert Path(r["las"]).is_file() and r["folder"] and r["curves"] > 0 and r["unit"] in ("m", "ft", None)
        if r["tops"]:
            table = read_tops(Path(r["tops"]["path"]), _las_header(Path(r["las"]))[1], None, r["unit"])
            assert table.tops and len(table.names()) == r["tops"]["formations"]
    assert any(r["tops"] for r in got) and not any("lithology" in (r["tops"] or {}).get("name", "") for r in got)


def test_the_start_page_offers_wells_questions_drops_and_progress_in_words():
    page = (U.STATIC / "index.html").read_text()
    start = _js_function(page, "startRender")
    assert "Drop a LAS file here" in start and "Or start with a sample well from Petrophys" in start
    assert "Questions to start with" in start and "suggestions()" in start
    assert 'api("/api/samples")' in page and "S.cfg.examples" in _js_function(page, "suggestions")
    drop = _js_function(page, "dropFiles")
    assert 'upload("las"' in drop and 'upload("tops"' in drop and 'upload("zones"' in drop and 'upload("notes"' in drop
    words = _js_function(page, "nowWords")
    assert "Petrophys is interpreting the well" in words and "of at most" in words and "timeLeft(j, m)" in words
    assert "S.cfg.typical" in _js_function(page, "timeLeft")


def test_a_job_shows_its_call_in_flight_only_while_it_runs():
    """Job.live (the model call as it streams) is in the page's view while the run goes on, never in its record."""
    import time

    from petroharness.ui import adapter as A
    job = A.Job("j1", {"question": "q"}, {})
    assert "live" not in job.view()
    job.set_live({"n": 3, "thinking": "First PHIE."})
    assert job.view()["live"] == {"n": 3, "thinking": "First PHIE."}
    job.set_live({})
    assert "live" not in job.view()
    job.set_live({"n": 4, "thinking": "x"})
    job.finished = time.time()
    assert "live" not in job.view() and "live" not in job.record()


def test_a_step_shows_what_it_produced_and_its_reasoning_in_both_views():
    """The Interpretation page's work lines and the Investigation log's cards build a step from the same parts (what it
    looked at, the results it opened, the findings it added or revised), and each adds the call's reasoning."""
    page = (U.STATIC / "index.html").read_text()
    stage = _js_function(page, "stepStage")
    for part in ('"Points to settle"', '"Looked at"', '"Results"', "claimsWord", '"Harness notes"'):
        assert part in stage
    work, story = _js_function(page, "workHtml"), _js_function(page, "storyPane")
    assert "workParts(c, m, res, calls, finished)" in work and '["Reasoning", th]' in work
    parts = _js_function(page, "workParts")
    assert 'stepStage(c.number, m, res, calls, finished, "Findings")' in parts and "checkerFound(round)" in parts
    assert 'stepStage(k, m, res, calls, finished, "Claims")' in story and "thinkPart(st.main)" in story
    assert story.count('["Reasoning", ') >= 5          # the read, each step, the settle step, the writer, each repair
    assert "workHtml(j, m, finished, res, calls)" in _js_function(page, "mainPane")
    assert "All of its reasoning" in _js_function(page, "thinkPart")


def test_the_reasoning_lines_shown_skip_the_ones_that_only_announce_the_reply():
    """thinkTail drops a line that says nothing about the well (the model announcing its reply) and keeps the rest."""
    import re
    page = (U.STATIC / "index.html").read_text()
    src = re.search(r"^const THINK_SKIP = /(.+)/i;$", page, re.M).group(1)
    skip = re.compile(src, re.I)
    for line in ("Let me write the JSON.", "Let me reply with JSON.", "Now write JSON.", "Now the JSON.", "Reply JSON only.", "I'll output the reply.",
                 "Only JSON.", "Final answer:", "[… 5,201 characters left out …]"):
        assert skip.search(line), line
    for line in ("Now Z8 has the highest RQI, 0.3352 um.", "Reply: the Brent Group holds 20 zones.", "JSON keys: focus, edits, next.",
                 "- C4: revise cite: EXCELLENT_RESERVOIR 35.6% is in E6."):
        assert not skip.search(line), line


def test_a_dropped_finding_keeps_its_small_badge():
    """The badge of a finding edit (+, ~, −) carries the class of its operation, and "drop" is also the class of the
    start page's drop zone: the badge's own rule resets the box that class gives (its border and padding)."""
    import re
    page = (U.STATIC / "index.html").read_text()
    badge = re.search(r"^\.cl \.o \{([^}]*)\}", page, re.M).group(1)
    zone = re.search(r"^\.drop \{([^}]*)\}", page, re.M).group(1)
    assert "padding:" in zone and "border:" in zone                 # what the drop zone sets
    assert "padding: 0;" in badge and "border: 0;" in badge and "width: 18px" in badge
    assert '<span class="o ${esc(e.op)}">' in _js_function(page, "claimEdits")


def test_an_opening_that_introduces_a_list_is_shown_with_its_items():
    """The answer block shows the answer's first two sentences; an opening that ends on a colon before a list would
    stop at the colon, so the list's items follow it, each by its first sentence."""
    page = (U.STATIC / "index.html").read_text()
    assert "leadList(sents, paras[1])" in _js_function(page, "mainPane")
    lead = _js_function(page, "leadList")
    assert "/:$/.test(" in lead and "slice(0, 6)" in lead and "sents.length > 2" in lead


def test_the_composers_button_stops_the_question_in_flight():
    """While a question is waiting or running the composer's one button is Stop, not a disabled Ask: a click posts
    /api/stop/<id>, the button waits ("Stopping") until the run ends, and Enter asks nothing meanwhile. A stopped run
    is no failure on the page: its own box, its status, and the next question of its conversation follows it."""
    page = (U.STATIC / "index.html").read_text()
    button = _js_function(page, "askButton")
    assert "STOP_ICON" in button and "ASK_ICON" in button and '"Stop this question"' in button
    assert "b.disabled = !!(j && stopping)" in button                # enabled while it runs, until Stop is pressed
    assert "askButton(running ? j : null)" in _js_function(page, "chipsRender")
    assert "post(`/api/stop/${j.id}`, {})" in _js_function(page, "stopRun")
    assert '$("#ask").onclick = () => (isRunning() ? stopRun() : ask());' in page
    assert "if (!isRunning() && !$(\"#ask\").disabled) ask();" in page       # Enter never asks over a running question
    assert 'e.name === "stopping"' in _js_function(page, "stoppingNow")       # pressed in another tab: the run says so
    assert 'if (j.status === "stopped") return stoppedBox(j, res);' in _js_function(page, "errorBox")
    assert "No answer was written." in _js_function(page, "stoppedBox")
    assert 'j.status === "stopped" && j.conversation && j.conversation.turn' in _js_function(page, "composerFor")
    assert '"Stopped before it was answered."' in _js_function(page, "turnHtml")
    assert ".status.stopped {" in page and ".stopbox {" in page

