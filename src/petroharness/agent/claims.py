"""The claims: the answer as claims the model adds, revises and drops by id, checked by code as they arrive (C2
holds the checks' messages, C3 renders the claims). The checks show the model facts about the record and its
citations; they never change a claim's content, grade or verdict (docs/DESIGN.md, G8)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from petroharness.agent import numbers as N
from petroharness.agent.checks import _NUM, number, number_provenance
from petroharness.agent.ledger import Ledger, shown_values

GRADES = ("hypothesis", "low", "moderate", "high", "not indicated", "undetermined")
_GRADE_WORDS = [  # how models write grades -> the scale (first match wins)
    (r"hypothes|unchecked|to check|untested|suspect", "hypothesis"),
    (r"not indicated|no indication|absent|none|negative|refuted", "not indicated"),
    (r"undetermin|cannot (be )?(settle|determine)|not determinable|unknown|insufficient", "undetermined"),
    (r"high|corroborat|strong|confirmed", "high"),
    (r"moderate|medium|fair|supported", "moderate"),
    (r"low|weak|marginal|log[- ]indicated|indicated|candidate|tentative|minor", "low"),
]
_APPROX = r"(?:~|≈|about |approx\w* |around |roughly )"
# flags any question may lean on (hole condition)
ANY_QUESTION_FLAGS = ("BAD_HOLE",)

_HYPOTHESIS = re.compile(r"^\s*(?:H\d+\s*[:.)\-]|hypothes\w*\s*[:\-]|expected\s*[:\-])", re.I)   # "H2: ...", "Hypothesis: ..."


def norm_grade(g) -> Optional[str]:
    g = str(g or "").strip().lower()
    if g in GRADES:
        return g
    if re.match(r"not (high|moderate|low|strong|weak|corroborat)", g):
        return None                                    # a negated grade says what it is not: refuse it
    for pat, grade in _GRADE_WORDS:
        if re.search(pat, g):
            return grade
    return None


_ECHO = re.compile(r"^(?:\s*C\d+\s*\[[^\]]*\]\s*)+")                     # "C1 [moderate] C1 [moderate] ..."
_TAIL = re.compile(r"(?:\s*\((?:\s*(?:E\d+(?:\s*[-–]\s*E\d+)?|MAP)\s*,?)+\))+\s*\.?\s*$")   # "... (E1, E4-E6, MAP)"


def clean_text(text: str) -> tuple:
    """Claim text without what the display adds (an echoed "C1 [grade]", a trailing list of item ids); the trailing
    ids become citations."""
    text = _ECHO.sub("", text or "").strip()
    cited = []
    m = _TAIL.search(text)
    if m:
        for a, b in re.findall(r"E(\d+)(?:\s*[-–]\s*E(\d+))?", m.group(0)):
            cited += [f"E{i}" for i in range(int(a), int(b or a) + 1)][:20]
        if "MAP" in m.group(0):
            cited.append("MAP")
        text = text[:m.start()].rstrip()
        text = text if text.endswith((".", "!", "?")) else text + "."
    return text, cited


def parse_ev(ev) -> list:
    """Cited items as models write them: a list or one string ("E1, E2", "[E3]"), ranges, any case; anything else
    (the map, the card, the index) is the map."""
    raw = ev if isinstance(ev, list) else [ev] if ev not in (None, "") else []
    out = []
    for x in raw:
        text = str(x).strip().upper()
        for a, b in re.findall(r"E(\d+)\s*[-–]\s*E(\d+)", text):
            if 0 <= int(b) - int(a) < 50:
                out += [f"E{i}" for i in range(int(a), int(b) + 1)]
        text = re.sub(r"E\d+\s*[-–]\s*E\d+", " ", text)
        out += re.findall(r"(?<![A-Z0-9])E\d+(?!\d)", text)
        if re.sub(r"(?<![A-Z0-9])E\d+(?!\d)|[\[\],;\s]", "", text):
            out.append("MAP")
    return list(dict.fromkeys(out))


def coerce_edit(raw) -> Optional[dict]:
    """An edit in the shapes models write -> {"op", "id", "point", "text", "means", "ev", "grade", "weak", "why"}."""
    if not isinstance(raw, dict):
        return None
    d = dict(raw)
    op = str(d.pop("op", "") or d.pop("action", "") or d.pop("type", "")).strip().lower()
    if not op:
        for k in ("add", "revise", "update", "edit", "drop", "delete", "remove"):
            if k in d:
                v = d.pop(k)
                op = k
                if isinstance(v, dict):
                    d = {**v, **d}
                elif isinstance(v, str):
                    d.setdefault("id", v)
                break
    op = {"update": "revise", "edit": "revise", "delete": "drop", "remove": "drop", "new": "add"}.get(op, op)
    if op not in ("add", "revise", "drop"):
        return None
    get = lambda *ks: next((d[k] for k in ks if k in d and d[k] not in (None, "")), None)
    ev = parse_ev(get("ev", "evidence", "evidence_ids", "items", "cites", "cite"))
    point = get("point", "p")
    if isinstance(point, (int, float)) and not isinstance(point, bool):
        point = int(point) if float(point).is_integer() else None
    elif point is not None:
        m = re.fullmatch(r"\s*(?:p(?:oint)?\s*)?(\d+)\s*", str(point), re.I)
        point = int(m.group(1)) if m else None
    text, cited = clean_text(str(get("text", "claim", "finding", "statement") or "").strip())
    if cited:
        ev = list(dict.fromkeys((ev or []) + cited))
    means = get("means", "meaning", "implication", "implies", "interpretation", "so_what")
    weak = get("weak", "weakness", "weaknesses", "limits", "limit", "caveats", "limitations")
    return {"op": op, "id": str(get("id", "claim_id", "cid") or "").strip().upper() or None, "point": point,
            "text": text or None, "means": str(means).strip() if means is not None else None, "ev": ev or None,
            "grade": get("grade", "confidence"), "weak": str(weak).strip() if weak is not None else None,
            "why": str(get("why", "reason") or "").strip()}


def _share(raw: str, text: str) -> bool:
    """raw% = 100 * a / b for two numbers a, b in the same sentence."""
    x, dec = number(raw), N.decimals(raw)
    tol = 0.5 * 10 ** (-dec) + 1e-9
    for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z(])|\n", text):
        if not re.search(rf"(?<![\d.]){re.escape(raw)}\s*%", sent):
            continue
        nums = [number(m.group(1)) for m in _NUM.finditer(sent) if not m.group(2)]     # as the checker reads them
        if any(b and abs(100 * a / b - x) <= tol for a in nums for b in nums if a < b):
            return True
    return False


from petroharness.agent import components as C  # noqa: E402  (the flags' texts: src/petroharness/agent/components/C2_guardrails/flags.json)


def _flag(key: str, **values) -> str:
    """A check's message, its template filled (C2 'flags')."""
    return C.fill_text(C.text("C2", "flags")[key], **values)


_NAME = re.compile(r"(?<![A-Za-z0-9_])(Z\d+|[A-Z][A-Z0-9_]{1,})(?![A-Za-z0-9_])")


class _Item:
    """A ledger item as the shared number rule reads evidence: its shown values and its text."""

    def __init__(self, item):
        self.id, self.item = item.id, item
        self.values = shown_values(item)
        self.columns = []

    def render(self) -> str:
        return f"[{self.item.id}] {self.item.text}"


def _same_context(x: str, text: str, item) -> bool:
    """The number sits in the item on a line that names something its sentence in the claim names (a zone, curve or
    class; a line under a curve's label counts the label)."""
    num = re.compile(rf"(?<![A-Za-z_\d.]){re.escape(x.rstrip('%'))}(?![\d])")
    sent = next((t for t in re.split(r"(?<=[.;!?])\s+|\n", text) if num.search(t)), text)
    names = set(_NAME.findall(sent))
    head = ""
    for line in item.lines:
        if not line.startswith(" "):
            head = line
        if num.search(line) and names & set(_NAME.findall(line + " " + head)):
            return True
    return False


def _item_names(item) -> set:
    """The curve and flag names an opened item's call reads (its arguments and condition)."""
    out = set()
    for k, v in (item.args or {}).items():
        if k in ("curves", "curve", "a", "b", "y", "x", "condition", "where"):
            for x in (v if isinstance(v, list) else [v]):
                out |= {t.upper() for t in re.findall(r"[A-Za-z][A-Za-z0-9_]*", str(x))}
    return out


@dataclass
class Claim:
    id: str
    point: int
    text: str
    means: str = ""
    ev: list = field(default_factory=list)
    grade: str = "hypothesis"
    weak: str = ""
    flags: list = field(default_factory=list)
    history: list = field(default_factory=list)
    text_at: int = 0                  # the results open when its text was written (a later id was opened after it)
    unshown: dict = field(default_factory=dict)   # its K3 numbers as data: {number as written: [items that hold it]}

    @property
    def settles(self) -> bool:
        return self.grade != "hypothesis" and not self.flags


class Claims:
    """The claims of one question's answer, checked against its ledger, the map and the question."""

    def __init__(self, points: list, ledger: Ledger, shown: str, question: str, view=None, wells: tuple = ()):
        self.points, self.ledger, self.shown, self.question = list(points), ledger, shown, question
        self.view, self.wells = view, tuple(wells)
        self.checks = view.reg.checks if view is not None else {}
        self.claims: dict = {}
        self.dropped: list = []
        self._n = 0
        self.families = ()                 # the families the model's topics read (the loop sets them; empty: all)

    @property
    def items(self) -> dict:
        return {e.id: e for e in self.ledger.items}

    # --- checks --------------------------------------------------------------------------------------------------
    def _unsupported(self, text: str, cited: list) -> list:
        bad, _ = number_provenance(text, self.shown, [_Item(e) for e in cited], self.checks, self.wells, self.question)
        out = []
        for x in dict.fromkeys(bad):
            raw = x.rstrip("%")
            if x.endswith("%") and _share(raw, text):
                continue                                       # a share of two numbers its sentence shows
            if re.search(_APPROX + re.escape(raw), text):
                first = N.first(raw)                           # a number, or a pair "k of N" (its first)
                v = number(first) if first else 0
                vals = [a for e in cited for a in shown_values(e)]
                if v and any(abs(a - v) <= 0.05 * abs(v) for a in vals):
                    continue                                   # an approximation of a shown value
            out.append(x)
        return out

    def check(self, c: Claim) -> list:
        items, flags = self.items, []
        missing = [e for e in c.ev if e != "MAP" and e not in items]
        if missing:
            flags.append(_flag("K1", missing=", ".join(missing)))
        if c.grade != "hypothesis" and not [e for e in c.ev if e == "MAP" or e in items]:
            flags.append(_flag("K2"))
        text = f"{c.text} {c.means} {c.weak}".strip()
        c.unshown = {}
        if c.grade != "hypothesis":
            cited = [items[e] for e in c.ev if e in items]
            bad = self._unsupported(text, cited)
            if bad:
                where = {}

                def holders(x) -> list:
                    """The results, not cited, that hold number x as written (for any number flagged, before or
                    after the citations added below: the check is redone on the cited set, which can flag a number
                    the first pass passed; benchmark N2 KeyError)."""
                    if x not in where:
                        where[x] = [e.id for e in items.values() if e.id not in c.ev
                                    and not number_provenance(x, "", [_Item(e)], self.checks, self.wells, "")[0]]
                    return where[x]
                for x in bad:
                    holders(x)
                digits = lambda x: len(re.sub(r"[^0-9]", "", x).lstrip("0"))

                def takes(x, i):
                    # a 4+ digit number held by 1-3 items rarely coincides
                    if digits(x) >= 4 and 1 <= len(where[x]) <= 3:
                        return True
                    return digits(x) >= 3 and 1 <= len(where[x]) <= 3 and _same_context(x, text, items[i])
                auto = sorted({i for x in bad for i in where[x] if takes(x, i)}, key=lambda i: int(i[1:]))
                if auto:                                       # the number is there: cite it (logged)
                    c.ev = c.ev + auto
                    c.history.append({"op": "cite", "by": "code", "ev": auto})
                    bad = self._unsupported(text, [items[e] for e in c.ev if e in items])
                if bad:
                    c.unshown = {x: list(holders(x)[:3]) for x in bad}      # the flag's numbers, as data (k3_split)
                    held = [_flag("K3_held", number=x, items=", ".join(holders(x)[:3])) for x in bad if holders(x)]
                    none = [x for x in bad if not holders(x)]
                    flags.append(_flag("K3", numbers="; ".join(held + ([_flag("K3_none", numbers=", ".join(none))]
                                                                       if none else []))))
        if c.grade == "high" and len({e for e in c.ev if e == "MAP" or e in items}) < 2:
            flags.append(_flag("K4"))
        if self.view is not None and c.grade != "hypothesis":
            flags += self.content_flags(text, c.text)
        if c.grade in ("high", "moderate", "not indicated"):
            flags += self._screen_not_run(c)
        if c.grade != "hypothesis" and _HYPOTHESIS.match(c.text or ""):
            flags.append(_flag("K10"))
        if c.grade not in ("hypothesis", "undetermined") and len(re.findall(r"[A-Za-z]{3,}", c.means or "")) < 3:
            flags.append(_flag("K9"))
        return flags

    def content_flags(self, text: str, claim_text: str = None) -> list:
        view, reg, out = self.view, self.view.reg, []
        for name, entry in (reg.checks.get("data_denials") or {}).items():
            present = [x for x in entry.get("curves", []) if view.available(x)]
            m = re.search(entry["pattern"], text, re.I) if present else None
            if m:
                out.append(_flag("K5_present", said=m.group(0), curves=", ".join(present), name=name))
        low = text.lower()
        has_core = view.available("PHIE_CC") or view.available("PERM_CC")
        for sent in re.split(r"(?<=[.!?])\s+", low):
            if has_core and reg.pattern("availability", "denial").search(sent) and \
                    reg.pattern("availability", "about_poroperm").search(sent) and not reg.pattern("availability", "hypothetical").search(sent):
                out.append(_flag("K7_unavailable"))
                break
            if not has_core and reg.pattern("availability", "calibrated_curve").search(sent) and \
                    not reg.pattern("availability", "negated").search(sent):
                out.append(_flag("K7_absent"))
                break
        # a well-wide route record read as this interval's route
        from petroharness.agent.routes import contradictions as route_contradictions
        out += [_flag("K5_route", said=m) for m in route_contradictions(text, view)]
        scoped = claim_text is not None
        out += self._before_claim(claim_text if scoped else text)  # the finding, not its caveats
        return out

    def _screen_not_run(self, c) -> list:
        """K11: a graded denial citing a screen that could not run here (rules/checks.yaml screen_not_run)."""
        cfg = self.checks.get("screen_not_run") or {}
        inv = getattr(getattr(self.ledger, "f", None), "inv", None)
        if not cfg or inv is None or not re.search(cfg["denial"], c.text or "", re.I):
            return []
        if re.search(cfg["caveat"], f"{c.text} {c.means} {c.weak}", re.I):
            return []
        dead = {}
        for sec in inv.sections:
            share = sum(float(re.sub(r"[^\d.]", "", k.share_pct or "0") or 0) for k in sec.classes
                        if k.name.upper() in cfg["no_indication_classes"])
            said = " ".join(map(str, sec.other)) + f" {sec.method or ''} {sec.basis or ''}"
            if share >= cfg["min_share_pct"] and re.search(cfg["could_not_run"], said, re.I):
                dead[sec.key] = said
        items = self.items
        cited = [e for e in c.ev if e in items and items[e].tool == "section"
                 and any(k == str(items[e].args.get("key")) or k.endswith("." + str(items[e].args.get("key"))) for k in dead)]
        if not cited:
            return []
        return [_flag("K11", items=", ".join(cited))]

    def _before_claim(self, text: str) -> list:
        """K8: the claim is about a property (its words) whose flags or classes have data here, and no opened item
        shows any of them."""
        cfg = (self.checks.get("indicators") or {}).get("properties") or {}
        opened = "\n".join(e.text for e in self.ledger.items)
        classes_here = {str(lab).upper(): key for key, sec in (getattr(self.ledger.f.store, "sections", {}) or {}).items()
                        for lab, rs in sec.classes.items() if rs}
        out = []
        scope = tuple(self.families) or None
        for name, prop in cfg.items():
            if not re.search(prop.get("words", r"(?!x)x"), text, re.I):
                continue
            flags = [fl for fl in prop.get("flags", []) if fl in self.ledger.f.inv.curves]
            pat = re.compile(prop.get("classes") or r"(?!x)x")
            classes = [lab for lab in classes_here if pat.fullmatch(lab)]
            if scope is not None:                              # only what the model's topics read
                classes = [lab for lab in classes if classes_here[lab].split(".", 1)[0] in scope]
                flags = [fl for fl in flags if fl in ANY_QUESTION_FLAGS or classes]
            if not flags and not classes:
                continue
            seen = [n for n in flags + classes if re.search(rf"(?<![A-Z0-9_]){re.escape(n)}(?![A-Z0-9_])", opened)]
            if not seen:
                how = [f"runs {fl}" for fl in flags[:2]] + [f"section {classes_here[c]}" for c in classes[:2]]
                out.append(_flag("K8", name=name, shown=", ".join((flags + classes)[:4]), how=" or ".join(how)))
        return out

    # --- edits ---------------------------------------------------------------------------------------------------
    def apply(self, edits: list) -> list:
        """Apply the edits in order; one message per edit that could not be applied (for the next turn)."""
        msgs = []
        for raw in edits or []:
            e = coerce_edit(raw)
            if e is None:
                msgs.append(f"not an edit: {str(raw)[:120]} (use op add, revise or drop)")
                continue
            if e["op"] == "add":
                if not e["text"]:
                    msgs.append("add: the claim has no text")
                    continue
                if e["point"] is None or not 1 <= e["point"] <= len(self.points):
                    msgs.append(f"add: point must be 1-{len(self.points)} (got {e['point']}): \"{e['text'][:60]}\"")
                    continue
                grade = norm_grade(e["grade"])
                if grade is None and e["ev"]:                # the grade is the model's: asked for, never set by code
                    got = f"got {e['grade']!r}" if e["grade"] is not None else "none given"
                    msgs.append(f"add: a claim that cites results needs its grade, one of {', '.join(GRADES)} ({got}): "
                                f"\"{e['text'][:60]}\"")
                    continue
                grade = grade or "hypothesis"                # no results cited: a hypothesis
                self._n += 1
                c = Claim(id=f"C{self._n}", point=e["point"], text=e["text"], means=e["means"] or "", ev=e["ev"] or [],
                          grade=grade, weak=e["weak"] or "", text_at=len(self.ledger.items))
                c.flags = self.check(c)
                c.history.append({"op": "add", "text": c.text, "ev": c.ev, "grade": c.grade, "flags": c.flags})
                self.claims[c.id] = c
                continue
            c = self.claims.get(e["id"] or "")
            if c is None and not e["id"] and e["point"] is not None:      # addressed by point: unambiguous only
                mine = [x for x in self.claims.values() if x.point == e["point"]]
                if len(mine) == 1:
                    c = mine[0]
                else:
                    msgs.append(f"{e['op']} without an id: point {e['point']} has claims "
                                f"{', '.join(x.id for x in mine) or 'none'} (give the claim's id)")
                    continue
            if c is None:
                msgs.append(f"{e['op']} {e['id']}: no such claim (claims: {', '.join(self.claims) or 'none'})")
                continue
            if e["op"] == "drop":
                c.history.append({"op": "drop", "why": e["why"]})
                self.dropped.append(self.claims.pop(c.id))
                continue
            if e["text"] and e["text"] != c.text:
                c.text, c.text_at = e["text"], len(self.ledger.items)
            if e["means"] is not None:
                c.means = e["means"]
            if e["ev"] is not None:
                c.ev = e["ev"]
            if e["grade"] is not None:
                g = norm_grade(e["grade"])
                if g is None:
                    msgs.append(f"revise {c.id}: grade must be one of {', '.join(GRADES)} (got {e['grade']!r})")
                else:
                    c.grade = g
            if e["weak"] is not None:
                c.weak = e["weak"]
            if e["point"] is not None and 1 <= e["point"] <= len(self.points):
                c.point = e["point"]
            c.flags = self.check(c)
            c.history.append({"op": "revise", "text": c.text, "ev": c.ev, "grade": c.grade, "flags": c.flags})
        return msgs

    def refresh(self) -> None:
        """Re-check every claim: new items can settle a flag."""
        for c in self.claims.values():
            c.flags = self.check(c)

    # --- views ---------------------------------------------------------------------------------------------------
    def settled(self, k: int) -> bool:
        return any(c.settles for c in self.claims.values() if c.point == k)

    def done_issues(self) -> list:
        out = [f"point {k} has no settled claim (graded, cited, unflagged)" for k in range(1, len(self.points) + 1)
               if not self.settled(k)]
        hyp = [c.id for c in self.claims.values() if c.grade == "hypothesis"]
        if hyp:
            out.append(f"hypotheses left: {', '.join(hyp)} (support, grade or drop each)")
        flagged = [c.id for c in self.claims.values() if c.flags]
        if flagged:
            out.append(f"flagged claims: {', '.join(flagged)} (fix or drop each)")
        return out


    def render(self) -> str:
        out = []
        for k, p in enumerate(self.points, 1):
            out.append(f"Point {k}: {p} [{'settled' if self.settled(k) else 'open'}]")
            mine = [c for c in self.claims.values() if c.point == k]
            for c in mine:
                ev = f" ({', '.join(c.ev)})" if c.ev else ""
                out.append(f"  {c.id} [{c.grade}] {c.text}{ev}")
                if c.means:
                    out.append(f"     means: {c.means}")
                if c.weak:
                    out.append(f"     weak: {c.weak}")
                out += [f"     ! {f}" for f in c.flags]
            if not mine:
                out.append("  (no claim yet)")
        return "\n".join(out)
