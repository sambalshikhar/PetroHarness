"""Curves: their names as the record holds them, the zones asked for, what each curve is (its status, kind, codes,
cautions and limits) and where a flag was computed from an input with no value."""

from __future__ import annotations

import re
from typing import Optional
import numpy as np
from petroharness.agent.map import num
from petroharness.well import summary as S
from petroharness.agent.engine.base import Formation, ToolError


    #   ones too: the ledger's item holds them all (get and find read them)


# --- names ----------------------------------------------------------------------------------------------------------

def near(f: Formation, name: str) -> str:
    """The curves with data whose names are closest to a name that is not one (a typo: BWV for BVW)."""
    import difflib
    c = str(name).strip().upper()
    close = difflib.get_close_matches(c, list(f.inv.curves), n=3, cutoff=0.6)
    close += [k for k in f.inv.curves if c[:3] and k.startswith(c[:3]) and k not in close]
    return ", ".join(close[:4])


def known_names(f: Formation) -> set:
    """Names that are curves somewhere: in the well's LAS (any depth), in the registry, or measured-log families."""
    reg = f.view.reg
    out = {str(c).upper() for c in getattr(f.view.prep.well, "curves", {}) or {}}
    out |= set(getattr(reg, "raw_order", []) or [])
    out |= {str(k).upper() for k in (reg.curves.get("plain_meanings") or {})}
    out |= {str(k).upper() for k in (reg.curves.get("meanings") or {})}
    out |= {c for members in (reg.curves.get("families") or {}).values() for c in members}
    return out


def curve(f: Formation, name) -> str:
    c = str(name).strip().upper()
    if c not in f.inv.curves:
        # a misspelt name with one clear match is that curve
        import difflib
        hit = difflib.get_close_matches(c, list(f.inv.curves), n=2, cutoff=0.85)
        if len(hit) == 1 or (len(hit) == 2 and difflib.SequenceMatcher(None, c, hit[0]).ratio()
                             - difflib.SequenceMatcher(None, c, hit[1]).ratio() > 0.08):
            return hit[0]
        close = near(f, c)
        what = "has no data in this interval" if c in known_names(f) else "is not a curve here"
        raise ToolError(f"{name!r} {what}" + (f"; did you mean {close}?" if close else "")
                        + f"; curves with data: {', '.join(sorted(f.inv.curves))}")
    return c


def curves(f: Formation, names) -> list:
    out = list(dict.fromkeys(curve(f, c) for c in ([names] if isinstance(names, str) else (names or []))))
    if not out:
        raise ToolError(f"name at least one curve; curves with data: {', '.join(sorted(f.inv.curves))}")
    return out


def zones(f: Formation, asked) -> list:
    """The zones asked for, in the order asked (all zones when none are). ALL (or *) is every zone,
    and a lithology name (SILT, CROSSBEDDED SAND, SIL*) the zones of that lithology."""
    if not asked:
        return list(f.view.zones)
    want = list(dict.fromkeys(str(z).strip().upper() for z in ([asked] if isinstance(asked, str) else asked)))
    known = {z.zone_id.upper(): z for z in f.view.zones}
    if any(w in ("ALL", "*", "ALL ZONES", "POOLED", "ZONES POOLED") for w in want):
        return list(f.view.zones)
    out = []
    for w in want:                                   # a zone named twice (by its id and its lithology) is one row
        if w in known:
            if known[w].zone_id not in {o.zone_id for o in out}:
                out.append(known[w])
            continue
        lith = [z for z in f.view.zones if _lith_match(z, w)]
        if not lith:
            liths = sorted({zone_name(z).upper() for z in f.view.zones})
            raise ToolError(f"no zone {w}; zones: {', '.join(z.zone_id for z in f.view.zones)}; or a lithology: "
                            f"{', '.join(liths)}; or ALL")
        out += [z for z in lith if z.zone_id not in {o.zone_id for o in out}]
    return out


def _lith_match(z, w: str) -> bool:
    """A zone's lithology named in full, or by a prefix ending in '*' (SIL* for SILT)."""
    lith = zone_name(z).upper()
    w = re.sub(r"\s+", " ", w.replace("_", " ")).strip()
    return lith.startswith(w[:-1].strip()) if w.endswith("*") and len(w) > 1 else lith == w or lith.rstrip("S") == w.rstrip("S")


def zone_at(f: Formation, depth: float) -> str:
    """The id of the zone holding the sample at a depth (by the zones' samples, so a sample on a zone's base is in it),
    or 'between zones'."""
    d = f.depth
    if d.size:
        i = int(np.argmin(np.abs(d - depth)))
        if abs(d[i] - depth) <= 1e-6 * max(1.0, abs(depth)):
            for z in f.view.zones:
                idx = np.asarray(z.indices)
                if idx.size and idx[0] <= i <= idx[-1] and i in set(idx.tolist()):
                    return z.zone_id
            return "between zones"
    for z in f.view.zones:
        if z.top - 1e-4 <= depth <= z.base + 1e-4:
            return z.zone_id
    return "between zones"


def same_as(f: Formation, c: str) -> list:
    """The curves holding the same values as c, either way round (a copy, or a step that passed its input through)."""
    cv = f.inv.curves.get(c)
    out = [cv.copy_of] if cv is not None and cv.copy_of in f.inv.curves else []
    out += [n for n, x in f.inv.curves.items() if x.copy_of == c]
    return [n for n in dict.fromkeys(out) if n != c]          # each once (two curves each a copy of the other), not c


def label(f: Formation, c: str) -> str:
    """A curve's label line: its name, unit and meaning, then its status (status: what it is, and the cautions the
    record knows)."""
    cv = f.inv.curves[c]
    unit = f" [{cv.unit}]" if cv.unit else ""
    pct = "; values in percent" if cv.percent and "%" not in (cv.unit or "") else ""
    same = same_as(f, c)
    twin = f"; {', '.join(same)} {'holds' if len(same) == 1 else 'hold'} the same values" if same else ""
    return f"{c}{unit} = {cv.meaning} ({status(f, c)}{pct}{twin})"


# --- status: what a curve is, from the record and the curve catalog ---------------------------------------------------

_KIND = re.compile(r";\s*an? (measurement|model output|flag|class|parameter)\b")


_MNEMONIC = re.compile(r"\b[A-Z][A-Z0-9_]*[A-Z0-9]\b")


def _kind_word(cv) -> str:
    """What a curve is: the catalog line's kind (a measurement, a model output, a flag, a class, a parameter); without
    a catalog line, a measured log of the input is a measurement and a curve a step or analyzer wrote a model output."""
    m = _KIND.search(getattr(cv, "catalog", "") or "")
    if m and m.group(1) == "parameter" and getattr(cv, "well_value", None) is None and cv.source == "computed":
        return "model output"                      # the catalog's word, but its values vary with depth here
    if m:
        return m.group(1)
    if cv.source == "input":
        return "measurement" if cv.measured_log else "input curve"
    return "model output" if cv.source in ("computed", "analyzer") else ""


def from_curves(f: Formation, c: str) -> list:
    """The curves a derived curve is computed from, as the catalog line names them after its kind ('a flag from VCL,
    porosity and SW' -> VCL, SW), else the step's recorded inputs; names only (a fallback list is one input)."""
    cv = f.inv.curves[c]
    line = getattr(cv, "catalog", "") or ""
    m = _KIND.search(line)
    if m:
        tail = line[m.end():]
        k = tail.find(" from ")
        names = _MNEMONIC.findall(tail[k + 6:]) if k >= 0 else []
        known = known_names(f) | set(f.inv.curves)
        return [n for n in dict.fromkeys(names) if n in known and n != c]
    return [str(i) for i in (cv.inputs or []) if str(i) != c]


def direct_inputs(f: Formation, c: str) -> list:
    """The curves c is computed from: the mnemonics its catalog line names, and from each input the step recorded the
    one it used (a fallback group 'PHIE+PHIT' or 'SWIRR/SW': its first member that is a curve here)."""
    try:
        named = from_curves(f, c)
    except KeyError:
        return []
    used = []
    for group in (f.inv.curves[c].inputs or []):
        members = [m.strip() for m in re.split(r"[+/]", str(group)) if m.strip()]
        first = next((m for m in members if m in f.inv.curves), None)
        if first:
            used.append(first)
    return [x for x in dict.fromkeys(named + used) if x != c]


def computed_from(f: Formation, a: str, b: str, depth: int = 6) -> list:
    """The chain by which curve a is computed from curve b through the record's inputs ([a, ..., b]), shortest first;
    [] when a is not computed from b (or either is not a curve of the record)."""
    if a == b or a not in f.inv.curves or b not in f.inv.curves:
        return []
    seen, frontier = {a}, [[a]]
    for _ in range(depth):
        nxt = []
        for path in frontier:
            ins = direct_inputs(f, path[-1])
            for c in ins:
                if c == b:
                    return path + [b]
                if c not in seen and c in f.inv.curves:
                    seen.add(c)
                    nxt.append(path + [c])
        frontier = nxt
    return []


def calibrated_twin(f: Formation, c: str) -> Optional[str]:
    """The core-calibrated curve of the same quantity with data here: the curve whose catalog meaning is
    'core-calibrated' + this curve's meaning (PHIE_CC beside PHIE), else None."""
    cv = f.inv.curves[c]
    want = f"core-calibrated {cv.meaning}".lower()
    return next((y for y, yv in f.inv.curves.items() if y != c and str(yv.meaning).lower() == want), None)


def _quicklook(f: Formation) -> dict:
    """{curve: how it was made} for the curves the record computed by a quicklook transform in this interval (the
    registry's construction entries with a quicklook route; the route read from the step record and the curves)."""
    cache = f.__dict__.setdefault("_status_cache", {})
    if "quicklook" not in cache:
        out = {}
        spec = (f.view.reg.curves.get("construction") or {}) if f.view is not None else {}
        for c, entry in spec.items():
            src = (entry or {}).get("sxo_quicklook")
            if src and c in f.inv.curves:
                try:
                    from petroharness.record.card import sxo_route
                    route = sxo_route(f.view)
                except Exception:  # noqa: BLE001  (no step record: no route to state)
                    route = "none"
                if route == "quicklook":
                    out[c] = f"a quicklook transform of {', '.join(src)}, not a shallow-resistivity reading"
                elif route == "mixed":
                    out[c] = f"a quicklook transform of {', '.join(src)} at part of the samples"
        cache["quicklook"] = out
    return cache["quicklook"]


def _fallback_used(f: Formation, c: str) -> list:
    """[(input, used instead, samples, of)] for each fallback input of the step that wrote c ('PHIE+PHIT': PHIE where
    present, otherwise PHIT) whose later choice fed c at some of this interval's samples (c has a value where the first
    has none and a later one has)."""
    cv = f.inv.curves[c]
    if cv.source != "computed":
        return []
    from petroharness.record.card import _FALLBACK
    x = np.asarray(f.view.values(c), dtype=float)
    have = np.isfinite(x)
    out = []
    for name in cv.inputs or []:
        if not _FALLBACK.match(str(name)):
            continue
        first, *rest = re.split(r"[+/]", str(name))
        if first not in f.inv.curves and first not in known_names(f):
            continue
        a = np.asarray(f.view.values(first), dtype=float) if first in f.inv.curves else np.full(x.size, np.nan)
        for r in rest:
            if r not in f.inv.curves:
                continue
            b = np.asarray(f.view.values(r), dtype=float)
            k = int((have & ~np.isfinite(a) & np.isfinite(b)).sum())
            if k:
                out.append((first, r, k, int(have.sum())))
    return out


def cautions(f: Formation, c: str) -> list:
    """[(short tag, the full text)]: what the record knows that qualifies a curve's values here - a parameter (one value
    for the whole well), uncalibrated beside a core-calibrated twin, a quicklook transform or a quicklook input, a
    fallback input, not computed by the workflow (an analyzer's own computation), not computed here (a flag never set
    whose input has no value in this interval). From the record and the curve catalog, never from a curve's name."""
    cache = f.__dict__.setdefault("_status_cache", {}).setdefault("cautions", {})
    if c in cache:
        return cache[c]
    cv = f.inv.curves[c]
    out = []
    if getattr(cv, "well_value", None) is not None:
        out.append(("one value", f"one value over the whole well ({num(float(cv.well_value))})"))
    twin = calibrated_twin(f, c)
    if twin and twin not in same_as(f, c):                      # a twin holding the same values calibrates nothing
        out.append(("uncalibrated", f"uncalibrated: the core-calibrated {twin} is in this interval"))
    quick = _quicklook(f)
    if c in quick:
        out.append(("quicklook", f"quicklook: {quick[c]}"))
    else:
        via = [q for q in quick if q in from_curves(f, c)]
        if via:
            out.append(("quicklook input", f"from a quicklook input: {', '.join(via)}"))
    for first, used, k, n in _fallback_used(f, c):
        out.append(("fallback input", f"fallback input: {used} where {first} has no value, at {k} of {n} samples here"))
    derived = {str(x).upper() for x in ((f.view.reg.curves.get("inventory") or {}).get("derived") or [])} \
        if f.view is not None else set()
    if cv.source == "analyzer" and c in derived:
        out.append(("not computed by the workflow", "not computed by the workflow: an analyzer's own computation"))
    if _kind_word(cv) == "flag" and f.view is not None:
        x = np.asarray(f.view.values(c), dtype=float)
        lacking = [i for i in from_curves(f, c) if i not in f.inv.curves]
        if lacking and np.isfinite(x).any() and not (x[np.isfinite(x)] > 0.5).any():
            out.append(("not computed here", f"not computed here: {', '.join(lacking)} "
                                             f"{'has' if len(lacking) == 1 else 'have'} no value in this interval, and "
                                             f"the flag is never set"))
    said = S.screened(f.view, c) if f.view is not None else ""
    if said:                                                    # readings the preparation removed (Petrophys's record)
        out.append(("screened", said))
    cache[c] = out
    return out


LIMIT_SHARE = 0.05          # a curve at its own maximum or minimum on at least this share of the zoned samples


HELD_SHARE = 0.5            # one value (not a bound) on at least this share of them: a held or padded reading


def limits(f: Formation, c: str) -> list:
    """What the zoned values of a value curve show about how they were made: constant (one value in every zoned sample),
    held at its maximum or minimum on at least LIMIT_SHARE of the zoned samples (a model's limit or a default), or one
    value inside its range on at least HELD_SHARE of them (a held or padded reading). From the values alone; [] for a
    flag or class codes, or a curve without values in the zones."""
    if f.view is None or not f.view.zones or c not in f.inv.curves or _kind_word(f.inv.curves[c]) in ("flag", "class"):
        return []
    idx = np.unique(np.concatenate([np.asarray(z.indices) for z in f.view.zones]))
    x = np.asarray(f.view.values(c), dtype=float)[idx]
    x = x[np.isfinite(x)]
    if x.size < 5:
        return []
    lo, hi = float(x.min()), float(x.max())
    if hi == lo:
        return [f"constant: {num(hi)} in every zoned sample"]
    out = []
    for v, word in ((hi, "maximum"), (lo, "minimum")):
        share = float((x == v).mean())
        if share >= LIMIT_SHARE:
            out.append(f"at its {word} {num(v)} in {100 * share:.0f}% of the zoned samples (a limit or a default value)")
    vals, counts = np.unique(x, return_counts=True)            # one value inside the range, at most of the samples
    k = int(np.argmax(counts))
    if counts[k] / x.size >= HELD_SHARE and float(vals[k]) not in (lo, hi):
        out.append(f"one value, {num(float(vals[k]))}, in {100 * counts[k] / x.size:.1f}% of the zoned samples (a held "
                   f"or padded reading)")
    return out


def provenance(f: Formation, curves) -> str:
    """One line per curve: what it is (its label: meaning, status and the record's cautions) and what its zoned values
    show about how they were made (limits); the curves in the order given, those of this interval only."""
    lines = []
    for c in dict.fromkeys(curves):
        if c not in f.inv.curves:
            continue
        extra = limits(f, c)
        lines.append(f"- {label(f, c)}" + (f"; {'; '.join(extra)}" if extra else ""))
    return "\n".join(lines)


def status(f: Formation, c: str) -> str:
    """What a curve is and the cautions the record knows: 'measurement'; 'model output of the porosity step'; 'flag of
    the net_pay step'; 'model output of the analyzers'; 'copy of X'; then each caution ('uncalibrated: ...')."""
    cv = f.inv.curves[c]
    kind = _kind_word(cv)
    if cv.source == "copy" and cv.copy_of:
        head = f"copy of {cv.copy_of}"
    elif cv.carried:                                   # a measured log the workflow carried (the inventory says how)
        head = cv.carried
    elif cv.source == "computed":
        head = f"{kind or 'model output'}" + (f" of {cv.writer}" if cv.writer else "")
    elif cv.source == "analyzer":
        head = f"{kind or 'model output'} of the analyzers"
    elif cv.source == "input":
        head = kind if kind in ("measurement", "input curve") else f"{kind}, supplied in the input"
    else:
        head = kind or str(cv.source)
    return "; ".join([head] + [text for _, text in cautions(f, c)])


def tagged(f: Formation, c: str) -> str:
    """A curve's name as a value line writes it: with its short cautions ('PHIE (uncalibrated)'), else the name."""
    tags = [t for t, _ in cautions(f, c)] if c in f.inv.curves else []
    return f"{c} ({', '.join(tags)})" if tags else c


def zone_name(z) -> str:
    return "no lithology data" if z.lithology.upper() == "NO_LITHOLOGY_DATA" else z.lithology


_UNIT = {"v/v": "fraction", "frac": "fraction", "fraction": "fraction", "dec": "fraction", "decimal": "fraction",
         "ft3/ft3": "fraction", "m3/m3": "fraction", "cm3/cm3": "fraction", "cfcf": "fraction",
         "md": "md", "%": "percent", "pu": "percent", "percent": "percent"}


def same_scale(f: Formation, a: str, b: str) -> bool:
    """Whether a - b means something: the same unit (fraction, mD, ...) and both in percent or neither."""
    ca, cb = f.inv.curves[a], f.inv.curves[b]
    ua, ub = (_UNIT.get((c.unit or "").strip().lower(), (c.unit or "").strip().lower()) for c in (ca, cb))
    return ua == ub and bool(ua) and ca.percent == cb.percent


# --- a flag computed from an input with no value ---------------------------------------------------------------------

_RECORD_LINE = re.compile(r"^(?P<name>[A-Z][A-Z0-9_]*):\s*(?P<plus>\+)?\s*(?P<cond>.*?)\s*->")


def flag_inputs(f: Formation, c: str) -> list:
    """What a flag or class the workflow wrote is computed from, as groups of fallbacks: the curves its step's record
    line for it names ("NET_PAY:  + SW < 0.7 -> ..." names SW; a line that starts with "+" adds to the line above it;
    "PHIE+PHIT" is PHIE where present, otherwise PHIT), and the record's flags its catalog line names (a flag from
    NET_PAY). [] for anything else: a curve of values is missing itself where its inputs are."""
    cache = f.__dict__.setdefault("_flag_inputs", {})
    if c in cache:
        return cache[c]
    cv, out = f.inv.curves.get(c), []
    if cv is not None and cv.source == "computed" and kind(f, c).kind != "values":
        known = known_names(f) | set(f.inv.curves)
        m = next((m for m in f.inv.methods if m.step == cv.step), None)
        lines, prev = [], []
        for ln in dict.fromkeys(list(m.decisions_here) + list(m.decisions)) if m is not None else []:   # each once
            hit = _RECORD_LINE.match(str(ln))
            if not hit:
                continue
            groups = [t.split("+") for t in re.findall(r"[A-Za-z][A-Za-z0-9_]*(?:\+[A-Za-z][A-Za-z0-9_]*)*", hit["cond"])
                      if all(p.upper() in known for p in t.split("+"))]
            groups = (prev if hit["plus"] else []) + groups
            lines.append((hit["name"], groups))
            prev = groups
        out = next((g for name, g in lines if name == c), [])
        flags = set(f.view.reg.curves.get("flags") or [])
        out += [[x] for x in re.findall(r"[A-Z][A-Z0-9_]+", cv.catalog or "") if x in flags and x != c and x in f.inv.curves]
    cache[c] = out
    return out


def uncomputed(f: Formation, c: str, _seen: tuple = ()) -> tuple:
    """(mask, why): the interval samples where flag c is not computed, because an input it is computed from
    (flag_inputs) has no value there (no curve of a fallback group has one) or is a flag not computed there; why: each
    reason with its samples, [("SW has no value", mask), ("NET_PAY is not computed", mask)], an input flag's only where
    it adds samples. The record's value there is a default, not a reading. Nothing for any other curve."""
    cache = f.__dict__.setdefault("_uncomputed", {})
    if c in cache:
        return cache[c]
    n = f.depth.size
    mask, why = np.zeros(n, dtype=bool), []
    for group in flag_inputs(f, c):
        if len(group) == 1 and group[0] in f.inv.curves and flag_inputs(f, group[0]) and group[0] not in _seen + (c,):
            sub = uncomputed(f, group[0], _seen + (c,))[0] & ~mask                # an input flag not computed
            reason = f"{group[0]} is not computed"
        else:
            have = np.zeros(n, dtype=bool)
            for g in group:
                x = f.view.values(g)
                if x is not None:
                    have |= np.isfinite(np.asarray(x, dtype=float))
            sub, reason = ~have, f"{' or '.join(group)} has no value"
        if sub.any():
            mask |= sub
            why.append((reason, sub))
    cache[c] = (mask, why)
    return cache[c]


def not_computed(f: Formation, c: str, idx) -> str:
    """'not computed (SW has no value)' when flag c is not computed at every one of the samples idx, with the reasons
    that hold there; '' otherwise."""
    gone, why = uncomputed(f, c)
    idx = np.asarray(idx)
    if not why or not idx.size or not gone[idx].all():
        return ""
    return f"not computed ({'; '.join(r for r, m in why if m[idx].any())})"


def uncomputed_note(f: Formation, c: str) -> str:
    """A label's note on where flag c is not computed in this interval ('' where it is computed everywhere)."""
    gone, why = uncomputed(f, c)
    if not gone.any():
        return ""
    return (f"not computed at {int(gone.sum())} of {gone.size} samples of this interval, where "
            f"{' or '.join(r for r, _ in why)} (the record's value there is a default, not a reading)")


def index_not_computed(f: Formation, sec) -> str:
    """Why a section classified nothing here ('' when it did): every class it gives is a label of a sample not assessed
    (rules/checks.yaml not_assessed) and its method names a curve with no value in this interval, or says an input was
    unavailable. Its thresholds then apply to nothing here."""
    cfg = f.view.reg.checks.get("not_assessed") or {}
    labels = [c.name for c in sec.classes]
    if not cfg or not labels or not all(re.match(cfg["labels"], x) for x in labels):
        return ""
    text, known = f"{sec.method or ''} {sec.basis or ''}", known_names(f) | set(f.inv.curves)
    missing = [t for t in dict.fromkeys(re.findall(r"[A-Z][A-Z0-9_]*", text)) if t in known and not f.view.available(t)]
    if missing:
        return (f"the index they classify was not computed: {', '.join(missing)} {'has' if len(missing) == 1 else 'have'} "
                f"no value in this interval")
    if re.search(cfg["unavailable"], text, re.I):
        return "the index they classify was not computed: its input was unavailable here, as the method line says"
    return ""


def uncomputed_said(f: Formation, text: str) -> str:
    """'; NET_PAY not computed at 11 of 518 samples (SW has no value)' for each flag a condition names that is not
    computed somewhere here, said short on the line that reads the condition (its stats label says it in full); ''
    when there is none."""
    out = ""
    for t in dict.fromkeys(x.upper() for x in re.findall(r"[A-Za-z][A-Za-z0-9_]*", str(text or ""))):
        gone, why = uncomputed(f, t) if t in f.inv.curves else (None, [])
        if why:
            out += f"; {t} not computed at {int(gone.sum())} of {gone.size} samples ({' or '.join(r for r, _ in why)})"
    return out


def kind(f: Formation, c: str) -> "S.Kind":
    """What curve c's values are, by their shape over the well (petroharness.well.summary.curve_kind)."""
    return S.curve_kind(f.view, c)


def codes(f: Formation, c: str) -> dict:
    """The labels the record gives curve c's class codes (the inventory's), {} when it gives none."""
    cv = f.inv.curves.get(c)
    return dict(getattr(cv, "codes", None) or {})
