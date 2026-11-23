"""What a question names, read through the catalog's vocabulary, and what of it this well's record lacks.

The vocabulary is the curve registry's (resources/rules/curves.yaml): the curve mnemonics it lists, `synonyms`,
`question_terms` and `named_measurements`. A name stands for the curves the vocabulary gives it; it is named but not in
this well's record when none of those curves has data in the interval. The names come from the READ call's `named`
list (the model's reading of the question) and from the question's own words.

This is the one place where code reads the question's words, and it reads them only as vocabulary: no rule here
depends on how a question is phrased (docs/DESIGN.md, G4).
"""
from __future__ import annotations

import re

CAPS = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]+(?![A-Za-z0-9_])")      # a word in capitals: a mnemonic as written
NAME_CHARS = 80                                                            # a name as the note shows it


def _phrase(phrase: str) -> re.Pattern:
    """A phrase as whole words, any case."""
    return re.compile(rf"(?<![a-z0-9_]){re.escape(phrase.lower())}(?![a-z0-9_])")


def written(text: str, names) -> list:
    """The names (mnemonics) the text writes as whole words, as written (case kept), in the names' order."""
    return [c for c in names if re.search(rf"(?<![A-Za-z0-9_]){re.escape(str(c))}(?![A-Za-z0-9_])", str(text or ""))]


def mnemonics(reg: dict) -> set:
    """Every curve mnemonic the registry names (its inventory, families, flags, core curves, meanings, synonyms, named
    measurements and the mnemonics of its question terms), in capitals."""
    families = reg.get("families") or {}
    inv, core = reg.get("inventory") or {}, reg.get("core") or {}
    out = set(inv.get("raw") or []) | set(inv.get("derived") or []) | set(reg.get("flags") or [])
    out |= set(core.get("curves") or []) | set(reg.get("meanings") or {}) | set(reg.get("synonyms") or {})
    out |= {c for members in families.values() for c in members}
    out |= {c for members in (reg.get("named_measurements") or {}).values() for c in members}
    out |= {c for tokens in (reg.get("question_terms") or {}).values() for c in tokens
            if c != "measured" and c not in families}
    return {str(c).upper() for c in out}


def _tokens(tokens, reg: dict) -> list:
    """A question term's curve tokens as mnemonics: a family name stands for its members, "measured" for every
    family's."""
    families = reg.get("families") or {}
    out = []
    for c in tokens:
        out += ([m for ms in families.values() for m in ms] if c == "measured" else list(families.get(c) or [c]))
    return out


def _measurement(key: str) -> str:
    """A named measurement's name as a question writes it: its key before the parenthesis."""
    return key.split(" (")[0].strip()


def _matches(text: str, reg: dict, known_upper: set) -> list:
    """(start, end, name as written, curves) for each name the text writes, in its order: a mnemonic in capitals (one
    of `known_upper`), a synonym, a question term, a named measurement. Where two names overlap, the longer is the one
    written ("shear sonic", not "sonic"; "spectral gamma ray", not "gamma ray"); two names on the same words join
    their curves."""
    low = text.lower()
    found = [(m.start(), m.end(), [m.group(0)]) for m in CAPS.finditer(text) if m.group(0) in known_upper]
    for c, words in (reg.get("synonyms") or {}).items():
        found += [(m.start(), m.end(), [c]) for w in words for m in _phrase(w).finditer(low)]
    for term, tokens in (reg.get("question_terms") or {}).items():
        found += [(m.start(), m.end(), _tokens(tokens, reg)) for m in _phrase(term).finditer(low)]
    for key, members in (reg.get("named_measurements") or {}).items():
        found += [(m.start(), m.end(), list(members)) for m in _phrase(_measurement(key)).finditer(low)]
    keep = []
    for a, b, curves in sorted(found, key=lambda x: (x[0] - x[1], x[0])):         # the longest first
        same = next((k for k in keep if (k[0], k[1]) == (a, b)), None)
        if same is not None:
            same[2] += [c for c in curves if c not in same[2]]
        elif not any(a < k[1] and k[0] < b for k in keep):
            keep.append([a, b, list(curves)])
    return [(a, b, text[a:b], curves) for a, b, curves in sorted(keep)]


def resolve(name, reg: dict, known=()) -> list:
    """The curves a name stands for: a mnemonic (the registry's, or one of `known`) that is the whole name (any case);
    else the curves of the names it writes (_matches: mnemonics in capitals, synonyms, question terms, named
    measurements), in its order."""
    text = str(name or "").strip()
    have = {str(c).upper(): c for c in known}
    known_upper = mnemonics(reg) | set(have)
    out = [text.upper()] if text.upper() in known_upper else []
    for _, _, _, curves in _matches(text, reg, known_upper):
        out += curves
    return list(dict.fromkeys(have.get(str(c).upper(), str(c).upper()) for c in out))


def in_text(text: str, reg: dict, known=()) -> list:
    """The names a text writes, in its order, each with the curves it stands for (_matches)."""
    known_upper = mnemonics(reg) | {str(c).upper() for c in known}
    return [(name, curves) for _, _, name, curves in _matches(str(text or ""), reg, known_upper)]


def named(s) -> list:
    """What the question names, each with the curves it stands for: the READ call's `named` list, then the question's
    own vocabulary. Names the vocabulary does not know are left out."""
    reg, known = s.f.view.reg.curves, list(s.f.inv.curves)
    items = [(str(n).strip(), resolve(n, reg, known)) for n in (getattr(s, "reading", None) or {}).get("named") or []]
    items += in_text(s.task.question, reg, known)
    return [(n, c) for n, c in items if n and c]


def absent(s) -> list:
    """The named items none of whose curves has data in this interval, as (name, curves); one item per set of curves
    (an item whose curves another item already holds is left out)."""
    view = s.f.view
    gone = [(n, c) for n, c in named(s) if not any(view.available(x) for x in c)]
    out = []
    for i, (n, c) in enumerate(gone):
        held = any(set(c) <= set(c2) and (set(c) < set(c2) or j < i) for j, (_, c2) in enumerate(gone) if j != i)
        if not held:
            out.append((n, c))
    return out


def note(s) -> str:
    """The lines under QUESTION (C10): "Named but not in this well's record: <name> (<curves>); ..." for the named
    items whose curves the record does not hold, and "Named, in this well's record but with no values in this
    interval: <name> (<curve>: what the range screening removed)" for those it holds without a value here (question
    DTC, held and screened out here, was said to be not in the record, and the answer said the well had no
    sonic log). A quantity the workflow derives (the catalog's derived curves) also names the Petrophys functions that
    may compute it (library.api.computes), so the model reaches for them before saying it cannot be had; empty when
    every named item has data here. The same items as data, for the answer's reader: facts()."""
    from petroharness.agent import components as C
    got = facts(s)
    out = [f for f in got if f["kind"] == "absent"]
    here = [f for f in got if f["kind"] == "empty"]
    unit = getattr(s, "unit_note", "") or ""             # a unit the tops file does not have (read.ask_back)

    def item(f):
        fns = f["computes"]
        return f"{f['name']} ({', '.join(f['curves'])}" + (f"; Petrophys may compute it: {', '.join(fns)}" if fns else "") + ")"

    def kept(f):
        return f"{f['name']} ({'; '.join(f'{x[0]}: {x[1]}' if x[1] else x[0] for x in ((c['curve'], c['why']) for c in f['curves']))})"
    lines = ([C.fill("C10", "absent_note", items="; ".join(item(f) for f in out))] if out else []) \
        + ([C.fill("C10", "empty_note", items="; ".join(kept(f) for f in here))] if here else []) \
        + ([unit] if unit else [])
    return "\n".join(lines)


def facts(s) -> list:
    """note()'s items as data, for the answer's reader (the web UI words them): {"kind": "absent", "name", "curves",
    "computes"} for a named item the record does not hold, {"kind": "empty", "name", "curves": [{"curve", "why"}]} for
    one it holds with no value in this interval, then the session's own (read.ask_back: a unit the tops file does not
    have, the user's zones with no sample here)."""
    from petroharness.well.summary import screened
    items = absent(s)
    out, here = [], []
    if items:
        view = s.f.view
        well = getattr(getattr(view, "prep", None), "well", None)
        held = {str(c).upper() for c in getattr(well, "curves", {}) or {}}
        derived = {str(c).upper() for c in ((view.reg.curves.get("inventory") or {}).get("derived") or [])}
        for n, c in items:
            if any(x.upper() in held for x in c):
                here.append({"kind": "empty", "name": n[:NAME_CHARS],
                             "curves": [{"curve": x, "why": screened(view, x) or ""} for x in c if x.upper() in held]})
                continue
            fns = []
            if {x.upper() for x in c} & derived:
                from petroharness.agent.library.api import computes
                fns = computes(n)
            out.append({"kind": "absent", "name": n[:NAME_CHARS], "curves": list(c), "computes": list(fns)})
    return out + here + list(getattr(s, "unit_facts", None) or [])