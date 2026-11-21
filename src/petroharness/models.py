"""The model the harness runs on: a model card (the served model's name and how to call it) and its endpoints.

    MODELS[key] = (model card, endpoints[, the served model's name])

Any chat model behind an OpenAI-compatible endpoint can answer: vLLM, SGLang, Ollama, LM Studio or a hosted API.
The packaged cards are under resources/models: k2_horizon_7b.yaml (the default, registry key k2-horizon-7b) and
generic.yaml (any other chat model, named by its served name); a card of your own is a YAML file of the same form
(docs/MODELS.md). The endpoints are comma-separated in PETROHARNESS_MODEL_URL (the benchmark command, with none set,
uses one server on this machine at vLLM's default port); a question picks one by its task id and rep."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

CARDS = Path(__file__).resolve().parent / "resources" / "models"
DEFAULT_KEY = "k2-horizon-7b"                  # the default model's registry key
DEFAULT_CARD = "models/k2_horizon_7b.yaml"
GENERIC_CARD = "models/generic.yaml"
URL_ENVS = ("PETROHARNESS_MODEL_URL",)


def env_urls() -> list[str]:
    """The endpoints the environment names: PETROHARNESS_MODEL_URL's, comma-separated."""
    text = next((os.environ[e] for e in URL_ENVS if os.environ.get(e, "").strip()), "")
    return [u.strip() for u in text.split(",") if u.strip()]


def card_file(card: str | None = None, model: str | None = None) -> str:
    """The model card: `card` (a YAML file, or a packaged card's name), else generic.yaml when `model` names the served
    model, else K2-Horizon-7B's. Packaged cards are given relative to the package's resources."""
    if not card:
        return GENERIC_CARD if model else DEFAULT_CARD
    path = Path(card).expanduser()
    if path.is_file():
        return str(path.resolve())
    packaged = CARDS / (card if card.endswith(".yaml") else f"{card}.yaml")
    if packaged.is_file():
        return f"models/{packaged.name}"
    known = ", ".join(sorted(p.stem for p in CARDS.glob("*.yaml")))
    raise ValueError(f"WHAT: no model card {card!r}. FIX: give a model card's YAML file (docs/MODELS.md), or the name "
                     f"of a packaged card: {known}.")


def card_settings(file: str) -> dict:
    """The card's `model` section, checked against the harness's model settings (a misspelt key is an error)."""
    from petroharness.config import RESOURCES, ModelConfig

    path = RESOURCES / file
    section = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("model")
    if not isinstance(section, dict):     # a wrong card is an input error: the command and the UI report ValueError
        raise ValueError(f"WHAT: the model card {path} has no `model` section. "  # noqa: TRY004
                         "FIX: see docs/MODELS.md.")
    return ModelConfig(**section).model_dump()


def label(file: str, model: str | None = None) -> str:
    """The model's name as people read it: --model, else the card's label, else the served name."""
    settings = card_settings(file)
    return model or settings.get("label") or settings["model"]


def register(urls: list[str], card: str | None = None, model: str | None = None) -> str:
    """The registry key for this card, served model and endpoints (added to MODELS when new). A card that names no
    model needs --model."""
    file = card_file(card, model)
    if not (model or card_settings(file)["model"]):
        raise ValueError(f"WHAT: the model card {Path(file).name} names no model. FIX: give the served model's name "
                         "(--model NAME, as the server lists it at /v1/models).")
    if file == DEFAULT_CARD and not model:
        if urls == MODELS[DEFAULT_KEY][1]:
            return DEFAULT_KEY
        key = DEFAULT_KEY + "@" + ",".join(urls)
    else:
        key = Path(file).stem + (f":{model}" if model else "") + "@" + ",".join(urls)
    MODELS.setdefault(key, (file, urls, model) if model else (file, urls))
    return key


MODELS = {DEFAULT_KEY: (DEFAULT_CARD, env_urls() or ["http://localhost:8000/v1"])}
