"""classify (docs/TOOLS.md): what the rock or its fluid is, by Petrophys, as classes or flags per
sample: gas effect, mineral volumes, flow units from FZI, electrofacies, moveable hydrocarbons. Each result is
written as curves of the question (GAS_FLAG, V_<MINERAL>, FLOW_UNIT, EFACIES, MOS, SOR) that runs, stats and
conditions read, and is shown zone by zone and pooled."""
from __future__ import annotations

import numpy as np

from petroharness.agent import engine as E
from petroharness.well import summary as S
from petroharness.agent.engine import Formation, Out, Result, ToolError
from petroharness.agent.library import _method, register, scratch_well

OBJECTS = {
    "gas": "gas effect: density porosity above neutron porosity by more than 0.05 (Petrophys detect_gas_effect), "
           "as GAS_FLAG with its depth runs; needs PHID and PHIN (else NPHI)",
    "minerals": "mineral volumes by Petrophys: method solver (multi-mineral solver: quartz, calcite, dolomite, "
                "anhydrite, as many as the logs resolve, with porosity solved, its residual and poor-fit flag; needs "
                "RHOB, NPHI, VCL; PEF and DT add rows) or calcite_dolomite (from RHOB, PHIE, VCL); writes V_<MINERAL>",
    "flow_units": "hydraulic flow units per sample from FZI (Petrophys calculate_flow_units, k-means on log FZI; k "
                  "units, else chosen by the library), as FLOW_UNIT with each unit's mean FZI; per sample, unlike "
                  "unit_roles' per-zone flow roles; needs PERM and PHIE",
    "electrofacies": "electrofacies by Petrophys k-means on RHOB, NPHI, GR and RDEP over the well (up to 5 classes; "
                     "the library fixes the curves and the class count), as EFACIES",
    "moveable_hydrocarbons": "moveable oil saturation MOS = SXO - SW and residual oil SOR = 1 - SXO (Petrophys), "
                             "beyond the record's MHI ratio; needs SXO from a flushed-zone log (RXO with RMF), not "
                             "the quicklook",
}


def _curve(f: Formation, *names) -> tuple:
    for n in names:
        if n in f.inv.curves:
            v = f.view.values(n)
            if v is not None and np.isfinite(v).any():
                return n, np.asarray(v, dtype=float)
    raise ToolError(f"needs {' or '.join(names)}; {'it has no data' if len(names) == 1 else 'none of them has data'} here")


def _full(f: Formation, values: np.ndarray) -> np.ndarray:
    full = np.full(np.asarray(f.view.prep.depth).size, np.nan)
    full[f.view.mask] = values
    return full


def _picked(f: Formation, zones) -> tuple:
    picked = E.zones(f, zones)
    idx = np.unique(np.concatenate([np.asarray(z.indices) for z in picked])) if picked else np.arange(f.depth.size)
    from petroharness.agent.state import _all
    if not zones or _all(zones):                                    # no zone named: the whole selection, as lookups
        idx = np.arange(f.depth.size)
    return picked, idx


def _pooled(f: Formation, idx: np.ndarray, row: Out) -> str:
    """The label of the samples idx taken as one: 'pooled' (the zones'), or, where they reach outside every zone,
    the whole selection's label as every lookup writes it."""
    if S.outside_mask(f.view)[idx].any():
        return S.whole_label_of(f.view, row.i)
    return "pooled"


MANY = 12                       # past this many zones, a per-zone list keeps the zones that matter and counts the rest


def _per_zone(row: Out, items: list, pct: bool = False, keep_zero: bool = True) -> str:
    """(zone id, value) as 'Z1 0.12; Z2 0.3': every zone, or past MANY zones the highest MANY (keep_zero false: of
    those above 0), with how many more."""
    items = [(z, v) for z, v in items if np.isfinite(v)]
    fmt = row.pct if pct else row.v
    if len(items) <= MANY:
        return "; ".join(f"{z} {fmt(v)}" for z, v in items)
    pool = items if keep_zero else [(z, v) for z, v in items if v > 0]
    shown = sorted(pool, key=lambda x: -x[1])[:MANY]
    rest = len(items) - len(shown)
    tail = f" ({rest} other zones {'lower' if keep_zero or len(pool) > len(shown) else 'at 0'})" if rest else ""
    return ("; ".join(f"{z} {fmt(v)}" for z, v in shown) or "none above 0") + tail


def _share(out: Out, f: Formation, flag: np.ndarray, picked: list, idx: np.ndarray, what: str) -> None:
    """The flag's share set and thickness, each zone and pooled."""
    from petrophys.evaluation.intervals import flag_intervals
    row = out.child()
    items = []
    for z in picked:
        zi = np.asarray(z.indices)
        ok = np.isfinite(flag[zi])
        if ok.any():
            items.append((z.zone_id, 100 * float(np.mean(flag[zi][ok] > 0.5))))
    ok = np.isfinite(flag[idx])
    pooled = 100 * float(np.mean(flag[idx][ok] > 0.5)) if ok.any() else float("nan")
    out.add(f"  {what} share of samples: " + _per_zone(row, items, pct=True, keep_zero=False)
            + f"; {_pooled(f, idx, row)} {row.pct(pooled)}", row)
    on = np.zeros(f.depth.size)
    on[idx] = np.nan_to_num(flag[idx]) > 0.5
    runs = flag_intervals(on, f.depth)
    if len(runs):
        runs = runs.sort_values("thickness", ascending=False) if "thickness" in runs else runs
        r = out.child()
        listed = "; ".join(f"{r.span(t, b)}" + (f" ({r.v(th)} {f.inv.depth_unit})" if th is not None else "")
                           for t, b, th in zip(runs["top"], runs["bottom"],
                                               runs["thickness"] if "thickness" in runs else [None] * len(runs)))
        shown = min(len(runs), 12)
        out.add(f"  runs ({len(runs)}, thickest first{', the first ' + str(shown) if len(runs) > shown else ''}): "
                + "; ".join(listed.split("; ")[:shown]), r)


def _gas(f: Formation, picked, idx) -> Result:
    from petrophys.interpretation.porosity.total_porosity import detect_gas_effect
    dn, phid = _curve(f, "PHID")
    nn, phin = _curve(f, "PHIN", "NPHI")
    ok = np.isfinite(phid) & np.isfinite(phin)
    flag = np.where(ok, np.asarray(detect_gas_effect(phin, phid), dtype=float), np.nan)
    name = register(f, "GAS_FLAG", _full(f, flag), f"gas effect: {dn} above {nn} by more than 0.05 (Petrophys "
                    "detect_gas_effect)", "flag", "classify gas (on request)")
    out = Out(f)
    row = out.child()
    out.add(f"gas effect by Petrophys detect_gas_effect: {dn} > {nn} + {row.v(0.05)} (density porosity above neutron "
            f"porosity) on {row.i(int(ok[idx].sum()))} samples with both", row)
    _share(out, f, flag, picked, idx, "gas effect")
    out.add(f"  written: {name} (a flag of this question: runs, stats and conditions read it)")
    return out.result()


def _minerals(f: Formation, method: str | None, picked, idx) -> Result:
    meth = str(method or "solver").strip().lower()
    out = Out(f)
    if meth == "calcite_dolomite":
        from petrophys.interpretation.lithology.carbonate_minerals import (
            CARBONATE_CALIBRATIONS,
            solve_calcite_dolomite,
        )
        _, rhob = _curve(f, "RHOB")
        pn, phi = _curve(f, "PHIE", "PHIT")
        _, vcl = _curve(f, "VCL")
        k = CARBONATE_CALIBRATIONS["generic"]
        res = solve_calcite_dolomite(rhob, phi, vcl, rho_fluid=float(k["rho_fluid"]), rho_clay=float(k["rho_clay"]))
        vols = {"calcite": res["calcite"], "dolomite": res["dolomite"]}
        solved = np.asarray(res["solved"], dtype=bool)
        row = out.child()
        out.add(f"calcite and dolomite by Petrophys solve_calcite_dolomite from RHOB, {pn} and VCL (fluid "
                f"{row.v(k['rho_fluid'])}, clay {row.v(k['rho_clay'])} g/cm3; a sample solves within 0.02 g/cm3 of "
                f"RHOB)", row)
        poor = None
    elif meth == "solver":
        from petrophys.interpretation.lithology import MultiMineralSolver
        _, rhob = _curve(f, "RHOB")
        _, nphi = _curve(f, "NPHI")
        _, vcl = _curve(f, "VCL")
        pef = f.view.values("PEF") if "PEF" in f.inv.curves else None
        dt = next((f.view.values(c) for c in ("DTC", "DT") if c in f.inv.curves), None)
        solver = MultiMineralSolver()
        try:
            res = solver.solve(rhob, nphi, vcl, pef=pef, dt=dt)
        except Exception as e:  # noqa: BLE001  (a library failure is the model's to read)
            raise ToolError(f"Petrophys MultiMineralSolver: {type(e).__name__}: {str(e)[:300]}") from None
        minerals = list(dict.fromkeys(solver.minerals + solver.minerals_no_pef))
        vols = {m: np.asarray(res[m], dtype=float) for m in minerals if m in res}
        solved = np.asarray(res["solved"], dtype=bool)
        poor = np.asarray(res["qc_flag"], dtype=float)
        row = out.child()
        rows = "RHOB, NPHI" + (", PEF" if pef is not None else "") + (", DT" if dt is not None else "")
        out.add(f"minerals by Petrophys MultiMineralSolver (porosity solved with the minerals, VCL given) on rows "
                f"{rows}; solved {row.pct(100 * float(solved[idx].mean()))} of samples; poor fit (residual over the "
                f"library's tolerance) {row.pct(100 * float(np.nanmean(poor[idx] > 0.5)))}", row)
    else:
        raise ToolError(f"minerals takes method solver or calcite_dolomite, not {method!r}")
    written = []
    for m, v in vols.items():
        v = np.where(solved, v, np.nan)
        if not np.isfinite(v[idx]).any():
            continue
        name = register(f, f"V_{m.upper()}", _full(f, v), f"{m} bulk volume (Petrophys {meth})", "v/v",
                        f"classify minerals {meth} (on request)")
        written.append(name)
        row = out.child()
        items = [(z.zone_id, float(np.nanmean(v[np.asarray(z.indices)]))) for z in picked
                 if np.isfinite(v[np.asarray(z.indices)]).any()]
        out.add(f"  {m} mean volume over solved samples: " + _per_zone(row, items)
                + f"; {_pooled(f, idx, row)} {row.v(float(np.nanmean(v[idx])))}", row)
    if poor is not None:
        name = register(f, "MM_POOR_FIT", _full(f, poor), "the solver's poor-fit flag (Petrophys MultiMineralSolver "
                        "qc_flag)", "flag", "classify minerals solver (on request)")
        written.append(name)
    out.add(f"  written: {', '.join(written) or 'nothing'} (curves of this question)")
    return out.result()


def _flow_units(f: Formation, method: str | None, k: int | None, picked, idx) -> Result:
    from petrophys.evaluation.flow_units.flow_units_module import calculate_flow_units
    if method and str(method).strip().lower() != "kmeans":
        raise ToolError(f"flow_units takes method kmeans, not {method!r}")
    pn, perm = _curve(f, "PERM")
    fn, phie = _curve(f, "PHIE")
    if k is not None and (not isinstance(k, (int, float)) or not 1 <= int(k) <= 6):
        raise ToolError(f"k is the number of units, 1 to 6, not {k!r}")
    try:
        res = calculate_flow_units(perm[idx], phie[idx], n_units=int(k) if k is not None else None)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Petrophys calculate_flow_units: {type(e).__name__}: {str(e)[:300]}") from None
    labels = np.full(f.depth.size, np.nan)
    labels[idx] = np.where(np.asarray(res.hfu) > 0, np.asarray(res.hfu, dtype=float), np.nan)
    name = register(f, "FLOW_UNIT", _full(f, labels), "hydraulic flow unit from FZI (Petrophys calculate_flow_units)",
                    "", "classify flow_units (on request)")
    out = Out(f)
    row = out.child()
    out.add(f"flow units by Petrophys calculate_flow_units (FZI from {pn} and {fn}, k-means on log FZI): "
            f"{row.i(res.n_units)} units over {row.i(int(np.sum(np.asarray(res.hfu) > 0)))} samples"
            + (f", k {row.i(int(k))} asked" if k is not None else ", k chosen by the library"), row)
    for u in range(1, res.n_units + 1):
        r = out.child()
        items = []
        for z in picked:
            zl = labels[np.asarray(z.indices)]
            n_z = int(np.sum(np.isfinite(zl)))
            if n_z:
                items.append((z.zone_id, 100 * float(np.sum(zl == u)) / n_z))
        out.add(f"  unit {u}: mean FZI {r.v(float(res.fzi_unit_mean[u - 1]))} (geometric), {r.i(int(res.counts[u - 1]))} "
                f"samples; share of each zone's samples: " + _per_zone(r, items, pct=True), r)
    if len(res.fzi_boundaries):
        r = out.child()
        out.add("  FZI boundaries between units: " + ", ".join(r.v(float(b)) for b in res.fzi_boundaries), r)
    out.add(f"  written: {name} (classes 1-{res.n_units}; a class curve of this question)")
    return out.result()


def _electrofacies(f: Formation, k: int | None, curves, picked, idx) -> Result:
    # Petrophys's k-means electrofacies, through its public numerical analysis (NumericalStatisticalAnalysis.analyze:
    # its ELECTROFACIES curve; the well is not changed). No public function takes the curves or the class count.
    from petrophys.evaluation.diagnostics.numerical_statistical_analysis import (
        NumericalStatisticalAnalysis as N,
    )
    well = scratch_well(f)
    n = np.asarray(f.view.prep.depth).size
    got = N().analyze(well, add_curves=False).derived_curves.get("ELECTROFACIES")
    full = np.asarray(got.data, dtype=float) if got is not None else np.full(n, np.nan)
    vals = full[f.view.mask]
    if not np.isfinite(vals[idx]).any():
        raise ToolError("electrofacies needs at least two of RHOB, NPHI, GR and RDEP with data here")
    full = full + 1                                                  # classes 1..n, as the other class curves
    vals = full[f.view.mask]
    name = register(f, "EFACIES", full, "electrofacies (Petrophys k-means on RHOB, NPHI, GR and RDEP over the well)",
                    "", "classify electrofacies (on request)")
    classes = sorted(int(c) for c in np.unique(vals[idx][np.isfinite(vals[idx])]))
    out = Out(f)
    row = out.child()
    note = "" if k is None and not curves else "; the library fixes the curves and the class count, so k and curves " \
                                               "were not applied"
    out.add(f"electrofacies by Petrophys k-means (RHOB, NPHI, GR, RDEP, scaled; up to 5 classes, over the whole well)"
            f": {row.i(len(classes))} classes in these samples{note}", row)
    for c in classes:
        r = out.child()
        items = []
        for z in picked:
            zl = vals[np.asarray(z.indices)]
            n_z = int(np.sum(np.isfinite(zl)))
            if n_z:
                items.append((z.zone_id, 100 * float(np.sum(zl == c)) / n_z))
        out.add(f"  class {c}: {r.i(int(np.sum(vals[idx] == c)))} samples; share of each zone's samples: "
                + _per_zone(r, items, pct=True), r)
    out.add(f"  written: {name} (a class curve of this question; stats with where \"{name} == 1\" describes a class)")
    return out.result()


def _moveable(f: Formation, picked, idx) -> Result:
    from petrophys.interpretation.saturation.sxo import (
        moveable_oil_saturation,
        residual_oil_saturation,
    )
    sat = _method(f, "saturation")
    how = str(((sat.parameters or {}) if sat else {}).get("sxo_method") or "")
    if "quicklook" in how or not how:
        reason = ((sat.parameters or {}) if sat else {}).get("sxo_reason") or "no flushed-zone resistivity with RMF"
        raise ToolError(f"moveable hydrocarbons need SXO from a flushed-zone log: here SXO is "
                        f"{how or 'not stated'} ({reason}), so SXO - SW would restate SW")
    _, sxo = _curve(f, "SXO")
    _, sw = _curve(f, "SW")
    ok = np.isfinite(sxo) & np.isfinite(sw)
    mos = np.where(ok, np.asarray(moveable_oil_saturation(sxo, sw), dtype=float), np.nan)
    sor = np.where(np.isfinite(sxo), np.asarray(residual_oil_saturation(sxo), dtype=float), np.nan)
    out = Out(f)
    out.add(f"moveable hydrocarbons by Petrophys: MOS = SXO - SW (moveable_oil_saturation, floored at 0) and SOR = "
            f"1 - SXO (residual_oil_saturation); SXO by {how}")
    written = []
    for nm, v, what in (("MOS", mos, "moveable oil saturation"), ("SOR", sor, "residual oil saturation")):
        name = register(f, nm, _full(f, v), f"{what} (Petrophys)", "v/v", "classify moveable_hydrocarbons (on request)")
        written.append(name)
        r = out.child()
        items = [(z.zone_id, float(np.nanmean(v[np.asarray(z.indices)]))) for z in picked
                 if np.isfinite(v[np.asarray(z.indices)]).any()]
        out.add(f"  {nm} mean: " + _per_zone(r, items) + f"; {_pooled(f, idx, r)} {r.v(float(np.nanmean(v[idx])))}", r)
    out.add(f"  written: {', '.join(written)} (curves of this question; the record's MHI = SW / SXO stays as it is)")
    return out.result()


def classify(f: Formation, what: str, method: str | None = None, curves=None, zones=None,
             k: int | None = None) -> Result:
    w = str(what or "").strip().lower().replace(" ", "_")
    if w not in OBJECTS:
        raise ToolError(f"classify has no {what!r}; it gives: " + "; ".join(f"{n}: {d}" for n, d in OBJECTS.items()))
    picked, idx = _picked(f, zones)
    if w == "gas":
        return _gas(f, picked, idx)
    if w == "minerals":
        return _minerals(f, method, picked, idx)
    if w == "flow_units":
        return _flow_units(f, method, k, picked, idx)
    if w == "electrofacies":
        return _electrofacies(f, k, curves, picked, idx)
    return _moveable(f, picked, idx)
