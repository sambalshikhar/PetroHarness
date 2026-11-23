"""The workflow's analyzers, run on a view: their sections and classes per zone (Petrophys's analyzers, imported by
name at run time), the label runs, the section summaries and each sample's label."""

from __future__ import annotations

from typing import Any
import numpy as np
from petroharness.well.calculations import calculations
from petroharness.well.view import FormationView, fmt, fmt_depth, sig
from petroharness.record.result import EvidenceError, flag_runs


_ANALYZERS = {
    "hydrocarbon": ("petrophys.evaluation.diagnostics.hydrocarbon_analysis", "HydrocarbonAnalysis"),
    "saturation": ("petrophys.evaluation.diagnostics.saturation_analysis", "SaturationAnalysis"),
    "permeability": ("petrophys.evaluation.diagnostics.permeability_analysis", "PermeabilityAnalysis"),
    "porosity": ("petrophys.evaluation.diagnostics.porosity_analysis", "PorosityAnalysis"),
    "lithology": ("petrophys.evaluation.diagnostics.lithology_analysis", "LithologyAnalysis"),
    "numerical": ("petrophys.evaluation.diagnostics.numerical_statistical_analysis", "NumericalStatisticalAnalysis"),
}


_SECTION_META = ("description", "methodology", "calculation_thresholds")


def make_analyzer(view: FormationView, family: str):
    """A family's petrophys analyzer with the policy's class tables (policy analyzers.class_tables: the library's
    current set, or the set a data config names in data.analyzer_class_tables, FormationView.build). Analyzers that
    take no class_tables argument (the numerical one, or any in a library without class-table sets) are built with
    their defaults."""
    import importlib
    import inspect
    module, cls = _ANALYZERS[family]
    klass = getattr(importlib.import_module(module), cls)
    tables = (view.policy.get("analyzers") or {}).get("class_tables")
    if tables and "class_tables" in inspect.signature(klass.__init__).parameters:
        return klass(class_tables=tables)
    return klass()


def zone_results(view: FormationView, family: str) -> list[tuple[Any, Any]]:
    """(zone, CategoryAnalysisResult): the library analyzer of a family run on exactly each zone's samples (as the
    workflow of record), once per view; the store and every class lookup read the same results."""
    import warnings

    family = family.lower()
    if family not in _ANALYZERS:
        raise EvidenceError(f"WHAT: unknown family {family!r}. FIX: use one of {sorted(_ANALYZERS)}.")
    cache = view.__dict__.setdefault("_analyzer_results", {})
    if family not in cache:
        analyzer = make_analyzer(view, family)
        out = []
        for z in view.zones:
            # with the calculations the well was interpreted with (petroharness.well.calculations)
            with warnings.catch_warnings(), calculations(getattr(view.prep, "context_profile", None)):
                warnings.simplefilter("ignore")
                out.append((z, analyzer.analyze(view.zone_well(z), add_curves=False)))
        cache[family] = out
    return cache[family]


def label_runs(depth: np.ndarray, labels) -> dict[str, list[tuple[float, float]]]:
    """Each label's runs as (first, last) sample depths, in first-appearance order; missing labels (None, NaN, '')
    have none. Runs from flag_runs (petrophys flag_intervals)."""
    labels = np.asarray(labels, dtype=object)
    out: dict[str, list[tuple[float, float]]] = {}
    for label in dict.fromkeys(labels.tolist()):
        if label is None or label == "" or (isinstance(label, float) and np.isnan(label)):
            continue
        out[str(label)] = [(float(depth[a]), float(depth[b])) for a, b in flag_runs(depth, (labels == label).astype(float))]
    return out


def _summary_fields(body) -> list[tuple[str, Any]]:
    """The scalar fields of an analyzer's summary (its result metadata, values not class intervals), e.g.
    reservoir_fraction of formation_level_summary; empty for anything else."""
    if not isinstance(body, dict):
        return []
    return [(k, v) for k, v in body.items()
            if k not in _SECTION_META and not isinstance(v, (list, dict)) and v not in (None, "")]


def section_summaries(view: FormationView, family: str, section: str) -> list[tuple[str, list[float]]]:
    """Analyzer sections that report values per zone instead of class intervals (e.g. formation_level_summary,
    mhi_confirmation): one line per zone with its scalar fields, and the numbers shown (for the verifier).
    Without it a verdict topic whose section is a summary would show nothing."""
    out = []
    for z, result in zone_results(view, family):
        fields, nums = [], []
        for k, v in _summary_fields(result.metadata.get(section)):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                nums.append(sig(float(v)))
                fields.append(f"{k} {fmt(sig(float(v)))}")
            else:
                fields.append(f"{k}: {v}")
        if fields:
            out.append((f"{section} — {z.zone_id} ({z.lithology}, {fmt_depth(z.top)}-{fmt_depth(z.base)} {view.depth_unit}): "
                        + "; ".join(fields), nums))
    return out


def _zone_mean_well(view: FormationView):
    """A petrophys Well with one sample per zone holding the zone means (codes as the zone's mode)."""
    from petrophys.model.well import Well

    full = view.prep.well
    w = Well(name=full.name)
    w.depth = np.array([(z.top + z.base) / 2 for z in view.zones], dtype=float)
    w._depth_unit = view.depth_unit                     # zone mid-points are in metres whatever the LAS unit
    w.header, w._parameters = full.header, full._parameters
    for mnemonic in full.curves:
        data = view.values(mnemonic)
        if data is None:
            continue
        vals = []
        for z in view.zones:
            x = data[z.indices]
            x = x[np.isfinite(x)]
            if x.size == 0:
                vals.append(np.nan)
            elif mnemonic == view.lithology_curve or mnemonic.startswith("LITHOLOGY"):
                u, c = np.unique(np.round(x), return_counts=True)
                vals.append(float(u[np.argmax(c)]))
            else:
                vals.append(float(np.mean(x)))
        w.add_curve(mnemonic, vals, view.unit(mnemonic))
    return w


def zone_classes_raw(view: FormationView, topic) -> dict:
    """{section: {zone_id: label}} from the analyzer run on zone means, plus thresholds."""
    import warnings

    topics = view.reg.resolve_topics(topic)
    if not topics:
        raise EvidenceError(f"WHAT: unknown topic {topic!r}. FIX: use one of {sorted(view.reg.topics['topics'])}.")
    w = _zone_mean_well(view)                         # one sample per zone, in zone order
    out, thresholds, summaries, families = {}, {}, [], {}
    for name in topics:
        for fam, secs in view.reg.topics["topics"][name]:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = make_analyzer(view, fam).analyze(w, add_curves=False)
            for sec in [k for k in list(result.sections) + list(result.metadata) if k in secs]:   # the result's order
                if _summary_fields(result.metadata.get(sec)):
                    # A summary (values, not classes) has no class per zone mean: it would read "unresolved" in every
                    # zone. zone_classes gives its values per zone instead (section_summaries).
                    summaries.append((fam, sec))
                    continue
                if sec not in result.sections:
                    continue
                section = result.sections[sec]
                thresholds[sec] = section.calculation_thresholds or ""
                families[sec] = fam
                out[sec] = {z.zone_id: str(lab) for z, lab in zip(view.zones, section.raw_labels)
                            if not (lab is None or lab == "" or (isinstance(lab, float) and np.isnan(lab)))}
    return {"classes": out, "thresholds": thresholds, "summaries": summaries, "families": families}


def sample_labels(view: FormationView, family: str, section: str) -> np.ndarray:
    """Each interval sample's label in a section, from the analyzer run on each zone's samples (None outside the zones
    and where the analyzer gives none)."""
    out = np.full(np.asarray(view.depth).size, None, dtype=object)
    for z, result in zone_results(view, family):
        if section in result.sections:
            labs = np.asarray(result.sections[section].raw_labels, dtype=object)
            if labs.size == len(z.indices):
                out[z.indices] = labs
    return out


def _net_rock_status(view: FormationView) -> dict[str, str]:
    """Each zone's net-rock status by the policy shale cutoff: the NET_ROCK fraction where the workflow wrote the flag,
    else the zone-mean VCL against the cutoff."""
    vcl_max = (view.policy.get("cutoffs") or {}).get("vcl_max")
    out = {}
    for z in view.zones:
        net = view.zone_values(z, "NET_ROCK")
        vcl = view.zone_values(z, "VCL")
        v = float(np.nanmean(vcl)) if vcl is not None and np.isfinite(vcl).any() else None
        if net is not None and np.isfinite(net).any():
            out[z.zone_id] = "pass" if float(np.nanmean(net)) >= 0.5 else ("fail" + (f" (VCL {v:.2f})" if v is not None else ""))
        elif v is not None and vcl_max is not None:
            out[z.zone_id] = "pass" if v <= vcl_max else f"fail (VCL {v:.2f})"
    return out
