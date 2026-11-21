"""The curves Petrophys's analyzers derive while they classify a zone, kept apart from the interpreted well."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class DerivedCurves:
    """The analyzers' derived curves over a well's samples, NaN outside the zones they were derived for."""

    n_samples: int
    new: dict[str, tuple[np.ndarray, str]] = field(default_factory=dict)   # name -> (values, unit)
    fills: dict[str, np.ndarray] = field(default_factory=dict)             # name -> values
    # name -> the analyzer's description of a curve this run made its own way (petrophys DerivedCurve.basis, set where
    # the run chose how: S_V from the datum or from the top of the analysed interval; the resistivity pair a ratio
    # used), the first one given: what the curve catalog's general line cannot know
    described: dict[str, str] = field(default_factory=dict)

    def add(self, well, rows: np.ndarray, curves: dict) -> None:
        """One analyzer run's derived curves (name -> petrophys Curve over the run's samples) for the zone whose
        samples are `rows` of `well` (the interpreted petrophys Well), in the analyzer's order."""
        for name, curve in curves.items():
            try:
                data = np.asarray(curve.data, dtype=float)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(data).any():
                continue
            said = " ".join(str(getattr(curve, "description", "") or "").split())
            basis = getattr(curve, "basis", None)
            if basis is None:                                   # a written curve keeps it in its metadata
                basis = (getattr(getattr(curve, "metadata", None), "custom", None) or {}).get("basis")
            if said and basis and name not in self.described:
                self.described[name] = said
            own = well.get(name)
            if own is None:
                values, _ = self.new.setdefault(name, (np.full(self.n_samples, np.nan), str(curve.unit or "")))
            elif np.isfinite(np.asarray(own.data, dtype=float)[rows]).any():
                continue
            else:
                values = self.fills.setdefault(name, np.full(self.n_samples, np.nan))
            values[rows] = data


def filled(data: np.ndarray, fill: np.ndarray) -> np.ndarray:
    """A curve's values, with the fill's where the curve has none (a new array; neither input is changed)."""
    return np.where(np.isfinite(data), data, fill)
