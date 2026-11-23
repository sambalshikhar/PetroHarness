"""summarize (docs/TOOLS.md): net pay and hydrocarbon pore thickness per zone with the cutoffs the
model gives, by Petrophys summarize_pay. The record's own flags and cutoffs are pay_summary's; this verb recomputes
the flags from VCL, PHIE and SW with one cutoff set, so a cutoff question is answered zone by zone."""
from __future__ import annotations

import numpy as np

from petroharness.agent import engine as E
from petroharness.agent.engine import Formation, Out, Result, ToolError
from petroharness.agent.library import _label, _num, defaults, joined_name, register
from petroharness.well import summary as S

OBJECTS = {
    "pay": "net rock, reservoir and pay thickness, net-to-gross, pay-averaged PHIE and SW, and hydrocarbon pore "
           "thickness (HCPT) per zone and pooled, with the cutoffs given (vcl_cutoff, phie_cutoff, sw_cutoff; the "
           "record's otherwise), by Petrophys summarize_pay; pay_summary gives the record's own flags and cutoffs. "
           "Needs VCL, PHIE and SW",
}
CUTOFFS = ("vcl_cutoff", "phie_cutoff", "sw_cutoff")


def _curve(f: Formation, name: str) -> np.ndarray:
    v = f.view.values(name) if name in f.inv.curves else None
    if v is None or not np.isfinite(v).any():
        raise ToolError(f"summarize pay needs {name}; it has no data here")
    return np.asarray(v, dtype=float)


def summarize(f: Formation, what: str = "pay", zones=None, vcl_cutoff: float | None = None,
              phie_cutoff: float | None = None, sw_cutoff: float | None = None) -> Result:
    w = str(what or "pay").strip().lower()
    if w not in OBJECTS:
        raise ToolError(f"summarize has no {what!r}; it gives: " + "; ".join(f"{k}: {v}" for k, v in OBJECTS.items()))
    from petrophys.evaluation.net_pay.pay_summary import summarize_pay
    rec = defaults(f, "net_pay")
    asked = {"vcl_cutoff": vcl_cutoff, "phie_cutoff": phie_cutoff, "sw_cutoff": sw_cutoff}
    cut, src = {}, {}
    for k in CUTOFFS:
        if asked[k] is not None:
            if not _num(asked[k]) or not 0 <= float(asked[k]) <= 1:
                raise ToolError(f"{k} is a fraction between 0 and 1, not {asked[k]!r}")
            cut[k], src[k] = float(asked[k]), "asked"
        elif _num(rec.get(k)):
            cut[k], src[k] = float(rec[k]), "record"
        else:
            cut[k], src[k] = None, "library standard"
    vcl, phie, sw = _curve(f, "VCL"), _curve(f, "PHIE"), _curve(f, "SW")
    depth, unit = f.depth, f.inv.depth_unit

    def pay(idx: np.ndarray):
        try:
            return summarize_pay(vcl=vcl[idx], phie=phie[idx], sw=sw[idx], depth=depth[idx], depth_unit=unit, **cut)
        except ValueError as e:
            raise ToolError(f"Petrophys summarize_pay: {str(e)[:300]}") from None

    out = Out(f)
    whole = pay(np.arange(depth.size))
    head = out.child()
    shown = ", ".join(f"{k.split('_')[0].upper()} {'<' if k != 'phie_cutoff' else '>'} "
                      f"{head.v(getattr(whole, k))} ({src[k]})" for k in CUTOFFS)
    out.add(f"pay by Petrophys summarize_pay, cutoffs {shown}: flags recomputed from VCL, PHIE and SW with this one "
            f"cutoff set and no exclusions (the record's NET_PAY leaves bad hole and non-reservoir lithology out; "
            f"pay_summary gives the record's own flags); thicknesses in {unit}, averages over the pay", head)

    def line(s, z=None, label: str = "") -> tuple:
        row = out.child()
        label = f"{z.zone_id} {E.zone_name(z)} {row.span(z.top, z.base)}" if z is not None else label
        avg = (f", pay PHIE {row.v(s.avg_phie_pay)}, pay SW {row.v(s.avg_sw_pay)}" if s.n_pay_samples else "")
        text = (f"  {label}: gross {row.v(s.gross_thickness)}, net rock {row.v(s.net_rock_thickness)}, net reservoir "
                f"{row.v(s.net_reservoir_thickness)}, net pay {row.v(s.net_pay_thickness)} ({row.i(s.n_pay_samples)} "
                f"of {row.i(s.n_samples)} samples); net-to-gross reservoir {row.v(s.ntg_reservoir)}, pay "
                f"{row.v(s.ntg_pay)}{avg}; HCPT {row.v(s.hcpt)} {unit}")
        return text, row

    picked = E.zones(f, zones)
    if not zones:                                   # the whole selection first, then its breakdown (engine.scopes)
        row = out.child()
        text, row = line(whole, label=S.whole_label_of(f.view, row.i))
        out.add(text, row)
    if len(picked) > 1:                             # the zones pooled: the zone rows fit in what is left
        pooled = np.unique(np.concatenate([np.asarray(z.indices) for z in picked]))
        kind = S.pooled_word(f.view)
        text, row = line(pay(pooled), label=f"{kind} pooled" if len(picked) == len(f.view.zones) else
                         f"{kind} pooled ({', '.join(z.zone_id for z in picked)})")
        out.add(text, row)
    rows = []
    for z in picked:
        idx = np.asarray(z.indices)
        if idx.size:
            text, row = line(pay(idx), z)
            rows.append((z.zone_id, text, row))
    out.fit(rows, what="zones", label="pay")
    if any(s == "asked" for s in src.values()):
        lab = _label("_".join(f"{k.split('_')[0]}{cut[k]}" for k in CUTOFFS if src[k] == "asked"), {})
        written = []
        for flag, values in (("NET_RES", whole.net_reservoir), ("NET_PAY", whole.net_pay)):
            full = np.full(np.asarray(f.view.prep.depth).size, np.nan)
            vals = np.asarray(values, dtype=float)
            vals[~(np.isfinite(vcl) & np.isfinite(phie) & np.isfinite(sw))] = np.nan
            full[f.view.mask] = vals
            written.append(register(f, joined_name(flag, lab), full, f"{flag} recomputed by Petrophys summarize_pay "
                                    f"with the cutoffs {shown}", "flag", "summarize pay (on request)"))
        out.add(f"  written: {', '.join(written)} (flags of this question: runs, stats and conditions read them)")
    return out.result()
