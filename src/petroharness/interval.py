"""Preparing an interval of a LAS for questions, as every entry point does (the question command, a conversation, the
web UI): the LAS header and depth range, the data settings built for it, the interval asked about (a unit of a tops
file, top and base, or the whole well), the tops file's units, the interpretation settings in force, and the task a
question runs as."""

from __future__ import annotations

import hashlib
import os
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
import yaml
from petroharness.well.tops import depth_unit_name, read_tops


WHOLE_WELL = "whole well"


# --- the inputs ------------------------------------------------------------------------------------------------------

def _las_header(las: Path) -> tuple[str | None, list[str]]:
    """(the LAS's depth unit as m/ft, or None; the names the well goes by: file stem, WELL, UWI and API headers)."""
    import lasio

    head = lasio.read(str(las), ignore_data=True)
    unit = depth_unit_name(head.curves[0].unit) if len(head.curves) else None
    names = [las.stem]
    for key in ("WELL", "UWI", "API", "APIN"):
        item = head.well.get(key) if key in head.well else None
        if item is not None and str(item.value).strip():
            names.append(str(item.value).strip())
    return unit, names


def _log_range(las: Path) -> tuple[float, float]:
    """The first and last depth of the log, in the LAS's own unit."""
    import numpy as np

    from petroharness.well.prepare import read_depth

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        depth = read_depth(las)
    return float(np.nanmin(depth)), float(np.nanmax(depth))


def _settings(las: Path, settings: Path | None, profile: str | None, lithology_curve, cache_dir: Path,
              policy_file: Path) -> tuple[dict, str]:
    """The data settings for this LAS and where they came from: a settings file's (--settings, else PETROHARNESS_DATA)
    data section as the base, else none; the LAS's folder as the data folder; petrophys.interpret with a context
    profile, else the library's defaults with the policy's net-pay cutoffs."""
    from petroharness.config import DATA_FILE_ENV
    from petroharness.well.prepare import default_interpret, load_policy

    path = settings or (Path(os.environ[DATA_FILE_ENV]) if os.environ.get(DATA_FILE_ENV) else None)
    data: dict = {}
    if path is not None:
        if not Path(path).is_file():
            raise FileNotFoundError(f"WHAT: no data settings file at {path}. FIX: give an existing YAML file "
                                    f"(configs/data.example.yaml shows the keys), or unset {DATA_FILE_ENV}.")
        data = dict((yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("data") or {})
    data.setdefault("las_dir", str(las.parent))
    data.setdefault("cache_dir", str(cache_dir))
    if lithology_curve:
        data["lithology_curve"] = lithology_curve
    if profile:
        if data.get("interpreter"):
            raise ValueError(f"WHAT: --profile {profile} and the settings' data.interpreter are both set. FIX: keep one.")
        data["interpret"] = {"context_profile": profile}
    elif not data.get("interpreter"):
        data["interpret"] = default_interpret(load_policy(policy_file), data.get("interpret"))
    return data, (str(path) if path is not None else "built from the LAS")


def _interpretation(data: dict, interpretation: dict) -> None:
    """The user's interpretation settings (petroharness.well.settings) into the data settings: Petrophys's into
    petrophys.interpret's options (over the policy's cutoffs), the zone rule into data.zone_*."""
    from petroharness.well import settings as T
    wrong = T.validate(interpretation)
    if wrong:
        raise ValueError("WHAT: interpretation settings that cannot be used: "
                         + "; ".join(f"{k}: {v}" for k, v in wrong.items()) + ". FIX: correct or remove them.")
    petro, zones = T.split(interpretation)
    if petro:
        options = data.get("interpret")
        if data.get("interpreter") or options is None or options.get("context_profile"):
            raise ValueError("WHAT: Petrophys settings with a context profile or a data interpreter. WHY: those fix their "
                             "own settings. FIX: drop the profile (or the interpreter), or the settings.")
        data["interpret"] = {**options, **petro}
    data.update(zones)


def _interval(las: Path, formation: str | None, tops: Path | None, top: float | None, base: float | None,
              depth_unit: str | None, data: dict) -> dict:
    """The interval asked about: {name, top, base, closed, unit (m/ft, or None for the LAS's own), from, report}.
    top None: the settings' tops table gives the named formation's interval (FormationView)."""
    stated = depth_unit_name(depth_unit) if depth_unit else None
    if depth_unit and stated is None:
        raise ValueError(f"WHAT: depth unit {depth_unit!r} is not m or ft. FIX: give m or ft.")
    las_unit, names = _las_header(las)
    if tops is not None:
        if base is not None:
            raise ValueError("WHAT: both a tops file and depths (--top/--base) are given. WHY: either gives the "
                             "interval. FIX: keep one: --formation NAME --tops FILE (with --top D, the row's top, for "
                             "a name the file lists twice), or --top D --base D.")
        table = read_tops(tops, names, stated, las_unit)
        if not formation:
            raise ValueError(f"WHAT: a tops file is given without a formation. FIX: add --formation with one of its "
                             f"names: {', '.join(table.names())}.")
        got = table.interval(formation, top)          # top: which row, for a name the file lists twice
        source = f"tops file {Path(tops).name}, base: {got.base_from}"
        out = {"name": got.name, "top": got.top, "base": got.base, "closed": got.closed, "unit": got.unit,
               "from": source, "units": [list(u) for u in table.within(got)]}
    elif top is not None or base is not None:
        unit = stated or las_unit
        if top is None or base is None:
            first, last = _log_range(las)
            factor = 1.0 if unit is None or las_unit is None else _factor(las_unit, unit)
            top = first * factor if top is None else top
            base = last * factor if base is None else base
        if base <= top:
            raise ValueError(f"WHAT: the base ({base:g}) is not below the top ({top:g}). FIX: give --top above --base "
                             "(depths increase downwards).")
        label = unit or "(LAS depth unit)"
        out = {"name": formation or f"depth interval {top:g}-{base:g} {label}", "top": float(top),
               "base": float(base), "closed": True, "unit": unit, "from": "depths given"}
    elif formation:
        if not data.get("tops_csv"):
            raise ValueError(f"WHAT: formation {formation!r} is named without its depths. WHY: the interval comes "
                             "from a tops file or from depths. FIX: add --tops FILE (a CSV with formation,top[,base]), "
                             "or give the depths: --top D --base D.")
        out = {"name": formation, "top": None, "base": None, "closed": False, "unit": None,
               "from": f"the settings' tops table {Path(data['tops_csv']).name}"}
    else:
        first, last = _log_range(las)
        out = {"name": WHOLE_WELL, "top": first, "base": last, "closed": True, "unit": las_unit,
               "from": "the whole log (no formation or depths given)"}
    out["las_unit"] = las_unit
    out["report"] = stated or out["unit"] or las_unit
    return out


def _units(las: Path, tops: Path, depth_unit: str | None) -> tuple:
    """The tops file's units of this well, for selections anywhere in it (data.units, reach "well";
    docs/ARCHITECTURE.md): each {name, top, base, closed, unit, line}, in the file's unit (None: the
    LAS's own), the base the unit's own where the file states it, else the next top (not included), else the end of the
    log (None). A name the file lists twice keeps each of its rows (a selection of it is refused with them); a row the
    file gets wrong (its base not below its top) is left out, as it would be refused as the focus, and kept with why
    (a question naming it is asked back with the row to fix, not told the unit is not in the file).
    (units, rows left out)."""
    stated = depth_unit_name(depth_unit) if depth_unit else None
    las_unit, names = _las_header(las)
    table = read_tops(tops, names, stated, las_unit)
    from petroharness.well.tops import name_key
    out, left = [], []
    for name in table.names():
        rows = [t for t in table.tops if name_key(t.name) == name_key(name)]
        if len(rows) > 1:
            out += [{"name": t.name, "top": t.top, "base": t.base, "closed": t.base is not None, "unit": t.unit,
                     "line": t.line} for t in rows]
            continue
        try:
            got = table.interval(name)
        except ValueError as e:
            t = rows[0]
            left.append({"name": t.name, "line": t.line, "top": t.top, "base": t.base, "unit": t.unit,
                         "why": str(e).replace("WHAT: ", "").split(" FIX:")[0].strip()})
            continue
        out.append({"name": got.name, "top": got.top, "base": got.base, "closed": got.closed, "unit": got.unit,
                    "line": rows[0].line})
    return out, left


def _factor(unit: str, to: str) -> float:
    from petroharness.well.tops import convert
    return convert(1.0, unit, to)


@dataclass(frozen=True)
class Inputs:
    """What a question's interval is prepared from: the arguments ask(), a conversation, the web UI and the setup
    command share (ask() says what each means). field_notes is a field notes file, or the notes already read from one
    (loaded)."""
    formation: str | None = None
    tops: object = None
    top: float | None = None
    base: float | None = None
    depth_unit: str | None = None
    lithology_curve: str | None = None
    formation_lithology: str | None = None
    profile: str | None = None
    settings: object = None
    skills: str | None = None
    interpretation: dict | None = None
    field_notes: object = None
    zones: object = None
    zones_sheet: str | None = None

    @classmethod
    def keys(cls) -> tuple:
        return tuple(f.name for f in fields(cls))

    @classmethod
    def of(cls, given) -> Inputs:
        """The inputs a mapping (or an argparse namespace) holds; other keys are left out."""
        given = given if isinstance(given, dict) else vars(given)
        return cls(**{k: given[k] for k in cls.keys() if k in given})

    def loaded(self) -> Inputs:
        """The field notes file read (petroharness.well.notes), its settings in force under `interpretation`'s; notes
        already read are kept as they are."""
        if not self.field_notes or isinstance(self.field_notes, dict):
            return self
        from petroharness.well.notes import load
        notes = load(self.field_notes)
        return replace(self, field_notes=notes, interpretation={**notes["settings"], **(self.interpretation or {})})


@dataclass
class Prepared:
    """One interval of one LAS, ready for questions: what ask() and a conversation (petroharness.session) set up
    before the model runs. `check` fills the view, the interval as used and the zoning's source."""
    las: Path
    key: str                      # the model registry key
    data: dict                    # the data settings built for this LAS
    source: str                   # where they came from
    span: dict                    # the interval asked about (_interval)
    said: str                     # the operator's lithology for the formation, when given
    given: dict                   # the settings every question of this interval runs under (config.given_settings)
    skills_given: str | None = None
    lithology_curve: str | None = None
    view: object = None
    used: dict = field(default_factory=dict)
    litho: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)     # the field notes in force (petroharness.well.notes.load), if any


def prepare(las: Path, key: str, inputs: Inputs, *, cache: Path) -> Prepared:
    """The data settings and the interval for this LAS under `inputs`, with `cache` as the folder the interpreted well
    is kept in."""
    from petroharness.config import ResourcePaths
    from petroharness.well.prepare import depth_order
    i = inputs.loaded()
    formation, tops, top, base, depth_unit = i.formation, i.tops, i.top, i.base, i.depth_unit
    settings, profile, lithology_curve, interpretation, zones = i.settings, i.profile, i.lithology_curve, \
        i.interpretation, i.zones
    problem = depth_order(las)                      # depths out of order: the file, the line and the fix, before all
    if problem:
        raise ValueError(problem)
    data, source = _settings(las, Path(settings) if settings else None, profile, lithology_curve, cache,
                             ResourcePaths().policy_file)
    if interpretation:
        _interpretation(data, interpretation)
    span = _interval(las, formation, Path(tops) if tops else None, top, base, depth_unit, data)
    if tops:                                        # every unit of the tops file, for selections anywhere in the well
        data["units"], data["units_left_out"] = _units(las, Path(tops), depth_unit)
    if zones:                                       # the user's zones: the question's frame (well.user_zones)
        from petroharness.well.user_zones import read_zones
        data["zones"] = read_zones(zones, _las_header(las)[1], i.zones_sheet)
        data["zones_source"] = Path(zones).name
    las_unit = span["las_unit"]
    report = "las" if span["report"] in (None, las_unit) else span["report"]
    if depth_unit:                                  # the command's --depth-unit wins over a settings file's
        data["depth_unit"] = report
    else:
        data.setdefault("depth_unit", report)
    library = library_given(i.skills)
    given = {"data": data, "eval": {}, **({"skills": library} if library else {})}
    return Prepared(las=las, key=key, data=data, source=source, span=span,
                    said=str(i.formation_lithology or "").strip(), given=given, skills_given=i.skills,
                    lithology_curve=lithology_curve, notes=dict(i.field_notes or {}))


def library_given(skills) -> str:
    """The skill library as given (--skills): a folder of the user's as its absolute path (it was given relative to
    here), "none" or a packaged library's name as written, "" when none was given."""
    library = str(skills or "").strip()
    if library and library.lower() != "none" and Path(library).expanduser().exists():
        library = str(Path(library).expanduser().resolve())
    return library


def task_for(p: Prepared, question: str, turn: int = 1):
    """(the task of one question about the prepared interval, the question as the model reads it). `turn`: the
    question's number in a conversation (the first question's task is ask()'s)."""
    from petroharness.tasks import Task
    span, las_unit = p.span, p.span["las_unit"]
    sent = question
    if p.said and p.data.get("zone_layout", "lithology_runs") != "formation":
        # the zones are lithology-log runs or shale-volume bands: the operator's lithology reaches the model with
        # the question (the "formation" layout shows it on the zone)
        sent = f"{question}\n\n(The operator states this formation's lithology: {p.said}.)"
    if span.get("units") and p.data.get("reach", "well") != "well":
        # the tops file's units inside the interval, as the file gives them (reach focus: the map lists none). Under
        # reach well the map lists every unit; said in the question, "inside this interval" read a question about
        # another unit as one about the interval
        u = span["unit"] or las_unit or ""
        listed = "; ".join(f"{n} {t:g}-{b:g} {u}".rstrip() for n, t, b in span["units"])
        sent = f"{sent}\n\n(The tops file lists these units inside this interval: {listed}.)"
    if p.notes.get("notes"):                     # the user's field notes, with every question
        from petroharness.well.notes import statement
        sent = f"{sent}\n\n{statement(p.notes)}"
    ident = f"{p.las}|{question}|{span}" + (f"|question {turn}" if turn > 1 else "")
    task = Task(task_id="a" + hashlib.sha256(ident.encode()).hexdigest()[:10],
                question=sent, well=p.las.stem, formation=span["name"], las_path=p.las, top=span["top"],
                base=span["base"], depth_unit=None if span["top"] is None else
                ("las" if span["unit"] in (None, las_unit) else span["unit"]),
                base_closed=span["closed"], formation_lithology=p.said.upper() or None)
    return task, sent


def check(p: Prepared, task, on_view: Callable | None = None) -> None:
    """The interval checked before any model call: the skill library must load, Petrophys interprets the well, the
    interval must hold samples and a named lithology curve data. Fills p.view, p.used and p.litho; `on_view(view)` is then called."""
    from petroharness.agent import direction
    from petroharness.agent.graph import task_config
    from petroharness.config import DataPaths, HarnessConfig, given_settings
    from petroharness.models import MODELS
    from petroharness.well.view import FormationView
    with given_settings(p.given):                   # a skill library that cannot be used stops here, not at a question
        direction.plugged(task_config(task, p.key, 1) if p.key in MODELS else None)   # (a card may name one)
    las, span, las_unit = p.las, p.span, p.span["las_unit"]
    cfg = HarnessConfig(data=DataPaths(**p.data), eval=None)
    view = FormationView.build(task, cfg)
    n = int(view.mask.sum())
    if n == 0:
        first, last = (float(view.prep.depth.min()), float(view.prep.depth.max())) if view.prep.depth.size else (0, 0)
        raise ValueError(f"WHAT: the interval {span['name']!r} has no samples in {las.name} (the log runs "
                         f"{first:g}-{last:g} {las_unit or ''}). FIX: check the depths and their unit "
                         "(--depth-unit).")
    if p.lithology_curve and view.lithology_curve is None:
        raise ValueError(f"WHAT: the lithology curve {p.lithology_curve!r} has no data in {las.name} (its curves: "
                         f"{', '.join(view.prep.input_curves)}). WHY: the zones come from it. FIX: name one of "
                         "those curves (as Petrophys names it), or leave --lithology-curve out.")
    if on_view is not None:
        on_view(view)
    depth = view.depth
    p.view = view
    p.used = {"name": span["name"], "top": round(float(view.interval.top), 4),
              "base": round(float(view.interval.base if view.interval.base is not None else depth[-1]), 4),
              "unit": view.report_unit, "samples": n, "from": span["from"]}
    if view.lithology_curve:
        p.litho = {"source": "lithology log", "curve": view.lithology_curve,
                   "how": "named" if p.lithology_curve else "detected"}
    elif view.solver_curve:
        p.litho = {"source": "mineral solver", **view.solver_record}
    elif view.vcl_bands:
        p.litho = {"source": "shale-volume bands", "curve": "VCL", "bands": list(view.vcl_bands)}
    else:
        p.litho = {"source": "none", "curve": None}
