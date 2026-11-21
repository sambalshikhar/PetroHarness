"""The report style (resources/profiles): how answers are laid out (sections, length, the zone table, the limitations
rule), never what they conclude or which basis a number is taken on."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from petroharness.config import RESOURCES


@lru_cache(maxsize=16)
def _yaml(path: str) -> dict:
    p = Path(path)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def profile(policy: dict | None) -> dict:
    """The report style named by the policy (empty when none)."""
    name = ((policy or {}).get("reporting") or {}).get("profile")
    if not name:
        return {}
    path = Path(name) if Path(name).is_absolute() else RESOURCES / name
    if not path.exists():
        raise FileNotFoundError(f"WHAT: report style {path} not found. WHY: the policy names it. FIX: create it or "
                                "remove policy reporting.profile.")
    return _yaml(str(path))
