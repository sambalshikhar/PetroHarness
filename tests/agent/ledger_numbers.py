"""The checker's number matching asked of a ledger directly (tests only): whether a claimed number is shown in cited
results, and where a number is shown."""
from petroharness.agent import numbers as N
from petroharness.agent.ledger import _claimed, matches, shown_values


def verify(led, value, ids) -> bool:
    """Whether a claimed number is shown in the cited items, at the precision the claim states."""
    claim, half = _claimed(value)
    items = [led.by_id(i) for i in ([ids] if isinstance(ids, str) else ids)]
    return any(matches(claim, half, v) for e in items if e is not None for v in shown_values(e))


def locate(led, value) -> list:
    """(item id, line) for each line that shows the number."""
    claim, half = _claimed(value)
    out = []
    for e in led.items:
        for ln, nums in e.rows:
            vals = [float(x) for x in nums] + N.shown_values(ln)
            if any(matches(claim, half, v) for v in vals):
                out.append((e.id, ln))
    return out
