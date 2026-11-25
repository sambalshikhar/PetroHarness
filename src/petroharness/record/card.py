"""Facts of the workflow's record: what each step ran, with which inputs, parameters and decisions (Rw, SW
models, SXO, MHI, permeability, cutoffs), read from the Petrophys step record."""

from __future__ import annotations

import re
from typing import Optional

import numpy as np

from petroharness.well.view import FormationView, fmt, sig


# ---------------------------------------------------------------------------
# Step-record access
# ---------------------------------------------------------------------------

def last_step(steps: dict, name: str) -> dict:
    """The record of a step. A step the workflow ran again later (e.g. `permeability_finalize` after net pay, whose
    SWIRR and PERM are the ones the curves hold) counts as that step: the last run wins."""
    found: dict = {}
    for key, rec in (steps or {}).items():
        if key == name or key.startswith(name + "_"):
            found = rec or {}
    return found


def _step(view: FormationView, name: str) -> dict:
    return last_step(view.prep.steps, name)


def _params(rec: Optional[dict]) -> dict:
    return (rec or {}).get("parameters") or {}


_FALLBACK = re.compile(r"^[A-Z][A-Z0-9_]*(?:[+/][A-Z][A-Z0-9_]*)+$")


def fallback(name: str) -> str:
    """A recorded input that is a fallback list, in plain words: "A+B" (the record's depth-wise composite: A, and B only
    where A is missing) or "A/B" (an input the step takes as A, or else B) reads "A where present, otherwise B"; any
    other name as recorded. A fallback list is never written "A, B" or "A+B", which read as two inputs or a sum."""
    name = str(name)
    if not _FALLBACK.match(name):
        return name
    first, *rest = re.split(r"[+/]", name)
    return first + "".join(f" where present, otherwise {r}" for r in rest)


def input_text(name: str) -> str:
    """A recorded input as text: a fallback list in plain words, in parentheses ("(PHIE where present, otherwise
    PHIT)"); any other input as recorded."""
    plain = fallback(name)
    return plain if plain == str(name) else f"({plain})"


def plain_inputs(text: str, inputs) -> str:
    """A step-record line (an equation, a record line) with each fallback list of the step's inputs written as
    input_text: "BVW = PHIE+PHIT * SW" -> "BVW = (PHIE where present, otherwise PHIT) * SW". Only the step's own
    fallback inputs are rewritten: another "A+B" in its lines (VCALC+VDOLO = 1 - VCL - PHIE) is a sum."""
    out = str(text)
    for name in sorted({str(i) for i in inputs or [] if _FALLBACK.match(str(i))}, key=len, reverse=True):
        out = re.sub(rf"(?<![A-Za-z0-9_+]){re.escape(name)}(?![A-Za-z0-9_+])", lambda m: input_text(m.group(0)), out)
    return out


def producer(steps: dict, curve: str) -> Optional[tuple[str, list[str]]]:
    """(step, the curves it read) of the step that made the curve (the record's outputs lists): the last workflow step
    that wrote it; else the last step of a preparation or of what followed the workflow (a record with stages: a
    context profile reads, screens and recomputes curves the LAS or the workflow made, and makes a few of its own)."""
    found = other = None
    for key, rec in (steps or {}).items():
        if curve in ((rec or {}).get("outputs") or []):
            hit = (key, list((rec or {}).get("inputs") or []))
            if ((rec or {}).get("stage") or "workflow") == "workflow":
                found = hit
            else:
                other = hit
    return found or other


def _same_values(a: np.ndarray, b: np.ndarray) -> bool:
    """Two curves of one well hold the same values: equal wherever both are defined, and defined at the same depths
    (allowing a few samples a later QC step removed from one of them)."""
    if a is None or b is None or a.shape != b.shape:
        return False
    fa, fb = np.isfinite(a), np.isfinite(b)
    both = fa & fb
    n = int(both.sum())
    return n > 0 and n >= 0.95 * max(int(fa.sum()), int(fb.sum())) and bool(np.allclose(a[both], b[both], rtol=1e-9, atol=0))


def curve_origin(view: FormationView, curve: str) -> Optional[tuple]:
    """Where a curve of the interpreted well comes from, from the record and the LAS, never assumed:
    ("step", step, inputs) a recorded step wrote it; ("supplied",) the LAS carries it and no step wrote it;
    ("copy", other) neither, and it holds the same values as the supplied curve `other`; ("unrecorded",) none of these.
    A record that does not list the curves its steps wrote cannot show a step or rule one out: the LAS still shows a
    curve it supplies, and anything else is None (unknown; a copy needs the record to show that no step wrote it)."""
    steps = view.prep.steps or {}
    listed = any("outputs" in (rec or {}) for rec in steps.values())
    made = producer(steps, curve) if listed else None
    supplied = curve.upper() in {c.upper() for c in view.prep.input_curves} or curve.upper() in _las_names(view)
    if made and not (supplied and (steps[made[0]] or {}).get("stage", "workflow") != "workflow"):
        return ("step",) + made                         # (a LAS curve a preparation read in or a QC screened: supplied)
    if supplied:
        return ("supplied",)
    if not listed:
        return None
    whole = view.prep.curve(curve)
    for other in view.prep.input_curves:
        if other != curve and _same_values(whole, view.prep.curve(other)):
            return ("copy", other)
    return ("unrecorded",)


def _las_names(view: FormationView) -> set:
    """The LAS file's own curve mnemonics (the loaded well's names are the library's aliases: RESD read in as RDEP); an
    unreadable header gives none."""
    from petroharness.well.view import las_mnemonics
    try:
        return set(las_mnemonics(str(view.task.las_path)))         # every curve, described or not
    except Exception:  # noqa: BLE001
        return set()


def _las_description(view: FormationView, curve: str) -> str:
    from petroharness.well.view import las_curve_descriptions

    try:
        return las_curve_descriptions(str(view.task.las_path)).get(curve.upper(), "")
    except Exception:                                  # a header lasio cannot read: no description, the rest stands
        return ""


def _decisions(rec: Optional[dict]) -> list[str]:
    return [d for d in ((rec or {}).get("decisions") or []) if isinstance(d, str)]


def _num(x) -> bool:
    return isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool) and bool(np.isfinite(x))


def _f(x) -> str:
    return fmt(float(x))


def _name(names: dict, ident) -> str:
    """How the card names a recorded method identifier (shown as recorded when the registry has no name for it)."""
    return str(names.get(ident, ident))


_COMPOSITE = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]*(?:\+[A-Z][A-Z0-9_]*)+)(?![A-Za-z0-9_])")


_CLAUSE = re.compile(r";\s+|,\s+(?=[A-Z][A-Z0-9_]* = )")     # a decision's clauses: "; ", and ", " before "NAME = "
_BINDING = re.compile(r"^([a-z][a-z_]*|[A-Z][A-Z0-9_]*) is ([A-Z][A-Z0-9_]*)(.*)$")


def clauses(decision: str) -> list[str]:
    """A decision line's clauses: "RQI = 0.0314*sqrt(k/phi), PHI_Z = phi/(1-phi); k is PERM" gives "RQI = ...",
    "PHI_Z = ..." and "k is PERM"."""
    return [c for c in _CLAUSE.split(decision) if c]


def bindings(decision: str) -> dict:
    """The curves a decision line says its words stand for, each as a composite in order of use: "k is PERM_CC, and
    PERM at samples without PERM_CC; phi is PHIE_CC" gives {"k": "PERM_CC+PERM", "phi": "PHIE_CC"}; also "phi is
    PHIE_CC (PHIE where it is missing)"."""
    out = {}
    for c in clauses(decision):
        m = _BINDING.match(c.strip())
        if m:
            rest = m.group(3)
            more = re.findall(r", and ([A-Z][A-Z0-9_]*) at samples without", rest)
            gap = re.match(r"\s*\((.+?) where it is missing\)", rest)
            if gap:
                more += [x.strip() for x in gap.group(1).split(", then ")]
            out[m.group(1)] = "+".join([m.group(2)] + more)
    return out


def _curves(text: str) -> str:
    """A depth-wise composite the record writes as PHIE+PHIT (PHIE, and PHIT where PHIE is missing), written so it
    cannot read as a sum: (PHIE where present, otherwise PHIT)."""
    return _COMPOSITE.sub(lambda m: input_text(m.group(1)), text)


def _norm_well(name) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


# ---------------------------------------------------------------------------
# One renderer per step (pure functions of the step record)
# ---------------------------------------------------------------------------

def rw_fact(rw: dict, values: Optional[np.ndarray]) -> Optional[str]:
    """Rw route and interval median. rw_min/rw_max in the record are the extremes of the RW curve over the whole
    well (in every route), not a floor; the card says when RW is one value for the whole well."""
    if not rw:
        return None
    p = _params(rw)
    text = f"Rw: route={rw.get('method') or 'not recorded'}"
    vals = None if values is None else np.asarray(values, dtype=float)
    finite = vals is not None and bool(np.isfinite(vals).any())
    if finite:
        text += f"; median in interval {_f(np.nanmedian(vals))} ohm.m"
    lo, hi = p.get("rw_min"), p.get("rw_max")
    if _num(lo) and _num(hi) and abs(float(hi) - float(lo)) <= 1e-9 * max(1.0, abs(float(hi))):
        text += f" (one value for the whole well: the record's minimum and maximum are both {_f(lo)} ohm.m)"
    elif _num(lo) and finite and np.nanmax(vals) <= float(lo) + 1e-9:
        text += f" (at the well's recorded minimum, {_f(lo)} ohm.m)"
    return text


def _coefficient(name: str, value) -> Optional[str]:
    if _num(value):
        return f"{name}={_f(value)}"
    if isinstance(value, str) and "lithology" in value:
        return f"{name} by lithology"
    return None


def porosity_parameters(por: dict, zone_lithologies: list[str]) -> Optional[str]:
    """The porosity step's recorded parameters: the matrix endpoints of the lithologies the zones have (all recorded
    groups when none match; names matched loosely, SAND ~ SANDSTONE ~ SHALY SANDSTONE), the fluid values and how PHIT
    was combined (the record's sample counts over the well). provenance(porosity) serves them on demand."""
    if not por:
        return None
    p = _params(por)
    present = {str(z).upper() for z in zone_lithologies}
    eps = [e for e in p.get("matrix_endpoints") or [] if all(_num(e.get(k)) for k in ("rho_ma", "nphi_ma", "dt_ma"))]
    named = lambda g: any(g and (g in z or z in g) for z in present)
    shown = [e for e in eps if named(str(e.get("lithology_group", "")).upper())] or eps
    parts = []
    if shown:
        parts.append("matrix by lithology: " + "; ".join(
            f"{e.get('lithology_group')} rho_ma {_f(e['rho_ma'])} g/cc, nphi_ma {_f(e['nphi_ma'])}, dt_ma {_f(e['dt_ma'])} us/ft"
            for e in shown))
    elif _num(p.get("rho_ma")):
        parts.append(" ".join(f"matrix {p.get('matrix_type') or ''}: rho_ma {_f(p['rho_ma'])} g/cc".split()))
    fluid = [f"{k} {_f(p[k])}{u}" for k, u in (("rho_fl", " g/cc"), ("dt_fl", " us/ft")) if _num(p.get(k))]
    if fluid:
        parts.append(", ".join(fluid))
    if p.get("phit_method"):
        counts = [f"{str(k).replace('_', ' ')} {int(n)}" for k, n in (p.get("phit_source_counts") or {}).items()
                  if _num(n) and n > 0 and k != "nan"]
        parts.append(f"PHIT {p['phit_method']}" + (f" (samples over the well: {', '.join(counts)})" if counts else ""))
    return "; ".join(parts) or None


def saturation_fact(sat: dict, names: dict, model_parameters: dict) -> Optional[str]:
    """The SW model(s) the record names, with their per-sample counts over the well, their recorded parameters and
    the curves the step read (its porosity among them) where the record lists them."""
    if not sat:
        return None
    p, decisions = _params(sat), _decisions(sat)
    counts = {str(m): int(n) for m, n in (p.get("sw_model_sample_counts") or {}).items() if _num(n) and n > 0}
    recorded = p.get("sw_model") or sat.get("method")
    models = list(counts) or [m for m in str(recorded or "").split("+") if m]
    if not models:
        return "SW model: not recorded"
    if len(models) == 1:
        text = f"SW model: {_name(names, models[0])}" + (" (every sample)" if counts else "")
    else:
        routed = p.get("sw_model_requested") == "auto" or \
            any(d.lower().startswith("auto-routing") for d in decisions)      # before Petrophys 3a9378e: its decision
        cut = p.get("vcl_cutoff_for_routing")
        vcl = f"VCL (cutoff {_f(cut)})" if _num(cut) else "VCL"
        how = f"routed on {vcl} and lithology" if routed else "routing rule not recorded"
        listing = ", ".join(f"{_name(names, m)} {counts[m]}" if m in counts else _name(names, m) for m in models)
        text = f"SW model per sample, {how}; " + ("well counts: " if counts else "models: ") + listing
    extras: list[str] = []
    for m in models:
        for key, label in (model_parameters.get(m) or {}).items():
            if _num(p.get(key)):
                s = str(label).format(_f(p[key]))
                if s not in extras:
                    extras.append(s)
    coefficients = [c for c in (_coefficient(k, p.get(k)) for k in ("a", "m", "n")) if c]
    read = [f"computed from {', '.join(input_text(c) for c in sat['inputs'])}"] if sat.get("inputs") else []
    return "; ".join([text] + extras + ([", ".join(coefficients)] if coefficients else []) + read)


def _sxo_methods(sat: dict) -> list[str]:
    p = _params(sat)
    methods = [str(m) for m, n in (p.get("sxo_method_counts") or {}).items() if _num(n) and n > 0]
    if not methods and p.get("sxo_method"):
        methods = [m for m in str(p["sxo_method"]).split("+") if m]
    return methods


def sxo_fact(route: str, sat: dict, names: dict, quicklook: list[str]) -> Optional[str]:
    """SXO in this interval: the route found for the interval, named after the record's methods and reason."""
    if route == "none":
        return None
    methods = _sxo_methods(sat)
    reason = _params(sat).get("sxo_reason")
    quick = [m for m in methods if m in quicklook]
    other = [m for m in methods if m not in quicklook]
    quick_name = _name(names, (quick or quicklook or ["quicklook"])[0])
    here = " in this interval" if len(methods) > 1 else ""
    if route == "quicklook":
        return f"SXO: {quick_name}{here}" + (f" ({reason})" if reason else "") + "; not independent evidence"
    measured = ", ".join(_name(names, m) for m in other)
    if route == "measured":
        return f"SXO: {measured}{here}" if measured else "SXO: from shallow resistivity"
    if measured:
        return f"SXO: mixed, {measured} and {quick_name}"
    return f"SXO: shallow resistivity where valid, {quick_name} elsewhere"


MHI_QUICKLOOK = ("MHI: computed from a quicklook SXO, so it follows SW by construction "
                 "(not independent evidence of movability)")


def mhi_fact(mhi: dict, available: bool, route: str = "") -> str:
    """The MHI line. Under a quicklook SXO (route "quicklook": SXO = SW^(1/5)) MHI = SW/SXO is SW^0.8, so the line says
    it follows SW by construction instead of quoting the record's rule: the rule ("only where SXO has invaded-zone
    support") read as if MHI were independent evidence here, and "no values" as "MHI not computed", which contradicts
    a workflow that computes MHI from the quicklook SXO. Measured and mixed routes keep the record's rule."""
    rule = _params(mhi).get("rule")
    if route == "quicklook":
        if available:
            return MHI_QUICKLOOK
        return ("MHI: with a quicklook SXO, MHI = SW/SXO follows SW by construction (not independent evidence of "
                "movability); no MHI values in this interval" + (f" (rule: {rule})" if rule else ""))
    if available:
        if not rule:
            return "MHI: computed (rule not recorded)"
        return f"MHI: {rule[4:]}" if rule.startswith("MHI ") else f"MHI rule: {rule}"
    if rule:
        return f"MHI: no values in this interval (rule: {rule})"
    return "MHI: no values in this interval" + (" (rule not recorded)" if mhi else " (no MHI step in the record)")


def swirr_text(perm: dict) -> Optional[str]:
    """How the SWIRR that PERM used was obtained, from the permeability step record (percentile, mask, fallback)."""
    p, decisions = _params(perm), _decisions(perm)
    swirr, how = p.get("swirr"), p.get("swirr_app_method") or p.get("swirr_source")
    md = p.get("swirr_metadata") or {}
    if not _num(swirr):
        curve = any("resolved as curve" in d for d in decisions)
        return f"SWIRR varying with depth ({how})" if curve and how else None
    value = f"SWIRR={_f(swirr)}"
    mask = [str(md["resflag_source"])] if md.get("resflag_source") else []
    if md.get("rt_curve") and _num(md.get("rt_cutoff")):
        mask.append(f"{md['rt_curve']}>{_f(md['rt_cutoff'])}")
    where = f" where {' and '.join(mask)}" if mask else ""
    n = md.get("hc_mask_samples")
    # a default SWIRR, as the step's decision says it ("SWIRR_APP = 0.200 (default): only 3 hydrocarbon samples ...";
    # before Petrophys 3a9378e "SWIRR_APP = 0.200 fallback because ...")
    fallback = str(how or "").startswith("default") or any(
        d.startswith("SWIRR") and ("fallback" in d or "(default)" in d) for d in decisions)
    if fallback:
        why = f"only {int(n)} samples{where}" if _num(n) else (md.get("reason") or "reason not recorded")
        return f"{value}, a fallback default ({why})"
    if _num(md.get("percentile")):
        of = md.get("sw_curve") or "the saturation curve"
        return f"{value} = P{_f(md['percentile'])} of {of}{where}" + (f" (n={int(n)})" if _num(n) else "")
    return f"{value} ({how})" if how else value


def perm_fact(perm: dict, names: dict) -> Optional[str]:
    """How the record made PERM; None where it records nothing about it (a line saying only "method not recorded"
    adds nothing, and answers copied it into their limitations)."""
    if not perm:
        return None
    p = _params(perm)
    method = p.get("empirical_method")
    swirr = swirr_text(perm)
    clip = _num(p.get("perm_max_clip_md"))
    if not (method or swirr or clip):
        return None
    text = "PERM: " + (_name(names, method) if method else "method not recorded")
    if swirr:
        text += f" with {swirr}"
    if clip:
        text += f"; clipped <= {_f(p['perm_max_clip_md'])} mD"
    return text


def core_source(steps: dict, names: dict, well: str = "") -> Optional[str]:
    """Which core plugs the PHIE_CC/PERM_CC transform was fitted on, from the core models the record lists."""
    models = _params(last_step(steps, "permeability")).get("core_models") \
        or _params(last_step(steps, "core_correction")).get("core_models") or []
    kinds = []
    for m in models:
        kind = _name(names, m.get("source_type") or "core plugs (source type not recorded)")
        if kind not in kinds:
            kinds.append(kind)
    if not kinds:
        return None
    others = sorted({str(m["source_well"]) for m in models
                     if m.get("source_well") and _norm_well(m["source_well"]) != _norm_well(well)})
    return " and ".join(kinds) + (f" ({', '.join(others)})" if others else "")


def readers(steps: dict, curves: list[str]) -> list[str]:
    """'step (curves it wrote)' for each recorded step that read any of the curves (the record's inputs lists)."""
    out = []
    for key, rec in (steps or {}).items():
        if {c for i in (rec or {}).get("inputs") or [] for c in str(i).split("+")} & set(curves):
            wrote = (rec or {}).get("outputs") or []
            out.append(f"{key} ({', '.join(wrote[:4])}{', ...' if len(wrote) > 4 else ''})" if wrote else key)
    return out


def unmodelled_fact(view: FormationView, curve: str, unknown: bool = True) -> Optional[str]:
    """A curve no recorded step computed: what it is instead (supplied, or the same values as a supplied curve);
    with neither, "method not recorded" (None when not `unknown`)."""
    if not view.available(curve):
        return None
    origin = curve_origin(view, curve)
    if origin is None or origin[0] == "step":
        return None
    if origin[0] == "copy":
        return (f"{curve}: the same values as {origin[1]} (no model in the record), so the {curve} of record is the "
                f"supplied {origin[1]}")
    if origin[0] == "supplied":
        return f"{curve}: supplied in the LAS; no model in the record"
    return f"{curve}: method not recorded" if unknown else None


def mineral_fact(view, minerals: list) -> str:
    """The solver's mineral volumes as this interval has them - at how many samples the solver left values
    and which of its supports (the lithology log, PEF, RHOB) are present here - instead of a caveat that reads as if
    the supports were missing."""
    import numpy as np
    from petroharness.well.formation import MISSING_LITHOLOGY
    ok = np.zeros(int(view.mask.sum()), dtype=bool)
    for c in minerals:
        x = view.values(c)
        if x is not None:
            ok |= np.isfinite(np.asarray(x, dtype=float))
    labels = getattr(view, "labels", None)
    # a lithology log only where the zones come from one: shale-volume band labels are not a lithology log
    has_log = (getattr(view, "lithology_curve", None) is not None and labels is not None
               and any(str(v) != MISSING_LITHOLOGY for v in labels))
    sup = [n for n, on in (("the lithology log", has_log), ("PEF", view.available("PEF")), ("RHOB", view.available("RHOB")))
           if on]
    return (f"{', '.join(minerals)}: mineral-solver volumes, with values at {int(ok.sum())} of {ok.size} samples here (the "
            f"solver leaves the rest unsolved); a solver mix is non-unique on its own, and here "
            + (f"{(', '.join(sup[:-1]) + ' and ' + sup[-1]) if len(sup) > 1 else sup[0]} "
               f"{'is' if len(sup) == 1 else 'are'} present to support it" if sup else
               "none of the lithology log, PEF or RHOB is present to support it"))


def core_plugs(view) -> str:
    """The core itself beside the core-calibrated curves: each core plug curve with values here and its count (an
    answer about "the core" read the calibrated log curve)."""
    plugs = [c for c in ((view.reg.curves.get("core") or {}).get("curves") or []) if view.available(c)]
    counts = [(c, int(np.isfinite(np.asarray(view.values(c), dtype=float)).sum())) for c in plugs]
    counts = [(c, n) for c, n in counts if n]
    if not counts:
        return ""
    return ("; they are log curves fitted to the core, not the core: the plug measurements here are "
            + ", ".join(f"{c} ({n} plugs)" for c, n in counts))


def core_fact(available: bool, source: Optional[str], supplied: Optional[list] = None,
              readers: Optional[list] = None, plugs: str = "") -> str:
    head = "Core-calibrated curves (PHIE_CC, PERM_CC): "
    if supplied:
        return head + (f"{', '.join(supplied)} supplied in the LAS as core-corrected values, the calibrated data of record "
                       "(the workflow reads them, it does not compute them)"
                       + (f"; read by the steps {'; '.join(readers)}" if readers else ""))
    if available:
        return head + "available (transform fitted on " + (source or "core plugs; source not recorded") + ")" + plugs
    if source:
        return head + f"not available in this interval (the well's transform is fitted on {source})"
    return head + "not available (no core model fitted in this well)"


_FLAG_DECISION = re.compile(r"^(NET_ROCK|NET_RES|NET_PAY):\s*(\+\s*|(?:NET_ROCK|NET_RES)\s+and\s+)?(\S+)\s*(<=|>=|<|>)\s*(\S+)")
_FLAG_PARAMETER = {"NET_ROCK": "vcl_cutoff", "NET_RES": "phie_cutoff", "NET_PAY": "sw_cutoff"}


def _policy_phie(cut: dict) -> str:
    vals = [f"{k} {cut[f'phie_min_{k}']}" for k in ("clastic", "carbonate") if cut.get(f"phie_min_{k}") is not None]
    return f"policy {', '.join(vals)}" if vals else "no policy value"


def cutoff_fact(net_pay: dict, policy: dict) -> str:
    """The flag cutoffs as the net-pay step applied them (its decision lines), the curve each one tested, and the
    policy only where the record has no value (labelled)."""
    cut = (policy or {}).get("cutoffs", {}) or {}
    if not net_pay:
        return (f"Cutoffs (policy; no net-pay step in the record): NET_ROCK VCL<{cut.get('vcl_max')}; "
                f"NET_RES +PHIE above the lithology cutoff ({_policy_phie(cut)}); NET_PAY +SW<{cut.get('sw_max')}")
    p = _params(net_pay)
    parsed = {}
    for d in _decisions(net_pay):
        m = _FLAG_DECISION.match(d)
        if m and m.group(1) not in parsed:
            plus, curve, op, raw = m.groups()[1:]
            curve = bindings(d).get(curve, curve)            # "porosity" -> the curve the decision says it is
            parsed[m.group(1)] = (plus, curve, op, raw)
    parts = []
    for flag, key in _FLAG_PARAMETER.items():
        if flag in parsed:
            plus, curve, op, raw = parsed[flag]
            try:
                value = float(raw)
            except ValueError:
                value = None
            head = f"{flag} {'+' if plus else ''}{_curves(curve)}{op}"
        elif key in p:
            value, head = p.get(key), f"{flag} {key.replace('_', ' ')} "
        else:
            continue
        if _num(value):
            parts.append(f"{head}{_f(value)}")
        elif flag == "NET_RES":
            lith = p.get("lithology")
            basis = "per-depth lithology cutoff" if lith == "per-depth" else \
                (f"{lith} lithology cutoff" if isinstance(lith, str) and lith else "lithology cutoff")
            parts.append(f"{head}{basis} (not recorded; {_policy_phie(cut)})")
        else:
            parts.append(f"{head}cutoff (value not recorded)")
    return "Cutoffs: " + ("; ".join(parts) if parts else "not recorded")


def vcl_fact(vcl: dict, names: dict) -> Optional[str]:
    """The shale-volume estimates the record says were used, how it combined them (its vcl_rule parameter), the ones
    it computed but left out of VCL (sp_in_vcl, nd_in_vcl) and the GR endpoints applied."""
    if not vcl:
        return None
    p, decisions = _params(vcl), _decisions(vcl)
    used, unused, left = [], [], []
    if p.get("gr_method"):
        used.append(f"GR ({_name(names, p['gr_method'])})")
    for key, inside, label, curve in (("use_sp", "sp_in_vcl", "SP", "VCL_SP"),
                                      ("use_nd", "nd_in_vcl", "neutron-density", "VCL_ND")):
        if p.get(key) is True and p.get(inside) is False:
            left.append(curve)                     # computed, not in the combination
        elif p.get(key) is True:
            used.append(label)
        elif p.get(key) is False:
            unused.append(label)
    rule = p.get("vcl_rule") if isinstance(p.get("vcl_rule"), str) and p.get("vcl_rule").strip() else None
    listing = ", ".join(used[:-1]) + " and " + used[-1] if len(used) > 1 else "".join(used)
    if rule:
        text = f"VCL: {rule} at each depth, as the record states it" + (f" (from {listing})" if listing else "")
    elif not used:
        text = "VCL: method not recorded"
    elif len(used) == 1:
        text = f"VCL: {listing} estimate"
    elif any("min(available methods)" in d for d in decisions):
        text = f"VCL: minimum of {listing} estimates"
    else:
        text = f"VCL: from {listing} estimates (combination rule not recorded)"
    if left:
        text += f"; {' and '.join(left)} computed but left out of VCL"
    if unused:
        text += f" ({' and '.join(unused)} not used)"
    lo = p.get("gr_min_used") if _num(p.get("gr_min_used")) else p.get("gr_min")
    hi = p.get("gr_max_used") if _num(p.get("gr_max_used")) else p.get("gr_max")
    if _num(lo) and _num(hi):
        text += f"; GR endpoints {_f(lo)}–{_f(hi)} API"
    if not (rule or used or left or unused or (_num(lo) and _num(hi))):
        return None                                    # the record holds nothing about VCL: no line saying so
    return text


_EQUATION_NAME = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]+(?:\+[A-Z][A-Z0-9_]+)*)(?![A-Za-z0-9_(])")


def _dotted(params: dict, path: str):
    value = params
    for key in path.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def recorded_inputs(steps: dict, spec: dict) -> Optional[list[str]]:
    """The curves a derived curve was computed from, as the step record states them (rules/curves.yaml construction);
    None when the record does not state it, so nothing is assumed. Names in an equation are upper-case mnemonics;
    a composite PHIE+PHIT counts as its first curve (the second only fills gaps); a name the record shows to be one
    value for the well (e.g. SWIRR with a single recorded swirr) is a constant, not an input."""
    for alternative in spec.get("alternatives") or []:    # the wordings of different Petrophys builds, in turn
        got = recorded_inputs(steps, alternative)
        if got:
            return got
    for step in spec.get("steps", []):
        rec = last_step(steps, step)
        p = _params(rec)
        text = None
        if spec.get("parameter") and isinstance(_dotted(p, spec["parameter"]), str):
            text = _dotted(p, spec["parameter"])
        prefix = spec.get("decision")
        for d in (_decisions(rec) if prefix and text is None else []):
            clause = next((c for c in clauses(d) if c.startswith(prefix)), None)
            if clause is not None:
                text = clause[len(prefix):]
                text = text.split(spec["stop"])[0] if spec.get("stop") else text
                bound = bindings(d)                          # k/phi -> PERM/PHIE, as the decision says
                text = re.sub(r"(?<![A-Za-z0-9_])([a-z][a-z_]*)(?![A-Za-z0-9_(])", lambda w: bound.get(w.group(1), w.group(1)), text)
                break
        if text is None and spec.get("core_model"):
            fitted = [m for m in p.get("core_models") or [] if isinstance(m, dict) and m.get(spec["core_model"])]
            if fitted:
                text = " ".join(str(m.get("input_curve") or "") for m in fitted)
        if text is None and spec.get("parameters"):
            used = [c for key, curves in spec["parameters"].items() if p.get(key) not in (None, False, "", "none")
                    for c in curves]
            if used:
                return list(dict.fromkeys(used))
        if text is None:
            continue
        if spec.get("inputs"):
            return list(spec["inputs"])
        constants = {name for name, key in (spec.get("constants") or {}).items() if _num(p.get(key))}
        aliases = spec.get("aliases") or {}
        names = [m.group(1).split("+")[0] for m in _EQUATION_NAME.finditer(text)]
        return list(dict.fromkeys(aliases.get(n, n) for n in names if n not in constants)) or None
    return None


# ---------------------------------------------------------------------------
# Interval routes read from the computed curves
# ---------------------------------------------------------------------------

def sxo_route(view: FormationView, idx=None) -> str:
    """The SXO route in the interval (or the samples idx): the record's SXO method when the well used one method;
    otherwise (several methods, or no record) read from the curves: quicklook where SXO equals SW^(1/5). Water-bearing
    samples (SW and SXO both 1) fit either route, so they do not decide it (counting them would call the route
    quicklook on water-bearing rock where shallow resistivity was used, against the workflow's own routing). An
    interval with no other samples has no route to state ("none")."""
    sxo, sw = view.values("SXO"), view.values("SW")
    if sxo is None:
        return "none"
    if idx is not None:
        sxo = sxo[idx]
        sw = None if sw is None else sw[idx]
    if sxo.size == 0 or not np.isfinite(sxo).any():
        return "none"
    methods = _sxo_methods(_step(view, "saturation"))
    if len(methods) == 1:
        return "quicklook" if methods[0] in view.reg.curves.get("sxo_quicklook_methods", []) else "measured"
    if sw is None:
        return "none"
    ok = np.isfinite(sxo) & np.isfinite(sw) & (sw >= 0) & ~((sw >= 0.999) & (sxo >= 0.999))
    if not ok.any():
        return "none"
    quick = np.abs(sxo[ok] - sw[ok] ** 0.2) < 1e-3
    share = float(quick.mean())
    return "quicklook" if share >= 0.95 else ("measured" if share <= 0.05 else "mixed")


def invasion_route(view: FormationView) -> str:
    """Which resistivity pairs INVASION_RATIO is in this interval, read from the computed curves against the pairs the
    invasion step's record names (petroharness.record.routes; the record's fallback text can describe the well
    elsewhere): "RESM/RESD at 544 samples (a medium resistivity, where no shallow log is)"; "" when none is read."""
    from petroharness.record.routes import _pairs, invasion_counts
    c = invasion_counts(view)
    return _pairs(c) if c and c["n"] > c.get("other", 0) else ""


# ---------------------------------------------------------------------------
# Card sections
# ---------------------------------------------------------------------------

def _names(view: FormationView) -> dict:
    return view.reg.curves.get("method_names", {}) or {}



def provenance_facts(view: FormationView) -> list[str]:
    """One line per workflow choice that commonly matters to an answer, each read from the step record."""
    names, steps, reg = _names(view), view.prep.steps, view.reg
    sat, route = _step(view, "saturation"), sxo_route(view)       # the route in this interval, read from its curves
    facts = [
        rw_fact(_step(view, "rw"), view.values("RW")),
        saturation_fact(sat, names, reg.curves.get("sw_model_parameters", {}) or {}),
        sxo_fact(route, sat, names, reg.curves.get("sxo_quicklook_methods", []) or []),
        mhi_fact(_step(view, "mhi"), view.available("MHI"), route),
        (perm_fact(_step(view, "permeability"), names) if _step(view, "permeability")
         else unmodelled_fact(view, "PERM", unknown=False)),           # no permeability record: what PERM is instead
    ]
    core = ("PHIE_CC", "PERM_CC")
    supplied = [c for c in core if (curve_origin(view, c) or ("",))[0] == "supplied"]   # one reader: the inventory's
    if not supplied:                                  # supplied ones are inputs the map lists with their meaning
        facts.append(core_fact(view.available("PHIE_CC") or view.available("PERM_CC"),
                               core_source(steps, names, view.task.well), plugs=core_plugs(view)))
    minerals = [m for m in reg.curves.get("minerals", {}) if view.available(m)]
    if minerals:
        facts.append(mineral_fact(view, minerals))
    facts.append(cutoff_fact(_step(view, "net_pay"), view.policy))
    facts.append(vcl_fact(_step(view, "vclay"), names))
    return [f for f in facts if f]


# A step's record lines describe the whole well's run; they are shown as written, under one label, and the interval's
# own facts come from the step's output curves (interval_facts), not from rewriting the lines.
RECORD_LABEL = "record (the whole well's run; its counts are the well's)"


def interval_facts(view: FormationView, outputs) -> tuple[list[str], list[float]]:
    """What a step's output curves hold in this interval, read from the curves: each flag's samples set here (and
    their thickness); the range here of a step's one curve of values (a temperature, an Rw: the record's is the whole
    well's); an output with values at only part of the interval's samples; and, where the analyzers filled
    an output the step left empty (the view's values against its own_values), the step's samples and the analyzers'
    apart: the record may say the step did not compute a curve the interval holds. (lines, their numbers)."""
    from petroharness.well.summary import curve_kind
    n_all, step, unit = int(view.mask.sum()), float(view.step), view.depth_unit
    lines, nums = [], []
    outs = [str(o) for o in dict.fromkeys(outputs or ()) if view.available(str(o))]
    values = [c for c in outs if curve_kind(view, c).kind == "values"]
    if len(values) == 1:                               # a step that writes one curve of values (a temperature, an
        c = values[0]                                  #   Rw): its range here, as a flag gives its count (question
        x = np.asarray(view.values(c), dtype=float)    #   the record's range is the whole well's)
        if np.isfinite(x).any():
            lo, hi, u = float(np.nanmin(x)), float(np.nanmax(x)), (view.unit(c) or "").strip()
            lines.append(f"{c} from {fmt(sig(lo))} to {fmt(sig(hi))}{' ' + u if u else ''}")
            nums += [sig(lo), sig(hi)]
    for c in dict.fromkeys(str(o) for o in outputs or ()):
        if not view.available(c):
            continue
        x = np.asarray(view.values(c), dtype=float)
        have = int(np.isfinite(x).sum())
        own = view.own_values(c)
        k = have if own is None else int(np.isfinite(np.asarray(own, dtype=float)).sum())
        added = f" ({k} from the step; the analyzers add {have - k} where the step left it empty)" if have > k else ""
        if curve_kind(view, c).kind == "flag":         # by the shape of its values, as every tool reads it
            n = int(np.nansum(x > 0.5))
            lines.append(f"{c} set at {n} of {have} samples ({fmt(n * step)} {unit})" + added)
            nums += [n, have, sig(n * step)] + ([k, have - k] if added else [])
        elif 0 < have < n_all or added:
            lines.append(f"{c} has values at {have} of {n_all} samples" + added)
            nums += [have, n_all] + ([k, have - k] if added else [])
    return lines, nums
