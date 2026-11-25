"""Which samples: the condition grammar (terms, chains, percentiles, zones, depth windows, class names) and the
selection it gives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
import numpy as np
from petroharness.agent.map import num
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)
from petroharness.agent.engine.base import Formation, ToolError
from petroharness.agent.engine.curves import curve, uncomputed, zone_name, zones


# --- which samples --------------------------------------------------------------------------------------------------

_UNSIGNED = r"(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


_NUMBER = r"[-+]?" + _UNSIGNED


_OPERAND = rf"(?:\|\s*[A-Za-z][A-Za-z0-9_]*\s*\||{_NUMBER}|[A-Za-z][A-Za-z0-9_]*)"


_SIDE = rf"{_OPERAND}(?:\s*[-+]\s*{_OPERAND})*"


_TERM = re.compile(rf"^\s*({_SIDE})\s*(<=|>=|==|!=|=|<|>)\s*({_SIDE})\s*$")


_WINDOW = re.compile(rf"^\s*(?:(?:depth|from)\s+)?({_NUMBER})\s*(?:-|–|to)\s*({_NUMBER})\s*(?:m|ft|feet|meters?|metres?)?\s*$", re.I)


_ZONE_TERM = re.compile(r"^\s*(?:in\s+)?(Z\d+)(?:\s*(?:-|–|to)\s*Z?(\d+))?\s*$", re.I)


_ZONE_WRITTEN = re.compile(r"^\s*(?:in\s+)?(Z\d+)\b\s*(.+?)\s*$", re.I)       # a zone with its name or depths


_DEPTHS_WRITTEN = re.compile(rf"{_NUMBER}\s*(?:-|–|—|to)\s*{_NUMBER}\s*(?:m|ft|feet|meters?|metres?)?", re.I)


_CHAIN = re.compile(rf"^\s*({_SIDE})\s*(<=|>=|<|>)\s*({_SIDE})\s*(<=|>=|<|>)\s*({_SIDE})\s*$")


# |X| as the absolute value (bars around a name, not beside another name; or before / after a comparison), so the
# bars left are 'or': "SW < 1 | SW == 1", "Z1|Z4|Z6", "CLASS_A | CLASS_B"
_ABS_BARS = re.compile(r"(?<![A-Za-z0-9_.])\|([A-Za-z][A-Za-z0-9_]*)\|(?![A-Za-z0-9_])"
                       r"|\|\s*([A-Za-z][A-Za-z0-9_]*)\s*\|(?=\s*(?:<=|>=|==|!=|=|<|>))")


GRAMMAR = C.text("C4", "grammar")


# an op written in words, as its sign (a tool's op argument, a condition's term: one table)
OP_WORDS = {"gt": ">", "greater": ">", "greater than": ">", "more than": ">", "above": ">", "exceeds": ">",
            "ge": ">=", "gte": ">=", "at least": ">=", "greater than or equal to": ">=",
            "lt": "<", "less": "<", "less than": "<", "below": "<",
            "le": "<=", "lte": "<=", "at most": "<=", "less than or equal to": "<="}


_OP_WORD_IN = re.compile(r"\s+(?:is\s+)?(" + "|".join(sorted((k.replace(" ", r"[\s_]+") for k in OP_WORDS), key=len,
                                                             reverse=True)) + r")\s+(?=[-+.\d|A-Za-z])", re.I)


def op_sign(word) -> Optional[str]:
    """An op written in words ("lt", "less_than", "at least") as its sign; None when it names none."""
    return OP_WORDS.get(re.sub(r"[\s_\-]+", " ", str(word)).strip().lower())


def _connectives(cond: str) -> str:
    """'and' / 'or' written as symbols (& &&, | ||), the bars of an absolute value kept."""
    held = []

    def keep(m) -> str:
        held.append(m.group(1) or m.group(2))
        return f"\x00{len(held) - 1}\x00"
    s = _ABS_BARS.sub(keep, cond)
    s = re.sub(r"\s*(?:\|\||\|)\s*", " or ", s)
    s = re.sub(r"\s*(?:&&|&)\s*", " and ", s)
    return re.sub("\x00(\\d+)\x00", lambda m: f"|{held[int(m.group(1))]}|", s)


def _terms(term: str) -> list:
    """One term as the grammar reads it: an op in words as its sign ("RXO_RDEP_RATIO below 0.95"); a band written as
    a chain ("0.2 <= VCL <= 0.5", "0.5 > SW > 0.2") as its two comparisons."""
    if not re.search(r"[<>=]", term):
        term = _OP_WORD_IN.sub(lambda m: f" {op_sign(m.group(1))} ", term, count=1)
    c = _CHAIN.match(term)
    if c and {c.group(2)[0], c.group(4)[0]} in ({"<"}, {">"}):
        return [f"{c.group(1)} {c.group(2)} {c.group(3)}", f"{c.group(3)} {c.group(4)} {c.group(5)}"]
    return [term]


_PERCENTILE = re.compile(r"(?<![A-Za-z0-9_.])(?:[pP](\d{1,2})(?![A-Za-z0-9_.])|(?:(?:its|the)\s+)?(\d{1,2})(?:st|nd|rd|th)"
                         r"\s+percentile(?:\s+of\s+[A-Za-z][A-Za-z0-9_]*)?)", re.I)


def _percentile_term(f: Formation, term: str) -> tuple:
    """A term comparing a curve with one of its own percentiles ("GR < p25", "GR below its 25th percentile"): the
    percentile over the samples the call reads, as the tools compute it (well.stats.percentile), written in its place.
    (term, a note naming the value) - the term as written where it names no one curve. "GR < p25" had
    no form, and the model filtered on another number than the p25 it then quoted; N4 wrote "GR < <p25>"."""
    m = _PERCENTILE.search(term)
    if not m:
        return term, ""
    # in the order written: a word that is no curve is named as the first such word, in every process (a set's order
    # changes with the hash seed, and a replayed request then differs from the recorded one)
    names = list(dict.fromkeys(x.upper() for x in re.findall(r"[A-Za-z][A-Za-z0-9_]*", _PERCENTILE.sub(" ", term))
                               if x.lower() not in ("its", "the", "of", "percentile", "below", "above")))
    names = list(dict.fromkeys(curve(f, x) for x in names if x != "DEPTH"))
    if len(names) != 1:
        return term, ""
    c, q = names[0], int(m.group(1) or m.group(2))
    from petroharness.well.stats import percentile
    v = percentile(np.asarray(f.view.values(c), dtype=float), q)
    if not np.isfinite(v):
        raise ToolError(f"{term.strip()!r}: {c} has no values here to take its p{q}")
    return _PERCENTILE.sub(num(v), term, count=1), f"p{q} of {c} = {num(v)}"


def _zone_written(f: Formation, t: str) -> Optional[str]:
    """A zone as the harness writes it, its id with its own name and / or depths ("Z1 LIMESTONE_GROUP_1",
    "Z12 (SILT_GROUP_14)", "Z1 LIMESTONE 8182-8350 ft"): the id; None for anything else after the id."""
    m = _ZONE_WRITTEN.match(t)
    if not m:
        return None
    z = next((z for z in f.view.zones if z.zone_id.upper() == m.group(1).upper()), None)
    if z is None:
        return None
    norm = lambda x: re.sub(r"[\s_]+", " ", x).strip(" ,;:()[]").upper()
    rest = norm(_DEPTHS_WRITTEN.sub(" ", m.group(2)))
    return z.zone_id if rest in ("", norm(zone_name(z)), norm(z.lithology)) else None


def _depth_limit(f: Formation, hit, x, ux: list, v, uv: list, op: str) -> tuple:
    """DEPTH compared with a number written with decimals: the number is the sample it rounds to, as a range's limit is
    (selection.round_limit), so "DEPTH >= TOP and DEPTH <= BASE" (or "TOP <= DEPTH") and the window "TOP-BASE" select
    the same samples. (x, v) as given otherwise."""
    from petroharness.agent.selection import round_limit
    if op not in ("<", "<=", ">", ">="):
        return x, v
    left, right = hit.group(1).strip(), hit.group(3).strip()
    if ux == ["DEPTH"] and not uv and re.fullmatch(_UNSIGNED, right):         # DEPTH >= number: a lower limit
        return x, round_limit(right, f.view, float(v), "top" if op in (">", ">=") else "base")
    if uv == ["DEPTH"] and not ux and re.fullmatch(_UNSIGNED, left):          # number <= DEPTH: the same, mirrored
        return round_limit(left, f.view, float(x), "top" if op in ("<", "<=") else "base"), v
    return x, v


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
    cond = re.sub(r"\s*\(p\d{1,2} of [A-Za-z0-9_]+ = [^()]*\)\s*$", "", cond)       # its own read-back's note
    cond = re.sub(r"\babs\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\)", r"|\1|", cond, flags=re.I)          # abs(X) is |X|
    cond = _connectives(cond)
    cond = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\s+(?:is\s+)?(?:finite|valid|present|available|defined|not null"
                  r"|has\s+(?:a\s+)?values?)(?![A-Za-z0-9_])", r"\1", cond, flags=re.I)           # "FZI finite": has a value
    n = f.depth.size
    total, reads, notes = np.zeros(n, dtype=bool), [], []
    for part in re.split(r"\s+or\s+", cond, flags=re.I):
        both = np.ones(n, dtype=bool)
        for term in (t for written in re.split(r"\s+and\s+", part, flags=re.I) for t in _terms(written)):
            term, said = _percentile_term(f, term)
            if said:
                notes.append(said)
            term = _unit_number(f, term)
            hit = _TERM.match(term)
            if hit:
                (x, ux), op, (v, uv) = _side(f, hit.group(1)), hit.group(2), _side(f, hit.group(3))
                if not ux + uv:
                    raise ToolError(f"{term.strip()!r} compares no curve; {GRAMMAR}")
                op = "==" if op == "=" else op
                x, v = _depth_limit(f, hit, x, ux, v, uv, op)
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
    return Selection(total, (reads[0] if single else cond) + (f" ({'; '.join(notes)})" if notes else ""))


_UNIT_AFTER = re.compile(rf"^(?P<left>.*?(?:<=|>=|==|!=|=|<|>)\s*)(?P<num>-?{_UNSIGNED})\s*(?P<unit>[A-Za-z%][A-Za-z0-9/%.]*)\s*$")


def _unit_number(f: Formation, term: str) -> str:
    """A term whose number is written with a unit ("GR > 100 API", "DTC > 330 us/m", "DEPTH > 9500 ft"): the number in
    the compared curve's unit (DEPTH: the reporting unit), converted by Petrophys (conversion_factor: gAPI and
    API are one unit); a unit that does not convert to it is refused, naming the curve's unit (before,
    "GR > 100 API" was refused as a term the grammar could not read)."""
    m = _UNIT_AFTER.match(term)
    if not m or m.group("unit").lower() in ("and", "or", "not"):
        return term                                   # no unit (a word of the grammar left over is refused as written)
    names = [x.upper() for x in re.findall(r"[A-Za-z][A-Za-z0-9_]*", m.group("left"))]
    if len(set(names)) != 1:
        return term                                   # no one curve to read the unit against: as written
    c = names[0]
    if c == "DEPTH":
        target = f.inv.depth_unit
    elif c in f.inv.curves:
        target = f.inv.curves[c].unit or f.view.unit(c) or ""
    else:
        return term                                   # the name is refused where it is read
    from petrophys.preprocessing.standardization.unit_converter import conversion_factor
    factor = conversion_factor(m.group("unit"), target) if target else None
    if factor is None:
        raise ToolError(f"{term.strip()!r}: {c} is in {target or 'no unit'}; write the number in {target or 'its unit'}, "
                        "or without a unit")
    return f"{m.group('left')}{float(m.group('num')) * factor:.10g}"


def _named(f: Formation, term: str) -> Selection:
    """A name used as a term: a flag curve (flag > 0.5), an analyzer class (section:CLASS, or CLASS when one section
    has it), or a curve (where it has a value)."""
    t = term.strip()
    held = re.fullmatch(r"(.+?)\s*\(\s*([A-Za-z_][\w.]*)\s*\)", t)       # a class as results write it: CLASS (section)
    if held and f.store is not None and any(held.group(2) in (k, k.split(".", 1)[-1]) for k in f.store.sections):
        t = f"{held.group(2)}:{held.group(1)}"
    t = _zone_written(f, t) or t                         # a zone with its own name or depths: the zone
    name = t.upper()
    w = _WINDOW.match(t)
    if w:                                               # a depth window, top-base: read as every range is
        from petroharness.agent.selection import _rounded_limits, parse_range    # (selection: units, the samples)
        text = re.sub(r"^\s*(?:depth|from)\s+", "", t, flags=re.I)
        try:
            span = parse_range(text, f.view)
        except ValueError as e:
            raise ToolError(str(e)) from None
        if span is not None:
            top, base = _rounded_limits(text, f.view, *span)
            return Selection((f.depth >= top - 1e-6) & (f.depth <= base + 1e-6),
                             f"depth {num(span[0])}-{num(span[1])} {f.view.report_unit}")
        top, base = sorted((float(w.group(1)), float(w.group(2))))    # a window written deeper first
        return Selection((f.depth >= top - 1e-6) & (f.depth <= base + 1e-6), f"depth {num(top)}-{num(base)} {f.inv.depth_unit}")
    zt = _ZONE_TERM.match(t)
    if zt:                                              # a zone, or a range of zones
        lo, hi = sorted((int(zt.group(1)[1:]), int(zt.group(2) or zt.group(1)[1:])))     # "Z5-Z2" is Z2 to Z5
        m = np.zeros(f.depth.size, dtype=bool)
        for z in zones(f, [f"Z{i}" for i in range(lo, hi + 1)]):
            m[np.asarray(z.indices)] = True
        return Selection(m, f"in Z{lo}" + (f"-Z{hi}" if hi != lo else ""))
    if name in f.inv.curves and f.view.is_flag(name):
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
    """The samples a tool's where keeps (select)."""
    return select(f, condition) if condition else None


def where_none(f: Formation, sel: Optional[Selection]) -> str:
    """What a result's where line says when the where keeps no sample of the stretch the call computes on: that
    stretch and its depths (and, reaching the well, how a call computes elsewhere); "" when it keeps samples. A
    finding, not a refusal: none of a formation's samples may be pay (a depth window outside the
    scope read as "GR: n 0" on every row, and the answer said GR was not logged there)."""
    if sel is None or np.asarray(sel.mask, dtype=bool).any():
        return ""
    d = np.asarray(f.depth, dtype=float)
    name = getattr(f.view, "selection", None) or f.inv.formation
    span = f" ({num(float(d[0]))}-{num(float(d[-1]))} {f.inv.depth_unit})" if d.size else ""
    said = f"it holds at no sample of {name}{span}, so every count below is 0"
    if getattr(f.view, "reach", "focus") == "well":
        said += "; a call computes on another stretch by naming it in zones (a unit, a depth range TOP-BASE)"
    return said


def restricted(f: Formation, c: str, sel: Optional[Selection]) -> np.ndarray:
    """A curve's interval values, missing outside the selection and where a flag is not computed (uncomputed)."""
    x = np.asarray(f.view.values(c), dtype=float)
    gone, _ = uncomputed(f, c)
    x = np.where(gone, np.nan, x) if gone.any() else x
    return x if sel is None else np.where(sel.mask, x, np.nan)
