"""Read-only access to reference material for tests and diagnostics (never used by the harness)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from petroharness.config import HarnessConfig
from petroharness.tasks import load_tasks

CFG = HarnessConfig()


@lru_cache(maxsize=1)
def benchmark_tasks() -> list:
    return load_tasks(CFG.eval.questions, CFG.data.las_dir)[0]


def benchmark_pairs(categories=None) -> list[tuple[str, str]]:
    tasks, _ = load_tasks(CFG.eval.questions, CFG.data.las_dir, categories)
    return sorted({(t.well, t.formation) for t in tasks})


def _formation_dir(well: str, formation: str, category: str = "hydrocarbon") -> Path:
    return CFG.eval.reference_context_dir / category / well / formation


@lru_cache(maxsize=512)
def reference_groups(well: str, formation: str, category: str = "hydrocarbon") -> list[dict]:
    """One dict per reference zone file: name, lithology, bounds, formation_info, analysis_results."""
    folder = _formation_dir(well, formation, category)
    groups = []
    for path in sorted(folder.glob("*.json")):
        payload = json.loads(path.read_text())
        ar = payload["analysis_results"]
        info = ar["lithology_group_info"]
        groups.append({
            "name": ar["lithology group"],
            "lithology": ar["lithology"],
            "top": info["start_depth"],
            "base": info["end_depth"],
            "n": info["data_points"],
            "formation_info": payload["formation_info"],
            "analysis_results": ar,
        })
    return sorted(groups, key=lambda g: g["top"])
