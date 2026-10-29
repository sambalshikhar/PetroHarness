"""The Petrophys calculations a well's analyses run with: the ones it was interpreted with."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import Iterator, Optional


@contextmanager
def calculations(context_profile: Optional[str]) -> Iterator[None]:
    """Run the block with the calculations of the context profile's package (None: the library's standard ones)."""
    if not context_profile:
        yield
        return
    from petrophys._internal.benchmark import historical_benchmark
    from petrophys.reporting.context_profiles import get_context_profile
    from petrophys.workflow.dynamic_workflow import _DATASET_CALCULATIONS, _dataset_calculations

    profile = get_context_profile(context_profile)
    names = {profile.name, *profile.aliases}
    own = next((d for d in _DATASET_CALCULATIONS if d in names), None)   # a package with calculations of its own
    with ExitStack() as stack:
        stack.enter_context(historical_benchmark())
        if own is not None:
            stack.enter_context(_dataset_calculations(own))
        yield


def as_context_group(well, rules: dict, context_profile: Optional[str]) -> None:
    """A part of a context-profile interpretation's workflow well, processed in place as the profile's package
    processes each group: the value-range QC the interpretation applied (rules: curve -> {low, high, action}) and its
    recomputation of the dependent curves from the part's own inputs (added where the part has them, the workflow's
    values kept where the package's calculations keep them)."""
    from petrophys.preprocessing.quality.value_ranges import ValueRangeRule, apply_value_range_qc
    from petrophys.reporting.reference_export import _synchronize_post_qc_dependent_curves

    qc = {c: ValueRangeRule(r["low"], r["high"], r.get("action") or "nan", (c,)) for c, r in rules.items()
          if r.get("low") is not None and r.get("high") is not None}
    with calculations(context_profile):
        if qc:
            apply_value_range_qc(well, curve_names=[c for c in qc if well.get(c) is not None], store_report=False,
                                 rules=qc)
        _synchronize_post_qc_dependent_curves(well, benchmark=context_profile is not None)
