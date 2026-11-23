"""The web UI's adapter over petroharness.ask: the page's inputs as ask()'s arguments (checked before a question is
queued), a LAS file's header, the formations a tops file names, and one question run as a Job, with its live
progress (progress.Observed) and the parts of its trace the page shows.

The page's inputs (POST /api/ask):

    {"las": PATH, "question": TEXT,
     "interval": {"mode": "whole"}
               | {"mode": "tops", "tops": PATH, "formation": NAME[, "unit": "m"|"ft"]}
               | {"mode": "depths", "top": D, "base": D[, "unit": "m"|"ft"][, "name": LABEL]},
     "lithology_curve": MNEMONIC, "formation_lithology": TEXT, "profile": NAME,
     "skills": "default" | "none" | PATH, "max_steps": N, "depth": "investigate",
     "interpretation": {SETTING: VALUE, ...},      (petroharness.well.settings: Petrophys's settings and the zone rule)
     "field_notes": PATH}                          (a field notes file: the field's standing settings and notes)

Everything but the LAS, the question and the interval is optional. A follow-up is {"follow": RUN_ID, "question": TEXT
[, "interpretation": {...}]}: it keeps the earlier question's inputs, and an interpretation given with it is the full
set of settings to run under from this question on.
"""

from __future__ import annotations

import functools
import itertools
import json
import threading
import time
import traceback
import warnings
from collections.abc import Callable
from pathlib import Path

MAX_QUESTION = 8000
MAX_STEPS_LIMIT = 30


class InputError(ValueError):
    """An input the page must correct: the message says what, why and how (as ask's own errors do)."""


# --- the inputs --------------------------------------------------------------------------------------------------------

def _file(path, what: str) -> Path:
    text = str(path or "").strip()
    if not text:
        raise InputError(f"WHAT: no {what} given. FIX: give its path on the server, or upload it.")
    p = Path(text).expanduser()
    if not p.is_file():
        raise InputError(f"WHAT: no {what} at {text}. FIX: give the path of an existing file on the server, or "
                         "upload it.")
    return p.resolve()


@functools.lru_cache(maxsize=1)
def samples() -> tuple:
    """Petrophys's sample wells, for the page's one-click start: each log sample (petrophys.datasets.list_samples) with
    its dataset folder, its header (the well's name, depth range and unit, curves) and the tops sample that has rows
    for it, if any: one whose well column names it, or, without a well column, whose file name holds the well's file
    name. Petrophys names its samples; the harness names none (tests/test_lint.py). Read once per server."""
    import lasio

    from petroharness.interval import _las_header
    from petroharness.well.tops import read_tops
    from petrophys.datasets import list_samples, sample
    tops = []
    for name in list_samples("geology"):
        try:
            tops.append(Path(sample(name)))
        except (FileNotFoundError, ValueError):
            continue
    out = []
    for name in list_samples("logs"):
        try:
            path = Path(sample(name))
            if path.suffix.lower() != ".las":
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                head = lasio.read(str(path), ignore_data=True)
                unit, names = _las_header(path)
            item = lambda key: str(head.well[key].value).strip() if key in head.well else ""
            row = {"name": name, "folder": path.parent.name, "las": str(path), "well": item("WELL"),
                   "top": _float(item("STRT")), "base": _float(item("STOP")), "unit": unit,
                   "curves": max(0, len(head.curves) - 1), "tops": None}
        except Exception:  # noqa: BLE001  (a sample that cannot be read is not offered)
            continue
        for t in tops:
            try:
                table = read_tops(t, names, None, unit)
            except (ValueError, LookupError, OSError):
                continue
            if table.tops and (table.wells or path.stem.lower() in t.stem.lower()):
                row["tops"] = {"path": str(t), "name": t.name, "formations": len(table.names())}
                break
        out.append(row)
    return tuple(out)


def _float(text) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def las_info(path) -> dict:
    """A LAS file's header as the page shows it: the well's names, the depth unit, the first and last depth of the log,
    its samples and curves (mnemonic, unit, description), and the curves that look like a lithology log."""
    import lasio
    import numpy as np

    from petroharness.interval import _las_header
    from petroharness.well.formation import LITHOLOGY_LOG
    from petroharness.well.prepare import read_depth

    p = _file(path, "LAS file")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            head = lasio.read(str(p), ignore_data=True)
            unit, names = _las_header(p)
            depth = np.asarray(read_depth(p), dtype=float)
    except Exception as exc:  # noqa: BLE001  (any failure to read is the same answer: not a readable LAS)
        raise InputError(f"WHAT: {p.name} could not be read as a LAS file ({type(exc).__name__}: {str(exc)[:200]}). "
                         "FIX: give a LAS 2.0 file (a well log with ~Version, ~Well, ~Curve and ~A sections).") from None
    from petroharness.well.prepare import depth_order
    problem = depth_order(p, depth)                            # spliced runs, a repeated section: said at once
    if problem:
        raise InputError(problem)
    finite = depth[np.isfinite(depth)]

    def well_item(key):
        return str(head.well.get(key, "").value or "").strip()

    curves = [{"mnemonic": c.mnemonic, "unit": (c.unit or "").strip(), "description": (c.descr or "").strip()}
              for c in head.curves[1:]]
    step = float(np.median(np.diff(finite))) if finite.size > 1 else None
    return {"path": str(p), "name": p.name, "well": well_item("WELL"), "uwi": well_item("UWI"),
            "names": names, "depth_unit": unit, "depth_unit_raw": (head.curves[0].unit or "").strip() if len(head.curves) else "",
            "top": float(finite.min()) if finite.size else None, "base": float(finite.max()) if finite.size else None,
            "step": round(step, 6) if step else None, "samples": int(depth.size), "curves": curves,
            "lithology_candidates": [c["mnemonic"] for c in curves
                                     if LITHOLOGY_LOG.search(c["mnemonic"]) or LITHOLOGY_LOG.search(c["description"])]}


def tops_info(path, las=None, unit: str | None = None) -> dict:
    """The formations a tops file names, as the tops reader finds them (petroharness.well.tops), each with the
    interval a question about it would use. With a LAS file, a table with a well column is read for that well only,
    and depths with no stated unit are in the LAS's unit."""
    from petroharness.interval import _las_header
    from petroharness.well.formation import FormationNotFound
    from petroharness.well.tops import read_tops

    p = _file(path, "tops file")
    las_unit, names = (None, [])
    if las:
        las_unit, names = _las_header(_file(las, "LAS file"))
    try:
        table = read_tops(p, names, unit or None, las_unit)
    except (ValueError, LookupError, OSError) as exc:
        raise InputError(str(exc)) from None
    out = []
    for name in table.names():
        row = {"name": name}
        try:
            got = table.interval(name)
            row.update(top=got.top, base=got.base, unit=got.unit, closed=got.closed, base_from=got.base_from)
        except FormationNotFound:                        # a name listed twice: each listing is chosen by its top
            row["repeated"] = []
            for t in (t for t in table.tops if t.name == name):
                one = {"top": t.top, "base": t.base, "line": t.line, "unit": t.unit}
                try:
                    got = table.interval(name, t.top)
                    one.update(base=got.base, closed=got.closed, base_from=got.base_from)
                except ValueError as exc:
                    one["error"] = str(exc)
                row["repeated"].append(one)
        except ValueError as exc:
            row["error"] = str(exc)
        out.append(row)
    fits = _fits_log(out + [r for f in out for r in f.get("repeated", [])], las, las_unit) if las else None
    return {"path": str(p), "name": p.name, "columns": table.columns, "wells": list(table.wells), "formations": out,
            **({"fits": fits} if fits else {})}


def zones_info(path, las=None) -> dict:
    """The user's zones a zones file gives (petroharness.well.user_zones, read as Petrophys reads tops), each with its
    depths, and what is wrong in them before a question is asked: zones that overlap (each sample belongs to one
    zone) and zones beyond the log (they get no sample, and are said with every answer)."""
    from petroharness.interval import _las_header
    from petroharness.well.user_zones import read_zones
    p = _file(path, "zones file")
    names = _las_header(_file(las, "LAS file"))[1] if las else []
    try:
        rows = read_zones(p, names)
    except (ValueError, LookupError, OSError) as exc:
        raise InputError(str(exc)) from None
    out = [{"name": r["name"], "top": r["top"], "base": r.get("base"), "unit": r.get("unit"), "line": r.get("line")}
           for r in rows]
    overlaps = []
    ordered = sorted(out, key=lambda z: float(z["top"]))
    for a, b in zip(ordered, ordered[1:]):
        if a["base"] is not None and float(b["top"]) < float(a["base"]):
            overlaps.append(f"{a['name']} and {b['name']} overlap ({float(b['top']):g}-{float(a['base']):g}): each sample "
                            "belongs to one zone, so a question with these zones is refused; make them meet or leave a gap.")
    problems = list(overlaps)
    fits = _fits_log(out, las, None) if las else None
    for z in out:
        if z.get("outside"):
            problems.append(f"{z['name']} ({float(z['top']):g}-{float(z['base']):g}) lies beyond the log"
                            f"{' (' + fits['log'] + ')' if fits else ''}: it gets no sample, and answers say so.")
    return {"path": str(p), "name": p.name, "zones": out, "problems": problems, "overlaps": overlaps}


def scope_input(value) -> list | None:
    """The stretches a question is on, as the user chose them (a list of depth ranges or unit names, e.g. a choice's
    scope in answer to a question back): None when not given; anything but a list of short texts is refused."""
    if value in (None, [], ""):
        return None
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        raise InputError("WHAT: scope must be a list of stretches, each a depth range or a unit's name (e.g. "
                         "[\"874-1250 m\"]). FIX: send a list of texts, or leave scope out.")
    if len(value) > MAX_SCOPE or any(len(x) > 200 for x in value):
        raise InputError(f"WHAT: scope of {len(value)} stretches. FIX: give at most {MAX_SCOPE}, each under 200 "
                         "characters.")
    return [x.strip() for x in value]


MAX_SCOPE = 12


def _fits_log(rows: list, las, las_unit) -> dict | None:
    """Whether the formations fall on the log: each one wholly beyond the log's depths is marked (outside), and when
    most are, whether their depths read in the other unit would fit it (a file in feet labelled metres: its
    interval had no sample and the question was refused only after it was asked)."""
    from petroharness.well.tops import convert
    try:
        info = las_info(las)
    except Exception:  # noqa: BLE001  (no range to check against: nothing said)
        return None
    lo, hi, lu = info.get("top"), info.get("base"), info.get("depth_unit") or las_unit
    if lo is None or hi is None or lu not in ("m", "ft"):
        return None
    placed = [r for r in rows if r.get("top") is not None]
    def inside(top, base, unit) -> bool:
        t = convert(float(top), unit or lu, lu)
        b = convert(float(base), unit or lu, lu) if base is not None else hi
        return b >= lo and t <= hi
    out = 0
    for r in placed:
        if not inside(r["top"], r.get("base"), r.get("unit")):
            r["outside"] = True
            out += 1
    said = {"outside": out, "of": len(placed), "log": f"{lo:g}-{hi:g} {lu}"}
    if placed and out * 2 > len(placed):
        units = {r.get("unit") or lu for r in placed}
        if len(units) == 1:
            stated = units.pop()
            other = "ft" if stated == "m" else "m"
            if sum(inside(r["top"], r.get("base"), other) for r in placed) * 2 > len(placed):
                said["hint"] = (f"{out} of {len(placed)} formations fall beyond the log ({lo:g}-{hi:g} {lu}); read in "
                                f"{other} they fit it. The file's depth unit ({stated}) may be wrong: fix it in the file.")
            else:
                said["hint"] = f"{out} of {len(placed)} formations fall beyond the log ({lo:g}-{hi:g} {lu})."
    return said


def _number(value, what: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise InputError(f"WHAT: the {what} {value!r} is not a number. FIX: give a depth such as 1520.5.") from None


def _unit(value) -> str | None:
    from petroharness.well.tops import depth_unit_name
    if value in (None, ""):
        return None
    got = depth_unit_name(value)
    if got is None:
        raise InputError(f"WHAT: depth unit {value!r} is not m or ft. FIX: choose m or ft.")
    return got


def arguments(inputs: dict) -> dict:
    """The page's inputs as petroharness.ask's keyword arguments, checked: what can be wrong in them is said now,
    before the question waits for a worker."""
    if not isinstance(inputs, dict):
        raise InputError("WHAT: the request is not a JSON object. FIX: send the page's form.")
    las = _file(inputs.get("las"), "LAS file")
    question = str(inputs.get("question") or "").strip()
    if not question:
        raise InputError("WHAT: the question is empty. FIX: write the question to answer.")
    if len(question) > MAX_QUESTION:
        raise InputError(f"WHAT: the question has {len(question)} characters. FIX: keep it under {MAX_QUESTION}.")
    kw: dict = {"las": las, "question": question}
    from petroharness.well.prepare import depth_order
    try:
        problem = depth_order(las)                             # spliced runs, a repeated section: said now
    except Exception:  # noqa: BLE001  (a file that cannot be read is said by the worker, with the reader's message)
        problem = ""
    if problem:
        raise InputError(problem)
    iv = inputs.get("interval") or {"mode": "whole"}
    mode = str(iv.get("mode") or "whole")
    if mode == "tops":
        tops = _file(iv.get("tops"), "tops file")
        formation = str(iv.get("formation") or "").strip()
        if not formation:
            raise InputError("WHAT: no formation chosen. FIX: pick one of the names the tops file lists.")
        row = _number(iv.get("top"), "top")              # which listing, for a name the file lists twice
        kw.update(tops=tops, formation=formation, depth_unit=_unit(iv.get("unit")))
        if row is not None:
            kw["top"] = row
        from petroharness.interval import _las_header
        from petroharness.well.tops import read_tops
        las_unit, names = _las_header(las)
        try:
            read_tops(tops, names, kw["depth_unit"], las_unit).interval(formation, row)
        except (ValueError, LookupError, OSError) as exc:
            raise InputError(str(exc)) from None
    elif mode == "depths":
        top, base = _number(iv.get("top"), "top"), _number(iv.get("base"), "base")
        if top is None and base is None:
            raise InputError("WHAT: no depths given. FIX: give the interval's top and base (or choose the whole well).")
        if top is not None and base is not None and base <= top:
            raise InputError(f"WHAT: the base ({base:g}) is not below the top ({top:g}). FIX: give the top above the "
                             "base (depths increase downwards).")
        name = str(iv.get("name") or "").strip()
        kw.update(top=top, base=base, depth_unit=_unit(iv.get("unit")), formation=name or None)
    elif mode != "whole":
        raise InputError(f"WHAT: interval mode {mode!r}. FIX: use whole, tops or depths.")
    for key in ("lithology_curve", "formation_lithology"):
        value = str(inputs.get(key) or "").strip()
        if value:
            kw[key] = value
    zones = str(inputs.get("zones") or "").strip()
    if zones:                                                  # the user's zones: they frame the interval (Z ids)
        kw["zones"] = str(_file(zones, "zones file"))
        info = zones_info(kw["zones"], las)                    # a file Petrophys cannot read is said now, and zones
        if info["overlaps"]:                                   # that overlap, which the question would refuse
            raise InputError(f"WHAT: zones of {info['name']} overlap: {info['overlaps'][0]} FIX: correct the file, "
                             "or ask without your zones.")
    profile = str(inputs.get("profile") or "").strip()
    if profile:
        known = context_profiles()
        if known and profile not in known:
            raise InputError(f"WHAT: no context profile {profile!r}. FIX: choose one of {', '.join(known)}, or none.")
        kw["profile"] = profile
    skills = str(inputs.get("skills") or "").strip()
    if skills and skills.lower() not in ("default", "none"):
        p = Path(skills).expanduser()
        if not p.is_dir():
            raise InputError(f"WHAT: no skill library folder at {skills}. FIX: give a library folder (laid out as the "
                             "packaged one), or choose the default library or none.")
        kw["skills"] = str(p.resolve())
    elif skills.lower() == "none":
        kw["skills"] = "none"
    steps = inputs.get("max_steps")
    if steps not in (None, ""):
        try:
            steps = int(steps)
        except (TypeError, ValueError):
            raise InputError(f"WHAT: max steps {steps!r} is not a whole number. FIX: give 1 to {MAX_STEPS_LIMIT}.") from None
        if not 1 <= steps <= MAX_STEPS_LIMIT:
            raise InputError(f"WHAT: max steps {steps}. FIX: give 1 to {MAX_STEPS_LIMIT}.")
        kw["max_steps"] = steps
    depth = str(inputs.get("depth") or "").strip().lower()
    if depth == "investigate":                                # default: the model says whether a question is direct
        kw["direct"] = False
    elif depth not in ("", "auto"):
        raise InputError(f"WHAT: depth {depth!r}. FIX: leave it out (the model decides), or give 'investigate' for a "
                         "full investigation of every question.")
    chosen = inputs.get("interpretation") or {}
    if chosen:
        if not isinstance(chosen, dict):
            raise InputError("WHAT: the interpretation settings are not a table of setting -> value. FIX: send "
                             "{\"setting\": value, ...}, or leave them out for the defaults.")
        from petroharness.well import settings as T
        wrong = T.validate(chosen)
        if wrong:
            raise InputError("WHAT: interpretation settings that cannot be used: "
                             + "; ".join(f"{k}: {v}" for k, v in wrong.items()) + ". FIX: correct or reset them.")
        if kw.get("profile") and T.split(chosen)[0]:
            raise InputError("WHAT: Petrophys settings with a context profile. WHY: a profile fixes its own settings. "
                             "FIX: choose no profile, or reset the Petrophys settings.")
        kw["interpretation"] = dict(chosen)
    notes = str(inputs.get("field_notes") or "").strip()
    if notes:                                     # checked now: the file, its settings, and a profile's conflict
        info = notes_info(notes)
        from petroharness.well import settings as T
        if kw.get("profile") and T.split(info["settings"])[0]:
            raise InputError("WHAT: field notes with Petrophys settings and a context profile. WHY: a profile fixes "
                             "its own settings. FIX: choose no profile, or field notes without Petrophys settings.")
        kw["field_notes"] = info["path"]
    return kw


PREPARE_KEYS = ("formation", "tops", "top", "base", "depth_unit", "lithology_curve", "formation_lithology", "profile",
                "skills", "interpretation", "field_notes")


def notes_info(path) -> dict:
    """A field notes file as the page shows it: {path, name, settings, notes}, checked (petroharness.well.notes)."""
    from petroharness.well.notes import load
    p = _file(path, "field notes file")
    try:
        n = load(p)
    except (ValueError, OSError) as exc:
        raise InputError(str(exc)) from None
    return {k: n[k] for k in ("path", "name", "settings", "notes")}


def view_of(inputs: dict, cache: Path):
    """The interval's view for a run's inputs: the well as Petrophys interpreted it under the run's settings (read from
    `cache`, the runs' shared cache, where the run left it), the interval and its zones. For the log viewer."""
    from petroharness import interval as I
    kw = arguments({**inputs, "question": "(the logs)"})
    las = kw.pop("las")
    p = I.prepare(las, "logs", I.Inputs.of({k: v for k, v in kw.items() if k in PREPARE_KEYS}).loaded(), cache=cache)
    I.check(p, I.task_for(p, "(the interval)")[0])
    return p.view


def preview(inputs: dict, cache: Path) -> dict:
    """What Petrophys makes of this well under these settings, before any question: the interval, its zones under the
    zone rule, how the zones were read (the lithology log, or shale-volume bands), and the value each setting took
    ({setting: {"value", "step"}}: the defaults the data decides, for this well). The interpreted well is kept in
    `cache` (the runs' shared cache), so the question that follows reuses it."""
    from petroharness import interval as I
    from petroharness.well import settings as T
    kw = arguments({**inputs, "question": "(a preview of the interpretation)"})
    las = kw.pop("las")
    inputs = I.Inputs.of({k: v for k, v in kw.items() if k in PREPARE_KEYS}).loaded()   # field notes' settings under
    p = I.prepare(las, "preview", inputs, cache=cache)                                # the ones set here
    I.check(p, I.task_for(p, "(the interval)")[0])
    view = p.view
    zones = view.zones
    thick = [float(z.base - z.top) for z in zones]
    return {"interval": p.used, "lithology": p.litho, "unit": view.depth_unit,
            "zones": [{"zone": z.zone_id, "lithology": z.lithology, "top": round(float(z.top), 4),
                       "base": round(float(z.base), 4)} for z in zones],
            "zoned": round(sum(thick), 4), "interval_thickness": round(float(view.interval.base - view.interval.top), 4)
            if view.interval.base is not None and view.interval.top is not None else None,
            "min_thickness": round(view.to_unit(float(view.policy["zones"]["min_thickness_m"])), 4)
            if hasattr(view, "to_unit") else None,
            "used": T.used(view.prep)}


def context_profiles() -> list:
    """Petrophys's context profiles (petrophys.reporting.context_profiles; empty when the installed Petrophys lists
    none)."""
    try:
        from petrophys.reporting.context_profiles import list_context_profiles
        return list(list_context_profiles())
    except Exception:  # noqa: BLE001  (a Petrophys without profiles, or one that fails to list them: none offered)
        return []


def interval_label(inputs: dict) -> str:
    """The interval as the run list names it."""
    iv = inputs.get("interval") or {}
    mode = iv.get("mode") or "whole"
    if mode == "tops":                          # a name the file lists twice: the listing chosen, by its top
        try:
            row = float(iv["top"]) if iv.get("top") not in (None, "") else None
        except (TypeError, ValueError):
            row = None
        return str(iv.get("formation") or "") + (f" from {row:g}" if row is not None else "")
    if mode == "depths":
        span = f"{iv.get('top') if iv.get('top') not in (None, '') else 'log top'}-" \
               f"{iv.get('base') if iv.get('base') not in (None, '') else 'log base'}"
        return str(iv.get("name") or "").strip() or f"{span} {iv.get('unit') or ''}".strip()
    return "whole well"


# --- one question ----------------------------------------------------------------------------------------------------

class Job:
    """One question: its inputs, its live events, then the answer and what the page shows of the trace."""

    def __init__(self, run_id: str, inputs: dict, kwargs: dict):
        self.id = run_id
        self.inputs = inputs
        self.kwargs = kwargs
        self.events: list = []
        self.status = "queued"
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.endpoint = ""
        self.answer = ""
        self.result: dict | None = None
        self.error = ""
        self.rating: dict = {}
        self.root = run_id                 # the run that started this conversation (itself, for a first question)
        self.conversation: dict = {}       # {root, turn, thread: [{turn, question, run}]}, once the question ran
        self.saved = False                 # its finished record is on disk (the server sets it after saving)
        self.live: dict = {}               # the model call in flight as it streams (progress.Observed); never saved
        self._lock = threading.Lock()

    def emit(self, event: dict) -> None:
        t0 = self.started or self.created
        with self._lock:
            self.events.append({"t": round(max(time.time() - t0, 0.0), 1), **event})

    def set_live(self, now: dict) -> None:
        with self._lock:
            self.live = now

    def elapsed(self) -> float:
        if self.started is None:
            return 0.0
        return round((self.finished or time.time()) - self.started, 1)

    def view(self, since: int = 0, final: bool | None = None) -> dict:
        """What the page is given. A job shows as finished once its record is saved, so whoever sees it finished finds
        the record on disk (final=True: the record itself, as it is)."""
        with self._lock:
            events = self.events[since:]
            n = len(self.events)
            live = dict(self.live) if self.finished is None else {}
        finished = self.finished is not None and (self.saved if final is None else final)
        status = self.status if finished or self.finished is None else "running"
        return {"id": self.id, "status": status, "inputs": self.inputs, "label": interval_label(self.inputs),
                "created": _iso(self.created), "elapsed": self.elapsed(), "endpoint": self.endpoint,
                "events": events, "n_events": n, "answer": self.answer if finished else "",
                "result": self.result if finished else None, "error": self.error, "rating": self.rating,
                "conversation": self.conversation or {"root": self.root}, **({"live": live} if live else {})}

    def record(self) -> dict:
        return self.view(0, final=True) | {"finished": _iso(self.finished) if self.finished else None}


def _iso(t: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="seconds")


_ASKING: dict = {}                     # a conversation's folder -> its lock: one question of it at a time
_ASKING_GUARD = threading.Lock()


def _asking(session: Path) -> threading.Lock:
    with _ASKING_GUARD:
        return _ASKING.setdefault(str(session), threading.Lock())


def run(job: Job, out: Path, model_url: str | None, model_factory: Callable | None = None,
        root_out: Path | None = None) -> None:
    """Answer the job's question as a question of a conversation (petroharness.session), reporting the interval's
    logs once Petrophys has interpreted the well (a `well` event: petroharness.ui.wellplot) and each model call as it
    happens. A first question starts the conversation in `out`/session and is answered as petroharness.ask answers
    it; a follow-up (`root_out`: the folder of the conversation's first run) resumes that conversation. The answer,
    the trace and the figures are written to `out`. model_factory(cfg) builds the model client (default: the
    harness's own LLM)."""
    import shutil

    from petroharness.llm import LLM
    from petroharness.session import Conversation

    base = model_factory or LLM
    job.status, job.started = "running", time.time()
    job.emit({"kind": "phase", "name": "started", "endpoint": model_url or ""})
    job.emit({"kind": "phase", "name": "interpreting"})
    def plot(view) -> None:                                   # the interval's logs, once Petrophys has read the well
        try:
            from petroharness.ui.wellplot import payload
            job.emit({"kind": "well", **payload(view)})
        except Exception as exc:  # noqa: BLE001  (the plot never fails the run)
            job.emit({"kind": "well", "error": f"{type(exc).__name__}: {exc}"})

    try:
        from petroharness.ui.progress import Observed
        kw = dict(job.kwargs)
        question = kw.pop("question")
        numbers = itertools.count(1)                         # one numbering for the run's calls (the question's client
        factory = lambda cfg: Observed(base(cfg), job.emit, numbers, live=job.set_live)   # and the figures call's)
        session = (root_out or out) / "session"
        with _asking(session):
            if root_out is None:
                session.mkdir(parents=True, exist_ok=True)
                cache = out / ".cache"
                if cache.exists() and not (session / ".cache").exists():     # the interpreted wells shared by every run
                    (session / ".cache").symlink_to(cache.resolve(), target_is_directory=True)
                c = Conversation.start(kw.pop("las"), session, **kw, model_url=model_url, llm_factory=factory,
                                       on_view=plot)
            else:
                c = Conversation.resume(session, model_url=model_url, llm_factory=factory, on_view=plot)
                if job.inputs.get("adopt"):               # the settings to run under from this question on
                    want = kw.get("interpretation") or {}
                    delta = {k: v for k, v in want.items() if c.settings.get(k) != v}
                    delta.update({k: None for k in c.settings if k not in want})
                    made = c.adopt(delta, by="user")
                    job.emit({"kind": "settings", "changes": made})
            if c.settings or "interpretation" in job.inputs:   # what the question runs under (a follow-up: the
                job.inputs["interpretation"] = c.settings     # settings in force, changed or not)
            shown = c.overview()                              # the interval's log display by Petrophys, once
            if shown is not None:
                (out / "figures").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(shown, out / "figures" / shown.name)
                job.emit({"kind": "display", "file": shown.name})
            scope = job.inputs.get("scope")
            if scope is not None:                         # a stretch the user chose (an answer to a question back)
                got = c.set_scope([str(x) for x in scope], chosen=True)
                job.emit({"kind": "scope", "scope": got})
            turn = c.ask(question)
            runs = json.loads((session / "runs.json").read_text(encoding="utf-8")) if (session / "runs.json").exists() else {}
            runs[str(turn.number)] = job.id
            (session / "runs.json").write_text(json.dumps(runs), encoding="utf-8")
        for name in ("answer.md", "trace.json"):
            shutil.copyfile(turn.folder / name, out / name)
        if (turn.folder / "figures").is_dir():
            shutil.copytree(turn.folder / "figures", out / "figures", dirs_exist_ok=True)
        job.conversation = {"root": job.root, "turn": turn.number,
                            "thread": [{"turn": r["turn"], "question": r["question"], "status": r["status"],
                                        "run": runs.get(str(r["turn"]))} for r in c.turns]}
        job.answer = turn.answer
        job.result = summary(turn.trace, c.p.used, turn.status)
        job.result["figures"] = [{"caption": g["caption"], "file": Path(g["file"]).name, "kind": g["kind"],
                                  "source": g["source"]} for g in turn.figures]
        job.result["basis"] = turn.basis
        if turn.trace.get("settings"):                    # the conversation's settings changed: in force, and how
            job.result["settings_changes"] = turn.trace["settings"]
        job.status = "done" if turn.ok else "error"
        if not turn.ok:
            job.error = str(turn.trace.get("error") or turn.status)
    except (ValueError, LookupError, OSError) as exc:          # the inputs (ask's own checks): said as ask says them
        job.status, job.error = "error", str(exc)
    except Exception as exc:  # noqa: BLE001  (one question's failure is recorded; the server goes on)
        job.status, job.error = "error", f"{type(exc).__name__}: {exc}"
        job.result = {"traceback": traceback.format_exc()[-4000:]}
    finally:
        job.finished = time.time()
        job.emit({"kind": "phase", "name": "finished", "status": job.status, **({"error": job.error} if job.error else {})})


def _route(trace: dict) -> str:
    from petroharness.agent.graph import route
    return route(trace)


def summary(trace: dict, interval: dict, status: str) -> dict:
    """What the page shows of a run's trace: the interval and zones, the READ, the points and claims, the opened
    results, each step, the settle step, the checker's rounds, the skills, the usage."""
    a = trace.get("ask") or {}
    usage = trace.get("usage") or []
    claims = [{k: c.get(k) for k in ("id", "point", "text", "means", "weak", "grade", "ev", "flags")}
              for c in trace.get("claims") or [] if isinstance(c, dict)]
    from petroharness.ui.progress import edit_view
    steps = []
    for s in trace.get("steps") or []:
        steps.append({"step": s.get("step"), "focus": s.get("focus", ""), "actions": s.get("actions") or [],
                      "guide_sections": s.get("guide_sections") or [],
                      "edits": [edit_view(e) for e in s.get("edits") or [] if e],
                      "edit_msgs": s.get("edit_msgs") or [], "done": s.get("done"), "error": s.get("error"),
                      "repaired": (s.get("repaired") or {}).get("by"), "stopped": s.get("stopped"),
                      "withheld": s.get("withheld") or [], "prompt_tokens": s.get("prompt_tokens")})
    settle = trace.get("settle") or {}
    return {
        "status": status, "seconds": trace.get("seconds"), "interval": interval,
        "question_sent": a.get("question_sent"), "lithology": a.get("lithology"), "zones": a.get("zones") or [],
        "settings": a.get("settings"), "interpret": a.get("interpret"), "petrophys": a.get("petrophys"),
        "read": {k: (trace.get("read") or {}).get(k) for k in ("topics", "named", "parse", "depth")},
        "route": _route(trace),
        "topics": trace.get("topics") or [], "absent": trace.get("absent") or [],
        "points": trace.get("points") or [], "intent": trace.get("intent"),
        "claims": claims,
        "dropped": [{k: c.get(k) for k in ("id", "point", "text")} for c in trace.get("dropped") or [] if isinstance(c, dict)],
        "done_issues": trace.get("done_issues") or [],
        "opened": [{"id": o[0], "call": o[1]} for o in trace.get("opened") or [] if isinstance(o, (list, tuple))],
        "errors": trace.get("errors") or [],
        "guides": trace.get("guides") or [], "skills": trace.get("skills"), "skills_given": a.get("skills_given"),
        "steps": steps,
        "settle": {k: settle.get(k) for k in ("claims_before", "claims_after", "issues_after", "error")}
                  | {"edits": len(settle.get("edits") or [])} if settle else None,
        "verify_rounds": trace.get("verify_rounds") or [],
        "zone_table": trace.get("zone_table") or "",
        "usage": {"calls": len(usage), "prompt_tokens": sum(u.get("prompt_tokens") or 0 for u in usage),
                  "completion_tokens": sum(u.get("completion_tokens") or 0 for u in usage),
                  "seconds": round(sum(u.get("seconds") or 0 for u in usage), 1),
                  "log": [{k: u.get(k) for k in ("stage", "prompt_tokens", "completion_tokens", "seconds")} for u in usage]},
        "error": trace.get("error"), "traceback": trace.get("traceback"),
        # the question back to the user (or a request outside the well's logs) and the answers to pick: the page's
        # buttons, each a question to send and, for a stretch, the scope set first (agent.read.ask_back)
        "ask": {"text": trace.get("ask_user") or "", "outside": bool(trace.get("outside")),
                "choices": [c for c in trace.get("ask_choices") or [] if isinstance(c, dict) and c.get("question")]}
               if status in ("ask_user", "outside") else None,
        "notes": _notes(trace),
        # the stretch the answer computed on, when not the interval: as used, who set it, and what its items became
        "scope": {"used": list((trace.get("scope") or {}).get("used") or []),
                  "by": "your choice" if trace.get("scope_chosen") else (trace.get("scope") or {}).get("by") or "the question",
                  "merged": (trace.get("scope") or {}).get("merged") or "", "note": (trace.get("scope") or {}).get("note") or ""},
    }


def _notes(trace: dict) -> list:
    """What the answer's reader should know before the numbers, each one sentence, worded for the reader from the
    notes the harness recorded as data under the question (agent.vocabulary.facts): measurements the record does not
    hold or holds with no value here, units the tops file lacks, the user's zones with no sample here. A run saved
    before the notes were recorded as data shows the lines the model was given."""
    facts = trace.get("reader_notes")
    if not facts:
        return [ln.strip() for ln in str(trace.get("question_notes") or "").splitlines() if ln.strip()]
    out = []
    for f in facts:
        kind = f.get("kind")
        if kind == "absent":
            out.append(f"Not in this well's record: {f['name']} (no {' or '.join(f['curves'])} curve).")
        elif kind == "empty":
            said = "; ".join(f"{c['curve']}: {c['why']}" if c.get("why") else c["curve"] for c in f["curves"])
            out.append(f"In this well's record but with no value in this interval: {f['name']} ({said}).")
        elif kind == "absent_unit":
            units = list(f["units"])
            listed = ", ".join(units[:12]) + (f" and {len(units) - 12} more" if len(units) > 12 else "")
            out.append(f"Not a unit of the tops file: {', '.join(f['names'])}. No value of another stretch is given "
                       f"for it; the file lists {listed}.")
        elif kind == "zones_left":
            for z in f["zones"]:
                out.append(f"Your zone {z['name']}, {z['top']:g}–{z['base']:g} {z['unit']}: {z['why']}. Nothing is "
                           "computed for it.")
    return out
