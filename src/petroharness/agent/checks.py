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

_NUM = re.compile(r"(?<![A-Za-z_\d.])(-?\d+(?:\.\d+)?)(\s*%|\s+percent\b)?", re.I)
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
        for m in _NUM.finditer(ascii_minus(e.render())):
            vals.append(float(m.group(1)))
    for m in _NUM.finditer(card):
        vals.append(float(m.group(1)))
    for m in _NUM.finditer(question):
        vals.append(float(m.group(1)))
        if m.group(2):
            vals.append(float(m.group(1)) / 100)
    return np.unique(np.asarray(vals, dtype=float))


def _supported(x: float, decimals: int, allowed: np.ndarray, percent: bool) -> bool:
    """x matches an allowed value at x's displayed precision, directly or as a fraction shown in percent; a percentage
    also as the complement of a shown share (100 - p, or 100 x (1 - f): the share that is not), recomputed here."""
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    if np.any(np.abs(allowed - x) <= tol):
        return True
    if not percent:
        return False
    frac, pct = allowed[(allowed >= 0) & (allowed <= 1)], allowed[(allowed >= 0) & (allowed <= 100)]
    return bool(np.any(np.abs(allowed * 100 - x) <= tol)                 # a fraction written as a percentage
                or np.any(np.abs(100 * (1 - frac) - x) <= tol) or np.any(np.abs(100 - pct - x) <= tol))


def _derived(x: float, decimals: int, stated: list[float]) -> bool:
    """x is a difference, sum, ratio or percentage difference of two supported numbers stated in the same sentence
    (the answer shows its inputs, so the arithmetic is checkable)."""
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    for i, a in enumerate(stated):
        for b in stated[i + 1:]:
            cands = [abs(a - b), a + b]
            for num, den in ((a, b), (b, a)):
                if den:
                    cands += [num / den, 100 * abs(num - den) / abs(den)]
            if any(abs(c - x) <= tol for c in cands):
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


def number_provenance(text: str, card: str, evidence: list[Evidence], checks: dict | None = None,
                      wells: Iterable[str] = (), question: str = "") -> tuple[list[str], int]:
    """(unsupported numbers, numbers checked). The names in `wells` (the task's well) and the checks' `ignore`
    patterns are removed first: they contain digits but are not numbers. Numbers the question states are supported
    (checks numbers.question), and so count as inputs of a derived number in the same sentence."""
    rules = (checks or {}).get("numbers", {})
    text, card, question = ascii_minus(text), ascii_minus(card), ascii_minus(question)
    for pattern in filter(None, map(well_name_pattern, wells)):
        question = pattern.sub(" ", question)
    allowed = _allowed_numbers(card, evidence, question if rules.get("question", True) else "")
    clean = strip_citations(text)
    for pattern in filter(None, map(well_name_pattern, wells)):
        clean = pattern.sub(" ", clean)
    for pat in rules.get("ignore", []):
        clean = re.sub(pat, " ", clean)
    unsupported, total = [], 0
    for sentence in re.split(r"(?<=[.;!?])\s+|\n", clean):
        found = []
        for m in _NUM.finditer(sentence):
            raw, pct = m.group(1), bool(m.group(2))
            decimals = len(raw.split(".")[1]) if "." in raw else 0
            found.append((raw, pct, decimals, float(raw)))
        stated = [x for _, pct, d, x in found if _supported(x, d, allowed, pct)]
        for raw, pct, decimals, x in found:
            if decimals == 0 and not pct and abs(x) < rules.get("skip_integers_below", 20):
                continue          # small counts and ordinals
            total += 1
            if _supported(x, decimals, allowed, pct):
                continue
            if rules.get("derived", True) and _derived(x, decimals, stated):
                continue
            unsupported.append(raw + ("%" if pct else ""))
    return unsupported, total


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
