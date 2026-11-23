"""The one scripted model of the tests: it replies by stage and keeps every call it gets.

    llm = ScriptedModel({"read*": {"topics": ["porosity"], "named": ["PHIE"]},
                         "step_1": FIRST,                # exactly this stage
                         "step_*": DONE, "settle*": DONE},  # every stage starting so
                        default="## Porosity\nRead zone by zone.\n")   # the writer and every other stage
"""
from __future__ import annotations

import json

DONE = {"edits": [], "next": [], "done": True}


class ScriptedModel:
    """A model whose reply depends on the call's stage.

    `replies` maps stages to replies. A key names one stage ("step_1"), or ends in "*" and names every stage starting
    with what comes before it ("step_*"; "*" alone names every stage). The stage's own key answers, else the longest
    "*" key it starts with, else `default`. A reply is a text; an object, sent as JSON; a list, whose items answer the
    calls in turn and `then` every call after; or a function of the call's messages giving either.

    Every call is kept in `sent` (stage, messages as sent, schema, max_tokens, retry), and logged in the usage like a
    real client's call. A subclass overrides `reply` to answer from more than the stage."""

    def __init__(self, replies: dict | None = None, default=DONE, then=DONE):
        self.replies = {k: list(v) if isinstance(v, list) else v for k, v in (replies or {}).items()}
        self.default, self.then, self.sent = default, then, []

    def replays_reasoning(self) -> bool:
        return True

    def rule(self, stage: str):
        """The key that answers a stage (None: the default)."""
        if stage in self.replies:
            return stage
        keys = [k for k in self.replies if k.endswith("*") and stage.startswith(k[:-1])]
        return max(keys, key=len) if keys else None

    def reply(self, stage: str, messages: list):
        key = self.rule(stage)
        r = self.default if key is None else self.replies[key]
        if isinstance(r, list):
            r = r.pop(0) if r else self.then
        return r(messages) if callable(r) else r

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False) -> str:
        self.sent.append({"stage": stage, "messages": json.loads(json.dumps(messages)), "schema": json_schema,
                          "max_tokens": max_tokens, "retry": retry})
        if usage is not None:                          # a test may pass none
            usage.log.append({"stage": stage, "prompt_tokens": sum(len(m.get("content") or "") for m in messages) // 4,
                              "completion_tokens": 5, "seconds": 0.0})
        r = self.reply(stage, messages)
        return r if isinstance(r, str) else json.dumps(r)

    # --- reading what was sent

    def stages(self) -> list:
        return [c["stage"] for c in self.sent]

    def calls(self, stage: str) -> list:
        """The calls whose stage starts with `stage`."""
        return [c for c in self.sent if c["stage"].startswith(stage)]

    def first(self, stage: str) -> list:
        """The message texts of the stage's first call."""
        return [m["content"] for m in next(c["messages"] for c in self.sent if c["stage"] == stage)]

    def prompt(self, stage: str) -> str:
        """The last message of the stage's first call: the prompt the step was given."""
        return self.first(stage)[-1]

    def last(self, stage: str) -> str:
        """The last message of the stage's latest call."""
        return next(c for c in reversed(self.sent) if c["stage"] == stage)["messages"][-1]["content"]


def in_turn(replies: list, then=DONE) -> ScriptedModel:
    """A model answering every call with the next of `replies`, whatever its stage, then `then`."""
    return ScriptedModel({"*": replies}, then=then)


def newest_result(messages: list) -> str:
    """The newest result id a call was shown ([E7] -> 'E7'; 'E1' when none)."""
    import re
    ids = re.findall(r"\[(E\d+)\]", messages[-1]["content"])
    return max(ids, key=lambda x: int(x[1:])) if ids else "E1"
