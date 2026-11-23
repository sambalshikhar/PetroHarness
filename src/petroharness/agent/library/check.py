"""The check verb: data-quality questions the record answers only in part (docs/TOOLS.md). Petrophys checks held
(stuck or padded) readings, the parts of bad hole (washout, large hole, caliper
rugosity, low density, PEF out of range) and the shift that ties core plugs to a log. Spikes, jumps, thresholds, gaps
and log-to-log depth matching are the existing lookups (spike_flags, adjacent_jumps, threshold_exceedance,
data_record, lag_correlation). Each flag is written as a curve of the question (HELD_<CURVE>, WASHOUT, ...), read by
runs, stats and conditions.
"""
from __future__ import annotations

import warnings

import numpy as np

from petroharness.agent import engine as E
from petroharness.agent.engine import Formation, Out, Result, ToolError
from petroharness.agent.library import register, scratch_well
from petroharness.record.catalog import flag_runs

OBJECTS = {
    "held_readings": "stuck or padded readings (one value repeated over 10 or more samples) per measured log, by depth "
                     "run and zone; curves: the logs (default every measured log); threshold: the repeat tolerance in "
                     "each log's unit (0)",
    "bad_hole": "the parts of bad hole by depth run and zone: washout (CALI - BS), large hole, caliper rugosity, low "
                "density, PEF out of range; needs CALI (and BS for washout); threshold: the washout limit CALI - BS, in "
                "inches (1.5)",
    "depth_shift": "the shift that ties core plugs (PHIC, KH_CORE, SWC or the like in the LAS) to a log: the best shift, "
                   "the correlation before and after, each core run on its own; curves: [the log] (default PHIE for "
                   "porosity, PERM for permeability, SW); threshold: the largest shift to scan, in depth units",
}
MAX_RUNS = 8


def check(f: Formation, what: str, curves=None, zones=None, threshold: float | None = None) -> Result:
    w = str(what or "").strip().lower()
    if w not in OBJECTS:
        raise ToolError(f"no check {what!r}; checks: " + "; ".join(f"{k}: {v}" for k, v in OBJECTS.items()))
    if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, (int, float))):
        raise ToolError(f"threshold must be a number, not {threshold!r}")
    return {"held_readings": held_readings, "bad_hole": bad_hole, "depth_shift": depth_shift}[w](
        f, curves, zones, threshold)


# --- shared ---------------------------------------------------------------------------------------------------------

def _well(f: Formation):
    """A copy of the prepared well (library.scratch_well): a check never changes the record."""
    return scratch_well(f)


def _las_depth(f: Formation) -> np.ndarray:
    """The interval's samples in the LAS depth unit (what Petrophys reads)."""
    return np.asarray(f.view.prep.depth, dtype=float)[f.view.mask]


def _on_interval(f: Formation, depth, flag) -> np.ndarray:
    """A flag Petrophys gave over `depth` (the well's samples or a window of them) as a flag over the interval."""
    full = np.asarray(f.view.prep.depth, dtype=float)
    depth, flag = np.asarray(depth, dtype=float), np.asarray(flag, dtype=float)
    out = np.zeros(full.size)
    if depth.size == full.size:
        out = np.nan_to_num(flag)
    else:
        pos = np.clip(np.searchsorted(full, depth), 0, full.size - 1)
        hit = np.isclose(full[pos], depth)
        out[pos[hit]] = np.nan_to_num(flag[hit])
    return (out > 0.5).astype(float)[f.view.mask]


def _write(f: Formation, name: str, flag: np.ndarray, meaning: str, step: str) -> str:
    full = np.full(np.asarray(f.view.prep.depth).size, np.nan)
    full[f.view.mask] = flag
    return register(f, name, full, meaning, "flag", step)


def _runs_text(out: Out, f: Formation, flag: np.ndarray) -> str:
    """The flag's depth runs, thickest first (MAX_RUNS of them), and their total thickness."""
    d = np.asarray(f.depth, dtype=float)
    step = float(np.median(np.diff(d))) if d.size > 1 else 0.0
    runs = [(d[a], d[b], d[b] - d[a] + step) for a, b in flag_runs(d, flag)]
    if not runs:
        return "no runs"
    shown = sorted(runs, key=lambda r: -r[2])[:MAX_RUNS]
    more = f"; {out.i(len(runs) - len(shown))} more" if len(runs) > len(shown) else ""
    return (f"{out.i(len(runs))} run{'s' if len(runs) != 1 else ''}, {out.v(sum(r[2] for r in runs))} {f.inv.depth_unit} in all: "
            + ", ".join(out.span(a, b) for a, b, _ in sorted(shown)) + more)


def _zone_shares(out: Out, f: Formation, flag: np.ndarray, zones=None) -> str:
    parts = []
    for z in E.zones(f, zones):
        idx = np.asarray(z.indices)
        if idx.size and flag[idx].any():
            parts.append(f"{z.zone_id} {out.pct(100.0 * float(flag[idx].mean()))}")
    return "; ".join(parts) or "no zone"


# --- held readings --------------------------------------------------------------------------------------------------

def held_readings(f: Formation, curves, zones, threshold) -> Result:
    from petrophys.preprocessing.quality.held_readings import find_held_readings
    well = _well(f)
    if curves:
        asked = E.curves(f, curves)
    else:
        asked = [c for c, cv in f.inv.curves.items() if cv.measured_log and cv.source == "input" and not cv.flat]
    names = set(getattr(well, "curves", {}) or {})
    cs = [c for c in asked if c in names]
    if not cs:
        raise ToolError("no measured log of this well to check" + (f" among {', '.join(asked)}" if asked else ""))
    d = _las_depth(f)
    tol = float(threshold) if threshold is not None else 0.0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            held = find_held_readings(well, cs, tolerance=tol, top=float(d.min()), bottom=float(d.max()))
    except ValueError as e:
        raise ToolError(f"Petrophys find_held_readings: {str(e)[:300]}") from None
    out = Out(f)
    out.add(f"Held readings (Petrophys find_held_readings: one value repeated over {out.i(held.min_run)} or more "
            f"samples, repeat tolerance {out.v(tol)} in each log's unit) in {', '.join(cs)}")
    clean = []
    for c in cs:
        flag = _on_interval(f, held.depth, held.masks.get(c, np.zeros(np.asarray(held.depth).size)))
        if not flag.any():
            clean.append(c)
            continue
        name = _write(f, f"HELD_{c}", flag, f"{c} held (stuck or padded) reading, Petrophys find_held_readings", "held readings (on request)")
        vals = np.asarray(f.view.values(c), dtype=float)
        first = [a for a, _ in flag_runs(np.asarray(f.depth, dtype=float), flag)]
        held_at = sorted({round(float(vals[a]), 6) for a in first if np.isfinite(vals[a])})
        row = out.child()
        has = np.isfinite(vals)
        share = 100.0 * float(flag[has].mean()) if has.any() else 0.0
        out.add(f"  {c}: {row.pct(share)} of its samples here held; {_runs_text(row, f, flag)}; held at "
                + ", ".join(row.v(v) for v in held_at[:6]) + (" ..." if len(held_at) > 6 else "")
                + f"; by zone: {_zone_shares(row, f, flag, zones)}; written: {name}", row)
    if clean:
        out.add(f"  none held: {', '.join(clean)}")
    return out.result()


# --- bad hole -------------------------------------------------------------------------------------------------------

PARTS = (("washout_flag", "WASHOUT", "washout: CALI - BS above the limit"),
         ("large_hole_flag", "LARGE_HOLE", "large hole: CALI above the large-hole limit"),
         ("low_density_flag", "LOW_DENSITY", "low density: RHOB below the valid minimum"),
         ("pef_exclusion_flag", "PEF_EXCLUDED", "PEF out of its valid range"))


def bad_hole(f: Formation, curves, zones, threshold) -> Result:
    from petrophys.preprocessing.quality.bad_hole.washout_detection import (
        WashoutDetection,
    )
    from petrophys.preprocessing.quality.wellbore import WellboreQC
    well = _well(f)
    names = set(getattr(well, "curves", {}) or {})
    if "CALI" not in names:
        raise ToolError("bad_hole needs a caliper (CALI); this well has none (the record's BAD_HOLE, where present, "
                        "rests on DRHO alone)")
    lim = float(threshold) if threshold is not None else 1.5
    detector, wqc = WashoutDetection(cali_threshold=lim), WellboreQC(washout_threshold=lim)
    rug = float(wqc.cali_variation_threshold)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = detector.detect(well)
            qc = wqc.analyze(well, add_curves=False)
    except Exception as e:  # noqa: BLE001  (a library failure is the model's to read, not a crash)
        raise ToolError(f"Petrophys bad-hole detection: {type(e).__name__}: {str(e)[:300]}") from None
    depth = np.asarray(f.view.prep.depth, dtype=float)
    out = Out(f)
    head = out.child()
    out.add(f"Bad hole by its parts (Petrophys WashoutDetection: washout CALI - BS > {head.v(lim)} in, large hole CALI "
            f"> {head.v(detector.large_hole_threshold)} in, low density RHOB < {head.v(detector.rhob_min)} g/cc, PEF "
            f"outside {head.v(detector.pef_min)}-{head.v(detector.pef_max)}; WellboreQC: caliper rugosity, the "
            f"rolling std of dCALI/dDepth above {head.v(rug)} in/m)"
            + ("" if "BS" in names else "; no bit size (BS) in the well: washout is not evaluated"), head)
    rough = getattr((qc.derived_curves or {}).get("CALI_ROUGHNESS"), "data", None)
    parts = [(attr, name, what, getattr(res, attr, None)) for attr, name, what in PARTS]
    if rough is not None:
        r = np.asarray(rough, dtype=float)
        parts.append(("rugosity", "RUGOSE", "caliper rugosity above the limit",
                      np.where(np.isfinite(r), (r > rug).astype(float), 0.0)))
    for _, name, what, flag_full in parts:
        if flag_full is None:
            continue
        flag = _on_interval(f, depth, flag_full)
        row = out.child()
        if not flag.any():
            out.add(f"  {name}: none here ({what})")
            continue
        written = _write(f, name, flag, f"{what} (Petrophys)", "bad hole parts (on request)")
        out.add(f"  {name}: {row.pct(100.0 * float(flag.mean()))} of the interval ({what}); {_runs_text(row, f, flag)}; "
                f"by zone: {_zone_shares(row, f, flag, zones)}; written: {written}", row)
    if "BAD_HOLE" in f.inv.curves:
        rec = np.asarray(f.view.values("BAD_HOLE"), dtype=float)
        row = out.child()
        ok = np.isfinite(rec)
        if ok.any():
            out.add(f"  the record's BAD_HOLE (all parts together): {row.pct(100.0 * float((rec[ok] > 0.5).mean()))} of "
                    f"the interval", row)
    return out.result()


# --- core depth shift -----------------------------------------------------------------------------------------------

PROPERTY_LOG = (("porosity", "PHIE", False), ("permeability", "PERM", True), ("sw", "SW", False))


def depth_shift(f: Formation, curves, zones, threshold) -> Result:
    from petrophys.interpretation.core_analysis.calibration import core_data_from_well
    from petrophys.interpretation.core_analysis.depth_matching import (
        find_core_depth_shift,
    )
    well = _well(f)
    d = _las_depth(f)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            core = core_data_from_well(well, top=float(d.min()), bottom=float(d.max()))
        except Exception as e:  # noqa: BLE001  (no core curves the library reads)
            raise ToolError(f"no core plugs in this interval's LAS (Petrophys core_data_from_well: {str(e)[:200]})") from None
    have = [(p, log, lg) for p, log, lg in PROPERTY_LOG if getattr(core, p, None) is not None
            and np.isfinite(np.asarray(getattr(core, p), dtype=float)).sum() > 0]
    if not have:
        raise ToolError("no core plugs in this interval's LAS (core porosity, permeability or saturation curves such as "
                        "PHIC, KH_CORE, SWC)")
    log = E.curve(f, (curves[0] if isinstance(curves, list) else curves)) if curves else None
    prop, default_log, log_scale = have[0]
    if log is not None:
        for p, dl, lg in have:
            if log.startswith(dl):
                prop, log_scale = p, lg
    log = log or default_log
    scale = float(f.view.depth_scale or 1.0)
    max_shift = float(threshold) / scale if threshold is not None else None
    step = float(np.median(np.diff(d))) if d.size > 1 else 0.0
    gap = f.view.to_unit(3.0) / scale                              # core runs: plugs more than 3 m apart
    caught = []
    with warnings.catch_warnings(record=True) as ws:
        warnings.simplefilter("always")
        try:
            r = find_core_depth_shift(well, core, log, core_property=prop, max_shift=max_shift, log_scale=log_scale,
                                      run_gap=gap)
        except ValueError as e:
            raise ToolError(f"Petrophys find_core_depth_shift: {str(e)[:300]}") from None
        caught = [w.message for w in ws if isinstance(w.message, UserWarning)]   # whole, with the inputs it asks for
    out = Out(f)
    row = out.child()
    u = f.inv.depth_unit
    n_plugs = int(np.isfinite(np.asarray(getattr(core, prop), dtype=float)).sum())
    out.add(f"Core-to-log depth shift (Petrophys find_core_depth_shift: core {prop} from the LAS, {row.i(n_plugs)} plugs "
            f"here, against {log}{' on log10' if log_scale else ''}; the log interpolated at each shifted plug depth, "
            f"Pearson r; only a positive r ties): best shift {row.v(r.shift * scale)} {u} (positive: the plugs move "
            f"deeper, log depth = core depth + shift), r {row.v(r.correlation)} against {row.v(r.correlation_unshifted)} "
            f"unshifted (n {row.i(r.n_points)}; scan step {row.v(step * scale)} {u})", row)
    runs = getattr(r, "runs", None)
    if runs is not None and len(runs):
        for _, rr in runs.iterrows():
            rw = out.child()
            where = f"  core run {rw.span(float(rr['top']) * scale, float(rr['bottom']) * scale)}: {rw.i(int(rr['plugs']))} plugs"
            if np.isfinite(float(rr["shift"])) and np.isfinite(float(rr["correlation"])):
                out.add(f"{where}, shift {rw.v(float(rr['shift']) * scale)} {u}, r {rw.v(float(rr['correlation']))}", rw)
            else:
                out.add(f"{where}, not scanned on its own (too few plugs with the log)", rw)
    if any(E.calibrated_twin(f, c) == log for c in f.inv.curves if c != log):
        out.add(f"  {log} is calibrated to core: a tie against the same core is not independent; match the log it was "
                f"calibrated from (Petrophys find_core_depth_shift's own caution)")
    for msg in E.said_whole(caught):
        out.add(f"  Petrophys notes: {msg}")
    return out.result()
