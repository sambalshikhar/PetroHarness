"""Synthetic wells for the interval tests: a LAS file and a tops file written from arrays chosen by hand, so that what
a stretch, a zone or a selection must hold can be typed in the test. Two levels:

- `prepared(depth, curves, ...)`: a stand-in for the prepared well (depth and curves only, no Petrophys run), for the
  view's own logic: `view(...)` builds a FormationView over it with the real labelling and zoning;
- `write_las(path, depth, curves, unit)` and `write_tops(path, rows)`: files the real pipeline reads (ask._settings,
  ask._interval, prepare_well), for integration tests.

The lithology codes are the library's built-in table (petroharness.well.formation.lithology_names()).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


# --- a stand-in prepared well ---------------------------------------------------------------------------------------

@dataclass
class FakePrepared:
    depth: np.ndarray
    curves: dict = field(default_factory=dict)
    input_curves: list = field(default_factory=list)
    derived_curves: list = field(default_factory=list)

    def curve(self, name: str) -> Optional[np.ndarray]:
        c = self.curves.get(name)
        return None if c is None else np.asarray(c, dtype=float)


def runs_of(spec) -> np.ndarray:
    """Per-sample values from [(value, count), ...]."""
    return np.concatenate([np.full(int(n), v, dtype=float) for v, n in spec])


def view(depth, *, lithology=None, vcl=None, focus=None, layout="lithology_runs", min_thickness_m=2.0,
         depth_scale=1.0, report_unit="m", m_per_unit=1.0, bands=(0.3, 0.6), table=None):
    """A FormationView over a stand-in well: `lithology` codes (a lithology log, curve LITH) or `vcl` (shale-volume
    bands without one); `focus` (top, base) in the reporting unit, both included (default: the whole well). The labels
    and zones are made by the view's own path (stretch over the focus)."""
    from petroharness.well.formation import Interval, lithology_names
    from petroharness.well.view import FormationView, _labels, _zones_over
    depth = np.asarray(depth, dtype=float)
    curves = {}
    if lithology is not None:
        curves["LITH"] = np.asarray(lithology, dtype=float)
    if vcl is not None:
        curves["VCL"] = np.asarray(vcl, dtype=float)
    prep = FakePrepared(depth=depth, curves=curves, input_curves=sorted(curves))
    rep = depth * depth_scale
    top, base = focus if focus is not None else (float(np.nanmin(rep)), float(np.nanmax(rep)))
    interval = Interval(formation="SYNTHETIC", top=top, base=base, closed=True)
    mask = interval.contains(rep)
    curve = "LITH" if lithology is not None else None
    use_bands = tuple(bands) if curve is None and vcl is not None else None
    code_table = dict(table) if table is not None else lithology_names()      # the library's built-in table
    labels = _labels(prep, mask, curve, use_bands, code_table)
    policy = {"zones": {"min_thickness_m": float(min_thickness_m)}}
    zones = _zones_over(rep[mask], labels, layout, float(min_thickness_m) / m_per_unit, None)
    return FormationView(task=None, prep=prep, interval=interval, mask=mask, zones=zones, policy=policy,
                         labels=labels, reg=None, lithology_curve=curve, vcl_bands=use_bands, code_table=code_table,
                         depth_scale=depth_scale, report_unit=report_unit, m_per_unit=m_per_unit,
                         zone_layout=layout)


# --- files for the real pipeline ------------------------------------------------------------------------------------

def write_las(path: Path, depth, curves: dict, unit: str = "M", well: str = "SYNTH-1") -> Path:
    """A LAS 2.0 file: DEPT in `unit` and the curves given (name -> (unit, values)); NaN written as -999.25."""
    import lasio
    las = lasio.LASFile()
    las.well["WELL"].value = well
    las.append_curve("DEPT", np.asarray(depth, dtype=float), unit=unit, descr="Depth")
    for name, (cu, values) in curves.items():
        las.append_curve(name, np.asarray(values, dtype=float), unit=cu)
    path = Path(path)
    las.write(str(path), version=2.0)
    return path


def write_tops(path: Path, rows, header=("formation_name", "top_depth", "bottom_depth", "depth_unit")) -> Path:
    """A tops CSV: `rows` are tuples in the order of `header` (None written empty)."""
    path = Path(path)
    lines = [",".join(header)] + [",".join("" if v is None else str(v) for v in r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def plausible_logs(depth, sand_mask) -> dict:
    """Logs a petrophysical workflow can interpret: clean, porous, oil-bearing sand where `sand_mask`, shale elsewhere
    (GR, RHOB, NPHI, RDEP, DTC, CALI, BS), with a little noise from a fixed seed."""
    rng = np.random.default_rng(0)
    n = len(depth)
    s = np.asarray(sand_mask, dtype=bool)
    jitter = lambda scale: rng.normal(0.0, scale, n)
    return {
        "GR": ("GAPI", np.where(s, 35.0, 110.0) + jitter(3.0)),
        "RHOB": ("G/C3", np.where(s, 2.30, 2.55) + jitter(0.01)),
        "NPHI": ("V/V", np.where(s, 0.20, 0.33) + jitter(0.005)),
        "RDEP": ("OHMM", np.where(s, 40.0, 3.0) * np.exp(jitter(0.05))),
        "DTC": ("US/F", np.where(s, 85.0, 100.0) + jitter(1.0)),
        "CALI": ("IN", 8.5 + jitter(0.05)),
        "BS": ("IN", np.full(n, 8.5)),
    }
