"""The tools of the investigation, each defined once (petroharness.tools.spec.Tool).

Everything that lists tools reads TOOLSET: the brief's tool text and its groups (agent/prompts.py), the names the reply
parser knows, the door a call goes through (agent/schemas.py), the ledger's one-line listings, the web UI's groups.

Adding a tool (docs/TOOLS.md, "Adding a tool"):
  1. its function, run(formation, **arguments) -> Result, where its kind lives: agent/tools.py (a lookup of the
     record), agent/compute.py (a computed table) or agent/library/ (an object of a verb over Petrophys);
  2. its description, the text the model reads, in components/C4_tools/tool_descriptions.json;
  3. its definition below, under its group.
tests/agent/test_tool_registration.py checks every definition, and the request gate (tests/gate) proves that a change
here alters no request of the measured runs.
"""
from __future__ import annotations

from petroharness.agent import components as C  # the texts: src/petroharness/agent/components
from petroharness.agent import compute as K
from petroharness.agent import library as P
from petroharness.agent.library import calibrate as library_calibrate, check as library_check
from petroharness.agent.library import classify as library_classify, summarize as library_summarize
from petroharness.agent import tools as T
from petroharness.agent.engine import STATISTICS
from petroharness.agent.library.api import verb_tool
from petroharness.tools.spec import Tool, Toolset

# --- the groups, as the brief heads them (docs/TOOLS.md: the tools by what users ask) ----------------------------------

DESCRIBE = "DESCRIBE: what the record holds"
COMPARE = "COMPARE AND GROUP"
CHECK = "CHECK: data quality"
CALCULATE = "CALCULATE: recompute with Petrophys"
CLASSIFY = "CLASSIFY"
SUMMARIZE = "SUMMARIZE"
CALIBRATE = "CALIBRATE: against core, elastic properties"

# --- the texts and the arguments several tools share -------------------------------------------------------------------

_TEXTS = C.text("C4", "tool_descriptions")      # each tool's description
CONDITION = C.text("C4", "condition")


def _text(name: str) -> str:
    return _TEXTS[name]


ZONES = {"type": "array", "items": {"type": "string"}, "description": C.text("C4", "zones_argument")}
WHERE = {"type": "string", "description": "only the samples where " + CONDITION}
STATS = {"type": "array", "items": {"type": "string"},
         "description": f"which statistics: {', '.join(STATISTICS)}, or any percentile p1-p99; left out: n, mean, "
                        "median, p10, p90, min, max (and geo_mean where the values are positive and span more "
                        "than two orders of magnitude)"}
CURVE = {"type": "string", "description": "a curve, e.g. DTC"}
CURVES = {"type": "array", "items": {"type": "string"}, "description": "curve names, e.g. [\"GR\", \"VCL\"]"}


# --- the verbs over Petrophys ------------------------------------------------------------------------------------------

def _verb(name: str, curated, group: str, text, arguments, main: str = "curves") -> Tool:
    """A verb over Petrophys. Its own arguments reach its curated objects (the tested shortcuts); search and run reach
    every Petrophys function it serves, so none of its own arguments is required. Its description ends with what a
    search reaches. Both are built when asked: the lists of methods come from the library's catalog."""
    def description() -> str:
        from petroharness.agent.library.api import menu_line
        return text() + "\n" + menu_line(name)

    def properties() -> dict:
        out = dict(arguments())
        out.update({
            "search": {"type": "string", "description": "words to search this verb's Petrophys functions, e.g. gas"},
            "run": {"type": "string", "description": "a Petrophys function's name, as search lists it"},
            "args": {"type": "object", "description": "run's arguments: a curve name, a condition (VCL > 0.6) or a value"}})
        out.setdefault("label", {"type": "string", "description": "the new curves' prefix"})
        return out

    return Tool(name, verb_tool(name, curated), group, description, properties, (), main=main, verb=True)


def _objects(module) -> tuple:
    """A verb's objects (its module's OBJECTS): their names, and one line each for the description."""
    return list(module.OBJECTS), "\n".join(f"    {k}: {v}" for k, v in module.OBJECTS.items())


def _what(module) -> dict:
    return {"type": "string", "enum": _objects(module)[0]}


def _with_objects(name: str, module):
    return lambda: _TEXTS[name] + "\n" + _objects(module)[1]


# --- the tools, in the order the brief lists them ---------------------------------------------------------------------

TOOLSET = Toolset((DESCRIBE, COMPARE, CHECK, CALCULATE, CLASSIFY, SUMMARIZE, CALIBRATE))

TOOLSET.add(
    # DESCRIBE: what the record holds
    Tool("stats", T.stats, DESCRIBE, _text("stats"),
         {"curves": {"type": "array", "items": {"type": "string"}, "description": "curve names, e.g. [\"PHIE\", \"SW\"]"},
          "zones": ZONES, "statistics": STATS, "where": WHERE},
         ("curves",), lead="curves"),
    Tool("profile", T.profile, DESCRIBE, _text("profile"),
         {"curve": {"type": "string", "description": "a curve, e.g. PHIE"}, "zones": ZONES, "statistics": STATS,
          "where": WHERE},
         ("curve",), main="curve", lead="curve"),
    Tool("runs", T.runs, DESCRIBE, _text("runs"),
         {"condition": {"type": "string", "description": CONDITION},
          "zones": ZONES,
          "limit": {"type": "integer", "description": "how many of the longest runs to list (20)"},
          "min_thickness": {"type": "number", "description": "only runs at least this thick"},
          "max_thickness": {"type": "number", "description": "only runs at most this thick (thin beds)"}},
         ("condition",), main="condition", lead="condition"),
    Tool("values_at", T.values_at, DESCRIBE, _text("values_at"),
         {"curves": CURVES,
          "depths": {"type": "array", "items": {"type": ["number", "string"]},
                     "description": "depths, e.g. [2900] or [\"9500 ft\"] (each nearest sample), or a range "
                                    "[\"2895-2905\"] (every sample in it)"}},
         ("curves", "depths"), lead="curves", stretch="whole_well"),     # the depths it is asked, wherever they lie
    Tool("section", T.section, DESCRIBE, _text("section"),
         {"key": {"type": "string", "description": "the section key exactly as the description lists it (family.section)"}},
         ("key",), main="key", lead="key", stretch="focus_only", focus_reason="the workflow's analyzer sections"),
    Tool("step", T.step, DESCRIBE, _text("step"),
         {"name": {"type": "string", "description": "the step name as the description lists it, e.g. saturation"}},
         ("name",), main="name", lead="name", stretch="whole_well"),     # the well's record of a step
    Tool("formation_summary", K.formation_summary, DESCRIBE, _text("formation_summary"),
         {"curves": CURVES, "statistics": STATS},
         (), lead="curves", table=True),

    # COMPARE AND GROUP
    Tool("compare", T.compare, COMPARE, _text("compare"),
         {"a": {"type": "string", "description": "a curve, e.g. PHIE"},
          "b": {"type": "string", "description": "a curve, e.g. PHIE_CC"},
          "zones": ZONES,
          "tolerance": {"type": "number", "description": "report the share of samples where |a - b| exceeds it"},
          "where": WHERE},
         ("a", "b"), main="a", lead="a", pair=("a", "b"), pair_word="vs"),
    # a least-squares line of one curve on another or on depth (relations, matrix lines, depth trends)
    Tool("crossplot", T.crossplot, COMPARE, _text("crossplot"),
         {"y": {"type": "string", "description": "the curve on the vertical axis, e.g. RHOB"},
          "x": {"type": "string", "description": "a curve, or DEPTH, e.g. NPHI"},
          "zones": ZONES, "log_y": {"type": "boolean", "description": "fit log10(y)"},
          "log_x": {"type": "boolean", "description": "fit against log10(x)"}, "where": WHERE},
         ("y", "x"), main="y", lead="y", pair=("y", "x"), pair_word="on"),
    Tool("overlap", T.overlap, COMPARE, _text("overlap"),
         {"a": {"type": "string", "description": "condition A: " + CONDITION},
          "b": {"type": "string", "description": "condition B, in the same grammar"},
          "zones": ZONES,
          "limit": {"type": "integer", "description": "how many runs of each set to list before cutting to the thickest (12)"}},
         ("a", "b"), main="a", pair=("a", "b")),
    Tool("lithology_stats", K.lithology_stats, COMPARE, _text("lithology_stats"),
         {"curves": CURVES, "statistics": {"type": "array", "items": {"type": "string"}}, "zones": ZONES},
         ("curves",), lead="curves", table=True),
    Tool("zone_contrast", K.zone_contrast, COMPARE, _text("zone_contrast"),
         {"curve": CURVE, "inputs": CURVES, "zones": ZONES},
         ("curve",), main="curve", lead="curve", table=True),
    Tool("curve_order", K.curve_order, COMPARE, _text("curve_order"),
         {"curves": CURVES, "relation": {"type": "string", "enum": ["decreasing", "increasing", "between"]},
          "zones": ZONES},
         ("curves",), lead="curves", table=True),
    Tool("vertical_sequence", K.vertical_sequence, COMPARE, _text("vertical_sequence"),
         {"curves": CURVES, "min_change": {"type": "number"}},
         (), lead="curves", table=True),

    # CHECK: data quality
    _verb("check", library_check.check, CHECK, _with_objects("check", library_check),
          lambda: {"what": _what(library_check),
                   "curves": {"type": "array", "items": {"type": "string"},
                              "description": "the curves to check (default: the object's own)"},
                   "zones": ZONES,
                   "threshold": {"type": "number", "description": "the object's limit, where it takes one"}},
          main="what"),
    Tool("spike_flags", K.spike_flags, CHECK, _text("spike_flags"),
         {"curves": CURVES, "k": {"type": "number"},
          "baseline": {"type": "string", "enum": ["zone", "zoned", "interval"]},
          "zones": ZONES,
          "scale": {"type": "string", "enum": ["linear", "log10"]},
          "window": {"type": "integer", "description": "rolling window in samples"}},
         ("curves",), lead="curves", table=True),
    Tool("adjacent_jumps", K.adjacent_jumps, CHECK, _text("adjacent_jumps"),
         {"curve": CURVE, "threshold": {"type": "number"}, "zones": ZONES},
         ("curve", "threshold"), main="curve", lead="curve", table=True),
    Tool("threshold_exceedance", K.threshold_exceedance, CHECK, _text("threshold_exceedance"),
         {"curve": CURVE, "threshold": {"type": "number"}, "op": {"type": "string", "enum": [">", ">=", "<", "<="]},
          "absolute": {"type": "boolean"}, "zones": ZONES},
         ("curve",), main="curve", lead="curve", table=True),
    Tool("data_record", K.data_record, CHECK, _text("data_record"),
         {"zones": ZONES},
         (), main="zones", table=True),
    # depth matching between logs by cross-correlation
    Tool("lag_correlation", K.lag_correlation, CHECK, _text("lag_correlation"),
         {"curves": CURVES,
          "max_lag": {"type": "number", "description": "search half-width in depth units (3 m when left out)"},
          "zones": ZONES},
         ("curves",), lead="curves", table=True),

    # CALCULATE: recompute with Petrophys
    _verb("calculate", P.calculate, CALCULATE, lambda: _TEXTS["calculate"] + "\n" + P.menu_text(),
          lambda: {"property": {"type": "string", "description": "the property, e.g. saturation"},
                   "method": {"type": "string", "description": "one of the methods the property lists, e.g. simandoux"},
                   "parameters": {"type": "object", "description": "parameter values, e.g. {\"rcl\": 4.0, \"m\": 2.2}"},
                   "label": {"type": "string", "description": "the new curves' suffix (default: the method), e.g. SIMANDOUX"},
                   "downstream": {"type": "boolean", "description": "also recompute the steps that read its outputs (true)"}},
          main="property"),
    _verb("what_if", P.what_if, CALCULATE, lambda: _TEXTS["what_if"],
          lambda: {"property": {"type": "string", "description": "the property whose input changes, e.g. net_pay"},
                   "parameter": {"type": "string", "description": "the input, e.g. sw_cutoff, m, rcl, or model / method"},
                   "values": {"type": "array", "items": {"type": ["number", "string"]},
                              "description": "the values to try (6 at most)"},
                   "target": {"type": "string", "description": "the curve to report, e.g. NET_PAY"},
                   "parameters": {"type": "object",
                                  "description": "inputs held fixed for every value, e.g. {\"rw_temp_f\": 105}"}},
          main="property"),
    _verb("estimate", P.estimate, CALCULATE,
          lambda: _TEXTS["estimate"] + "\n" + "\n".join(f"    {k}: {' | '.join(v)}" for k, v in P.ESTIMATES.items()),
          lambda: {"parameter": {"type": "string", "enum": list(P.ESTIMATES)},
                   "method": {"type": "string", "description": "one of the parameter's methods below (the first by default)"},
                   "zones": ZONES,
                   "rmf": {"type": "number", "description": "mud-filtrate resistivity, ohm.m (rw by sp; else the LAS header's)"},
                   "rmf_temp_f": {"type": "number", "description": "the temperature of rmf, degF"},
                   "bht_f": {"type": "number", "description": "bottom-hole temperature, degF (temperature; else the header's)"},
                   "td": {"type": "number", "description": "the depth of bht_f, in the well's depth unit"},
                   "vcl_max": {"type": "number", "description": "the clean samples' VCL limit (0.3)"},
                   "phie_min": {"type": "number", "description": "the porous samples' PHIE floor for rwa (0.05)"}},
          main="parameter"),

    # CLASSIFY
    _verb("classify", library_classify.classify, CLASSIFY, _with_objects("classify", library_classify),
          lambda: {"what": _what(library_classify), "method": {"type": "string"},
                   "curves": {"type": "array", "items": {"type": "string"}, "description": "the curves to classify on"},
                   "zones": ZONES, "k": {"type": "integer", "description": "the number of classes or units"}},
          main="what"),
    Tool("zone_classes", K.zone_classes, CLASSIFY, _text("zone_classes"),
         {"topic": {"type": "string",
                    "description": "a classification topic, e.g. hc_indicators, porosity_quality, flow_units"}},
         ("topic",), main="topic", lead="topic", table=True, stretch="focus_only",
         focus_reason="the workflow's analyzer classes, zone by zone"),
    Tool("unit_roles", K.unit_roles, CLASSIFY, _text("unit_roles"),
         {"zones": ZONES},
         (), main="zones", table=True),

    # SUMMARIZE
    _verb("summarize", library_summarize.summarize, SUMMARIZE, _with_objects("summarize", library_summarize),
          lambda: {"what": _what(library_summarize), "zones": ZONES,
                   "vcl_cutoff": {"type": "number"}, "phie_cutoff": {"type": "number"}, "sw_cutoff": {"type": "number"}},
          main="what"),
    Tool("pay_summary", K.pay_summary, SUMMARIZE, _text("pay_summary"), {}, (), table=True),

    # CALIBRATE: against core, elastic properties
    _verb("calibrate", library_calibrate.calibrate, CALIBRATE, _with_objects("calibrate", library_calibrate),
          lambda: {"what": _what(library_calibrate),
                   "curves": {"type": "array", "items": {"type": "string"}, "description": "the curves to use"},
                   "zones": ZONES},
          main="what"),
    Tool("core_vs_log", K.core_vs_log, CALIBRATE, _text("core_vs_log"),
         {"zones": ZONES},
         (), main="zones", table=True),
)

TOOLS = TOOLSET.functions()          # name -> the function that runs it
