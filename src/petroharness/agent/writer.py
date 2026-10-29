"""The writer: the answer written from the checked claims, the zone table and the results the claims cite (C9);
its checker's repair requests (C2): numbers no result shows, words about the investigation, and statements the
record contradicts. The checker shows facts; it never asks for a different verdict (docs/DESIGN.md, G8)."""

from __future__ import annotations

import re

import numpy as np

from petroharness.profile import profile
from petroharness.llm import LLM, Usage
from petroharness.agent.checks import availability_issues, data_denials, number_provenance
from petroharness.agent.compose import strip_citations

from petroharness.agent.claims import Claims, _Item
from petroharness.agent.ledger import get_lines
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)
from petroharness.agent import vocabulary

LINES_CHARS = 9000

RULES = C.text("C9", "rules")
_NAMES = re.compile(r"(?<![A-Za-z0-9_])(Z\d+(?:\s*[-–]\s*Z\d+)?|[A-Z][A-Z0-9]*_[A-Z0-9_]+|[A-Z]{2,}[A-Z0-9]*)(?![A-Za-z0-9_])")


def claim_names(text: str) -> tuple:
    zones, words = [], []
    for n in _NAMES.findall(text or ""):
        m = re.fullmatch(r"Z(\d+)\s*[-–]\s*Z(\d+)", n)
        if m and 0 <= int(m.group(2)) - int(m.group(1)) < 60:
            zones += [f"Z{i}" for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        elif re.fullmatch(r"Z\d+", n):
            zones.append(n)
        elif n not in ("MAP", "AND", "OR", "NOT", "NO", "HC", "API", "MD", "TVD"):
            words.append(n)
    return list(dict.fromkeys(zones)), list(dict.fromkeys(words))


def k3_split(c) -> tuple:
    """A claim's K3 flag as ({number: [items that hold it]}, [numbers no opened item shows])."""
    held, none = {}, []
    for f in c.flags:
        if not f.startswith("K3"):
            continue
        body = re.sub(r"^K3\s+", "", f).split(" (cite the item")[0]
        for part in [x.strip() for x in body.split(";") if x.strip()]:
            m = re.match(r"(.+?) is in ((?:E\d+(?:, )?)+)$", part)
            if m:
                held[m.group(1).strip()] = [e.strip() for e in m.group(2).split(",")]
                continue
            m = re.match(r"(.+?) in no opened item$", part)
            if m:
                none += [x.strip() for x in m.group(1).split(",") if x.strip()]
            else:                                                  # unread: stays unverified
                none.append(re.sub(r"\s*\(.*$", "", part))
    return held, none


def _held(c) -> dict:
    """{item id: [numbers it holds]} for the claim's K3 numbers that opened items hold."""
    out = {}
    for x, eids in k3_split(c)[0].items():
        for e in eids:
            out.setdefault(e, []).append(x)
    return out


def _number_lines(item, numbers: list) -> list:
    """The item's lines that show one of the numbers, at the number's written precision."""
    out = []
    for x in numbers:
        v = re.sub(r"[^\d.\-]", "", x)
        try:
            val, dec = float(v), len(v.split(".")[1]) if "." in v else 0
        except ValueError:
            continue
        tol = 0.5 * 10 ** -dec + 1e-12
        out += [ln for ln, ns in item.rows if any(abs(n - val) <= tol for n in ns) and ln not in out]
    return out


def cited_lines(claims: Claims, budget: int = LINES_CHARS, only=None) -> str:
    """For each settled claim (or each of `only`, claim ids), the lines of the results it cites that hold what it names
    (its classes and curves, in the zones it names). Earlier points first; cut at the budget."""
    out, used, seen = [], 0, set()
    items = claims.items
    for c in sorted((c for c in claims.claims.values() if c.grade != "hypothesis" and (only is None or c.id in only)),
                    key=lambda c: (c.point, c.id)):
        zones, words = claim_names(f"{c.text} {c.weak}")
        for eid in c.ev:
            e = items.get(eid)
            if e is None or not (zones or words):
                continue
            q = ", ".join(words + zones) if words else ", ".join(zones)
            lines = [ln for ln in get_lines(e, q, zone_at=claims.ledger.zone_of) if (eid, ln) not in seen]
            if not lines:
                continue
            block = f"[{eid}] {e.call_text()} (for {c.id})\n" + "\n".join(lines)
            if used + len(block) > budget:
                out.append("... (more lines cut at the budget; the claims carry the rest)")
                return "\n\n".join(out)
            seen |= {(eid, ln) for ln in lines}
            out.append(block)
            used += len(block)
        for eid, numbers in _held(c).items():                      # items that hold numbers the claim did not cite
            e = items.get(eid)
            lines = [ln for ln in _number_lines(e, numbers) if (eid, ln) not in seen] if e is not None else []
            if not lines:
                continue
            block = f"[{eid}] {e.call_text()} (for {c.id}: holds {', '.join(numbers)})\n" + "\n".join(lines)
            if used + len(block) > budget:
                out.append("... (more lines cut at the budget; the claims carry the rest)")
                return "\n\n".join(out)
            seen |= {(eid, ln) for ln in lines}
            out.append(block)
            used += len(block)
    return "\n\n".join(out)


def claims_block(claims: Claims, confidence: bool = False) -> str:
    out = []
    for k, p in enumerate(claims.points, 1):
        out.append(f"Point {k}: {p}")
        mine = [c for c in claims.claims.values() if c.point == k and c.grade != "hypothesis"]
        for c in mine:
            held, none = k3_split(c)
            bad = [", ".join(none)] if none else []
            also = "".join(f"; {', '.join(eids)} (holds {x})" for x, eids in held.items())
            note = f" | unverified, do not state: {'; '.join(bad)}" if bad else ""
            grade = (f"{c.grade} confidence" if c.grade in ("low", "moderate", "high") else c.grade) if confidence else c.grade
            out.append(f"  [{c.id}] {c.text} | grade: {grade} | means: {c.means or '-'} | weak: {c.weak or '-'} | "
                       f"results: {', '.join(c.ev) or '-'}{also}{note}")
        if not mine:
            out.append("  (not settled by the investigation)")
    return "\n".join(out)


def writer_map(text: str) -> str:
    """The map as the writer reads it: without the notes block (the notes are for the investigation; what matters
    reaches the writer through the claims' weaknesses)."""
    return text.split("\nNotes on this interval")[0]


def contradictions(draft: str, s) -> list:
    """Statements of the draft that the record contradicts, as repair messages: core-calibrated curves said absent
    where they exist or used where there are none (V4), data said missing that the interval has (V9), and a well-wide
    route record read as this interval's route. Each states the fact; the model writes the correction."""
    if not (draft or "").strip():
        return []
    from petroharness.agent.routes import contradictions as route_contradictions
    text, view = strip_ids(draft), s.f.view
    out = availability_issues(strip_citations(text), view, view.reg) + data_denials(text, view)
    out += [f"WHAT: the answer {m}. FIX: state the route this interval uses." for m in route_contradictions(text, view)]
    return out


_DASH_MINUS = re.compile(r"(?<![\w.%)\]])[\u2013\u2014](?=\d)")     # "-0.138" written "\u20130.138" (not a range: 3\u20135)


class _Magnitudes:
    """a result's shown negative values also as their magnitudes ("0.138 below" restates a shown
    difference of -0.138; the computations' items already count both)."""

    def __init__(self, it):
        self.id, self.item, self.columns, self._text = it.id, it.item, [], it.render()
        self.values = list(it.values) + [abs(v) for v in it.values if v is not None and np.isfinite(v) and v < 0]

    def render(self) -> str:
        return self._text


def unsupported(text: str, s, table: str = "") -> list:
    """Numbers of the draft that no opened result, the map or the question shows (arithmetic on shown numbers in the
    same sentence passes); the zone table the writer is shown counts as shown, a dash right before a
    number is its minus sign, and a shown negative value supports its magnitude (otherwise an answer that holds only
    such numbers is sent to repair rounds for nothing)."""
    items = [_Item(e) for e in s.ledger.items]
    text = _DASH_MINUS.sub("-", text)
    items = [_Magnitudes(i) for i in items]
    card = s.map + ("\n" + table if table else "")
    bad, _ = number_provenance(text, card, items, s.f.view.reg.checks, (s.task.well,), s.task.question)
    return list(dict.fromkeys(bad))




# where the way a number is summarised changes the answer: the results that differ, and which leads and why (G6)
ASPECTS_RULE = C.text("C9", "aspects_rule")
# the limitations name what limits the findings, not a catalogue of logs
LIMITS_RULE = C.text("C9", "limits_rule")
# what the question names that this well's record lacks: said once, then what the data allow
ABSENT_RULE = C.text("C9", "absent_rule")
# a weakness qualifies a reading, it does not reverse it; a negative with its zone counts
NO_REVERSAL_RULE = C.text("C10", "no_reversal_rule")
# "low"/"high" in a question is a level, and also a ranking; the answers ranked three zones of low BVW
# and answered "No" because the zone with the highest permeability did not have the lowest of three low values
HIGH_LOW_RULE = C.text("C10", "high_low_rule")
# a formation of one zone has no zone-by-zone or zone-mean reading; its variation is by depth
ONE_ZONE_RULE = C.text("C9", "one_zone_rule")
EXACT_RULE = C.text("C9", "exact_rule")


def report_numbers(text: str) -> str:
    """The delivered text's numbers, as written: the results' own precision (no rounding in code)."""
    return text


TABLE_RULE = C.text("C9", "table_rule")
TABLE_ROWS = 60


def zone_table(s, claims: Claims, wide: bool = False, style: str = "by_curve") -> str:
    """The report's zone table (the report style's by-interval table: each zone's mean, and the geometric mean of a
    log-shaped curve), or by curve each zone's n, min, median, mean and max of the curves the settled claims name (and
    the question names), in the order they are first named, at most 5 curves and TABLE_ROWS rows."""
    from petroharness.agent.engine import restricted, statistic
    f = s.f
    values = lambda z, c: restricted(f, c, None)[np.asarray(z.indices)]    # a flag not computed somewhere: no value there
    named = []
    text = " ".join([s.task.question] + [f"{c.text} {c.means}" for c in claims.claims.values() if c.grade != "hypothesis"])
    from petroharness.agent.engine import same_as
    if len(f.view.zones) == 1 and style == "by_interval":           # one zone: a row per curve with its spread,
        style = "by_curve"                                          #   not one row of means
    flags_too = style == "by_interval"                              # a flag's interval mean is the share it covers
    from petroharness.well.summary import curve_kind
    kind = lambda c: curve_kind(f.view, c).kind                     # by the shape of the values: class codes have no
    for tok in re.findall(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]{1,}(?![A-Za-z0-9_])", text):   #   mean, a flag's is its share
        if tok in f.inv.curves and kind(tok) != "classes" and (flags_too or kind(tok) != "flag") and tok not in named \
                and not set(same_as(f, tok)) & set(named):          # one row for curves with the same values
            named.append(tok)
    zs = list(f.view.zones)
    most = 8 if wide else 5
    keep = named[:max(1, min(most, (TABLE_ROWS + (20 if wide else 0)) // max(len(zs), 1)))] if named else []
    if not keep or not zs:
        return ""
    u = f.inv.depth_unit
    from petroharness.agent.map import num
    if style == "by_interval":                                     # one row per interval, the curves' means across
        from petroharness.agent import direction                     # the standard curves of the model's topics first
        has = lambda c: np.isfinite(np.asarray(f.view.values(c), dtype=float)).any()
        core = []
        for c in direction.overview(getattr(s, "topics", ())):
            if c in f.inv.curves and has(c) and kind(c) != "classes" and c not in core and not set(same_as(f, c)) & set(core):
                core.append(c)
        core = core[:6]
        # the curves the question names lead (its mnemonics: vocabulary)
        said = set(vocabulary.written(s.task.question, named))
        asked = [c for c in named if c in said]
        core = list(dict.fromkeys(asked + core))[:6]
        cols = core + [c for c in named if c not in core and not set(same_as(f, c)) & set(core)][:max(0, 9 - len(core))]
        # each zone's mean, and the geometric mean beside it where the curve's values are positive and span more than
        # two orders of magnitude (the summary layer's shape rule, whatever the curve or the question's words)
        from petroharness.well.summary import log_shaped
        spec = [x for c in cols for x in ([(c, "mean"), (c, "geo_mean")] if kind(c) == "values"
                                          and log_shaped(f.view.values(c)) else [(c, "mean")])]
        names = {"mean": "Mean", "geo_mean": "Geometric mean"}
        head = ["Depth Interval (" + u + ")", "Lithology"] + [
            (f"{c} fraction" if kind(c) == "flag" else f"{names[k]} {' = '.join([c] + same_as(f, c))}") +
            (f" ({f.inv.curves[c].unit})" if f.inv.curves[c].unit and kind(c) != "flag" else "") for c, k in spec]
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for z in zs:
            lith = "no lithology data" if z.lithology.upper() == "NO_LITHOLOGY_DATA" else z.lithology.title()
            cells = []
            for c, k in spec:
                x = values(z, c)
                v = statistic(x, k)
                cells.append(report_numbers(num(v)) if v == v else "-")
            out.append(f"| {num(z.top)}-{num(z.base)} | {lith} | " + " | ".join(cells) + " |")
        return "\n".join(out)
    if len(zs) == 1:                                                       # one zone: the property's standard curves
        from petroharness.agent import direction                                             #   first, as the by-interval table has them
        core = []
        for c in direction.overview(getattr(s, "topics", ())):
            if c in f.inv.curves and kind(c) not in ("flag", "classes") and f.view.available(c) and c not in core \
                    and not set(same_as(f, c)) & set(core):
                core.append(c)
        keep = list(dict.fromkeys(core[:6] + [c for c in named if not set(same_as(f, c)) & set(core[:6])]))[:most]
    out = [f"| Zone | Lithology | Depth ({u}) | Curve | n | Min | Median | Mean | Max |", "|---|---|---|---|---|---|---|---|---|"]
    for z in zs:
        lith = "no lithology data" if z.lithology.upper() == "NO_LITHOLOGY_DATA" else z.lithology.title()
        for c in keep:
            x = values(z, c)
            vals = [statistic(x, k) for k in ("n", "min", "median", "mean", "max")]
            cells = [str(int(vals[0]))] + [report_numbers(num(v)) if v == v else "-" for v in vals[1:]]
            zid = f"{z.zone_id} ({z.name})" if getattr(z, "name", "") else z.zone_id
            name = " = ".join([c] + same_as(f, c))
            out.append(f"| {zid} | {lith} | {num(z.top)}-{num(z.base)} | {name} | " + " | ".join(cells) + " |")
    return "\n".join(out)


# words about the investigation rather than the formation; NEW and ids in capitals only
PROCESS = re.compile(r"\b(?:workflow|opened) record\b|\b(?:not )?opened\b(?! up)|\bthe (?:ledger|tool)\b|\bthe claims?\b(?! that)|"
                     r"\bresult lines?\b|\bthe map\b|\bthe record shows\b|(?-i:\bNEW\b)|(?-i:(?<![\w\[(./-])E\d{1,3}\b)", re.I)
_CLAIM_IDS = re.compile(r"\s?[\[(]\s*(?:C\d+|MAP)(?:\s*[,;/]\s*(?:C\d+|E\d+|MAP))*\s*[\])]")


# a view's size limit is no fact about the data ("zones left out to keep this short" became "the
# zone records are truncated" in the limitations)
DISPLAY = re.compile(r"\bleft out to keep (?:this|it) short\b|\b(?:display|view|output)(?:'s)? (?:size )?limit\b|"
                     r"\btruncated (?:in|from) the (?:records?|results?|outputs?|tables?|summar(?:y|ies))\b|"
                     r"\b(?:records?|results?|outputs?|tables?|summar(?:y|ies)|zone rows|rows) (?:were |was |are |is )?"
                     r"(?:truncated|cut off)\b|\bnot shown in this view\b", re.I)


# the model's self-corrections left in the text ("SIL... wait, SILT_GROUP_20"): working notes, not the answer
LEAK = re.compile(r"(?:\.\.\.|…)\s*(?:wait|hmm|oops|sorry|no wait)\b|\b(?:wait|hmm|oops)\s*[,!:]|\bscratch that\b", re.I)


def leaks(text: str) -> list:
    """The working notes left in an answer, each with a little of the text around it, in order, once each."""
    out = [text[max(0, m.start() - 12):m.end() + 24].strip() for m in LEAK.finditer(text or "")]
    return list(dict.fromkeys(out))


def process_words(text: str) -> list:
    """The phrases of an answer that talk about the investigation, in order, once each."""
    found = [m.group(0) for m in PROCESS.finditer(text)] + [m.group(0) for m in DISPLAY.finditer(text)]
    return list(dict.fromkeys(found))


def strip_ids(text: str) -> str:
    """Evidence ids, claim ids and [MAP] out of the delivered text."""
    out = strip_citations(_CLAIM_IDS.sub("", text))
    return re.sub(r"[ \t]+([.,;:])", r"\1", out)


# the model's working notes, which a reasoning model sometimes writes into its reply (the repair turn above all)
META = re.compile(r"\bThe user\b|\bLet me\b|\bI need to\b|\bI will (?:now )?(?:rewrite|check|fix|remove|go)|\b(?:my|the) "
                  r"previous (?:answer|draft|version|reply)\b|\bActually,|\brewrite the answer\b|\bthese need to go\b|"
                  r"^\s*-\s*\"[^\"]{3,}\"\s*[—-]", re.I | re.M)


def clean_reply(text: str, draft: str = "") -> str:
    """The answer in a reply, without the model's working notes: from the last occurrence of the draft's first heading
    (or the reply's last first-level section start) when notes precede it; "" when notes remain."""
    if not text or not META.search(text):
        return text
    heads = re.findall(r"^#{1,3} .+$", draft or "", re.M) or re.findall(r"^#{1,3} .+$", text, re.M)
    if heads:
        i = text.rfind(heads[0])
        if i > 0 and not META.search(text[i:]):
            return text[i:]
    return ""


# variant "open": no word caps, everything opened in view, zones by record name, data availability
OPEN_SHAPES = C.text("C9", "open_shapes")
OPEN_RULES = C.text("C9", "open_rules")
_OPEN_DROP = ("Respect the length for the shape", "Limitations are the weaknesses", "State each finding's grade once")

# The general reporting rules, in this harness's terms (map, results, claims). Class a: reporting practice. In order:
# readings off the question are context; the class rule; rank, never deny; mixed readings; controls; negatives; the
# grade rule without its ban on naming a likely fluid (the gas facet asks for the favoured fluid, graded).
V5_RULES = C.text("C9", "v5_rules")

# Style: prose dense with numbers, machine digits and class codes in sentences, and every interval restated across
# sections read poorly. Numbers go to four significant figures in code; these rules keep the findings and move the
# zone values to the table the answer already carries.
OPEN_CHARS = 24000


def opened_results(s, budget: int = OPEN_CHARS) -> str:
    """Every opened result: whole while the budget lasts, newest last; then digests. the results the
    claims cite and the newest are kept whole first, the oldest uncited ones digested first (a digested newest result
    would leave a class found last written as 'not shown')."""
    items = s.ledger.items
    claims = getattr(s, "claims", None)               # a session before its investigation has none
    cited = {x for c in (claims.claims.values() if claims is not None else []) for x in c.ev}
    order = [e for e in items if e.id in cited] + [e for e in reversed(items) if e.id not in cited]
    whole_ids, used = set(), sum(len(s.ledger.digest(e)) + 2 for e in items)
    for e in order:                                    # upgrade digests to the whole text while the budget lasts
        extra = len(e.text) + len(e.id) + 3 - len(s.ledger.digest(e))
        if used + extra <= budget:
            whole_ids.add(e.id)
            used += extra
    return "\n\n".join(f"[{e.id}] {e.text}" if e.id in whole_ids else s.ledger.digest(e) for e in items)


# --- the reader's format (the reporting profile's `format` block; the writer's own format without one) -------------

ZONE_RULE_PREFIXES = ("Refer to zones by id and depth range", "Name each zone at first mention")
LITH_ZONES = C.text("C9", "lith_zones")
LENGTH_PREFIX = "Length follows the content"


def reader_format(policy, fmt: str = "profile") -> dict:
    """The profile's format block, or {} (the writer's own format) when there is none or the run asks for the default."""
    if fmt == "default":
        return {}
    return dict(profile(policy).get("format") or {})


def apply_format(rules: list, shapes: dict, f: dict) -> tuple:
    """(rules, shapes) under a format: its shapes over the writer's, its length, its way of naming zones."""
    if not f:
        return rules, shapes
    shapes = {**shapes, **{k: " ".join(str(v).split()) for k, v in (f.get("shapes") or {}).items()}}
    out = []
    for r in rules:
        if r.startswith(ZONE_RULE_PREFIXES) and f.get("zone_names") == "lithology_and_depth":
            if LITH_ZONES not in out:
                out.append(LITH_ZONES)
            continue
        if r.startswith(LENGTH_PREFIX) and f.get("words"):
            lo, hi = f["words"]
            out.append(f"Length: about {lo}-{hi} words. Cover every point with the intervals and values that settle it; "
                       "leave out what does not bear on the question. (The reader's format.)")
            continue
        out.append(r)
    if f.get("words") and not any(r.startswith("Length: about") for r in out):
        lo, hi = f["words"]
        out.append(f"Length: about {lo}-{hi} words. (The reader's format.)")
    out += [" ".join(str(r).split()) for r in f.get("rules") or []]
    return out, shapes



def prompt(s, variant: str = "", fmt: str = "profile") -> tuple:
    """(system, user, table, shape): the writer's prompt. It always holds the points and every settled claim (the
    gate checks it)."""
    view = s.f.view
    shape = view.reg.shape_for(s.intent)
    open_ = variant == "open"
    form = reader_format(view.policy, fmt)
    style = form.get("zone_table") or "by_curve"
    table = zone_table(s, s.claims, wide=open_, style=style) if shape in ("list", "report") else ""
    rules = ([r for r in RULES if not r.startswith(_OPEN_DROP)] + OPEN_RULES) if open_ else list(RULES)
    rules = rules + V5_RULES
    rules = [EXACT_RULE if r.startswith("Round numbers to the precision") else r for r in rules]   # numbers as computed
    rules = rules + [ASPECTS_RULE, NO_REVERSAL_RULE, HIGH_LOW_RULE]
    zs = getattr(getattr(getattr(s, "f", None), "view", None), "zones", None)
    if zs is not None and len(zs) == 1:                 # one zone: no zone-level verdicts to give
        rules = rules + [ONE_ZONE_RULE]
    # limitations tied to findings; what the question names and the record lacks (the note under the question)
    rules = [LIMITS_RULE if r.startswith("In the limitations, say once which measured logs") else r for r in rules]
    absent = vocabulary.note(s)
    if absent:
        rules = rules + [ABSENT_RULE]
    base_shapes = dict(OPEN_SHAPES) if open_ else {n: " ".join(x["instructions"].split()) for n, x in view.reg.shapes.items()}
    rules, shape_map = apply_format(rules, base_shapes, form)
    rules = rules + ([TABLE_RULE] if table else [])
    shapes = "\n".join(f"- {k}: {v}" for k, v in shape_map.items())
    system = (C.text("C9", "write")
              .replace("{RULES}", "\n".join(f"{i + 1}. {r}" for i, r in enumerate(rules)))
              .replace("{SHAPES}", shapes))
    pack = cited_lines(s.claims)
    points = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(s.claims.points))
    seen = (f"THE ZONE TABLE (inserted where you write {{{{ZONE_TABLE}}}}; computed from the data, its values are exact "
            f"and are evidence like the results: what you write must agree with it, and an empty cell is a zone without "
            f"that curve):\n{table}") if table else ""
    parts = [f"QUESTION:\n{s.task.question}", absent, f"THE ANSWER MUST SETTLE:\n{points}",
             f"YOUR CLAIMS:\n{claims_block(s.claims, confidence=open_)}",
             f"RESULT LINES (what the claims cite):\n{pack}" if pack else "",
             f"ALL RESULTS (everything the investigation computed):\n{opened_results(s)}" if open_ else "",
             seen, f"THE MAP\n{writer_map(s.map)}", f"Write the answer in the '{shape}' shape."]
    user = "\n\n".join(p for p in parts if p)
    return system, user, table, shape


def write(llm: LLM, s, cfg, usage: Usage, trace: dict, variant: str = "", fmt: str = "profile") -> tuple:
    """The answer: the writer's draft, the checker's rounds and the repairs, the zone table -> (text, status). The
    nodes are in the question graph (src/petroharness/agent/graph.py, docs/GRAPH.md), run here as the writer graph."""
    from petroharness.agent.graph import write_answer
    return write_answer(llm, s, cfg, usage, trace, variant, fmt)
