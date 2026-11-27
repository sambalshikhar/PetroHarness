"""Connect a model: the ways a person running PetroHarness plugs in the model that answers, and the choice they keep.

    ollama      a model on this computer, run by Ollama: WellLogLLM-3.7B or -7B as a GGUF from Hugging Face, or any
                model Ollama can pull. PetroHarness makes a copy of it with the context window the harness needs
                (CONTEXT), loads it, and says where Ollama runs it (the GPU: Apple silicon through Metal, NVIDIA, AMD;
                or the CPU) and what on this computer is not ideal for it (checks()).
    server      a vLLM server, or any OpenAI-compatible endpoint, with its API key if it has one.
    openrouter  a hosted model through OpenRouter, with your OpenRouter API key.

The web UI's Model dialog uses it (petroharness.ui.server, /api/model); the command and the web UI start with the
saved choice when no model option and no PETROHARNESS_MODEL_URL are given (saved()). Benchmark mode never reads it.

What it keeps, in home(): model.json (the choice), cards/ (the model card written for it) and keys.json (the API keys,
readable by you only). A key goes to the endpoint it belongs to and nowhere else: the page is told only whether a key
is kept. A run reads its key from the environment variable its card names (api_key_env); arm() sets that variable in
this process from keys.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import yaml

CONTEXT = 65536                         # the context window the harness needs: prompts reach about 40,000 tokens
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_DOWNLOAD = "https://ollama.com/download"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
OPENROUTER_KEYS = "https://openrouter.ai/keys"

# WellLogLLM as GGUF files, by size: the Hugging Face repository Ollama pulls them from, each quantization's download
# size in GB, the name of PetroHarness's copy in Ollama, the packaged card, and the Ollama release that first runs their
# architecture (K2-Horizon).
GGUF = {
    "3.7b": {"label": "WellLogLLM-3.7B, GGUF", "repo": "sambal/WellLogLLM-3.7B-GGUF", "copy": "welllogllm-3.7b",
             "quants": {"Q8_0": 5.4, "Q6_K": 4.2, "Q5_K_M": 3.6, "Q4_K_M": 3.2},   # the files: 5.39, 4.16, 3.64, 3.16 GB
             "quant": "Q8_0", "ollama": "0.40.4", "card": "welllogllm_3_7b_gguf"},
    "7b": {"label": "WellLogLLM-7B, GGUF", "repo": "sambal/WellLogLLM-7B-GGUF", "copy": "welllogllm-7b",
           "quants": {"Q8_0": 9.6, "Q6_K": 7.4, "Q5_K_M": 6.5, "Q4_K_M": 5.6},   # the files: 9.57, 7.39, 6.47, 5.59 GB
           "quant": "Q8_0", "ollama": "0.40.4", "card": "welllogllm_7b_gguf"},
}
WELLLOGLLM_GGUF = GGUF["3.7b"]          # the default: the one PetroHarness starts with when no model is set
# Both WellLogLLM models keep 147,456 bytes of context cache a token at 16 bits (36 layers, 8 key-value heads of 128):
# about 9.7 GB at CONTEXT, on top of the weights. With the runtime's own buffers, what a GGUF needs in memory.
KV_BYTES_PER_TOKEN = 147456
OVERHEAD_GB = 1.0


def gguf_needs(size: str, quant: str) -> float:
    """The memory WellLogLLM's GGUF of this size and quantization needs at the harness's context, in GB."""
    return round(GGUF[size]["quants"][quant] + KV_BYTES_PER_TOKEN * CONTEXT / 1e9 + OVERHEAD_GB, 1)
# WellLogLLM on a vLLM server (vllm_guide()): each model's Hugging Face repository, its served name (that of its packaged
# card) and the GPU memory it needs at the harness's context window.
VLLM_MODELS = [
    {"label": "WellLogLLM-7B", "repo": "sambal/WellLogLLM-7B", "served": "welllogllm-7b", "gpu": "40 GB"},
    {"label": "WellLogLLM-3.7B", "repo": "sambal/WellLogLLM-3.7B", "served": "welllogllm-3.7b", "gpu": "24 GB"},
]
VLLM_URL = "http://localhost:8000/v1"
# How the harness calls a server's model: the packaged card a choice starts from (resources/models).
KINDS = {"welllogllm": "welllogllm_7b", "generic": "generic"}
NAMED = re.compile(r"welllog|k2.*horizon|k2h", re.I)     # a model of the WellLogLLM / K2-Horizon family, by its name
ProgressFn = Callable[[dict], None]


class Cancelled(Exception):
    """The person stopped the connection (a pull in progress is abandoned)."""


# --- where it keeps what it is told ---------------------------------------------------------------------------------

def home() -> Path:
    """PetroHarness's folder for this user: PETROHARNESS_HOME, else the system's place for an application's settings."""
    if os.environ.get("PETROHARNESS_HOME", "").strip():
        return Path(os.environ["PETROHARNESS_HOME"]).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "PetroHarness"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PetroHarness"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "petroharness"


def _write_private(path: Path, text: str) -> None:
    """A file only its owner can read (on Windows, the user's profile folder keeps it to the user)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _keys() -> dict:
    try:
        return json.loads((home() / "keys.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def slot(route: str, url: str = "") -> str:
    """Where a key is kept: "openrouter", or "server <url>" for a server."""
    return "openrouter" if route == "openrouter" else f"server {url.rstrip('/')}"


def key(slot_name: str) -> Optional[str]:
    """The key kept for a slot; for OpenRouter, OPENROUTER_API_KEY when none is kept."""
    kept = _keys().get(slot_name)
    if kept:
        return kept
    return os.environ.get("OPENROUTER_API_KEY") or None if slot_name == "openrouter" else None


def keep_key(slot_name: str, value: Optional[str]) -> None:
    """Keep a key for a slot (None or "" forgets it)."""
    keys = _keys()
    if value:
        keys[slot_name] = value
    else:
        keys.pop(slot_name, None)
    _write_private(home() / "keys.json", json.dumps(keys, indent=1))


def key_env(slot_name: str) -> str:
    """The environment variable a card reads its key from: one per slot, so that runs of an earlier choice keep theirs."""
    return "PETROHARNESS_KEY_" + hashlib.sha1(slot_name.encode()).hexdigest()[:10].upper()


def arm(slot_name: str, value: Optional[str] = None) -> Optional[str]:
    """Set the slot's variable in this process to its key (`value`, else the kept one); the variable's name, or None
    when there is no key."""
    value = value or key(slot_name)
    if not value:
        return None
    name = key_env(slot_name)
    os.environ[name] = value
    return name


def key_state() -> dict:
    """Which keys are kept (never the keys): {"openrouter": bool, "servers": [url, ...], "openrouter_env": bool}."""
    keys = _keys()
    return {"openrouter": bool(keys.get("openrouter")), "openrouter_env": bool(os.environ.get("OPENROUTER_API_KEY")),
            "servers": sorted(k.split(" ", 1)[1] for k in keys if k.startswith("server "))}


# --- the saved choice ------------------------------------------------------------------------------------------------

def save_choice(choice: dict) -> None:
    """Keep the choice for the next start (no key in it: keys stay in keys.json)."""
    keep = {k: choice[k] for k in ("route", "label", "model", "model_card", "urls", "slot", "ollama", "quant", "size",
                                   "request")
            if choice.get(k) is not None}
    keep["saved"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_private(home() / "model.json", json.dumps(keep, indent=1))


def saved() -> Optional[dict]:
    """The saved choice, ready to run: {model_card, urls, label, route, ...} with its key set in this process; None
    when there is none, or its card is gone."""
    try:
        choice = json.loads((home() / "model.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    card = choice.get("model_card")
    if not card or not choice.get("urls"):
        return None
    from petroharness.models import card_file
    try:
        card_file(card)
    except ValueError:
        return None
    if choice.get("slot"):
        arm(choice["slot"])
    return choice


# --- model cards -----------------------------------------------------------------------------------------------------

def packaged(name: str) -> dict:
    """A packaged card's `model` section, as written (resources/models/<name>.yaml)."""
    from petroharness.models import CARDS
    return dict(yaml.safe_load((CARDS / f"{name}.yaml").read_text(encoding="utf-8"))["model"])


def kind_of(model: str, kind: str = "auto") -> str:
    """How the harness calls a model: the kind asked, or for "auto" the WellLogLLM card for a model of that family
    (WellLogLLM, K2-Horizon) by its name, else the generic one."""
    if kind in KINDS:
        return kind
    if kind != "auto":
        raise ValueError(f"WHAT: no way to call a model named {kind!r}. FIX: auto, welllogllm or generic.")
    return "welllogllm" if NAMED.search(model or "") else "generic"


def write_card(stem: str, fields: dict, note: str) -> str:
    """Write a model card under home()/cards and check it as a run would; its path."""
    from petroharness.models import card_settings
    fields = {k: v for k, v in fields.items() if k != "base_url"}
    path = home() / "cards" / (re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-") + ".yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Written by PetroHarness ({note}). The fields: docs/MODELS.md\n"
                    + yaml.safe_dump({"model": fields}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    card_settings(str(path))
    return str(path)


def openrouter_fields(row: dict) -> dict:
    """A hosted model's card fields from what OpenRouter says of it: no fields the API does not know, the model's own
    sampling, JSON as the model allows, output caps within its limit."""
    cap = 32768 if row.get("reasoning") else 16384
    if row.get("max_out"):
        cap = min(cap, int(row["max_out"]))
    return {"model": row["id"], "label": row.get("name") or row["id"], "reasoning": bool(row.get("reasoning")),
            "send_template_kwargs": False, "send_temperature": False, "max_tokens_param": "max_tokens",
            "structured_output": row.get("structured") or "none", "replay_reasoning_field": False,
            "max_tokens_spec": cap, "max_tokens_writer": cap, "timeout_s": 1800, "max_retries": 2}


# --- HTTP ------------------------------------------------------------------------------------------------------------

def _open(url: str, body: Optional[dict] = None, token: Optional[str] = None, timeout: float = 10):
    headers = {"Accept": "application/json", "User-Agent": "petroharness"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def _json(url: str, body: Optional[dict] = None, token: Optional[str] = None, timeout: float = 10):
    with _open(url, body, token, timeout) as r:
        return json.loads(r.read() or b"{}")


def _said(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = json.loads(exc.read() or b"{}")
            detail = detail.get("error") if isinstance(detail, dict) else detail
            detail = detail.get("message") if isinstance(detail, dict) else detail
        except ValueError:
            detail = ""
        return f"HTTP {exc.code}" + (f": {str(detail)[:200]}" if detail else "")
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)
    return f"{type(exc).__name__}: {str(exc)[:200]}"


# --- Ollama ----------------------------------------------------------------------------------------------------------

def _version(text: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:3])


def _tagged(name: str) -> str:
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"


def ollama_status(url: str = OLLAMA_URL) -> dict:
    """Whether Ollama answers at url, its version and the models it has."""
    url = (url or OLLAMA_URL).rstrip("/")
    out = {"url": url, "download": OLLAMA_DOWNLOAD, "needs": WELLLOGLLM_GGUF["ollama"], "local": _loopback(url)}
    try:
        out["version"] = _json(url + "/api/version", timeout=4).get("version", "")
        out["models"] = [m.get("name") or m.get("model") for m in _json(url + "/api/tags", timeout=8).get("models", [])]
    except Exception as exc:  # noqa: BLE001  (not running, or not Ollama: said as such)
        return out | {"running": False, "error": _said(exc)}
    out["running"] = True
    out["new_enough"] = _version(out["version"]) >= _version(WELLLOGLLM_GGUF["ollama"])
    return out


def _stream(url: str, body: dict, on_line: Callable[[dict], None], cancel: Optional[threading.Event]) -> None:
    """POST to an Ollama route that answers in NDJSON lines; an "error" line is raised."""
    with _open(url, body, timeout=60) as r:
        for raw in r:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if not raw.strip():
                continue
            line = json.loads(raw)
            if line.get("error"):
                raise ValueError(f"WHAT: Ollama said: {line['error']}.")
            on_line(line)


def ollama_copy_name(source: str) -> str:
    """The name of the copy PetroHarness makes of an Ollama model, with the harness's context window."""
    for g in GGUF.values():
        m = re.fullmatch(r"hf\.co/" + re.escape(g["repo"]) + r":(\w+)", source, re.I)
        if m:
            return f"{g['copy']}:{m.group(1).lower()}"
    return "petroharness/" + re.sub(r"[^a-z0-9._-]+", "-", source.lower()).strip("-") + ":64k"


def ollama_ensure(url: str, source: str, report: ProgressFn, cancel: Optional[threading.Event] = None,
                  what: str = "") -> str:
    """The model `source` in Ollama at url, as a copy with the harness's context window: pulled first when Ollama does
    not have it, the copy made once. The copy's name."""
    url = (url or OLLAMA_URL).rstrip("/")
    st = ollama_status(url)
    if not st["running"]:
        raise ValueError(f"WHAT: Ollama does not answer at {url} ({st['error']}). FIX: install Ollama "
                         f"({OLLAMA_DOWNLOAD}) and start it, or give the address it listens on.")
    have = {_tagged(m) for m in st["models"]}
    name = ollama_copy_name(source)
    if _tagged(name) in have:
        return name
    what = what or source
    if _tagged(source) not in have:
        report({"text": f"Downloading {what}", "done": 0, "total": 0})

        def pulled(line: dict) -> None:
            if line.get("total"):
                report({"text": f"Downloading {what}", "done": line.get("completed", 0), "total": line["total"]})
            elif line.get("status"):
                report({"text": f"{what}: {line['status']}"})
        _stream(url + "/api/pull", {"model": source, "stream": True}, pulled, cancel)
    report({"text": f"Making the copy with a {CONTEXT // 1024}k-token context: {name}"})
    _stream(url + "/api/create", {"model": name, "from": source, "parameters": {"num_ctx": CONTEXT}, "stream": True},
            lambda line: None, cancel)
    return name


# --- this computer: what is not ideal for running a model on it ------------------------------------------------------

_SYSTEM: dict = {}


def _loopback(url: str) -> bool:
    from urllib.parse import urlparse
    return (urlparse(url or OLLAMA_URL).hostname or "") in ("127.0.0.1", "localhost", "::1")


def _memory() -> Optional[int]:
    """This computer's memory, in bytes (None where it cannot be read)."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        elif sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip())
        elif sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                           [(n, ctypes.c_ulonglong) for n in ("total", "avail", "page", "page_avail", "virt",
                                                              "virt_avail", "ext")]
            st = Status()
            st.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return int(st.total)
    except Exception:  # noqa: BLE001  (unknown: not checked)
        return None
    return None


def _gpus() -> list:
    """The GPUs Ollama can run a model on here: [{kind: apple | nvidia | amd, name, free (bytes, NVIDIA only)}]."""
    if sys.platform == "darwin":
        return [{"kind": "apple", "name": "Apple silicon GPU (Metal)"}] if platform.machine() == "arm64" else []
    out = []
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            got = subprocess.run([smi, "--query-gpu=name,memory.free", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=8).stdout
            for line in got.strip().splitlines():
                name, free = (x.strip() for x in line.rsplit(",", 1))
                out.append({"kind": "nvidia", "name": name, "free": int(float(free)) * 2 ** 20})
        except Exception:  # noqa: BLE001  (nvidia-smi present but not answering: no GPU counted)
            out = []
    if not out and sys.platform.startswith("linux") and os.path.exists("/dev/kfd"):
        out.append({"kind": "amd", "name": "AMD GPU (ROCm)"})
    return out


def _ollama_models() -> Path:
    """Where Ollama keeps its models: OLLAMA_MODELS, else its default folder."""
    if os.environ.get("OLLAMA_MODELS"):
        return Path(os.environ["OLLAMA_MODELS"]).expanduser()
    service = Path("/usr/share/ollama/.ollama/models")             # the Linux install script's service
    return service if sys.platform.startswith("linux") and service.exists() else Path.home() / ".ollama" / "models"


def system(max_age: float = 60) -> dict:
    """This computer, as running a model goes: {os, machine, memory, gpus, free_disk, disk_at}, kept max_age s."""
    if _SYSTEM and time.time() - _SYSTEM["t"] < max_age:
        return _SYSTEM["value"]
    where = _ollama_models()
    probe = next((p for p in [where, *where.parents] if p.exists()), Path.home())
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        free = None
    value = {"os": platform.system(), "machine": platform.machine(), "memory": _memory(), "gpus": _gpus(),
             "free_disk": free, "disk_at": str(where)}
    _SYSTEM.update(t=time.time(), value=value)
    return value


def checks(size: str, quant: str, url: str = OLLAMA_URL, have: bool = False) -> list:
    """What on this computer is fine for WellLogLLM's GGUF of this size and quantization at the harness's context, and
    what is not ideal, each with what to do: [{name, state: ok | warn | bad, text}]. "bad" stops a connection (no room
    to download); "warn" lets it go on. Only for Ollama on this computer: another computer is not seen from here."""
    g = GGUF[size]
    if not _loopback(url):
        return [{"name": "This computer", "state": "ok", "text": "Ollama runs on another computer: its memory and GPU "
                                                                  "are not checked from here."}]
    sy, need, file_gb = system(), gguf_needs(size, quant), g["quants"][quant]
    what = f"{g['label'].split(',')[0]} {quant}"
    out = []
    mem = sy["memory"] / 1e9 if sy["memory"] else None
    if mem is None:
        out.append({"name": "Memory", "state": "ok", "text": f"Not read on this system; {what} needs about "
                                                             f"{need:.0f} GB with the harness's 64k-token context."})
    elif mem < need:
        out.append({"name": "Memory", "state": "warn",
                    "text": f"This computer has {mem:.0f} GB; {what} needs about {need:.0f} GB with the harness's "
                            "64k-token context, so it may not load, or run very slowly. Choose a smaller size, or "
                            "run the model on a computer with more memory."})
    else:
        out.append({"name": "Memory", "state": "ok", "text": f"{mem:.0f} GB, for about {need:.0f} GB the model needs."})
    gpus = sy["gpus"]
    kinds = {x["kind"] for x in gpus}
    if not gpus:
        mac = sy["os"] == "Darwin"
        out.append({"name": "GPU", "state": "warn",
                    "text": ("This Mac has no Apple silicon GPU" if mac else "No GPU found") + ": Ollama runs the "
                            "model on the CPU, far more slowly than on a GPU. It works; a question takes much longer."})
    elif "apple" in kinds:
        if mem and need > 0.65 * mem:
            out.append({"name": "GPU", "state": "warn",
                        "text": f"Apple silicon GPU (Metal). The model and its context, about {need:.0f} GB, take "
                                f"most of the {mem:.0f} GB the CPU and GPU share: Ollama may run part of it on the "
                                "CPU, which is slower. Close other programs, or choose a smaller size."})
        else:
            out.append({"name": "GPU", "state": "ok", "text": "Apple silicon GPU: Ollama runs the model on it, "
                                                              "through Metal."})
    elif "nvidia" in kinds:
        free = sum(x.get("free") or 0 for x in gpus) / 1e9
        names = ", ".join(sorted({x["name"] for x in gpus}))
        if free < need:
            out.append({"name": "GPU", "state": "warn",
                        "text": f"{names}: {free:.0f} GB free, and the model with its context needs about "
                                f"{need:.0f} GB, so Ollama runs part of it on the CPU, which is slower. Close programs "
                                "that use the GPU, or choose a smaller size."})
        else:
            out.append({"name": "GPU", "state": "ok", "text": f"{names}, {free:.0f} GB free."})
    else:
        out.append({"name": "GPU", "state": "ok", "text": "AMD GPU found: Ollama runs the model on it where its "
                                                          "ROCm build supports the card."})
    if not have and sy["free_disk"] is not None:
        free_disk = sy["free_disk"] / 1e9
        if free_disk < file_gb + 1:
            out.append({"name": "Disk", "state": "bad",
                        "text": f"The download is {file_gb} GB and {free_disk:.1f} GB is free where Ollama keeps "
                                f"models ({sy['disk_at']}). FIX: free some space, or choose a smaller size."})
        else:
            out.append({"name": "Disk", "state": "ok",
                        "text": f"{free_disk:.0f} GB free for the {file_gb} GB download."})
    return out


def ollama_load(url: str, name: str, report: ProgressFn) -> dict:
    """Load the model in Ollama (as a question would), so that Ollama says where it put it: {size, size_vram}."""
    url = url.rstrip("/")
    report({"text": f"Loading {name} in Ollama"})
    try:
        _json(url + "/api/generate", {"model": name, "stream": False, "keep_alive": "10m"}, timeout=900)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"WHAT: Ollama could not load {name} ({_said(exc)}). FIX: choose a smaller size, or close "
                         "programs that use memory.") from None
    try:
        for m in _json(url + "/api/ps", timeout=10).get("models", []):
            if name in (m.get("name"), m.get("model")):
                return {"size": m.get("size"), "size_vram": m.get("size_vram")}
    except Exception:  # noqa: BLE001  (where it runs is then not said)
        pass
    return {}


def placement(loaded: dict, local: bool = True) -> tuple:
    """Where Ollama runs the loaded model, in words, and a warning when that is not ideal (or None)."""
    size, vram = loaded.get("size"), loaded.get("size_vram")
    if not size:
        return None, None
    apple = local and system()["os"] == "Darwin" and platform.machine() == "arm64"
    gpu = "the Mac's GPU (Metal)" if apple else "the GPU"
    share = (vram or 0) / size
    if share >= 0.99:
        return f"all on {gpu}", None
    if share <= 0.01:
        return "on the CPU", ("Ollama runs the model on the CPU: a question takes far longer than on a GPU. On a "
                              "computer with a GPU (Apple silicon, NVIDIA or AMD), Ollama uses it.")
    pct = round(100 * share)
    return (f"{pct}% on {gpu}, {100 - pct}% on the CPU",
            f"Ollama put {100 - pct}% of the model on the CPU, as the rest did not fit in {gpu}'s memory: answers "
            "come more slowly. Close other programs, or choose a smaller size.")


# --- a server --------------------------------------------------------------------------------------------------------

def server_models(url: str, token: Optional[str] = None) -> list:
    """The models an OpenAI-compatible server lists at /models: [{id, context}] (context where it says, as vLLM does)."""
    url = url.strip().rstrip("/")
    if not re.match(r"https?://", url):
        raise ValueError("WHAT: the server's address. FIX: give it with http:// or https://, ending in /v1 "
                         "(for example http://localhost:8000/v1).")
    try:
        data = _json(url + "/models", token=token, timeout=8)
    except Exception as exc:  # noqa: BLE001
        hint = " FIX: give the server's API key." if "401" in _said(exc) or "403" in _said(exc) else \
               " FIX: check the address (it ends in /v1) and that the server runs."
        raise ValueError(f"WHAT: {url}/models did not answer ({_said(exc)}).{hint}") from None
    return [{"id": m.get("id"), "context": m.get("max_model_len") or m.get("context_length")}
            for m in data.get("data", []) if m.get("id")]


def vllm_guide(port: int = 8000) -> dict:
    """How to serve WellLogLLM with vLLM, as the Model dialog and the docs show it: the install line, and for each
    model the command that serves it under its packaged card's name."""
    def command(m: dict) -> str:
        return (f"vllm serve {m['repo']} --served-model-name {m['served']} --port {port} \\\n"
                f"  --max-model-len {CONTEXT} --trust-remote-code \\\n"
                "  --reasoning-parser k2_horizon --chat-template-content-format string")
    return {"install": 'pip install "vllm>=0.30"', "url": VLLM_URL.replace("8000", str(port)),
            "needs": "Linux with an NVIDIA GPU", "models": [m | {"command": command(m)} for m in VLLM_MODELS]}


# --- OpenRouter ------------------------------------------------------------------------------------------------------

_OPENROUTER: dict = {}


def openrouter_models(max_age: float = 600) -> list:
    """OpenRouter's text models: [{id, name, context, price_in, price_out (USD per million tokens), reasoning,
    structured, max_out}], kept for max_age seconds."""
    if _OPENROUTER and time.time() - _OPENROUTER["t"] < max_age:
        return _OPENROUTER["rows"]
    try:
        data = _json(OPENROUTER_URL + "/models", timeout=20).get("data", [])
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"WHAT: OpenRouter's model list did not come ({_said(exc)}). FIX: check the connection, "
                         "then try again.") from None
    rows = []
    for m in data:
        if "text" not in ((m.get("architecture") or {}).get("output_modalities") or ["text"]):
            continue
        params = set(m.get("supported_parameters") or [])
        price = m.get("pricing") or {}

        def per_m(v):
            try:
                return round(float(v) * 1e6, 3)
            except (TypeError, ValueError):
                return None
        rows.append({"id": m["id"], "name": m.get("name") or m["id"], "context": m.get("context_length"),
                     "price_in": per_m(price.get("prompt")), "price_out": per_m(price.get("completion")),
                     "reasoning": bool(params & {"reasoning", "include_reasoning"}),
                     "structured": "json_schema" if "structured_outputs" in params
                     else "json_object" if "response_format" in params else "none",
                     "max_out": (m.get("top_provider") or {}).get("max_completion_tokens")})
    rows.sort(key=lambda r: r["name"].lower())
    _OPENROUTER.update(t=time.time(), rows=rows)
    return rows


def openrouter_check(token: str) -> dict:
    """Whether OpenRouter takes the key: its label and credit limit as OpenRouter says them."""
    try:
        data = _json(OPENROUTER_URL + "/key", token=token, timeout=10).get("data", {})
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"WHAT: OpenRouter did not take the key ({_said(exc)}). FIX: copy the key again from "
                         f"{OPENROUTER_KEYS}.") from None
    return {"label": data.get("label"), "limit": data.get("limit"), "usage": data.get("usage")}


# --- connect ---------------------------------------------------------------------------------------------------------

def connect(body: dict, report: ProgressFn = lambda p: None, cancel: Optional[threading.Event] = None) -> dict:
    """Make the choice in `body` ready to answer: the key kept when asked, the model pulled and copied (Ollama), its
    card written. What a run needs: {model_card, urls, label, model, route, slot?, warning?}. A choice that cannot
    work raises ValueError (WHAT/FIX); Cancelled when stopped.

    body: {route: "ollama", url?, model: "welllogllm" | an Ollama model's name, quant?}
          {route: "server", url, key?, remember?, model, kind?: auto | welllogllm | generic}
          {route: "openrouter", key?, remember?, model}"""
    route = body.get("route")
    if route == "ollama":
        return _connect_ollama(body, report, cancel)
    if route == "server":
        return _connect_server(body, report)
    if route == "openrouter":
        return _connect_openrouter(body, report)
    raise ValueError("WHAT: where the model runs. FIX: route ollama, server or openrouter.")


def _connect_ollama(body: dict, report: ProgressFn, cancel) -> dict:
    url = (body.get("url") or OLLAMA_URL).strip().rstrip("/")
    asked = (body.get("model") or "welllogllm").strip()
    warnings: list = []
    if asked == "welllogllm":
        size = (body.get("size") or "3.7b").lower()
        if size not in GGUF:
            raise ValueError(f"WHAT: no WellLogLLM of size {size}. FIX: one of {', '.join(GGUF)}.")
        g = GGUF[size]
        quant = body.get("quant") or g["quant"]
        if quant not in g["quants"]:
            raise ValueError(f"WHAT: no {quant} of {g['label'].split(',')[0]}. FIX: one of {', '.join(g['quants'])}.")
        st = ollama_status(url)
        if st["running"] and not st["new_enough"]:
            raise ValueError(f"WHAT: Ollama {st['version']} is too old for WellLogLLM. FIX: update it to "
                             f"{g['ollama']} or later ({OLLAMA_DOWNLOAD}).")
        source = f"hf.co/{g['repo']}:{quant}"
        have = st.get("running") and any(_tagged(m).lower() in (_tagged(source).lower(), _tagged(ollama_copy_name(source)))
                                         for m in st.get("models") or [])
        found = checks(size, quant, url, have=bool(have))
        stop = [c for c in found if c["state"] == "bad"]
        if stop:
            raise ValueError("WHAT: " + " ".join(c["text"] for c in stop))
        warnings = [c["text"] for c in found if c["state"] == "warn"]
        name = ollama_ensure(url, source, report, cancel, what=f"{g['label']} ({quant}, about {g['quants'][quant]} GB)")
        fields = packaged(g["card"]) | {"model": name, "label": g["label"]}
        card = write_card(f"ollama-{name}", fields, f"{g['label']} {quant} in Ollama at {url}")
        out = {"route": "ollama", "model": name, "label": g["label"], "model_card": card, "urls": [url + "/v1"],
               "ollama": url, "quant": quant, "size": size}
    else:
        name = ollama_ensure(url, asked, report, cancel)
        kind = kind_of(asked, body.get("kind") or "auto")
        fields = packaged(KINDS[kind]) | {"model": name, "label": asked}
        if kind == "welllogllm":
            fields |= {"structured_output": "none", "timeout_s": packaged(WELLLOGLLM_GGUF["card"])["timeout_s"]}
        card = write_card(f"ollama-{name}", fields, f"{asked} in Ollama at {url}")
        out = {"route": "ollama", "model": name, "label": asked, "model_card": card, "urls": [url + "/v1"],
               "ollama": url}
    where, warn = placement(ollama_load(url, name, report), _loopback(url))
    if warn:                    # what Ollama did beats what was expected: the GPU check gives way to it
        warnings = [w for w in warnings if not w.startswith(("Apple silicon", "No GPU", "This Mac"))
                    and "free, and the model" not in w] + [warn]
    return out | {"where": where, "warnings": warnings}


def _connect_server(body: dict, report: ProgressFn) -> dict:
    url = (body.get("url") or "").strip().rstrip("/")
    where = slot("server", url)
    given = (body.get("key") or "").strip() or None
    token = given or key(where)
    report({"text": f"Checking {url}"})
    rows = server_models(url, token)
    model = (body.get("model") or "").strip()
    if not model and len(rows) == 1:
        model = rows[0]["id"]
    row = next((r for r in rows if r["id"] == model), None)
    if row is None:
        listed = ", ".join(r["id"] for r in rows) or "none"
        raise ValueError(f"WHAT: {url} does not serve {model or 'the model asked for'} (it serves: {listed}). FIX: "
                         "choose one of its models.")
    if given and body.get("remember", True):
        keep_key(where, given)
    env = arm(where, token) if token else None
    kind = kind_of(model, body.get("kind") or "auto")
    fields = packaged(KINDS[kind]) | {"model": model, "label": _known_label(model)}
    if env:
        fields["api_key_env"] = env
    card = write_card(f"server-{model}", fields, f"{model} at {url}")
    out = {"route": "server", "model": model, "label": fields["label"], "model_card": card, "urls": [url],
           "slot": where if token else None}
    if row.get("context") and int(row["context"]) < CONTEXT:
        out["warnings"] = [(f"{model} has a context window of {int(row['context']):,} tokens; the harness needs "
                          f"{CONTEXT:,} (serve it with --max-model-len {CONTEXT} or more).")]
    return out


def _known_label(model: str) -> str:
    """A packaged WellLogLLM card's label for the served name it gives; else the name as served."""
    for card in ("welllogllm_7b", "welllogllm_3_7b"):
        fields = packaged(card)
        if fields.get("model") == model:
            return fields.get("label") or model
    return model


def _connect_openrouter(body: dict, report: ProgressFn) -> dict:
    where = slot("openrouter")
    given = (body.get("key") or "").strip() or None
    token = given or key(where)
    if not token:
        raise ValueError(f"WHAT: no OpenRouter API key. FIX: paste your key (from {OPENROUTER_KEYS}).")
    report({"text": "Checking the OpenRouter key"})
    openrouter_check(token)
    if given and body.get("remember", True):
        keep_key(where, given)
    model = (body.get("model") or "").strip()
    row = next((r for r in openrouter_models() if r["id"] == model), None)
    if row is None:
        raise ValueError(f"WHAT: OpenRouter has no model {model!r}. FIX: choose one from the list.")
    fields = openrouter_fields(row) | {"api_key_env": arm(where, token)}
    card = write_card(f"openrouter-{model}", fields, f"{model} on OpenRouter")
    out = {"route": "openrouter", "model": model, "label": fields["label"], "model_card": card,
           "urls": [OPENROUTER_URL], "slot": where}
    if row.get("context") and int(row["context"]) < CONTEXT:
        out["warnings"] = [(f"{row['name']} has a context window of {int(row['context']):,} tokens; the harness "
                          f"sends prompts of up to about 40,000 and needs {CONTEXT:,}.")]
    return out
