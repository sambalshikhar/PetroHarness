"""Curve statistics from Petrophys (evaluation.summaries.curve_statistics)."""

from __future__ import annotations

import numpy as np
from petrophys.evaluation.summaries import curve_statistics as _library_statistics, percentile_key

# harness name -> petrophys name
LIBRARY_NAMES = {"mean": "arithmetic_mean", "min": "minimum", "max": "maximum", "median": "median", "p50": "median",
                 "std": "standard_deviation", "var": "variance", "geometric_mean": "geometric_mean",
                 "harmonic_mean": "harmonic_mean", "third_power_average": "third_power_average", "mode": "mode"}
PERCENTILES = {"p10": 10, "p25": 25, "p75": 75, "p90": 90}


def statistics(x, names) -> dict[str, float]:
    """The named statistics of the finite samples of x, and n (the sample count); empty without a finite sample.
    Names: LIBRARY_NAMES, PERCENTILES, iqr (p75 - p25) and max_abs (the larger of |min| and |max|)."""
    names = list(names)
    wanted = {PERCENTILES[n] for n in names if n in PERCENTILES} | ({25, 75} if "iqr" in names else set())
    s = _library_statistics(np.asarray(x, dtype=float), percentiles=sorted(wanted))
    if s is None:
        return {}
    out = {}
    for n in names:
        if n in LIBRARY_NAMES:
            out[n] = s[LIBRARY_NAMES[n]]
        elif n in PERCENTILES:
            out[n] = s[percentile_key(PERCENTILES[n])]
        elif n == "iqr":
            out[n] = s[percentile_key(75)] - s[percentile_key(25)]
        elif n == "max_abs":
            out[n] = max(abs(s["minimum"]), abs(s["maximum"]))
        else:
            raise KeyError(n)
    return {k: float(v) for k, v in out.items()} | {"n": int(s["count"])}


def statistic(x, name: str) -> float:
    """One statistic of the finite samples of x (NaN without a finite sample)."""
    return statistics(x, [name]).get(name, float("nan"))


def percentile(x, q: float) -> float:
    """The q-th percentile of the finite samples of x, as Petrophys computes every percentile the tools show (NaN
    without a finite sample)."""
    s = _library_statistics(np.asarray(x, dtype=float), percentiles=[q])
    return float(s[percentile_key(q)]) if s is not None else float("nan")
