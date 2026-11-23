"""Well preparation: read the raw LAS and interpret it with Petrophys (petrophys.interpret with the library's settings
and the policy's cutoffs, or with a context profile; the data's own interpreter; or a pinned engine the policy names);
the prepared well is cached by content."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Optional

import numpy as np


def _read(path: Path):
    from petrophys.io import read_las

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return read_las(Path(path))


def read_depth(path: Path) -> np.ndarray:
    return np.asarray(_read(path).depth, dtype=float)


def depth_order(path: Path, depth: Optional[np.ndarray] = None) -> str:
    """What is wrong with the order of a LAS file's depths, as a WHAT / WHY / FIX message naming where, else "": a depth
    that goes back against the file's direction (spliced runs, a repeated section: the stretch between is logged twice
    and would be counted twice in every result), a depth given twice in a row, or depths that decrease down the whole
    file (logged bottom up: zones and every depth-ordered result read a log top down, and its zones would come out
    empty). Petrophys warns of the first two ("depth changes direction", "duplicate depth values") without saying where;
    which samples to keep, and the file's order, are the user's to fix, so the file is refused, not reordered."""
    d = np.asarray(read_depth(path) if depth is None else depth, dtype=float)
    rows = np.where(np.isfinite(d))[0]
    if rows.size < 2:
        return ""
    step = np.diff(d[rows])
    moving = step[step != 0]
    sign = 1.0 if not moving.size or np.median(moving) > 0 else -1.0
    back, same = np.where(step * sign < 0)[0], np.where(step == 0)[0]
    if not back.size and not same.size and sign > 0:
        return ""
    name, unit, lines = Path(path).name, _depth_unit(path), _data_lines(path, d.size)
    g = lambda x: f"{round(float(x), 4):.10g}"              # a depth as the file writes it, to 4 decimals
    at = lambda i: f"line {lines[rows[i]]}" if lines else f"sample {rows[i] + 1}"
    more = lambda n: f" (and {n} more place{'s' if n != 1 else ''})" if n else ""
    if back.size:
        i = back[0]
        hi, lo = d[rows[i]], d[rows[i + 1]]
        return (f"WHAT: the depth in {name} goes back at {at(i + 1)}, from {g(hi)} to {g(lo)}{unit}{more(back.size - 1)}: "
                f"{g(min(hi, lo))}-{g(max(hi, lo))}{unit} is logged twice (spliced runs or a repeated section). WHY: each "
                "depth is one sample; a stretch logged twice would be counted twice in every result. FIX: keep one run "
                "over the overlap so the depths run one way down the file, and load it again.")
    if not same.size:                                       # one way, but bottom up
        return (f"WHAT: the depth in {name} decreases down the file, from {g(d[rows[0]])} at {at(0)} to "
                f"{g(d[rows[-1]])}{unit} at {at(rows.size - 1)} (logged bottom up). WHY: zones and every depth-ordered "
                "result read a log top down; read bottom up, the interval would hold no zone. FIX: write the file with "
                "depth increasing down the file, and load it again.")
    i = same[0]
    return (f"WHAT: the depth {g(d[rows[i]])}{unit} is given twice in {name}, at {at(i)} and {at(i + 1)}"
            f"{more(same.size - 1)}. WHY: each depth is one sample; a depth given twice would be counted twice. FIX: "
            "keep one row per depth, and load the file again.")


def _depth_unit(path: Path) -> str:
    """" m" or " ft" for the LAS's depth unit, else ""."""
    import lasio

    from petroharness.well.tops import depth_unit_name
    try:
        head = lasio.read(str(path), ignore_data=True)
        unit = depth_unit_name(head.curves[0].unit) if len(head.curves) else None
    except Exception:  # noqa: BLE001  (no unit read: the depths are said without one)
        unit = None
    return f" {unit}" if unit else ""


def _data_lines(path: Path, n: int) -> list:
    """The file line (1 = the first) of each of the n data rows of an unwrapped LAS's ~A section, else [] (a wrapped
    file, or rows that do not match n: the place is then said by its sample number)."""
    out, inside = [], False
    with open(path, "r", encoding="utf-8", errors="replace") as stream:
        for k, line in enumerate(stream, 1):
            text = line.strip()
            if text.startswith("~"):
                if inside:
                    break
                inside = text[1:2].upper() == "A"
                continue
            if inside and text and not text.startswith("#"):
                out.append(k)
    return out if len(out) == n else []



# ---------------------------------------------------------------------------
# Policy-driven interpretation
# ---------------------------------------------------------------------------

import functools
import hashlib
import json
import os
import pickle
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

import yaml

from petroharness.core.files import write_atomic


def lithology_domain(net_pay_parameters: dict) -> str:
    """The net-pay step's lithology domain (clastic or carbonate). Petrophys records it as `lithology`; an engine may
    record `lithology_domain`. Neither: clastic, the library's default."""
    p = net_pay_parameters or {}
    return str(p.get("lithology_domain") or p.get("lithology") or "clastic")


def load_policy(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# The policy's net-pay cutoffs (cutoffs.<key>) as petrophys.interpret's options (DynamicWorkflowConfig): the harness
# checks that the interpretation used the policy's cutoffs, and the library's own defaults for these differ.
POLICY_CUTOFFS = {"vcl_cutoff": "vcl_max", "sw_cutoff": "sw_max"}


def default_interpret(policy: dict, options: Optional[dict] = None) -> dict:
    """petrophys.interpret's options for a LAS: the given ones over the policy's net-pay cutoffs; a context profile
    fixes its own settings, so options naming one are returned as given."""
    options = dict(options or {})
    if not options.get("context_profile"):
        cutoffs = policy.get("cutoffs") or {}
        for option, key in POLICY_CUTOFFS.items():
            if cutoffs.get(key) is not None:
                options.setdefault(option, cutoffs[key])
    return options


@dataclass
class PreparedWell:
    """An interpreted well (or formation slice) plus the record of how it was interpreted."""

    name: str
    policy: str
    scope: str                      # "full_well" or "formation:<name>"
    well: Any                       # petrophys Well with raw and derived curves
    input_curves: list[str]
    derived_curves: list[str]
    steps: dict[str, dict]          # step -> {method, parameters, decisions}
    header_parameters: dict[str, Any]
    policy_adjustments: dict[str, Any] = field(default_factory=dict)
    # Value-range QC applied to the curves (policy value_range_qc): {"rules": {curve: {low, high, action}},
    # "changed": {curve: bool array of the samples set to NaN or clipped}}. Empty when no QC ran.
    value_qc: dict[str, Any] = field(default_factory=dict)
    # The interpretation's workflow well before what it did after the workflow (a context profile's value-range QC and
    # recomputation of dependent curves, applied to `well`): a zone's well is built from it as the profile's package
    # builds each group (view.zone_well). None: zones are parts of `well`.
    workflow_well: Any = None

    @property
    def context_profile(self) -> Optional[str]:
        """The petrophys context profile the well was interpreted with (data.interpret), else None."""
        return ((self.policy_adjustments or {}).get("interpret") or {}).get("context_profile")

    @property
    def depth(self) -> np.ndarray:
        return np.asarray(self.well.depth, dtype=float)

    def curve(self, name: str) -> Optional[np.ndarray]:
        c = self.well.get(name)
        return None if c is None else np.asarray(c.data, dtype=float)

    def unit(self, name: str) -> str:
        c = self.well.get(name)
        return "" if c is None else str(getattr(c, "unit", "") or "")


class _Subset:
    """A view of some curves of a well (for applying QC to those only)."""

    def __init__(self, well, names):
        self._well, self.curves = well, list(names)

    def get(self, name):
        return self._well.get(name)


def _apply_value_qc(well) -> dict[str, Any]:
    """The installed library's value-range QC (physical plausibility per curve family), applied in place.

    Returns the rules that changed something and, per curve, the samples they changed, so the card can say how
    much of an interval the QC removed instead of hiding it."""
    from petrophys.preprocessing.quality.value_ranges import clean_curve_values

    rules, changed = {}, {}
    for name in list(well.curves):
        curve = well.get(name)
        old = np.asarray(curve.data, dtype=float)
        new, item = clean_curve_values(name, old)
        if item is None or not item["changed"]:
            continue
        rules[name] = {"low": item["low"], "high": item["high"], "action": item["action"]}
        changed[name] = ~((old == new) | (np.isnan(old) & np.isnan(new)))
        curve._data = new
    return {"rules": rules, "changed": changed} if rules else {}


def _sync_after_qc(well) -> None:
    """petrophys' step after value-range QC (reference_export._synchronize_post_qc_dependent_curves): BVW, PHI_NORM,
    RQI and FZI recomputed from the cleaned PHIE / SW / PERM, so no dependent value survives where the QC removed its
    input (before: 1174 BVW and 1458 RQI / FZI samples of the 112 benchmark formations did)."""
    from petrophys.reporting.reference_export import _synchronize_post_qc_dependent_curves
    _synchronize_post_qc_dependent_curves(well)


def engine_dir(policy: dict, engines_dir: Optional[Path]) -> Optional[Path]:
    """The source tree of the engine the policy names (None when it names none, or "installed": petrophys.interpret
    interprets with the library's settings, default_interpret)."""
    name = policy.get("engine")
    if not name or name == "installed":
        return None
    if engines_dir is None:
        raise ValueError(f"WHAT: the policy names engine {name!r} but no engines directory is configured. "
                         "FIX: set data.engines_dir.")
    path = Path(engines_dir) / name
    meta = path / "ENGINE.json"
    if not meta.exists():
        raise FileNotFoundError(f"WHAT: interpretation engine {name!r} not found at {path}. WHY: the policy names it as "
                                "its workflow of record. FIX: build the pinned engine (docs/DEVELOPMENT.md), or set data.engines_dir.")
    if json.loads(meta.read_text(encoding="utf-8")).get("name") != name:
        raise ValueError(f"WHAT: {meta} does not describe engine {name!r}. FIX: rebuild the engine directory.")
    return path


# Spellings of the same unit: an engine's reader can keep the LAS spelling where the installed library normalizes it.
UNIT_SPELLINGS = {"gapi": "API", "m3/m3": "v/v", "frac": "v/v", "dec": "v/v"}


def _interpret_with_engine(las_path: Path, engine: Path, value_range_qc: bool):
    """Run a pinned engine (src/petroharness/well/runner.py) in its own interpreter on the raw LAS."""
    import subprocess
    import sys
    import tempfile

    from petrophys.model.well import Well

    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "out"
        proc = subprocess.run([sys.executable, str(Path(__file__).with_name("runner.py")), str(engine),
                               str(las_path), str(prefix), json.dumps({"value_range_qc": value_range_qc})],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-1200:]
            raise RuntimeError(f"WHAT: engine {engine.name} failed on {Path(las_path).name}. WHY: {tail} "
                               "FIX: run src/petroharness/well/runner.py on this LAS to reproduce.")
        arrays = np.load(f"{prefix}.npz")
        meta = json.loads(Path(f"{prefix}.json").read_text(encoding="utf-8"))
        well = Well(meta["well"])
        well.depth = np.asarray(arrays["__depth__"], dtype=float)
        well.depth_unit = meta["depth_unit"] or "m"
        changed = {n[len("__qc__"):]: np.asarray(arrays[n], dtype=bool) for n in arrays.files if n.startswith("__qc__")}
        report = {r["curve"]: r for r in meta.get("value_range_qc_report") or [] if r.get("changed")}
        qc = {"rules": {n: {k: report.get(n.upper(), {}).get(k) for k in ("low", "high", "action")} for n in changed},
              "changed": changed} if changed else {}
        for name in arrays.files:
            if name != "__depth__" and not name.startswith("__qc__"):
                unit = meta["units"].get(name, "")
                well.add_curve(name, np.asarray(arrays[name], dtype=float), UNIT_SPELLINGS.get(unit.lower(), unit), name)
    return well, set(meta["input_curves"]), meta["steps"], meta["header"], meta["engine"], qc


def _interpret_with_interpreter(las_path: Path, spec: str):
    """Interpret one LAS with the data's petrophys batch interpreter (data.interpreter, "module:function"): it reads a
    folder of LAS files, so it gets a folder holding this one. Returns the interpreted well, the LAS's own curves, the
    step record and the workflow result."""
    import importlib
    import tempfile

    module, _, name = spec.rpartition(":")
    try:
        if module.endswith(".py"):                  # an adapter file kept with the data
            import importlib.util
            loader = importlib.util.spec_from_file_location(Path(module).stem, module)
            mod = importlib.util.module_from_spec(loader)
            loader.loader.exec_module(mod)
        else:
            mod = importlib.import_module(module)
        interpret = getattr(mod, name)
    except (ImportError, AttributeError, FileNotFoundError) as exc:
        raise ValueError(f"WHAT: data.interpreter {spec!r} is not a function ({exc}). FIX: give 'module:function' of a "
                         "petrophys batch interpreter.") from exc
    with tempfile.TemporaryDirectory() as tmp, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        source = Path(tmp) / "las"
        source.mkdir()
        (source / las_path.name).symlink_to(las_path.resolve())
        items = interpret(source, Path(tmp) / "out", well_names=[las_path.stem])
    if len(items) != 1 or not items[0].success or items[0].result is None:
        errors = "; ".join(e for it in items for e in (it.errors or [])) or f"{len(items)} results"
        raise RuntimeError(f"WHAT: {spec} did not interpret {las_path.name} ({errors}). FIX: run it on this LAS to see why.")
    item = items[0]
    result = item.result
    return result.well, set(item.input_curves), _step_record(result.base_result.steps_executed), result


def unknown_interpret_options(options: dict) -> list:
    """The options petrophys.interpret does not declare: neither its own parameters nor a setting of
    petrophys.DynamicWorkflowConfig (as Petrophys declares them; [] when it declares none this can read)."""
    import dataclasses
    import inspect

    import petrophys
    config = getattr(petrophys, "DynamicWorkflowConfig", None)
    if config is None or not dataclasses.is_dataclass(config):
        return []
    named = {k for k, v in inspect.signature(petrophys.interpret).parameters.items()
             if v.kind not in (v.VAR_KEYWORD, v.VAR_POSITIONAL)}
    known = named | {f.name for f in dataclasses.fields(config) if not f.name.startswith("_")}
    return sorted(k for k in options if k not in known)


def _interpret_with_petrophys(las_path: Path, options: dict):
    """Interpret one LAS with petrophys.interpret(las, **options) (data.interpret), e.g. with a context profile, which
    interprets a well of a petrophys context package as that package's context does and records every calculation in
    its steps (the profile's preparation, the workflow, the context's QC and recomputation). Returns the interpreted
    well, the step record, the value-range QC it applied and its workflow's own well (None: not kept)."""
    import petrophys

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            result = petrophys.interpret(las_path, **options)
        except TypeError as exc:                 # Petrophys refuses settings it does not have: the user's to correct
            unknown = unknown_interpret_options(options)
            if not unknown:
                raise
            raise ValueError(f"WHAT: data.interpret names settings Petrophys does not have: {', '.join(unknown)}. "
                             "WHY: they are passed to petrophys.interpret as they are. FIX: correct or remove them "
                             "(the settings are the fields of petrophys.DynamicWorkflowConfig).") from exc
    if result.errors or not result.has_usable_interpretation:       # a step that could not run is recorded, not fatal
        raise RuntimeError(f"WHAT: petrophys.interpret({las_path.name}, {options}) gave no interpretation: "
                           f"{'; '.join(result.errors) or result.status}. FIX: run it on this LAS to see why.")
    steps = _step_record(result.steps_executed)
    raw = [s.to_dict() for s in result.steps_executed]
    for name, entry in steps.items():
        entry["stage"] = step_stage(name)
    # the workflow's own well, before the profile's QC and recomputation (petrophys keeps it as the result's context
    # run, from which its group statistics take a group's samples; no public accessor yet)
    workflow_well = getattr(getattr(result, "_context_run", None), "well", None)
    # the value-range rules that changed something, from the step that reports them, and the samples each changed: where
    # the workflow's value and the interpreted value differ (petrophys records how many, not which)
    rules = {c["curve"]: {k: c.get(k) for k in ("low", "high", "action")}
             for d in raw for c in (d.get("parameters") or {}).get("changes") or []
             if isinstance(c, dict) and c.get("curve") and c.get("changed")}
    changed = {}
    for c in rules if workflow_well is not None else []:
        old, new = workflow_well.get(c), result.well.get(c)
        if old is not None and new is not None and np.shape(old.data) == np.shape(new.data):
            a, b = np.asarray(old.data, dtype=float), np.asarray(new.data, dtype=float)
            changed[c] = ~((a == b) | (np.isnan(a) & np.isnan(b)))
    qc = ({"rules": rules, "changed": changed} if changed else {"rules": rules}) if rules else {}
    return result.well, steps, qc, workflow_well


def step_stage(name: str) -> str:
    """Where a step of a petrophys record ran: "preparation" (a context profile's preparation, before the workflow),
    "after" (the profile's QC and recomputation, after it) or "workflow"; petrophys names the first two preparation_*
    and context_*."""
    return "preparation" if name.startswith("preparation_") else "after" if name.startswith("context_") else "workflow"


def _step_record(steps_executed) -> dict:
    """The step record of a petrophys workflow result, in order: step -> step_entry (a name recorded twice keeps both,
    the later as name_2), bad-hole thresholds included."""
    steps: dict = {}
    for s in steps_executed:
        name = str(s.step)
        steps[name if name not in steps else f"{name}_{sum(k == name or k.startswith(name + '_') for k in steps) + 1}"] = \
            step_entry(s.to_dict())
    if "bad_hole" in steps:
        from petrophys.preprocessing.quality.bad_hole.flag_generator import generate_bad_hole_flags

        from petroharness.well.runner import bad_hole_thresholds
        steps["bad_hole"]["parameters"] = bad_hole_thresholds(generate_bad_hole_flags) | (steps["bad_hole"].get("parameters") or {})
    return steps


def _numeric(v) -> bool:
    """A recorded cutoff that is one number (a cutoff set per depth by lithology is recorded as text)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_engine_cutoffs(steps: dict, cut: dict, well=None) -> None:
    """A policy that names an engine must state the cutoffs that engine used (the card and the checks quote them).

    Recorded cutoffs are compared directly. An engine that records no single porosity cutoff (per-depth cutoffs by
    lithology) is checked on its curves: no NET_RES sample may have porosity at or below the policy's lowest PHIE
    cutoff, and no net-rock sample above its highest cutoff may be left out of NET_RES."""
    p = (steps.get("net_pay") or {}).get("parameters") or {}
    if well is not None and not _numeric(p.get("phie_cutoff")):     # none, or per depth ("lithology_dependent")
        _check_porosity_cutoff_on_curves(steps, cut, well)
    domain = lithology_domain(p)
    want = {"vcl_cutoff": cut.get("vcl_max"), "sw_cutoff": cut.get("sw_max"),
            "phie_cutoff": cut.get("phie_min_carbonate" if domain == "carbonate" else "phie_min_clastic")}
    bad = {k: (p.get(k), v) for k, v in want.items() if v is not None and _numeric(p.get(k)) and abs(float(p[k]) - float(v)) > 1e-12}
    if bad:
        raise RuntimeError(f"WHAT: the engine used cutoffs {bad} (engine, policy). WHY: the policy describes the engine's "
                           "workflow. FIX: make the policy's cutoffs match the engine.")


def _check_porosity_cutoff_on_curves(steps: dict, cut: dict, well) -> None:
    import re

    phi_cuts = [cut[k] for k in ("phie_min_clastic", "phie_min_carbonate") if cut.get(k) is not None]
    rock, res = well.get("NET_ROCK"), well.get("NET_RES")
    if not phi_cuts or rock is None or res is None:
        return
    decisions = " ".join(d for d in (steps.get("net_pay") or {}).get("decisions") or [] if isinstance(d, str))
    named = re.search(r"NET_RES:\s*\+\s*([A-Z_]+)\s*>", decisions)
    phi_curve = well.get(named.group(1)) if named else None
    phi_curve = phi_curve if phi_curve is not None else well.get("PHIE")
    if phi_curve is None:
        return
    phi = np.asarray(phi_curve.data, dtype=float)
    in_rock, in_res = np.asarray(rock.data, float) > 0.5, np.asarray(res.data, float) > 0.5
    too_low = int(np.sum(in_res & np.isfinite(phi) & (phi <= min(phi_cuts) - 1e-9)))
    left_out = int(np.sum(in_rock & ~in_res & np.isfinite(phi) & (phi > max(phi_cuts) + 1e-9)))
    if too_low or left_out:
        raise RuntimeError(f"WHAT: the engine's NET_RES does not follow the policy's porosity cutoffs {phi_cuts}: "
                           f"{too_low} reservoir samples at or below the lowest, {left_out} net-rock samples above "
                           "the highest left out. WHY: the policy describes the engine's workflow. FIX: make the "
                           "policy's PHIE cutoffs match the engine.")


def _check_cutoffs(result, cut: dict) -> None:
    """The net-pay flags must use the policy's cutoffs; fail loudly if the library used others."""
    st = next((s for s in result.base_result.steps_executed if s.step == "net_pay"), None)
    if st is None:
        return
    p = st.to_dict().get("parameters") or {}
    domain = lithology_domain(p)
    want = {"vcl_cutoff": cut.get("vcl_max"), "sw_cutoff": cut.get("sw_max"),
            "phie_cutoff": cut.get("phie_min_carbonate" if domain == "carbonate" else "phie_min_clastic")}
    bad = {k: (p.get(k), v) for k, v in want.items() if v is not None and _numeric(p.get(k)) and abs(float(p[k]) - float(v)) > 1e-12}
    if bad:
        raise RuntimeError(f"WHAT: the interpretation used cutoffs {bad} (used, policy). WHY: net pay must follow the "
                           "policy. FIX: check the policy's cutoffs and the library's cutoff handling.")


# Bump when the interpretation code changes what it computes, so cached wells are not reused across versions.
INTERPRETATION_VERSION = 18                # 13: data.interpret; each step's stage; 14: the steps' parameter notes; 15: the Rw check both ways, class labels in category_labels; 16: LAS descriptions (curve_description); 17: written_by; 18: no engine = petrophys.interpret (the installed-library route removed)


def step_entry(d: dict) -> dict:
    """One step of the record: its method, parameters and decisions (and its parameter notes, where Petrophys gives
    them), and the curves it read, wrote and removed where
    the library lists them (inputs/outputs/removed; absent when it does not, so nothing is assumed). The outputs
    include the curves the library lists as also written by the step (also_written). A parameter that holds a whole
    nested step record (e.g. the workflow a preparation ran) is given by its steps' names, and a value-range QC's
    changes (petrophys's report: curve, range, samples changed) are decisions, one line per curve it changed."""
    entry = {k: d.get(k) for k in ("method", "parameters", "decisions")}
    params = d.get("parameters")
    if isinstance(params, dict):
        params, decisions = dict(params), list(d.get("decisions") or [])
        for k, v in list(params.items()):
            if isinstance(v, list) and v and all(isinstance(x, dict) and "step" in x for x in v):
                params[k] = [str(x["step"]) for x in v]
        changes = params.get("changes")
        if isinstance(changes, list) and all(isinstance(c, dict) and "curve" in c for c in changes):
            del params["changes"]
            for c in changes:
                if c.get("changed"):
                    done = "clipped to the range" if c.get("action") == "clip" else "set to NaN"
                    decisions.append(f"{c['curve']}: {c['changed']} samples of the well outside {c.get('low')} to "
                                     f"{c.get('high')} ({c.get('below', 0)} below, {c.get('above', 0)} above) {done}")
        entry["parameters"], entry["decisions"] = params, decisions
    for key, name in (("inputs", "input_curves"), ("outputs", "output_curves"), ("removed", "curves_removed")):
        if isinstance(d.get(name), (list, tuple)) and (d[name] or key != "removed"):
            entry[key] = [str(c) for c in d[name]]
    if isinstance(d.get("also_written"), (list, tuple)) and d["also_written"]:
        entry["outputs"] = list(dict.fromkeys([*entry.get("outputs", []), *(str(c) for c in d["also_written"])]))
    if isinstance(d.get("parameter_notes"), dict) and d["parameter_notes"]:     # what a parameter is, where its name
        entry["notes"] = {str(k): str(v) for k, v in d["parameter_notes"].items()}   #   alone misleads (Petrophys's)
    if isinstance(d.get("written_by"), dict) and d["written_by"]:   # the outputs an analysis the step ran wrote: which
        entry["written_by"] = {str(k): str(v) for k, v in d["written_by"].items()}
    return entry
INTERPRETATION_KEYS = ("name", "engine", "cutoffs", "value_range_qc")


@functools.lru_cache(maxsize=1)
def library_identity() -> str:
    """The installed petrophys: its version and what build it is. A source checkout: its commit (with +dirty for
    uncommitted changes). An installed package: the commit it was installed from where pip recorded one, else a hash
    of its installed files. The value-range QC and the post-QC curves come from it even when an engine interprets, so
    a cached well is valid only for the same library."""
    import petrophys
    src = Path(petrophys.__file__).resolve().parent
    version = getattr(petrophys, "__version__", "?")
    commit = dirty = ""
    try:
        git = lambda *a: subprocess.run(["git", "-C", str(src), *a], capture_output=True, text=True, timeout=10)
        # git answers for any folder inside a repository: an installed package in a virtual environment that sits in
        # some other repository would be given that repository's commit. Only a tracked source file is a checkout.
        if git("ls-files", "--error-unmatch", "__init__.py").returncode == 0:
            commit = git("rev-parse", "HEAD").stdout.strip()
            dirty = git("status", "--porcelain", "--", ".").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit, dirty = "", ""
    if commit:
        return f"{version}@{commit}{'+dirty' if dirty else ''}"
    return f"{version}@{_installed_build('petrophys') or 'no-git'}"


def _installed_build(package: str) -> str:
    """An installed distribution's build: the commit pip recorded for it (an install from a repository), else
    `files-` and a hash of its record of installed files; "" when it is not an installed distribution."""
    import importlib.metadata as md
    try:
        dist = md.distribution(package)
    except md.PackageNotFoundError:
        return ""
    try:
        commit = (json.loads(dist.read_text("direct_url.json") or "{}").get("vcs_info") or {}).get("commit_id")
    except ValueError:
        commit = None
    if commit:
        return str(commit)
    record = dist.read_text("RECORD")
    return f"files-{hashlib.sha256(record.encode()).hexdigest()[:12]}" if record else ""


@functools.lru_cache(maxsize=256)
def _las_digest(path: str, size: int, mtime_ns: int) -> str:
    """The LAS file's content (size and mtime key the memo; the bytes key the cache)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def _cache_path(cache_dir: Path, policy: dict, las_path: Path, scope: str, engine: Optional[Path] = None,
                interpreter: Optional[str] = None, interpret: Optional[dict] = None) -> Path:
    # Only interpretation settings and the LAS content key the cache; display/zone/confidence rules do not change
    # curves. The content is in the key, so a revised LAS under the same name (core curves removed, a bit size added)
    # never reuses a cached well.
    relevant = {k: policy.get(k) for k in INTERPRETATION_KEYS} | {"_version": INTERPRETATION_VERSION,
                                                                  "_library": library_identity()}
    if engine is not None:
        relevant["_engine"] = (engine / "ENGINE.json").read_text(encoding="utf-8")      # identity of the pinned engine
    if interpreter:
        relevant["_interpreter"] = interpreter                          # the data's own workflow of record
        module = interpreter.rpartition(":")[0]
        if module.endswith(".py") and Path(module).is_file():           # an adapter file: its content keys the cache
            relevant["_interpreter_file"] = hashlib.sha256(Path(module).read_bytes()).hexdigest()[:16]
    if interpret is not None:
        relevant["_interpret"] = {k: str(v) for k, v in interpret.items()}  # petrophys.interpret's options
        relevant["_interpret_files"] = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest()[:16]
                                        for k, v in interpret.items() if isinstance(v, str) and Path(v).is_file()}
    digest = hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:8]
    stem = f"{Path(las_path).stem}__{scope.replace(':', '_').replace(' ', '_').replace('/', '_')}"
    if Path(las_path).is_file():                       # the file's content: one folder per policy, a file per content
        st = Path(las_path).stat()
        stem += "__" + _las_digest(str(las_path), st.st_size, st.st_mtime_ns)
    return Path(cache_dir) / f"{policy['name']}_{digest}" / f"{stem}.pkl"


_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def prepare_well(las_path: Path, policy: dict, cache_dir: Optional[Path] = None, *args, **kwargs):
    """The prepared well (_prepare_well), one preparation of a LAS at a time per cache folder: questions on the same
    well in other threads (a benchmark's workers, the web UI) wait and read the cached result instead of interpreting
    the same well again."""
    if cache_dir is None:
        return _prepare_well(las_path, policy, cache_dir, *args, **kwargs)
    key = (str(Path(las_path).resolve()), str(Path(cache_dir).resolve()))
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())
    with lock:
        return _prepare_well(las_path, policy, cache_dir, *args, **kwargs)


def _owned(path: Path) -> bool:
    """A cache file this user wrote: a pickle from a folder others can write could run their code (POSIX only)."""
    return not hasattr(os, "getuid") or path.stat().st_uid == os.getuid()


def _prepare_well(
    las_path: Path,
    policy: dict,
    cache_dir: Optional[Path] = None,
    engines_dir: Optional[Path] = None,
    interpreter: Optional[str] = None,
    interpret: Optional[dict] = None,
) -> PreparedWell:
    """Read and standardize the raw LAS, interpret the whole log once, cache the result.

    `interpreter` (data.interpreter) has the data's own batch interpreter interpret it, `interpret`
    (data.interpret) petrophys.interpret with those options; otherwise the engine the policy names
    (its workflow of record, a pinned library under `engines_dir`) interprets the raw LAS unchanged,
    and with no engine named petrophys.interpret runs with the library's settings and the policy's
    cutoffs (default_interpret), as `petroharness ask` does.
    """
    from petrophys.preprocessing.standardization import standardize_curves

    if interpreter and interpret is not None:
        raise ValueError("WHAT: both data.interpreter and data.interpret are set. FIX: keep the one that interprets "
                         "this data.")
    engine = None if interpreter or interpret is not None else engine_dir(policy, engines_dir)
    if not interpreter and interpret is None and engine is None:
        interpret = default_interpret(policy)
    if policy.get("interpretation_scope", "full_well") != "full_well":
        raise ValueError(f"WHAT: the policy's interpretation_scope is {policy['interpretation_scope']!r}. WHY: every "
                         "route interprets the whole well. FIX: leave interpretation_scope out (or write full_well).")
    scope = "full_well"

    if cache_dir is not None:
        path = _cache_path(cache_dir, policy, las_path, scope, engine, interpreter, interpret)
        if path.exists() and _owned(path):
            with path.open("rb") as fh:
                return pickle.load(fh)

    raw = _read(las_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        well = standardize_curves(raw, rename_curves=True, convert_units=True)
    header = {}
    for key, value in (getattr(well, "_parameters", {}) or {}).items():
        try:
            json.dumps(value)
            header[str(key)] = value
        except TypeError:
            header[str(key)] = str(value)

    if interpreter:
        # The interpreter is the data's workflow of record: its well is final (its own value-range QC included).
        interpreted, input_curves, steps, result = _interpret_with_interpreter(Path(las_path), interpreter)
        _check_cutoffs(result, policy.get("cutoffs", {}))
        qc = {}
        prepared = PreparedWell(name=Path(las_path).stem, policy=policy["name"], scope=scope, well=interpreted,
                                input_curves=sorted(input_curves),
                                derived_curves=sorted(set(interpreted.curves) - set(input_curves)),
                                steps=steps, header_parameters=header, policy_adjustments={"interpreter": interpreter},
                                value_qc=qc)
        if cache_dir is not None:
            _write_cache(path, prepared)
        return prepared

    if interpret is not None:
        # petrophys.interpret's well is final (its own value-range QC included); the LAS's curves are its inputs
        interpreted, steps, qc, workflow_well = _interpret_with_petrophys(Path(las_path), interpret)
        _check_engine_cutoffs(steps, policy.get("cutoffs", {}))           # the recorded cutoffs, as data.interpreter
        input_curves = set(well.curves) & set(interpreted.curves)
        prepared = PreparedWell(name=Path(las_path).stem, policy=policy["name"], scope=scope, well=interpreted,
                                input_curves=sorted(input_curves),
                                derived_curves=sorted(set(interpreted.curves) - input_curves),
                                steps=steps, header_parameters=header, policy_adjustments={"interpret": interpret},
                                value_qc=qc, workflow_well=workflow_well)
        if cache_dir is not None:
            _write_cache(path, prepared)
        return prepared

    # a pinned engine: the policy's workflow of record
    interpreted, input_curves, steps, _, identity, qc = _interpret_with_engine(
        Path(las_path), engine, bool(policy.get("value_range_qc", False)))
    _check_engine_cutoffs(steps, policy.get("cutoffs", {}), interpreted)
    raw_depth = np.asarray(well.depth, dtype=float)
    if raw_depth.shape == interpreted.depth.shape and np.allclose(raw_depth, interpreted.depth, equal_nan=True):
        added = sorted(set(well.curves) - set(interpreted.curves))     # LAS curves the engine's reader dropped
        for name in added:
            c = well.get(name)
            interpreted.add_curve(name, np.asarray(c.data, dtype=float), str(getattr(c, "unit", "") or ""), name)
            input_curves.add(name)
        if added and policy.get("value_range_qc", False):              # same QC as the engine's own curves
            extra = _apply_value_qc(_Subset(interpreted, added))
            for key in ("rules", "changed"):
                qc.setdefault(key, {}).update(extra.get(key, {}))
    if policy.get("value_range_qc", False):
        _sync_after_qc(interpreted)
    prepared = PreparedWell(name=Path(las_path).stem, policy=policy["name"], scope=scope, well=interpreted,
                            input_curves=sorted(input_curves),
                            derived_curves=sorted(set(interpreted.curves) - set(input_curves)),
                            steps=steps, header_parameters=header, policy_adjustments={"engine": identity},
                            value_qc=qc)
    if cache_dir is not None:
        _write_cache(path, prepared)
    return prepared


def _write_cache(path: Path, prepared: PreparedWell) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, pickle.dumps(prepared))         # readers never see a partial file
