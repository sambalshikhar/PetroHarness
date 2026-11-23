"""Built sessions the tests share: one on a formation with net pay and saturation, as a READ call leaves it."""
from __future__ import annotations

import re

MEANS = "the zone holds the formation's hydrocarbon-bearing rock"     # a claim's 'means', for a settled pay claim


def runs_total(text: str) -> str:
    """The thickness a runs result gives for all its intervals, as its head line writes it
    ('Intervals where ... (N intervals, T m, P% of the gross)'): a number the result shows."""
    return re.search(r"^Intervals where .*?\(\d+ intervals?, ([\d.]+) ", text, re.M).group(1)


def chose(s, *topics):
    """The session as a READ call choosing these topics leaves it (the map kept as built)."""
    from petroharness.agent import direction
    s.topics, s.families = list(topics), direction.families(topics)
    return s


def pay_session():
    """A session on the first formation with NET_PAY and SW, READ having chosen hydrocarbon detection."""
    from _support.formations import F
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.map import render
    from petroharness.agent.state import Session
    t, f = next((t, f) for t, f in F() if "NET_PAY" in f.inv.curves and "SW" in f.inv.curves)
    return chose(Session(t, f, render(f.inv), Ledger(f)), "hydrocarbon_detection")
