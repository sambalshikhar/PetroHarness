"""The interval's logs for the web UI's plot: the measured logs and Petrophys's interpretation over the interval, track
by track, with the lithology zones and each zone's means.

The curves are chosen by the curve registry's log families (resources/rules/curves.yaml) and Petrophys's output
names, never by one well's own mnemonics. Each track shows a log on its conventional display scale when nine in ten of
its values fall on that scale, else on the range of its own values (P1-P99). A curve is thinned to at most MAX_POINTS
samples for the page (a flag keeps a set sample of every window, so a thin flagged run stays visible).
"""

from __future__ import annotations

import math

import numpy as np

MAX_POINTS = 1500
# (track title, the curves: a registry family's first curve with data ("family:<name>"), every curve of a family with
# data, up to three ("families:<name>"), or a Petrophys output name; the scale)
TRACKS = (
    ("Gamma ray", ("family:gamma ray", "family:caliper"), "linear"),
    ("Resistivity", ("families:resistivity",), "log"),
    ("Density · neutron", ("family:density", "family:neutron"), "linear"),
    ("Sonic", ("family:sonic",), "linear"),
    ("Shale volume", ("VCL",), "linear"),
    ("Porosity", ("PHIE", "PHIT"), "linear"),
    ("Water saturation", ("SW",), "linear"),
    ("Permeability", ("PERM",), "log"),
)
# conventional display scales (left, right): by registry family, or by Petrophys's output name
SCALES = {"gamma ray": (0, 150), "caliper": (6, 16), "resistivity": (0.2, 2000), "density": (1.95, 2.95),
          "neutron": (0.45, -0.15), "sonic": (140, 40), "VCL": (0, 1), "PHIE": (0.5, 0), "PHIT": (0.5, 0),
          "SW": (1, 0), "PERM": (0.01, 10000)}
MEANS = ("VCL", "PHIE", "SW")          # each zone's mean
CUTOFF_STEP = "net_pay"                # the workflow step whose <curve>_cutoff parameters the page draws
MEDIANS = ("PERM",)                    # each zone's median (permeability spans decades)
FLAGS_SHOWN = 4


def _round(x: float) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return float(f"{x:.5g}")


def _family(reg_curves: dict, name: str) -> str | None:
    for fam, members in (reg_curves.get("families") or {}).items():
        if name in members:
            return fam
    return None


def _scale(values: np.ndarray, conventional: tuple | None, log: bool) -> tuple:
    """(left, right): the conventional scale when nine in ten values fall on it, else the values' P1-P99 (the
    conventional direction kept)."""
    v = values[np.isfinite(values)]
    if log:
        v = v[v > 0]
    if not v.size:
        return conventional or ((0.1, 1000) if log else (0, 1))
    if conventional:
        lo, hi = sorted(conventional)
        if np.mean((v >= lo) & (v <= hi)) >= 0.9:
            return conventional
    lo, hi = (float(x) for x in np.percentile(v, [1, 99]))
    if hi <= lo:
        lo, hi = (lo / 2, lo * 2) if log else (lo - 0.5, hi + 0.5)
    reverse = bool(conventional) and conventional[0] > conventional[1]
    return (_round(hi), _round(lo)) if reverse else (_round(lo), _round(hi))


def _thin(values: np.ndarray, k: int, flag: bool = False) -> list:
    if k > 1:
        if flag:                                   # the window's set sample, so a thin run stays visible
            n = values.size
            starts = np.arange(0, n, k)
            values = np.array([np.nanmax(values[s:s + k]) if np.isfinite(values[s:s + k]).any() else np.nan
                               for s in starts])
        else:
            values = values[::k]
    return [_round(float(x)) for x in values]


def made(view) -> dict:
    """How the interval was interpreted and zoned, as the page says it under the plot: Petrophys's run (its dynamic
    workflow with the settings given, a context profile, an interpreter or an engine) and the steps its workflow ran;
    where the lithology came from (the LAS's own lithology log; Petrophys's mineral solver, with its step record:
    method, domain, input curves, decisions, samples solved; or shale-volume bands, with the shale-volume step's
    method); and the zone rule (layout, minimum thickness in the reporting unit, the user's zones)."""
    prep = view.prep
    adj = prep.policy_adjustments or {}
    opts = adj.get("interpret") or {}
    if "engine" in adj:
        run = {"kind": "engine", "name": str(adj["engine"])[:120]}
    elif "interpreter" in adj:
        run = {"kind": "interpreter", "name": str(adj["interpreter"])[:120]}
    elif opts.get("context_profile"):
        run = {"kind": "context profile", "name": str(opts["context_profile"])}
    else:
        run = {"kind": "dynamic workflow"}
    steps = [name for name, e in (prep.steps or {}).items() if (e or {}).get("stage", "workflow") == "workflow"]
    if view.lithology_curve:
        lith = {"source": "lithology log", "curve": view.lithology_curve, "codes": len(view.code_table or {})}
    elif view.solver_curve:
        lith = {"source": "mineral solver", **view.solver_record}
    elif view.vcl_bands:
        lith = {"source": "shale-volume bands", "bands": list(view.vcl_bands),
                "method": str(((prep.steps or {}).get("vclay") or {}).get("method") or "")}
    else:
        lith = {"source": "none"}
    zones = view.policy.get("zones") or {}
    rule = {"layout": view.zone_layout, "user": bool(view.user_zones), "file": view.zones_source,
            "min_thickness": _round(float(zones.get("min_thickness_m", 0.0)) / (view.m_per_unit or 1.0))}
    return {"run": run, "steps": steps, "lithology": lith, "zone_rule": rule}


def payload(view) -> dict:
    """The interval's plot: depths (the reporting unit), the tracks with their curves and scales, the flags, the
    lithology column (each run of one lithology), the zones with their means, and the net-pay step's cutoffs."""
    reg = view.reg.curves
    families = reg.get("families") or {}
    prep = view.prep
    depth = np.asarray(view.depth, dtype=float)
    n = depth.size
    k = max(1, math.ceil(n / MAX_POINTS))
    measured = set(prep.input_curves)

    def has(c):
        return bool(c) and view.available(c)

    def curve(c: str, log: bool) -> dict:
        values = np.asarray(view.values(c), dtype=float)
        fam = _family(reg, c)
        got = prep.well.get(c)
        return {"name": c, "unit": prep.unit(c), "about": str(getattr(got, "description", "") or "")[:120],
                "source": "LAS" if c in measured else "Petrophys",
                "scale": _scale(values, SCALES.get(fam) or SCALES.get(c), log), "values": _thin(values, k)}

    tracks = []
    for title, members, scale in TRACKS:
        names = []
        for m in members:
            if m.startswith("family:"):
                names += [next((c for c in families.get(m[7:], []) if has(c)), None)]
            elif m.startswith("families:"):
                names += [c for c in families.get(m[9:], []) if has(c)][:3]
            else:
                names.append(m)
        names = [c for c in dict.fromkeys(names) if has(c)]
        if names:
            tracks.append({"title": title, "log": scale == "log", "curves": [curve(c, scale == "log") for c in names]})
    flags = [{"name": f, "values": _thin(np.asarray(view.values(f), dtype=float), k, flag=True)}
             for f in (reg.get("flags") or []) if has(f)][:FLAGS_SHOWN]

    runs, labels = [], list(view.labels) if view.labels is not None else []
    step = float(np.median(np.diff(depth))) if n > 1 else 0.0
    for i, lab in enumerate(labels):
        if runs and runs[-1]["lithology"] == lab and i == runs[-1]["_end"] + 1:
            runs[-1]["base"], runs[-1]["_end"] = depth[i], i
        else:
            runs.append({"lithology": str(lab), "top": depth[i], "base": depth[i], "_end": i})
    for r in runs:
        r["top"], r["base"] = _round(r["top"] - step / 2), _round(r["base"] + step / 2)
        r.pop("_end")

    zones = []
    for z in view.zones:
        row = {"zone": z.zone_id, "lithology": z.lithology, "top": _round(z.top), "base": _round(z.base),
               "thickness": _round(z.base - z.top), "samples": len(z.indices)}
        stats = {}
        for c in MEANS + MEDIANS:
            if has(c):
                v = view.zone_values(z, c)
                v = v[np.isfinite(v)] if v is not None else np.array([])
                if v.size:
                    stats[c] = _round(float(np.median(v) if c in MEDIANS else np.mean(v)))
        for f in flags:
            v = view.zone_values(z, f["name"])
            v = v[np.isfinite(v)] if v is not None else np.array([])
            if v.size:
                stats[f["name"]] = _round(100.0 * float(np.mean(v > 0)))
        row["stats"] = stats
        zones.append(row)

    # the net-pay step's cutoffs, by the curve each names (vcl_cutoff: VCL), as the step record holds them
    params = ((prep.steps or {}).get(CUTOFF_STEP) or {}).get("parameters") or {}
    cutoffs = {k[:-len("_cutoff")].upper(): float(v) for k, v in params.items()
               if k.endswith("_cutoff") and isinstance(v, (int, float)) and not isinstance(v, bool)
               and has(k[:-len("_cutoff")].upper())}
    base = view.interval.base if view.interval.base is not None else (float(depth[-1]) if n else None)
    return {"unit": view.report_unit, "top": _round(float(view.interval.top)), "base": _round(base),
            "samples": int(n), "step": _round(step * k), "depth": _thin(depth, k), "tracks": tracks, "flags": flags,
            "lithology": runs, "lithology_curve": view.lithology_curve,
            "zone_bands": list(view.vcl_bands) if view.vcl_bands else None, "made": made(view),
            "zones": zones, "means": list(MEANS), "medians": list(MEDIANS), "cutoffs": cutoffs, "cutoff_step": CUTOFF_STEP}


# --- the log viewer: every curve of the well, and any depth window at the detail it needs ---------------------------

EXTENTS = ("interval", "well")


def extent_view(view, extent: str = "interval"):
    """The view the log viewer shows: the question's interval, or the whole prepared well (its zones by the same rule)."""
    if extent not in EXTENTS:
        raise ValueError(f"WHAT: no extent {extent!r}. FIX: use one of {', '.join(EXTENTS)}.")
    if extent == "interval":
        return view
    depth = np.asarray(view.prep.depth, dtype=float) * view.depth_scale
    held = depth[np.isfinite(depth)]
    return view.stretch(float(held.min()), float(held.max()), name="whole well")


def _kind(view, name: str, values: np.ndarray) -> str:
    """curve, flag (0 and 1 only) or classes (Petrophys keeps category labels with it)."""
    got = view.prep.well.get(name)
    if ((getattr(getattr(got, "metadata", None), "custom", None) or {}).get("category_labels")):
        return "classes"
    v = values[np.isfinite(values)]
    return "flag" if v.size and bool(np.all((v == 0) | (v == 1))) else "curve"


def log_index(view, extent: str = "interval") -> dict:
    """What the log viewer can show of an extent: its depth range, every curve with a value there (unit, what it is,
    measured or computed, its kind, a scale to start from and whether it reads better on a log scale), the tracks the
    page starts with (the plot's), the lithology runs, the zones and how they were made."""
    v = extent_view(view, extent)
    base = payload(v)
    reg, prep = view.reg.curves, view.prep
    measured = set(prep.input_curves)
    log_families = {m[7:] if m.startswith("family:") else m[9:] if m.startswith("families:") else m
                    for _, members, scale in TRACKS if scale == "log" for m in members}
    curves = []
    for name in sorted(prep.well.curves):
        if name.upper() in ("DEPT", "DEPTH") or not v.available(name):
            continue
        values = np.asarray(v.values(name), dtype=float)
        fam = _family(reg, name)
        log = fam in log_families or name in log_families
        got = prep.well.get(name)
        curves.append({"name": name, "unit": prep.unit(name), "about": str(getattr(got, "description", "") or "")[:120],
                       "source": "LAS" if name in measured else "Petrophys", "family": fam, "kind": _kind(view, name, values),
                       "log": log, "scale": _scale(values, SCALES.get(fam) or SCALES.get(name), log)})
    tracks = [{"title": t["title"], "log": t["log"], "curves": [c["name"] for c in t["curves"]]} for t in base["tracks"]]
    return {"extent": extent, "unit": base["unit"], "top": base["top"], "base": base["base"], "samples": base["samples"],
            "step": _round(float(np.median(np.diff(np.asarray(v.depth, dtype=float)))) if base["samples"] > 1 else 0.0),
            "curves": curves, "tracks": tracks, "flags": [f["name"] for f in base["flags"]],
            "lithology": base["lithology"], "zones": [{k: z[k] for k in ("zone", "lithology", "top", "base")} for z in base["zones"]],
            "made": base["made"], "cutoffs": base["cutoffs"]}


def _window(v, top: float, base: float) -> np.ndarray:
    depth = np.asarray(v.depth, dtype=float)
    lo, hi = (top, base) if top <= base else (base, top)
    return np.flatnonzero((depth >= lo) & (depth <= hi))


def log_window(view, top: float, base: float, curves: list, points: int = MAX_POINTS, extent: str = "interval") -> dict:
    """The named curves between two depths, at most `points` samples each (every k-th beyond that; a flag keeps a set
    sample of each k): what the viewer draws for the window on screen, in full detail once it is zoomed in."""
    v = extent_view(view, extent)
    idx = _window(v, float(top), float(base))
    depth = np.asarray(v.depth, dtype=float)[idx]
    k = max(1, math.ceil(idx.size / max(1, int(points))))
    out = {}
    for name in curves:
        if not v.available(name):
            continue
        values = np.asarray(v.values(name), dtype=float)[idx]
        out[name] = _thin(values, k, flag=_kind(view, name, values) == "flag")
    return {"extent": extent, "top": float(top), "base": float(base), "samples": int(idx.size), "every": k,
            "depth": [round(float(d), 4) for d in depth[::k]], "values": out}       # depths exact: a zoomed window
