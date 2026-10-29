"""The answer's assembly: citations stripped, the zone table (src/petroharness/agent/writer.py) placed in the draft."""

from __future__ import annotations

import re

# Citations are delivery scaffolding: models write them in many forms ([E1], [E1, E4], [E1/E7], [E1-E5], (E3),
# (E2, E3), [E1 card], bare E5) and sometimes leak notes into them ([E6? no, card]). All of them are removed.
_CITE_TOKEN = r"(?:E\d+|formation card|card)"
_CITE_SEP = r"(?:\s*(?:,|;|/|&|\+|-|–|—|\band\b|\bto\b)\s*|\s+)"
_PAREN_CITATION = re.compile(rf"\s?\(\s*{_CITE_TOKEN}(?:{_CITE_SEP}{_CITE_TOKEN})*\s*\)", re.I)
_SQUARE_CITATION = re.compile(r"\s?\[[^\[\]\n]{0,80}?\bE\d+\b[^\[\]\n]{0,80}?\]|\s?\[\s*(?:formation card|card)\s*\]", re.I)
_BARE_RANGE = re.compile(r"\s?(?<![\w\[(])E\d{1,3}\s*(?:-|–|—|/|,|\bto\b)\s*E\d{1,3}(?!\w)")
_BARE_ID = re.compile(r"\s?(?<![\w\[(./-])E\d{1,3}(?![\w])")
_CITATION = re.compile(r"\[E\d+|\(E\d+|(?<![\w./-])E\d{1,3}(?!\w)")



def strip_citations(text: str) -> str:
    out = _SQUARE_CITATION.sub("", text)
    out = _PAREN_CITATION.sub("", out)
    out = _BARE_RANGE.sub("", out)
    out = _BARE_ID.sub("", out)
    out = re.sub(r"[ \t]+([.,;:])", r"\1", out)          # "value [E1]." -> "value."
    out = re.sub(r",(?:[ \t]*,)+", ",", out)                # "[E1], [E2], [E3]" left ",,"
    out = re.sub(r",[ \t]*(?=[.;:!?])", "", out)             # "value [E1], [E2]." -> "value."
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
