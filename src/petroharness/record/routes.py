"""Which route a derived curve took in this interval, read sample by sample from the curves."""
from __future__ import annotations

import re
from typing import Optional

import numpy as np

SHALLOW = ("RXO", "RSHA", "RESS", "RMED")          # the record's order: measured shallow curves first, then the fallback
FALLBACK = "RMED"
_TOL = 1e-3                                        # relative: the ratio as written by the workflow, against s / deep


def _values(view, c: str) -> Optional[np.ndarray]:
    try:
        x = view.values(c) if view.available(c) else None
    except Exception:  # noqa: BLE001  (a curve the view cannot give)
        x = None
    return None if x is None else np.asarray(x, dtype=float)


def invasion_pair(view) -> tuple:
    """(deep curve, the shallow-side curves in the record's order, the medium ones among them) of the invasion step's
    record: its inputs and rxo_source_counts (shallow_source_counts: the true shallow logs; the others are a medium log
    taken where no shallow one is). Without that record: RDEP, SHALLOW, {RMED}."""
    rec = (getattr(view.prep, "steps", None) or {}).get("invasion") or {}
    p = rec.get("parameters") or {}
    counts = p.get("rxo_source_counts") or {}
    if not counts:
        return "RDEP", list(SHALLOW), {FALLBACK}
    order = [str(c) for c in p.get("rxo_curve_order") or SHALLOW]
    side = [c for c in order if c in counts] + [c for c in counts if c not in order]
    true = set(p.get("shallow_source_counts") or {})
    deep = next((str(i) for i in rec.get("inputs") or [] if "+" not in str(i) and str(i) not in counts), "RDEP")
    return deep, side, {c for c in side if c not in true}


def invasion_counts(view) -> Optional[dict]:
    """Per sample with an INVASION_RATIO value, the resistivity pair that gives it (a shallow-side curve of the record
    over its deep curve, within 0.1%); a sample two curves fit counts for the first in the record's order. None without
    the ratio or the deep curve. Keys: n, deep, side (the record's order), medium (those taken where no shallow log
    is), each side curve's count, other."""
    deep_name, side, medium = invasion_pair(view)
    ratio, deep = _values(view, "INVASION_RATIO"), _values(view, deep_name)
    if ratio is None or deep is None:
        return None
    ok = np.isfinite(ratio)
    if not ok.any():
        return None
    out, taken = {"n": int(ok.sum()), "deep": deep_name, "side": side, "medium": medium}, np.zeros(ratio.size, dtype=bool)
    with np.errstate(invalid="ignore", divide="ignore"):
        for c in side:
            s = _values(view, c)
            if s is None:
                continue
            q = s / deep
            fit = ok & ~taken & np.isfinite(q) & (deep > 0) & (np.abs(ratio - q) <= _TOL * np.maximum(np.abs(ratio), 1e-6))
            if fit.any():
                out[c] = int(fit.sum())
                taken |= fit
    out["other"] = int((ok & ~taken).sum())
    return out


def medium_used(c: dict) -> list:
    """The medium curves the ratio takes in place of a shallow log at some sample here."""
    return [m for m in c.get("side", []) if m in c.get("medium", ()) and c.get(m)]


def sxo_counts(view) -> Optional[dict]:
    """Per sample with SXO and SW: quicklook where SXO = SW^(1/5) (within 0.001), water-bearing where both are 1 (either
    route gives that), measured (from shallow resistivity) otherwise. None without SXO and SW."""
    sxo, sw = _values(view, "SXO"), _values(view, "SW")
    if sxo is None or sw is None:
        return None
    ok = np.isfinite(sxo) & np.isfinite(sw) & (sw >= 0)
    if not ok.any():
        return None
    water = ok & (sw >= 0.999) & (sxo >= 0.999)
    with np.errstate(invalid="ignore"):
        quick = ok & ~water & (np.abs(sxo - np.where(sw >= 0, sw, np.nan) ** 0.2) < 1e-3)
    return {"n": int(ok.sum()), "measured": int((ok & ~water & ~quick).sum()), "quicklook": int(quick.sum()),
            "water": int(water.sum())}


def _pairs(c: dict) -> str:
    # the count names its unit: a bare count after "at" reads as a depth
    # ("RSHA/RDEP at 1924" -> "at 1 sample (1924 ft)")
    u = " samples"
    deep = c.get("deep", "RDEP")
    parts = [f"{k}/{deep} at {c[k]}{u}" + (" (a medium resistivity, where no shallow log is)" if k in c.get("medium", ())
                                           else "")
             for k in c.get("side", SHALLOW) if c.get(k)]
    if c.get("other"):
        parts.append(f"no pair of the record at {c['other']}{u}")
    return ", ".join(parts)


def route_lines(view) -> dict:
    """{step: lines}: the routes this interval's samples took, for the steps that record a well-wide route."""
    out = {}
    c = invasion_counts(view)
    if c:
        line = f"in this interval INVASION_RATIO = {_pairs(c)} of its {c['n']} samples with a ratio"
        if not medium_used(c):
            line += "; no medium resistivity stands in for a shallow one here"
        out["invasion"] = [line]
    s = sxo_counts(view)
    if s:
        parts = [f"from shallow resistivity at {s['measured']} samples" if s["measured"] else "",
                 f"the quicklook SW^(1/5) at {s['quicklook']} samples" if s["quicklook"] else "",
                 f"1 where SW is 1 too (water-bearing, either route) at {s['water']} samples" if s["water"] else ""]
        line = f"in this interval SXO is {'; '.join(p for p in parts if p)} (of its {s['n']} samples with SXO and SW)"
        if s["quicklook"] and s["quicklook"] >= 0.5 * max(s["n"] - s["water"], 1):
            # "no evidence of invasion or movability" is a statement about SXO and MHI, not a verdict on movability
            # itself, and the line says so
            line += ("; where SXO is the quicklook it is a formula of SW (and MHI = SW^0.8), not a flushed-zone reading: "
                     "SXO and MHI add no evidence of invasion or movability beyond SW (the resistivity separation "
                     "and the pay flags remain the evidence)")
        out["saturation"] = [line]
        out["mhi"] = [line]
    return out


_SAYS_FALLBACK = re.compile(r"\bRMED\s*/\s*RDEP\b|medium[- /]+deep\s+(?:resistivity\s+)?(?:proxy|fallback|ratio)|"
                            r"\bfall(?:s|ing)?[- ]?back\b[^.;]{0,60}\b(?:RMED|medium)\b|\bINVASION_RATIO\b[^.;]{0,80}\bfallback\b",
                            re.I)
_SAYS_QUICKLOOK = re.compile(r"\bquick[- ]?look\b[^.;]{0,60}\bSXO\b|\bSXO\b[^.;]{0,60}\bquick[- ]?look\b|"
                             r"\bSXO\b[^.;]{0,40}SW\s*\^\s*\(?\s*1\s*/\s*5|\bSW\s*\^\s*\(?\s*1\s*/\s*5\)?[^.;]{0,40}\bSXO\b", re.I)
_NEGATED = re.compile(r"\b(?:not|no|never|isn't|is not|rather than|instead of)\b", re.I)


def contradictions(text: str, view) -> list:
    """Sentences saying this interval's INVASION_RATIO is the RMED/RDEP fallback where no sample uses it (and a
    shallow curve gives it), or that SXO is the quicklook where no sample is quicklook (and some are measured)."""
    out = []
    c, s = invasion_counts(view), sxo_counts(view)
    for sent in re.split(r"(?<=[.!?;])\s+|\n", text or ""):
        if _NEGATED.search(sent):
            continue
        if c and not medium_used(c) and c["n"] - c.get("other", 0) > 0 and _SAYS_FALLBACK.search(sent):
            out.append(f"says INVASION_RATIO uses the medium/deep fallback here, but in this interval it is "
                       f"{_pairs(c)} of its {c['n']} samples (the fallback text in the step record describes the well)")
            c = None
        if s and not s["quicklook"] and s["measured"] and _SAYS_QUICKLOOK.search(sent):
            out.append(f"says SXO is the quicklook SW^(1/5) here, but in this interval SXO comes from shallow resistivity "
                       f"at {s['measured']} of its {s['n']} samples and the quicklook at none")
            s = None
    return out
