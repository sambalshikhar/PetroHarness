"""The formations of the configured dataset that the tests share, each built once: (task, view, store, inventory) by
formations(), and the tools' Formation over each by F(); a test reading them is marked data."""
from __future__ import annotations

import warnings
from functools import lru_cache

from petroharness.agent.inventory import from_view
from petroharness.agent.tools import Formation
from petroharness.config import HarnessConfig
from petroharness.record.store import build as build_store
from petroharness.tasks import load_tasks
from petroharness.well.view import FormationView


def default_reporting(cfg: HarnessConfig) -> HarnessConfig:
    """The configuration with the data's two reporting settings at the package's defaults: data.basis "all" (each
    zone, the zones pooled and the whole interval where it differs) and no conventions. A data file may set its own (a
    benchmark's file sets the zones basis and its conventions); the formations the tests share are built without them,
    so what the tests assert of the tools, the map and the prompts holds whichever data file is in use. The two
    settings have their own tests (tests/agent/test_writer_evidence.py; the zones basis over every summarising tool:
    tests/agent/test_summary.py)."""
    return cfg.model_copy(update={"data": cfg.data.model_copy(update={"basis": "all", "conventions": []})})


CFG = default_reporting(HarnessConfig())       # read on import: with no data settings, a module using it is skipped


@lru_cache(maxsize=1)
def formations() -> list:
    """(task, view, store, inventory) for each formation of the dataset, hydrocarbon tasks first (built on the default
    reporting settings: default_reporting)."""
    tasks, index = load_tasks(CFG.eval.questions, CFG.data.las_dir)
    tasks = sorted(tasks, key=lambda t: index[t.task_id]["category"] != "hydrocarbon")
    out, seen = [], set()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for t in tasks:
            k = (str(t.las_path), t.formation)
            if k in seen:
                continue
            seen.add(k)
            v = FormationView.build(t, CFG.for_tasks())
            s = build_store(v)
            out.append((t, v, s, from_view(v, s)))
    return out


@lru_cache(maxsize=1)
def F() -> list:
    """(task, Formation) for each formation: what the tools run on."""
    return [(t, Formation(inv, v, s)) for t, v, s, inv in formations()]
