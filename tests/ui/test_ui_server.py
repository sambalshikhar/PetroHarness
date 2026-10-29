"""The web UI's server (src/petroharness/ui/server.py) without a model: the page and its images, uploads, a LAS file's
header, the formations a tops file names, the checks on the inputs, the model endpoints' health and choice, and the
`petroharness ui` command.

    python -m pytest tests/ui -q
"""
import json
import sys
import threading
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


def test_the_tops_listing(ui, files):
    _, c = ui
    las, tops = files
    status, got = c.json(f"/api/tops?path={tops}&las={las}")
    assert status == 200, got
    rows = {r["name"]: r for r in got["formations"]}
    assert list(rows) == ["Upper", "Lower", "Repeat"]
    assert (rows["Upper"]["top"], rows["Upper"]["base"], rows["Upper"]["base_from"]) == (1000.0, 1002.0, "stated base")
    assert (rows["Lower"]["base"], rows["Lower"]["base_from"]) == (1003.0, "next top Repeat")
    assert [r["top"] for r in rows["Repeat"]["repeated"]] == [1000.5, 1003.0]        # asked about by its depths
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
    got = A.arguments(_ask(las, interval={"mode": "depths", "top": "1001", "base": "", "unit": "M", "name": " sand "},
                           skills="default"))
    assert (got["top"], got["base"], got["depth_unit"], got["formation"]) == (1001.0, None, "m", "sand")
    assert "skills" not in got
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
    assert U.served_model() == "k2-horizon-7b-grpo200"


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
    monkeypatch.setattr(U, "served_model", lambda: "m")
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
