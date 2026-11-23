"""The analyzer sections: Petrophys's analyzers run on each lithology zone, their classes as depth runs, and a
section rendered as evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from petroharness.well.derived import DerivedCurves
from petroharness.record.analyzers import _ANALYZERS, label_runs, zone_results
from petroharness.record.catalog import Evidence
from petroharness.well.view import FormationView, fmt, fmt_depth, sig

# --- store and index ---------------------------------------------------------------------------------------------

@dataclass
class Run:
    zone: str
    top: float
    base: float
    thickness: float          # the zone's thickness x the share of its samples inside the listed interval

    def depths(self) -> str:
        return fmt_depth(self.top) if round(self.top, 1) == round(self.base, 1) else f"{fmt_depth(self.top)}-{fmt_depth(self.base)}"


@dataclass
class Section:
    family: str
    name: str
    description: str = ""
    methodology: str = ""
    thresholds: str = ""
    classes: dict[str, list[Run]] = field(default_factory=dict)                     # label -> runs, top to base
    values: list[tuple[str, list[tuple[str, Any]]]] = field(default_factory=list)   # summary sections: (zone, fields)

    @property
    def key(self) -> str:
        return f"{self.family}.{self.name}"


@dataclass
class Store:
    view: FormationView
    sections: dict[str, Section]
    curves: list[str]
    background: frozenset[str]
    derived: frozenset[str] = frozenset()        # curves the analyzers derived while classifying, added after all ran

    def zone_ids(self, runs: list[Run]) -> list[str]:
        return list(dict.fromkeys(r.zone for r in runs))


def store_curves(view: FormationView) -> list[str]:
    """Curves with data in the interval, in the well's order; depth and the lithology code curves left out."""
    skip = {"DEPT", "DEPTH", str(view.lithology_curve or "").upper()}
    skip |= {str(c).upper() for c in (view.policy.get("lithology", {}).get("curve") or [])}
    names = list(view.prep.well.curves) + [c for c in view.analyzer_curves if view.prep.well.get(c) is None]
    return [c for c in names if str(c).upper() not in skip and view.available(c)]


def analyzer_sections(view: FormationView) -> tuple[dict[str, Section], DerivedCurves]:
    """Every analyzer family run per lithology zone (evidence.zone_results), read from its result: each section's
    per-sample labels (AnalysisSection.raw_labels) as class runs (label_runs: petrophys flag_intervals), its metadata
    summaries as value sections, and the curves it derived (CategoryAnalysisResult.derived_curves, over the well's
    samples), with a zone's own curves where its well is built apart from the interpreted well (petroharness.well.derived)."""
    sections: dict[str, Section] = {}
    full = view.prep.well
    derived = DerivedCurves(full.n_samples)
    rows = np.flatnonzero(view.mask)
    if getattr(view.prep, "workflow_well", None) is not None:   # zones built apart from the well: their own curves
        for z in view.zones:
            zone = view.zone_well(z)
            derived.add(full, rows[z.indices], {name: zone.get(name) for name in zone.curves})
    for family in _ANALYZERS:
        for z, result in zone_results(view, family):
            derived.add(full, rows[z.indices], result.derived_curves)
            zd = view.depth[z.indices]
            per_sample = z.thickness / max(len(zd), 1)       # a zone's classes add up to its thickness
            for name, section in result.sections.items():
                sec = sections.setdefault(f"{family}.{name}", Section(family, name))
                sec.description = sec.description or str(section.description or "").strip()
                sec.methodology = sec.methodology or str(section.methodology or "").strip()
                sec.thresholds = sec.thresholds or str(section.calculation_thresholds or "").strip()
                for label, runs in label_runs(zd, section.raw_labels).items():
                    for a, b in runs:
                        n = int(((zd >= a) & (zd <= b)).sum())
                        sec.classes.setdefault(label, []).append(Run(z.zone_id, a, b, n * per_sample))
            for name, meta in result.metadata.items():      # summaries per zone (e.g. reservoir_fraction)
                if not isinstance(meta, dict):
                    continue
                sec = sections.setdefault(f"{family}.{name}", Section(family, name))
                fields = [(k, v) for k, v in meta.items() if not isinstance(v, (list, dict)) and v not in (None, "")]
                if fields:
                    sec.values.append((z.zone_id, fields))
    for sec in sections.values():
        for runs in sec.classes.values():
            runs.sort(key=lambda r: r.top)
    return sections, derived


def _total(runs: list[Run]) -> float:
    return float(sum(r.thickness for r in runs))


# --- render ---------------------------------------------------------------------------------------------------------

def _class_line(store: Store, label: str, runs: list[Run], keep: Optional[int]) -> str:
    """One class: run count, total and share of the zoned thickness, largest run, then its runs zone by zone as listed
    (at most `keep` per zone, the thickest, in depth order; keep=0: per-zone totals only)."""
    view = store.view
    total = _total(runs)
    big = max(runs, key=lambda r: r.thickness)
    share = 100 * total / view.zoned_thickness if view.zoned_thickness > 0 else 0.0
    head = (f"{label} ({len(runs)} intervals, {fmt(sig(total, 3))} {view.depth_unit}, {fmt(sig(share, 3))}% of the zoned thickness; "
            f"largest {big.depths()} {view.depth_unit} in {big.zone}" + ("; background class" if label in store.background else "") + ")")
    parts = []
    for zid in store.zone_ids(runs):
        zr = [r for r in runs if r.zone == zid]
        if keep == 0:
            parts.append(f"{zid} {len(zr)} intervals {fmt(sig(_total(zr), 3))} {view.depth_unit}")
            continue
        shown = zr if keep is None or len(zr) <= keep else sorted(sorted(zr, key=lambda r: -r.thickness)[:keep], key=lambda r: r.top)
        more = [r for r in zr if r not in shown]
        tail = f" (+{len(more)} thinner, {fmt(sig(_total(more), 3))} {view.depth_unit})" if more else ""
        parts.append(f"{zid} " + ", ".join(r.depths() for r in shown) + tail)
    return head + ": " + "; ".join(parts)


def basis_line(view: FormationView, basis: dict, derived: frozenset = frozenset()) -> Optional[str]:
    """Where the curve a section's classes rest on has values, and what the classes rest on elsewhere (registry
    curves.section_basis): zones without any value (the analyzer computed the curve again there, or did not assess)
    and samples without one in the other zones (they take the section's default class). A curve the store derived
    after the analyzers ran (derived) was not there for them: the section rests on what it did without it."""
    c = basis["curve"]
    if c in derived:
        return f"basis: {basis['derived']}"
    x = view.values(c) if view.available(c) else None
    if x is None or not np.isfinite(x).any():
        if not any(all(view.available(i) and np.isfinite(view.zone_values(z, i)).any() for i in basis.get("inputs", []))
                   for z in view.zones):
            return None
        return f"basis: no {c} values in this interval: {basis['none']}"
    has = [z.zone_id for z in view.zones if np.isfinite(view.zone_values(z, c)).any()]
    fed = lambda z: all(view.available(i) and np.isfinite(view.zone_values(z, i)).any() for i in basis.get("inputs", []))
    none = [z.zone_id for z in view.zones if z.zone_id not in has and fed(z)]     # computed again from the inputs
    zoned = x[view.zoned]
    share = 100 * float(np.isfinite(zoned).mean()) if zoned.size else 0.0
    text = f"basis: the {c} curve has values in {fmt(sig(share, 3))}% of the zoned samples"
    if none:
        which = ", ".join(none) if len(none) <= 6 else (f"{len(none)} of {len(view.zones)} zones" +
                                                       (f" (all but {', '.join(has)})" if len(has) <= 6 else ""))
        text += f"; {'zone' if len(none) == 1 else 'zones'} {which} {'has' if len(none) == 1 else 'have'} none: {basis['none']}"
    if share < 100 and any(not np.isfinite(view.zone_values(view.zone(z), c)).all() for z in has):
        text += f"; elsewhere a sample without {c} reads as {basis['missing']}"
    return text


def section_evidence(store: Store, key: str, keep_fg: Optional[int], keep_bg: Optional[int]) -> dict:
    sec = store.sections[key]
    facts = []
    if sec.methodology:
        facts.append(f"method: {sec.methodology}")
    if sec.thresholds:
        facts.append(f"thresholds: {sec.thresholds}")
    basis = (store.view.reg.curves.get("section_basis") or {}).get(key)
    line = basis_line(store.view, basis, store.derived) if basis else None
    if line:
        facts.append(line)
    for label, runs in sorted(sec.classes.items(), key=lambda kv: (kv[0] in store.background, -_total(kv[1]))):
        facts.append(_class_line(store, label, runs, keep_bg if label in store.background else keep_fg))
    for zid, fields in sec.values:
        z = store.view.zone(zid)
        vals = "; ".join(f"{k} {fmt(sig(float(v)))}" if isinstance(v, (int, float)) and not isinstance(v, bool)
                         else f"{k}: {v}" for k, v in fields)
        facts.append(f"{zid} ({z.lithology}, {fmt_depth(z.top)}-{fmt_depth(z.base)} {store.view.depth_unit}): {vals}")
    return {"call": "petrophys_section", "args": {"section": key},
            "title": f"{sec.family.capitalize()} analyzer, {sec.name}: {sec.description}", "facts": facts}



# Degradation schedule when the opened readings exceed the render budget: (runs listed per zone for indicator
# classes, for background classes); None = every run as listed, 0 = per-zone totals only.
_KEEP = [(None, None), (None, 4), (None, 0), (8, 0), (4, 0), (2, 0), (1, 0), (0, 0)]



# --- write and guard ------------------------------------------------------------------------------------------------



OBS_CHARS = 14000           # one opened item above this lists fewer class runs per zone


def section_dict(store: "Store", key: str) -> dict:
    """A section's evidence as an open action renders it: the most class runs that fit one observation."""
    d = None
    for keep_fg, keep_bg in _KEEP:
        d = section_evidence(store, key, keep_fg, keep_bg)
        if len(Evidence(id="", **d).render()) <= OBS_CHARS:
            break
    return d
