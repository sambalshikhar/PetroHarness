"""Writing a result: Out (lines with their numbers, cut to the size limit) and the note of what a cut left out."""

from __future__ import annotations

import re
from petroharness.agent.map import num
from petroharness.well import summary as S
from petroharness.agent.engine.base import Formation, Result, max_chars
from petroharness.agent.engine.curves import zone_name


# --- writing --------------------------------------------------------------------------------------------------------

CUT_GET = "get this result with find"      # the ledger writes the result's id for "this result"


KEPT = ("", None, "kept")                  # a row held out of the text whose get a shown line names (Out.keep)


class Out:
    """Text and the numbers it shows, written together: each line keeps the numbers formatted into it. A line cut from
    the text shown (the size limit) stays in the result, held under what it is (its curve, its zone or row id)."""

    def __init__(self, f: Formation):
        self.f, self.rows, self._pending = f, [], []          # rows: (line, its numbers)
        self.held = []                                        # per row: None (shown), or (label, id, what) when cut

    def v(self, x) -> str:                                    # a value
        self._pending.append(float(x))
        return num(float(x))

    def i(self, k) -> str:                                    # a count
        self._pending.append(int(k))
        return str(int(k))

    def pct(self, p) -> str:                                  # a share, one decimal
        self._pending.append(float(p))
        return f"{float(p):.1f}%"

    def depth(self, x) -> str:
        return f"{self.v(x)} {self.f.inv.depth_unit}"

    def span(self, top, base) -> str:
        return f"{self.v(top)}-{self.v(base)} {self.f.inv.depth_unit}"

    def zone(self, z) -> str:
        return f"{z.zone_id} {zone_name(z)} {self.span(z.top, z.base)}"

    def child(self) -> "Out":
        return Out(self.f)

    def add(self, line: str, child=None) -> None:
        """A line shown, with the numbers written into it (child: an Out whose numbers they are, or a list of them)."""
        nums = self._pending + (list(child) if isinstance(child, list) else child._pending if child is not None else [])
        self.rows.append((line, nums))
        self.held.append(None)
        self._pending = []

    def hold(self, line: str, child, key: tuple) -> None:
        """A line kept in the result but cut from the text shown; key (label, id, what) names it in the cut line."""
        self.add(line, child)
        self.held[-1] = key

    def keep(self, line: str, child=None) -> None:
        """A line kept in the result and not shown, whose get a shown line already names (a long run list: the line
        says how many runs it shows and the find that fetches every one); the cut line does not repeat it."""
        self.add(line, child)
        self.held[-1] = KEPT

    def add_numbers(self, line: str, numbers: list) -> None:
        """A line written elsewhere, with the numbers written into it."""
        self.add(line)
        self.rows[-1] = (line, list(self.rows[-1][1]) + [float(x) for x in numbers])

    def extend(self, other: "Out") -> None:
        self.rows += other.rows
        self.held += other.held

    @property
    def lines(self) -> list:
        return [ln for ln, _ in self.rows]

    @property
    def shown_chars(self) -> int:
        return sum(len(ln) + 1 for (ln, _), h in zip(self.rows, self.held) if h is None)

    @property
    def numbers(self) -> list:
        return [x for _, ns in self.rows for x in ns]

    def fit(self, rows: list, budget: int = None, what: str = "zones", label: str = "") -> None:
        """Add rows (id, line, its Out or numbers): shown while the shown text stays within budget, the rest held in
        the result (named at the end of the text, with the find that fetches them)."""
        budget = max_chars() if budget is None else budget
        used, over = self.shown_chars, False
        for rid, ln, child in rows:
            over = over or used + len(ln) + 1 > budget - 260         # room for the cut line
            if over:
                self.hold(ln, child, (label, rid, what))
                continue
            self.add(ln, child)
            used += len(ln) + 1

    def result(self) -> Result:
        """The text shown, within max_chars (a last guard holds the lines past it); when lines were held, a last line
        naming them and the find that fetches them. The result keeps every line and number."""
        held, used, cap, over = list(self.held), 0, max_chars(), False
        for k, (ln, _) in enumerate(self.rows):
            if held[k] is not None:
                continue
            over = over or used + len(ln) + 1 > cap - 80
            if over:
                held[k] = ("", None, "lines")
            else:
                used += len(ln) + 1
        while True:                                               # the cut line fits too
            note = cut_note([(ln, h) for (ln, _), h in zip(self.rows, held) if h is not None and h is not KEPT])
            shown = [k for k, h in enumerate(held) if h is None]
            if not note or not shown or used + len(note) <= cap:
                break
            held[shown[-1]] = ("", None, "lines")
            used -= len(self.rows[shown[-1]][0]) + 1
        text = "\n".join([ln for (ln, _), h in zip(self.rows, held) if h is None] + ([note] if note else []))
        return Result(text, self.numbers, list(self.rows))


_ZONE_ID = re.compile(r"(?<![A-Za-z0-9_])Z(\d+)(?![A-Za-z0-9_])")


def cut_note(held: list) -> str:
    """The last line of a text cut to its size limit: what is not shown (each curve's zones, the runs, rows or lines)
    and the find that fetches it from the result. held: [(line, (label, id, what))]."""
    if not held:
        return ""
    groups = {}                                                   # (what, ids) -> labels
    order = []
    loose = 0
    for ln, (label, rid, what) in held:
        if rid is None:
            loose += 1
            continue
        key = next((k for k in order if k[0] == (what, label)), None)
        if key is None:
            key = ((what, label), [])
            order.append(key)
        key[1].append(str(rid))
    parts = {}
    for (what, label), ids in order:
        zone_like = all(re.fullmatch(r"Z\d+", i) for i in ids)
        which = S.zone_ids(ids) if zone_like else (", ".join(ids) if len(ids) <= 6 else f"{ids[0]} to {ids[-1]} ({len(ids)})")
        parts.setdefault((what, which), []).append(label)
    said = [(what.format(ids=which) if "{ids}" in what else f"{what} {which}")
            + (f" of {', '.join(x for x in labels if x)}" if any(labels) else "") for (what, which), labels in parts.items()]
    if loose:
        said.append(f"the last {loose} lines")
    zs = sorted({f"Z{m}" for ln, _ in held for m in _ZONE_ID.findall(ln)}, key=lambda z: int(z[1:]))
    more = ""
    if zs and sum(len(ln) + 1 for ln, _ in held) > max_chars():      # more than one get returns: a zone at a time
        find, more = zs[0], f" (a zone at a time: {S.zone_ids(zs)})"
    elif zs:
        find = S.zone_ids(zs)
    else:
        words = [w for _, (label, rid, _) in held for w in ([label] if label else [str(rid)] if rid is not None else [])]
        heads = [m.group(1) for ln, (_, rid, _) in held if rid is None             # a line's first words
                 for m in [re.match(r"\s*([A-Za-z0-9_]+(?: [a-z]+)?)", ln)] if m]
        find = ", ".join(list(dict.fromkeys(w for w in words + heads if w))[:8])
    return (f"(not shown here, to keep within the size limit: {'; '.join(said)}; they are in this result: "
            f"{CUT_GET} \"{find}\"{more})")
