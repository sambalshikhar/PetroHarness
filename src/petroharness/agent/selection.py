"""What a tool's `zones` names, anywhere in the well (docs/ARCHITECTURE.md).

An item is, first match wins: a zone id of the focus (Z3), ALL, a lithology of the focus's zones (SAND, SIL*), a unit
of the tops file (matched as the focus's name is: case, spaces and punctuation ignored), a depth range TOP-BASE (m or
ft, else the reporting unit). Only focus items: the call goes on as today. One unit or range: the call runs on its
stretch (FormationView.stretch), whose rows R1.. are its own lithology zones. Several items: one row each, named as
asked, in depth order; a sample on a boundary two items share is the deeper item's (Petrophys's `label_depths`
convention); items that overlap beyond it, units listed twice, items with no sample of the well and unknown items are
refused with what is on offer. Under reach "focus" (the benchmark's data configs) only focus items are taken, and any
other is refused exactly as before.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Optional

import numpy as np

from petroharness.agent import engine as E
from petroharness.agent.engine import Formation, ToolError

_ALL = ("ALL", "*", "ALL ZONES", "POOLED", "ZONES POOLED")
_RANGE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*([A-Za-z]*)\s*$", re.IGNORECASE)
_UNITS = {"": None, "m": "m", "metre": "m", "metres": "m", "meter": "m", "meters": "m",
          "ft": "ft", "f": "ft", "feet": "ft", "foot": "ft"}
_ROW = re.compile(r"^R\d+$", re.IGNORECASE)
# a name followed by its depths, bare or in brackets: how a scope line, a result's header and the interval name write a
# stretch (by_unit labels, _named, interval_name); read back by its depths, so every name the harness writes selects
_NAMED = re.compile(r"^(?P<name>.*\S)\s+\(?(?P<range>\d+(?:\.\d+)?\s*(?:-|–|—|to)\s*\d+(?:\.\d+)?\s*[A-Za-z]*)\)?$",
                    re.IGNORECASE)


@dataclass(frozen=True)
class _Item:
    label: str                  # as it will be named: the unit's name, the range in the reporting unit, the zone id
    top: float
    base: float
    closed: bool = True
    zone: object = None         # a zone of the focus
    by_unit: bool = False       # a range written with a unit's own depths, named by the unit (its depths kept)


def _zone_item(f: Formation, z) -> "_Item":
    """A zone as an item, its limits its first and last samples' depths (a zone's top and base are kept rounded to 4
    decimals: a stretch between them could leave out its end samples)."""
    d = np.asarray(f.view.depth, dtype=float)
    idx = np.asarray(z.indices)
    return _Item(z.zone_id, float(d[idx[0]]), float(d[idx[-1]]), True, z)


def _g(x: float) -> str:
    return f"{x:g}"


def parse_range(text: str, view) -> Optional[tuple[float, float]]:
    """A depth range TOP-BASE in the reporting unit of `view` (its report_unit and m_per_unit), else None. A range
    that reads as one but cannot be used (its top below its base, a unit other than m or ft) is refused."""
    m = _RANGE.match(str(text or ""))
    if not m:
        return None
    a, b, unit = float(m.group(1)), float(m.group(2)), m.group(3).lower()
    if unit not in _UNITS:
        raise ValueError(f"{text.strip()}: the unit {m.group(3)} is not m or ft; give the range in m or ft, or with no "
                         f"unit for {view.report_unit}")
    unit = _UNITS[unit]
    factor = 1.0 if unit is None else (1.0 if unit == "m" else 0.3048) / view.m_per_unit
    top, base = a * factor, b * factor
    if top > base:
        shown = view.report_unit if unit is None else unit
        raise ValueError(f"{text.strip()}: its top {_g(a)} {shown} is below its base {_g(b)} {shown}; give the "
                         "shallower depth first")
    return top, base


def round_limit(raw: str, view, value: float, which: str, unit=None) -> float:
    """A depth limit written with decimals is the sample it rounds to: with no sample on it but one within half its
    last decimal, a lower limit ("top") moves up to that sample and an upper one ("base") down to it (the map's
    2841.0193 is the sample at 2841.01929, which the written value would leave out); a whole number stays exact
    ("2800-3000 m"). The one rule for a range's limits and a DEPTH comparison's number. `unit`: the written unit's
    name ("m", "ft"; None: the report unit)."""
    from petroharness.agent import numbers as N
    if "." not in str(raw):
        return value
    import numpy as np
    d = np.asarray(view.prep.depth, dtype=float) * view.depth_scale
    d = d[np.isfinite(d)]
    slack = N.half_unit(raw) * (1.0 if unit is None else (1.0 if unit == "m" else 0.3048) / view.m_per_unit)
    if which == "top":
        near = d[(d >= value - slack) & (d < value)]
        return float(near.min()) if near.size else value
    near = d[(d <= value + slack) & (d > value)]
    return float(near.max()) if near.size else value


def _rounded_limits(text: str, view, top: float, base: float) -> tuple:
    """A range's limits, each the sample it rounds to (round_limit)."""
    m = _RANGE.match(str(text or ""))
    if not m:
        return top, base
    unit = _UNITS.get(m.group(3).lower())
    return round_limit(m.group(1), view, top, "top", unit), round_limit(m.group(2), view, base, "base", unit)


# a unit's rank, written out or abbreviated as tops files do ("<Name> Group" is "<NAME> GP.")
RANKS = {"group": "gp", "groups": "gp", "grp": "gp", "subgroup": "subgp", "subgroups": "subgp", "formation": "fm",
         "formations": "fm", "fmn": "fm", "fms": "fm", "member": "mbr", "members": "mbr", "mb": "mbr", "mbrs": "mbr",
         "supergroup": "supgp", "supergroups": "supgp"}
_RANK_KEYS = {"gp", "subgp", "fm", "mbr", "supgp"}
_MARKERS = {"top", "base"}            # a pick's marker in a unit's name as some tops files write it ("NAME FM. TOP")


def _key(name: str) -> str:
    """How a unit's name is matched: the tops file's matching (case, spaces, punctuation), with a rank word written
    out, abbreviated or plural alike."""
    from petroharness.well.tops import name_key
    words = re.findall(r"[A-Za-z0-9]+", str(name))
    return name_key(" ".join(RANKS.get(w.lower(), w) for w in words))


def _core(name: str) -> str:
    """A unit's name without its rank word and pick marker ("NAME Formation", "NAME FM. TOP", "the NAME" alike)."""
    from petroharness.well.tops import name_key
    words = [RANKS.get(w.lower(), w.lower()) for w in re.findall(r"[A-Za-z0-9]+", str(name))]
    return name_key(" ".join(w for w in words if w not in _RANK_KEYS | _MARKERS | {"the"}))


def _rank(name: str) -> str:
    return next((r for r in (RANKS.get(w.lower(), w.lower()) for w in re.findall(r"[A-Za-z]+", str(name)))
                 if r in _RANK_KEYS), "")


def units_named(f: Formation, written: str) -> list:
    """The units of the tops file (and the user's zones) a name as a user writes it means: by the file's matching
    (_key: case, spaces, punctuation, a rank word written out, abbreviated or plural), else by the name alone, without
    its rank word or pick marker (_core), a rank word given choosing among units of that name. Users write names in
    their own convention; several units of different names is the user's to choose between."""
    units = list(getattr(f.view, "units", None) or [])
    key = _key(written)
    hits = [u for u in units if _key(u.name) == key]
    if hits:
        return hits
    core = _core(written)
    if not core:
        return []
    hits = [u for u in units if _core(u.name) == core]
    rank = _rank(written)
    if rank and len({u.name for u in hits}) > 1:
        hits = [u for u in hits if _rank(u.name) == rank] or hits
    return hits


def _is_focus(f: Formation, w: str) -> bool:
    if w in _ALL or w in {z.zone_id.upper() for z in f.view.zones}:
        return True
    return any(E._lith_match(z, w) for z in f.view.zones)


def _offer(f: Formation) -> str:
    """Every kind of item on offer, for a refusal."""
    v = f.view
    unit = v.report_unit
    d = np.asarray(v.prep.depth, dtype=float) * v.depth_scale
    lo, hi = float(np.nanmin(d)), float(np.nanmax(d))
    liths = sorted({E.zone_name(z).upper() for z in v.zones})
    units = "; ".join(f"{u.name} {_g(u.top)}-{_g(u.base)} {unit}" for u in v.units)
    return (f"zones: {', '.join(z.zone_id for z in v.zones) or 'none'}; or a lithology: {', '.join(liths) or 'none'}; "
            f"or ALL" + (f"; or a unit of the tops file: {units}" if units else "")
            + f"; or a depth range TOP-BASE within the well's {_g(lo)} to {_g(hi)} {unit}")


WHOLE_WELL_ITEM = "the whole well"                      # a scope item: the well's own span (agent.read.scope_items)
# a depth range as a scope item is typed: TOP-BASE with an optional unit (parse_range reads it)
RANGE_PATTERN = r"^[0-9]+(\.[0-9]+)? ?- ?[0-9]+(\.[0-9]+)?( ?(m|ft))?$"


def names(f: Formation) -> list:
    """Every name a selection reads as a stretch, as the map and the zones list them: the zone ids and lithologies
    of the focus, ALL, the lithology zones under the user's zones, the tops file's units and the user's zones (one
    each), and the whole well. A READ reply's scope items are one of these or a depth range (RANGE_PATTERN): typed
    by the schema it is decoded with, so an item is never a name with a note."""
    v = f.view
    out = [z.zone_id for z in v.zones] + sorted({E.zone_name(z).upper() for z in v.zones}) + ["ALL"]
    out += [z.zone_id for z in getattr(v, "lithology_zones", None) or []]
    keys = [_key(u.name) for u in v.units]
    out += [u.name for u, k in zip(v.units, keys) if keys.count(k) == 1]   # a unit listed twice: by its depths
    return list(dict.fromkeys(x for x in out + [WHOLE_WELL_ITEM] if x))


def as_written(f: Formation, labels) -> list:
    """A scope's labels as a READ reply can write them: one of names(f) or a depth range, as they are; a unit's name
    with its depths ("NAME (TOP-BASE m)": a range that is a unit's own, also of a name the tops file lists more than
    once) by its depths. The READ shows the scope in force this way: shown by its label, a reply that restated it
    could not be typed, and the decoder went on from the name's first letters to another unit's name."""
    known, out = set(names(f)), []
    for label in labels:
        label = str(label)
        m = re.fullmatch(r".+ \((" + RANGE_PATTERN.strip("^$") + r")\)", label)
        out.append(m.group(1) if m and label not in known else label)
    return out


def _items(f: Formation, asked: str) -> list:
    """The items one asked word names, beyond the focus's zones: lithology zones under the user's zones (an L id, or a
    lithology: each of its zones), a unit (of the tops file or the user's zones), a depth range."""
    v = f.view
    w = str(asked).strip()
    lz = getattr(v, "lithology_zones", None) or []
    if lz:
        hit = [z for z in lz if z.zone_id.upper() == w.upper()] or [z for z in lz if E._lith_match(z, w.upper())]
        if hit:
            return [_zone_item(f, z) for z in hit]
    return [_item(f, asked)]


def _item(f: Formation, asked: str) -> _Item:
    v = f.view
    w = str(asked).strip()
    hits = units_named(f, w)
    if len({u.name for u in hits}) > 1:                # one name, several units of the file (a core shared)
        listed = "; ".join(f"{u.name} {_g(u.top)}-{_g(u.base)} {v.report_unit}" for u in hits)
        raise ToolError(f"{w} names {len(hits)} units of the tops file ({listed}): select the one you mean by its name "
                        "as the file lists it, or its depths, TOP-BASE")
    if len(hits) > 1:
        listed = "; ".join(f"line {u.line}: {_g(u.top)}-{_g(u.base)} {v.report_unit}" for u in hits)
        raise ToolError(f"{hits[0].name} is listed {len(hits)} times in the tops file ({listed}): select the one you "
                        "mean by its depths, TOP-BASE")
    if hits:
        u = hits[0]
        return _Item(u.name, u.top, u.base, u.closed)
    try:
        span = parse_range(w, v)
    except ValueError as e:
        raise ToolError(str(e)) from None
    if span is not None:
        top, base = _rounded_limits(w, v, *span)
        label = f"{_g(span[0])}-{_g(span[1])} {v.report_unit}"
        same = _units_at(f, *span, top, base)            # a unit's own top and base, or its samples: that unit, said
        if len(same) == 1:
            u = same[0]
            return _Item(f"{u.name} ({label})", u.top, u.base, u.closed, by_unit=True)
        return _Item(label, top, base, True)
    named = _NAMED.match(w)
    if named:                                            # a stretch as the harness writes it, a name with its depths
        return _item(f, named.group("range"))            # ("UNIT (TOP-BASE m)", "UNIT TOP-BASE m"): the depths are
        #                                                  the stretch
    if _ROW.match(w):
        raise ToolError(f"{w.upper()} is a row of an earlier result, not a zone of the focus: select it by its depths, "
                        "TOP-BASE")
    raise ToolError(f"no zone or unit {w}; {_offer(f)}")


def _units_at(f: Formation, top: float, base: float, rtop: float = None, rbase: float = None) -> list:
    """The units of the tops file a range is written by: its top and base the unit's own, each within half a sample,
    or its samples (limits rounded to them: rtop, rbase) exactly the unit's (the model wrote
    a unit's depths, as the map lists them, for the unit; X18: the unit's last sample for its base)."""
    half = 0.5 * float(getattr(f.view, "step", 0.0) or 0.0) + 1e-9 * max(1.0, abs(base))
    d = np.asarray(f.view.prep.depth, dtype=float) * f.view.depth_scale
    lo, hi = (top, base) if rtop is None else (rtop, rbase)
    mine = (d >= lo - 1e-9 * max(1.0, abs(lo))) & (d <= hi + 1e-9 * max(1.0, abs(hi)))

    def same(u) -> bool:
        if abs(u.top - top) <= half and abs(u.base - base) <= half:
            return True
        tol = 1e-9 * max(1.0, abs(u.base))
        theirs = (d >= u.top - 1e-9 * max(1.0, abs(u.top))) & ((d <= u.base + tol) if u.closed else (d < u.base - tol))
        return bool(mine.any()) and bool(np.array_equal(mine, theirs))
    return [u for u in getattr(f.view, "units", None) or [] if same(u)
            and not _is_focus(f, u.name.strip().upper())]  # a name a focus zone takes cannot name it (it reads as the zone)


def _stretch(f: Formation, it: _Item, name: str):
    try:
        return f.view.stretch(it.top, it.base, name=name, closed=it.closed)
    except ValueError as e:
        msg = str(e).replace("WHAT: ", "")
        raise ToolError(f"{it.label} {_g(it.top)}-{_g(it.base)} {f.view.report_unit}: {msg}") from None


def _formation(f: Formation, view) -> Formation:
    """The formation a call on a selection computes on: its view, and an inventory of that view (its gross, its
    curves with data, petroharness.agent.inventory.from_view), with the curves this question calculated carried over
    from the focus's inventory, counted over the selection. No analyzer sections: they were computed for the focus."""
    from dataclasses import replace as _replace
    from petroharness.agent.inventory import from_view
    if f.inv is None:                                    # a formation built for its view alone: none to carry over
        return Formation(None, view, None)
    inv = from_view(view, None)
    for name, c in f.inv.curves.items():
        if name not in inv.curves and name in view.calculated:
            x = view.values(name)
            n = int(np.isfinite(x).sum()) if x is not None else 0
            inv.curves[name] = _replace(c, n=n, coverage=float(n / x.size) if x is not None and x.size else 0.0,
                                        zone_coverage={z.zone_id: float(np.isfinite(view.zone_values(z, name)).mean())
                                                       if np.asarray(z.indices).size else 0.0 for z in view.zones})
    return Formation(inv, view, None)


def carry_back(f: Formation, on: Formation, written=None) -> None:
    """The curves a call on a selection wrote (agent.library.register: values over the well's samples) entered in the
    question's inventory too, so its later calls read them, each described as it now is: where it holds values (the
    selection it was computed on; a curve of the same name computed before is replaced) and its coverage of the
    interval. `written`: the names the call wrote (None: those not yet in the inventory)."""
    names = list(written) if written is not None else [n for n in on.inv.curves if n not in f.inv.curves]
    sel = getattr(on.view, "selection", None) or ""
    where = (f"the samples {sel}" if sel.startswith("where ") else sel) if sel else ""
    for name in names:
        c = on.inv.curves.get(name)
        if c is None or name not in on.view.calculated:
            continue
        full = np.asarray(on.view.calculated[name], dtype=float)
        f.view.calculated[name] = on.view.calculated[name]
        if name in getattr(on.view, "calc_flags", ()):
            f.view.calc_flags.add(name)
        ok = np.isfinite(full[f.view.mask])
        note = f" (computed on {where}; no value outside it)" if where else ""
        f.inv.curves[name] = replace(
            c, meaning=re.sub(r" \(computed on .*; no value outside it\)$", "", c.meaning) + note,
            coverage=float(ok.mean()) if ok.size else 0.0, n=int(ok.sum()),
            zone_coverage={z.zone_id: float(ok[np.asarray(z.indices)].mean()) for z in f.view.zones
                           if np.asarray(z.indices).size})


def interval_name(f: Formation) -> str:
    """The interval the session opened on, by its name and depths: what every lookup computes on with no scope."""
    inv = f.inv
    return f"{inv.formation} {inv.top:g}-{inv.base:g} {inv.depth_unit}"


def _rows(zones: list) -> list:
    return [replace(z, zone_id=f"R{k}") for k, z in enumerate(zones, start=1)]


def _named(f: Formation, it) -> str:
    """An item with its depths, each named once (a range is its own name: "2841-2865 m", not "2841-2865 m 2841-2865 m")."""
    depths = f"{_g(it.top)}-{_g(it.base)} {f.view.report_unit}"
    if getattr(it, "by_unit", False):                  # a range named by its unit already says its depths
        return it.label
    return depths if parse_range(str(it.label), f.view) is not None else f"{it.label} {depths}"


def _union(f: Formation, picked: list) -> tuple:
    """A selection's items as the disjoint stretches of their union, in depth order: an item inside another (or the
    same stretch) is part of it; items that overlap join into the range they cover together. (items, notes saying
    each merge). One rule for a question's scope and a tool's zones (a unit with its own range, the
    interval with its units, a unit with the zones inside it were refused as overlapping and the scope dropped)."""
    out, notes, unit = [], [], f.view.report_unit
    d = np.asarray(f.view.prep.depth, dtype=float) * f.view.depth_scale

    def held(it) -> tuple:                             # the first and last sample it holds (its limits, holding none):
        tt, tb = 1e-9 * max(1.0, abs(it.top)), 1e-9 * max(1.0, abs(it.base))   # items compare by their samples (X01:
        m = (d >= it.top - tt) & ((d <= it.base + tb) if it.closed else (d < it.base - tb))   # a unit's top 2841 and
        idx = np.flatnonzero(m)                        # the interval's first sample 2841.0193 read as an overlap)
        return (float(d[idx[0]]), float(d[idx[-1]])) if idx.size else (it.top, it.base)
    span = {id(it): held(it) for it in picked}
    for it in sorted(picked, key=lambda it: (span[id(it)][0], -span[id(it)][1])):
        a, b = span[id(it)]
        if out and a < span[id(out[-1])][1]:           # shares samples with the stretch before it (beyond one
            #   boundary sample: adjacent units that both hold it are two rows, the sample the deeper one's)
            last = out[-1]
            if b <= span[id(last)][1]:                 # inside it, or the same samples
                n_it, n_last = _named(f, it), _named(f, last)
                if span[id(it)] != span[id(last)]:
                    notes.append(f"{n_it} is part of {n_last}")
                elif not (n_it.startswith(n_last) or n_last.startswith(n_it)):    # a unit and its own depths: one
                    notes.append(f"{n_it} and {n_last} hold the same samples: one row")   # name, said once (not
                continue                               #   "UNIT (TOP-BASE m) is part of UNIT")
            joined = _Item(f"{_g(last.top)}-{_g(it.base)} {unit}", last.top, it.base, it.closed)
            span[id(joined)] = (span[id(last)][0], b)
            notes.append(f"{_named(f, last)} and {_named(f, it)} overlap: one row, {joined.label}")
            out[-1] = joined
            continue
        out.append(it)
    return out, notes


def _picked(f: Formation, items: list, as_asked: bool = False) -> list:
    """The stretches the items name (a focus zone, a lithology, a unit, the user's zones, a depth range), each by its
    own name (the unit's name, the range in the reporting unit); `as_asked`: an item that names one stretch keeps the
    words it was asked by (a scope's line)."""
    picked = []
    for a in items:
        got = [_zone_item(f, z) for z in E.zones(f, [a])] if _is_focus(f, str(a).strip().upper()) else _items(f, a)
        keep = as_asked and len(got) == 1 and not got[0].by_unit      # a range named by its unit: both said
        picked += [replace(got[0], label=str(a).strip())] if keep else got
    return picked


def union_labels(f: Formation, asked) -> list:
    """A scope's items as the disjoint stretches of their union (_union), each as asked, or by its depths where items
    joined."""
    items = [asked] if isinstance(asked, str) else list(asked)
    return [it.label for it in _union(f, _picked(f, items, as_asked=True))[0]]


def same_samples(a, b) -> bool:
    """Two views of one well on exactly the same samples (a selection written as the interval's own stretch)."""
    ma, mb = getattr(a, "mask", None), getattr(b, "mask", None)
    return ma is not None and mb is not None and np.shape(ma) == np.shape(mb) and bool(np.array_equal(ma, mb))


def resolve(f: Formation, asked, force: bool = False, notes: list = None) -> tuple:
    """(the formation the call computes on, the zones argument it is given). Focus items alone (or nothing asked):
    (f, asked) unchanged, unless `force` (a tool that does not read zones itself, or a verb's run): then a selection of
    those zones, one row each. Otherwise a formation on the selection's view, and None (every row of it). `notes`, a
    list: the union's notes are added to it (an item part of another, items that overlap joined), the interval's own
    samples included, for the caller to say (merges() reads them)."""
    if not asked:
        return f, asked
    items = [asked] if isinstance(asked, str) else list(asked)
    words = [str(a).strip().upper() for a in items]
    if all(_is_focus(f, w) for w in words) and not force:
        return f, asked
    if getattr(f.view, "reach", "focus") != "well":
        E.zones(f, asked)                                # refused exactly as before: only the focus is in reach
        return f, asked                                  # (not reached: E.zones raises for the item it cannot read)
    picked, merged = _union(f, _picked(f, items))     # the union of what it names, as disjoint stretches
    if notes is not None:
        notes.extend(m for m in merged if m not in notes)
    name = ", ".join(it.label for it in picked)          # the selection, named by its items in depth order
    said = name
    if len(picked) == 1:
        it = picked[0]
        view = _stretch(f, it, it.label)
        if same_samples(view, f.view) and not getattr(f.view, "selection", None):
            return f, None                               # the interval's own samples: the interval, not a selection
        return _formation(f, replace(view, zones=_rows(view.zones), selection=said)), None
    span = _stretch(f, _Item(name, picked[0].top, max(it.base for it in picked), True), name)
    d = span.depth
    owner = np.full(d.size, -1)
    for k in range(len(picked) - 1, -1, -1):             # deepest first: a shared boundary sample is the deeper item's
        it = picked[k]
        tol = 1e-9 * max(1.0, abs(it.base))
        inside = (d >= it.top - 1e-9 * max(1.0, abs(it.top))) & ((d <= it.base + tol) if it.closed else (d < it.base - tol))
        owner[inside & (owner < 0)] = k
    from petroharness.well.formation import Zone
    rows = []
    for k, it in enumerate(picked):
        idx = np.flatnonzero(owner == k)
        if idx.size == 0:
            raise ToolError(f"{it.label} {_g(it.top)}-{_g(it.base)} {f.view.report_unit}: no sample of the well lies in "
                            f"it; {_offer(f)}")
        rows.append(Zone(zone_id=f"R{k + 1}", name=it.label, lithology=it.label, top=round(float(d[idx[0]]), 4),
                         base=round(float(d[idx[-1]]), 4), n_samples=int(idx.size), indices=idx))
    return _formation(f, replace(span, zones=rows, selection=said)), None


def refuse_focus_only(tool: str, f: Formation) -> None:
    """A tool that rests on what the workflow computed for the focus (Tool.stretch "focus_only"), given a stretch
    elsewhere: refused, with what it reads and the tools that read any stretch."""
    from petroharness.agent.toolset import TOOLSET
    t = TOOLSET.get(tool)
    reason = t.focus_reason if t is not None and t.stretch == "focus_only" else ""
    if reason:
        raise ToolError(f"{tool} reads {reason}, computed for the focus ({f.view.interval.formation}) only: for a unit "
                        "or a depth range elsewhere, use stats, profile, runs, compare, crossplot or lithology_stats")


def merges(f: Formation, notes) -> str:
    """The line a result or a scope gives the union's notes in (resolve's `notes`): which items were part of others or
    joined, so the model sees what its zones became ("" when none)."""
    return f"Zones as asked: {'; '.join(notes)}." if notes else ""


def header(f: Formation, notes=()) -> str:
    """The line a selection's result opens with: what was selected, its depths and samples, what its rows are; then
    the union's notes (merges)."""
    line = _header(f)
    return line + (f" {merges(f, notes)}" if notes else "")


def _header(f: Formation) -> str:
    v = f.view
    rows = [z.zone_id for z in v.zones]
    if v.selection.startswith("where "):                 # a run under where: the samples where it holds
        return (f"Selection: the samples {v.selection}: {int(v.mask.sum())} samples; each zone holds its samples where "
                "it holds (not in depth order: runs of the condition are a runs call)")
    one = "your zones within it" if getattr(v, "user_zones", None) else "its lithology zones"
    what = (one if "," not in v.selection else "the items asked, in depth order")
    ids = f"rows {rows[0]}-{rows[-1]}" if len(rows) > 1 else (f"row {rows[0]}" if rows else "no row")
    from petroharness.well.summary import selection_name
    return (f"Selection: {selection_name(v)}, {int(v.mask.sum())} samples; {ids} {'are' if len(rows) > 1 else 'is'} {what} "
            "(ids of this result only)")


BY = ("lithology", "lithology zones")


def by(f: Formation, frame) -> Formation:
    """A call's `by`: "lithology" reports it by the lithology zones (L1..) where the user's zones frame the question;
    where they do not, the lithology zones are the frame already (the call as asked)."""
    if frame is None:
        return f
    if str(frame).strip().lower() not in BY:
        raise ToolError(f"by takes \"lithology\" (report by the lithology zones), not {frame!r}")
    lz = getattr(f.view, "lithology_zones", None) or []
    if not lz:
        return f
    return _formation(f, replace(f.view, zones=list(lz), all_zones=None))


def listed_more_than_once(f: Formation, texts) -> list:
    """The units the tops file lists more than once whose name the texts use, in any convention (_said_in): [(name,
    [(line, top, base), ...])]. Such a name is no one stretch; which one is meant is the user's to say, or the tops
    file's to fix (ask the user to select one or fix the file)."""
    units = list(getattr(f.view, "units", None) or [])
    by = {}
    for u in units:
        by.setdefault(_key(u.name), []).append(u)
    return [(us[0].name, [(u.line, u.top, u.base) for u in sorted(us, key=lambda u: u.top)])
            for us in by.values() if len(us) > 1 and _said_in(us[0].name, texts)]


_FILLER = {"the", "a", "an", "of", "this", "that", "these", "those", "its", "their", "each", "every", "whole", "same",
           "which", "what", "in", "on", "at", "for", "and", "or", "to", "into", "within", "across", "over", "below",
           "above", "under", "entire", "main", "target", "given", "named", "said", "both", "all", "any", "another"}


def _phrases(text: str) -> list:
    """The unit phrases of a text, each with its shorter endings: a name of up to four words before a rank word, in
    any case ("the NAME Formation", "name fm", "NAME Formations"); a name made only of filler words is none."""
    out = []
    for m in _UNIT_PHRASE.finditer(str(text or "")):
        words = m.group(1).split()
        if words[-1].lower() in _FILLER:
            continue
        out.append([" ".join(words[k:]) + " " + m.group(2) for k in range(len(words)) if words[k].lower() not in _FILLER]
                   or [words[-1] + " " + m.group(2)])
    return out


def _said_in(name: str, texts) -> bool:
    """Whether the texts use a unit's name in any of the conventions users write (units_named): as a unit phrase,
    by its name alone ("the NAME"), as a whole text, or as the file writes it."""
    core = _core(name)
    for t in texts:
        t = str(t or "")
        if _key(t) == _key(name) or (core and _core(t) == core):
            return True
        plain = re.sub(r"[\W_]+", " ", t).casefold()
        written = re.sub(r"[\W_]+", " ", re.sub(r"\b(?:top|base)\b", " ", str(name), flags=re.I)).casefold().split()
        bare = [w for w in written if RANKS.get(w, w) not in _RANK_KEYS]
        if bare and re.search(r"(?<![a-z0-9])" + r"\s+".join(map(re.escape, bare)) + r"(?![a-z0-9])", plain):
            return True
        for tries in _phrases(t):
            if any(_key(x) == _key(name) or (core and _core(x) == core) for x in tries):
                return True
    return False


def shared_names_unread(f: Formation, texts) -> list:
    """Bare names the texts use that several differently named units share (_core), with nothing in the texts that
    picks one (a rank word or the name as the file lists it): [(the bare name, [units])]. Which one is meant is the
    user's to say (a bare name shared by a group and a formation in the file was answered over the
    whole well)."""
    units = list(getattr(f.view, "units", None) or [])
    groups = {}
    for u in units:
        groups.setdefault(_core(u.name), {})[u.name] = u
    out = []
    for core, by_name in groups.items():
        if not core or len(by_name) < 2:
            continue
        bare = next(iter(by_name))
        if not _said_in(bare, texts):
            continue
        picked = {u.name for t in texts for tries in _phrases(t) for x in tries for u in units_named(f, x)
                  if u.name in by_name and len({v.name for v in units_named(f, x)}) == 1}
        picked |= {n for n in by_name for t in texts if _key(t) == _key(n)}
        if not picked:
            out.append((re.sub(r"\s+(?:gp|fm|mbr|grp|group|formation|member)\.?$", "", bare, flags=re.I).strip(),
                        sorted(by_name.values(), key=lambda u: u.top)))
    return out


def left_out_named(f: Formation, texts) -> list:
    """The tops file's rows left out of the units (data.units_left_out: a base not below the top) whose name the texts
    use, in any convention: a question about one is asked back with the row to fix (not told the
    unit is absent)."""
    return [r for r in getattr(f.view, "units_left_out", None) or [] if _said_in(str(r.get("name", "")), texts)]


# a unit as users write it: words before a rank word, in any case ("the NAME Formation", "NAME fm", "NAME Groups")
_UNIT_PHRASE = re.compile(r"((?:[A-Za-z][A-Za-z'\-]*\s+){0,3}[A-Za-z][A-Za-z'\-]*)\s+(formations?|fmn|fms|fm\.?|groups?|"
                          r"grp|gp\.?|members?|mbrs?|mb\.?|mbr\.?)(?![A-Za-z])", re.I)


def unit_names_unread(f: Formation, texts) -> list:
    """Units the texts name (a name before a rank word) that are no unit of the tops file, by any of its shorter
    endings and in any convention (units_named): [(the name as written, the file's units close to it)], each once.
    A name close to units is likely misspelt: the question is asked back (a misspelt name was answered
    as the interval); one close to none is a unit the file does not have, said under the question."""
    import difflib
    units = list(getattr(f.view, "units", None) or [])
    if not units:
        return []
    names = sorted({u.name for u in units})
    plain = lambda x: _core(x)
    out, seen = [], set()
    for t in texts:
        for tries in _phrases(t):
            if any(_resolves(f, x) for x in tries):
                continue
            name = tries[-1]                              # the shortest: the name itself with its rank word
            if plain(name) in seen:
                continue
            seen.add(plain(name))
            close = difflib.get_close_matches(plain(name), [plain(n) for n in names], n=3, cutoff=0.7)
            if not plain(name):
                continue
            out.append((name, [n for n in names if plain(n) in close]))
    return out


def _resolves(f: Formation, text: str) -> bool:
    try:
        _item(f, text)
        return True
    except ToolError as e:
        return " is listed " in str(e)                   # listed twice: asked back as such, not as unread


def _names_stretches(f: Formation, items: list) -> bool:
    try:
        resolve(f, items, force=True)
        return True
    except ToolError:
        return False


def _listed_twice(f: Formation, text: str) -> str:
    """The selection's own message when the text is a unit the tops file lists more than once ("NAME is listed 2
    times ... select the one you mean by its depths"), else "" (where naming a unit listed twice got the condition grammar's
    refusal, which says nothing of the unit or its two stretches)."""
    try:
        _item(f, text)
    except ToolError as e:
        return str(e) if " is listed " in str(e) else ""
    return ""


def _window_inside(f: Formation, text: str, zones) -> None:
    """A depth window written as a where, on a call with no stretch of its own: where reads the interval's samples,
    so a window that reaches outside the interval is refused with the zones call that computes on all of it (a
    window there read n 0 or part of the window, and was taken for the stretch)."""
    if zones and not all(_is_focus(f, str(z).strip().upper()) for z in ([zones] if isinstance(zones, str) else zones)):
        return                                       # the call's own stretch: where reads within it
    try:
        got = parse_range(text, f.view)
    except ValueError:
        return
    if got is None:                                  # not a depth window
        return
    top, base = got
    v = f.view
    lo, hi = float(v.interval.top), float(v.interval.base)
    if lo - 1e-6 <= top and base <= hi + 1e-6:
        return
    u = v.report_unit
    k = int(np.asarray(E.select(f, text).mask, dtype=bool).sum())
    inside = "none of its samples is one of the interval's" if k == 0 else f"only {k} of its samples are the interval's"
    raise ToolError(f"where {text!r} reads the samples of the interval, {lo:g}-{hi:g} {u}, and {inside}: to compute "
                    f"on all of {top:g}-{base:g} {u}, give it as zones, \"zones\": {json.dumps([text])}")


def where_names_stretches(f: Formation, where, zones=None) -> None:
    """`where` holds a condition on curves; stretches of the well (units, the user's zones, depth ranges) go in zones.
    A where that names stretches, alone or after a condition ("SW < 0.5 in <unit>"), is refused with the call to
    write instead; any other where is left to the condition's own reading."""
    if isinstance(where, (list, tuple)):
        items = [str(x).strip() for x in where if str(x).strip()]
        if items and all(_names_stretches(f, [x]) for x in items):      # each a stretch (zones says if they overlap)
            raise ToolError(f"where takes a condition on curves as text (as \"SW < 0.5\"); {json.dumps(items)} name "
                            f"stretches of the well: give them as zones, \"zones\": {json.dumps(items)}")
        return
    text = str(where).strip()
    try:
        E.select(f, text)
    except ToolError:
        pass
    else:                                            # a condition it reads: a depth window must lie in the interval
        _window_inside(f, text, zones)
        return
    if _names_stretches(f, [text]):
        raise ToolError(f"where takes a condition on curves (as \"SW < 0.5\"); {text!r} names a stretch of the well: "
                        f"give it as zones, \"zones\": {json.dumps([text])}")
    twice = _listed_twice(f, text)
    if twice:
        raise ToolError(f"where takes a condition on curves (as \"SW < 0.5\"); {twice}, as zones")
    m = re.match(r"^(.*\S)\s+(?:in|within|inside|over)\s+(?:the\s+)?(.+)$", text, re.I)
    if m:
        try:
            E.select(f, m.group(1))
        except ToolError:
            return
        if _names_stretches(f, [m.group(2)]):
            raise ToolError(f"where takes the condition alone and zones the stretch: \"where\": {json.dumps(m.group(1))}, "
                            f"\"zones\": {json.dumps([m.group(2)])}")


def where_view(f: Formation, condition: str) -> Formation:
    """A verb's run under `where`: the formation on the samples where the condition holds (the view's mask restricted
    to them; each zone keeps its id, restricted to its samples that pass). Its samples are not in depth order, so a
    function that reads the well or a depth window is refused there (library.api.run)."""
    sel = np.asarray(E.select(f, condition).mask, dtype=bool)
    if not sel.any():
        raise ToolError(f"no sample here where {condition}: nothing to run on")
    v = f.view
    idx = np.flatnonzero(v.mask)
    mask = np.zeros_like(v.mask)
    mask[idx[sel]] = True
    new = np.cumsum(sel) - 1                             # each kept sample's position among the kept ones
    d = np.asarray(v.depth, dtype=float)
    zones = []
    for z in v.zones:
        zi = np.asarray(z.indices)
        keep = zi[sel[zi]]
        if keep.size:
            zones.append(replace(z, indices=new[keep], n_samples=int(keep.size), top=round(float(d[keep[0]]), 4),
                                 base=round(float(d[keep[-1]]), 4)))
    name = f"where {condition}" + (f" in {v.selection}" if getattr(v, "selection", None) else "")
    return _formation(f, replace(v, mask=mask, zones=zones, all_zones=None, selection=name))
