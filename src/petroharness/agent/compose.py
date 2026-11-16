"""The answer's assembly: citations stripped, the zone table (src/petroharness/agent/writer.py) placed in the draft."""

from __future__ import annotations

import re

# Citations are delivery scaffolding: models write them in many forms ([E1], [E1, E4], [E1/E7], [E1-E5], (E3),
# (E2, E3), [E1 card], bare E5) and sometimes leak notes into them ([E6? no, card]). All of them are removed.
_CITE_TOKEN = r"(?:E\d+|formation card|card)"
_CITE_SEP = r"(?:\s*(?:,|;|/|&|\+|-|–|—|\band\b|\bto\b)\s*|\s+)"
_PAREN_CITATION = re.compile(rf"\s?\(\s*{_CITE_TOKEN}(?:{_CITE_SEP}{_CITE_TOKEN})*\s*\)", re.I)
_SQUARE_CITATION = re.compile(r"\s?\[[^\[\]\n]{0,80}?\bE\d+\b[^\[\]\n]{0,80}?\]|\s?\[\s*(?:formation card|card)\s*\]", re.I)
_BARE_RANGE = re.compile(r"\s?(?<![\w\[(])E\d{1,3}\s*(?:-|–|—|/|,|\bto\b)\s*E\d{1,3}(?!\w|\.\d)")
_BARE_ID = re.compile(r"\s?(?<![\w\[(./-])E\d{1,3}(?!\w|\.\d)")
_CITATION = re.compile(r"\[E\d+|\(E\d+|(?<![\w./-])E\d{1,3}(?!\w)")
# a result named as the owner of what it shows ("from E5's zone means"): the id goes, and the sentence keeps a
# determiner ("from the zone means"), not a stranded possessive ("from's zone means")
_ID_POSSESSIVE = re.compile(r"(?<![\w\[./-])E\d{1,3}['’]s\b")

# A chain of ids, which goes as one: E2/E5, E1//E4, E3-E7, E2, E4 and E9; a claim id or the map's name joined to an id
# by a slash (C8b/E7, E1/Map) belongs to it (a claim id alone is no citation: C1-C5 also name the mud gases).
_ID = r"E\d{1,3}"
_JOIN = r"(?:\s*(?:/{1,2}|,|;|&|\+|-|–|—)\s*|\s+(?:and|or|to)\s+|\s+)"
_TAG = r"(?:C\d+[a-z]?|(?i:map))"
_CHAIN = rf"(?:{_TAG}\s*/\s*)*{_ID}(?:{_JOIN}{_ID})*(?:\s*/\s*{_TAG})*(?!\w|\.\d)"
_CHAIN_AT = re.compile(rf"(?<![\w\[(./-]){_CHAIN}")
_ANY_ID = re.compile(rf"(?<![\w.-]){_ID}(?!\w|\.\d)")
# an id opening a bold label ("**E4 carbonate analysis**"): the space after it goes with it
_BOLD_CHAIN = re.compile(rf"(?<=\*\*){_CHAIN}[ \t]+(?=\w)")
# "Result E3 shows": the result named by its id
_RESULT_ID = re.compile(rf"\b([Rr]esult)(s?)\s+(?:{_CHAIN})")
# a bracket that holds an id beside other text: "(E10, n = 161)", "(E12: R² 0.91 at zone level)", "(see C8b/E7)",
# "[E8 pooled n=772, slope ≈17]" (a short square bracket with an id is a citation: _SQUARE_CITATION)
_PAREN_GROUP = re.compile(r"([ \t]?)\(([^()\[\]\n]{0,300})\)")
_SQUARE_GROUP = re.compile(r"([ \t]?)\[([^\[\]\n]{0,400})\]")
_LEAD = re.compile(rf"^\s*{_CHAIN}(?:\s*[,;:]\s*|\s*[–—]\s+|\s+|$)")
_LEAD_NOUN = re.compile(rf"^\s*({_CHAIN})(?=[ \t]+\w)")
_TRAIL = re.compile(rf"(?:\s*[,;:/]\s*|\s+[–—-]\s*|\s+)?{_CHAIN}\s*$")
# What remains of a citation that only names a part of what the writer was shown (writer.prompt's sections: THE MAP,
# WHAT THE CURVES ARE, the LIMITS by point, the RESULTS; the workflow's record, the card) means nothing to a reader: it
# goes with the id. A remainder that says something ("n = 161") stays.
_SCAFFOLD = re.compile(r"(?:(?:see|per|cf\.?|from|in|via|by|also|and|vs\.?)\s*)?(?:the\s+)?(?:(?:workflow\s+)?map|workflow|"
                       r"(?:method\s+|step\s+|workflow\s+|map\s+)?records?|what the curves are|curve descriptions?|"
                       r"(?:point\s*\d+\s*)?limits?(?:\s*point\s*\d+)?|"
                       r"results?|(?:formation\s+)?card)?", re.I)
# those sections named in the writer's own capitals, with no id: "(WHAT THE CURVES ARE, MAP)", "(ZONE_TABLE,)"
_SECTION_REF = re.compile(r"[ \t]?\((?:[ \t]*(?:THE MAP|MAP|WHAT THE CURVES ARE|THE ZONE TABLE|ZONE_TABLE|RESULTS|LIMITS)"
                          r"[ \t]*[,;/]?)+[ \t]*\)")
# An id that is the noun of its phrase ("of E6 alone", "I use E10 for", "in E3 (criterion ...)", "E4 labels Z2")
# becomes "the result": deleting it would leave "of alone". An id that qualifies a noun ("the E7 zone contrast") or
# cites a sentence ("per 10 m of depth E5.") is deleted as before. The noun is known by the word before it (a
# preposition, a determiner, a conjunction, a verb that takes an object, or the start of a sentence or an item) and
# what follows it (punctuation, a bracket, or a word that cannot be the noun it qualifies).
_BEFORE_NOUN = frozenset(
    "of in on from by with for to into per via than between across within under over at as like vs versus "
    "and or but because since whereas although though while if when where whether "
    "use uses used using see read reads follow follows following cite cites trust favour favor prefer "
    "take takes check checks".split())
_DETERMINERS = frozenset("the a an this that these those its their each every any".split())
_NOUN_FOLLOWERS = (
    r"for|alone|and|or|but|vs\.?|versus|is|are|was|were|has|have|had|does|did|can|cannot|could|would|will|may|might|"
    r"must|should|also|only|itself|here|there|above|below|which|that|where|when|while|because|so|then|now|still|"
    r"again|already|never|not|with|without|in|on|at|by|from|of|to|into|over|under|between|across|within|than|as|if|"
    r"shows?|showed|gives?|gave|lists?|listed|reports?|reported|states?|stated|returns?|returned|records?|recorded|"
    r"puts?|places?|placed|finds?|found|covers?|counts?|marks?|marked|labels?|labell?ed|flags?|flagged|classifies|"
    r"classified|computes?|computed|uses?|used|reads?|holds?|held|carr(?:y|ies|ied)|confirms?|confirmed|says|"
    r"leaves?|left|treats?|sets?|takes?|keeps?|excludes?|includes?|applies|applied|assigns?|defines?|derives?|"
    r"yields?|provides?|indicates?|suggests?|supports?|agrees?|matches|contains?|describes?|measures?|caps?|"
    r"supply|supplies|supplied|show")
_AFTER_NOUN = re.compile(rf"(?:\*\*|__)?\s*(?:[.,;:!?)\]]|$|\(|(?:{_NOUN_FOLLOWERS})\b)", re.I)
# a chain's tail after a slash, which older code left when it removed the chain's head (";/E9 show", "the/E11"):
# the slash becomes a space and the id is read where it stands (not after a claim id or the map: "C8b/E7" is a chain)
_SLASH_TAIL = re.compile(rf"(?<=\S)(?<!C\d)(?<!C\d\d)(?<!C\d[a-z])(?<!C\d\d[a-z])(?<![Mm]ap)(?<!MAP)/(?={_ID}(?!\w|\.\d))")
# a bracketed id after a word that takes a noun ("Per [E2] and [E4], ...", "class shares from [E3];", "noted in (E13)")
# is that noun: its brackets go first, and the noun rule reads it
_PREP = (r"of|in|on|from|by|per|with|to|see|than|as|between|into|via|under|over|across|within|at|like|vs|versus|"
         r"use|uses|using|read|reads|cite|cites|following")
_BRACKET_NOUN = re.compile(rf"\b({_PREP})[ \t]+[\[(][ \t]*({_CHAIN})[ \t]*[\])]", re.I)
_BRACKET_AND = re.compile(rf"({_ID})[ \t]+(and|or)[ \t]+[\[(][ \t]*({_CHAIN})[ \t]*[\])]")
_TRAIL_NOUN = re.compile(rf"\b([A-Za-z]+)[ \t]+({_CHAIN})\s*$")
_AFTER_WORD = re.compile(rf"[ \t]+(?:{_NOUN_FOLLOWERS})\b", re.I)


def _possessive(m: re.Match) -> str:
    before = m.string[:m.start()].rstrip(" \t*_")
    return "The" if not before or before[-1] in ".!?:\n" or before.endswith("- ") else "the"


def _starts(before: str) -> bool:
    """Whether a word placed after `before` opens a sentence, a line, a list item or a bold label."""
    b = before.rstrip(" \t")
    if re.search(r"(?:^|(?<=\s))(?:\*\*|__)$", b):                     # an opening bold marker
        b = b[:-2].rstrip(" \t")
    return not b or b[-1] in ".!?:\n" or bool(re.search(r"(?:^|\n)[ \t]*(?:[-*+]|\d+[.)])$", b))


def _noun(chain: str, before: str, start: str) -> str:
    many = len(_ANY_ID.findall(chain)) > 1
    noun = "results" if many else "result"
    prev = re.search(r"([A-Za-z]+)[ \t]*$", before)
    if prev and prev.group(1).lower() in _DETERMINERS:
        return noun
    if _starts(before):
        return start + noun
    if re.search(r";[ \t]*$", before):                       # a clause after a semicolon: its subject
        return "the " + noun
    if prev and prev.group(1).lower() in _BEFORE_NOUN:
        return "the " + noun
    return ""


def _as_noun(m: re.Match) -> str:
    """An id chain: "the result(s)" where it is its phrase's noun, else "" (it qualifies, labels or cites)."""
    s, before = m.string, m.string[:m.start()]
    after = s[m.end():]
    if _starts(before) and re.match(r"(?:\*\*|__)?[ \t]*:(?:\*\*|__)?\s", after):   # a label: "- **E3/E4**: Deviation"
        return ""
    if not _AFTER_NOUN.match(s, m.end()):
        return ""
    return _noun(m.group(0), before, "The ")


def _result_id(m: re.Match) -> str:
    """ "Result E3 shows" -> "The result shows"; "the result E3" -> "the result" """
    before = m.string[:m.start()]
    if re.search(r"\b(?:the|a|this|that|each)[ \t]+$", before, re.I):
        return m.group(1) + m.group(2)
    return ("The " if _starts(before) else "the ") + "result" + m.group(2)


def _ids_out(text: str) -> str:
    """The ids of a stretch of text: nouns named "the result", the rest deleted."""
    text = re.sub(rf"(\*\*|__)[ \t]*({_CHAIN})[ \t]*\1(?![*_])", r"\2", text)   # "**E5** reports": no bold for an id
    text = _SLASH_TAIL.sub(" ", text)
    text = re.sub(rf"(?<![\w\[(./-]){_CHAIN}-(?=[a-z])", "", text)              # "E19-consistent" -> "consistent"
    text = _BOLD_CHAIN.sub(lambda m: (n + " ") if (n := _as_noun(m)) else "", text)
    text = _CHAIN_AT.sub(_as_noun, text)
    text = _BARE_RANGE.sub("", text)
    return _BARE_ID.sub("", text)


def _group(m: re.Match, close: str = ")") -> str:
    """A bracket holding an id: the citation at its opening or close goes, a scaffold label with it; what it says
    stays, in a parenthesis ("(E10, n = 161)" -> "(n = 161)"); an id opening it as a noun stays a noun ("(E8 lists
    ...)" -> "(the result lists ...)"); emptied, it goes."""
    inner = m.group(2)
    if not _ANY_ID.search(inner):
        return m.group(0)

    def tidy(x: str) -> str:
        x = _SLASH_TAIL.sub(" ", x)
        t = _TRAIL_NOUN.search(x)
        if t and t.group(1).lower() in _BEFORE_NOUN - {"and", "or"}:         # "(fallback noted in E13)": its noun
            x = x[:t.start(2)] + _noun(t.group(2), "", "the ").replace("The ", "the ")
        x = _ids_out(_TRAIL.sub("", x))
        x = re.sub(r"^\s*(?:[,;:/&+]|[–—-](?=\s|$))+\s*|\s*(?:[,;:/&+]|(?<=\s)[–—-])+\s*$", "", x)
        return re.sub(r"[ \t]{2,}", " ", x).strip()

    rest = tidy(_LEAD.sub("", inner))
    if all(_SCAFFOLD.fullmatch(p.strip()) for p in re.split(r"[,;/]", rest)):    # "(E9 record)": a label
        return ""
    lead = _LEAD_NOUN.match(inner)
    if lead and _AFTER_WORD.match(inner, lead.end()):                          # "(E8 lists ...)": its subject
        rest = tidy(_noun(lead.group(1), "", "the ") + inner[lead.end():])
    return m.group(1) + "(" + rest + ")"


def strip_citations(text: str) -> str:
    out = _ID_POSSESSIVE.sub(_possessive, text)
    out = _RESULT_ID.sub(_result_id, out)
    out = _BRACKET_NOUN.sub(r"\1 \2", out)
    out = _BRACKET_AND.sub(r"\1 \2 \3", out)
    out = _SQUARE_CITATION.sub("", out)
    out = _SQUARE_GROUP.sub(_group, out)
    out = re.sub(rf"[ \t]?\[[ \t]*{_CHAIN}[^\[\]\n]*(?=\n|$)", "", out)   # a square bracket never closed: "[E1,"
    out = _PAREN_CITATION.sub("", out)
    out = _PAREN_GROUP.sub(_group, out)
    out = _SECTION_REF.sub("", out)
    out = re.sub(rf"\((?:[ \t]*{_CHAIN})(?:[ \t]*[,;:][ \t]*|[ \t]+)(?=\S)", "(", out)   # opening a nested parenthesis
    out = _ids_out(out)
    out = re.sub(r"(?:^|(?<=\s))(\*\*|__)[ \t]*[:;,.]?[ \t]*\1(?![*_])", "", out, flags=re.M)   # "**E3/E4**" emptied
    out = re.sub(r"(^|\n)([ \t]*(?:[-*+]|\d+[.)])[ \t]+)(?::|[–—])[ \t]*", r"\1\2", out)   # "- : Deviation", "- — Zone"
    out = re.sub(r"[ \t]+([.,;:])", r"\1", out)          # "value [E1]." -> "value."
    out = re.sub(r",(?:[ \t]*,)+", ",", out)                # "[E1], [E2], [E3]" left ",,"
    out = re.sub(r",[ \t]*(?=[.;:!?])", "", out)             # "value [E1], [E2]." -> "value."
    out = re.sub(r",[ \t]*(?=\|(?:[ \t]|$))", " ", out, flags=re.M)   # "inverted, |": a table cell's end
    out = re.sub(r"[ \t]*[,;][ \t]*\)", ")", out)            # "(n = 18, E4)" -> "(n = 18)", not "(n = 18,)"
    out = re.sub(r"[ \t]+\([ \t]*\)", "", out)               # "value (E4)." emptied: "value."
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def leftover_citations(text: str) -> list[str]:
    """Evidence ids still present after stripping (render check)."""
    return _CITATION.findall(text)


ZONE_TABLE_TOKEN = "{{ZONE_TABLE}}"


def compose(draft: str, table: str) -> str:
    """Replace the table token; if the writer omitted it, place the table after the first section, or at the end
    of an answer without sections."""
    if not table:
        return draft.replace(ZONE_TABLE_TOKEN, "").strip()
    if ZONE_TABLE_TOKEN in draft:
        return draft.replace(ZONE_TABLE_TOKEN, table, 1).replace(ZONE_TABLE_TOKEN, "")
    parts = draft.split("\n## ")
    if len(parts) >= 3:
        return parts[0] + "\n## " + parts[1].rstrip() + "\n\n" + table + "\n\n## " + "\n## ".join(parts[2:])
    return draft.rstrip() + "\n\n" + table
