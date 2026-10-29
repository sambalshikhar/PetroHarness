"""The workflow store: every analyzer family's sections per lithology zone, plus the curves the analyzers derive
while classifying (PHI_NORM, MHI, ND_SEPARATION, ...), kept as curves of the formation view."""

from __future__ import annotations

import numpy as np

from petroharness.record.sections import Store, analyzer_sections, store_curves
from petroharness.well.view import FormationView


def phi_norm(well) -> tuple[np.ndarray, str]:
    """PHI_NORM as petrophys delivers it (reference_export._synchronize_post_qc_dependent_curves): calculate_phi_z on
    the depth-wise PHIE_CC, PHIE, PHIT composite of the cleaned curves, 0 < phi < 1 (NaN elsewhere); the workflow's
    PHI_Z where no value QC changed its input."""
    from petrophys._internal.analysis_helpers import get_curve_data_depthwise
    from petrophys.evaluation.rock_quality.rock_quality_module import calculate_phi_z
    phie, _, _ = get_curve_data_depthwise(well, ["PHIE_CC", "PHIE", "PHIT"])
    return (np.full(well.n_samples, np.nan) if phie is None else np.asarray(calculate_phi_z(phie), dtype=float)), "fraction"


def build(view: FormationView) -> Store:
    """The analyzers' sections and derived curves (native.analyzer_sections); the derived curves become
    view.analyzer_curves and view.analyzer_fills (petroharness.well.derived; never the workflow's well)."""
    full = view.prep.well
    sections, derived = analyzer_sections(view)
    view.analyzer_curves.clear()
    view.analyzer_curves.update(derived.new)
    view.analyzer_fills.clear()
    view.analyzer_fills.update(derived.fills)
    if full.get("PHI_NORM") is None and "PHI_NORM" not in derived.new:
        view.analyzer_curves["PHI_NORM"] = phi_norm(full)
    background = frozenset(str(c) for c in view.reg.topics.get("background_classes", []) or [])
    return Store(view=view, sections=sections, curves=store_curves(view), background=background,
                 derived=frozenset(derived.new))
