"""Deterministic checks of a written answer against the record (numbers traced to evidence, data said missing that the
interval has, core-calibrated curves said absent or used where there are none), returned as WHAT / WHY / FIX
messages. They show facts; what the answer concludes is the model's (docs/DESIGN.md, G8). The writer's checker calls
them (src/petroharness/agent/writer.py)."""

from __future__ import annotations

import re
from typing import Iterable, Optional

import numpy as np

from petroharness.record.catalog import Evidence
from petroharness.well.view import FormationView
from petroharness.agent.compose import strip_citations
from petroharness.agent.engine import ToolError
from petroharness.agent.ledger import evaluate

from petroharness import options
from petroharness.agent import numbers as N
from petroharness.agent.numbers import NUM as _NUM, number, shown_values   # noqa: F401  (the one grammar)
_MINUS = str.maketrans({"\u2212": "-", "\ufe63": "-", "\uff0d": "-"})   # typographic minus signs: a model writes -0.42 as \u22120.42


def ascii_minus(text: str) -> str:
    """Typographic minus signs (U+2212 and its variants) as ASCII '-': the number checks read a signed value only
    with an ASCII minus (otherwise \u22120.419 reads as 0.419 and is flagged against a shown -0.419)."""
    return (text or "").translate(_MINUS)


def _allowed_numbers(card: str, evidence: list[Evidence], question: str = "") -> np.ndarray:
    """Numbers the answer may state: the evidence values and every number shown in the pack, the card and the
    question (a threshold or percentile the question states; a percentage there also as a fraction)."""
    vals: list[float] = []
    for e in evidence:
        vals.extend(float(v) for v in e.values if v is not None and np.isfinite(v))
        vals += shown_values(ascii_minus(e.render()))
    vals += shown_values(card)
    for m in _NUM.finditer(question):
        vals.append(number(m.group(1)))
        if m.group(2):
            vals.append(number(m.group(1)) / 100)
    return np.unique(np.asarray(vals, dtype=float))


def _supported(x: float, decimals: int, allowed: np.ndarray, percent: bool) -> bool:
    """x matches an allowed value at x's displayed precision, directly or as a fraction shown in percent; a percentage
    also as the complement of a shown share (100 - p, or 100 x (1 - f): the share that is not), recomputed here."""
    tol = N.tolerance(N.half_of(decimals), x)
    if np.any(np.abs(allowed - x) <= tol):
        return True
    if not percent:
        return False
    frac, pct = allowed[(allowed >= 0) & (allowed <= 1)], allowed[(allowed >= 0) & (allowed <= 100)]
    return bool(np.any(np.abs(allowed * 100 - x) <= tol)                 # a fraction written as a percentage
                or np.any(np.abs(100 * (1 - frac) - x) <= tol) or np.any(np.abs(100 - pct - x) <= tol))


def _derived(x: float, decimals: int, stated: list[float], percent: bool = True, counts: list = None) -> bool:
    """x is a difference (with its sign or without), sum, product or ratio of two supported numbers stated in the same sentence
    (a percentage difference or share of them only where x is written as a percentage: "50 samples" is no
    100 x (12 - 8) / 8), or the total of a run of
    them as the sentence lists them ("51 samples (DTC 9, RDEP 11, GR 11, PERM 12, NPHI 8)"); a count's run is read
    over the sentence's counts, the shares written beside them left out ("3474 split as 662 (18.1%), 2799 (76.4%), 12
    (0.3%) and 1 (0.0%)"): the answer shows its inputs, so the arithmetic is checkable."""
    tol = N.tolerance(N.half_of(decimals), x)
    run = counts if counts is not None and not percent else stated
    least = 3 if options.get().tight_numbers else 2     # a mean of two is a midpoint: "0.12 to 0.24, mean 0.18"
    for i in range(len(run)):                          # a total beside its breakdown, or the mean of the values listed
        total = run[i]                                 #   ("roughly 1.63 (1.6911, 1.541, 1.6435)")
        for j in range(i + 1, len(run)):
            total += run[j]
            if (j - i >= 2 and abs(total - x) <= tol) or (j - i + 1 >= least and abs(total / (j - i + 1) - x) <= tol):
                return True
    for i, a in enumerate(stated):
        for b in stated[i + 1:]:
            cands = [abs(a - b), a - b, b - a, a + b, a * b]   # a change written with its sign ("78.375 to 74.625
            #   (-3.75)"); a product ("0.875 x 27.5 ft = 24.0625": a share of a thickness)
            for num, den in ((a, b), (b, a)):
                if den:
                    cands += [num / den] + ([100 * abs(num - den) / abs(den), 100 * num / den] if percent else [])
            if any(abs(c - x) <= tol for c in cands):      # a percentage: a change, or a share ("30 of 185 (16.2%)")
                return True
    return False


_NAME_SEP = r"[\s/_#-]"


def well_name_pattern(well: str) -> Optional[re.Pattern]:
    """The well's name as prose may write it: its letter and digit runs in order (same case), joined by any of
    space / _ # - (a file stem writes '/' as '_': '12_3-4 A' matches '12/3-4 A' and '12/3-4A'). Adjacent digit runs
    need a separator, so the pattern never swallows a plain number. None for a name of one run or without digits:
    it cannot be told from a number (or from a word), and the card states it anyway."""
    tokens = re.findall(r"[A-Za-z]+|\d+", str(well))
    if len(tokens) < 2 or not any(t.isdigit() for t in tokens):
        return None
    body = re.escape(tokens[0])
    for prev, tok in zip(tokens, tokens[1:]):
        body += (_NAME_SEP + "+" if prev.isdigit() and tok.isdigit() else _NAME_SEP + "*") + re.escape(tok)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])")


# the unit a worked-out number's inputs must stand in: a sentence (clauses joined by ";" are one: "PHIE mean 0.1258;
# PHIT mean 0.1260 (diff 0.0002)" in a table cell), ended by . ! ? or a line
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")


def _prepared(text: str, card: str, evidence, rules: dict, wells, question: str) -> tuple:
    """(the text as the checker reads it: citations, the well's name and the ignore patterns out; the card; the
    numbers allowed), the one reading of number_provenance and derivations."""
    text, card, question = ascii_minus(text), ascii_minus(card), ascii_minus(question)
    for pattern in filter(None, map(well_name_pattern, wells)):
        question = pattern.sub(" ", question)
    allowed = _allowed_numbers(card, evidence, question if rules.get("question", True) else "")
    clean = N.spelled_as_digits(strip_citations(text))   # numbers written in words, read as the digits they write
    for pattern in filter(None, map(well_name_pattern, wells)):
        clean = pattern.sub(" ", clean)
    for pat in rules.get("ignore", []):
        clean = re.sub(pat, " ", clean)
    return _regrouped(clean, allowed), card, allowed


# thousands grouped by spaces ("3 114.1112", "(10 000)", "5 192 samples"), the SI way: the digits of one number
_GROUPED = re.compile(r"(?<![A-Za-z_\d.,])\d{1,3}(?: \d{3})+(?:\.\d+)?(?!\d)")


def _regrouped(text: str, allowed: np.ndarray) -> str:
    """Thousands written with spaces read as one number where that number is one the record shows (a
    permeability answer wrote "3 114.1112 mD" and "Z6 (6 376)", and 20 of its numbers were read as pairs of others);
    digits that stand apart otherwise ("2 300" for 2 and 300) stay as written."""
    def one(m):
        joined = m.group(0).replace(" ", "")
        return joined if _supported(number(joined), N.decimals(joined), allowed, False) else m.group(0)
    return _GROUPED.sub(one, text)


def derivations(text: str, card: str, evidence: list, flagged, checks: dict | None = None, wells=(),
                question: str = "") -> dict:
    """For a flagged number that is a difference (with its sign or without), sum, ratio or share of two numbers the
    answer states elsewhere, each shown by a result: {the flagged number: "A - B"}. The repair names that arithmetic
    so the writer keeps the number and writes its inputs beside it ("higher by 18.87 API" was
    flagged because the two means stood in the next sentence, and the repair's 'or remove it' removed the answer). The
    check itself stays the sentence's: this only says how to pass it."""
    rules = (checks or {}).get("numbers", {})
    clean, _, allowed = _prepared(text, card, evidence, rules, wells, question)
    stated = []
    for m in _NUM.finditer(clean):
        raw, pct = m.group(1), bool(m.group(2))
        x = number(raw)
        if (raw, x) not in stated and _supported(x, N.decimals(raw), allowed, pct) and abs(x) >= 1e-12:
            stated.append((raw, x))
    out = {}
    for item in flagged:
        raw = str(item).rstrip("%")
        pct = str(item).endswith("%")
        try:
            x = number(raw)
            tol = N.tolerance(N.half_unit(raw), x)
        except ValueError:
            continue
        said = _written(clean, raw, pct)
        if said is not None:                           # the arithmetic written out beside it: its value, computed
            expr, value = said
            if abs(value - x) > tol:
                out[item] = ("wrong", expr, f"{value:.{max(N.decimals(raw), 0)}f}")
                continue
        for i, (ra, a) in enumerate(stated):
            for rb, b in stated[i + 1:]:
                cands = [(f"{ra} - {rb}", a - b), (f"{rb} - {ra}", b - a), (f"{ra} + {rb}", a + b)]
                cands += [(f"{ra} / {rb}", a / b), (f"{rb} / {ra}", b / a)] if a and b else []
                if pct and a and b:
                    cands += [(f"100 x {ra} / {rb}", 100 * a / b), (f"100 x {rb} / {ra}", 100 * b / a)]
                hit = next((e for e, v in cands if abs(abs(v) - abs(x)) <= tol and (v < 0) == (x < 0)), None)
                if hit:
                    out[item] = ("elsewhere", hit)
                    break
            if item in out:
                break
    return out


_NUMBER = r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
# one piece of written arithmetic: a number (not the digits of a name like Z1), an operator, a parenthesis, or an "x"
# standing alone as the multiplication sign; a run of them up to the "=" is the expression the answer computes
_TOKEN = rf"(?:(?<![\d.,_A-Za-wyz]){_NUMBER}|[-+*/()]|(?<![A-Za-z])x(?![A-Za-z]))"
_EXPRESSION = re.compile(rf"(?:{_TOKEN}\s*)+$")
_RESULT = re.compile(rf"(?:=|≈|~|is about|is)\s*~?\s*\+?({_NUMBER})\s*(%)?")


def _written(text: str, raw: str, pct: bool):
    """The arithmetic the answer writes out right before a number ("0.1417 / 0.2688 ≈ 0.5277", "0.2 x (1 - 0.35) =
    0.13"): (the expression as written, its value, x 100 where the number is a percentage), else None. The expression
    is the whole run of arithmetic before the "=" back to the clause start, computed with precedence by the ledger's
    calculator (a fragment read left to right asked for 0.65 in "0.2 x (1 - 0.35) = 0.13", and for 0.52 in "1 - 0.35 x
    0.8 = 0.72", where the writer was right); an expression that does not parse names no value. The writer's
    arithmetic slips (golden and benchmark answers: 4.375 / 5.1063 written 0.8569) are named with their value so the
    repair corrects them."""
    t = text.replace("\u00d7", "x").replace("\u00f7", "/").replace("\u2212", "-")
    for m in _RESULT.finditer(t):
        if m.group(1) != raw or bool(m.group(2)) != pct:
            continue
        run = _EXPRESSION.search(SENTENCE.split(t[:m.start()])[-1])
        if not run:
            continue
        expr = " ".join(run.group(0).split())
        expr = re.sub(r"^(?:(?:[)*/+x]|-(?=\s))\s*)+", "", expr)     # a ")" or a spaced dash before it is not its own
        while expr.startswith("(") and expr.count("(") > expr.count(")"):              # a parenthesis it sits in
            expr = expr[1:].lstrip()
        try:
            value, inputs = evaluate(re.sub(r"(?<=\d),(?=\d{3})", "", expr).replace("x", "*"))
        except ToolError:
            continue
        if len(inputs) >= 2:
            return expr, (100 * value if pct else value)
    return None


def number_provenance(text: str, card: str, evidence: list[Evidence], checks: dict | None = None,
                      wells: Iterable[str] = (), question: str = "") -> tuple[list[str], int]:
    """(unsupported numbers, numbers checked). The names in `wells` (the task's well) and the checks' `ignore`
    patterns are removed first: they contain digits but are not numbers. Numbers the question states are supported
    (checks numbers.question), and so count as inputs of a derived number in the same sentence."""
    rules = (checks or {}).get("numbers", {})
    clean, card, allowed = _prepared(text, card, evidence, rules, wells, question)
    unsupported, total = [], 0
    lines = None                                       # each shown line's values, read once a pair needs them

    def paired(k: str, n: str) -> bool:                # one shown line holds k with N, or N - k with N
        nonlocal lines
        if lines is None:                              # every line of what is shown: the card's, and each result's
            texts = card.splitlines() + [ln for e in evidence for ln in _lines_of(e)]     # rows, as its values are
            lines = [np.asarray(shown_values(ascii_minus(ln)), dtype=float) for ln in texts if ln.strip()]
        dk, dn = N.decimals(k), N.decimals(n)
        xk, xn = number(k), number(n)
        return any(_supported(xn, dn, ln, False) and (_supported(xk, dk, ln, False) or _supported(xn - xk, dk, ln, False))
                   for ln in lines if ln.size >= 2)

    tight = options.get().tight_numbers
    named, asked = None, np.asarray(shown_values(ascii_minus(question)), dtype=float)

    def on_a_line_naming(x: float, d: int, pct: bool, names: set) -> bool:
        """x shown on a line that names one of `names`: on the line itself, in its result's first line (what the
        result is about) or in its table's header row."""
        return any(toks & names and _supported(x, d, vals, pct) for toks, vals in named_lines() if vals.size)

    def named_lines() -> list:
        nonlocal named
        if named is None:                              # (names, values) of every shown line, once
            named = []
            for b, block in enumerate([card.splitlines()] + [_lines_of(e) for e in evidence]):
                head, header = set(), set()
                for j, ln in enumerate(block):
                    toks = set(_NAMES.findall(ln))
                    if b and j == 0:
                        head = toks
                    if not ln.lstrip().startswith("|"):
                        header = set()
                    elif _RULE.match(ln):
                        continue
                    elif not header:
                        header = toks or {""}
                    named.append((toks | head | header, np.asarray(shown_values(ascii_minus(ln)), dtype=float)))
        return named

    for sentence in SENTENCE.split(clean):
        found, measured = [], set()
        for m in _NUM.finditer(sentence):
            raw, pct = m.group(1), bool(m.group(2))
            found.append((raw, pct, N.decimals(raw), number(raw)))
            if tight and _UNIT_AFTER.match(sentence, m.end()):
                measured.add(len(found) - 1)           # "net pay 12 m": a measure, not a count
        stated = [x for _, pct, d, x in found if _supported(x, d, allowed, pct)]
        counts = [x for _, pct, d, x in found if not pct and _supported(x, d, allowed, pct)]
        in_pairs = set()                                # "k of N": judged as a pair, not number by number
        for m in _PAIR.finditer(sentence):
            k, n = m.group(1), m.group(2)
            if min(number(k), number(n)) < rules.get("skip_integers_below", 20) or N.decimals(k) or N.decimals(n):
                continue                               # a count is a whole number: "40.08/50.51" lists two values
            in_pairs |= {k, n}
            total += 1
            if paired(k, n):
                continue
            xk = number(k)
            others = lambda xs: (lambda i: xs[:i] + xs[i + 1:])(xs.index(xk)) if xk in xs else xs   # not k itself
            if (_supported(number(n), N.decimals(n), allowed, False)        # k a total written with its arithmetic
                    and _derived(xk, N.decimals(k), others(stated), False, others(counts))):  # ("32 + 17 + 75 = 124 of 229")
                continue
            unsupported.append(m.group(0))
        for k, (raw, pct, decimals, x) in enumerate(found):
            if decimals == 0 and not pct and abs(x) < rules.get("skip_integers_below", 20) and k not in measured:
                continue          # small counts and ordinals
            if raw in in_pairs and not pct:
                continue          # read with its pair
            total += 1
            if _supported(x, decimals, allowed, pct):
                names = (set(_NAMES.findall(sentence)) & set().union(*(t for t, _ in named_lines()))) if tight else ()
                if names and not _supported(x, decimals, asked, pct) and not on_a_line_naming(x, decimals, pct, names):
                    unsupported.append(raw + ("%" if pct else ""))   # shown, but not where what it is about is
                continue
            if rules.get("derived", True) and _derived(x, decimals, stated, pct, counts):
                continue
            unsupported.append(raw + ("%" if pct else ""))
    return unsupported, total


# the names a line or a sentence gives what a number is about: a zone id or a curve's mnemonic; a table's rule row
_NAMES = re.compile(r"\b(?:Z\d+|[A-Z][A-Z0-9_]{1,})\b")
_RULE = re.compile(r"^\s*\|[-:| ]+\|\s*$")

# a unit right after a number: the number is a measure (a thickness, a depth, a value), not a count or an ordinal
_UNIT_AFTER = re.compile(r"\s?(?:m|ft|feet|metres?|meters?|mD|md|API|ohm\.?m|g/cm3|g/cc|v/v|us/ft|°F|degF|ppm)\b")


def _lines_of(e) -> list:
    """A result's lines as the checker reads its values: every row of a ledger item (a direct question's writer reads
    results whole, beyond the text a step was shown; the item's values are all its rows' numbers), else its text."""
    rows = getattr(getattr(e, "item", None), "rows", None)
    return [ln for ln, _ in rows] if rows else e.render().splitlines()


# "k of N", "k out of N", "k/N": a count stated with its population ("658 of 848" where no result
# shows 658 with 848)
_PAIR = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?:of|out of|/)\s*(?:the\s+|all\s+)?"
                   r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\d.]*\d)", re.I)


def availability_issues(text: str, view: FormationView, reg) -> list[str]:
    """V4, clause by clause and only about calibrated porosity/permeability: a denial of PHIE_CC/PERM_CC that exist
    where it speaks (the curves it names, in the zones it names), or a use of ones that do not exist. At most one
    message; a conditional ('where PHIE_CC is missing', a fallback) states coverage and is not a denial."""
    low = text.lower()
    has_core = view.available("PHIE_CC") or view.available("PERM_CC")
    negated, about_poroperm = reg.pattern("availability", "negated"), reg.pattern("availability", "about_poroperm")
    denial, hypo = reg.pattern("availability", "denial"), reg.pattern("availability", "hypothetical")
    calibrated = reg.pattern("availability", "calibrated_curve")

    def core_where_said(sentence: str) -> bool:
        """The core-corrected curves a denial is about exist where it speaks: the ones it names (else either), in the
        zones it names (else anywhere in the interval). A curve absent from a named zone may be called absent there."""
        named = [c for c in ("PHIE_CC", "PERM_CC") if c.lower() in sentence] or ["PHIE_CC", "PERM_CC"]
        zones = [z for z in view.zones if re.search(rf"\b{re.escape(z.zone_id.lower())}\b", sentence)]
        for c in named:
            if not zones and view.available(c):
                return True
            for z in zones:
                v = view.zone_values(z, c)
                if v is not None and np.isfinite(v).any():
                    return True
        return False

    for sentence in re.split(r"(?<=[.!?])\s+|\n+|;\s*|:\s+", low):    # clauses; each line (a table row) on its own
        hypothetical = hypo.search(sentence)
        if has_core and denial.search(sentence) and about_poroperm.search(sentence) and not hypothetical \
                and core_where_said(sentence):
            supplied = [c for c in ("PHIE_CC", "PERM_CC") if c in set(view.prep.input_curves) and view.available(c)]
            origin = ("supplied in the LAS as core-corrected values" if supplied
                      else "calibrated on core from this well")              # as the card's core fact
            return ["WHAT: the answer says core-calibrated porosity/permeability is unavailable. WHY: PHIE_CC/PERM_CC "
                    f"exist in this interval ({origin}; see the card). FIX: report the "
                    "core-calibrated values from the evidence and label them as such. Statements about core plugs "
                    "inside the interval may stay."]
        if not has_core and calibrated.search(sentence) and not negated.search(sentence):
            return ["WHAT: the answer cites PHIE_CC/PERM_CC. WHY: no core-calibrated curves exist in this interval. "
                    "FIX: use the log-derived PHIE/PERM and state that core calibration is not available."]
    return []


def data_denials(text: str, view: FormationView) -> list[str]:
    """V9: data said to be missing while the interval has it (rules/checks.yaml data_denials)."""
    out = []
    for name, entry in (view.reg.checks.get("data_denials") or {}).items():
        present = [c for c in entry.get("curves", []) if view.available(c)]
        m = re.search(entry["pattern"], text, re.I) if present else None
        if m:
            out.append(f"WHAT: the answer says '{m.group(0)}', but this interval has {', '.join(present)}. WHY: the card "
                       f"lists the {name} curves present here and how they were used. FIX: use them as the card describes, "
                       "and say only what is actually missing.")
    return out
