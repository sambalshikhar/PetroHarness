"""The engine's base: a formation in a question (Formation), a result (Result), a refusal (ToolError), the size limit
and the messages Petrophys gives."""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, field
import numpy as np
from petroharness.agent.inventory import Inventory
from petroharness.well import summary as S


STATISTICS = S.STATISTICS          # every statistic the summary layer computes (and any percentile pNN)


WIDE_CHARS = 9000                  # room for every zone row (6,000 cut zone rows, even in the first


                                   #   look; the model spent steps re-fetching them and wrote "truncated" limitations)


MESSAGES_SHOWN = 8


# the inputs Petrophys's messages ask for during one tool call (petrophys Advice), for the call door's advice; one list
# per call (schemas.call sets it), safe across the questions run side by side
ADVISED: ContextVar = ContextVar("petrophys_advised", default=None)


def advised(message) -> None:
    """Note the inputs a Petrophys message asks for, as data (petrophys._internal.advice: a message, an exception or a
    warning carrying an Advice), for the call that is running."""
    got = ADVISED.get()
    if got is None:
        return
    from petrophys._internal.advice import inputs_of
    seen, m = set(), message
    while m is not None and id(m) not in seen:  # an exception's chain too (a refusal raised from Petrophys's error)
        seen.add(id(m))
        got.extend(i for i in inputs_of(m) if i not in got)
        m = getattr(m, "__context__", None) or getattr(m, "__cause__", None)


def skipped_said(skipped: dict) -> list:
    """A Petrophys run's skipped steps as messages ("step: reason"), each keeping the inputs its reason asks for."""
    from petrophys._internal.advice import restated
    return [restated(f"{k}: {v}", v) for k, v in (skipped or {}).items()]


def said_whole(messages, limit: int = MESSAGES_SHOWN) -> list:
    """What Petrophys said (its warnings, errors and skipped steps) as a result shows it: each message whole (a fix it
    names is never cut off), once, in the order said; past `limit` messages, how many more there were. The inputs a
    message asks for are noted for the call (advised)."""
    out = []
    for m in messages:
        advised(m)
        t = re.sub(r"\s+", " ", str(m)).strip()
        if t and t not in out:
            out.append(t)
    return out[:limit] + ([f"and {len(out) - limit} more"] if len(out) > limit else [])


def max_chars() -> int:
    return WIDE_CHARS


class ToolError(ValueError):
    pass


@dataclass
class Formation:
    inv: Inventory
    view: object                      # petroharness.well.view.FormationView
    store: object = None              # petroharness.record.sections.Store: the analyzer sections with every class run

    @property
    def depth(self) -> np.ndarray:
        return np.asarray(self.view.depth, dtype=float)              # the interval's samples, in the reporting unit


@dataclass
class Result:
    text: str                                         # what the model is shown: within the size limit, and when rows
    #   were cut from it, a last line naming them with the find that fetches them
    numbers: list = field(default_factory=list)       # every number of the result
    rows: list = field(default_factory=list)          # every (line, the numbers written into it), in order, the cut
