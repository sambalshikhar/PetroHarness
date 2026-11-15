"""Which results show each number an answer states. The matching is the number checker's own
(petroharness.agent.checks: a number matches a shown value at its written precision, a percentage also a shown
fraction), applied result by result instead of over all results at once.

    shows(answer, items) -> {"0.2697": ["E7", "E12"], "14.03": ["E9"], ...}
"""
from __future__ import annotations

MAX_NUMBERS = 300                                           # numbers of one answer kept with their results


def shows(text: str, items: list, skip_integers_below: int = 20) -> dict:
    """Each number the text states (as written; small counts and ordinals left out, as the checker leaves them) ->
    the ids of the results that show it, in the ledger's order. A number no single result shows is absent: it was
    supported by the map, the zone table, the question, or arithmetic on shown numbers."""
    from petroharness.agent import checks as K
    from petroharness.agent.compose import strip_citations
    from petroharness.agent.writer import _DASH_MINUS, _Item, _Magnitudes
    wrapped = [(e.id, K._allowed_numbers("", [_Magnitudes(_Item(e))])) for e in items]
    out: dict = {}
    for m in K._NUM.finditer(strip_citations(K.ascii_minus(_DASH_MINUS.sub("-", text or "")))):
        raw, pct = m.group(1), bool(m.group(2))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        x = float(raw)
        if decimals == 0 and not pct and abs(x) < skip_integers_below:
            continue
        key = raw + ("%" if pct else "")
        if key in out or len(out) >= MAX_NUMBERS:
            continue
        ids = [i for i, allowed in wrapped if allowed.size and K._supported(x, decimals, allowed, pct)]
        if ids:
            out[key] = ids
    return out
