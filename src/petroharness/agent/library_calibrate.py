"""calibrate (docs/TOOLS_DESIGN.md): the log against core, and the rock-physics relations, by Petrophys.

porosity, permeability and saturation give Petrophys's calibration fit of a log curve to the core plugs the LAS
carries (R2, bias, RMSE and the regression line, zones pooled and each zone with plugs); core_vs_log gives the core
and log statistics side by side. poro_perm fits Petrophys's porosity-permeability transform, on core where the plugs
allow, else on the log. shear predicts a shear slowness from the compressional one (Greenberg-Castagna), and elastic
gives the dynamic elastic properties.
"""
from __future__ import annotations

import warnings

import numpy as np

from petroharness.agent import engine as E
from petroharness.agent.engine import Formation, Out, Result, ToolError
from petroharness.agent.library import _curve, _full, _method, _zone_mask, register, scratch_well
from petroharness.well import summary as S

OBJECTS = {
    "porosity": "the fit of a log porosity (PHIE, or the curve named) to core porosity (PHIC, CPOR): R2, bias, RMSE "
                "and the line, zones pooled and each zone with plugs; core_vs_log gives the statistics side by side",
    "permeability": "the fit of log permeability (PERM, or the curve named) to core permeability (KH_CORE, CPERM) in "
                    "log10: R2, bias, RMSE and the line; core_vs_log gives the statistics side by side",
    "saturation": "the fit of log water saturation (SW, or the curve named) to core SW (SWC, CSW): R2, bias, RMSE and "
                  "the line; core_vs_log gives the statistics side by side",
    "poro_perm": "a transform log10(K) = A * porosity + B fitted on core plugs (core porosity and permeability), else "
                 "on the log (PHIE and PERM), saying which; writes PERM_PP",
    "shear": "a shear slowness predicted from DTC by Greenberg-Castagna for the record's matrix (writes DTS_GC), "
             "against a measured DTS where there is one",
    "elastic": "dynamic elastic properties from RHOB, DTC and DTS (measured, else a DTS_GC this question predicted): "
               "Vp, Vs, Vp/Vs, acoustic impedance, Poisson's ratio, shear, bulk and Young's moduli, per zone",
}
# what -> (the log curve by default, Petrophys's calibration function, the core measurement it needs)
CORE_FITS = {"porosity": ("PHIE", "calibrate_porosity", "porosity"),
             "permeability": ("PERM", "calibrate_permeability", "permeability"),
             "saturation": ("SW", "calibrate_saturation", "sw")}
CORE_CURVES = {"porosity": "PHIC or CPOR", "permeability": "KH_CORE or CPERM", "sw": "SWC or CSW"}


def calibrate(f: Formation, what: str, curves=None, zones=None) -> Result:
    w = str(what or "").strip().lower()
    if w not in OBJECTS:
        raise ToolError(f"no calibration of {what!r}; calibrate: " + "; ".join(f"{k}: {v}" for k, v in OBJECTS.items()))
    keep = _zone_mask(f, zones)
    if w in CORE_FITS:
        return _core_fit(f, w, _one(curves), keep)
    if w == "poro_perm":
        return _poro_perm(f, keep)
    if w == "shear":
        return _shear(f, keep)
    return _elastic(f, keep)


def _one(curves) -> str | None:
    if not curves:
        return None
    names = [curves] if isinstance(curves, str) else list(curves)
    if len(names) != 1:
        raise ToolError(f"calibrate takes one log curve, not {len(names)}")
    return str(names[0]).strip().upper()


def _depths(f: Formation, idx: np.ndarray) -> tuple:
    """The (top, bottom) of these interval samples in the well's own depth unit, as Petrophys reads core depths."""
    d = np.asarray(f.view.prep.depth, dtype=float)[f.view.mask][idx]
    return float(d.min()), float(d.max())


def _core(f: Formation, idx: np.ndarray):
    from petrophys.interpretation.core_analysis.calibration import core_data_from_well
    top, bottom = _depths(f, idx)
    try:
        with warnings.catch_warnings():                  # unit conversions are in the core's metadata, and said
            warnings.simplefilter("ignore")
            return core_data_from_well(scratch_well(f), top=top, bottom=bottom)
    except ValueError:                                   # no core curve with data in these depths
        return None


def _well_with(f: Formation, c: str):
    """The prepared well, with a curve this question calculated added to a copy (the record's curves are on it)."""
    w2 = scratch_well(f)
    if w2.get(c) is not None:
        return w2
    if c not in f.view.calculated:
        raise ToolError(f"{c!r} is not a curve of this well or of this question")
    unit = f.inv.curves[c].unit if c in f.inv.curves else ""
    w2.add_curve(c, np.asarray(f.view.calculated[c], dtype=float), unit, f"{c} (calculated in this question)")
    return w2


def _scopes(f: Formation, keep: np.ndarray, i=str) -> list:
    """(label, interval sample indices) of the bases every tool reports by, the whole selection first
    (engine.scopes)."""
    return E.scopes(f, keep, i)


def _core_fit(f: Formation, w: str, curve: str | None, keep: np.ndarray) -> Result:
    from petrophys.interpretation.core_analysis import calibration as C
    log_curve, fn_name, needs = CORE_FITS[w]
    log_curve = curve or log_curve
    well = _well_with(f, log_curve)
    fn = getattr(C, fn_name)
    out = Out(f)
    rows, used_core, norm = [], None, None
    for label, idx in _scopes(f, keep):
        core = _core(f, idx)
        if core is None or getattr(core, needs) is None or not np.isfinite(np.asarray(getattr(core, needs), float)).any():
            continue
        try:
            res = fn(well, core, log_curve)
        except ValueError as e:                          # the library's own reason, said back once
            raise ToolError(f"Petrophys {fn_name}: {str(e)[:300]}") from None
        if res.n_points < 3 or not np.isfinite(res.r_squared):
            continue
        used_core = used_core or core.metadata.get(f"core_{needs}_curve")
        norm = norm or core.metadata.get(f"core_{needs}_normalization")
        row = out.child()
        rows.append(((f"  {label}: n {row.i(res.n_points)} plugs, R2 {row.v(res.r_squared)}, bias "
                      f"{row.v(res.bias)} (log - core), RMSE {row.v(res.rmse)}; line: log = {row.v(res.slope)} * core "
                      f"+ {row.v(res.intercept)}"), row))
    if not rows:
        raise ToolError(f"no {CORE_CURVES[needs]} core plugs with {log_curve} values in these zones (at least 3 "
                        f"needed): the {w} fit needs core {needs if needs != 'sw' else 'water saturation'} in the LAS")
    space = " in log10" if w == "permeability" else ""
    out.add(f"{log_curve} against core {used_core or needs}{space} (Petrophys {fn_name}: R2 of the core-log "
            f"correlation, bias = mean(log - core), RMSE, and the fitted line log = slope * core + intercept; a "
            f"slope near 1 with a small bias is a calibrated log). core_vs_log gives the values side by side.")
    for ln, r in rows:
        out.add(ln, r)
    said = [str(m) for m in (norm.get("warnings") or [])] if isinstance(norm, dict) else []
    if said:
        out.add("  Petrophys converted the core values: " + "; ".join(said)[:400])
    return out.result()


def _poro_perm(f: Formation, keep: np.ndarray) -> Result:
    from petrophys.interpretation.core_analysis.calibration import (
        fit_poro_perm_transform,
    )
    from petrophys.model.core import CoreData
    idx = np.flatnonzero(keep)
    core = _core(f, idx)
    basis = "core plugs"
    if core is None or core.porosity is None or core.permeability is None:
        _, phi = _curve(f, "PHIE")
        _, perm = _curve(f, "PERM")
        depth = np.asarray(f.view.prep.depth, dtype=float)[f.view.mask]
        core = CoreData(depth=depth[idx], porosity=phi[idx], permeability=perm[idx])
        basis = "the log (PHIE and PERM: no core porosity and permeability here)"
    try:
        t = fit_poro_perm_transform(core)
    except ValueError as e:
        raise ToolError(f"Petrophys fit_poro_perm_transform: {str(e)[:300]}") from None
    _, phie = _curve(f, "PHIE")
    perm_pp = np.asarray(t.predict(phie), dtype=float)
    register(f, "PERM_PP", _full(f, perm_pp), f"permeability from the poro-perm transform fitted on {basis.split(' (')[0]}",
             "mD", "poro-perm transform (on request)")
    out = Out(f)
    row = out.child()
    out.add(f"poro-perm transform fitted on {basis} (Petrophys fit_poro_perm_transform): log10(K) = A * porosity + B "
            f"with A {row.v(t.A)}, B {row.v(t.B)}; R2 {row.v(t.r_squared)}, RMSE {row.v(t.rmse)} (log10 mD), n "
            f"{row.i(t.n_points)}. Written: PERM_PP (the transform applied to PHIE).", row)
    if basis.startswith("core") and "PERM" in f.inv.curves:
        perm = np.asarray(f.view.values("PERM"), dtype=float)
        ok = keep & np.isfinite(perm) & (perm > 0) & np.isfinite(perm_pp) & (perm_pp > 0)
        if ok.any():
            r2 = out.child()
            out.add(f"  against the record's PERM over {r2.i(int(ok.sum()))} samples: geometric means PERM_PP "
                    f"{r2.v(10 ** np.mean(np.log10(perm_pp[ok])))}, PERM {r2.v(10 ** np.mean(np.log10(perm[ok])))} mD",
                    r2)
    return out.result()


def _slowness(f: Formation, name: str) -> tuple:
    """A sonic slowness in us/ft (converted from us/m when the record's unit says so)."""
    n, v = _curve(f, name)
    unit = (f.inv.curves[n].unit or "").lower().replace(" ", "")
    return n, (v * 0.3048 if unit in ("us/m", "usec/m") else v)


def _shear(f: Formation, keep: np.ndarray) -> Result:
    from petrophys.interpretation.saturation.sonic.rock_physics import (
        slowness_to_velocity,
        vs_from_vp_greenberg_castagna,
    )
    dn, dtc = _slowness(f, "DTC")
    from petroharness.agent import library_api as A
    fn = A.lookup("vs_from_vp_greenberg_castagna")
    vp = slowness_to_velocity(dtc)
    lith, said = A._record_lithology(f, fn, "lithology")             # the binder's fill (one rule)
    kw = {"vp_ms": vp} | ({} if lith is A._UNSET else {"lithology": lith})
    vs = (A._by_lithology(fn, vs_from_vp_greenberg_castagna, kw)[0] if isinstance(lith, A._ByLithology)
          else vs_from_vp_greenberg_castagna(**kw))
    vs = np.asarray(vs, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        dts_gc = np.where(vs > 0, 304800.0 / vs, np.nan)
    register(f, "DTS_GC", _full(f, dts_gc), f"shear slowness predicted from {dn} (Greenberg-Castagna; lithology {said})",
             "us/ft", "shear prediction (on request)")
    out = Out(f)
    row = out.child()
    out.add(f"shear slowness predicted from {dn} by Petrophys vs_from_vp_greenberg_castagna, lithology {said} "
            f"(brine-saturated rock assumed). Written: DTS_GC (us/ft); median, us/ft: "
            f"{E.over_bases(f, np.where(keep, dts_gc, np.nan), row)}.", row)
    if "DTS" in f.inv.curves and f.view.available("DTS"):
        _, dts = _slowness(f, "DTS")
        parts, r = [], out.child()
        for label, idx in _scopes(f, keep):
            ok = idx[np.isfinite(dts[idx]) & np.isfinite(dts_gc[idx])]
            if ok.size:
                d = dts_gc[ok] - dts[ok]
                parts.append(f"{label}: n {r.i(ok.size)}, mean DTS_GC {r.v(np.mean(dts_gc[ok]))} vs DTS "
                             f"{r.v(np.mean(dts[ok]))}, mean difference {r.v(np.mean(d))} us/ft")
        out.add("  against the measured DTS: " + ("; ".join(parts) or "no samples with both"), r)
    else:
        out.add("  no measured DTS here to set it against")
    return out.result()


def _elastic(f: Formation, keep: np.ndarray) -> Result:
    from petrophys.interpretation.rock_physics.elastic import (
        calculate_elastic_properties,
    )
    _, rhob = _curve(f, "RHOB")
    dn, dtc = _slowness(f, "DTC")
    if "DTS" in f.inv.curves and f.view.available("DTS"):
        _, dts = _slowness(f, "DTS")
        shear = "the measured DTS"
    elif "DTS_GC" in f.view.calculated:
        dts = np.asarray(f.view.values("DTS_GC"), dtype=float)
        shear = "DTS_GC (predicted in this question)"
    else:
        dts, shear = None, ""
    p = calculate_elastic_properties(rhob, dtc, dts)
    fields = [("VP", "vp_m_s", "m/s", "compressional velocity"), ("AI", "acoustic_impedance_mrayl", "MRayl",
              "acoustic impedance")]
    if dts is not None:
        fields += [("VS", "vs_m_s", "m/s", "shear velocity"), ("POISSON", "poisson_ratio", "", "Poisson's ratio"),
                   ("SHEAR_MOD", "shear_mod_gpa", "GPa", "shear modulus"), ("BULK_MOD", "bulk_mod_gpa", "GPa",
                   "bulk modulus"), ("YOUNG_MOD", "young_mod_gpa", "GPa", "Young's modulus")]
    out = Out(f)
    out.add(f"dynamic elastic properties by Petrophys calculate_elastic_properties from RHOB, {dn}"
            + (f" and {shear}" if dts is not None else " (no shear slowness: Vs, Poisson's ratio and the moduli need "
               "DTS; calibrate shear predicts one)") + "; medians over the whole selection, the zones pooled and each zone:")
    written = []
    for base, attr, unit, meaning in fields:
        x = np.asarray(getattr(p, attr), dtype=float)
        name = base if base not in f.inv.curves or base in f.view.calculated else f"{base}_EL"
        register(f, name, _full(f, x), f"{meaning} (Petrophys calculate_elastic_properties)", unit,
                 "elastic properties (on request)")
        written.append(name)
        row = out.child()
        zs = "; ".join(f"{lab} {row.v(np.nanmedian(x[idx]))}" for lab, idx in _scopes(f, keep)
                       if np.isfinite(x[idx]).any())
        out.add(f"  {name} ({unit or 'ratio'}): {zs}", row)
    if dts is not None:
        vp, vs = np.asarray(p.vp_m_s, dtype=float), np.asarray(p.vs_m_s, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(vs > 0, vp / vs, np.nan)
        row = out.child()
        zs = "; ".join(f"{lab} {row.v(np.nanmedian(ratio[idx]))}" for lab, idx in _scopes(f, keep)
                       if np.isfinite(ratio[idx]).any())
        out.add(f"  Vp/Vs: {zs}", row)
    out.add(f"  written: {', '.join(written)} (curves of this question)")
    return out.result()
