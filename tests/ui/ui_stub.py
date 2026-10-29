"""A stand-in for K2-Horizon-7B in the UI tests, replying by stage: the READ call's topics; step 1 opening results
of several tools and reading a guide (which opens sections); step 2 citing the first look and saying done; the settle
step with no edits; a writer draft holding a number no result shows (so the checker asks for one repair round); the
repair. Every call is recorded."""

import json
import threading

READ = {"topics": ["porosity", "shale_clay"], "named": ["PHIE"]}
STEP1 = {"asks": "How porous is the interval, and how much shale does it hold?",
         "points": ["How does porosity vary by zone?"], "intent": "characterize", "focus": "porosity and shale by zone",
         "edits": [{"op": "add", "point": 1, "text": "Porosity varies by zone", "grade": "hypothesis"}],
         "next": [{"stats": {"curves": ["PHIE", "VCL"]}}, {"profile": {"curve": "PHIE"}}, {"runs": "NET_PAY"},
                  {"compare": {"a": "PHIE", "b": "VCL"}}, {"guide": "porosity"}], "done": False}
STEP2 = {"focus": "settle point 1",
         "edits": [{"op": "revise", "id": "C1", "ev": ["E1"], "grade": "moderate",
                    "means": "the zones differ in porosity"}],
         "next": [], "done": True}
DONE = {"edits": [], "next": [], "done": True}
DRAFT = "## Porosity\nPorosity is 0.987654 in every zone.\n\n{{ZONE_TABLE}}"
REPAIRED = "## Porosity\nPorosity is read zone by zone in the table.\n\n{{ZONE_TABLE}}"


class StubModel:
    """Replies by stage; `gate` (a threading.Event) holds every call until it is set."""

    def __init__(self, cfg=None, gate=None, log=None):
        self.cfg = cfg
        self.gate = gate
        self.sent = log if log is not None else []
        self._lock = threading.Lock()

    def replays_reasoning(self):
        return True

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
        if self.gate is not None:
            self.gate.wait(60)
        with self._lock:
            self.sent.append({"stage": stage, "messages": json.loads(json.dumps(messages)), "max_tokens": max_tokens,
                              "schema": json_schema, "retry": retry})
        usage.log.append({"stage": stage, "prompt_tokens": sum(len(m["content"] or "") for m in messages) // 4,
                          "completion_tokens": 12, "seconds": 0.0})
        if stage.startswith("read"):
            r = READ
        elif stage == "step_1":
            r = STEP1
        elif stage == "step_2":
            r = STEP2
        elif stage.startswith(("step_", "settle")):
            r = DONE
        elif stage.startswith("writer"):
            r = DRAFT
        else:
            r = REPAIRED
        return r if isinstance(r, str) else json.dumps(r)
