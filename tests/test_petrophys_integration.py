"""petrophys computes, the harness orchestrates: every tool the model can call reaches the library, or is a generic
data operation or a reader of the workflow's record listed here with its reason.

A static call graph over the harness modules: a tool's own functions and the harness functions they call, followed to
the petrophys functions they import or the analyzers they run (evidence.zone_results / _ANALYZERS). The tools are the
catalog's computations and every tool of the toolset (agent/toolset.py: agent/tools.py, agent/compute.py; a compute
function that runs a catalog computation by name, _run(f, "name") or CATALOG["name"], reaches what that computation
reaches). The verbs (agent/library_api.py) run Petrophys's own registered functions. A new tool that computes
petrophysics in the harness fails here until its computation is in petrophys (or it is shown to be a generic data
operation and listed below).

    .venv/bin/python -m pytest tests/test_petrophys_integration.py -q
"""

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = {"catalog": "src/petroharness/record/catalog.py", "sections": "src/petroharness/record/sections.py",
           "card": "src/petroharness/record/card.py", "view": "src/petroharness/well/view.py", "stats": "src/petroharness/well/stats.py",
           "formation": "src/petroharness/well/formation.py", "prepare": "src/petroharness/well/prepare.py", "store": "src/petroharness/record/store.py",
           "summary": "src/petroharness/well/summary.py", "tools": "src/petroharness/agent/tools.py",
           "compute": "src/petroharness/agent/compute.py", "engine": "src/petroharness/agent/engine.py"}
# Reaching any of these runs a petrophys analyzer (imported by name at run time).
ANALYZER_ENTRIES = {("catalog", "zone_results"), ("catalog", "zone_classes_raw")}

# Generic data operations on curves and zone means: the operation itself is not petrophysics, and its statistics go
# through petrophys only.
GENERIC = {
    "correlation": "Pearson / rank correlation of two curves and their zone means",
    "adjacent_jumps": "changes between adjacent samples above a threshold",
    "zone_relation": "the per-zone order of curve means",
    "zone_contrast": "zone means grouped by the high and low zones of a curve",
    "threshold_exceedance": "samples beyond a threshold, per zone",
    "depth_trend": "linear trend of zone means with depth",
    "spike_flags": "samples beyond k standard deviations",
}

# Tools that render what the petrophys workflow recorded (its step record: what ran, with which inputs and
# decisions): library output read, not computed.
RECORD_READERS = {
    "provenance": "the workflow's step record for the topics asked",
    "step": "one step of the workflow's record: its method, inputs, the curves it wrote, equations and parameters",
}


def _graph():
    defs, calls, lib = {}, defaultdict(set), defaultdict(set)
    imported = defaultdict(dict)                       # module -> {local name: (module, name)} for harness imports
    aliases = defaultdict(dict)                        # module -> {local name: harness module} ("from ... import summary as S")
    for m, rel in MODULES.items():
        tree = ast.parse((ROOT / rel).read_text())
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                tail = node.module.split(".")[-1]
                for a in node.names:
                    if node.module.startswith("petrophys"):
                        imported[m][a.asname or a.name] = ("petrophys", f"{node.module}.{a.name}")
                    elif tail in MODULES:
                        imported[m][a.asname or a.name] = (tail, a.name)
                    elif a.name in MODULES:
                        aliases[m][a.asname or a.name] = a.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            key = (m, node.name)
            defs[key] = node
            local = {}
            for sub in ast.walk(node):
                if isinstance(sub, ast.ImportFrom) and sub.module and sub.module.startswith("petrophys"):
                    for a in sub.names:
                        local[a.asname or a.name] = f"{sub.module}.{a.name}"
            for sub in ast.walk(node):
                if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name) and sub.value.id == "CATALOG" \
                        and isinstance(sub.slice, ast.Constant) and isinstance(sub.slice.value, str):
                    calls[key].add(("catalog", sub.slice.value))         # CATALOG["name"](...): that computation
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "_run" \
                        and len(sub.args) > 1 and isinstance(sub.args[1], ast.Constant):
                    calls[key].add(("catalog", sub.args[1].value))       # compute._run(f, "name"): that computation
                if isinstance(sub, ast.Call):
                    f = sub.func
                    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                    base = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else None
                    for nm in (name, base):
                        if nm in local:
                            lib[key].add(local[nm])
                        elif nm in imported[m]:
                            target = imported[m][nm]
                            (lib[key].add(target[1]) if target[0] == "petrophys" else calls[key].add(target))
                    if base in aliases[m]:                     # a harness module by its alias: S.compute
                        calls[key].add((aliases[m][base], f.attr))
                    if isinstance(f, ast.Name):
                        calls[key].add((m, f.id))
                    elif isinstance(f, ast.Attribute):
                        calls[key].add((m, f.attr))
                        if base == "view":                     # FormationView methods
                            calls[key].add(("view", f.attr))
                if isinstance(sub, ast.Name) and sub.id == "_ANALYZERS":
                    lib[key].add("petrophys analyzers")
    return defs, calls, lib


def _reaches_petrophys(key, defs, calls, lib, seen=None) -> bool:
    seen = set() if seen is None else seen
    if key in seen or key not in defs:
        return False
    seen.add(key)
    if lib[key] or key in ANALYZER_ENTRIES:
        return True
    return any(_reaches_petrophys(c, defs, calls, lib, seen) for c in calls[key])


def test_every_tool_reaches_petrophys_or_is_a_listed_data_operation():
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from petroharness.agent.toolset import TOOLSET
    from petroharness.record.catalog import CATALOG
    defs, calls, lib = _graph()
    tools = [("catalog", name) for name in CATALOG]
    for tool in TOOLSET:
        module, name = tool.run.__module__, tool.run.__name__
        if module == "petroharness.agent.library_api":                 # a verb: Petrophys's registered functions
            continue
        assert module.split(".")[-1] in MODULES, f"{tool.name}: {module} is not in the graph (MODULES)"
        tools.append((module.split(".")[-1], name, tool.name))
    missing = [k[-1] for k in tools if k[-1] not in GENERIC and k[-1] not in RECORD_READERS
               and not _reaches_petrophys(k[:2], defs, calls, lib)]
    assert not missing, (f"{missing}: WHY: petrophys computes, the harness orchestrates. FIX: put the computation in "
                         "petrophys and call it, or list the tool in GENERIC with why it is a generic data operation.")
    stale = [t for t in {**GENERIC, **RECORD_READERS} if not any(k[-1] == t for k in tools)]
    assert not stale, f"{stale} are not tools any more: remove them from GENERIC / RECORD_READERS"


def test_the_graph_sees_library_calls():
    """The checker itself: tools known to call petrophys are found to, and a pure-numpy helper is not."""
    defs, calls, lib = _graph()
    for tool in ("pay_summary", "classify", "zone_classes", "unit_roles", "formation_summary", "vertical_sequence",
                 "curve_order", "zone_stats", "flag_intervals", "core_vs_log"):
        assert _reaches_petrophys(("catalog", tool), defs, calls, lib), tool
    assert not _reaches_petrophys(("formation", "segment_zones"), defs, calls, lib)
