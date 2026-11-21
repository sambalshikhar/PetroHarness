"""What a user sees and types for the default model carries its public name: its registry key (the benchmark command's
--models), its packaged card's file name; and the endpoints come from one variable, PETROHARNESS_MODEL_URL. The served
model's name (the card's `model`, what the server answers to) is the server's and stays as served.

    .venv/bin/python -m pytest tests/test_model_names.py -q
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERNAL = re.compile(r"\bk200[a-z]\b|_grpo200\b|\bK2H_TOOL_URLS\b")     # a checkpoint's working name, a cluster variable


def test_the_default_model_key_and_card_carry_the_public_name():
    from petroharness import models
    assert models.DEFAULT_KEY == "k2-horizon-7b" and models.DEFAULT_KEY in models.MODELS
    assert Path(models.DEFAULT_CARD).name == "k2_horizon_7b.yaml"
    assert models.label(models.MODELS[models.DEFAULT_KEY][0]) == "K2-Horizon-7B"


def test_the_endpoints_come_from_petroharness_model_url_alone(monkeypatch):
    from petroharness import models
    monkeypatch.delenv("PETROHARNESS_MODEL_URL", raising=False)
    monkeypatch.setenv("K2H_TOOL_URLS", "http://h3:8100/v1")
    assert models.env_urls() == []
    monkeypatch.setenv("PETROHARNESS_MODEL_URL", "http://h1:8100/v1, http://h2:8100/v1")
    assert models.env_urls() == ["http://h1:8100/v1", "http://h2:8100/v1"]


def test_no_working_names_in_the_package_or_its_docs():
    hits = []
    for base in ("src/petroharness", "docs", "configs"):
        for p in sorted((ROOT / base).rglob("*")):
            if p.is_file() and p.suffix in (".py", ".yaml", ".md", ".json", ".html", ".js", ".txt") \
                    and "egg-info" not in str(p):
                hits += [f"{p.relative_to(ROOT)}:{i}" for i, line in
                         enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1) if INTERNAL.search(line)]
        hits += [str(p.relative_to(ROOT)) for p in (ROOT / base).rglob("*") if INTERNAL.search(p.name)]
    for p in (ROOT / "README.md",):
        hits += [f"README.md:{i}" for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if INTERNAL.search(line)]
    assert not hits, "working names in shipped files: " + ", ".join(hits[:20])
