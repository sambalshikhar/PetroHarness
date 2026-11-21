"""Real wells for the interval tests: Petrophys's sample wells, each with the interval a question asks about, built the
way a question builds them (ask._settings and ask._interval, then FormationView.build). One cache folder per process,
so each well is interpreted once.

    from _wells import CASES, focus_view
    view = focus_view(CASES["brent"])
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

_CACHE = Path(tempfile.mkdtemp(prefix="petroharness-wells-"))


@dataclass(frozen=True)
class Case:
    las: str                                  # a petrophys.sample name
    tops: Optional[str] = None                # a petrophys.sample name
    formation: Optional[str] = None
    top: Optional[float] = None               # with base: an interval by depth, in `unit`
    base: Optional[float] = None
    unit: Optional[str] = None
    data: tuple = field(default_factory=tuple)   # (key, value) data settings over the question's defaults
    what: str = ""
    zones: Optional[str] = None               # a zones file (the user's zones), by its path


CASES = {
    "brent": Case("30/6-5", "formations_30_6-5.csv", "BRENT GP.", what="lithology log, tops, metres"),
    "1671": Case("16/7-1", top=2000.0, base=2560.0, unit="m", what="by depth; no neutron or PEF log; evaporites"),
    "cheal": Case("cheal-1", "formations_cheal-1.csv", "Moki", what="no lithology log: shale-volume bands"),
    "tuhua": Case("tuhua-7", "formations_tuhua-7.csv", "McKee", what="no lithology log (shale-volume bands), Taranaki"),
    "hw3": Case("HW-3", "formations_costa.csv", "KHARAIB-2", what="carbonate, a tops table of many wells, feet"),
    "teapot": Case("teapot_17-wx-21", what="the whole log, feet"),
    "brent_formation": Case("30/6-5", "formations_30_6-5.csv", "BRENT GP.", data=(("zone_layout", "formation"),),
                            what="one zone per formation (zone_layout: formation)"),
    "hw3_m": Case("HW-3", "formations_costa.csv", "KHARAIB-2", data=(("depth_unit", "m"),),
                  what="a feet log reported in metres (depths scaled)"),
    "teapot_m": Case("teapot_17-wx-21", top=2000.0, base=3000.0, unit="ft", data=(("depth_unit", "m"),),
                     what="by depth in feet inside the log, reported in metres (depths scaled)"),
}


def sample(name: str) -> Path:
    """A Petrophys sample by name, or a file by its path (a synthetic well, tests/_synthetic.py)."""
    if Path(name).is_absolute() and Path(name).exists():
        return Path(name)
    import petrophys
    return Path(petrophys.sample(name))


def task_cfg(case: Case, prefix: str = "w"):
    """(task, config, data settings) of the case's question, as a question builds them (ask._settings, ask._interval,
    ask._units); build under config.given_settings({"data": data, "eval": {}})."""
    import petroharness.ask as A
    from petroharness.config import DataPaths, HarnessConfig, ResourcePaths
    from petroharness.tasks import Task
    las = sample(case.las)
    tops = sample(case.tops) if case.tops else None
    held = os.environ.pop("PETROHARNESS_DATA", None)      # a data settings file set in the shell is not this well's
    try:
        data, _ = A._settings(las, None, None, None, _CACHE, ResourcePaths().policy_file)
    finally:
        if held is not None:
            os.environ["PETROHARNESS_DATA"] = held
    data.update(dict(case.data))
    span = A._interval(las, case.formation, tops, case.top, case.base, case.unit, data)
    if tops is not None:                                  # every unit of the tops file, as a question keeps them
        data["units"], data["units_left_out"] = A._units(las, tops, case.unit)
    if case.zones:                                        # the user's zones, as a question reads them
        from petroharness.well.user_zones import read_zones
        data["zones"] = read_zones(case.zones, A._las_header(las)[1])
        data["zones_source"] = Path(case.zones).name
    data.setdefault("depth_unit", "las")
    task = Task(task_id=prefix + hashlib.sha256(f"{las}{case}".encode()).hexdigest()[:10], question="q",
                well=las.stem, formation=span["name"], las_path=las, top=span["top"], base=span["base"],
                depth_unit=None if span["top"] is None else (span.get("unit") or "las"), base_closed=span["closed"],
                formation_lithology=None)
    return task, HarnessConfig(data=DataPaths(**data), eval=None), data


@lru_cache(maxsize=None)
def focus_view(case: Case):
    """The question's view of the case's interval (petroharness.well.view.FormationView)."""
    from petroharness.config import given_settings
    from petroharness.well.view import FormationView
    task, cfg, data = task_cfg(case, "w")
    with given_settings({"data": data, "eval": {}}):
        return FormationView.build(task, cfg)


@lru_cache(maxsize=None)
def formation_of(case: Case):
    """The question's session formation (agent.engine.Formation: inventory, view, analyzer sections) of the case, built
    as a question builds it (agent.loop.Session.build): for calling tools."""
    from petroharness.agent.loop import Session
    from petroharness.config import given_settings
    task, cfg, data = task_cfg(case, "s")
    with given_settings({"data": data, "eval": {}}):
        return Session.build(task, cfg).f
