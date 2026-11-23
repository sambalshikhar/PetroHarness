"""Formation intervals (from the tops) and their lithology zones."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from petroharness.config import DataPaths

MISSING_LITHOLOGY = "NO_LITHOLOGY_DATA"
# Policy keyword (lithology.codes) for the library's built-in lithology code table, which the nomenclature workbook in
# the data paths overrides code by code. Any other value names a YAML file mapping code -> label.
LIBRARY_CODE_TABLE = "library"
# A LAS curve whose mnemonic or description says this is a lithology (or facies) log: how the lithology log is found
# when the user names none (data.lithology_curve).
LITHOLOGY_LOG = re.compile(r"LITH|FACIES", re.IGNORECASE)


def normalize_top_name(name: str) -> str:
    """'Example Fm. Top' -> 'EXAMPLE FM. TOP'."""
    return re.sub(r"\s+", " ", str(name).strip().upper())


def normalize_well(name: str) -> str:
    """'12/3-4' and '12_3-4' -> '12_3-4'."""
    return str(name).strip().replace("/", "_")


@dataclass(frozen=True)
class Interval:
    formation: str
    top: float
    base: Optional[float]          # next top of any rank; None = to the end of the log
    closed: bool = False           # base included: a formation's stated base depth, not the next top

    def contains(self, depth: np.ndarray) -> np.ndarray:
        """The samples in the interval. A depth within a unit conversion's last digits of a limit counts as on it (a
        top given in feet on a log in metres lands a float error off the sample it names once it is converted)."""
        near = lambda x: 1e-9 * max(1.0, abs(x))
        mask = depth >= self.top - near(self.top)
        if self.base is not None:
            tol = near(self.base)
            mask &= (depth <= self.base + tol) if self.closed else (depth < self.base - tol)
        return mask


@lru_cache(maxsize=4)
def _tops_table(tops_csv: str, columns: tuple, name_pattern: Optional[str] = None) -> pd.DataFrame:
    try:
        df = pd.read_csv(tops_csv)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        said = " ".join(str(exc).split()).replace("Error tokenizing data. C error: ", "")
        raise ValueError(f"WHAT: the settings' tops table {Path(tops_csv).name} cannot be read as a table ({said}). "
                         "FIX: give every row the same columns, with a header line naming them (data.tops_columns "
                         "says which are the well, the name and the top).") from exc
    df = df.rename(columns={src: dst for dst, src in columns})
    df["well"] = df["well"].map(normalize_well)
    df["name"] = df["name"].map(normalize_top_name)
    if name_pattern:
        rx = re.compile(name_pattern)
        df = df[df["name"].map(lambda s: bool(rx.search(s)))]
    df = df.dropna(subset=["top"])
    return df[["well", "name", "top"]]


class FormationNotFound(LookupError):
    pass


def resolve_interval(well: str, formation: str, tops_csv: Path, columns: dict[str, str],
                     name_pattern: Optional[str] = None) -> Interval:
    """The named top down to the next deeper top of any rank (the benchmark's interval convention).

    `columns` maps well/name/top to the table's column names and `name_pattern` selects the top names that count
    (None keeps every top): the data paths' `tops_columns` and `top_name_pattern` (see `interval_from_tops`). Depths
    are returned as the table states them; the table records no unit (see DataPaths.tops_depth_unit)."""
    table = _tops_table(str(tops_csv), tuple(columns.items()), name_pattern)
    rows = table[table["well"] == normalize_well(well)]
    if rows.empty:
        raise FormationNotFound(f"no tops for well {well!r} in {tops_csv}")
    name = normalize_top_name(formation)
    hit = rows[rows["name"] == name]
    if hit.empty:
        known = ", ".join(sorted(rows["name"].unique()))
        raise FormationNotFound(f"top {formation!r} not found for well {well!r}; known tops: {known}")
    if len(hit) > 1:                                 # as the tops-file reader reads a name listed twice
        at = ", ".join(f"{float(t):g}" for t in sorted(hit["top"]))
        raise ValueError(f"WHAT: the settings' tops table {Path(tops_csv).name} lists {name} {len(hit)} times for well "
                         f"{well!r} (tops at {at}). WHY: a name listed more than once is not one stretch. FIX: give the "
                         "interval by its depths (--top and --base), or give each listing its own name in the table.")
    top = float(hit["top"].min())
    deeper = sorted(t for t in rows["top"].unique() if t > top)
    return Interval(formation=name, top=top, base=float(deeper[0]) if deeper else None)


def interval_from_tops(well: str, formation: str, data: "DataPaths") -> Interval:
    """`resolve_interval` with the tops table, column names and top-name pattern of the data paths (DataPaths)."""
    return resolve_interval(well, formation, data.tops_csv, data.tops_columns, data.top_name_pattern)


def cell_span(top: float, base: float, n: int) -> float:
    """The thickness of n samples from top to base (the first and last sample's depths): base - top, or under the
    cell_thickness switch n steps of regular sampling, as Petrophys counts thickness (each sample its own cell)."""
    from petroharness import options
    span = base - top
    return span * n / (n - 1) if n > 1 and options.get().cell_thickness else span


@dataclass
class Zone:
    zone_id: str          # e.g. "Z3"
    name: str             # e.g. "CROSSBEDDED SAND_GROUP_2" (lithology + run number)
    lithology: str
    top: float            # first sample depth
    base: float           # last sample depth
    n_samples: int
    indices: np.ndarray = field(repr=False)
    stated: str = ""      # the formation's lithology as its tops state it, where the lithology log reads another

    @property
    def thickness(self) -> float:
        """First to last sample; under cell_thickness, Petrophys's rule: each sample its own cell (n samples, n steps)."""
        return cell_span(self.top, self.base, self.n_samples)


@lru_cache(maxsize=4)
def lithology_names(nomenclature_xlsx: Optional[str] = None, code_column: Optional[str] = None,
                    label_column: Optional[str] = None) -> dict[int, str]:
    """Code -> label. The field nomenclature workbook wins (its `code_column` holds the numeric code, `label_column`
    the label: DataPaths.lithology_columns); the library's built-in table fills any code the workbook lacks."""
    from petrophys.evaluation.diagnostics.lithology_analysis import GROUND_TRUTH_NAMES

    names = {int(k): str(v) for k, v in GROUND_TRUTH_NAMES.items()}
    if nomenclature_xlsx and Path(nomenclature_xlsx).exists():
        sheet = pd.read_excel(nomenclature_xlsx)
        missing = [c for c in (code_column, label_column) if c is None or c not in sheet.columns]
        if missing:
            raise ValueError(f"WHAT: the lithology workbook {Path(nomenclature_xlsx).name} has no column(s) {missing} "
                             f"(it has {list(map(str, sheet.columns))}). WHY: its codes and labels decode the lithology "
                             "log. FIX: set data.lithology_columns (code, label) to the workbook's column names.")
        for code, label in zip(sheet[code_column], sheet[label_column]):
            if pd.notna(code) and pd.notna(label):
                names[int(round(float(code)))] = str(label).strip()
    return {k: re.sub(r"\s+", " ", v.upper()) for k, v in names.items()}


def lithology_table(data: "DataPaths") -> dict[int, str]:
    """The library's built-in code table overridden by the data paths' nomenclature workbook (DataPaths)."""
    workbook = data.lithology_nomenclature
    return lithology_names(str(workbook) if workbook else None, data.lithology_columns.code,
                           data.lithology_columns.label)


def decode_lithology(codes: Optional[np.ndarray], n: int, names: Optional[dict[int, str]] = None) -> np.ndarray:
    """Lithology codes -> upper-case display labels from a code table (default: the library's built-in table;
    the harness passes `lithology_table(data)` or the policy's YAML table)."""
    if codes is None:
        return np.asarray([MISSING_LITHOLOGY] * n, dtype=object)
    names = names or lithology_names()
    out = []
    for value in np.asarray(codes, dtype=float):
        label = names.get(int(round(value))) if np.isfinite(value) and value >= 0 else None
        out.append(label or MISSING_LITHOLOGY)
    return np.asarray(out, dtype=object)


def segment_zones(depth: np.ndarray, labels: np.ndarray, min_zone_thickness_m: float = 2.0) -> list[Zone]:
    """Contiguous label runs; keep runs strictly thicker than the minimum."""
    if depth.size == 0:
        return []
    change = np.ones(labels.size, dtype=bool)
    change[1:] = labels[1:] != labels[:-1]
    run_ids = np.cumsum(change)
    counters: dict[str, int] = {}
    zones: list[Zone] = []
    for rid in np.unique(run_ids):
        idx = np.flatnonzero(run_ids == rid)
        lith = str(labels[idx[0]])
        counters[lith] = counters.get(lith, 0) + 1
        top, base = float(depth[idx[0]]), float(depth[idx[-1]])
        if not (base - top > min_zone_thickness_m):
            continue
        zones.append(Zone(
            zone_id=f"Z{len(zones) + 1}",
            name=f"{lith}_GROUP_{counters[lith]}",
            lithology=lith,
            top=round(top, 4),
            base=round(base, 4),
            n_samples=int(idx.size),
            indices=idx,
        ))
    return zones


def formation_zone(depth: np.ndarray, labels: np.ndarray, stated: str = None) -> list[Zone]:
    """data.zone_layout "formation": the whole interval as one zone, every sample in it, labelled by the majority
    lithology of the samples that have one (the lithology log is read sample by sample, as every curve is), else by
    the formation's lithology the data states (its tops), else MISSING_LITHOLOGY. A stated lithology the log does not
    read is kept on the zone (Zone.stated), so both readings reach the answer."""
    if depth.size == 0:
        return []
    known = [str(x) for x in labels if str(x) != MISSING_LITHOLOGY]
    said = str(stated).strip().upper() if stated and str(stated).strip() else ""
    if known:
        values, counts = np.unique(np.asarray(known, dtype=object), return_counts=True)
        lith = str(values[int(np.argmax(counts))])
    else:
        lith = said or MISSING_LITHOLOGY
    idx = np.arange(depth.size)
    return [Zone(zone_id="Z1", name=f"{lith}_GROUP_1", lithology=lith, top=round(float(depth[0]), 4),
                 base=round(float(depth[-1]), 4), n_samples=int(idx.size), indices=idx,
                 stated=said if said and said != lith.upper() else "")]


def lithology_candidates(named) -> list[str]:
    """The lithology-log mnemonics the user names (data.lithology_curve): one, a list (wells that name the log
    differently), or none."""
    names = [] if named is None else [named] if isinstance(named, str) else list(named)
    bad = [c for c in names if not isinstance(c, str) or not c.strip()]
    if bad:
        raise ValueError(f"WHAT: data.lithology_curve has entries {bad!r} that are not curve mnemonics. WHY: the "
                         "lithology log is chosen by mnemonic. FIX: give one mnemonic, a list of them, or null.")
    return names


def find_lithology_curve(curve: Callable[[str], Optional[np.ndarray]], las_curves: list[str],
                         describe: Callable[[str], str] = lambda c: "", named=None) -> Optional[str]:
    """The well's lithology log. Named (data.lithology_curve): the first of those mnemonics the well has with data.
    Not named: the LAS's own curve (las_curves: never one the workflow computed) whose mnemonic or description says it
    is a lithology or facies log (LITHOLOGY_LOG) and whose values are integer codes. None: no lithology log, and the
    zones come from the lithology Petrophys's mineral solver wrote (solver_lithology), else from shale-volume bands.
    Two such curves and none named is an error that names them.
    `curve` returns a curve's data by mnemonic (None when the well lacks it); `describe` its LAS description."""
    def has(name):
        data = curve(name)
        return data is not None and bool(np.isfinite(np.asarray(data, dtype=float)).any())

    names = lithology_candidates(named)
    if names:
        return next((c for c in names if has(c)), None)
    found = []
    for name in las_curves:
        if not (LITHOLOGY_LOG.search(name) or LITHOLOGY_LOG.search(describe(name) or "")) or not has(name):
            continue
        x = np.asarray(curve(name), dtype=float)
        x = x[np.isfinite(x) & (x >= 0)]
        if x.size and np.allclose(x, np.round(x)):
            found.append(name)
    if len(found) > 1:
        raise ValueError(f"WHAT: this LAS has several lithology logs ({', '.join(found)}). WHY: the zones come from "
                         "one. FIX: name it in data.lithology_curve.")
    return found[0] if found else None


def solver_lithology(steps: dict, well) -> Optional[dict]:
    """The lithology Petrophys's workflow solved when the well had no lithology log: its lithology step's code curve
    (the output that carries Petrophys's category labels: the mineral solver's dominant mineral per sample) with its
    code table (code -> upper-case label; Petrophys's "unknown", a sample the solver could not call, is no
    lithology), and how the step made it as its record says (method, domain, input curves, decisions, samples
    solved). None: the step wrote no such curve, or it has no value."""
    step = (steps or {}).get("lithology") or {}
    params = step.get("parameters") or {}
    if not params.get("lithology_curve_written"):
        return None
    for name in step.get("outputs") or []:
        c = well.get(name) if well is not None else None
        labels = ((getattr(getattr(c, "metadata", None), "custom", None) or {}).get("category_labels")
                  if c is not None else None)
        if not labels or not np.isfinite(np.asarray(c.data, dtype=float)).any():
            continue
        from petroharness.well.prepare import lithology_domain
        table = {int(k): (MISSING_LITHOLOGY if str(v).strip().lower() == "unknown" else str(v).upper())
                 for k, v in labels.items()}
        net_pay = ((steps or {}).get("net_pay") or {}).get("parameters") or {}
        return {"curve": name, "table": table, "method": str(step.get("method") or ""),
                "domain": str(params.get("lithology_domain") or lithology_domain(net_pay)),
                "inputs": [str(x) for x in step.get("inputs") or []],
                "decisions": [str(x) for x in step.get("decisions") or []],
                "solved": params.get("multi_mineral_solved_samples"), "samples": params.get("multi_mineral_total_samples")}
    return None


def vcl_band_labels(vcl: np.ndarray, bands=(0.3, 0.6)) -> np.ndarray:
    """Fallback labels when a well has neither a lithology log nor a solved lithology: shale-volume bands."""
    lo, hi = bands
    out = np.full(vcl.shape, MISSING_LITHOLOGY, dtype=object)
    ok = np.isfinite(vcl)
    out[ok & (vcl < lo)] = "CLEAN (VCL BAND)"
    out[ok & (vcl >= lo) & (vcl < hi)] = "SHALY (VCL BAND)"
    out[ok & (vcl >= hi)] = "SHALE-PRONE (VCL BAND)"
    return out
