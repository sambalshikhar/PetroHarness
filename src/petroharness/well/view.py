"""A formation-scoped view over a prepared well: the interval's samples, zones, curve access, formatting."""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

import numpy as np

from petroharness.well.calculations import as_context_group
from petroharness.config import HarnessConfig
from petroharness.tasks import Task
from petroharness.well.derived import filled
from petroharness.well.formation import (LIBRARY_CODE_TABLE, Interval, Zone, decode_lithology, interval_from_tops,
                                    lithology_table, normalize_top_name, find_lithology_curve, formation_zone, segment_zones,
                                    vcl_band_labels)
from petroharness.registry import Registry, load as load_registry
from petroharness.well.prepare import PreparedWell, load_policy, prepare_well, read_depth

def _metres_factor(unit) -> Optional[float]:
    """Metres per unit of depth (petrophys normalize_depth_unit reads the spelling, UnitRegistry.DEPTH_TO_M gives the
    factor); None for a spelling the library does not know as a depth unit."""
    from petrophys.model.units import UnitRegistry, normalize_depth_unit

    canonical = normalize_depth_unit(str(unit or ""), strict=False)
    return UnitRegistry.DEPTH_TO_M.get(canonical) if canonical in ("m", "ft") else None


def metres_per(unit: str, source: str) -> float:
    """Metres per unit of depth; an unknown unit is refused (its depths could not be shown in metres)."""
    factor = _metres_factor(unit)
    if factor is None:
        raise ValueError(f"WHAT: {source} depth unit is {unit!r}, not a length unit this harness knows (m or ft). "
                         "WHY: thicknesses, zone limits and every depth on the card would be mislabelled. FIX: give the "
                         "depth in metres or feet (e.g. DEPT.M or DEPT.F in the LAS ~Curve section).")
    return factor


def check_depth_unit(prep: PreparedWell, policy: dict) -> float:
    """Metres per depth unit of the prepared well. A LAS that states no unit is taken to be in the policy's unit
    (the readers report one); an unknown unit is refused."""
    want = str(policy.get("depth_unit", "m"))
    unit = str(getattr(prep.well, "depth_unit", "") or "").strip() or want
    return metres_per(unit, "the LAS")


def reporting_unit(wanted: Optional[str], prep: PreparedWell) -> tuple[str, float]:
    """(label, metres per unit) of the unit every depth, thickness and zone limit is shown in: a unit name (m or ft),
    or "las" for the well's own depth unit."""
    from petrophys.model.units import normalize_depth_unit

    wanted = str(wanted or "m").strip()
    if wanted.lower() == "las":
        own = str(getattr(prep.well, "depth_unit", "") or "").strip() or "m"
        label = normalize_depth_unit(own, strict=False)
        return label, metres_per(own, "the LAS")
    return normalize_depth_unit(wanted, strict=False), metres_per(wanted, "the reporting")


@functools.lru_cache(maxsize=256)
def las_curve_descriptions(las_path: str) -> dict:
    """{mnemonic: description} the LAS header states for its curves (the provider's own words; read without the data,
    once per file)."""
    import lasio

    las = lasio.read(str(las_path), ignore_data=True)
    return {str(c.mnemonic).upper(): str(c.descr or "").strip() for c in las.curves if str(c.descr or "").strip()}


def las_depth_unit(las_path: Path) -> str:
    """The depth unit the LAS header states for its index curve ("" if it states none), read without the data."""
    import lasio

    las = lasio.read(str(las_path), ignore_data=True)
    return str(las.curves[0].unit or "").strip() if len(las.curves) else ""


def _scaled(interval: Interval, factor: float) -> Interval:
    if factor == 1.0:
        return interval
    return replace(interval, top=interval.top * factor, base=None if interval.base is None else interval.base * factor)


def _prepare_in_metres(task: Task, policy: dict, cfg: HarnessConfig) -> tuple[PreparedWell, Interval, float, str, float]:
    """The interpreted well (in its LAS depth unit), the task's interval in the reporting unit, reporting units per LAS
    depth unit, and the reporting unit (label, metres per unit): data.depth_unit, else the policy's depth_unit.

    An explicit task interval is in metres (Task.top/base). A tops table records no unit: its depths are in
    data.tops_depth_unit or, when that is unset, assumed to be in the LAS's own unit (tops are normally picked on the
    logs' depth index)."""
    las = Path(task.las_path)
    if task.top is not None:
        interval = Interval(formation=normalize_top_name(task.formation), top=float(task.top), base=task.base,
                            closed=task.base_closed)
        unit = None if task.depth_unit == "las" else (task.depth_unit or "m")
    elif cfg.data.tops_csv is None:
        raise ValueError(f"WHAT: the task names formation {task.formation!r} without its depths and no tops table is "
                         "set. WHY: the interval comes from the formation info or the tops. FIX: give the formation's "
                         "top and base with the task, or set data.tops_csv.")
    else:
        interval, unit = interval_from_tops(task.well, task.formation, cfg.data), cfg.data.tops_depth_unit
    stated, las_interval = None, interval
    if unit is not None:
        # prepare_well slices a formation-scope interpretation in the LAS's unit: give it the interval in that unit.
        stated = las_depth_unit(las)
        las_interval = _scaled(interval, metres_per(unit, "the interval's") / metres_per(stated, f"{las.name}'s"))
    prep = prepare_well(las, policy, las_interval, cfg.data.cache_dir, cfg.data.engines_dir, cfg.data.lithology_curve,
                        interpreter=cfg.data.interpreter, interpret=cfg.data.interpret)
    scale = check_depth_unit(prep, policy)
    if scale != 1.0:
        # The LAS readers take a file without a depth unit to be in feet: convert only a unit the file states.
        stated = las_depth_unit(las) if stated is None else stated
        if _metres_factor(stated) != scale and not _converted_depths(las, prep, stated, scale):
            states = f"states depth unit {stated!r}" if stated else "states no depth unit"
            raise ValueError(f"WHAT: {las.name} {states} but was read as {prep.well.depth_unit!r}. WHY: its depths "
                             "would be converted with the wrong factor. FIX: state the index curve's unit in the LAS "
                             "~Curve section (e.g. DEPT.M or DEPT.F).")
    label, rep_m = reporting_unit(cfg.data.depth_unit or policy.get("depth_unit", "m"), prep)
    to_rep = (scale if unit is None else metres_per(unit, "the interval's")) / rep_m
    return prep, _scaled(interval, to_rep), scale / rep_m, label, rep_m


def _converted_depths(las: Path, prep: PreparedWell, stated: str, scale: float) -> bool:
    """Whether the prepared well's depths are the LAS's own converted from the unit the LAS states to the unit the
    well states (an interpretation that reports the well in another unit, e.g. a context profile in its package's),
    not the LAS's depths under another unit's name."""
    from_las = _metres_factor(stated)
    if from_las is None:
        return False
    las_depth = read_depth(las)
    return las_depth.shape == prep.depth.shape and bool(np.allclose(las_depth * from_las / scale, prep.depth,
                                                                     rtol=1e-6, atol=1e-3, equal_nan=True))


def sig(x: float, figures: int = 4) -> float:
    """Round to significant figures (the display precision of record)."""
    if x is None or not np.isfinite(x) or x == 0:
        return x
    return round(float(x), figures - 1 - int(math.floor(math.log10(abs(x)))))


def fmt(x: float, figures: int = 4) -> str:
    if x is None or not np.isfinite(x):
        return "n/a"
    v = sig(x, figures)
    if abs(v) < 1e-3:
        return f"{v:.4f}".rstrip("0").rstrip(".") if round(v, 4) != 0 else "0"
    text = f"{v:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


def fmt_depth(x: float) -> str:
    return f"{x:.1f}"


def fmt_pct(p: float, decimals: int = 0, sign: bool = True) -> str:
    """A percentage for display. A nonzero share that would round to zero shows as "<1%" (or "<0.1%"): a rock type,
    flag or class present in a few samples is not absent, and "0%" would say it is."""
    if p is None or not np.isfinite(p):
        return "n/a"
    text = f"{p:.{decimals}f}"
    if p > 0 and float(text) == 0:
        text = "<" + (f"{10 ** -decimals:.{decimals}f}" if decimals else "1")
    return text + ("%" if sign else "")


@dataclass
class FormationView:
    """One formation in one well. Depths (`depth`, `interval`, zones) are in the reporting unit (`report_unit`, metres by default);
    `prep` keeps the interpreted well in its LAS unit and `depth_scale` converts it."""

    task: Task
    prep: PreparedWell
    interval: Interval
    mask: np.ndarray
    zones: list[Zone]
    policy: dict
    labels: np.ndarray            # decoded lithology label per interval sample
    reg: Registry = field(default_factory=load_registry)   # domain knowledge (rules/*.yaml)
    lithology_curve: Optional[str] = None        # the lithology log the zones come from (None: no lithology log)
    vcl_bands: Optional[tuple[float, float]] = None   # set when the zones are shale-volume bands instead
    code_table: dict[int, str] = field(default_factory=dict)   # the policy's lithology code table (code -> label)
    depth_scale: float = 1.0      # reporting units per LAS depth unit (0.3048 for a LAS in feet shown in metres)
    report_unit: str = "m"        # the unit every depth, thickness and zone limit is shown in (data.depth_unit / policy)
    m_per_unit: float = 1.0       # metres per reporting unit (thresholds stated in metres are converted with it)
    # curves the analyzers computed while classifying (src/petroharness/record/store.py), name -> (values over the well's samples, unit):
    # readable like any curve, never added to the workflow's well, so the card and every analyzer run see only the
    # workflow's curves (as petrophys runs them)
    analyzer_curves: dict = field(default_factory=dict)
    # workflow curves the analyzers computed in zones where the workflow left them empty (src/petroharness/record/store.py,
    # petroharness.well.derived), name -> values over the well's samples: values() reads them only where the workflow's
    # curve has no value
    analyzer_fills: dict = field(default_factory=dict)
    # curves Petrophys calculated during the question on the model's request (agent/library.py: calculate), name ->
    # values over the well's samples; read like the workflow's own curves
    calculated: dict = field(default_factory=dict)

    @classmethod
    def build(cls, task: Task, cfg: Optional[HarnessConfig] = None) -> "FormationView":
        cfg = cfg or HarnessConfig()
        policy = load_policy(cfg.resources.policy_file)
        prep, interval, scale, unit, rep_m = _prepare_in_metres(task, policy, cfg)
        depth = prep.depth * scale if scale != 1.0 else prep.depth
        mask = interval.contains(depth)
        if cfg.data.zone_layout == "formation" and interval.base is not None and depth.size > 1:
            # the formation's samples as its context holds them: within half a step of its top and base (absorbs a
            # unit conversion's last digits; the default layout is unchanged)
            half = 0.5 * float(np.nanmedian(np.abs(np.diff(depth))))
            mask = (depth >= interval.top - half) & (depth <= interval.base + half)
        scheme = policy.get("lithology", {}).get("codes", LIBRARY_CODE_TABLE)
        if scheme == LIBRARY_CODE_TABLE:
            table = lithology_table(cfg.data)
        else:                                     # a YAML file mapping code -> label
            import yaml
            table = {int(k): str(v).upper() for k, v in yaml.safe_load(Path(scheme).read_text()).items()}
        if "curve" in (policy.get("lithology") or {}):
            raise ValueError("WHAT: the policy names a lithology curve (lithology.curve). WHY: which LAS curve is the "
                             "lithology log belongs to the data, not to the interpretation policy. FIX: remove it from "
                             "the policy; name the curve in data.lithology_curve, or leave it null to detect it.")
        describe = lambda c: str(getattr(prep.well.get(c), "description", "") or "")
        curve = find_lithology_curve(prep.curve, list(prep.input_curves), describe, cfg.data.lithology_curve)
        bands = None
        if curve is None and prep.curve("VCL") is not None:
            # No lithology log in this LAS: zones from shale-volume bands (policy zones.fallback_vcl_bands).
            bands = tuple(float(b) for b in policy["zones"].get("fallback_vcl_bands", (0.3, 0.6)))
            labels = vcl_band_labels(prep.curve("VCL")[mask], bands)
        else:
            labels = decode_lithology(None if curve is None else prep.curve(curve)[mask], int(mask.sum()), names=table)
        if cfg.data.zone_layout == "formation":           # the data's context: one group per formation
            zones = formation_zone(depth[mask], labels, getattr(task, "formation_lithology", None))
        else:
            zones = segment_zones(depth[mask], labels, policy["zones"]["min_thickness_m"] / rep_m)
        return cls(task=task, prep=prep, interval=interval, mask=mask, zones=zones, policy=policy, labels=labels,
                   reg=load_registry(cfg.resources.rules_dir), lithology_curve=curve, vcl_bands=bands,
                   code_table=table, depth_scale=scale, report_unit=unit, m_per_unit=rep_m)

    @property
    def depth_unit(self) -> str:
        """The unit of every depth the view returns (the reporting unit)."""
        return self.report_unit

    def to_unit(self, metres: float) -> float:
        """A length stated in metres (a policy or catalog threshold), in the reporting unit."""
        return metres / self.m_per_unit if self.m_per_unit != 1.0 else metres

    # -- sample access -------------------------------------------------------------------------
    @property
    def depth(self) -> np.ndarray:
        """Interval sample depths in metres."""
        d = self.prep.depth[self.mask]
        return d * self.depth_scale if self.depth_scale != 1.0 else d

    @property
    def step(self) -> float:
        d = self.depth
        return float(np.median(np.diff(d))) if d.size > 1 else 0.0

    def values(self, curve: str) -> Optional[np.ndarray]:
        """The curve over the interval (own_values), with the analyzers' values where the workflow left it empty."""
        data, fill = self.own_values(curve), self.analyzer_fills.get(curve)
        return data if data is None or fill is None else filled(data, fill[self.mask])

    def own_values(self, curve: str) -> Optional[np.ndarray]:
        """The curve over the interval as the workflow has it (else the analyzers' own curve), without the fills."""
        data = self.prep.curve(curve)
        if data is None and curve in self.analyzer_curves:
            data = self.analyzer_curves[curve][0]
        if data is None:
            data = self.calculated.get(curve)
        return None if data is None else data[self.mask]

    def well_values(self, curve: str) -> Optional[np.ndarray]:
        """The curve over all the well's samples, not only the interval's (with the analyzers' fills): what the curve's
        values are (summary.curve_kind) is read on these."""
        data = self.prep.curve(curve)
        if data is None and curve in self.analyzer_curves:
            data = self.analyzer_curves[curve][0]
        if data is None:
            data = self.calculated.get(curve)
        fill = self.analyzer_fills.get(curve)
        return data if data is None or fill is None else filled(data, fill)

    def zone_values(self, zone: Zone, curve: str) -> Optional[np.ndarray]:
        data = self.values(curve)
        return None if data is None else data[zone.indices]

    def available(self, curve: str) -> bool:
        data = self.values(curve)
        return data is not None and bool(np.isfinite(data).any())

    def resolve_curves(self, curves: list) -> list:
        """Curve arguments as mnemonics. A measured-log family name (rules/curves.yaml families, e.g. "sonic") stands
        for that family's curves present here, and "measured" for every measured log present, family by family, so a
        broad statistics question can get each log family (caliper, every sonic, density, neutron, resistivities, GR,
        PEF) without the planner knowing each LAS's mnemonics. Other items pass through unchanged (the same list
        object when there is no family name)."""
        families = self.reg.curves.get("families", {}) or {}
        key = lambda c: str(c).strip().lower().replace("_", " ")
        if not any(isinstance(c, str) and (key(c) == "measured" or key(c) in families) for c in curves):
            return curves
        out = []
        for c in curves:
            k = key(c) if isinstance(c, str) else None
            if k == "measured":
                out += [m for members in families.values() for m in members if self.available(m)]
            elif k in families:
                out += [m for m in families[k] if self.available(m)]
            else:
                out.append(c)
        return list(dict.fromkeys(out))

    def in_percent(self, curve: str) -> bool:
        """Whether a fraction-type core curve is stored in percent (rules/curves.yaml core.fraction_groups): petrophys
        core_saturation_to_fraction reads a curve of its group as percent (a percent unit, or values that only percent
        explains). Core analyses report saturations either way whatever the LAS unit header says; an unknown unit
        label is left to the values."""
        from petrophys.model.units import core_saturation_to_fraction

        for group in (self.reg.curves.get("core", {}) or {}).get("fraction_groups", []) or []:
            if curve in group:
                for c in group:
                    whole = self.prep.curve(c)
                    if whole is None or not np.isfinite(whole).any():
                        continue
                    try:
                        _, record = core_saturation_to_fraction(whole, self.unit(c), mnemonic=c)
                    except ValueError:
                        _, record = core_saturation_to_fraction(whole, None, mnemonic=c)
                    if record["reason"] in ("declared_percent", "inferred_percent"):
                        return True
        return False

    def family(self, curve: str) -> Optional[str]:
        """The measured-log family of a mnemonic (rules/curves.yaml families), None when it is in none."""
        return next((f for f, members in (self.reg.curves.get("families", {}) or {}).items() if curve in members), None)

    @property
    def zoned(self) -> np.ndarray:
        """Interval samples inside the lithology zones. The others are thin runs and transitions between zones,
        which formation statistics and QC baselines leave out (they mix two rock types)."""
        out = np.zeros(int(self.mask.sum()), dtype=bool)
        for z in self.zones:
            out[z.indices] = True
        return out

    def good_hole(self) -> np.ndarray:
        """Interval samples the bad-hole flag passes (BAD_HOLE = 0). Without a BAD_HOLE curve every sample passes;
        a sample whose flag is missing does not (its hole condition is unknown)."""
        bh = self.values("BAD_HOLE")
        if bh is None or not np.isfinite(bh).any():
            return np.ones(int(self.mask.sum()), dtype=bool)
        return np.isfinite(bh) & (bh <= 0.5)

    def at_bound(self, curve: str, min_count: int = 3, min_fraction: float = 0.005) -> np.ndarray:
        """Interval samples held at a model or tool limit: the curve's interval minimum or maximum when several samples
        share that exact value (a clip piles samples up at the bound: SW at 1, PHIE or VCL at 0, PERM at its clip),
        and samples the value-range QC clipped. Such samples do not follow the curve's inputs, so a sample
        correlation over them measures the clip, not the rock. Flag curves have no bounds in this sense."""
        x = self.values(curve)
        out = np.zeros(int(self.mask.sum()), dtype=bool)
        if x is None or curve in self.reg.flags:
            return out
        fin = np.isfinite(x)
        if not fin.any():
            return out
        need = max(min_count, int(np.ceil(min_fraction * fin.sum())))
        for bound in (np.nanmin(x), np.nanmax(x)):
            hit = fin & (x == bound)
            if hit.sum() >= need:
                out |= hit
        qc = getattr(self.prep, "value_qc", None) or {}
        rule, changed = (qc.get("rules") or {}).get(curve) or {}, (qc.get("changed") or {}).get(curve)
        if rule.get("action") == "clip" and changed is not None and np.shape(changed) == np.shape(self.mask):
            out |= np.asarray(changed, dtype=bool)[self.mask]
        return out

    def unit(self, curve: str) -> str:
        if self.prep.well.get(curve) is None and curve in self.analyzer_curves:
            return self.analyzer_curves[curve][1]
        return self.prep.unit(curve)

    def zone(self, ref: str) -> Optional[Zone]:
        for z in self.zones:
            if ref in (z.zone_id, z.name):
                return z
        return None

    @property
    def top(self) -> float:
        return float(self.depth.min())

    @property
    def base(self) -> float:
        return float(self.depth.max())

    @property
    def gross(self) -> float:
        return self.base - self.top

    @property
    def zoned_thickness(self) -> float:
        return float(sum(z.thickness for z in self.zones))

    def zone_well(self, zone: Zone):
        """The petrophys Well restricted to exactly the zone's samples (index-based, no depth rounding), with its
        depths in metres like the rest of the view (the analyzers report depth ranges that reach the evidence). A context
        profile's interpretation (PreparedWell.workflow_well): the zone as the profile's package builds each group, the
        workflow's samples with the interpretation's QC and recomputation (calculations.as_context_group)."""
        rows = np.flatnonzero(self.mask)[zone.indices]
        workflow = getattr(self.prep, "workflow_well", None)
        if workflow is None:
            return self._sub_well(rows)
        sub = self._sub_well(rows, workflow)
        as_context_group(sub, (self.prep.value_qc or {}).get("rules") or {}, self.prep.context_profile)
        return sub

    def interval_well(self):
        """The petrophys Well restricted to exactly the interval's samples, depths in metres (as zone_well)."""
        return self._sub_well(np.flatnonzero(self.mask))

    def _sub_well(self, rows: np.ndarray, full=None):
        """The workflow's well (or `full`, a well on the same samples) restricted to the given samples (petrophys
        Well.select), depths in metres."""
        full = self.prep.well if full is None else full
        mask = np.zeros(full.n_samples, dtype=bool)
        mask[rows] = True
        sub = full.select(mask)
        if self.depth_scale != 1.0:
            sub.depth, sub.depth_unit = np.asarray(sub.depth) * self.depth_scale, self.depth_unit
        return sub
