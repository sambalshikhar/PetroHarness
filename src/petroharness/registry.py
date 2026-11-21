"""Domain knowledge as data: the registries in resources/rules/*.yaml (curves, judgements, shapes, checks, catalog,
topics, relations), loaded once and carried by the formation view."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path

import yaml

DEFAULT_RULES_DIR = Path(__file__).resolve().parent / "resources" / "rules"


@dataclass(frozen=True)
class Registry:
    rules_dir: Path

    def _load(self, name: str) -> dict:
        return yaml.safe_load((self.rules_dir / name).read_text(encoding="utf-8")) or {}

    # --- curves.yaml -------------------------------------------------------------------------------
    @cached_property
    def curves(self) -> dict:
        return self._load("curves.yaml")

    @property
    def raw_order(self) -> list[str]:
        return self.curves["inventory"]["raw"]


    @property
    def derived_order(self) -> list[str]:
        return self.curves["inventory"]["derived"]

    @cached_property
    def flags(self) -> frozenset[str]:
        return frozenset(self.curves["flags"])

    # --- judgements.yaml ---------------------------------------------------------------------------
    @cached_property
    def _judgements_file(self) -> dict:
        return self._load("judgements.yaml")

    @property
    def expansion(self) -> dict:
        return self._judgements_file["expansion"]


    # --- shapes.yaml -------------------------------------------------------------------------------
    @cached_property
    def _shapes_file(self) -> dict:
        return self._load("shapes.yaml")

    @property
    def shapes(self) -> dict[str, dict]:
        return self._shapes_file["shapes"]

    def shape_for(self, intent: str) -> str:
        return next((n for n, s in self.shapes.items() if intent in s.get("intents", [])), self._shapes_file["default"])

    # --- checks.yaml -------------------------------------------------------------------------------
    @cached_property
    def checks(self) -> dict:
        return self._load("checks.yaml")

    def pattern(self, section: str, name: str, multiline: bool = False):
        """A compiled verifier pattern from checks.yaml (case-insensitive)."""
        import re
        return re.compile(self.checks[section][name], re.I | (re.M if multiline else 0))

    # --- topics.yaml and catalog.yaml --------------------------------------------------------------
    @cached_property
    def topics(self) -> dict:
        return self._load("topics.yaml")

    @cached_property
    def catalog(self) -> dict:
        return self._load("catalog.yaml")

    def resolve_topics(self, names) -> list[str]:
        """Class topic names, or aliases (judgement names, older family names) -> topic names."""
        t, out = self.topics, []
        for name in ([names] if isinstance(names, str) else list(names or [])):
            key = str(name).strip().lower()
            for topic in ([key] if key in t["topics"] else t["aliases"].get(key, [])):
                if topic not in out:
                    out.append(topic)
        return out


    def limit(self, name: str, default):
        return self.catalog.get("limits", {}).get(name, default)

    # --- relations.yaml ----------------------------------------------------------------------------
    @cached_property
    def relations(self) -> dict:
        """Classes and mechanisms for the correlation call (empty when a rules dir has no such file)."""
        return self._load("relations.yaml") if (self.rules_dir / "relations.yaml").exists() else {}

    def relation_limit(self, name: str, default):
        return (self.relations.get("limits") or {}).get(name, default)


@lru_cache(maxsize=8)
def load(rules_dir: str | Path = DEFAULT_RULES_DIR) -> Registry:
    return Registry(Path(rules_dir))
