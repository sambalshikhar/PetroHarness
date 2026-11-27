"""Connecting a model (petroharness.connect) and the web UI's Model dialog behind it (/api/model): against small local
servers that play Ollama, a vLLM server that wants a key, and OpenRouter. No network, no download; each test has its own
PetroHarness folder (conftest: PETROHARNESS_HOME)."""

import json
import os
import stat
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_ui_server import _ask, files, serve  # noqa: F401  (files: a fixture)
from ui_stub import StubModel

from petroharness import ask as ASK
from petroharness import connect as C
from petroharness.models import CARDS, card_settings
from petroharness.ui import server as U


def _server(routes):
    """A local HTTP server: routes[(method, path)] -> fn(body, headers) -> (status, obj | list of NDJSON lines)."""
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _go(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            calls.append((method, self.path, body, dict(self.headers)))
            fn = routes.get((method, self.path.split("?")[0]))
            status, obj = fn(body, self.headers) if fn else (404, {"error": "not found"})
            data = (b"".join(json.dumps(x).encode() + b"\n" for x in obj) if isinstance(obj, list)
                    else json.dumps(obj).encode())
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.calls = calls
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    return srv


FINE = {"os": "Linux", "machine": "x86_64", "memory": 64e9, "gpus": [{"kind": "nvidia", "name": "GPU", "free": 40e9}],
        "free_disk": 500e9, "disk_at": "/models"}


@pytest.fixture(autouse=True)
def _this_computer(monkeypatch):
    """A computer that fits WellLogLLM, the same wherever the tests run."""
    monkeypatch.setattr(C, "system", lambda max_age=60: FINE)


@pytest.fixture
def ollama():
    """A stand-in Ollama 0.40.18 that has one other model: a pull adds the model, a create adds the copy."""
    tags = {"other:latest"}

    def pull(body, h):
        tags.add(C._tagged(body["model"]))
        return 200, [{"status": "pulling manifest"}, {"status": "pulling 1a2b", "total": 100, "completed": 40},
                     {"status": "pulling 1a2b", "total": 100, "completed": 100}, {"status": "success"}]

    def create(body, h):
        tags.add(C._tagged(body["model"]))
        return 200, [{"status": "success"}]

    loaded = {}

    def generate(body, h):
        loaded[body["model"]] = {"name": body["model"], "model": body["model"], "size": 100, "size_vram": srv.vram}
        return 200, {"model": body["model"], "done": True, "done_reason": "load"}

    srv = _server({("GET", "/api/version"): lambda b, h: (200, {"version": "0.40.18"}),
                   ("GET", "/api/tags"): lambda b, h: (200, {"models": [{"name": t} for t in sorted(tags)]}),
                   ("POST", "/api/pull"): pull, ("POST", "/api/create"): create, ("POST", "/api/generate"): generate,
                   ("GET", "/api/ps"): lambda b, h: (200, {"models": list(loaded.values())})})
    srv.tags, srv.vram = tags, 100
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def vllm():
    """A stand-in vLLM server that serves welllogllm-7b (64k context) and a small model, to the key sk-test only."""
    def models(body, h):
        if h.get("Authorization") != "Bearer sk-test":
            return 401, {"error": {"message": "Unauthorized"}}
        return 200, {"data": [{"id": "welllogllm-7b", "max_model_len": 65536},
                              {"id": "tiny-chat", "max_model_len": 8192}]}
    srv = _server({("GET", "/v1/models"): models})
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def openrouter(monkeypatch):
    rows = [{"id": "vendor/thinker", "name": "Vendor: Thinker", "context_length": 200000,
             "supported_parameters": ["reasoning", "structured_outputs", "response_format"],
             "pricing": {"prompt": "0.000003", "completion": "0.000015"}, "top_provider": {"max_completion_tokens": 20000},
             "architecture": {"output_modalities": ["text"]}},
            {"id": "vendor/small", "name": "Vendor: Small", "context_length": 32768, "supported_parameters": [],
             "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"output_modalities": ["text"]}},
            {"id": "vendor/painter", "name": "Vendor: Painter", "architecture": {"output_modalities": ["image"]}}]

    def key(body, h):
        ok = h.get("Authorization") == "Bearer sk-or-good"
        return (200, {"data": {"label": "test key", "limit": 10}}) if ok else (401, {"error": {"message": "No auth"}})
    srv = _server({("GET", "/api/v1/models"): lambda b, h: (200, {"data": rows}), ("GET", "/api/v1/key"): key})
    monkeypatch.setattr(C, "OPENROUTER_URL", srv.url + "/api/v1")
    C._OPENROUTER.clear()
    yield srv
    srv.shutdown()
    srv.server_close()
    C._OPENROUTER.clear()


# --- where it keeps things ------------------------------------------------------------------------------------------

def test_the_folder_is_the_test_s_own_and_keys_stay_private(tmp_path):
    assert str(C.home()).startswith(os.environ["PETROHARNESS_HOME"])
    C.keep_key(C.slot("server", "http://h:8000/v1/"), "sk-secret")
    C.keep_key("openrouter", "sk-or-secret")
    path = C.home() / "keys.json"
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600              # readable by its owner only
    state = C.key_state()
    assert state == {"openrouter": True, "openrouter_env": False, "servers": ["http://h:8000/v1"]}
    assert "sk-" not in json.dumps(state)                             # the page is told whether, never what
    C.keep_key("openrouter", None)
    assert not C.key_state()["openrouter"]


def test_a_card_reads_its_key_from_its_own_variable():
    one, two = C.slot("server", "http://a/v1"), C.slot("server", "http://b/v1")
    assert C.key_env(one) != C.key_env(two)                           # runs of an earlier choice keep their key
    assert C.arm(one, "k1") == C.key_env(one) and os.environ[C.key_env(one)] == "k1"
    assert C.arm(two) is None                                         # no key kept, none given


# --- the packaged WellLogLLM cards ----------------------------------------------------------------------------------

def test_the_welllogllm_cards_call_the_model_as_k2_horizon_s_card_does():
    k2 = card_settings("models/k2_horizon_7b.yaml")
    differs = {"model", "label", "base_url"}
    for name, served, label in [("welllogllm_7b", "welllogllm-7b", "WellLogLLM-7B"),
                                ("welllogllm_3_7b", "welllogllm-3.7b", "WellLogLLM-3.7B")]:
        got = card_settings(f"models/{name}.yaml")
        assert (got["model"], got["label"]) == (served, label)
        assert {k: v for k, v in got.items() if k not in differs} == {k: v for k, v in k2.items() if k not in differs}
    for size, g in C.GGUF.items():
        gguf = card_settings(f"models/{g['card']}.yaml")
        assert (gguf["label"], gguf["base_url"]) == (g["label"], "http://localhost:11434/v1")
        assert gguf["model"] == C.ollama_copy_name(f"hf.co/{g['repo']}:{g['quant']}") == f"{g['copy']}:q8_0"
        assert gguf["structured_output"] == "none" and gguf["timeout_s"] > k2["timeout_s"]
        assert {k: v for k, v in gguf.items() if k not in differs | {"structured_output", "timeout_s"}} == \
               {k: v for k, v in k2.items() if k not in differs | {"structured_output", "timeout_s"}}
        assert all(gb > 0 for gb in g["quants"].values()) and (CARDS / f"{g['card']}.yaml").is_file()
    assert C.WELLLOGLLM_GGUF is C.GGUF["3.7b"]


def test_the_vllm_guide_serves_each_model_under_its_card_s_name():
    guide = C.vllm_guide()
    for m in guide["models"]:
        card = card_settings(f"models/{m['served'].replace('-', '_').replace('.', '_')}.yaml")
        assert f"--served-model-name {card['model']} " in m["command"]
        assert f"vllm serve {m['repo']} " in m["command"] and "--reasoning-parser k2_horizon" in m["command"]
        assert f"--max-model-len {C.CONTEXT}" in m["command"]


# --- Ollama -----------------------------------------------------------------------------------------------------------

def test_welllogllm_is_pulled_then_copied_with_the_harness_s_context_once(ollama):
    seen = []
    choice = C.connect({"route": "ollama", "url": ollama.url, "model": "welllogllm", "quant": "Q4_K_M"}, seen.append)
    source = f"hf.co/{C.WELLLOGLLM_GGUF['repo']}:Q4_K_M"
    pulls = [c for c in ollama.calls if c[1] == "/api/pull"]
    creates = [c for c in ollama.calls if c[1] == "/api/create"]
    assert [p[2]["model"] for p in pulls] == [source]
    assert creates[0][2] == {"model": "welllogllm-3.7b:q4_k_m", "from": source, "parameters": {"num_ctx": C.CONTEXT},
                             "stream": True}
    assert any(p.get("total") == 100 and p.get("done") == 40 for p in seen)       # the download's progress
    assert (choice["model"], choice["label"], choice["urls"]) == ("welllogllm-3.7b:q4_k_m", "WellLogLLM-3.7B, GGUF",
                                                                 [ollama.url + "/v1"])
    assert (choice["where"], choice["warnings"]) == ("all on the GPU", [])           # loaded, and Ollama said where
    card = card_settings(choice["model_card"])
    assert (card["model"], card["label"], card["reasoning"]) == ("welllogllm-3.7b:q4_k_m", "WellLogLLM-3.7B, GGUF", True)
    before = len(ollama.calls)
    C.connect({"route": "ollama", "url": ollama.url, "model": "welllogllm", "quant": "Q4_K_M"})
    assert not [c for c in ollama.calls[before:] if c[1] in ("/api/pull", "/api/create")]   # made once


def test_another_ollama_model_gets_a_copy_and_the_card_its_name_calls_for(ollama):
    choice = C.connect({"route": "ollama", "url": ollama.url, "model": "other"})
    assert choice["model"] == "petroharness/other:64k"
    assert not [c for c in ollama.calls if c[1] == "/api/pull"]                   # Ollama had it
    assert card_settings(choice["model_card"])["send_template_kwargs"] is False   # the generic card
    k2 = C.connect({"route": "ollama", "url": ollama.url, "model": "ifm/k2-horizon:3.7b"})
    card = card_settings(k2["model_card"])
    assert card["chat_template_kwargs"] == {"reasoning_effort": "high"} and card["structured_output"] == "none"


def test_ollama_too_old_or_missing_is_said_with_what_to_do(ollama):
    with pytest.raises(ValueError, match=r"does not answer.*FIX: install Ollama.*ollama\.com"):
        C.connect({"route": "ollama", "url": "http://127.0.0.1:9", "model": "welllogllm"})
    old = _server({("GET", "/api/version"): lambda b, h: (200, {"version": "0.39.1"}),
                   ("GET", "/api/tags"): lambda b, h: (200, {"models": []})})
    try:
        with pytest.raises(ValueError, match=r"Ollama 0\.39\.1 is too old for WellLogLLM.*0\.40\.4"):
            C.connect({"route": "ollama", "url": old.url, "model": "welllogllm"})
        assert not [c for c in old.calls if c[1] == "/api/pull"]                    # nothing downloaded first
    finally:
        old.shutdown()
        old.server_close()
    with pytest.raises(ValueError, match="no Q3_K of WellLogLLM"):
        C.connect({"route": "ollama", "url": ollama.url, "model": "welllogllm", "quant": "Q3_K"})
    with pytest.raises(ValueError, match="no WellLogLLM of size 13b"):
        C.connect({"route": "ollama", "url": ollama.url, "model": "welllogllm", "size": "13b"})


def test_on_this_computer_wellogllm_is_the_3_7b_the_7b_is_for_a_gpu_server(ollama):
    assert set(C.GGUF) == {"3.7b"}                                              # no 7B GGUF to run on a CPU
    with pytest.raises(ValueError, match="no WellLogLLM of size 7b"):
        C.connect({"route": "ollama", "url": ollama.url, "model": "welllogllm", "size": "7b"})
    assert "WellLogLLM-7B" in [m["label"] for m in C.vllm_guide()["models"]]  # the 7B: the vLLM command


# --- what is not ideal on this computer ---------------------------------------------------------------------------------

def _computer(monkeypatch, **over):
    monkeypatch.setattr(C, "system", lambda max_age=60: FINE | over)


def test_a_computer_that_fits_says_so(monkeypatch):
    got = {c["name"]: c for c in C.checks("3.7b", "Q8_0")}
    assert {c["state"] for c in got.values()} == {"ok"} and set(got) == {"Memory", "GPU", "Disk"}
    assert "64 GB" in got["Memory"]["text"] and "16 GB" in got["Memory"]["text"]      # needs = 5.4 + 9.7 + 1


def test_little_memory_and_no_gpu_are_warned_with_what_to_do(monkeypatch):
    _computer(monkeypatch, memory=8e9, gpus=[])
    got = {c["name"]: c for c in C.checks("3.7b", "Q8_0")}
    assert got["Memory"]["state"] == "warn" and "8 GB" in got["Memory"]["text"] and "smaller size" in got["Memory"]["text"]
    assert got["GPU"]["state"] == "warn" and got["GPU"]["text"].startswith("No GPU found") and "CPU" in got["GPU"]["text"]
    _computer(monkeypatch, os="Darwin", machine="x86_64", gpus=[])
    assert next(c for c in C.checks("3.7b", "Q8_0") if c["name"] == "GPU")["text"].startswith("This Mac has no Apple")


def test_a_mac_s_shared_memory_and_a_full_gpu_are_warned(monkeypatch):
    _computer(monkeypatch, os="Darwin", machine="arm64", memory=16e9, gpus=[{"kind": "apple", "name": "Apple silicon GPU (Metal)"}])
    gpu = next(c for c in C.checks("3.7b", "Q8_0") if c["name"] == "GPU")
    assert gpu["state"] == "warn" and "the CPU and GPU share" in gpu["text"]
    _computer(monkeypatch, os="Darwin", machine="arm64", memory=64e9, gpus=[{"kind": "apple", "name": "Apple silicon GPU (Metal)"}])
    assert next(c for c in C.checks("3.7b", "Q8_0") if c["name"] == "GPU")["state"] == "ok"
    _computer(monkeypatch, gpus=[{"kind": "nvidia", "name": "Small GPU", "free": 6e9}])
    gpu = next(c for c in C.checks("3.7b", "Q8_0") if c["name"] == "GPU")
    assert gpu["state"] == "warn" and "6 GB free" in gpu["text"]


def test_no_room_to_download_stops_before_the_download(monkeypatch, ollama):
    _computer(monkeypatch, free_disk=2e9)
    disk = next(c for c in C.checks("3.7b", "Q8_0") if c["name"] == "Disk")
    assert disk["state"] == "bad" and "FIX: free some space" in disk["text"]
    with pytest.raises(ValueError, match="free where Ollama keeps models"):
        C.connect({"route": "ollama", "url": ollama.url, "model": "welllogllm"})
    assert not [c for c in ollama.calls if c[1] == "/api/pull"]
    assert not [c for c in C.checks("3.7b", "Q8_0", have=True) if c["name"] == "Disk"]   # downloaded: no download


def test_another_computer_s_ollama_is_not_checked_from_here():
    got = C.checks("3.7b", "Q8_0", url="http://gpu-box:11434")
    assert len(got) == 1 and "another computer" in got[0]["text"]


def test_a_model_partly_on_the_cpu_is_said_after_it_loads(ollama):
    ollama.vram = 60
    choice = C.connect({"route": "ollama", "url": ollama.url, "model": "welllogllm"})
    assert choice["where"] == "60% on the GPU, 40% on the CPU" and "40% of the model on the CPU" in choice["warnings"][-1]
    ollama.vram = 0
    assert C.placement({"size": 10, "size_vram": 0})[0] == "on the CPU"
    assert C.placement({"size": 10, "size_vram": 10}) == ("all on the GPU", None)
    assert C.placement({}) == (None, None)


def test_a_connection_stopped_mid_download_is_cancelled(ollama):
    stop = threading.Event()
    stop.set()
    with pytest.raises(C.Cancelled):
        C.connect({"route": "ollama", "url": ollama.url, "model": "welllogllm"}, cancel=stop)


# --- a server ---------------------------------------------------------------------------------------------------------

def test_a_server_s_key_is_kept_and_its_card_reads_it(vllm):
    with pytest.raises(ValueError, match="401.*FIX: give the server's API key"):
        C.connect({"route": "server", "url": vllm.url + "/v1", "model": "welllogllm-7b"})
    choice = C.connect({"route": "server", "url": vllm.url + "/v1/", "key": "sk-test", "model": "welllogllm-7b"})
    card = card_settings(choice["model_card"])
    assert (card["label"], card["chat_template_kwargs"]) == ("WellLogLLM-7B", {"reasoning_effort": "high"})
    assert card["api_key_env"] == C.key_env(C.slot("server", vllm.url + "/v1")) and os.environ[card["api_key_env"]] == "sk-test"
    assert C.key(C.slot("server", vllm.url + "/v1")) == "sk-test"
    again = C.connect({"route": "server", "url": vllm.url + "/v1", "model": "tiny-chat"})   # the kept key, a new model
    assert card_settings(again["model_card"])["send_template_kwargs"] is False and "65,536" in again["warnings"][0]
    with pytest.raises(ValueError, match="does not serve nothing-here.*welllogllm-7b, tiny-chat"):
        C.connect({"route": "server", "url": vllm.url + "/v1", "model": "nothing-here"})
    with pytest.raises(ValueError, match="http:// or https://"):
        C.server_models("localhost:8000/v1")


# --- OpenRouter ---------------------------------------------------------------------------------------------------------

def test_openrouter_lists_text_models_and_writes_a_hosted_api_card(openrouter):
    rows = {r["id"]: r for r in C.openrouter_models()}
    assert set(rows) == {"vendor/thinker", "vendor/small"}                       # text models only
    assert (rows["vendor/thinker"]["price_in"], rows["vendor/thinker"]["structured"]) == (3.0, "json_schema")
    with pytest.raises(ValueError, match="no OpenRouter API key"):
        C.connect({"route": "openrouter", "model": "vendor/thinker"})
    with pytest.raises(ValueError, match="did not take the key.*401"):
        C.connect({"route": "openrouter", "key": "sk-or-bad", "model": "vendor/thinker"})
    choice = C.connect({"route": "openrouter", "key": "sk-or-good", "model": "vendor/thinker"})
    card = card_settings(choice["model_card"])
    assert (card["structured_output"], card["reasoning"], card["max_tokens_spec"]) == ("json_schema", True, 20000)
    assert (card["send_template_kwargs"], card["send_temperature"], card["replay_reasoning_field"]) == (False, False, False)
    assert os.environ[card["api_key_env"]] == "sk-or-good" and C.key_state()["openrouter"]
    small = C.connect({"route": "openrouter", "model": "vendor/small"})           # the kept key
    assert card_settings(small["model_card"])["structured_output"] == "none" and "32,768" in small["warnings"][0]


# --- the saved choice -------------------------------------------------------------------------------------------------

def test_the_saved_choice_comes_back_with_its_key_and_without_it_in_the_file(vllm, monkeypatch):
    choice = C.connect({"route": "server", "url": vllm.url + "/v1", "key": "sk-test", "model": "welllogllm-7b"})
    C.save_choice(choice | {"request": {"route": "server", "url": vllm.url + "/v1", "model": "welllogllm-7b"}})
    assert "sk-test" not in (C.home() / "model.json").read_text()
    env = card_settings(choice["model_card"])["api_key_env"]
    monkeypatch.delenv(env)
    kept = C.saved()
    assert (kept["label"], kept["urls"]) == ("WellLogLLM-7B", [vllm.url + "/v1"]) and os.environ[env] == "sk-test"
    os.remove(kept["model_card"])
    assert C.saved() is None                                                     # its card is gone: no choice


def test_the_command_uses_the_saved_choice_and_explicit_options_win(vllm, monkeypatch):
    monkeypatch.delenv("PETROHARNESS_MODEL_URL", raising=False)
    choice = C.connect({"route": "server", "url": vllm.url + "/v1", "key": "sk-test", "model": "welllogllm-7b"})
    C.save_choice(choice)
    kw = {"model": None, "model_card": None, "model_url": None}
    ASK.default_model(kw)
    assert (kw["model_card"], kw["model_url"]) == (choice["model_card"], vllm.url + "/v1")
    given = {"model": None, "model_card": "generic", "model_url": "http://h:1/v1"}
    ASK.default_model(given)
    assert given == {"model": None, "model_card": "generic", "model_url": "http://h:1/v1"}


def test_the_command_with_nothing_set_makes_welllogllm_ready_or_says_how(ollama, monkeypatch):
    monkeypatch.delenv("PETROHARNESS_MODEL_URL", raising=False)
    monkeypatch.setattr(C, "OLLAMA_URL", "http://127.0.0.1:9")
    with pytest.raises(ValueError, match="Ollama does not answer.*Or give a model: --model-url"):
        ASK.default_model({"model": None, "model_card": None, "model_url": None})
    monkeypatch.setattr(C, "OLLAMA_URL", ollama.url)
    kw = {"model": None, "model_card": None, "model_url": None}
    ASK.default_model(kw)
    assert kw["model_url"] == ollama.url + "/v1" and card_settings(kw["model_card"])["label"] == "WellLogLLM-3.7B, GGUF"
    assert C.saved()["request"] == {"route": "ollama", "model": "welllogllm"}   # kept: the next run starts with it


# --- the web UI -------------------------------------------------------------------------------------------------------

def _wait(client, state="running", timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        st = client.json("/api/model")[1]
        if (st.get("task") or {}).get("state") != state:
            return st
        time.sleep(0.05)
    raise AssertionError("the connection did not finish")


def test_the_dialog_connects_a_model_and_the_next_questions_use_it(tmp_path, ollama):
    app = U.App(tmp_path / "runs", workers=1, urls=["http://127.0.0.1:9/v1"])
    srv, client = serve(app)
    try:
        st = client.json("/api/model")[1]
        assert st["can_change"] and st["label"] == "K2-Horizon-7B" and st["welllogllm"]["repo"] == C.WELLLOGLLM_GGUF["repo"]
        checked = client.json("/api/model/check", {"route": "ollama", "url": ollama.url})[1]
        assert checked["running"] and checked["new_enough"] and not any(checked["welllogllm"]["3.7b"].values())
        assert {c["name"] for c in checked["checks"]} == {"Memory", "GPU", "Disk"}       # this computer, for 3.7B Q8_0
        assert st["needs"]["3.7b"]["Q8_0"] == C.gguf_needs("3.7b", "Q8_0") and set(st["gguf"]) == {"3.7b"}
        old_pool = app.endpoints
        status, task = client.json("/api/model/connect", {"route": "ollama", "url": ollama.url, "model": "welllogllm"})
        assert status == 200 and task["state"] == "running"
        st = _wait(client)
        assert st["task"]["state"] == "done", st["task"]
        assert (st["label"], st["route"], st["urls"]) == ("WellLogLLM-3.7B, GGUF", "ollama", [ollama.url + "/v1"])
        assert (st["where"], st["warnings"]) == ("all on the GPU", []) and "all on the GPU" in st["task"]["text"]
        assert app.endpoints is not old_pool and app.choice["model_card"].endswith(".yaml")
        assert client.json("/api/config")[1]["label"] == "WellLogLLM-3.7B, GGUF"
        assert C.saved()["label"] == "WellLogLLM-3.7B, GGUF"                     # kept for the next start
        assert client.json("/api/model/check", {"route": "ollama", "url": ollama.url})[1]["welllogllm"]["3.7b"]["Q8_0"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_question_keeps_the_model_it_was_asked_with(tmp_path, ollama, files):
    gate = threading.Event()                                                      # holds the stand-in model's calls
    app = U.App(tmp_path / "runs", workers=1, model_factory=lambda cfg: StubModel(cfg, gate=gate))
    try:
        first = app.submit(_ask(files[0]))
        pool = app.endpoints
        app.use(C.connect({"route": "ollama", "url": ollama.url, "model": "welllogllm"}))
        later = app.submit(_ask(files[0]))
        assert first.pool is pool and later.pool is app.endpoints and later.pool is not pool
        assert "model_card" not in first.kwargs and later.kwargs["model_card"] == app.choice["model_card"]
        assert app.label == "WellLogLLM-3.7B, GGUF"
    finally:
        gate.set()


def test_a_server_others_can_reach_does_not_change_its_model(tmp_path):
    app = U.App(tmp_path / "runs", workers=1, model_factory=lambda cfg: StubModel(cfg))
    srv, client = serve(app)
    srv.RequestHandlerClass.loopback = False
    srv.RequestHandlerClass.allow_hosts = frozenset({"127.0.0.1"})
    try:
        assert client.json("/api/model")[1]["can_change"] is False
        for path, body in [("/api/model/connect", {"route": "ollama"}), ("/api/model/check", {"route": "ollama"}),
                           ("/api/model/forget", {"route": "openrouter"}), ("/api/model/stop", {})]:
            status, got = client.json(path, body)
            assert status == 403 and "cannot change its model" in got["error"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_wrong_choice_is_said_in_the_dialog(tmp_path):
    app = U.App(tmp_path / "runs", workers=1, model_factory=lambda cfg: StubModel(cfg))
    srv, client = serve(app)
    try:
        client.json("/api/model/connect", {"route": "server", "url": "http://127.0.0.1:9/v1", "model": "m"})
        st = _wait(client)
        assert st["task"]["state"] == "error" and "did not answer" in st["task"]["text"]
        assert client.json("/api/model/connect", {"route": "nowhere"})[0] == 200
        assert "route ollama, server or openrouter" in _wait(client)["task"]["text"]
        status, got = client.json("/api/model/check", {"route": "nowhere"})
        assert status == 400 and "route ollama, server or openrouter" in got["error"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_endpoints_health_check_carries_the_card_s_key(vllm, monkeypatch):
    monkeypatch.setenv("PETROHARNESS_KEY_TEST", "sk-test")
    assert U.Endpoints([vllm.url + "/v1"], "welllogllm-7b", key_env="PETROHARNESS_KEY_TEST").health()[0]["ok"]
    assert not U.Endpoints([vllm.url + "/v1"], "welllogllm-7b").health()[0]["ok"]          # no key: 401


def test_the_ui_without_a_model_starts_on_welllogllm_in_ollama(tmp_path, monkeypatch, ollama):
    monkeypatch.delenv("PETROHARNESS_MODEL_URL", raising=False)
    monkeypatch.setattr(C, "OLLAMA_URL", ollama.url)
    started = {}
    monkeypatch.setattr(U, "make_servers", lambda app, *a, **k: started.setdefault("app", app) and [_Stop()])
    assert U.main(["--runs", str(tmp_path / "r")]) == 0
    app = started["app"]
    assert app.label == "WellLogLLM-3.7B, GGUF" and app.route == "ollama"
    end = time.time() + 30
    while app.setup.get("state") == "running" and time.time() < end:
        time.sleep(0.05)
    assert app.setup["state"] == "done" and [c[2]["model"] for c in ollama.calls if c[1] == "/api/pull"] == \
        [f"hf.co/{C.WELLLOGLLM_GGUF['repo']}:{C.WELLLOGLLM_GGUF['quant']}"]


class _Stop:
    """A server that stops at once (main's serve_forever returns as on Ctrl-C)."""
    server_address = ("127.0.0.1", 7860)

    def serve_forever(self):
        raise KeyboardInterrupt


def test_the_page_has_the_model_dialog_and_never_shows_a_key():
    page = (U.STATIC / "index.html").read_text(encoding="utf-8")
    for fn in ("modelOpen", "mOllama", "mServer", "mRouter", "modelGo", "setupBar", "mHave"):
        assert f"function {fn}(" in page
    assert 'id="modelbtn"' in page and 'id="setupbar"' in page
    assert "type=\"password\" id=\"mskey\"" in page and "type=\"password\" id=\"mokey\"" in page
    # once sent, a key is cleared from the page; the state it reads back says only whether one is kept
    assert 'M.srv.key = ""; M.or.key = "";' in page
