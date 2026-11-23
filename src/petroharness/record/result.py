"""What every computation of the record shares: its result (Evidence), its refusal (EvidenceError) and the runs
of a flag over depth."""

from __future__ import annotations

from typing import Any, Union
import numpy as np
from pydantic import BaseModel, Field
from petroharness.well.view import fmt


class EvidenceError(ValueError):
    pass


class Evidence(BaseModel):
    id: str
    call: str
    args: dict[str, Any]
    title: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Union[str, float, int, None]]] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)   # every number shown, for the verifier
    coefficients: list[tuple[float, int]] = Field(default_factory=list)   # sample-level coefficients shown, with n
    runs: list[dict[str, Any]] = Field(default_factory=list)   # flagged_runs: every run, for the code-composed block

    def render(self) -> str:
        out = [f"[{self.id}] {self.title}"]
        if self.columns:
            out.append(" | ".join(self.columns))
            for r in self.rows:
                out.append(" | ".join("n/a" if v is None else (fmt(v) if isinstance(v, float) else str(v)) for v in r))
        out.extend(f"- {f}" for f in self.facts)
        return "\n".join(out)


def flag_runs(depth: np.ndarray, flag: np.ndarray) -> list[tuple[int, int]]:
    """The flagged runs as (first, last) sample indices, from petrophys evaluation.intervals.flag_intervals
    (consecutive flagged samples, never joined across a depth gap of more than 1.5 sampling steps). The library
    reports each run's cell boundaries; the harness shows the first and last flagged samples, like its zones."""
    from petrophys.evaluation.intervals import flag_intervals as library_intervals

    depth = np.asarray(depth, dtype=float)
    on = np.isfinite(np.asarray(flag, dtype=float)) & (np.asarray(flag, dtype=float) > 0.5)
    if not on.any():
        return []
    out = []
    for top, bottom in zip(*library_intervals(on, depth)[["top", "bottom"]].to_numpy().T):
        idx = np.flatnonzero(on & (depth >= top) & (depth <= bottom))
        out.append((int(idx[0]), int(idx[-1])))
    return out


def _runs(depth: np.ndarray, flag: np.ndarray, step: float = 0.0) -> list[tuple[float, float]]:
    """The flagged runs as (first, last) sample depths (flag_runs)."""
    return [(float(depth[a]), float(depth[b])) for a, b in flag_runs(depth, flag)]
