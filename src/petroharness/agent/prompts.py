"""The brief and step 1's prompt: the tools the model is shown and how a step is asked."""

from __future__ import annotations

from petroharness.agent.replies import VERBS
from petroharness.agent.state import ACTIONS

from petroharness.agent import direction, vocabulary
from petroharness.agent.engine import Formation
from petroharness.agent.schemas import named
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)


def _tool_line(t: dict) -> str:
    fn = t["function"]
    args = ", ".join(f'"{k}": ...' for k in fn["parameters"]["properties"])
    return f'  {{"{fn["name"]}": {{{args}}}}}   {fn["description"]}'


def tools_text(reach: str = "focus") -> str:
    """The tools as the brief lists them, from the tool schemas (src/petroharness/agent/schemas.py), grouped by verb
    under the line that says where Petrophys's functions are."""
    by = {t["function"]["name"]: t for t in named()}
    out = [C.text("C4", "library")]
    for head, names in VERBS:                                # every tool has its group (tools.spec.Toolset.add)
        out.append(f"  {head}")
        out += [_tool_line(by[n]) for n in names]
    # the zone selector the engine reads
    out.append('  zones (any lookup that takes them): zone ids ["Z2", "Z3"], a lithology ["SILT"] for its zones, '
               'or ["ALL"]; left out, every zone')
    if reach == "well":                                      # anywhere in the well (docs/ARCHITECTURE.md)
        out[-1] = ('  zones (any lookup that takes them): zone ids ["Z2", "Z3"], a lithology ["SILT"] for its zones, '
                   'or ["ALL"]; anywhere in the well, a depth range ["2870-2890"] or a unit of the tops file by its name '
                   '["<unit name>"], the call computing on that stretch with rows of its own; several, one row each; '
                   'left out, every zone. A verb\'s run also takes "where": only the samples where a condition holds '
                   '(e.g. the water leg, "SW > 0.95"). runs lists every interval unless given a limit')
    return "\n".join(out)


_PLUGGED = object()            # brief() and step1() given no library: the plugged one (direction.plugged())


def _library(library):
    return direction.plugged() if library is _PLUGGED else library


def _reach(s) -> str:
    """The session's reach (data.reach, on its view): what a tool's zones may name."""
    return getattr(getattr(getattr(s, "f", None), "view", None), "reach", "focus")


def brief(library=_PLUGGED, reach: str = "focus") -> str:
    """The system prompt of the READ call, a step and the settle step. With a skill library it names DIRECTION and the
    guide action (C1's guide fragments); with none (None), neither."""
    on = _library(library) is not None
    text = C.prompt("C1", "brief", direction=C.text("C1", "brief_direction") if on else "",
                  guide_action=C.text("C1", "brief_guide") if on else "")
    text = text.rstrip() + "\n\n" + BRIEF_WEAKNESSES + "\n"
    text = text.rstrip() + "\n\n" + BRIEF_LEVELS + "\n"
    return text.replace("{TOOLS}", tools_text(reach)).replace("{ACTIONS}", str(ACTIONS))


# what turns a weakness into a verdict (e.g. "flow units not distinct" after opening three FZI classes; "clay is
# not a control" from one pooled crossplot)
BRIEF_WEAKNESSES = C.text("C10", "brief_weaknesses")


# the reservoir properties every answer's formation overview reads (clay, effective porosity, water
# saturation, permeability), added to any first look
CORE_CURVES = ("VCL", "PHIE", "SW", "PERM")


CORE_LOOK_CAP = 14


# the mineral volumes a workflow computes (the composition, when the model chose this topic)
MINERAL_VOLUMES = ("VCL", "VQUAR", "VCALC", "VDOLO", "VANHY", "VSAND", "VSILT", "VSHALE", "VCOAL")


MINERAL_TOPIC = "lithology_mineralogy"


def named_curves(f: Formation, named) -> list:
    """The curves with data here that the READ call's named measurements stand for, in their order (the catalog's
    vocabulary: src/petroharness/agent/vocabulary.py resolve)."""
    have = {c.upper(): c for c in f.inv.curves}
    out = []
    for item in named or []:
        out += [have[c.upper()] for c in vocabulary.resolve(item, f.view.reg.curves, have.values())
                if c.upper() in have and f.view.available(have[c.upper()])]
    return list(dict.fromkeys(out))


# levels as well as rankings
BRIEF_LEVELS = C.text("C10", "brief_levels")


STEP1 = C.text("C5", "step1")


EXAMPLE_TOPIC = "net_reservoir_pay"      # step 1's example is a question on pay: its guide call names the library's guide


#   on that topic area (else the library's first guide)


def step1(library=_PLUGGED) -> str:
    """Step 1's instructions. With a skill library, the guide sentence and the example's guide call (C5's guide
    fragments); with none (None), neither."""
    lib = _library(library)
    if lib is None:
        text = C.fill_text(STEP1, guide_sentence="", guide_call="")
    else:
        g = (lib.on(EXAMPLE_TOPIC) or list(lib.facets))[0]
        text = C.fill_text(STEP1, guide_sentence=C.text("C5", "step1_guides"),
                           guide_call=C.fill("C5", "step1_guide_call", guide=g))
    return text.replace("{ACTIONS}", str(ACTIONS))


# the points stay within the question: unasked step-1 points take steps and become answer sections
POINTS_SCOPE = C.text("C5", "points_scope")
