"""The evidence graph of a conversation, rebuilt from its session log (log.jsonl and blobs/): no well, no Petrophys and
no model are needed to build it, and building it twice from the same log gives the same graph.

Nodes (id: kind):
    las             the LAS file (its path and SHA-256)
    curve:<NAME>    a curve: measured (from the LAS) or computed (by a step), with its unit
    step:<name>     a workflow step Petrophys ran: its method and its parameters
    Q<n>            question n
    E<k>            a result the investigation opened: the tool, its arguments, the SHA-256 of its text
    A<n>            the answer to question n: its status and the SHA-256 of its text
    C<n>.<k>        a settled claim of question n: its text and grade
    F<n>.<k>        a figure of answer n: its kind, file and caption

Links (kind: from -> to):
    from            a measured curve -> las
    computed_by     a computed curve -> the step that wrote it
    reads           a step -> a curve it read; a result -> a curve its call names
    opened          Q<n> -> a result opened while answering it
    answered_by     Q<n> -> A<n>
    states          A<n> -> a claim it settled
    cites           a claim -> a result it rests on
    shows           A<n> -> a result that shows a number the answer states (the link carries the numbers)
    carries         A<n> -> a figure
    draws           a figure -> the result it plots

    g = EvidenceGraph.from_log("my-session")
    g.trail(2)             # everything answer 2 rests on, back to the LAS file
    g.to_json()            # the whole graph, in a fixed order
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from petroharness.evidence import record as R


@dataclass
class EvidenceGraph:
    nodes: dict = field(default_factory=dict)          # id -> {"kind": ..., ...}
    links: list = field(default_factory=list)          # {"kind", "from", "to", ...}

    # --- building -------------------------------------------------------------------------------------------------

    def node(self, nid: str, kind: str, **data) -> str:
        self.nodes.setdefault(nid, {"kind": kind}).update({k: v for k, v in data.items() if v is not None})
        return nid

    def link(self, kind: str, src: str, dst: str, **data) -> None:
        if src in self.nodes and dst in self.nodes and not any(
                x["kind"] == kind and x["from"] == src and x["to"] == dst for x in self.links):
            self.links.append({"kind": kind, "from": src, "to": dst, **data})

    def _record(self, snap: dict) -> None:
        """The computation graph: curves, steps and what read what. A later snapshot of the same conversation adds
        the curves computed on request since."""
        for step in snap["steps"]:
            self.node(f"step:{step['step']}", "step", method=step["method"], parameters=step["parameters"])
        owner = R.step_of(snap)
        for name, cv in snap["curves"].items():
            step = owner.get(name, "")
            self.node(f"curve:{name}", "curve", unit=cv["unit"], source=cv["source"])
            if step:
                self.node(f"step:{step}", "step")           # a curve computed on request: its label is its step
                self.link("computed_by", f"curve:{name}", f"step:{step}")
            elif cv["source"] == "input" and "las" in self.nodes:
                self.link("from", f"curve:{name}", "las")
        for step in snap["steps"]:
            for name in R.NAME.findall(" ".join(step["inputs"])):
                self.link("reads", f"step:{step['step']}", f"curve:{name}")
            for name in step["outputs"]:                    # an output the interval holds no samples of
                if f"curve:{name}" not in self.nodes:
                    self.node(f"curve:{name}", "curve", source="computed")
                    self.link("computed_by", f"curve:{name}", f"step:{step['step']}")

    @classmethod
    def from_log(cls, folder) -> EvidenceGraph:
        """The graph of the conversation in `folder`, from its log and blobs alone."""
        folder = Path(folder)
        events = [json.loads(line) for line in (folder / "log.jsonl").read_text().splitlines() if line.strip()]
        blob = lambda sha: (folder / "blobs" / sha).read_text()
        g, figures = cls(), {}
        for e in events:                                    # the file and the record first: results link to curves
            if e["type"] == "session_start":
                if e.get("las"):
                    g.node("las", "las", path=e.get("las"), sha256=e.get("las_sha256"))
                g.nodes.setdefault("session", {"kind": "session"}).update(
                    {k: e[k] for k in ("mode", "interval", "model", "petrophys", "harness") if e.get(k) is not None})
            elif e["type"] == "record":
                g._record(json.loads(blob(e["sha256"])))
            elif e["type"] == "setup":                      # what the answers were made with; the last one stands,
                s = g.nodes.setdefault("session", {"kind": "session"})      # earlier ones are kept by their hashes
                s["setups"] = s.get("setups", []) + [e["hash"]]
                s["setup"] = e["hash"]
        for e in events:
            kind, n = e["type"], e.get("turn", 0)
            if kind == "question":
                g.node(f"Q{n}", "question", text=e.get("text"))
            elif kind == "result":
                g.node(e["id"], "result", tool=e.get("tool"), args=e.get("args"), sha256=e.get("sha256"),
                       chars=e.get("chars"), question=n)
                g.link("opened", f"Q{n}", e["id"])
                for name in R.names(json.dumps(e.get("args") or {})):
                    g.link("reads", e["id"], f"curve:{name}")
            elif kind == "figure":
                k = figures[n] = figures.get(n, 0) + 1
                g.node(f"F{n}.{k}", "figure", figure=e.get("kind"), file=e.get("file"), caption=e.get("caption"),
                       source=e.get("source"), question=n)
            elif kind == "turn_end":
                a = g.node(f"A{n}", "answer", status=e.get("status"), sha256=e.get("answer_sha256"),
                           opening=e.get("opening"), question=n)
                g.link("answered_by", f"Q{n}", a)
                for k, c in enumerate(e.get("claims") or [], 1):
                    cid = g.node(f"C{n}.{k}", "claim", text=c.get("text"), grade=c.get("grade"), point=c.get("point"),
                                 question=n)
                    g.link("states", a, cid)
                    for eid in c.get("ev") or []:
                        g.link("cites", cid, eid)
                by_result: dict = {}
                for number, ids in (e.get("shows") or {}).items():
                    for eid in ids:
                        by_result.setdefault(eid, []).append(number)
                for eid, numbers in by_result.items():
                    g.link("shows", a, eid, numbers=numbers)
                for k in range(1, figures.get(n, 0) + 1):
                    fid = f"F{n}.{k}"
                    g.link("carries", a, fid)
                    g.link("draws", fid, str(g.nodes[fid].get("source") or ""))
        return g

    # --- reading ---------------------------------------------------------------------------------------------------

    def out(self, nid: str, kind: str | None = None) -> list:
        return [x["to"] for x in self.links if x["from"] == nid and (kind is None or x["kind"] == kind)]

    def into(self, nid: str, kind: str | None = None) -> list:
        return [x["from"] for x in self.links if x["to"] == nid and (kind is None or x["kind"] == kind)]

    def questions(self) -> list:
        return sorted(int(k[1:]) for k, v in self.nodes.items() if v["kind"] == "question")

    def upstream(self, curves: list) -> tuple:
        """(curves, steps) the given curves rest on, however far back: each curve's step, what that step read, and
        so on to the measured logs."""
        seen_c, seen_s, todo = [], [], list(curves)
        while todo:
            c = todo.pop(0)
            if c in seen_c or c not in self.nodes:
                continue
            seen_c.append(c)
            for s in self.out(c, "computed_by"):
                if s not in seen_s:
                    seen_s.append(s)
                    todo += self.out(s, "reads")
        return seen_c, seen_s

    def trail(self, n: int) -> dict:
        """Everything answer n rests on: its claims with the results they cite, the numbers it states with the results
        that show them, those results with the curves their calls name, the steps behind those curves with their
        parameters, the measured logs they start from, and the LAS file."""
        a = f"A{n}"
        if a not in self.nodes:
            raise KeyError(f"WHAT: question {n} has no answer in this conversation. FIX: one of {self.questions()}.")
        claims = [{"id": c, **{k: self.nodes[c].get(k) for k in ("text", "grade")}, "results": self.out(c, "cites")}
                  for c in self.out(a, "states")]
        numbers: dict = {}
        for x in self.links:
            if x["kind"] == "shows" and x["from"] == a:
                for number in x["numbers"]:
                    numbers.setdefault(number, []).append(x["to"])
        ids = list(dict.fromkeys([e for c in claims for e in c["results"]] + [e for v in numbers.values() for e in v]))
        ids = [e for e in ids if e in self.nodes]
        results = [{"id": e, **{k: self.nodes[e].get(k) for k in ("tool", "args", "sha256", "question")},
                    "curves": [c.split(":", 1)[1] for c in self.out(e, "reads")]} for e in ids]
        named = list(dict.fromkeys(f"curve:{c}" for r in results for c in r["curves"]))
        curves, steps = self.upstream(named)
        return {"question": {"n": n, "text": self.nodes.get(f"Q{n}", {}).get("text")},
                "answer": {k: self.nodes[a].get(k) for k in ("status", "sha256", "opening")},
                "claims": claims, "numbers": numbers, "results": results,
                "curves": [{"name": c.split(":", 1)[1], "unit": self.nodes[c].get("unit"),
                            "source": self.nodes[c].get("source"),
                            "step": next((s.split(":", 1)[1] for s in self.out(c, "computed_by")), None),
                            "named": c in named} for c in curves],
                "steps": [{"step": s.split(":", 1)[1], "method": self.nodes[s].get("method"),
                           "parameters": self.nodes[s].get("parameters") or {},
                           "reads": [c.split(":", 1)[1] for c in self.out(s, "reads")]} for s in steps],
                "figures": [{k: self.nodes[f].get(k) for k in ("figure", "file", "caption", "source")}
                            for f in self.out(a, "carries")],
                "las": self.nodes.get("las"), "session": self.nodes.get("session")}

    def to_json(self) -> dict:
        """The graph in a fixed order (nodes by id, links by kind, from, to): equal for equal logs."""
        return {"nodes": {k: self.nodes[k] for k in sorted(self.nodes)},
                "links": sorted(self.links, key=lambda x: (x["kind"], x["from"], x["to"]))}
