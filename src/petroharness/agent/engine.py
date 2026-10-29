"""The framework under the tools: curve and zone selection, conditions, statistics (the one summary layer,
petroharness.well.summary), the shared output with its size limit (C4 describes the arguments, C7 frames the output)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from petroharness.agent.inventory import Inventory
from petroharness.agent.map import num
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)
from petroharness.well import summary as S

STATISTICS = S.STATISTICS          # every statistic the summary layer computes (and any percentile pNN)
WIDE_CHARS = 9000                  # room for every zone row (6,000 cut zone rows, even in the first
                                   #   look; the model spent steps re-fetching them and wrote "truncated" limitations)


def max_chars() -> int:
    return WIDE_CHARS


class ToolError(ValueError):
    pass


@dataclass
class Formation:
    inv: Inventory
    view: object                      # petroharness.well.view.FormationView
    store: object = None              # petroharness.record.sections.Store: the analyzer sections with every class run

    @property
    def depth(self) -> np.ndarray:
        return np.asarray(self.view.depth, dtype=float)              # the interval's samples, in the reporting unit


@dataclass
class Result:
    text: str                                         # what the model is shown: within the size limit, and when rows
    #   were cut from it, a last line naming them with the find that fetches them
    numbers: list = field(default_factory=list)       # every number of the result
    rows: list = field(default_factory=list)          # every (line, the numbers written into it), in order, the cut
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
    for w in want:
        if w in known:
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
    return out + [n for n, x in f.inv.curves.items() if x.copy_of == c and n != c]


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
        out.append(("parameter", f"parameter: one value for the whole well ({num(float(cv.well_value))})"))
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
    cache[c] = out
    return out


def status(f: Formation, c: str) -> str:
    """What a curve is and the cautions the record knows: 'measurement'; 'model output of the porosity step'; 'flag of
    the net_pay step'; 'model output of the analyzers'; 'copy of X'; then each caution ('uncalibrated: ...')."""
    cv = f.inv.curves[c]
    kind = _kind_word(cv)
    if cv.source == "copy" and cv.copy_of:
        head = f"copy of {cv.copy_of}"
    elif cv.source == "computed":
        head = f"{kind or 'model output'}" + (f" of the {cv.step} step" if cv.step else "")
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


# --- which samples --------------------------------------------------------------------------------------------------

_UNSIGNED = r"(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_NUMBER = r"[-+]?" + _UNSIGNED
_OPERAND = rf"(?:\|\s*[A-Za-z][A-Za-z0-9_]*\s*\||{_NUMBER}|[A-Za-z][A-Za-z0-9_]*)"
_SIDE = rf"{_OPERAND}(?:\s*[-+]\s*{_OPERAND})*"
_TERM = re.compile(rf"^\s*({_SIDE})\s*(<=|>=|==|!=|=|<|>)\s*({_SIDE})\s*$")
_WINDOW = re.compile(rf"^\s*(?:(?:depth|from)\s+)?({_NUMBER})\s*(?:-|–|to)\s*({_NUMBER})\s*(?:m|ft|feet|meters?|metres?)?\s*$", re.I)
_ZONE_TERM = re.compile(r"^\s*(Z\d+)(?:\s*(?:-|–|to)\s*Z?(\d+))?\s*$", re.I)
GRAMMAR = C.text("C4", "grammar")


def _side(f: Formation, text: str):
    """One side of a comparison: curves (DEPTH is the sample depth) and numbers added and subtracted."""
    toks = re.findall(rf"\|[A-Za-z][A-Za-z0-9_]*\||{_UNSIGNED}|[-+]|[A-Za-z][A-Za-z0-9_]*", text.replace(" ", ""))
    total, sign, used = None, 1.0, []
    for t in toks:
        if t in "+-":
            sign = -1.0 if t == "-" else 1.0
            continue
        if t.startswith("|"):                               # |DRHO|: the absolute value
            c = curve(f, t.strip("|"))
            used.append(c)
            v = np.abs(np.asarray(f.view.values(c), dtype=float))
        elif t[0].isalpha():
            if t.upper() == "DEPTH":
                v = f.depth
                used.append("DEPTH")
            else:
                c = curve(f, t)
                used.append(c)
                v = np.asarray(f.view.values(c), dtype=float)
        else:
            v = float(t)
        total = sign * v if total is None else total + sign * v
        sign = 1.0
    return total, used


@dataclass
class Selection:
    mask: np.ndarray                  # interval samples selected
    read: str                         # the condition as the tools read it back


def select(f: Formation, condition: str) -> Selection:
    """Terms joined by 'and' / 'or' ('and' binds first). A term is CURVE OP NUMBER, CURVE OP CURVE, or a name: a flag
    (set), a curve (has a value), an analyzer class (its runs)."""
    cond = str(condition).strip()
    if not cond:
        raise ToolError(f"the condition is empty; {GRAMMAR}")
    cond = re.sub(r"\babs\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\)", r"|\1|", cond, flags=re.I)          # abs(X) is |X|
    cond = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\s+(?:is\s+)?(?:finite|valid|present|available|defined|not null)\b",
                  r"\1", cond, flags=re.I)                                                      # "FZI finite": has a value
    n = f.depth.size
    total, reads = np.zeros(n, dtype=bool), []
    for part in re.split(r"\s+or\s+", cond, flags=re.I):
        both = np.ones(n, dtype=bool)
        for term in re.split(r"\s+and\s+", part, flags=re.I):
            hit = _TERM.match(term)
            if hit:
                (x, ux), op, (v, uv) = _side(f, hit.group(1)), hit.group(2), _side(f, hit.group(3))
                if not ux + uv:
                    raise ToolError(f"{term.strip()!r} compares no curve; {GRAMMAR}")
                op = "==" if op == "=" else op
                x, v = np.broadcast_to(np.asarray(x, dtype=float), (n,)), np.asarray(v, dtype=float)
                with np.errstate(invalid="ignore"):
                    m = {"<": x < v, "<=": x <= v, ">": x > v, ">=": x >= v, "==": x == v, "!=": x != v}[op]
                both &= m & np.isfinite(x) & np.isfinite(v)
                reads.append(None)
            else:
                sel = _named(f, term)
                both &= sel.mask
                reads.append(sel.read)
        total |= both
    single = len(reads) == 1 and reads[0] is not None              # one name alone reads back as what it means
    return Selection(total, reads[0] if single else cond)


def _named(f: Formation, term: str) -> Selection:
    """A name used as a term: a flag curve (flag > 0.5), an analyzer class (section:CLASS, or CLASS when one section
    has it), or a curve (where it has a value)."""
    t = term.strip()
    name = t.upper()
    w = _WINDOW.match(t)
    if w:                                               # a depth window, top-base
        top, base = sorted((float(w.group(1)), float(w.group(2))))
        return Selection((f.depth >= top - 1e-6) & (f.depth <= base + 1e-6), f"depth {num(top)}-{num(base)} {f.inv.depth_unit}")
    zt = _ZONE_TERM.match(t)
    if zt:                                              # a zone, or a range of zones
        lo = int(zt.group(1)[1:])
        hi = int(zt.group(2)) if zt.group(2) else lo
        m = np.zeros(f.depth.size, dtype=bool)
        for z in zones(f, [f"Z{i}" for i in range(lo, hi + 1)]):
            m[np.asarray(z.indices)] = True
        return Selection(m, f"in {zt.group(1).upper()}" + (f"-Z{hi}" if hi != lo else ""))
    if name in f.inv.curves and name in f.view.reg.flags:
        with np.errstate(invalid="ignore"):
            return Selection(np.asarray(f.view.values(name), dtype=float) > 0.5, f"{name} > 0.5")
    want_key, _, want_label = t.rpartition(":")
    want_key = re.sub(r"[:/\s]+", ".", want_key.strip())
    found = [(key, lab, rs) for key, sec in (f.store.sections.items() if f.store is not None else [])
             for lab, rs in sec.classes.items()
             if str(lab).strip().upper() == (want_label.strip().upper() if want_key else name)
             and (not want_key or want_key in (key, key.split(".", 1)[-1]))]
    if len(found) == 1:
        key, lab, rs = found[0]
        return Selection(_class_mask(f, rs), f"{lab} ({key})")
    if len(found) > 1:
        raise ToolError(f"{term!r} is a class in {len(found)} sections: {', '.join(k for k, _, _ in found)}; "
                        f"write section:{found[0][1]}")
    if want_key:
        raise ToolError(f"no class {want_label!r} in a section {want_key!r}")
    if name in f.inv.curves:
        return Selection(np.isfinite(np.asarray(f.view.values(name), dtype=float)), f"{name} has a value")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", t):
        raise ToolError(f"{term!r} is not a curve with data, a flag or an analyzer class here; {GRAMMAR}; "
                        f"curves with data: {', '.join(sorted(f.inv.curves))}")
    raise ToolError(f"cannot read {term!r}; {GRAMMAR}")


def _class_mask(f: Formation, rs) -> np.ndarray:
    """The zone samples inside a class's runs (the store's Run: zone, top, base)."""
    d = f.depth
    m = np.zeros(d.size, dtype=bool)
    by_id = {z.zone_id: z for z in f.view.zones}
    for r in rs:
        z = by_id.get(r.zone)
        if z is None:
            continue
        idx = np.asarray(z.indices)
        m[idx[(d[idx] >= r.top - 1e-6) & (d[idx] <= r.base + 1e-6)]] = True
    return m


def where(f: Formation, condition) -> Optional[Selection]:
    return select(f, condition) if condition else None


def restricted(f: Formation, c: str, sel: Optional[Selection]) -> np.ndarray:
    """A curve's interval values, missing outside the selection and where a flag is not computed (uncomputed)."""
    x = np.asarray(f.view.values(c), dtype=float)
    gone, _ = uncomputed(f, c)
    x = np.where(gone, np.nan, x) if gone.any() else x
    return x if sel is None else np.where(sel.mask, x, np.nan)


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
        for ln in (list(m.decisions_here) + list(m.decisions)) if m is not None else []:
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


# --- writing --------------------------------------------------------------------------------------------------------

CUT_GET = "get this result with find"      # the ledger writes the result's id for "this result"
KEPT = ("", None, "kept")                  # a row held out of the text whose get a shown line names (Out.keep)


class Out:
    """Text and the numbers it shows, written together: each line keeps the numbers formatted into it. A line cut from
    the text shown (the size limit) stays in the result, held under what it is (its curve, its zone or row id)."""

    def __init__(self, f: Formation):
        self.f, self.rows, self._pending = f, [], []          # rows: (line, its numbers)
        self.held = []                                        # per row: None (shown), or (label, id, what) when cut

    def v(self, x) -> str:                                    # a value
        self._pending.append(float(x))
        return num(float(x))

    def i(self, k) -> str:                                    # a count
        self._pending.append(int(k))
        return str(int(k))

    def pct(self, p) -> str:                                  # a share, one decimal
        self._pending.append(float(p))
        return f"{float(p):.1f}%"

    def depth(self, x) -> str:
        return f"{self.v(x)} {self.f.inv.depth_unit}"

    def span(self, top, base) -> str:
        return f"{self.v(top)}-{self.v(base)} {self.f.inv.depth_unit}"

    def zone(self, z) -> str:
        return f"{z.zone_id} {zone_name(z)} {self.span(z.top, z.base)}"

    def child(self) -> "Out":
        return Out(self.f)

    def add(self, line: str, child=None) -> None:
        """A line shown, with the numbers written into it (child: an Out whose numbers they are, or a list of them)."""
        nums = self._pending + (list(child) if isinstance(child, list) else child._pending if child is not None else [])
        self.rows.append((line, nums))
        self.held.append(None)
        self._pending = []

    def hold(self, line: str, child, key: tuple) -> None:
        """A line kept in the result but cut from the text shown; key (label, id, what) names it in the cut line."""
        self.add(line, child)
        self.held[-1] = key

    def keep(self, line: str, child=None) -> None:
        """A line kept in the result and not shown, whose get a shown line already names (a long run list: the line
        says how many runs it shows and the find that fetches every one); the cut line does not repeat it."""
        self.add(line, child)
        self.held[-1] = KEPT

    def add_numbers(self, line: str, numbers: list) -> None:
        """A line written elsewhere, with the numbers written into it."""
        self.add(line)
        self.rows[-1] = (line, list(self.rows[-1][1]) + [float(x) for x in numbers])

    def extend(self, other: "Out") -> None:
        self.rows += other.rows
        self.held += other.held

    @property
    def lines(self) -> list:
        return [ln for ln, _ in self.rows]

    @property
    def shown_chars(self) -> int:
        return sum(len(ln) + 1 for (ln, _), h in zip(self.rows, self.held) if h is None)

    @property
    def numbers(self) -> list:
        return [x for _, ns in self.rows for x in ns]

    def fit(self, rows: list, budget: int = None, what: str = "zones", label: str = "") -> None:
        """Add rows (id, line, its Out or numbers): shown while the shown text stays within budget, the rest held in
        the result (named at the end of the text, with the find that fetches them)."""
        budget = max_chars() if budget is None else budget
        used, over = self.shown_chars, False
        for rid, ln, child in rows:
            over = over or used + len(ln) + 1 > budget - 260         # room for the cut line
            if over:
                self.hold(ln, child, (label, rid, what))
                continue
            self.add(ln, child)
            used += len(ln) + 1

    def result(self) -> Result:
        """The text shown, within max_chars (a last guard holds the lines past it); when lines were held, a last line
        naming them and the find that fetches them. The result keeps every line and number."""
        held, used, cap, over = list(self.held), 0, max_chars(), False
        for k, (ln, _) in enumerate(self.rows):
            if held[k] is not None:
                continue
            over = over or used + len(ln) + 1 > cap - 80
            if over:
                held[k] = ("", None, "lines")
            else:
                used += len(ln) + 1
        while True:                                               # the cut line fits too
            note = cut_note([(ln, h) for (ln, _), h in zip(self.rows, held) if h is not None and h is not KEPT])
            shown = [k for k, h in enumerate(held) if h is None]
            if not note or not shown or used + len(note) <= cap:
                break
            held[shown[-1]] = ("", None, "lines")
            used -= len(self.rows[shown[-1]][0]) + 1
        text = "\n".join([ln for (ln, _), h in zip(self.rows, held) if h is None] + ([note] if note else []))
        return Result(text, self.numbers, list(self.rows))


_ZONE_ID = re.compile(r"(?<![A-Za-z0-9_])Z(\d+)(?![A-Za-z0-9_])")


def cut_note(held: list) -> str:
    """The last line of a text cut to its size limit: what is not shown (each curve's zones, the runs, rows or lines)
    and the find that fetches it from the result. held: [(line, (label, id, what))]."""
    if not held:
        return ""
    groups = {}                                                   # (what, ids) -> labels
    order = []
    loose = 0
    for ln, (label, rid, what) in held:
        if rid is None:
            loose += 1
            continue
        key = next((k for k in order if k[0] == (what, label)), None)
        if key is None:
            key = ((what, label), [])
            order.append(key)
        key[1].append(str(rid))
    parts = {}
    for (what, label), ids in order:
        zone_like = all(re.fullmatch(r"Z\d+", i) for i in ids)
        which = S.zone_ids(ids) if zone_like else (", ".join(ids) if len(ids) <= 6 else f"{ids[0]} to {ids[-1]} ({len(ids)})")
        parts.setdefault((what, which), []).append(label)
    said = [(what.format(ids=which) if "{ids}" in what else f"{what} {which}")
            + (f" of {', '.join(x for x in labels if x)}" if any(labels) else "") for (what, which), labels in parts.items()]
    if loose:
        said.append(f"the last {loose} lines")
    zs = sorted({f"Z{m}" for ln, _ in held for m in _ZONE_ID.findall(ln)}, key=lambda z: int(z[1:]))
    more = ""
    if zs and sum(len(ln) + 1 for ln, _ in held) > max_chars():      # more than one get returns: a zone at a time
        find, more = zs[0], f" (a zone at a time: {S.zone_ids(zs)})"
    elif zs:
        find = S.zone_ids(zs)
    else:
        words = [w for _, (label, rid, _) in held for w in ([label] if label else [str(rid)] if rid is not None else [])]
        heads = [m.group(1) for ln, (_, rid, _) in held if rid is None             # a line's first words
                 for m in [re.match(r"\s*([A-Za-z0-9_]+(?: [a-z]+)?)", ln)] if m]
        find = ", ".join(list(dict.fromkeys(w for w in words + heads if w))[:8])
    return (f"(not shown here, to keep within the size limit: {'; '.join(said)}; they are in this result: "
            f"{CUT_GET} \"{find}\"{more})")


# --- grouped how ----------------------------------------------------------------------------------------------------

def bases(f: Formation, zs: list = None) -> list:
    """Each zone, the zones pooled and the whole interval, in that order (petroharness.well.summary.bases)."""
    return S.bases(f.view, zs)


# --- measured how ---------------------------------------------------------------------------------------------------

def statistic(x: np.ndarray, name: str, log: bool = False) -> float:
    """One statistic of the finite samples (petroharness.well.summary.compute); log: percentiles on log10 values."""
    try:
        return S.statistic(x, S.statistic_name(name), log)
    except ValueError:
        raise ToolError(S.derivation(name)) from None


def statistics(names) -> tuple:
    """(the statistics asked for that the summary layer computes, n first, or None when none are: each curve then takes
    the default set; a line for each one it does not compute, saying how to derive it with calc)."""
    asked = list(dict.fromkeys(S.statistic_name(s) for s in (names or [])))
    good = [s for s in asked if S.known(s)]
    notes = [S.derivation(s) for s in asked if not S.known(s)]
    return (["n"] + [s for s in good if s != "n"] if good else None), notes   # n always: a mean of three samples says so


def kind(f: Formation, c: str) -> "S.Kind":
    """What curve c's values are, by their shape over the well (petroharness.well.summary.curve_kind)."""
    return S.curve_kind(f.view, c)


def codes(f: Formation, c: str) -> dict:
    """The labels the record gives curve c's class codes (the inventory's), {} when it gives none."""
    cv = f.inv.curves.get(c)
    return dict(getattr(cv, "codes", None) or {})


def no_codes(f: Formation, tool: str, *cs) -> None:
    """Class codes are labels, not quantities: a tool that averages, fits or screens values does not take them (by the
    shape of the values, summary.curve_kind); the error says where their shares are."""
    for c in cs:
        if c in f.inv.curves and kind(f, c).kind == "classes":
            raise ToolError(f"{c} holds class codes (labels, not quantities): {tool} of codes means nothing; its "
                            f"class shares are in stats {c}, and another curve class by class is stats <curve> where "
                            f"{c} == <code>")


def class_values(out: Out, x: np.ndarray, k, labels: dict, thick) -> str:
    """Class codes over one group: n of the group's samples, then each class present with its share of those with a
    value, its samples and its thickness (thick(code)); one value over the well: that value."""
    n, counts = S.class_counts(x, k.codes)
    head = f"n {out.i(n)} of {out.i(x.size)}"
    if k.kind == "one value":
        return head + (f", every value {S.code_text(k.codes[0], labels)}" if n else "")
    u = out.f.inv.depth_unit
    return head + "".join(f", class {S.code_text(c, labels)} {out.pct(100 * m / n)} ({out.i(m)} samples, "
                          f"{out.v(thick(c))} {u})" for c, m in counts)


def curve_statistics(f: Formation, c: str, asked) -> tuple:
    """(names, log) for a curve: the asked statistics or the default set, the geometric mean and log10 percentiles by
    the shape of the curve's values over the interval (petroharness.well.summary)."""
    x = np.asarray(f.view.values(c), dtype=float)
    return S.names(asked, x), S.log_shaped(x)


def flag_values(out: Out, x: np.ndarray, thick: float) -> str:
    """A flag over one group: n of the group's samples, how many are set, their share and thickness."""
    ok = np.isfinite(x)
    on = int((x[ok] > 0.5).sum())
    return (f"n {out.i(ok.sum())} of {out.i(x.size)}, set in {out.i(on)} samples "
            f"({out.pct(100 * on / ok.sum() if ok.any() else 0.0)} of those with a value), "
            f"thickness {out.v(thick)} {out.f.inv.depth_unit}")


def set_thickness(f: Formation, on: np.ndarray, kind: str, zs: list) -> float:
    """The thickness of the set samples of a basis, in the zones' convention (a zone's thickness x its share): the
    whole interval scales the gross; zones pooled add their zones."""
    if kind == "whole":
        return f.inv.gross * float(on.sum()) / max(on.size, 1)
    return float(sum(thickness(z, int(on[z.indices].sum())) for z in zs))


def values(out: Out, x: np.ndarray, d: np.ndarray, names, log: bool = False, at: bool = True, zone: bool = True) -> str:
    """Values of one curve over one group: n of the group's samples, the statistics, the depths of min and max (at),
    each with the zone its sample is in (zone; left out where every sample of the group lies outside the zones)."""
    parts = []
    ok = np.isfinite(x)
    got = S.compute(x, list(names), log)
    for s in names:
        v = got[s]
        if s == "n":
            parts.append(f"n {out.i(v)} of {out.i(x.size)}")
        elif np.isfinite(v):
            text = f"{s} {out.v(v)}"
            if s in ("min", "max") and at:
                where = float(d[ok][np.argmin(x[ok]) if s == 'min' else np.argmax(x[ok])])
                text += f" at {out.depth(where)}"
                if zone:
                    text += f" ({zone_at(out.f, where)})"    # which zone the sample is in
            parts.append(text)
    return ", ".join(parts)


def thickness(z, n: int) -> float:
    """n samples of zone z as thickness, the analyzer sections' convention: the zone's thickness x its share."""
    return z.thickness * n / max(z.n_samples, 1)


def extent(f: Formation, mask: np.ndarray, zs: list) -> list:
    """(top, base, samples, zone) for each run of consecutive selected samples inside one of the zones zs."""
    found = []
    for z in zs:
        idx = np.asarray(z.indices)
        on = mask[idx]
        k = 0
        while k < idx.size:
            if on[k]:
                j = k
                while j + 1 < idx.size and on[j + 1] and idx[j + 1] == idx[j] + 1:
                    j += 1
                found.append((float(f.depth[idx[k]]), float(f.depth[idx[j]]), j - k + 1, z))
                k = j + 1
            else:
                k += 1
    return sorted(found, key=lambda r: r[0])


def _ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    r = np.empty(x.size)
    r[order] = np.arange(x.size)
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)       # ties take their average rank
    return (np.bincount(inv, weights=r) / counts)[inv]


def rank_correlation(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    ra, rb = _ranks(a[ok]), _ranks(b[ok])
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def span_text(out: Out, x: np.ndarray) -> str:
    """A curve's range over the samples shown: 'min-max' ('min to max' when a value is negative)."""
    lo, hi = float(np.min(x)), float(np.max(x))
    return f"{out.v(lo)} to {out.v(hi)}" if lo < 0 or hi < 0 else f"{out.v(lo)}-{out.v(hi)}"


def coefficient_basis(out: Out, kind: str, k: int, ranges: list) -> str:
    """What a coefficient was computed on: its kind and transform, its n and each variable's range over the
    samples used; ranges: [(name, values used)]."""
    return f"({kind}; n {out.i(k)}; " + ", ".join(f"{n} {span_text(out, x)}" for n, x in ranges) + ")"


def pair(out: Out, xa: np.ndarray, xb: np.ndarray, a: str, b: str, same: bool, tolerance) -> str:
    """Two curves over one group: n of the group's samples where both have values, both means, a - b on one scale,
    the rank correlation with what it was computed on (its n, each curve's range, on ranks)."""
    ok = np.isfinite(xa) & np.isfinite(xb)
    if not ok.any():
        return f"n {out.i(0)} of {out.i(xa.size)}, no sample where both {a} and {b} have values"
    parts = [f"n {out.i(ok.sum())} of {out.i(xa.size)}", f"mean {a} {out.v(np.mean(xa[ok]))}",
             f"mean {b} {out.v(np.mean(xb[ok]))}"]
    if same:
        dd = xa[ok] - xb[ok]
        parts += [f"difference mean {out.v(np.mean(dd))}", f"sd {out.v(np.std(dd))}"]
        # which way the difference goes, and how often
        t = float(tolerance or 0.0)
        tt = num(t)
        parts.append(f"{a} > {b}{f' + {tt}' if t else ''} in {out.pct(100 * np.mean(dd > t))}, "
                     f"{a} < {b}{f' - {tt}' if t else ''} in {out.pct(100 * np.mean(dd < -t))}"
                     + (f", within {tt} in {out.pct(100 * np.mean(np.abs(dd) <= t))}" if t else
                        f", equal in {out.pct(100 * np.mean(dd == 0))}"))
    rc = rank_correlation(xa, xb)
    if np.isfinite(rc):
        parts.append(f"rank correlation {out.v(rc)} "
                     + coefficient_basis(out, "Spearman, on ranks", int(ok.sum()), [(a, xa[ok]), (b, xb[ok])]))
    return ", ".join(parts)


def line_fit(out: Out, x: np.ndarray, y: np.ndarray, names: tuple = None, raw: tuple = None) -> str:
    """A least-squares line y = intercept + slope * x over one group: n of the group's samples where both have values,
    slope, intercept, R2 and the correlation, with what the correlation was computed on (names: (y, x) as fitted, a
    transform in the name; raw: (y, x) values before any transform, whose ranges are shown); fewer than 3 samples or a
    constant x give no line."""
    ok = np.isfinite(x) & np.isfinite(y)
    n = int(ok.sum())
    if n < 3:
        return f"n {out.i(n)} of {out.i(x.size)} (too few samples for a line)"
    xs, ys = x[ok], y[ok]
    if np.ptp(xs) == 0:
        return f"n {out.i(n)} of {out.i(x.size)} (x is constant: no line)"
    slope, intercept = np.polyfit(xs, ys, 1)
    r = float(np.corrcoef(xs, ys)[0, 1]) if np.ptp(ys) > 0 else 0.0
    text = (f"n {out.i(n)} of {out.i(x.size)}, slope {out.v(slope)}, intercept {out.v(intercept)}, R2 {out.v(r * r)}, "
            f"correlation {out.v(r)}")
    if names:
        yn, xn = names
        ry, rx = raw if raw is not None else (y, x)
        bare = lambda s: s[6:-1] if s.startswith("log10(") else s
        text += " " + coefficient_basis(out, f"Pearson on {yn} and {xn}", n,
                                        [(bare(yn), np.asarray(ry)[ok]), (bare(xn), np.asarray(rx)[ok])])
        if bare(xn) == "DEPTH":                                      # a trend with depth, in words
            text += f"; {yn} {S.direction_words(r)}"
    return text


def together(rc: float, a: str, b: str) -> str:
    """A coefficient between two curves in words: '<a> higher where <b> is higher' (positive) or '... lower'."""
    if not np.isfinite(rc) or rc == 0:
        return f"no rank order between {a} and {b}"
    return f"{a} higher where {b} is {'higher' if rc > 0 else 'lower'}"
