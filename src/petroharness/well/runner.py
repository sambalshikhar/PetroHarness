"""Run a pinned Petrophys engine on one raw LAS and write its curves and step record (a subprocess of prepare)."""

from __future__ import annotations

import copy
import json
import sys
import warnings
from pathlib import Path


def _jsonable(value):
    """Step parameters can hold numpy scalars and arrays; keep scalars, summarize arrays."""
    import numpy as np

    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return {"array_size": int(value.size)}
    if isinstance(value, np.generic):
        return value.item()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def bad_hole_thresholds(generate_bad_hole_flags) -> dict:
    """The thresholds the library's bad-hole step used: it calls generate_bad_hole_flags with its defaults and does
    not record them, so read them from the signature (BAD_HOLE = CALI-BS above the caliper threshold or |DRHO| above
    the density threshold, or bit size above the large-hole threshold)."""
    import inspect

    p = inspect.signature(generate_bad_hole_flags).parameters
    pick = {"cali_threshold": "cali_minus_bs_threshold_in", "drho_threshold": "drho_threshold_g_cc",
            "large_hole_threshold": "large_hole_threshold_in"}
    out = {new: p[old].default for old, new in pick.items() if old in p and p[old].default is not inspect._empty}
    return out | {"thresholds_source": "library defaults"} if out else {}


def _import_first(*candidates):
    import importlib

    for module, name in candidates:
        try:
            return getattr(importlib.import_module(module), name)
        except (ImportError, AttributeError):
            continue
    raise ImportError(f"none of {candidates} is available in this engine")


def main(argv: list[str]) -> int:
    engine_dir, las_path, out_prefix = (Path(a) for a in argv[:3])
    options = json.loads(argv[3]) if len(argv) > 3 else {}
    root = engine_dir / "src" if (engine_dir / "src" / "petrophys").is_dir() else engine_dir
    sys.path.insert(0, str(root))
    import numpy as np
    import petrophys

    if not Path(petrophys.__file__).resolve().is_relative_to(root.resolve()):
        raise SystemExit(f"engine not loaded: petrophys came from {petrophys.__file__}, expected {root}")

    read_las = _import_first(("petrophys.io.las_reader", "read_las"), ("petrophys.io", "read_las"))
    standardize = _import_first(("petrophys.qaqc.standardization", "standardize_curves"),
                                ("petrophys.preprocessing.standardization", "standardize_curves"))
    from petrophys.workflow.zoned_batch import _finalize_export_curves, run_dynamic_workflow_with_zones

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        well = standardize(read_las(las_path), rename_curves=True, convert_units=True)
        input_curves = sorted(well.curves)
        header = {str(k): _jsonable(v) for k, v in (getattr(well, "_parameters", {}) or {}).items()}
        result = run_dynamic_workflow_with_zones(copy.deepcopy(well))
        _finalize_export_curves(result.well, set(input_curves))
        qc_report, qc_changed = [], {}
        if options.get("value_range_qc", True):
            apply_qc = _import_first(("petrophys.qaqc.value_range_qc", "apply_value_range_qc"),
                                     ("petrophys.preprocessing.quality.value_ranges", "apply_value_range_qc"))
            before = {n: np.asarray(result.well.get(n).data, dtype=float).copy() for n in result.well.curves}
            qc_report = apply_qc(result.well) or []
            for n, old in before.items():                 # which samples the rules changed (NaN-ed or clipped)
                new = np.asarray(result.well.get(n).data, dtype=float)
                changed = ~((old == new) | (np.isnan(old) & np.isnan(new)))
                if changed.any():
                    qc_changed[n] = changed

    w = result.well
    arrays = {"__depth__": np.asarray(w.depth, dtype=float)}
    arrays.update({f"__qc__{n}": m for n, m in qc_changed.items()})
    units = {}
    for name in w.curves:
        curve = w.get(name)
        arrays[name] = np.asarray(curve.data, dtype=float)
        units[name] = str(getattr(curve, "unit", "") or "")
    steps = {}
    for step in result.base_result.steps_executed:
        d = step.to_dict()
        steps[step.step] = {k: _jsonable(d.get(k)) for k in ("method", "parameters", "decisions")}
    if "bad_hole" in steps:
        flags = _import_first(("petrophys.qaqc.bad_hole.flag_generator", "generate_bad_hole_flags"),
                              ("petrophys.preprocessing.quality.bad_hole.flag_generator", "generate_bad_hole_flags"))
        params = steps["bad_hole"].get("parameters") or {}
        steps["bad_hole"]["parameters"] = _jsonable(bad_hole_thresholds(flags)) | params
    engine_meta = engine_dir / "ENGINE.json"
    meta = {"well": str(getattr(w, "name", "") or Path(las_path).stem), "depth_unit": str(getattr(w, "depth_unit", "") or ""),
            "units": units, "input_curves": input_curves, "header": header, "steps": steps,
            "warnings": [str(x) for x in result.base_result.warnings][:50],
            "engine": json.loads(engine_meta.read_text()) if engine_meta.exists() else {"dir": str(engine_dir)},
            "value_range_qc": bool(options.get("value_range_qc", True)),
            "value_range_qc_report": _jsonable(qc_report)}
    np.savez_compressed(f"{out_prefix}.npz", **arrays)
    Path(f"{out_prefix}.json").write_text(json.dumps(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
