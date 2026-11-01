"""The writer: the answer written from the investigation's claims, every result it opened, the provenance card of the
curves those name, the zone table and the map (C9); its checker's repair requests (C2): numbers no result shows, words
about the investigation, and statements the record contradicts. The checker shows facts; it never asks for a different
verdict (docs/DESIGN.md, G8)."""

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
    card = s.map + ("\n" + table if table else "") + ("\n" + getattr(s, "card", "") if getattr(s, "card", "") else "")
    bad, _ = number_provenance(text, card, items, s.f.view.reg.checks, (s.task.well,), s.task.question)
    return list(dict.fromkeys(bad))




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


# the writer's own drafting left in the reply ("We need answer per rules.", "Need ensure ...", "Need include ..."): lines
# that open on "need" and a verb; two or more mark a draft (in 2,501 v3.5 answers only one, a drafted answer, had any)
DRAFT = re.compile(r"^\s*(?:we )?need (?!to\b|for\b|of\b|not\b)[a-z]+\b", re.I | re.M)


def drafting(text: str) -> list:
    """The drafting lines of a reply (DRAFT), when there are two or more; [] otherwise."""
    found = [m.group(0).strip() for m in DRAFT.finditer(text or "")]
    return found if len(found) >= 2 else []


def leaks(text: str) -> list:
    """The working notes left in an answer, each with a little of the text around it, in order, once each: the
    self-corrections (LEAK) and the drafting lines (DRAFT, two or more)."""
    out = [text[max(0, m.start() - 12):m.end() + 24].strip() for m in LEAK.finditer(text or "")]
    out += [ln for ln in drafting(text)[:4]]
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
    notes = lambda t: bool(META.search(t) or drafting(t))
    if not text or not notes(text):
        return text
    heads = re.findall(r"^#{1,3} .+$", draft or "", re.M) or re.findall(r"^#{1,3} .+$", text, re.M)
    if heads:
        i = text.rfind(heads[0])
        if i > 0 and not notes(text[i:]):
            return text[i:]
    return ""


# the settle step's view of every opened result (whole while the budget lasts, then digests)
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


# --- the reader's format (the reporting profile's `format` block: the zone table's style) ------------------------

def reader_format(policy, fmt: str = "profile") -> dict:
    """The profile's format block, or {} (the writer's own format) when there is none or the run asks for the default."""
    if fmt == "default":
        return {}
    return dict(profile(policy).get("format") or {})


def conventions_block(s) -> str:
    """The data's reporting conventions (data.conventions), as the prompts show them; "" when it has none."""
    conv = list(getattr(getattr(getattr(s, "f", None), "view", None), "conventions", None) or [])
    return ("THIS DATA'S REPORTING CONVENTIONS (how its reports name and group what the record holds; follow them in "
            "the answer without naming them):\n" + "\n".join(f"- {c}" for c in conv)) if conv else ""


# --- the writer's prompt -----------------------------------------------------------------------------------------------
# The claims carry the investigation's judgement; every opened result lets the writer set a claim right where a result
# says otherwise; the provenance card states what each curve is and what its values show.
RESULTS_CHARS = 60000
_MNEMONIC = re.compile(r"\b[A-Z][A-Z0-9_]{1,}\b")


def curve_card(s) -> str:
    """The provenance card (engine.provenance) of the curves the opened results and the claims name, in order of first
    mention."""
    from petroharness.agent import engine as E
    text = "\n".join(e.text for e in s.ledger.items) + "\n" + claims_block(s.claims, confidence=True)
    return E.provenance(s.f, [m for m in _MNEMONIC.findall(text) if m in s.f.inv.curves])


def prompt(s, fmt: str = "profile") -> tuple:
    """(system, user, table, shape): the question (and what it names that the record lacks), the data's conventions,
    the claims, every opened result in full (cut at RESULTS_CHARS), what the curves are, the zone table and the map,
    under C9's write text (with the table rule when a zone table is inserted)."""
    view = s.f.view
    shape = view.reg.shape_for(s.intent)
    form = reader_format(view.policy, fmt)
    table = zone_table(s, s.claims, wide=True, style=form.get("zone_table") or "by_curve") if shape in ("list", "report") else ""
    results = "\n\n".join(f"[{e.id}] {e.text}" for e in s.ledger.items)
    if len(results) > RESULTS_CHARS:
        results = results[:RESULTS_CHARS] + "\n... (cut)"
    s.card = curve_card(s)
    seen = (f"THE ZONE TABLE (inserted where you write {{{{ZONE_TABLE}}}}; computed from the data, its values are exact "
            f"and are evidence like the results: what you write must agree with it, and an empty cell is a zone without "
            f"that curve):\n{table}") if table else ""
    parts = [f"QUESTION:\n{s.task.question}", vocabulary.note(s), conventions_block(s),
             f"YOUR CLAIMS (readings made as the results came in; the results decide where they differ):\n"
             f"{claims_block(s.claims, confidence=True)}",
             f"RESULTS (everything the investigation computed, by id):\n{results}",
             f"WHAT THE CURVES ARE (from the record: each curve's meaning, status and what its values show):\n{s.card}",
             seen, f"THE MAP\n{writer_map(s.map)}"]
    system = C.text("C9", "write") + (f"\n9. {TABLE_RULE}" if table else "")      # the zone table once, as the writer's
    return system, "\n\n".join(p for p in parts if p), table, shape


def write(llm: LLM, s, cfg, usage: Usage, trace: dict, variant: str = "", fmt: str = "profile") -> tuple:
    """The answer: the writer's draft, the checker's rounds and the repairs, the zone table -> (text, status). The
    nodes are in the question graph (src/petroharness/agent/graph.py, docs/GRAPH.md), run here as the writer graph."""
    from petroharness.agent.graph import write_answer
    return write_answer(llm, s, cfg, usage, trace, variant, fmt)
