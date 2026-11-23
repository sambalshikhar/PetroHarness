"""The question graph (docs/GRAPH.md, "The question graph"): the graph's shape against the blueprint, and hosted
tracing refused.

    .venv/bin/python -m pytest tests/agent/test_graph_flow.py -q
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]


def test_graph_matches_the_blueprint():
    """Every node of the question graph is in the node table of docs/GRAPH.md's question graph section, and every route
    the code has is in its route table (from, to)."""
    from petroharness.agent.graph import GRAPH
    doc = (ROOT / "docs" / "GRAPH.md").read_text().split("\n## The question graph\n", 1)[1].split("\n## ", 1)[0]
    g = GRAPH.get_graph()
    nodes = {n for n in g.nodes if not n.startswith("__")}
    table = set(re.findall(r"^\| `(\w+)` \| (?:code|model)", doc, re.M))
    assert nodes == table, (nodes - table, table - nodes)
    routes = {(m.group(1), t) for m in re.finditer(r"^\| `(\w+)` \| [^|]+\| (.+?) \|$", doc, re.M)
              for t in re.findall(r"`(\w+)`", m.group(2))}
    edges = {(e.source, e.target) for e in g.edges if not e.source.startswith("__") and not e.target.startswith("__")}
    missing = {e for e in edges if e not in routes}
    assert not missing, f"routes in the code but not in docs/GRAPH.md: {sorted(missing)}"
    assert (ROOT / "docs" / "graph.mmd").read_text() == g.draw_mermaid(), "docs/graph.mmd: redraw it from the code"
    from petroharness.agent.graph import State
    section = doc.split("**State**", 1)[1].split("## Nodes", 1)[0]
    documented = {n for row in re.findall(r"^\| ([^|]+) \|", section, re.M) for n in re.findall(r"`(\w+)`", row)}
    assert documented == set(State.__annotations__), (documented ^ set(State.__annotations__))


def test_hosted_tracing_refused(monkeypatch):
    from petroharness.agent.graph import no_hosted_tracing
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with pytest.raises(RuntimeError, match="hosted tracing is switched on"):
        no_hosted_tracing()
