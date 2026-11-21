"""One grammar for a number written in text, a result's or a model's: every reader of written numbers reads them here
(the number checker, the ledger's shown values and calc, the claims, the writer's line lookup, a table cell).

    20,700      one number (a thousands separator written); "21,22" and "21, 22" stay two
    -0.02       signed; in "2841-2865" the minus after a digit is a dash: two positive numbers
    1.5e-3      an exponent
    12.5 %      a percentage (NUM's second group)
    R43, Z3, E12, SW_ARCHIE_A1   names: a digit after a letter or underscore starts no number
    90th, 1st   ordinals: a rank, not a value ("the 90th percentile")
"""
import re
from functools import lru_cache

NUM = re.compile(r"(?<![A-Za-z_\d.])(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?)(?!\d|(?:st|nd|rd|th)\b)"
                 r"(\s*%|\s+percent\b)?", re.I)
# what stands right before a number that makes it a band's edge or a subtrahend: "PHIN - 0.02", "± 2", "+/- 2"
_BAND = re.compile(r"(?:[\w)\]]\s+-\s*|±\s*|\+/-\s*)$")


def number(raw: str) -> float:
    """A number as written ("20,700", "-0.02", "1.5e-3") as its value."""
    return float(str(raw).replace(",", ""))


def decimals(raw: str) -> int:
    """The digits written after the decimal point ("0.210" 3, "20,700" 0, "1.5e-3" 4: the value's own decimals)."""
    s = str(raw).replace(",", "").lower()
    mant, _, exp = s.partition("e")
    k = len(mant.split(".")[1]) if "." in mant else 0
    return max(0, k - int(exp or 0))


def half_unit(raw: str) -> float:
    """Half the unit of a number's last written digit: the rounding a value written so can hide ('0.21' 0.005)."""
    return 0.5 * 10 ** (-decimals(raw))


def first(text: str):
    """The first number a text writes, as written (None when it writes none)."""
    m = NUM.search(str(text or ""))
    return m.group(1) if m else None


def values(text: str) -> list:
    """Every number a text writes, as values."""
    return [number(m.group(1)) for m in NUM.finditer(str(text or ""))]


def shown_values(text: str) -> list:
    """The values a text shows: each number, and the negative of one shown as a band's edge or after a binary minus
    ("PHID < PHIN - 0.02" shows the band -0.02 too; "mean +/- 2 std")."""
    return list(_shown(str(text or "")))


@lru_cache(maxsize=8192)
def _shown(text: str) -> tuple:
    """shown_values of one text, once: a result's text is fixed once opened, and the claim check reads every result
    for every number it flags (uncached, a claim took 0.1 s on a well of 84 results)."""
    out = []
    for m in NUM.finditer(text):
        v = number(m.group(1))
        out.append(v)
        if v > 0 and _BAND.search(text[max(0, m.start() - 12):m.start()]):
            out.append(-v)
    return tuple(out)


# --- numbers written in words ------------------------------------------------------------------------------------------
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
_NUMBER_WORD = "|".join(sorted(list(_UNITS) + list(_TENS) + list(_SCALES) + ["point", "and"], key=len, reverse=True))
_SPELLED = re.compile(rf"\b(?:{_NUMBER_WORD})(?:[\s-]+(?:{_NUMBER_WORD}))*\b", re.I)


def _spelled_value(words: list) -> "str | None":
    """The number a run of number words writes, as digits: "seven hundred sixty-eight" 768, "two thousand eight hundred
    forty-one" 2841, "one hundred sixteen point nine" 116.9, and a depth or a year said in pairs, "twenty-four forty-one"
    2441; None when the run is no number ("and" alone)."""
    words = [w.lower() for w in words if w.lower() != "and"]
    if not words:
        return None
    if "point" in words:
        i = words.index("point")
        whole, frac = words[:i], words[i + 1:]
        if not frac or any(w not in _UNITS or _UNITS[w] > 9 for w in frac):
            return None
        head = _spelled_value(whole) if whole else "0"
        return None if head is None else head + "." + "".join(str(_UNITS[w]) for w in frac)
    chunks, total, cur, pair = [], 0, 0, False
    for w in words:
        if w in _UNITS:
            if cur % 10 or (cur >= 10 and cur < 20) or (w in _UNITS and _UNITS[w] >= 10 and cur % 100):
                if cur and cur < 100 and not total:      # a new pair after a whole one ("forty-one" after "twenty-four")
                    chunks.append(cur)
                    cur, pair = 0, True
            cur += _UNITS[w]
        elif w in _TENS:
            if cur % 100 >= 10 or (cur and cur % 100 == 0 and cur < 100):
                if cur < 100 and not total:
                    chunks.append(cur)
                    cur, pair = 0, True
            cur += _TENS[w]
        elif w == "hundred":
            cur = (cur or 1) * 100
        else:
            total += (cur or 1) * _SCALES[w]
            cur = 0
    if pair:
        chunks.append(cur)
        return "".join(f"{c:02d}" if k else str(c) for k, c in enumerate(chunks))
    return str(total + cur)


def spelled_as_digits(text: str) -> str:
    """The text with numbers written in words as digits, so the checker reads them as it reads digits (question suite
    P7: an answer wrote a top "twenty-four forty-one metres", 2441 where the record shows 2841, and no check saw it).
    A run worth less than 20 stays a word (a count; the checker skips those)."""
    def convert(words: list) -> str:
        v = _spelled_value(words)
        return v if v is not None and (float(v) >= 20 or "." in v) else " ".join(words)

    def one(m):
        words, parts, cur = re.split(r"[\s-]+", m.group(0)), [], []
        for k, w in enumerate(words):                  # "and" joins only after a scale ("one hundred and twenty");
            if w.lower() == "and" and not (k and words[k - 1].lower() in _SCALES):   # "twenty and thirty" is two
                parts.append(convert(cur) if cur else "")
                parts.append("and")
                cur = []
            else:
                cur.append(w)
        parts.append(convert(cur) if cur else "")
        return " ".join(p for p in parts if p)
    return _SPELLED.sub(one, str(text or ""))

