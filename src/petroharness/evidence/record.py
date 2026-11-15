"""The computation graph as the well's record holds it: each curve with where it comes from, each workflow step with
its method, what it read, what it wrote and its parameters. Petrophys ran the steps; this reads their record
(petroharness.agent.inventory) into plain data, so it can be kept in a session log and walked without the well.

    snapshot(inventory) -> {"curves": {name: {source, unit, step}}, "steps": [{step, method, inputs, outputs,
                            parameters}]}
    behind(snapshot, names) -> the steps that computed the named curves and the steps those read from
"""
from __future__ import annotations

import re

NAME = re.compile(r"\b[A-Z][A-Z0-9_]+\b")
_SKIP = ("_note", "_notes", "_source_file", "_path")       # record entries that are not parameters
MAX_PARAMETERS = 24                                         # shown per step
NAMED, UPSTREAM = "named", "upstream"
ON_REQUEST = "computed on request in this conversation"


def parameters(recorded: dict, cap: int = MAX_PARAMETERS) -> dict:
    """A step's parameters as a reader uses them: the scalar entries of its record (numbers, text, yes/no), as recorded.
    Tables and lists stay in the record (the step tool shows them)."""
    out = {}
    for k, v in (recorded or {}).items():
        if str(k).endswith(_SKIP) or v is None or isinstance(v, (dict, list, tuple, set)):
            continue
        if isinstance(v, str) and (not v.strip() or len(v) > 80):
            continue
        out[str(k)] = v if isinstance(v, (bool, int, float, str)) else str(v)
        if len(out) >= cap:
            break
    return out


def snapshot(inv) -> dict:
    """The record as plain data (JSON-ready, in the workflow's order)."""
    curves = {str(name): {"source": str(cv.source), "unit": str(getattr(cv, "unit", "") or ""),
                          "step": str(cv.step) if cv.source == "computed" and cv.step else ""}
              for name, cv in inv.curves.items()}
    steps = [{"step": str(m.step), "method": str(m.method or ""), "inputs": [str(i) for i in (m.inputs or [])],
              "outputs": [str(o) for o in (m.outputs or [])], "parameters": parameters(m.parameters)}
             for m in inv.methods]
    return {"curves": curves, "steps": steps}


def step_of(snap: dict) -> dict:
    """Curve name -> the step that computed it: the curve's own record first, then the step whose outputs name it (a
    curve the interval holds no samples of is still a step's output)."""
    out = {}
    for m in snap["steps"]:
        for o in m["outputs"]:
            out.setdefault(o, m["step"])
    for name, cv in snap["curves"].items():
        if cv["step"]:
            out[name] = cv["step"]
    return out


def names(text: str) -> list:
    """The curve-like names a text holds, in order, each once."""
    return list(dict.fromkeys(NAME.findall(text or "")))


def behind(snap: dict, named: list) -> list:
    """The steps behind the named curves, in the workflow's order -> [{step, method, curves, inputs, parameters,
    why}]. `named`: a step that computed one of the curves. `upstream`: a step one of those reads from, however far
    back. A curve computed on request during the conversation comes last, by the label it was computed under."""
    methods = {m["step"]: m for m in snap["steps"]}
    owner = step_of(snap)
    curves: dict = {}                                       # step -> the named curves it computed
    for c in dict.fromkeys(named):
        if c in owner:
            curves.setdefault(owner[c], []).append(c)
    why = {step: NAMED for step in curves}
    todo = list(curves)
    while todo:                                             # the steps the named ones read from
        m = methods.get(todo.pop())
        for name in NAME.findall(" ".join(m["inputs"])) if m is not None else []:
            step = owner.get(name)
            if step and step not in why:
                why[step] = UPSTREAM
                todo.append(step)
    order = {m["step"]: i for i, m in enumerate(snap["steps"])}
    out = []
    for step in sorted(why, key=lambda k: (k not in order, order.get(k, 0), k)):
        m = methods.get(step)
        out.append({"step": step, "method": m["method"] if m is not None else ON_REQUEST,
                    "curves": curves.get(step) or (m["outputs"][:6] if m is not None else []),
                    "inputs": list(m["inputs"]) if m is not None else [],
                    "parameters": dict(m["parameters"]) if m is not None else {}, "why": why[step]})
    return out
