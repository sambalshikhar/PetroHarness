"""The estimate verb: a parameter estimated from this well's logs by Petrophys (Rw, Archie a and m, GR endpoints,
the matrix, temperature)."""

from __future__ import annotations

import warnings
from typing import Optional
import numpy as np
from petroharness.agent.engine import Formation, Out, Result, ToolError, limits, said_whole
from petroharness.agent.library.shared import _curve, _full, _method, _num, _zone_mask, _zone_means, defaults, register


# --- estimate -------------------------------------------------------------------------------------------------------

ESTIMATES = {"rw": ["rwa", "pickett", "sp"], "archie_m": ["pickett"], "clay_point": ["neutron_density"],
             "gr_endpoints": ["percentiles"], "matrix": ["apparent"], "temperature": ["gradient"]}


def estimate(f: Formation, parameter: str, method: Optional[str] = None, zones=None,
             vcl_max: Optional[float] = None, phie_min: Optional[float] = None, rmf: Optional[float] = None,
             rmf_temp_f: Optional[float] = None, bht_f: Optional[float] = None, td: Optional[float] = None) -> Result:
    p = str(parameter or "").strip().lower()
    if p not in ESTIMATES:
        raise ToolError(f"no estimate of {parameter!r}; estimates: " + "; ".join(f"{k} ({', '.join(v)})" for k, v in ESTIMATES.items()))
    meth = str(method or ESTIMATES[p][0]).strip().lower()
    if meth not in ESTIMATES[p]:
        raise ToolError(f"{p} is estimated by {', '.join(ESTIMATES[p])}, not {method!r}")
    keep = _zone_mask(f, zones)
    (a, a_src), (mm, m_src) = _archie_am(f)
    vmax = float(vcl_max) if vcl_max is not None else 0.3
    pmin = float(phie_min) if phie_min is not None else 0.05
    out = Out(f)
    if p == "rw" and meth == "rwa":
        from petrophys.interpretation.electrical.rw.rwa import apparent_water_resistivity
        rn, rt = _curve(f, "RT", "RDEP")
        pn, phi = _curve(f, "PHIE")
        _, vcl = _curve(f, "VCL")
        rwa = np.asarray(apparent_water_resistivity(rt, phi, a=a, m=mm), dtype=float)
        use = keep & np.isfinite(rwa) & (rwa > 0) & np.isfinite(vcl) & (vcl < vmax) & (phi > pmin)
        if use.sum() < 10:
            raise ToolError(f"fewer than 10 clean, porous samples (VCL < {vmax}, {pn} > {pmin}) with {rn} here; "
                            "widen vcl_max or lower phie_min, or estimate over more zones")
        full = np.full(np.asarray(f.view.prep.depth).size, np.nan)
        full[f.view.mask] = rwa
        rwa_name = register(f, "RWA", full, f"apparent water resistivity {rn} * {pn}^m / a (Petrophys)", "ohm.m",
                            "apparent water resistivity (on request)")
        x = rwa[use]
        row = out.child()
        out.add(f"rw by apparent water resistivity (Petrophys apparent_water_resistivity: RWA = {rn} * {pn}^m / a, "
                f"a {row.v(a)} ({a_src}) and m {row.v(mm)} ({m_src})) over {row.i(x.size)} clean, porous samples (VCL < "
                f"{row.v(vmax)}, {pn} > {row.v(pmin)}), at formation temperature: min {row.v(x.min())}, p5 "
                f"{row.v(np.percentile(x, 5))}, p10 {row.v(np.percentile(x, 10))}, median {row.v(np.median(x))} ohm.m. "
                f"In water-bearing clean rock RWA equals Rw; hydrocarbons raise it, so Rw is read from the low end. "
                f"The record's Rw: {_rec_rw(f, row)}. Written: {rwa_name} (a curve of this question).", row)
        return out.result()
    if p in ("rw", "archie_m") and meth == "pickett":
        from petrophys.interpretation.electrical.cementation.pickett_analysis import pickett_analysis
        rn, rt = _curve(f, "RT", "RDEP")
        pn, phi = _curve(f, "PHIE")
        _, vcl = _curve(f, "VCL")
        use = keep & np.isfinite(rt) & np.isfinite(phi) & (phi > 0) & (rt > 0)
        try:
            with warnings.catch_warnings(record=True) as caught:      # Petrophys's own caution on the fit, shown
                warnings.simplefilter("always")
                params, info = pickett_analysis(rt[use], phi[use], sw_water=1.0, vcl_cutoff=vmax, vcl=vcl[use])
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Petrophys pickett_analysis: {type(e).__name__}: {str(e)[:300]}") from None
        said = str((info or {}).get("error") or "").strip()
        if said:      # its a, m and n are then the defaults it started from, not a fit
            raise ToolError(f"Petrophys pickett_analysis could not fit: {said[:200]} ({int(use.sum())} samples with "
                            f"{rn} and {pn}, clean below VCL {vmax}); widen vcl_max, or estimate over more zones")
        row = out.child()
        extra = {k: v for k, v in (info or {}).items() if _num(v)}
        out.add(f"Pickett analysis (Petrophys pickett_analysis on {rn} and {pn}, clean samples VCL < {row.v(vmax)}, "
                f"water line at SW 1): a {row.v(params.a)}, m {row.v(params.m)}, n {row.v(params.n)}"
                + ("; " + ", ".join(f"{k} {row.v(v)}" for k, v in extra.items()) if extra else "")
                + f" (for comparison: a {row.v(a)} ({a_src}), m {row.v(mm)} ({m_src}); the record's Rw "
                  f"{_rec_rw(f, row)})", row)
        notes = said_whole(w.message for w in caught if isinstance(w.message, UserWarning))
        if notes:
            out.add("  Petrophys said: " + "; ".join(notes))
            sel = str(getattr(f.view, "selection", "") or "")
            if getattr(f.view, "reach", "focus") == "well" and not sel.startswith("where "):
                out.add('  the water-bearing samples alone: this call again with "where" (e.g. "SW > 0.95"), the fit '
                        'then reads only the samples where it holds')
        return out.result()
    if p == "rw" and meth == "sp":
        return _rw_sp(f, keep, rmf, rmf_temp_f)
    if p == "gr_endpoints":
        return _gr_endpoints(f, keep)
    if p == "matrix":
        return _matrix(f, keep)
    if p == "temperature":
        return _temperature(f, bht_f, td)
    if p == "clay_point":
        from petrophys.interpretation.clay_volume.nd_method import nd_shale_point
        _, nphi = _curve(f, "NPHI")
        _, rhob = _curve(f, "RHOB")
        _, vcl = _curve(f, "VCL")
        shale = keep & np.isfinite(vcl) & (vcl > 0.6)
        try:
            r_sh, n_sh = nd_shale_point(nphi[keep], rhob[keep], shale[keep])   # Petrophys returns (den_clay, neu_clay)
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Petrophys nd_shale_point: {type(e).__name__}: {str(e)[:300]}") from None
        row = out.child()
        out.add(f"clay point (Petrophys nd_shale_point on {row.i(int(shale.sum()))} shale samples, VCL > 0.6): NPHI "
                f"{row.v(n_sh)}, RHOB {row.v(r_sh)}", row)
        return out.result()
    raise ToolError(f"{p} by {meth} is not available")


def _gr_endpoints(f: Formation, keep: np.ndarray) -> Result:
    """GR clean and shale lines by the clay-volume step's rule: P5 and P95 of the GR picks, bounded by Petrophys
    (bounded_gr_baselines), over the samples asked and over the whole well, against the record's."""
    from petrophys.interpretation.clay_volume.gr_method import GR_CLEAN_BOUND, GR_SHALE_BOUND, bounded_gr_baselines
    gn, gr = _curve(f, "GR")
    out, row = Out(f), None
    lines = []
    for what, x in (("the samples asked", gr[keep]), ("the whole well", f.view.well_values(gn))):
        x = np.asarray(x, dtype=float)
        x = x[np.isfinite(x)]
        if x.size < 10:
            continue
        p5, p95 = float(np.percentile(x, 5)), float(np.percentile(x, 95))
        clean, shale = bounded_gr_baselines(p5, p95)
        row = out.child()
        lines.append(((f"  over {what} ({row.i(x.size)} samples): P5 {row.v(p5)}, P95 {row.v(p95)} API -> clean "
                       f"{row.v(clean)}, shale {row.v(shale)} API"), row))
    if not lines:
        raise ToolError(f"fewer than 10 {gn} samples here")
    rec = (_method(f, "clay_volume").parameters or {}) if _method(f, "clay_volume") else {}
    bounds = out.child()
    out.add(f"GR endpoints by the clay-volume step's rule ({gn}: P5 for clean, P95 for shale, bounded by Petrophys "
            f"bounded_gr_baselines to a clean line of at most {bounds.v(GR_CLEAN_BOUND)} and a shale line of at least "
            f"{bounds.v(GR_SHALE_BOUND)} API):", bounds)
    for ln, r in lines:
        out.add(ln, r)
    picked = [k for k in ("gr_min", "gr_max", "gr_min_used", "gr_max_used") if _num(rec.get(k))]
    if picked:
        r = out.child()
        out.add("  the record's: " + ", ".join(f"{k} {r.v(rec[k])}" for k in picked) + " API", r)
    return out.result()


def _matrix(f: Formation, keep: np.ndarray) -> Result:
    """Apparent matrix density (RHOmaa) and volumetric photoelectric absorption (Umaa) by Petrophys, per zone,
    against the minerals' values from Petrophys's mineral table and the matrix the record's porosity used."""
    from petrophys.interpretation.lithology.apparent_matrix import (apparent_matrix_density,
                                                                    apparent_matrix_volumetric_pe,
                                                                    apparent_total_porosity)
    from petrophys.interpretation.lithology.matrix_properties import MINERAL_PROPERTIES
    _, rhob = _curve(f, "RHOB")
    _, nphi = _curve(f, "NPHI")
    phia = np.asarray(apparent_total_porosity(rhob, nphi), dtype=float)
    rhomaa = np.asarray(apparent_matrix_density(rhob, phia), dtype=float)
    rhomaa_name = register(f, "RHOMAA", _full(f, rhomaa), "apparent matrix density: RHOB with the pore fluid removed "
                           "(Petrophys)", "g/cc", "apparent matrix (on request)")
    out = Out(f)
    row = out.child()
    out.add(f"apparent matrix by Petrophys (apparent_total_porosity from RHOB and NPHI on the limestone reference, then "
            f"apparent_matrix_density): RHOmaa (median, g/cc) {_zone_means(f, rhomaa, keep, row)}. Written: "
            f"{rhomaa_name}.", row)
    if "PEF" in f.inv.curves and f.view.available("PEF"):
        pef = np.asarray(f.view.values("PEF"), dtype=float)
        umaa = np.asarray(apparent_matrix_volumetric_pe(pef, rhob, phia), dtype=float)
        umaa_name = register(f, "UMAA", _full(f, umaa), "apparent matrix volumetric photoelectric absorption "
                             "(Petrophys)", "b/cc", "apparent matrix (on request)")
        row = out.child()
        out.add(f"  Umaa (median, b/cc; from PEF, apparent_matrix_volumetric_pe) {_zone_means(f, umaa, keep, row)}. "
                f"Written: {umaa_name}.", row)
    else:
        out.add("  no PEF here: Umaa (the RHOmaa-Umaa lithology plot) needs it")
    row = out.child()
    minerals = "; ".join(f"{m} {row.v(MINERAL_PROPERTIES[m]['density'])} g/cc, U {row.v(MINERAL_PROPERTIES[m]['u'])}"
                         for m in ("quartz", "calcite", "dolomite", "anhydrite") if m in MINERAL_PROPERTIES)
    rec = (_method(f, "porosity").parameters or {}) if _method(f, "porosity") else {}
    used = f"; the record's porosity used matrix density {row.v(rec['rho_ma'])} g/cc" if _num(rec.get("rho_ma")) else ""
    out.add(f"  minerals (Petrophys mineral table): {minerals}{used}", row)
    return out.result()


def _temperature_source(rec: dict, row) -> str:
    """Where the record's temperature comes from, from its step's parameters: the measured log with the gradient
    filling its gaps; a gradient anchored to a bottom-hole temperature; or the default gradient, no anchor."""
    g = f"{row.v(rec['gradient_f_per_100ft'])} degF/100ft" if _num(rec.get("gradient_f_per_100ft")) else ""
    surf = f" from a surface {row.v(rec['surface_temp_f'])} degF" if _num(rec.get("surface_temp_f")) else ""
    anchored = _num(rec.get("bht_f"))
    grad = (f"the gradient {g}{surf} to the bottom-hole {row.v(rec['bht_f'])} degF" if anchored else
            f"a default gradient {g}{surf} (no bottom-hole temperature anchors it)") if g else ""
    if _num(rec.get("temp_log_coverage")):
        gaps = rec.get("temp_log_gap_samples")
        fill = (f"; where the log has no value, {grad}" + (f", at {row.i(int(gaps))} samples" if _num(gaps) else "")
                if grad else "")
        return f": the measured temperature log at {row.pct(100 * float(rec['temp_log_coverage']))} of the well's samples{fill}"
    return f": {grad}" if grad else ""


def _temperature(f: Formation, bht_f: Optional[float], td: Optional[float]) -> Result:
    """Formation temperature as the record's temperature step has it (its TEMP and gradient), and the gradient from
    a bottom-hole temperature (given, else the LAS header's) by Petrophys gradient_from_bht."""
    from petrophys.interpretation.temperature.temp_gradient import gradient_from_bht
    m = _method(f, "temperature")
    rec = (m.parameters or {}) if m else {}
    out = Out(f)
    if "TEMP" in f.inv.curves and f.view.available("TEMP"):
        temp = np.asarray(f.view.values("TEMP"), dtype=float)
        keep = np.isfinite(temp)
        row = out.child()
        out.add(f"formation temperature (the record's TEMP; temperature step {m.method if m else 'unknown'}"
                f"{_temperature_source(rec, row)}): mean, degF: {_zone_means(f, temp, keep, row, np.nanmean)}"
                + "".join(f"; TEMP {x}" for x in limits(f, "TEMP")), row)     # what its values show (engine.limits)
    hdr = getattr(f.view.prep.well, "header", None)
    bht = bht_f if bht_f is not None else (getattr(hdr, "bht", None) if hdr is not None else None)
    bht_unit = "F" if bht_f is not None else str(getattr(hdr, "bht_unit", None) or "F")
    depth = td if td is not None else (getattr(hdr, "td", None) if hdr is not None else None)
    depth_unit = f.inv.depth_unit if td is not None else str(getattr(hdr, "td_source_unit", None) or f.inv.depth_unit)
    if not (_num(bht) and _num(depth)):
        out.add("  no bottom-hole temperature here (none given, none in the LAS header): give bht_f (degF) and td (the "
                f"total depth, {f.inv.depth_unit}) for a gradient from them")
        return out.result()
    try:
        g = gradient_from_bht(float(bht), float(depth), bht_unit=bht_unit, depth_unit=depth_unit)
    except Exception as e:  # noqa: BLE001  (the library refuses a temperature or depth it cannot use)
        raise ToolError(f"Petrophys gradient_from_bht: {str(e)[:300]}") from None
    row = out.child()
    src = "given" if bht_f is not None else "LAS header"
    vs = (f" (the record's: {row.v(rec['gradient_f_per_100ft'])})" if _num(rec.get("gradient_f_per_100ft")) else "")
    out.add(f"  gradient from BHT {row.v(bht)} {bht_unit} at TD {row.v(depth)} {depth_unit} ({src}; Petrophys "
            f"gradient_from_bht): {row.v(g)} degF/100ft{vs}", row)
    return out.result()


def _rw_sp(f: Formation, keep: np.ndarray, rmf: Optional[float], rmf_temp_f: Optional[float]) -> Result:
    """Rw from the static SP over the samples asked, by Petrophys sp_rw_in_window: its clean and shale SP lines, the
    mud-filtrate resistivity (given, else the LAS header's) and the record's formation temperature."""
    from petrophys.interpretation.electrical.rw.sp_window import sp_rw_in_window
    _curve(f, "SP")
    hdr = getattr(f.view.prep.well, "header", None)
    rm_f = rmf if rmf is not None else getattr(hdr, "rmf", None)
    rm_t = rmf_temp_f if rmf_temp_f is not None else getattr(hdr, "rm_temp", None)
    if not (_num(rm_f) and _num(rm_t)):
        raise ToolError("rw by sp needs the mud-filtrate resistivity: give rmf (ohm.m) and rmf_temp_f (degF), as this "
                        "LAS header states none")
    temp = f.view.prep.curve("TEMP")
    if temp is None:
        raise ToolError("rw by sp needs the formation temperature (TEMP), which the record does not have here")
    depth = np.asarray(f.view.prep.depth, dtype=float)[f.view.mask][keep]
    try:
        res = sp_rw_in_window(f.view.prep.well, rmf=float(rm_f), rmf_temp_f=float(rm_t),
                              temperature_f=np.asarray(temp, dtype=float), top=float(depth.min()),
                              bottom=float(depth.max()))
    except Exception as e:  # noqa: BLE001  (the library's own reason, said back)
        raise ToolError(f"Petrophys sp_rw_in_window: {str(e)[:300]}") from None
    out = Out(f)
    row = out.child()
    src = "given" if rmf is not None else "LAS header"
    out.add(f"rw from the static SP (Petrophys sp_rw_in_window over {row.i(res.n_samples)} samples, "
            f"{row.i(res.n_clean_samples)} clean): Rw {row.v(res.rw)} ohm.m at {row.v(res.reference_temp_f)} degF; SSP "
            f"{row.v(res.ssp_mv)} mV (clean line {row.v(res.sp_clean_mv)}, shale line {row.v(res.sp_shale_mv)} mV); Rmf "
            f"{row.v(rm_f)} ohm.m at {row.v(rm_t)} degF ({src}). A small SSP means water about as saline as the "
            f"filtrate: then read it as a consistency check. The record's Rw: {_rec_rw(f, row)}.", row)
    return out.result()


def _archie_am(f: Formation) -> list:
    """Archie's a and m with their source: the record's where it states a number, else the library's (a 1, m 2) with
    what the record states instead (lithology_dependent: one per lithology, no single number)."""
    sat, m = defaults(f, "saturation"), _method(f, "saturation")
    rec = (m.parameters or {}) if m else {}
    return [(sat[k], "record") if k in sat else
            (d, "library default" + (f"; the record's is {rec[k]}" if rec.get(k) not in (None, "") else ""))
            for k, d in (("a", 1.0), ("m", 2.0))]


def _rec_rw(f: Formation, row: Out) -> str:
    """The record's Rw as its formation_water step states it: the value with its reference temperature, and the
    range at formation temperature."""
    m = _method(f, "formation_water")
    rec = (m.parameters or {}) if m else {}
    one = next((k for k in ("rw", "rw_from_rwa", "rw_at_measured_temp") if _num(rec.get(k))), None)
    temp = next((rec[k] for k in ("reference_temp_f", "rwa_reference_temp_f", "measured_temp_f") if _num(rec.get(k))), None)
    parts = []
    if one:
        parts.append(f"{row.v(rec[one])} ohm.m ({one}{f' at {row.v(temp)} degF' if temp is not None else ''})")
    if _num(rec.get("rw_min")) and _num(rec.get("rw_max")):
        parts.append(f"{row.v(rec['rw_min'])}-{row.v(rec['rw_max'])} ohm.m at formation temperature")
    return "; ".join(parts) + f" (method {m.method})" if parts and m else "not stated"
