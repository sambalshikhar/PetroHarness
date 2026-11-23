"""The session graph and the later-question graph (docs/GRAPH.md): each graph's shape against its blueprint,
and the routes on a conversation run with a stand-in model.

    .venv/bin/python -m pytest tests/session/test_session_graph.py -q
"""
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tests" / "agent")]

DOC = (ROOT / "docs" / "GRAPH.md").read_text()


def _shape(graph):
    g = graph.get_graph()
    nodes = {n for n in g.nodes if not n.startswith("__")}
    edges = {(e.source, e.target) for e in g.edges if not e.source.startswith("__") and not e.target.startswith("__")}
    return g, nodes, edges


def _section(title: str) -> str:
    return DOC.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0]


def _routes(text: str) -> set:
    return {(m.group(1), t) for m in re.finditer(r"^\| `(\w+)` \| [^|]+\| (.+?) \|$", text, re.M)
            for t in re.findall(r"`(\w+)`", m.group(2))}


def test_the_session_graph_matches_its_blueprint():
    from petroharness.session.graph import SESSION, State
    g, nodes, edges = _shape(SESSION)
    text = _section("The session graph")
    assert nodes == set(re.findall(r"^\| `(\w+)` \| (?:code|model|graph) \|", text, re.M))
    assert edges <= _routes(text), sorted(edges - _routes(text))
    assert (ROOT / "docs" / "graph_session.mmd").read_text() == g.draw_mermaid(), "docs/graph_session.mmd: redraw it"
    state = text.split("**State**", 1)[1].split("### Nodes", 1)[0]
    assert set(re.findall(r"`(\w+)`", state)) == set(State.__annotations__)


def test_the_later_question_graph_is_the_question_graph_without_build_plus_the_reply_route():
    from petroharness.agent.graph import GRAPH, LATER
    g, nodes, edges = _shape(LATER)
    _, qnodes, qedges = _shape(GRAPH)
    text = _section("The later-question graph")
    assert nodes == qnodes - {"build"}                            # the same nodes, the well not built again
    kept = {e for e in qedges if "build" not in e}
    assert kept <= edges and edges - kept <= _routes(text), sorted(edges - kept - _routes(text))
    assert edges - kept == {("settle", "write_brief")}            # the one more route: the short form after settling
    assert (ROOT / "docs" / "graph_later.mmd").read_text() == g.draw_mermaid(), "docs/graph_later.mmd: redraw it"


def test_the_routes_decide_as_the_blueprint_says():
    from petroharness.agent import graph as Q
    from petroharness.session import graph as S
    ctx = lambda **kw: NS(context=NS(conversation=NS(**kw)))
    ok, bad, empty = ({"got": {"answer": a, "status": s}} for a, s in (("text", "ok"), ("", "error: X"), ("  ", "ok")))
    assert S.after_turn(ok, ctx(live=object())) == "project"
    assert S.after_turn(bad, ctx(live=object())) == S.after_turn(empty, ctx(live=object())) == "commit"
    assert S.after_turn(ok, ctx(live=None)) == "commit"
    assert S.after_project({}, ctx(figures=True)) == "figures" and S.after_project({}, ctx(figures=False)) == "commit"
    run = lambda reply, depth="investigate": NS(context=NS(session=NS(reply=reply, depth=depth, claims=object(),
                                                                       ledger=NS(items=[1]))))
    assert Q.reply_form({}, run("brief")) == "write_brief" and Q.reply_form({}, run("full")) == "write"
    assert Q.after_close_later({}, run("brief")) == "settle"                      # settle first, where results were opened
    nothing = NS(context=NS(session=NS(reply="brief", depth="investigate", claims=object(), ledger=NS(items=[]))))
    assert Q.after_close_later({}, nothing) == "write_brief" and Q.after_close({}, nothing) == "write"
    none = NS(context=NS(session=NS(reply="brief", depth="direct", claims=None, ledger=NS(items=[]))))
    assert Q.after_close_later({}, none) == "no_answer"
    # a direct question: look steps, then the short writer with no settle call (both graphs)
    direct = run("full", "direct")
    assert Q.after_first_look({}, direct) == "look" and Q.after_first_look({}, run("full")) == "ask"
    assert Q.after_look({"finished": False}, direct) == "look" and Q.after_look({"finished": True}, direct) == "close"
    assert Q.after_look({"finished": False}, run("full")) == "ask"                # sent to an investigation after all
    assert Q.after_close({}, direct) == Q.after_close_later({}, direct) == "write_brief"
