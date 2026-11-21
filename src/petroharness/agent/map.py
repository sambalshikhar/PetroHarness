"""The map: the first thing the model reads - the inventory as plain facts (C7 frames it)."""

from __future__ import annotations

import math
import re
from typing import Iterable

from petroharness.agent import components as C
from petroharness.agent.inventory import Inventory
from petroharness.record.card import input_text, plain_inputs
from petroharness.record.params import BOOKKEEPING, RANGES

# step parameters that are bookkeeping, not values a reader uses (where a value came from, requested vs used, ranges
# that repeat a curve's own statistics, sample tallies)
_SKIP_SUFFIX = BOOKKEEPING + RANGES


def num(x) -> str:
    """A number as the inventory holds it, never in exponent form: integers as integers; |x| >= 1 to at most 4
    decimals (depths keep their half-feet); |x| < 1 to 4 significant figures."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return str(x)
    if isinstance(x, int):
        return str(x)
    if not math.isfinite(x):
        return "n/a"
    if abs(x) < 1e-12:                                   # rounding noise (e.g. the spread of a constant curve)
        return "0"
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    if abs(x) >= 1:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    s = f"{x:.{max(4, 4 - int(math.floor(math.log10(abs(x)))) - 1)}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _coefficients(params: dict, said: dict = None) -> list:
    """Scalar numeric parameters a reader uses, as 'name value' (with the unit the record keeps beside it, and what the
    value is where the catalog says its name alone misleads); matrix endpoints compactly."""
    out, said = [], said or {}
    for k, v in params.items():
        if k.endswith(_SKIP_SUFFIX):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            unit = params.get(f"{k}_unit")                 # the unit the record keeps beside it (td: td_unit)
            out.append(f"{k} {num(v)}" + (f" {unit}" if isinstance(unit, str) and unit.strip() else "")
                       + (f" ({said[k]})" if said.get(k) else ""))
        elif k == "matrix_endpoints" and isinstance(v, list):
            for e in v:
                if isinstance(e, dict) and e.get("lithology_group"):
                    out.append(f"matrix {e['lithology_group']} rho_ma {num(e.get('rho_ma'))}, nphi_ma {num(e.get('nphi_ma'))}, "
                               f"dt_ma {num(e.get('dt_ma'))}")
    return out


def _join(items: Iterable[str], sep: str = ", ") -> str:
    return sep.join(i for i in items if i)


def parameter(c, step: str) -> str:
    """A curve a step wrote that holds one value over the whole well, whatever set it (a setting, a default, a fit, a
    clip): "VANHY 0: one value over the whole well as the lithology step wrote it (<its meaning>)"; the step's record
    (its values, method and lines) says how."""
    return f"{c.name} {num(c.well_value)}: " + C.fill("C7", "one_value", step=step, meaning=c.meaning)


def primary_absent(inv: Inventory) -> list:
    """The measured logs not in the input among those the workflow's completeness record counts
    (petrophys PRIMARY_LOGS_FOR_COMPLETENESS; the harness catalogue also lists logs the workflow never reads, such as
    spectral gamma, and answers called those missing)."""
    try:
        from petrophys.reporting.reference_export import PRIMARY_LOGS_FOR_COMPLETENESS
    except Exception:  # noqa: BLE001  (an older petrophys: the catalogue's list)
        return list(inv.logs_absent)
    primary = {str(n).upper() for n in PRIMARY_LOGS_FOR_COMPLETENESS}
    return [c for c in inv.logs_absent if c.upper() in primary]


# the notes a family leaves out (they seeded unasked fluid points and limitations)
FLUID_NOTES = ("Rw:", "SW model", "SXO:", "MHI:")
NOTE_SCOPE = {"porosity": FLUID_NOTES, "lithology": FLUID_NOTES}


def scoped_notes(notes: list, families) -> list:
    """The map's notes for the families the model's topics read (none: every note): could-not-run notes only for
    those families' sections; the saturation-route notes left out when every family is porosity or lithology."""
    if not families:
        return list(notes)
    keep = []
    for x in notes:
        m = re.match(r"^([a-z]+)\.[a-z_]+: ", x)
        if m and m.group(1) not in families:
            continue
        if all(x.startswith(NOTE_SCOPE.get(fam, ())) for fam in families):
            continue
        keep.append(x)
    return keep


def _compact(methods: list, by_step: dict, what, inv: Inventory) -> list:
    """One line per step of a preparation or of the QC and recomputation after the workflow: its method, the curves
    it made, and for a value-range QC the samples its rules changed in this interval (the rest: the step tool)."""
    out = []
    qc = getattr(inv, "value_qc", None) or {}
    for m in methods:
        line = f"    step {m.step}: method {m.method}"
        cs = by_step.pop(m.step, [])
        if cs:
            line += "; curves " + "; ".join(what(c) for c in cs)
        known = [(c, qc[c]) for c in (m.outputs or []) if c in qc and isinstance(qc[c].get("changed"), int)]
        if known:                                       # counted where the record says which samples a rule changed
            hit = [f"{c} {q['changed']} {'clipped' if (q.get('rule') or {}).get('action') == 'clip' else 'set to NaN'} "
                   f"outside {num((q.get('rule') or {}).get('low'))} to {num((q.get('rule') or {}).get('high'))}"
                   for c, q in known if q["changed"]]
            line += ("; in this interval " + ", ".join(hit)) if hit else "; in this interval no sample changed"
        out.append(line)
    return out


UNITS_SHOWN = 30          # units of the tops file listed in the map (reach "well"); the rest counted


def render(inv: Inventory, families=None) -> str:
    u = inv.depth_unit
    lines = [f"WELL {inv.well}, FORMATION {inv.formation}"]
    whole = getattr(inv, "reach", "focus") == "well" and inv.well_span
    if whole:                         # the well's log first, then the interval as a part of it: read the other way, a
        lo, hi = inv.well_span        # question about "the whole well" was taken for the interval (its samples for the log's)
        n = getattr(inv, "well_samples", 0)
        lines.append(f"Well: its log runs {num(lo)}-{num(hi)} {u}" + (f", {n} samples every {num(inv.step)} {u}" if n else "")
                     + "; a tool's zones may name a depth range TOP-BASE anywhere in it or a unit of the tops file, "
                       "computed on that stretch")
        lines.append(f"Interval (the formation the session opened on, one part of the well): {num(inv.top)}-"
                     f"{num(inv.base)} {u} (gross {num(inv.gross)} {u}); {inv.samples} of the well's samples")
    else:
        lines.append(f"Interval: {num(inv.top)}-{num(inv.base)} {u} (gross {num(inv.gross)} {u}); {inv.samples} samples "
                     f"every {num(inv.step)} {u}")
    if whole:
        if inv.units:
            shown = "; ".join(f"{n} {num(t)}-{num(b)} {u}" for n, t, b in inv.units[:UNITS_SHOWN])
            more = f"; and {len(inv.units) - UNITS_SHOWN} more" if len(inv.units) > UNITS_SHOWN else ""
            lines.append(f"  Units of the tops file: {shown}{more}")
    share = 100 * inv.zoned_thickness / inv.gross if inv.gross else 0
    source = getattr(inv, "zones_source", None)
    lines.append(f"Zones: {len(inv.zones)}" + (f", your zones from {source}" if source else "")
                 + f", covering {num(inv.zoned_thickness)} {u} ({share:.0f}% of the interval)")
    if source and inv.lithology_zones:                        # the lithology zones, under the user's
        lz = inv.lithology_zones
        listed = "; ".join(f"{i} {lith} {num(t)}-{num(b)} {u}" for i, lith, t, b in lz[:UNITS_SHOWN])
        more = f"; and {len(lz) - UNITS_SHOWN} more" if len(lz) > UNITS_SHOWN else ""
        lines.append(f"  Lithology zones ({len(lz)}; a lookup's \"by\": \"lithology\" reports by them, its zones may "
                     f"name one by its L id or a lithology): {listed}{more}")
    if len(inv.zones) == 1:                                   # one zone: no zone-by-zone reading; variation by depth
        lines.append("  One zone: its variation is read by depth (runs of a condition, profile's upper, middle and "
                     "lower thirds, crossplot with x DEPTH), not zone by zone")
    for z in inv.zones:
        lith = "no lithology data" if z.lithology.upper() == "NO_LITHOLOGY_DATA" else z.lithology
        name = getattr(z, "name", "")
        if name and name.upper().startswith(lith.upper()):     # the record name holds the lithology: the name alone
            head = f"{z.id} {name}"
        else:
            head = f"{z.id}{f' ({name})' if name else ''} {lith}"
        lines.append(f"  {head} {num(z.top)}-{num(z.base)} {u} ({num(z.thickness)} {u})")
        if getattr(z, "log_shares", ""):                # the log's shares where the zone is not all one reading of it
            top = z.log_shares.split(", ")[0].rsplit(" ", 1)[0]
            mixed = "" if top.upper() == z.lithology.upper() else (
                " (the zone is yours: the rock types the lithology log reads in it)" if source else
                " (the zone's lithology is the formation's, as the data states it)")
            lines.append(f"    lithology log in {z.id}: {z.log_shares}" + mixed)
        if getattr(z, "stated", ""):                    # the log names the zone; the formation's tops record another
            lines.append(f"    the formation tops record its lithology as {z.stated} (the lithology log reads {lith})")

    copies = {}
    for x in inv.curves.values():
        if x.copy_of:
            copies.setdefault(x.copy_of, []).append(x.name)

    def what(c, full=False):
        """A curve as the map names it: in full, the catalog's line (what it is, its kind and inputs); under a
        workflow step, whose line says how it was made from which inputs, what it is."""
        same = list(copies.get(c.name, [])) + [x for x in getattr(c, "same_as", []) or [] if x not in copies.get(c.name, [])]
        twin = f" (same values as {c.copy_of})" if c.copy_of else (f" (same values as {', '.join(same)})" if same else "")
        if getattr(c, "well_value", None) is not None and c.step:     # one value for the well: a parameter
            return parameter(c, c.step) + twin
        line = getattr(c, "catalog", "") or ""
        run = f" (this run: {c.run_said})" if getattr(c, "run_said", "") else ""
        if line and full and "; " in line and twin:          # the twin beside what the curve is, before its kind
            head, rest = line.split("; ", 1)
            return f"{c.name} = {head}{twin}; {rest}{run}"
        return f"{c.name} = {line if line and full else c.meaning}" + run + twin

    lines.append("Raw input (the LAS as given, before the workflow)")
    lines.append("  curves: " + "; ".join(what(c) for c in inv.curves.values() if c.source == "input"))
    absent = primary_absent(inv)                       # the measured logs the workflow uses (petrophys's own list)
    empty = []
    # in the input, no value here: not "not in the input"
    empty = [c for c in getattr(inv, "logs_empty", []) or [] if c in absent]
    absent = [c for c in absent if c not in empty]
    if absent:
        mean = getattr(inv, "absent_meanings", {}) or {}
        lines.append("  measured logs not in the input: " + _join(f"{c} ({mean[c]})" if mean.get(c) else c
                                                                   for c in absent))
    if empty:                                          # with what the preparation's range screening removed, where it did
        said = getattr(inv, "logs_screened", {}) or {}
        lines.append("  measured logs in the input with no values in this interval: "
                     + _join(f"{c} ({said[c]})" if said.get(c) else c for c in empty))
    if inv.header:
        lines.append("  header: " + "; ".join(f"{k} {num(h['value'])}{(' ' + h['unit']) if h['unit'] else ''}"
                                             + (f" ({h['description']})" if h["description"] else "")
                                             for k, h in inv.header.items()))

    lines.append("After the workflow (the record of the whole well's run: its record and equations lines, counts "
                 "included, are the well's; lines that say 'in this interval' are computed from this interval's samples)")
    by_step = {}
    for c in inv.curves.values():
        if c.source == "computed" and c.step:
            by_step.setdefault(c.step, []).append(c)
    stages = {s: [m for m in inv.methods if getattr(m, "stage", "workflow") == s] for s in ("preparation", "workflow", "after")}
    if stages["preparation"]:
        lines.append("  preparation (before the workflow; the step tool gives a step's full record)")
        lines += _compact(stages["preparation"], by_step, lambda c: what(c, full=True), inv)
    for m in stages["workflow"]:                   # a fallback input in plain words ("A where present, otherwise B")
        plain = lambda text: plain_inputs(text, m.inputs)
        lines.append(f"  step {m.step}: method {m.method}" + (f"; inputs {_join(input_text(i) for i in m.inputs)}"
                                                              if m.inputs else ""))
        cs = by_step.pop(m.step, [])
        if cs:                                         # a curve an analysis inside the step wrote names it
            lines.append("    curves: " + "; ".join(what(c) + (f" (written by {c.writer})" if c.by else "") for c in cs))
        if m.equations_here:
            lines.append("    equations: " + "; ".join(plain(e) for e in m.equations_here))
        values = _coefficients(m.parameters, getattr(m, "said", None))
        if values:                                     # the record's values are the whole well's
            lines.append("    values (whole well, as recorded): " + "; ".join(values))
        if m.routes_here:                              # the route this interval's samples took, from its curves
            lines.append("    " + "; ".join(m.routes_here))
        if m.facts_here:                               # what the step's output curves hold here, from the curves
            lines.append("    in this interval: " + "; ".join(m.facts_here))
        if m.decisions_here:                           # the run's own lines, as written: the whole well's (the
            lines.append("    record: " + "; ".join(plain(" ".join(d.split())) for d in m.decisions_here))   # header)
            # (the header says once for every step what catalog.RECORD_LABEL says on each line of the tools)
    if stages["after"]:
        lines.append("  QC and recomputation (after the workflow; the step tool gives a step's full record)")
        lines += _compact(stages["after"], by_step, lambda c: what(c, full=True), inv)
    for step, cs in by_step.items():                     # computed curves whose step the record holds no entry for
        lines.append(f"  step {step}")
        lines.append("    curves: " + "; ".join(what(c, full=True) for c in cs))
    other = [c for c in inv.curves.values() if c.source in ("copy", "unknown") or (c.source == "computed" and not c.step)]
    if other:
        lines.append("  other curves: " + "; ".join(what(c, full=True) for c in other))
    analyzer = [c for c in inv.curves.values() if c.source == "analyzer"]
    if analyzer:                                     # each with the catalog's line: what it is, its kind and inputs
        plain = [c.name for c in analyzer if not getattr(c, "catalog", "")]
        lines.append("Computed by the analyzers:" + (f" {_join(plain)}" if plain else ""))
        lines += [f"  {what(c, full=True)}" for c in analyzer if getattr(c, "catalog", "")]

    if inv.sections:
        cats = {}
        for s in inv.sections:
            cats.setdefault(s.family, []).append(s.key.split(".", 1)[1])
        lines.append("Analyzer sections")
        for cat, keys in cats.items():
            lines.append(f"  {cat} ({len(keys)}): " + _join(keys))
    notes = getattr(inv, "notes", None) or []
    if families:
        notes = scoped_notes(notes, families)
    if notes:
        lines.append("Notes on this interval")
        lines += [f"  - {x}" for x in notes]
    return "\n".join(lines)
