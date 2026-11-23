"""A stand-in for K2-Horizon-7B in the UI tests, replying by stage: the READ call's topics; step 1 opening results
of several tools and reading a guide (which opens sections); step 2 citing the first look and saying done; the settle
step with no edits; a writer draft holding a number no result shows (so the checker asks for one repair round); the
repair. Every call is recorded."""

import threading

from _support.model import DONE, ScriptedModel

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
DRAFT = "## Porosity\nPorosity is 0.987654 in every zone.\n\n{{ZONE_TABLE}}"
REPAIRED = "## Porosity\nPorosity is read zone by zone in the table.\n\n{{ZONE_TABLE}}"


class StubModel(ScriptedModel):
    """Replies by stage; `gate` (a threading.Event) holds every call until it is set; `log` collects the calls of
    every model a test makes."""

    def __init__(self, cfg=None, gate=None, log=None):
        super().__init__({"read*": READ, "step_1": STEP1, "step_2": STEP2, "step_*": DONE, "settle*": DONE,
                          "writer*": DRAFT}, default=REPAIRED)
        self.cfg, self.gate = cfg, gate
        if log is not None:
            self.sent = log
        self._lock = threading.Lock()

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
        if self.gate is not None:
            self.gate.wait(60)
        with self._lock:
            return super().chat(stage, messages, usage, max_tokens, json_schema, temperature, retry)
