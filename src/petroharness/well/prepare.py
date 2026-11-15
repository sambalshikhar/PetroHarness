"""Well preparation: read the raw LAS and interpret it with Petrophys under the policy (a context profile, the
installed library with the policy's corrections, or a pinned engine); the prepared well is cached by content."""

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



# ---------------------------------------------------------------------------
# Policy-driven interpretation
# ---------------------------------------------------------------------------

import copy
import dataclasses
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

from petroharness.well.formation import Interval, find_lithology_curve


def load_policy(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


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


def _rwa_p5_fix(w, rule: dict, lith_curve: Optional[str]) -> dict:
    """Workflow-of-record apparent-Rw rule, referenced to the clean-wet median temperature."""
    from petrophys.workflow.dynamic_workflow import GROUND_TRUTH_CODE_TO_GROUP, _group_array_from_numeric_codes

    temp = np.asarray(w.get("TEMP").data, float)
    rdep = np.asarray(w.get("RDEP").data, float)
    phi_curve = w.get("PHIE_CC") if w.get("PHIE_CC") is not None else w.get("PHIE")
    phie = np.asarray(phi_curve.data, float)
    vcl = np.asarray(w.get("VCL").data, float)
    a = np.full_like(rdep, rule["a_other"])
    litho = w.get(lith_curve) if lith_curve else None
    if litho is not None:
        groups = _group_array_from_numeric_codes(np.asarray(litho.data, float), GROUND_TRUTH_CODE_TO_GROUP)
        a = np.where(np.char.upper(np.asarray(groups, dtype=str)) == "SANDSTONE", rule["a_sandstone"], rule["a_other"])
    with np.errstate(all="ignore"):
        rwa = rdep * phie ** rule["m"] / a
    ok = (np.isfinite(rdep) & np.isfinite(phie) & np.isfinite(vcl) & (vcl < rule["vcl_max"])
          & (phie > rule["phie_min"]) & np.isfinite(rwa) & (rwa > 0))
    if not ok.any():
        return {}
    tref = float(np.nanmedian(temp[ok]))
    rwa_ref = rwa[ok] * (temp[ok] + 6.77) / (tref + 6.77)  # Arps, to the reference temperature
    return {"rw": float(np.percentile(rwa_ref, rule["percentile"])), "rw_meas_temp_f": tref}


def _interpret(well, policy: dict, lithology_curve=None):
    from petrophys.reporting.reference_export import _context_workflow_config
    from petrophys.workflow.zoned_batch import _finalize_export_curves, run_dynamic_workflow_with_zones

    input_curves = set(well.curves)
    cfg = _context_workflow_config(well=well)
    if policy.get("gr_endpoints") == "auto":
        cfg = dataclasses.replace(cfg, gr_min=None, gr_max=None)
    cut = policy.get("cutoffs", {})
    explicit = {k: cut[p] for k, p in (("vcl_cutoff", "vcl_max"), ("sw_cutoff", "sw_max")) if cut.get(p) is not None}
    cfg = dataclasses.replace(cfg, **explicit)          # the policy's cutoffs, not the library's defaults

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        first = run_dynamic_workflow_with_zones(copy.deepcopy(well), cfg)
    steps = {s.step: s for s in first.base_result.steps_executed}
    rw_method = steps["rw"].method if "rw" in steps else None

    adjust: dict[str, Any] = {}
    rw_rule = policy.get("rw", {})
    if rw_method in ("user_provided_assumed_reference_temperature", "las_metadata_assumed_reference_temperature") \
            and rw_rule.get("header_rw_without_rwt") == "median_formation_temperature":
        adjust = {"rw_meas_temp_f": float(np.nanmedian(np.asarray(first.well.get("TEMP").data, float)))}
    elif rw_method and rw_method.startswith("rwa_clean_wet") and rw_rule.get("rwa_fallback"):
        lith = find_lithology_curve(lambda n: None if first.well.get(n) is None else first.well.get(n).data,
                                    sorted(input_curves), lambda n: str(getattr(well.get(n), "description", "") or ""),
                                    lithology_curve)
        adjust = _rwa_p5_fix(first.well, rw_rule["rwa_fallback"], lith)

    # The library picks the PHIE cutoff per lithology domain; the policy sets one per domain.
    np_params = (steps["net_pay"].to_dict().get("parameters") or {}) if "net_pay" in steps else {}
    domain = np_params.get("lithology_domain", "clastic")
    phie_policy = cut.get("phie_min_carbonate" if domain == "carbonate" else "phie_min_clastic")
    if phie_policy is not None and isinstance(np_params.get("phie_cutoff"), (int, float)) \
            and abs(float(np_params["phie_cutoff"]) - float(phie_policy)) > 1e-12:
        adjust["phie_cutoff"] = float(phie_policy)

    result = first
    if adjust:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_dynamic_workflow_with_zones(copy.deepcopy(well), dataclasses.replace(cfg, **adjust))
    _check_cutoffs(result, cut)
    _finalize_export_curves(result.well, input_curves)
    step_dicts = {}
    for s in result.base_result.steps_executed:
        d = s.to_dict()
        step_dicts[s.step] = step_entry(d)
    if "bad_hole" in step_dicts:
        from petrophys.preprocessing.quality.bad_hole.flag_generator import generate_bad_hole_flags

        from petroharness.well.runner import bad_hole_thresholds
        step_dicts["bad_hole"]["parameters"] = bad_hole_thresholds(generate_bad_hole_flags) | (
            step_dicts["bad_hole"].get("parameters") or {})
    return result.well, input_curves, step_dicts, {"first_pass_rw_method": rw_method, **adjust}


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
    """The source tree of the engine the policy names (None: the installed library with the policy's corrections)."""
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
    if json.loads(meta.read_text()).get("name") != name:
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
        meta = json.loads(Path(f"{prefix}.json").read_text())
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


def _interpret_with_petrophys(las_path: Path, options: dict):
    """Interpret one LAS with petrophys.interpret(las, **options) (data.interpret), e.g. with a context profile, which
    interprets a well of a petrophys context package as that package's context does and records every calculation in
    its steps (the profile's preparation, the workflow, the context's QC and recomputation). Returns the interpreted
    well, the step record, the value-range QC it applied and its workflow's own well (None: not kept)."""
    import petrophys

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = petrophys.interpret(las_path, **options)
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
    domain = p.get("lithology_domain", "clastic")
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
    domain = p.get("lithology_domain", "clastic")
    want = {"vcl_cutoff": cut.get("vcl_max"), "sw_cutoff": cut.get("sw_max"),
            "phie_cutoff": cut.get("phie_min_carbonate" if domain == "carbonate" else "phie_min_clastic")}
    bad = {k: (p.get(k), v) for k, v in want.items() if v is not None and _numeric(p.get(k)) and abs(float(p[k]) - float(v)) > 1e-12}
    if bad:
        raise RuntimeError(f"WHAT: the interpretation used cutoffs {bad} (used, policy). WHY: net pay must follow the "
                           "policy. FIX: check the policy's cutoffs and the library's cutoff handling.")


# Bump when the interpretation code changes what it computes, so cached wells are not reused across versions.
INTERPRETATION_VERSION = 13                # 13: data.interpret; each step's stage


def step_entry(d: dict) -> dict:
    """One step of the record: its method, parameters and decisions, and the curves it read, wrote and removed where
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
    return entry
INTERPRETATION_KEYS = ("name", "engine", "interpretation_scope", "gr_endpoints", "rw", "cutoffs", "value_range_qc")


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
                lithology_curve=None, interpreter: Optional[str] = None, interpret: Optional[dict] = None) -> Path:
    # Only interpretation settings and the LAS content key the cache; display/zone/confidence rules do not change
    # curves. The lithology log the user names can (the installed library's Rwa correction reads it). The content is
    # in the key, so a revised LAS under the same name (core curves removed, a bit size added) never reuses a cached
    # well.
    relevant = {k: policy.get(k) for k in INTERPRETATION_KEYS} | {"_version": INTERPRETATION_VERSION,
                                                                  "_library": library_identity()}
    if lithology_curve is not None:
        relevant["_lithology_curve"] = lithology_curve
    if engine is not None:
        relevant["_engine"] = (engine / "ENGINE.json").read_text()      # identity of the pinned engine
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


def prepare_well(
    las_path: Path,
    policy: dict,
    interval: Optional[Interval] = None,
    cache_dir: Optional[Path] = None,
    engines_dir: Optional[Path] = None,
    lithology_curve=None,
    interpreter: Optional[str] = None,
    interpret: Optional[dict] = None,
) -> PreparedWell:
    """Read and standardize the raw LAS, interpret it under the policy, cache the result.

    With interpretation_scope == "formation", `interval` selects the depth slice that is
    interpreted on its own; with "full_well" the whole log is interpreted once. `interpret`
    (data.interpret) has petrophys.interpret interpret the whole LAS with those options, and
    `interpreter` (data.interpreter) the data's own batch interpreter; otherwise, when the policy
    names an engine (its workflow of record, a pinned library under `engines_dir`), that engine
    interprets the raw LAS unchanged, else the installed library runs with the policy's
    corrections.
    """
    from petrophys.preprocessing.standardization import standardize_curves

    if interpreter and interpret is not None:
        raise ValueError("WHAT: both data.interpreter and data.interpret are set. FIX: keep the one that interprets "
                         "this data.")
    engine = None if interpreter or interpret is not None else engine_dir(policy, engines_dir)
    scope_kind = policy.get("interpretation_scope", "full_well")
    if engine is not None and scope_kind != "full_well":
        raise ValueError("WHAT: an engine interprets the whole well. FIX: use interpretation_scope: full_well.")
    if scope_kind == "formation":
        if interval is None:
            raise ValueError("policy interpretation_scope=formation needs an interval")
        scope = f"formation:{interval.formation}"
    else:
        scope = "full_well"

    if cache_dir is not None:
        path = _cache_path(cache_dir, policy, las_path, scope, engine, None if engine is not None else lithology_curve,
                           interpreter, interpret)
        if path.exists():
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

    if engine is not None:
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

    if scope_kind == "formation":
        depth = np.asarray(well.depth, float)
        top = max(interval.top, float(np.nanmin(depth)))
        base = float(np.nanmax(depth)) if interval.base is None else float(np.nextafter(min(interval.base, np.nanmax(depth)), -np.inf))
        well = well.depth_slice(top, base)

    interpreted, input_curves, steps, adjust = _interpret(well, policy, lithology_curve)
    qc = _apply_value_qc(interpreted) if policy.get("value_range_qc", False) else {}
    if policy.get("value_range_qc", False):
        _sync_after_qc(interpreted)
    prepared = PreparedWell(
        name=Path(las_path).stem,
        policy=policy["name"],
        scope=scope,
        well=interpreted,
        input_curves=sorted(input_curves),
        derived_curves=sorted(set(interpreted.curves) - set(input_curves)),
        steps=steps,
        header_parameters=header,
        policy_adjustments=adjust,
        value_qc=qc,
    )
    if cache_dir is not None:
        _write_cache(path, prepared)
    return prepared


def _write_cache(path: Path, prepared: PreparedWell) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    with tmp.open("wb") as fh:
        pickle.dump(prepared, fh)
    os.replace(tmp, path)                              # atomic: readers never see a partial file
