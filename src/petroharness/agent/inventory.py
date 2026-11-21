"""The inventory: the model of one formation's input that every later part reads (curves, units, steps,
sections, zones; code only, no model calls)."""

from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from petroharness.record.card import curve_origin
from petroharness.well.view import FormationView
from petroharness.well import summary as S


try:                                            # petrophys's own curve vocabulary (it supplies, the harness reads)
    from petrophys.reporting.reference_export import FAMILY_LABELS as _PP_LABELS, REFERENCE_CURVE_TO_STEP as _PP_STEPS
except Exception:                               # an older petrophys without them: those sources are skipped
    _PP_LABELS, _PP_STEPS = {}, {}

SOURCES = ("input", "computed", "analyzer", "copy", "unknown")
PROPERTIES = {"porosity": "PHIC", "permeability": "KH_CORE", "water saturation": "SWC"}     # property -> its plug curve


@dataclass
class Curve:
    name: str
    unit: str
    meaning: str
    meaning_from: str                  # registry (the curve catalog) | petrophys description | petrophys label | LAS header
                                       # | registry family | step | unknown
    source: str                        # one of SOURCES
    step: Optional[str] = None         # the step that wrote it (computed)
    by: str = ""                       # the analysis inside that step that wrote it, where the record says (written_by)
    inputs: Optional[list] = None      # the curves that step read, where the record lists them
    copy_of: Optional[str] = None
    step_from: Optional[str] = None    # "record" | "petrophys curve map" (computed)
    coverage: float = 0.0              # share of the interval's samples with data
    n: int = 0
    zone_coverage: dict = field(default_factory=dict)   # zone id -> share of its samples with data
    percent: bool = False              # a fraction stored in percent (its values say so)
    flat: bool = False                 # one value over the interval
    measured_log: bool = False         # a measured log: an input the registry lists as one, a vendor name of one the
                                       #   workflow carries, or one the workflow carried under its name or standardized
    carried: str = ""                  # a measured log a workflow step wrote from the input itself: how (measurements)
    same_as: list = field(default_factory=list)   # the input curves that hold the same values (the LAS carrying one
                                       #   log under two names: CALI and DCAL); neither is a copy of the other
    codes: dict = field(default_factory=dict)   # code -> label, where the record maps the curve's class codes (the
                                       #   lithology log, by the data's code table): the codes it holds over the well
    well_value: Optional[float] = None  # a computed curve that holds one value over the whole well: that value (not a
                                        #   curve that varies with depth)
    catalog: str = ""                   # the curve catalog's line (rules/curves.yaml meanings: what it is; its kind and
                                        #   inputs), empty when the catalog has none; `meaning` is its first part
    run_said: str = ""                  # an analyzer's curve: how its run says it made it, where that says how (a source
                                        #   in brackets, or what from): S_V "from the datum (...)", KH "(PERM_CC -> ...)"

    @property
    def writer(self) -> str:
        """Who wrote a computed curve, as every reader names it: the analysis inside its step where the record says
        (written_by: "the hydrocarbon analysis, in the net_pay step"), else the step ("the net_pay step")."""
        if self.by:
            return f"the {self.by}" + (f", in the {self.step} step" if self.step else "")
        return f"the {self.step} step" if self.step else ""


@dataclass
class Zone:
    id: str
    lithology: str
    top: float
    base: float
    thickness: float
    n: int
    name: str = ""                     # the record's name for the zone (its lithology group, e.g. LIMESTONE_GROUP_1)
    log_shares: str = ""               # the lithology log's shares in the zone, when the zone's lithology is another
                                       #   (a formation lithology the data states)
    stated: str = ""                   # the formation's lithology as its tops state it, where the log reads another


@dataclass
class SourceRank:
    curve: str
    rank: int                          # 1 plug measurement, 2 core-corrected, 3 log model
    kind: str                          # a plain description of what the curve is


@dataclass
class SectionClass:
    name: str
    definition: Optional[str]
    intervals: Optional[int]
    thickness: Optional[float]
    share_pct: Optional[str]
    background: bool
    runs: str


@dataclass
class Section:
    key: str
    family: str                                        # the analyzer family (the key's first part)
    title: str
    method: Optional[str]
    basis: Optional[str]
    classes: list = field(default_factory=list)
    other: list = field(default_factory=list)          # facts that are neither method, basis, thresholds nor a class
    thresholds: Optional[str] = None                   # the recorded thresholds line, kept when it is
                                                       #   not in the NAME: definition form (never dropped unread)


@dataclass
class Method:
    step: str
    method: str
    inputs: Optional[list]
    outputs: Optional[list]
    parameters: dict                   # every parameter as recorded (numbers, text, lists, tables)
    equations: list                    # decision lines that state an equation, verbatim
    decisions: list                    # the other decision lines, verbatim
    scope: str = "well"                # the record describes the whole well
    equations_here: list = field(default_factory=list)   # the equations scoped to this interval (evidence.scoped_decision)
    routes_here: list = field(default_factory=list)      # this interval's routes, read from its curves (agent.routes)
    facts_here: list = field(default_factory=list)       # what the step's output curves hold here (interval_facts)
    decisions_here: list = field(default_factory=list)   # the run's lines as written (the whole well's record)
    stage: str = "workflow"            # preparation / workflow / after (a context profile's QC and recomputation)
    said: dict = field(default_factory=dict)   # what a recorded value is, where its name alone misleads (the step
                                               #   record's parameter notes: rwa_median_over_rw, a check of the Rw)


@dataclass
class Inventory:
    well: str
    formation: str
    depth_unit: str
    top: float
    base: float
    gross: float
    step: float
    samples: int
    zones: list
    zoned_thickness: float
    curves: dict                       # name -> Curve
    properties: dict                   # property -> [SourceRank], best first
    methods: list
    header: dict                       # name -> {value, unit, description}
    value_qc: dict                     # curve -> {rule, changed} (changed: interval samples the rule altered)
    sections: list
    logs_present: list
    logs_absent: list
    record_lists_outputs: bool
    absent_meanings: dict = field(default_factory=dict)      # measured log -> what it is (it is not in the input)
    notes: list = field(default_factory=list)                 # facts about this interval's record (src/petroharness/agent/notes.py)
    logs_empty: list = field(default_factory=list)            # measured logs in the input with no values in this interval
    logs_screened: dict = field(default_factory=dict)         # of those, what the preparation's range screening removed
    reach: str = "focus"                                      # what a tool's zones may name (data.reach)
    well_span: tuple = ()                                     # the well's first and last sample depths (reach "well")
    well_samples: int = 0                                     # the well's samples (the log's whole length)
    units: list = field(default_factory=list)                 # the tops file's units in reach: (name, top, base)
    zones_source: Optional[str] = None                        # the zones file of the user's zones (they are `zones`)
    lithology_zones: list = field(default_factory=list)       # under the user's zones: (id, lithology, top, base)

    def to_dict(self) -> dict:
        return asdict(self)


# --- curves ----------------------------------------------------------------------------------------------------

def _twins(view: FormationView, curves: dict) -> None:
    """Input curves that hold the same values name each other (Curve.same_as): a LAS that carries one log under two
    names (a vendor's and the standard one). The inventory found copies only among computed curves, so two supplied
    curves with one log's values read as two logs."""
    from petroharness.record.card import _same_values
    inputs = [c for c, cv in curves.items() if cv.source == "input"]
    data = {c: view.prep.curve(c) for c in inputs}
    for i, a in enumerate(inputs):
        for b in inputs[i + 1:]:
            if curves[a].n == curves[b].n and _same_values(data[a], data[b]):
                curves[a].same_as.append(b)
                curves[b].same_as.append(a)


def measured_logs(reg) -> set:
    """The registry's measured logs (its raw list and log families): names that are measurements, whatever wrote
    them. The one list of them (the inventory reads it; a curve's status reads the inventory)."""
    fam = [c for members in (reg.curves.get("families") or {}).values() for c in members]
    return {c.upper() for c in list(reg.raw_order) + fam}


def _carried(curves: dict, measured: set) -> None:
    """A measured log a workflow step wrote from the input itself is a measurement, not a model output: the input
    under the workflow's name (a copy of a measured input: RDEP holding ILD's values) or the input as the step
    standardized it (the step reads and writes the same measured log: units, nulls, ranges); and the input a measured
    workflow curve copies (a vendor name: DENS for the workflow's RHOB) is a measured log too."""
    for c, cv in curves.items():
        if cv.source != "computed" or not cv.step:
            continue
        inputs = [str(i) for i in (cv.inputs or [])]
        if cv.copy_of and cv.copy_of in inputs and (c.upper() in measured or cv.copy_of.upper() in measured):
            cv.carried, cv.measured_log = f"measurement: the input {cv.copy_of} under the workflow's name (the {cv.step} step)", True
        elif c.upper() in measured and c in inputs:
            cv.carried, cv.measured_log = f"measurement, as the {cv.step} step standardized it", True
    for c, cv in curves.items():
        if cv.source == "input" and any(x.copy_of == c and x.name.upper() in measured for x in curves.values()):
            cv.measured_log = True


def _registry_meaning(reg, curve: str) -> Optional[str]:
    """The registry's meaning without its method placeholder ("= {method}", "({method})")."""
    m = (reg.curves.get("meanings") or {}).get(curve)
    if not m:
        return None
    m = re.sub(r"\s*\(\{[a-z_]+\}\)", "", m)
    m = re.sub(r"\s*=\s*\{[a-z_]+\}", "", m)
    return " ".join(m.split()).strip(" ,")


def _petrophys_description(view: FormationView, curve: str) -> Optional[str]:
    c = view.prep.well.get(curve) if curve in set(view.prep.well.curves) else None
    d = getattr(getattr(c, "metadata", None), "description", "") if c is not None else ""
    d = (d or "").strip()
    return d if d and d.upper() != curve.upper() else None          # a description that only repeats the name says nothing


def _las_description(view: FormationView, curve: str) -> Optional[str]:
    from petroharness.record.card import _las_description as las
    d = (las(view, curve) or "").strip()
    return d if d and d.upper() != curve.upper() else None


def _source(view: FormationView, curve: str, measured: set, analyzer: set, listed: bool) -> dict:
    """The curve's source, from the record and the LAS (card.curve_origin), then the analyzers and petrophys's map."""
    origin = curve_origin(view, curve)
    if origin and origin[0] == "step":
        by = ((view.prep.steps or {}).get(origin[1]) or {}).get("written_by") or {}
        return {"source": "computed", "step": origin[1], "inputs": list(origin[2] or []) or None, "step_from": "record",
                **({"by": str(by[curve])} if curve in by else {})}
    if origin and origin[0] == "supplied":
        return {"source": "input", "measured_log": curve.upper() in measured}
    if origin and origin[0] == "copy":
        return {"source": "copy", "copy_of": origin[1]}
    if curve in analyzer:
        return {"source": "analyzer"}
    if curve in _PP_STEPS and not listed:   # a record that lists no step's outputs: petrophys's curve-to-step map (a
                                            #   record that lists them names every curve's writer itself)
        recorded = _PP_STEPS[curve] in (view.prep.steps or {})
        return {"source": "computed", "step": _PP_STEPS[curve],
                "step_from": "petrophys curve map" + ("" if recorded or not listed else " (step not in the record)")}
    return {"source": "unknown"}


def lithology_logs(view: FormationView) -> set:
    """The curves that are the lithology log here, whatever the LAS calls them: the one the view detected (or the data
    config names) and the policy's lithology curves."""
    names = {str(view.lithology_curve or "").upper()} | {str(c).upper() for c in (view.policy.get("lithology", {}) or {}).get("curve") or []}
    return {n for n in names if n}


def _meaning(view: FormationView, curve: str, src: dict) -> tuple[str, str]:
    """What the curve is, the same whatever its source; where it came from is the source field."""
    reg = view.reg
    if curve.upper() in lithology_logs(view) and reg.curves.get("lithology_log"):
        return str(reg.curves["lithology_log"]), "registry"            # the catalog's line for the lithology log
    for getter, label in ((lambda: _registry_meaning(reg, curve), "registry"),     # the curve catalog
                          (lambda: _PP_LABELS.get(curve), "petrophys label"),
                          (lambda: _petrophys_description(view, curve), "petrophys description"),
                          (lambda: _las_description(view, curve), "LAS header")):
        m = getter()
        if m:
            return m, label
    family = next((f for f, members in (reg.curves.get("families") or {}).items() if curve in members), None)
    if src.get("measured_log") and family:
        return f"{family} log", "registry family"
    if src.get("step"):
        return f"output of the {src['step']} step", "step"
    return "unknown", "unknown"


def _absent_meaning(reg, curve: str) -> str:
    """What a measured log that is not in the input is (the registry's curve catalog, petrophys label, or
    its family)."""
    m = _registry_meaning(reg, curve) or _PP_LABELS.get(curve)
    if m:
        return m
    family = next((f for f, members in (reg.curves.get("families") or {}).items() if curve in members), None)
    return f"{family} log" if family else ""


def _curve_names(view: FormationView, store) -> list:
    names = list(dict.fromkeys(list(view.prep.well.curves) + list(getattr(view, "analyzer_curves", {}) or {})
                               + (list(store.curves) if store is not None else [])))
    return [c for c in names if c.upper() != "DEPT" and view.available(c)]


def _checked_meaning(view: FormationView, c: str, meaning: str) -> str:
    """a curve named shear whose values track compressional slowness (within 10% of DTC at the median)
    says so: a mnemonic table's label is not a measurement (an answer called such a curve shear sonic)."""
    if "shear" not in meaning.lower() or c == "DTC" or not view.available("DTC") or not view.available(c):
        return meaning
    x, d = (np.asarray(view.values(n), dtype=float) for n in (c, "DTC"))
    ok = np.isfinite(x) & np.isfinite(d) & (d > 0)
    if ok.sum() < 10:
        return meaning
    r = float(np.median(x[ok] / d[ok]))
    return meaning + (f" (its values track DTC: median ratio {r:.2f}; shear slowness reads about 1.5-2 times DTC)"
                      if 0.9 <= r <= 1.1 else "")


def _well_value(view: FormationView, c: str, src: dict) -> Optional[float]:
    """The one value a curve a workflow step wrote holds over the whole well (a step parameter written as a curve, e.g.
    SWIRR_APP), or None: a curve with more than one value, an input, a flag or a class (registry flags; meanings that
    say a flag or a class)."""
    if src.get("source") != "computed" or src.get("copy_of") or view.is_flag(c):
        return None
    if re.search(r";\s*an?\s+(?:flag|class)\b", (view.reg.curves.get("meanings") or {}).get(c) or ""):
        return None
    whole = view.prep.curve(c)
    fin = whole[np.isfinite(whole)] if whole is not None else np.array([])
    return float(fin[0]) if fin.size > 1 and float(np.min(fin)) == float(np.max(fin)) else None


def _run_said(view: FormationView, c: str, src: dict) -> str:
    """An analyzer's curve this run made its own way: its run's description (recorded where Petrophys gives the run's
    basis, DerivedCurve.basis), which the catalog's general line cannot know; else ""."""
    if src.get("source") != "analyzer":
        return ""
    return str((getattr(view, "analyzer_described", None) or {}).get(c) or "")


def _same_as_workflow(view: FormationView, curves: dict) -> None:
    """An analyzer's curve that holds a workflow curve's values wherever it has values (RXO_RDEP_RATIO and
    SEPARATION_RATIO: the workflow's INVASION_RATIO) is marked a copy of it, so the map says "same values as"; one
    value throughout matches too easily and is left alone."""
    work = [n for n, cv in curves.items() if cv.source == "computed" and not cv.copy_of]
    for c, cv in curves.items():
        if cv.source != "analyzer" or cv.copy_of:
            continue
        a = view.well_values(c)
        if a is None:
            continue
        a = np.asarray(a, dtype=float)
        fa = np.isfinite(a)
        if fa.sum() < 2 or float(np.nanmin(a)) == float(np.nanmax(a)):
            continue
        for w in work:
            b = view.prep.curve(w)
            if b is None or np.shape(b) != a.shape:
                continue
            b = np.asarray(b, dtype=float)
            both = fa & np.isfinite(b)
            if both.sum() >= 0.95 * fa.sum() and np.allclose(a[both], b[both], rtol=1e-9, atol=0):
                cv.copy_of = w
                break


# --- properties ----------------------------------------------------------------------------------------------------

def _properties(view: FormationView, curves: dict) -> dict:
    """Each property's curves ranked by anchoring: plug measurement (with samples here), then core-corrected, then a
    log model. Core-corrected curves are the registry's core_substitution pairs; a copy keeps its source's rank."""
    reg = view.reg
    pairs = reg.expansion["core_substitution"]["pairs"]                     # log curve -> core-corrected curve
    corrected = set(pairs.values())
    out = {}
    for prop, plug in PROPERTIES.items():
        logs = list((reg.curves.get("core") or {}).get("log_pairs", {}).get(plug, []))
        ranks = []
        if plug in curves:
            ranks.append(SourceRank(plug, 1, f"plug measurement ({curves[plug].n} samples)"))
        for c in logs:
            if c not in curves:
                continue
            cv = curves[c]
            where = "input" if cv.source == "input" else f"computed by {cv.writer}" if cv.source == "computed" else cv.source
            if cv.copy_of:                             # a copy, or a step that passed its input through
                ranks.append(SourceRank(c, 2 if cv.copy_of in corrected else 3, f"copy of {cv.copy_of}"))
            elif c in corrected:
                ranks.append(SourceRank(c, 2, f"core-calibrated ({where})"))
            else:
                ranks.append(SourceRank(c, 3, f"log model ({where})" if cv.source == "computed" else f"({where})"))
        copy = lambda r: bool(curves[r.curve].copy_of) if r.curve in curves else False
        out[prop] = sorted(ranks, key=lambda r: (r.rank, copy(r), logs.index(r.curve) if r.curve in logs else -1))
    return out


def calibrated_twins(inv: "Inventory") -> dict:
    """{log curve: its core-calibrated twin}, as the properties rank them: a core-calibrated curve (not a copy) with
    data here, beside the log curve the record names it after (X and X_CC), where the two hold different values."""
    out = {}
    for ranks in inv.properties.values():
        for r in ranks:
            cv, base = inv.curves.get(r.curve), r.curve[:-3] if r.curve.endswith("_CC") else ""
            if r.rank == 2 and cv is not None and cv.n and not cv.copy_of and base in inv.curves \
                    and inv.curves[base].copy_of != r.curve:
                out[base] = r.curve
    return out


# --- methods -----------------------------------------------------------------------------------------------------

_EQUATION = re.compile(r"^[A-Za-z][A-Za-z0-9_()]*(?:\s*[,/]\s*[A-Za-z][A-Za-z0-9_]*)?\s*=\s*\S")


def _methods(view: FormationView) -> list:
    out = []
    routes = {}
    # the routes this interval's samples took (the record is the well's)
    from petroharness.agent.routes import route_lines
    routes = route_lines(view)
    for step, rec in (view.prep.steps or {}).items():
        rec = rec or {}
        params = copy.deepcopy(dict(rec.get("parameters") or {}))
        lines = [d for d in rec.get("decisions") or [] if isinstance(d, str)]
        eq = [d for d in lines if _EQUATION.match(d)]
        rest = [d for d in lines if d not in eq]
        from petroharness.record.catalog import interval_facts
        facts, _ = interval_facts(view, list(rec.get("outputs") or []))
        here = routes.get(step, [])                                  # this interval's route (data), the lines as written
        said = {k: v for k, v in (rec.get("notes") or {}).items() if k in params}    # Petrophys's notes on them
        out.append(Method(step=step, method=str(rec.get("method") or ""), inputs=rec.get("inputs"),
                          outputs=rec.get("outputs"), parameters=params, equations=eq, decisions=rest,
                          equations_here=eq, decisions_here=rest, routes_here=here, facts_here=facts,
                          stage=str(rec.get("stage") or "workflow"), said=said))
    return out


# --- header and value QC ---------------------------------------------------------------------------------------------

def _header(view: FormationView) -> dict:
    """The LAS header parameters: NAME with NAME__UNIT and NAME__DESCR folded in; internal keys (_...) left out."""
    raw = dict(getattr(view.prep, "header_parameters", None) or {})
    out = {}
    for k, v in raw.items():
        if k.startswith("_") or "__" in k:
            continue
        out[k] = {"value": v, "unit": raw.get(f"{k}__UNIT", ""), "description": raw.get(f"{k}__DESCR", "")}
    return out


def _value_qc(view: FormationView) -> dict:
    qc = dict(getattr(view.prep, "value_qc", None) or {})
    rules, changed = qc.get("rules") or {}, qc.get("changed") or {}
    out = {}
    for c, rule in rules.items():
        ch = changed.get(c)
        n = None
        try:
            arr = np.asarray(ch, dtype=bool)
            if arr.shape == view.mask.shape:
                n = int(arr[view.mask].sum())
        except (TypeError, ValueError):
            n = None
        out[c] = {"rule": rule, "changed": n}
    return out


# --- sections ----------------------------------------------------------------------------------------------------

_CLASS = re.compile(r"^(?P<name>[A-Z][A-Z0-9_]+) \((?P<body>\d+ intervals?[^)]*)\): (?P<runs>.*)$")   # zone value lines are not classes


def _section(key: str, d: dict) -> Section:
    sec = Section(key=key, family=key.split(".", 1)[0], title=d.get("title", ""), method=None, basis=None)
    definitions = {}
    for f in d.get("facts") or []:
        f = str(f)
        if f.startswith("method:"):
            sec.method = f[len("method:"):].strip()
        elif f.startswith("basis:"):
            sec.basis = f[len("basis:"):].strip()
        elif f.startswith("thresholds:"):
            sec.thresholds = f[len("thresholds:"):].strip()            # read below, against the classes
        else:
            m = _CLASS.match(f)
            if m:
                body = m.group("body")
                iv = re.search(r"(\d+) intervals?", body)
                th = re.search(r"([\d.]+) (?:ft|m)\b", body)
                sh = re.search(r"(<?[\d.]+)% of the zoned thickness", body)
                sec.classes.append(SectionClass(m.group("name"), None, int(iv.group(1)) if iv else None,
                                                float(th.group(1)) if th else None, sh.group(1) if sh else None,
                                                "background class" in body, m.group("runs")))
            else:
                sec.other.append(f)
    if sec.thresholds:
        definitions.update(criteria(sec.thresholds, [c.name for c in sec.classes]))
    for c in sec.classes:
        c.definition = definitions.get(c.name)
    if all(c.definition or c.background for c in sec.classes):    # every class carries its criterion: the line is read
        sec.thresholds = None
    return sec


_NAMED = re.compile(r"^\s*(?P<name>[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*):\s+(?P<def>\S.*?)\s*\.?\s*$")


def criteria(raw: str, classes: list) -> dict:
    """Each class's criterion from a section's thresholds line: the line's parts, split at ';' and at a
    sentence's end, read as 'NAME: rule' (the rule, as recorded) or as a band (_banded); a part naming no class, or a
    rule in words that is one part of a longer rule, is left to the recorded line."""
    out = {}
    for seg in re.split(r";|\.\s+(?=[A-Z])", str(raw or "")):
        m = _NAMED.match(seg)
        if m and m.group("name") in classes and m.group("name") not in out:
            out[m.group("name")] = m.group("def").strip()
    for k, v in _banded(raw, classes).items():
        out.setdefault(k, v)
    return out


_BAND = re.compile(r"^\s*(?:[A-Za-z][A-Za-z ]*:\s+)?(?P<name>[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*)\s*:?\s+(?P<def>\S.*?)\s*\.?\s*$")


_VALUE_FIRST = re.compile(r"^(?:[<>]=?|=|-?\d|between\b)")


def _banded(raw: str, classes: list) -> dict:
    """Class definitions from a thresholds line written as bands ('EXCELLENT < 0.20; GOOD 0.20-0.40', 'MEGA_PORES >=5;
    MACRO_PORES >=2 to <5', 'MHI bands: HIGH_MOVEABLE_HC <0.5, MODERATE 0.5-0.7'): a band names a class exactly, or
    is the first word of exactly one class (EXCELLENT -> EXCELLENT_HC_SATURATION) when the band is a plain value range
    ('< 0.20', '0.20-0.40', 'between -0.05 and 0.05'); a rule in words ('EXCELLENT when >0.15', one part of a quality
    rule) is left to the recorded line, as is a band naming no class or several. The definition is the band as recorded."""
    out = {}
    for seg in re.split(r";|,(?=\s*[A-Z][A-Z0-9_]*\s+[^,A-Z])|\.\s+(?=[A-Z])", raw):
        m = _BAND.match(seg)
        if not m or not re.search(r"\d", m.group("def")):
            continue                                      # a list of names, or a band without a value
        name, band = m.group("name"), m.group("def").strip()
        hit = [c for c in classes if c == name]
        if not hit and _VALUE_FIRST.match(band):          # a first word stands for a class only before a plain band
            hit = [c for c in classes if c.startswith(name + "_")]
        if len(hit) == 1 and hit[0] not in out:
            out[hit[0]] = f"{name} {band}" if hit[0] != name else band
    return out


# --- build ----------------------------------------------------------------------------------------------------

def _log_shares(view, z) -> str:
    """The lithology log's shares of a zone's samples ("SHALE 99.4%, NO_LITHOLOGY_DATA 0.6%") when they are not all
    the zone's own lithology: a zone labelled by its formation's stated lithology keeps the log's reading beside it."""
    labels = getattr(view, "labels", None)
    if labels is None or not len(getattr(z, "indices", [])):
        return ""
    lab = np.asarray(labels, dtype=object)[np.asarray(z.indices)]
    vals, counts = np.unique(lab.astype(str), return_counts=True)
    if len(vals) == 1 and str(vals[0]).upper() == str(z.lithology).upper():
        return ""
    order = np.argsort(-counts)
    return ", ".join(f"{vals[i]} {100 * counts[i] / lab.size:.1f}%" for i in order)


def _codes(view: FormationView, c: str) -> dict:
    """{code: label} of the class codes a curve holds over the well, where the record maps them
    (petroharness.well.summary.code_labels); {} otherwise."""
    from petroharness.well import summary
    labels = summary.code_labels(view, c)
    if not labels:
        return {}
    k = summary.curve_kind(view, c)
    return {code: labels[code] for code in k.codes if code in labels} if k.kind != "values" else {}


def from_view(view: FormationView, store=None) -> Inventory:
    reg = view.reg
    steps = view.prep.steps or {}
    listed = any("outputs" in (rec or {}) for rec in steps.values())
    measured = measured_logs(reg)
    analyzer = set(getattr(view, "analyzer_curves", {}) or {})
    curves = {}
    for c in _curve_names(view, store):
        src = _source(view, c, measured, analyzer, listed)
        if src.get("source") == "computed" and src.get("inputs"):    # a step that passed an input through: its values
            from petroharness.record.card import _same_values
            whole = view.prep.curve(c)
            same = next((i for i in src["inputs"] if i != c and _same_values(whole, view.prep.curve(i))), None)
            if same:
                src["copy_of"] = same
        meaning, frm = _meaning(view, c, src)
        catalog = meaning if frm == "registry" else ""          # the map shows the catalog's line; tools its first part
        meaning = _checked_meaning(view, c, meaning.split("; ")[0] if catalog else meaning)
        x = view.values(c)
        n = int(np.isfinite(x).sum()) if x is not None else 0
        zc = {}
        for z in view.zones:
            zx = view.zone_values(z, c)
            zc[z.zone_id] = float(np.isfinite(zx).mean()) if zx is not None and zx.size else 0.0
        fin = x[np.isfinite(x)] if x is not None else np.array([])
        one = _well_value(view, c, src)
        curves[c] = Curve(name=c, unit=view.unit(c) or "", meaning=meaning, meaning_from=frm, n=n,
                          coverage=float(n / x.size) if x is not None and x.size else 0.0, zone_coverage=zc,
                          percent=bool(view.in_percent(c)), flat=bool(fin.size > 1 and np.nanmin(fin) == np.nanmax(fin)),
                          codes=_codes(view, c), well_value=one, catalog=catalog, run_said=_run_said(view, c, src), **src)
    _same_as_workflow(view, curves)
    _carried(curves, measured)
    _twins(view, curves)
    zones = [Zone(z.zone_id, z.lithology, float(z.top), float(z.base), float(z.thickness), int(z.n_samples),
                  str(getattr(z, "name", "") or ""), _log_shares(view, z), str(getattr(z, "stated", "") or ""))
             for z in view.zones]
    sections = []
    for k in (store.sections if store is not None else []):
        sec = _section(k, _section_dict(store, k))
        sec.basis = _basis(view, store, k)
        sections.append(sec)
    present = [c for c in reg.raw_order if c in curves]
    absent = [c for c in reg.raw_order if c not in curves]
    in_well = {str(c).upper() for c in view.prep.well.curves}
    empty = [c for c in absent if c.upper() in in_well]            # in the input, but no value in this interval
    return Inventory(well=view.task.well, formation=view.task.formation, depth_unit=view.depth_unit,
                     top=float(view.top), base=float(view.base), gross=float(view.gross), step=float(view.step),
                     samples=int(view.mask.sum()) if getattr(view, "mask", None) is not None else 0,
                     zones=zones, zoned_thickness=float(view.zoned_thickness), curves=curves,
                     properties=_properties(view, curves), methods=_methods(view), header=_header(view),
                     value_qc=_value_qc(view), sections=sections, logs_present=present,
                     logs_absent=absent, record_lists_outputs=listed,
                     absent_meanings={c: _absent_meaning(reg, c) for c in absent},
                     notes=_notes(view, curves, sections), logs_empty=empty,
                     logs_screened={c: S.screened(view, c) for c in empty if S.screened(view, c)}, **_reach(view))


def _reach(view) -> dict:
    """What a tool's zones may name beyond the interval's zones (reach "well"): the well's span and the tops file's
    units, in the reporting unit; nothing under reach "focus"."""
    out = {}
    if getattr(view, "zones_source", None):                  # the user's zones frame it; the lithology zones: L1..
        out = {"zones_source": view.zones_source,
               "lithology_zones": [(z.zone_id, z.lithology, float(z.top), float(z.base))
                                   for z in getattr(view, "lithology_zones", [])]}
    if getattr(view, "reach", "focus") != "well":
        return out
    d = np.asarray(view.prep.depth, dtype=float) * view.depth_scale
    return {**out, "reach": "well", "well_span": (float(np.nanmin(d)), float(np.nanmax(d))),
            "well_samples": int(np.isfinite(d).sum()),
            "units": [(u.name, float(u.top), float(u.base)) for u in getattr(view, "units", [])]}


def _notes(view, curves, sections) -> list:
    from petroharness.agent.notes import notes
    return notes(view, curves, sections)


def _basis(view: FormationView, store, key: str) -> Optional[str]:
    """What a section's classes rest on, as facts (registry curves.section_basis, its plain wording): where that curve
    has values, the zones without it, and what a sample without it gets."""
    spec = (view.reg.curves.get("section_basis") or {}).get(key)
    if not spec or not spec.get("plain"):
        return None
    c, plain = spec["curve"], spec["plain"]
    if c in store.derived:
        return plain["derived"]
    x = view.values(c) if view.available(c) else None
    fed = lambda z: all(view.available(i) and np.isfinite(view.zone_values(z, i)).any() for i in spec.get("inputs", []))
    if x is None or not np.isfinite(x).any():
        return f"no {c} values in this interval; {plain['none']}" if any(fed(z) for z in view.zones) else None
    has = [z.zone_id for z in view.zones if np.isfinite(view.zone_values(z, c)).any()]
    none = [z.zone_id for z in view.zones if z.zone_id not in has and fed(z)]
    zoned = x[view.zoned]
    share = 100 * float(np.isfinite(zoned).mean()) if zoned.size else 0.0
    text = f"the classes rest on {c}; {c} has values in {share:.1f}% of the zoned samples"
    if none:
        text += f"; {'zone' if len(none) == 1 else 'zones'} {', '.join(none)} {'has' if len(none) == 1 else 'have'} no {c}: {plain['none']}"
    if share < 100:
        text += f"; {plain['missing']}"
    return text


def _section_dict(store, key: str) -> dict:
    from petroharness.record.sections import section_dict          # the store's section rendering, as the tools present it
    return section_dict(store, key)


