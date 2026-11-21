"""Notes on this interval: general facts about the interval's record the map states (routes, fallbacks, cutoffs)."""
from __future__ import annotations

import re

import numpy as np

BAD_HOLE_SHOWN = 5.0           # zones with at least this share (%) of bad-hole samples are named
NOT_RUN_SHARE = 99.0           # a class over at least this share (%) of the samples is "about the whole interval"
_CURVE = re.compile(r"\b[A-Z][A-Z0-9_]{1,}\b")
_NEGATIVE = re.compile(r"^NO_(?!.*DATA$)[A-Z_]+$")           # reads as "none found", unlike NO_DATA or UNDETERMINED
_ONLY_WHEN = re.compile(r"only when (?:both )?([A-Z0-9_ ,]+?(?: and [A-Z0-9_]+)?) (?:are|is) present", re.I)


from petroharness.record.card import mineral_fact  # noqa: F401,E402  (the card builds every fact; kept for callers)


def _facts(view, curves: dict) -> list:
    """The record's provenance facts, as the card builds them from data (record.card.provenance_facts): the notes
    layer reads no fact's text."""
    from petroharness.record.card import provenance_facts
    return list(provenance_facts(view))


def bad_hole(view) -> list:
    """(zone id, share %) of samples with BAD_HOLE > 0.5, per zone with data, in zone order."""
    if not view.available("BAD_HOLE"):
        return []
    out = []
    for z in view.zones:
        x = np.asarray(view.zone_values(z, "BAD_HOLE"), dtype=float)
        x = x[np.isfinite(x)]
        if x.size:
            out.append((z.zone_id, round(100 * float((x > 0.5).mean()), 1)))
    return out


def _bad_hole_note(view) -> str:
    shares = bad_hole(view)
    if not shares:
        return ""
    big = sorted([s for s in shares if s[1] >= BAD_HOLE_SHOWN], key=lambda s: -s[1])
    if not big:
        return f"Bad hole (BAD_HOLE > 0.5): under {BAD_HOLE_SHOWN:g}% of the samples in every zone"
    named = ", ".join(f"{z} {s:g}%" for z, s in big[:8]) + (f" (and {len(big) - 8} more zones)" if len(big) > 8 else "")
    return (f"Bad hole (BAD_HOLE > 0.5): {named} of the zone's samples; there the pad tools read mud "
            "(RHOB low, density porosity high; NPHI, PEF affected)")


def _share(c) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", c.share_pct or "") or 0)
    except ValueError:
        return 0.0


def not_run(sections, curves: dict) -> list:
    """(section key, class, share, the inputs it lacks) for sections whose negative-sounding class covers about the
    whole interval while the method needs an input this interval lacks: curves its method requires that have no data
    here, or an input the analyzer marks 'unavailable'."""
    out = []
    for sec in sections:
        top = max(sec.classes, key=_share, default=None)
        if top is None or _share(top) < NOT_RUN_SHARE or not _NEGATIVE.match(str(top.name)):
            continue
        method = sec.method or ""
        need = [n for m in _ONLY_WHEN.finditer(method) for n in _CURVE.findall(m.group(1))]
        lacks = [n for n in dict.fromkeys(need) if n not in curves]
        if not lacks and re.search(r"\bunavailable\b", method):
            lacks = ["an input it reads as unavailable"]
        if lacks:
            out.append((sec.key, top.name, _share(top), lacks))
    return out


def _not_run_notes(sections, curves: dict) -> list:
    return [f"{key}: {cls} on {share:g}% of the samples, but its method needs {', '.join(lacks)}, not here: "
            "samples it could not compute, not a negative result"
            for key, cls, share, lacks in not_run(sections, curves)]


# classes the lithology analyzer gives by construction (petrophys evaluation/diagnostics/lithology_analysis):
# its carbonate indicators need PEF and RHOB on the same sample, and a sample it cannot test keeps NON_CARBONATE; its
# GR and PEF consistency windows exist for these groups only, so a rock of any other group cannot match
CARBONATE_INPUTS = ("PEF", "RHOB")
CARBONATE_PEF, CARBONATE_RHOB = 2.8, 2.6            # its indicator: PEF > 2.8 and bulk RHOB > 2.6 on the same sample
CALCITE_RHO, WATER_RHO = 2.71, 1.0                  # g/cm3, the matrix and fluid of a water-filled limestone
CONSISTENCY_GROUPS = ("SHALE", "SANDSTONE", "LIMESTONE", "DOLOMITE")


def _section(sections, name: str):
    return next((s for s in sections if s.key.split(".")[-1] == name), None)


def _carbonate_note(view, sections) -> list:
    """NON_CARBONATE over samples the carbonate indicators could not test (PEF or RHOB missing there)."""
    sec = _section(sections, "carbonate_analysis")
    non = next((c for c in (sec.classes if sec else []) if c.name == "NON_CARBONATE"), None)
    if non is None:
        return []
    both = np.ones(int(view.mask.sum()), dtype=bool)
    for c in CARBONATE_INPUTS:
        x = view.values(c)
        both &= np.isfinite(np.asarray(x, dtype=float)) if x is not None else False
    if both.mean() >= 0.99:
        return []
    lacks = [c for c in CARBONATE_INPUTS if not view.available(c)]
    return [f"{sec.key}: its carbonate indicators need {' and '.join(CARBONATE_INPUTS)} on the same sample, together at "
            f"{int(both.sum())} of {both.size} samples here" + (f" ({', '.join(lacks)} has no data here)" if lacks else "")
            + "; samples it could not test keep the label NON_CARBONATE"]


def _mismatch_note(view, sections) -> list:
    """CARBONATE_LOG_MISMATCH where PEF reads carbonate and only bulk RHOB fails the indicator: the rule, the counts and
    the bulk density a water-filled calcite matrix has at their median porosity (facts only: the model concludes)."""
    sec = _section(sections, "carbonate_analysis")
    mis = next((c for c in (sec.classes if sec else []) if c.name == "CARBONATE_LOG_MISMATCH"), None)
    if mis is None:
        return []
    pef, rho = (np.asarray(view.values(c), dtype=float) if view.values(c) is not None else None for c in CARBONATE_INPUTS)
    if pef is None or rho is None:
        return []
    tested = np.isfinite(pef) & np.isfinite(rho)
    rho_only = tested & (pef > CARBONATE_PEF) & (rho <= CARBONATE_RHOB)
    if tested.sum() == 0 or rho_only.sum() < 0.5 * tested.sum():
        return []
    phi = next((np.asarray(view.values(c), dtype=float) for c in ("PHIE", "PHIT") if view.available(c)), None)
    if phi is None or not np.isfinite(phi[rho_only]).any():
        return []
    p = float(np.nanmedian(phi[rho_only]))
    expect = CALCITE_RHO * (1 - p) + WATER_RHO * p
    return [f"{sec.key}: its carbonate indicator needs PEF > {CARBONATE_PEF:g} and bulk RHOB > {CARBONATE_RHOB:g} g/cm3; at "
            f"{int(rho_only.sum())} of {int(tested.sum())} tested samples here PEF reads carbonate and only bulk RHOB fails. "
            f"At their median porosity ({p:.3g} v/v) a water-filled calcite matrix reads about {expect:.3g} g/cm3 "
            f"(RHOB = {CALCITE_RHO:g} (1 - phi) + {WATER_RHO:g} phi)"]


GAS_SCREEN = 0.03       # petrophys saturation_analysis: WEAK_GAS_EFFECT from PHID - PHIN >= 0.03 (0.08, 0.15 above)


def _gas_screen_note(view, sections) -> list:
    """The saturation analyzer's gas classes screen PHID - PHIN alone on every sample; the workflow's crossover call
    (CROSSOVER_FLAG) adds clay, porosity and hole conditions: how many screened samples it confirms here."""
    sec = _section(sections, "gas_indicator_analysis_methods")
    if sec is None or not any(c.name.endswith("_GAS_EFFECT") and not c.name.startswith("NO_") for c in sec.classes):
        return []
    sep, flag = view.values("ND_SEPARATION"), view.values("CROSSOVER_FLAG")
    if sep is None or flag is None:
        return []
    sep, flag = np.asarray(sep, dtype=float), np.asarray(flag, dtype=float)
    with np.errstate(invalid="ignore"):
        screened, called = sep >= GAS_SCREEN, flag > 0.5
    try:
        from petrophys.evaluation.diagnostics.hydrocarbon_analysis import HydrocarbonAnalysis as H
        rule = (f"PHID - PHIN > {H.CROSSOVER_ND_SEPARATION:g} with VCL < {H.CROSSOVER_VCL_MAX:g}, PHIE > "
                f"{H.CROSSOVER_PHIE_MIN:g} and good hole")
    except Exception:  # noqa: BLE001  (an older petrophys: the rule unnamed)
        rule = "a larger separation with clay, porosity and hole conditions"
    return [f"{sec.key}: its gas classes screen PHID - PHIN alone (WEAK_GAS_EFFECT from {GAS_SCREEN:g}) with no clay, "
            f"porosity or hole condition, at {int(screened.sum())} of {screened.size} samples here; the workflow's "
            f"crossover call CROSSOVER_FLAG ({rule}) is set at {int((screened & called).sum())} of them"]


def _consistency_note(view, sections) -> list:
    """Zones whose rock is in a lithology group the consistency check has no window for (they cannot match)."""
    sec = _section(sections, "lithology_log_consistency")
    if sec is None:
        return []
    try:
        from petrophys.evaluation.diagnostics.lithology_analysis import GROUND_TRUTH_GROUPS
    except Exception:  # noqa: BLE001  (an older petrophys: no note)
        return []
    table = getattr(view, "code_table", None) or {}
    hit = {}
    for z in view.zones:
        codes = {int(c) for c, lab in table.items() if str(lab).strip().upper() == str(z.lithology).strip().upper()}
        groups = {g for g, cs in GROUND_TRUTH_GROUPS.items() if codes & set(cs)}
        if groups and not groups & set(CONSISTENCY_GROUPS):
            hit.setdefault((str(z.lithology).upper(), "/".join(sorted(groups))), []).append(z.zone_id)
    return [f"{sec.key}: the check has GR and PEF windows for the {', '.join(g.lower() for g in CONSISTENCY_GROUPS)} groups "
            f"only; {', '.join(zs)} ({lith}, the workflow's {grp} group) has no window, and the check gives "
            "NO_LOG_LITHOLOGY_MATCH where it has no window" for (lith, grp), zs in hit.items()]


def notes(view, curves: dict, sections) -> list:
    out = _facts(view, curves)
    bh = _bad_hole_note(view)
    if bh:
        out.append(bh)
    out += _not_run_notes(sections, curves)
    out += (_carbonate_note(view, sections) + _mismatch_note(view, sections) + _consistency_note(view, sections)
            + _gas_screen_note(view, sections))
    return out
