"""The interpretation settings a user may change before Petrophys interprets a well (the web UI's settings panel;
ask(..., interpretation=...)): Petrophys's own, read from the library (petrophys.workflow.DynamicWorkflowConfig: each
setting's group, help, default, unit and choices), and the harness's zone rule. A setting left unset keeps its
default: the policy's for the zones and the net-pay cutoffs, Petrophys's for the rest (often read from the LAS header
or derived from the data, which a preview shows for the well in hand).

    schema()                    the settings, grouped for the page: {"groups": [{"key", "title", "about", "fields": [...]}]}
    validate(settings)          {setting: what is wrong} for the settings a user gave (empty: all can be used)
    split(settings)             (Petrophys's options, the data's zone settings) for a run
    used(prep)                  {setting: the value Petrophys used} on a prepared well, from its step record
"""
from __future__ import annotations

import dataclasses
import functools
import inspect
import re
from typing import Any

# The page's groups, in order, and the Petrophys settings each holds; a Petrophys setting no group names is shown
# under "More from Petrophys", so a setting added to the library appears without a change here. A setting whose type
# takes a table, a list or a pair rather than one value is not a field (_takes_a_table): a settings file gives it under
# data.interpret. HIDDEN: those that take a file or name the data, and the library's internal flags.
GROUPS = [
    ("zones", "Zones", "How the interval is split into zones: the unit every answer reports on.", []),
    ("clay", "Clay volume", "How shale volume (VCL) is computed from the gamma ray, SP and density-neutron.",
     ["gr_method", "gr_min", "gr_max", "sp_min", "sp_max", "rho_cl"]),
    ("porosity", "Porosity and matrix", "The matrix and fluid properties the porosity equations use.",
     ["matrix_type", "rho_ma", "nphi_ma", "dt_ma", "rho_fl", "dt_fl", "phi_cl", "apply_hc_correction", "hc_type",
      "rho_hc", "hc_hydrogen_index"]),
    ("water", "Formation water", "Rw: given, from salinity, or estimated from the data.",
     ["rw", "rw_meas_temp_f", "salinity_ppm", "allow_default_rw"]),
    ("saturation", "Water saturation", "The saturation model and its parameters.",
     ["sw_model", "a", "m", "n", "m_star", "cec", "b_coeff", "rwb", "rtsh", "vsh_exp", "shale_exp",
      "sw_routing_vcl_cutoff"]),
    ("permeability", "Permeability", "The permeability transform and the irreducible water saturation.",
     ["perm_method", "perm_fallback_method", "swirr", "swirr_flag_phi_cl", "use_peer_core"]),
    ("pay", "Net reservoir and pay", "The cutoffs that flag net reservoir and net pay.",
     ["vcl_cutoff", "phie_cutoff", "sw_cutoff", "reuse_input_resflag"]),
    ("temperature", "Temperature", "The temperature profile Rw and Rmf are corrected along.",
     ["surface_temp_f", "bht_f", "td_ft", "gradient_f_per_100ft"]),
    ("mud", "Mud", "Mud type and filtrate properties (Rmf, Rm).",
     ["mud_type", "mud_water", "mud_has_clay_or_kcl", "rmf_at_meas_temp", "rmf_meas_temp_f", "rmf_salinity_ppm",
      "rmf_chlorides_mg_l", "rm", "rm_meas_temp_f"]),
    ("lithology", "Lithology", "The interpretation domain and the mineral solve.",
     ["lithology_domain", "lithology_source", "carbonate_calibration", "mineral_solver_version"]),
    ("input", "Input handling", "How the LAS curves are read and checked.",
     ["standardize_input", "rename_input_curves", "calculation_profile"]),
]
HIDDEN = {"raise_on_error", "peer_wells", "formation_tops", "zones", "lithology", "lithology_csv", "lithology_intervals",
          "lithology_codes", "lithology_curve", "skip_steps", "nd_clay", "curve_aliases"}
# the settings most interpretations are checked on, shown first in their groups
COMMON = {"zone_min_thickness_m", "zone_vcl_bands", "zone_layout", "gr_method", "gr_min", "gr_max", "matrix_type",
          "rho_ma", "rw", "salinity_ppm", "sw_model", "a", "m", "n", "perm_method", "vcl_cutoff", "phie_cutoff",
          "sw_cutoff", "bht_f", "mud_type", "lithology_domain"}
LABELS = {
    "gr_method": "GR to shale volume", "gr_min": "GR clean (gr_min)", "gr_max": "GR shale (gr_max)",
    "sp_min": "SP shale (sp_min)", "sp_max": "SP clean (sp_max)", "rho_cl": "Clay density", "matrix_type": "Matrix",
    "rho_ma": "Matrix density (ρma)", "nphi_ma": "Matrix neutron porosity", "dt_ma": "Matrix sonic (Δtma)",
    "rho_fl": "Fluid density (ρfl)", "dt_fl": "Fluid sonic (Δtfl)", "phi_cl": "Clay porosity",
    "apply_hc_correction": "Hydrocarbon correction", "hc_type": "Hydrocarbon type", "rw": "Rw",
    "rw_meas_temp_f": "Rw temperature", "salinity_ppm": "Water salinity", "allow_default_rw": "Default Rw if none found",
    "sw_model": "Saturation model", "a": "Tortuosity a", "m": "Cementation m", "n": "Saturation exponent n",
    "m_star": "Shaly-sand m*", "cec": "CEC", "b_coeff": "B coefficient", "rwb": "Bound-water Rwb", "rtsh": "Shale Rt",
    "vsh_exp": "Shale-volume exponent", "shale_exp": "Shale exponent", "sw_routing_vcl_cutoff": "Shaly-sand model above VCL",
    "perm_method": "Permeability transform", "perm_fallback_method": "Fallback transform", "swirr": "Irreducible Sw",
    "swirr_flag_phi_cl": "Swirr reservoir flag", "use_peer_core": "Use core from peer wells",
    "vcl_cutoff": "VCL cutoff", "phie_cutoff": "PHIE cutoff", "sw_cutoff": "SW cutoff",
    "reuse_input_resflag": "Reuse the LAS reservoir flag", "surface_temp_f": "Surface temperature",
    "bht_f": "Bottom-hole temperature", "td_ft": "Total depth for BHT", "mud_type": "Mud type", "mud_water": "Mud water",
    "mud_has_clay_or_kcl": "Mud has clay or KCl", "rmf_at_meas_temp": "Rmf", "rmf_meas_temp_f": "Rmf temperature",
    "rmf_salinity_ppm": "Filtrate salinity", "rmf_chlorides_mg_l": "Filtrate chlorides", "rm": "Rm",
    "rm_meas_temp_f": "Rm temperature", "lithology_domain": "Interpretation domain", "lithology_source": "Lithology source",
    "carbonate_calibration": "Carbonate calibration", "mineral_solver_version": "Mineral solver version",
    "standardize_input": "Standardize curves and units", "rename_input_curves": "Rename vendor mnemonics",
    "calculation_profile": "Calculation profile",
    "rho_hc": "Hydrocarbon density (ρhc)", "hc_hydrogen_index": "Hydrocarbon hydrogen index",
    "gradient_f_per_100ft": "Geothermal gradient",
}
UNITS = (("degF", "°F"), ("ohm.m", "ohm.m"), ("g/cm3", "g/cm³"), ("us/ft", "µs/ft"), ("ppm", "ppm"), ("mg/l", "mg/l"),
         ("v/v", "v/v"), ("in feet", "ft"), ("API", "API"), ("mV", "mV"), ("meq/100g", "meq/100 g"),
         ("meq/100 g", "meq/100 g"))
# the harness's own: the zone rule (policy zones), set per run through the data settings
ZONE_FIELDS = [
    {"key": "zone_min_thickness_m", "label": "Minimum zone thickness", "kind": "number", "unit": "m", "length": True,
     "help": "A run of one lithology (or one shale-volume band) no thicker than this is not a zone; its samples stay "
             "in the whole-interval statistics as samples outside the zones.",
     "more": "Thin-bedded intervals (a few feet per bed) keep few zones at the default; a smaller value keeps more, and "
             "each zone then rests on fewer samples."},
    {"key": "zone_vcl_bands", "label": "Shale-volume bands", "kind": "bands", "unit": "v/v",
     "help": "For a well with neither a lithology log nor a solved lithology: the VCL edges of the clean, shaly and "
             "shale-prone bands that zone it.",
     "more": "Below the first edge a sample is clean, between the edges shaly, above the second shale-prone."},
    {"key": "zone_layout", "label": "Zone layout", "kind": "choice", "choices": ["lithology_runs", "formation"],
     "choice_labels": {"lithology_runs": "Runs of one lithology", "formation": "The whole interval as one zone"},
     "help": "Split the interval into runs of one lithology, or keep it as one zone."},
]


def _doc_fields(cls) -> dict:
    """{field: (Petrophys's group heading, its doc)} read from the class source: '# -- Heading --' lines open a group,
    '#:' lines document the field that follows."""
    out, group, doc = {}, "", []
    for line in inspect.getsource(cls).splitlines():
        s = line.strip()
        head = re.match(r"#\s*--\s*(.+?)\s*-+\s*$", s)
        if head:
            group, doc = head.group(1), []
        elif s.startswith("#:"):
            doc.append(s[2:].strip())
        elif re.match(r"^[a-z_][a-z0-9_]*\s*:", s):
            out[s.split(":", 1)[0].strip()] = (group, " ".join(doc))
            doc = []
        elif not s.startswith("#"):
            doc = [] if s else doc
    return out


def _choices(cls, name: str) -> list:
    """The values Petrophys accepts for a text setting, read from its own validation message ('use one of: ...')."""
    try:
        cls(**{name: "__not_a_choice__"})
    except Exception as exc:  # noqa: BLE001
        m = re.search(r"use one of:\s*(.+)", str(exc))
        if m:
            listed = re.split(r",\s*or\s+|\s+or\s+", m.group(1), maxsplit=1)[0]
            return [c.strip() for c in listed.split(",") if re.fullmatch(r"[A-Za-z0-9_]+", c.strip())]
    return []


def _unit(doc: str, kind: str = "number") -> str:
    """A number's unit, as its help states it: the first unit named in the first sentence (Petrophys writes it after
    the name: 'Mud-filtrate chlorides (Cl-), mg/l, ...'), else the first in the rest. Switches and choices have none
    (a unit in their help belongs to a value they set)."""
    if kind not in ("number", "integer"):
        return ""
    for text in (_first(doc), doc):
        found = [(m.start(), shown) for token, shown in UNITS
                 for m in [re.search(rf"(?<![\w/]){re.escape(token)}(?![\w/])", text)] if m]
        if found:
            return min(found)[1]
    return ""


def _first(doc: str) -> str:
    """A doc's first sentence, plain (the rest goes in the panel's 'more')."""
    plain = re.sub(r"``([^`]+)``", r"\1", re.sub(r":(?:func|class|meth|attr):`~?([^`]+)`", r"\1", doc))
    for m in re.finditer(r"[.!?](?=\s|$)", plain):          # a sentence end, not an abbreviation's period
        if not re.search(r"\b(?:i\.e|e\.g|etc|vs|cf|approx)$", plain[:m.start()]):
            return plain[:m.end()].strip()
    return plain.strip()


def _plain(doc: str) -> str:
    return re.sub(r"``([^`]+)``", r"\1", re.sub(r":(?:func|class|meth|attr):`~?([^`]+)`", r"\1", doc)).strip()


@functools.lru_cache(maxsize=1)
def schema() -> dict:
    """The settings, grouped for the page, each with its key, label, kind (number, switch, choice, bands), unit,
    choices, default (None: Petrophys reads it from the LAS header or derives it from the data), help (Petrophys's
    first sentence) and more (the rest), and whether it is common. The defaults of the zone rule and the cutoffs are
    the policy's (the harness's defaults)."""
    from petrophys.workflow import DynamicWorkflowConfig as C

    from petroharness.config import ResourcePaths
    from petroharness.well.prepare import load_policy
    policy = load_policy(ResourcePaths().policy_file)
    docs = _doc_fields(C)
    by_name = {f.name: f for f in dataclasses.fields(C) if not f.name.startswith("_")}
    cut = policy.get("cutoffs") or {}
    policy_default = {"vcl_cutoff": cut.get("vcl_max"), "sw_cutoff": cut.get("sw_max"), "phie_cutoff": cut.get("phie_min_clastic")}

    def field(name: str) -> dict:
        f, (heading, doc) = by_name[name], docs.get(name, ("", ""))
        typ = str(f.type)
        default = f.default if f.default is not dataclasses.MISSING else None
        if policy_default.get(name) is not None:
            default = policy_default[name]
        choices = _choices(C, name) if "str" in typ else []
        kind = ("switch" if "bool" in typ else "choice" if choices else
                "integer" if typ in ("<class 'int'>", "int") else "number" if any(t in typ for t in ("float", "Any", "int"))
                else "text")
        return {"key": name, "label": LABELS.get(name, name.replace("_", " ")), "kind": kind, "unit": _unit(doc, kind),
                "choices": choices, "default": default, "help": _first(doc), "more": _plain(doc),
                "common": name in COMMON, "petrophys": True, "heading": heading}

    groups, placed = [], set()
    for key, title, about, names in GROUPS:
        fields = [{"choices": [], "unit": "", "more": "", "heading": "Zones", **z, "default": _zone_default(policy, z["key"]),
                   "common": True, "petrophys": False} for z in ZONE_FIELDS] \
            if key == "zones" else [field(n) for n in names if n in by_name]
        placed.update(names)
        groups.append({"key": key, "title": title, "about": about,
                       "fields": sorted(fields, key=lambda x: not x["common"])})
    rest = [field(n) for n in by_name if n not in placed and n not in HIDDEN and not _takes_a_table(by_name[n].type)]
    if rest:
        groups.append({"key": "more", "title": "More from Petrophys", "about": "Other settings of the Petrophys workflow.",
                       "fields": rest})
    return {"groups": groups, "petrophys": _library()}


def _takes_a_table(t) -> bool:
    """A setting's type takes a table, a list or a pair (Dict, List, Tuple; with or without None), not one value."""
    import typing
    args = [a for a in typing.get_args(t) if a is not type(None)] if typing.get_origin(t) is typing.Union else [t]
    return bool(args) and all(typing.get_origin(a) in (dict, list, tuple) for a in args)


def _zone_default(policy: dict, key: str):
    z = policy.get("zones") or {}
    return {"zone_min_thickness_m": z.get("min_thickness_m"), "zone_vcl_bands": list(z.get("fallback_vcl_bands") or []),
            "zone_layout": "lithology_runs"}[key]


def _library() -> str:
    try:
        from petroharness.well.prepare import library_identity
        return library_identity()
    except Exception:  # noqa: BLE001
        return ""


def _fields() -> dict:
    return {f["key"]: f for g in schema()["groups"] for f in g["fields"]}


def validate(settings: dict) -> dict:
    """{setting: what is wrong, in words} for the settings given (unknown names, values of the wrong kind, a choice
    not on the list, zone values out of range, and what Petrophys's own validation refuses). Empty: all can be used."""
    from petrophys.workflow import DynamicWorkflowConfig as C
    known, errors, petro = _fields(), {}, {}
    for k, v in (settings or {}).items():
        f = known.get(k)
        if f is None:
            errors[k] = "not a setting this panel knows"
            continue
        kind = f["kind"]
        if kind in ("number", "integer"):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                errors[k] = "give a number"
                continue
            if kind == "integer" and int(v) != v:
                errors[k] = "give a whole number"
                continue
        elif kind == "switch" and not isinstance(v, bool):
            errors[k] = "give true or false"
            continue
        elif kind == "choice" and v not in f["choices"]:
            errors[k] = f"choose one of: {', '.join(f['choices'])}"
            continue
        elif kind == "bands":
            if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)
                    and 0 < v[0] < v[1] < 1):
                errors[k] = "give two edges between 0 and 1, the first below the second"
            continue
        if k == "zone_min_thickness_m" and not v > 0:
            errors[k] = "give a thickness above 0"
        elif f.get("petrophys"):
            petro[k] = v
    if petro:
        try:
            C(**petro)
        except Exception as exc:  # noqa: BLE001  (Petrophys says which value it refuses)
            for line in str(exc).splitlines():
                m = re.match(r"\s*-\s*([a-z_0-9]+)\s*=?(.*)", line)
                if m and m.group(1) in petro:
                    errors[m.group(1)] = line.strip(" -")
            if not any(k in errors for k in petro):
                errors["_petrophys"] = str(exc).strip()
    return errors


def split(settings: dict) -> tuple[dict, dict]:
    """(Petrophys's options for petrophys.interpret, the data settings of the zone rule) of valid settings."""
    known = _fields()
    petro = {k: v for k, v in (settings or {}).items() if known.get(k, {}).get("petrophys")}
    zones = {k: v for k, v in (settings or {}).items() if k in {z["key"] for z in ZONE_FIELDS}}
    if "zone_vcl_bands" in zones:
        zones["zone_vcl_bands"] = [float(x) for x in zones["zone_vcl_bands"]]
    return petro, zones


def used(prep) -> dict:
    """{setting: the value Petrophys used} on a prepared well, read from its step record: the parameters of its steps
    whose names are settings (the first step that records one), with the step that used it, and the unit the step
    records beside it where it records one (td_unit beside td_ft: a total depth taken from the log is in the log's
    unit, whatever the setting's name says)."""
    known = _fields()
    out: dict[str, Any] = {}
    steps = getattr(prep, "steps", None) or {}
    for step, rec in sorted(steps.items(), key=lambda kv: kv[0] != "net_pay"):   # the cutoffs: net pay's own
        for k, v in ((rec or {}).get("parameters") or {}).items():
            if k in known and k not in out and isinstance(v, (int, float, str, bool)):
                if step != "net_pay" and k in ("vcl_cutoff", "phie_cutoff", "sw_cutoff") and "net_pay" in steps:
                    continue
                params = (rec or {}).get("parameters") or {}
                applied = params.get(f"{k}_used")                                # the value Petrophys applied
                out[k] = {"value": applied if isinstance(applied, (int, float, str, bool)) else v, "step": step}
                unit = params.get(f"{k}_unit", params.get(f"{k.rsplit('_', 1)[0]}_unit"))   # td_ft: td_unit
                if isinstance(unit, str) and unit.strip():
                    out[k]["unit"] = unit.strip()
    return out


# --- a conversation's settings change (petroharness.session: Conversation.adopt) -----------------------------------------

def merged(in_force: dict, changes: dict) -> dict:
    """The settings after a change: `changes` over `in_force`, a value of None taking the setting back to its
    default (leaving it out of the settings)."""
    out = dict(in_force or {})
    for k, v in (changes or {}).items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def diff(before: dict, after: dict) -> list:
    """[{key, from, to}] for each setting whose value differs (None: the default), in the order of the settings."""
    keys = list(dict.fromkeys([*(before or {}), *(after or {})]))
    return [{"key": k, "from": (before or {}).get(k), "to": (after or {}).get(k)}
            for k in keys if (before or {}).get(k) != (after or {}).get(k)]


def _shown(key: str, value) -> str:
    if value is None:
        d = _fields().get(key, {}).get("default")
        return "the default" + (f" ({_shown(key, d)})" if d is not None else "")
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (list, tuple)):
        return " / ".join(_shown(key, x) for x in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def describe(changes: list) -> str:
    """A change in words, as the log, the prompts and the answer's header name it: "m 2 -> 1.8; rw the default -> 0.04"."""
    return "; ".join(f"{c['key']} {_shown(c['key'], c['from'])} -> {_shown(c['key'], c['to'])}" for c in changes)


def values(settings: dict) -> str:
    """Settings as values in words: "m 1.8; sw_cutoff 0.6"."""
    return "; ".join(f"{k} {_shown(k, v)}" for k, v in (settings or {}).items())
