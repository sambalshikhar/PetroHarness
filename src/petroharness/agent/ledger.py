"""The ledger: the evidence of one question, held in full outside the model; every opened result has an id the
claims cite."""

from __future__ import annotations

import ast
import inspect
import json
import math
import re
from dataclasses import dataclass, field
from typing import Optional

from petroharness.agent.engine import CUT_GET, Formation, ToolError, max_chars
from petroharness.agent.schemas import arguments, call, fit, known_args
from petroharness.agent.toolset import TOOLS, TOOLSET

DIGEST_CHARS = 700         # an item at or below this size is its own digest
SECTION_DIGEST_CHARS = 1600  # a section's digest keeps its classes and their runs (the answer's
                             #   reading of a class section; 700 kept the header only and answers gave shares)
GET_CHARS = 6000           # one get is cut here, with how to narrow it (a tool's output is at most this: any line fits)
FIND_CHARS = 6000          # a ledger-wide find shows items up to here and names the rest
from petroharness.agent import numbers as N                                   # the one grammar for written numbers
# what a digest keeps, by priority: what the item is (its first line, each curve's label), what it adds up to, then
# how it was made
_P0 = re.compile(r"^[A-Z][A-Z0-9_]* (against|\[|=)")
_P1 = re.compile(r"^(  classes \(|  whole interval[: (]|  every sample where |  by zone mean:|  zones whose means meet it|  zones pooled[:,]|  these zones pooled[:,]|"
                 r"  all zones:|  zones asked:|  shallowest top|  highest zone by|  lowest zone by|  with depth|"
                 # a selection's lines (agent.selection) and runs' intervals (reach well)
                 r"  rows whose means meet it|  rows pooled[:,]|  these rows pooled[:,]|  by zone:|  by row:|"
                 r"  .+ \(\d+ samples outside any row\))")
_P2 = re.compile(r"^(Samples where|  method:|  basis:|  equation:|  inputs:|  curves:)")


@dataclass
class Item:
    id: str
    tool: str
    args: dict
    key: str                          # the normalized call
    rows: list                        # (line, numbers written into it)
    text: str
    numbers: list = field(default_factory=list)

    @property
    def lines(self) -> list:
        return [ln for ln, _ in self.rows]

    def call_text(self) -> str:
        """The call in one short line, for listings."""
        a = dict(self.args)
        head = a.pop("expression" if self.tool == "calc" else TOOLSET.lead(self.tool), "")     # the tool's own lead
        if self.tool == "compare":
            head = f"{head} vs {a.pop('b', '')}"
        elif self.tool == "crossplot":
            head = f"{head} on {a.pop('x', '')}"
        head = ", ".join(head) if isinstance(head, list) else str(head)
        rest = "; ".join(f"{k} {', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in a.items())
        text = f"{self.tool} {head}".rstrip() + (f" ({rest})" if rest else "")      # a tool with no lead: no gap
        return text if len(text) <= 90 else text[:87] + "..."


# --- matching (zones exact, words token-bounded) --------------------------------------------------------------------

def _word(w: str, text: str, parts: bool = False) -> bool:
    """w in text as a whole word or name; with parts, also as whole parts of a name between underscores (MOVEABLE in
    HIGH_MOVEABLE_HC, GAS_EFFECT in WEAK_GAS_EFFECT)."""
    edge = "A-Za-z0-9" if parts else "A-Za-z0-9_"
    return re.search(rf"(?<![{edge}.])" + re.escape(w) + rf"(?![{edge}])", text, re.I) is not None


def zones_in(text: str) -> set:
    """The zones a text names: Zk tokens and ranges Za-Zb (every zone of the range)."""
    out = set()
    for a, b in re.findall(r"(?<![A-Za-z0-9_])Z(\d+)\s*(?:-|–|to)\s*Z(\d+)(?!\d)", text):
        if 0 <= int(b) - int(a) < 1000:
            out |= {f"Z{i}" for i in range(int(a), int(b) + 1)}
    return out | {f"Z{int(n)}" for n in re.findall(r"(?<![A-Za-z0-9_])Z(\d+)(?![A-Za-z0-9_])", text)}


def _terms(find: str) -> tuple:
    """find -> (zones, words): zone terms (Z3, z03, Z3-Z5) and the other terms, separated by , ; or | (alternatives)."""
    zs, words = set(), []
    for t in [t.strip() for t in re.split(r"[,;|]", str(find or "")) if t.strip()]:
        if re.fullmatch(r"[Zz]\d+(?:\s*(?:-|–|to)\s*[Zz]\d+)?", t):
            zs |= zones_in(t.upper())
        else:
            words.append(t)
    return zs, words


def _blocks(lines: list) -> list:
    """[(head index, [indices])]: a block is a line that is not indented and the indented lines after it."""
    out = []
    for i, ln in enumerate(lines):
        if not ln.startswith(" ") or not out:
            out.append((i, [i]))
        else:
            out[-1][1].append(i)
    return out


_CLASS = re.compile(r"^(  [A-Z][A-Z0-9_]*(?: \([^)]*\))?: .*?; runs: )(.*)$")
_THICKEST = re.compile(r"^thickest \d+ of \d+: ")                 # a long list cut to its thickest runs
_EVERY = re.compile(r"\s*\.\.\. \(every run: condition ([^)]*)\)\s*$")   # a list cut, and the condition of every run
_CELL = re.compile(r"^(?:(Z\d+)(?: \([^)]*\))? )?(-?\d+(?:\.\d+)?)(?:-(-?\d+(?:\.\d+)?))?(?: \([^)]*\))?$")


def _class_runs(line: str, zs: set, zone_at=None) -> Optional[str]:
    """A section's class line restricted to zones: its head and only the runs in those zones. A run is "Z2 a-b" or
    "Z2 (SAND) a-b" (a class over several zones, with its zone's rock) or "a-b" (in one zone: zone_at(depth) names
    it), with its thickness where the list is its thickest runs. "none in Z3" only where the list is whole and every
    run's zone is known; a cut list, or a run whose zone cannot be read, says its runs there are not listed, with the
    condition that lists every run (a cut list read as none would be a false absence)."""
    m = _CLASS.match(line)
    if not m:
        return None
    text = m.group(2)
    every = _EVERY.search(text)
    cut = bool(every) or bool(_THICKEST.match(text))
    keep, unread = [], False
    for cell in [c.strip() for c in re.split(r"[,;]\s*", _THICKEST.sub("", _EVERY.sub("", text))) if c.strip()]:
        hit = _CELL.match(cell)
        zone = (hit.group(1) or (zone_at(float(hit.group(2))) if zone_at else None)) if hit else None
        if zone is None:
            unread = True
        elif zone in zs:
            keep.append(cell)
    where = ", ".join(sorted(zs, key=lambda z: int(z[1:])))
    rest = f"; every run: runs {every.group(1)}" if every else ""
    if keep:
        return m.group(1) + ", ".join(keep) + (f" (the list is cut: more may be in {where}{rest})" if cut else "")
    if cut or unread:
        why = f"the list is cut{rest}" if cut else "the runs here do not name their zone"
        return m.group(1) + f"not listed here for {where} ({why})"
    return m.group(1) + f"none in {where}"


def get_lines(item: Item, find: str, parts: bool = False, zone_at=None) -> list:
    """Matching lines of one item, each block's head first for context (a curve's label above its zone rows). Zone
    terms are OR'd, word terms OR'd, the two kinds AND'd. A word naming a block's head selects its whole block; a class
    line asked by zone keeps only that zone's runs, or says it has none there. With parts (the model's get and find),
    a word that names nothing in the item whole matches whole parts of names between underscores (MOVEABLE:
    HIGH_MOVEABLE_HC), while one that does (LOW_SW) stays that name (not VERY_LOW_SW). zone_at: the zone of a depth,
    for a class's runs written without zone ids (_class_runs)."""
    zs, words = _terms(find)
    if not zs and not words:
        return []
    lines = item.lines
    loose = {w for w in words if parts and not any(_word(w, ln) for ln in lines)}
    word = lambda ln: any(_word(w, ln, w in loose) for w in words)
    where = ", ".join(sorted(zs, key=lambda z: int(z[1:])))
    out = []
    for head, idx in _blocks(lines):
        whole = bool(words) and word(lines[head])
        picked = []
        for i in idx[1:]:
            ln = lines[i]
            named = bool(words) and word(ln)
            if words and not whole and not named:
                continue
            if zs:
                cl = _class_runs(ln, zs, zone_at)
                if cl is not None:
                    if "none in" in cl and not named:
                        continue                                    # asked by zone only: a class absent there is left out
                    ln = cl
                elif not (zones_in(ln) & zs):
                    continue
            picked.append(ln)
        if picked:
            out += [lines[head]] + picked
        elif whole and not zs:
            out.append(lines[head])
        elif whole and zs:
            out += [lines[head], f"  (nothing in {where} here)"]
        elif not zs and words and word(lines[head]):
            out.append(lines[head])
    return out


MISS_NAMES = 15            # names a get that matched nothing lists
def read_as(find: str) -> str:
    """How a find was read, for a miss: its zone terms and its words."""
    zs, words = _terms(find)
    zones = ", ".join(sorted(zs, key=lambda z: int(z[1:])))
    return "read as " + "; ".join(x for x in (f"zones {zones}" if zones else "",
                                             f"words {', '.join(repr(w) for w in words)}" if words else "") if x) \
        + "; terms are separated by , ; or |, zones and words must both match, and a word matches a name or a part of one between underscores"


def _names(item: Item) -> list:
    """The names an item's lines hold: curves, classes and flags (capitals, digits and underscores), in order."""
    found = re.findall(r"(?<![A-Za-z0-9_.])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*(?![A-Za-z0-9_])", "\n".join(item.lines))
    return [n for n in dict.fromkeys(found) if len(n) > 1 and not re.fullmatch(r"Z\d+|E\d+|[A-Z]", n)]


# --- numbers --------------------------------------------------------------------------------------------------------

def shown_values(item: Item) -> list:
    """Every number the item shows: those written into its lines and those in its text (a class's run depths)."""
    return [float(x) for x in item.numbers] + N.shown_values(item.text)


def _claimed(value) -> tuple:
    """A claimed number and the half-unit of its last stated digit: '0.21' -> (0.21, 0.005); '12.3%' -> (12.3, 0.05)."""
    raw = N.first(value)
    if raw is None:
        raise ValueError(f"no number in {value!r}")
    return N.number(raw), N.half_unit(raw)


def matches(claim: float, half: float, v: float) -> bool:
    return abs(claim - v) <= half * (1 + 1e-9) + 1e-12 * max(1.0, abs(v))     # slack for float error at large values


# --- arithmetic (calc) ----------------------------------------------------------------------------------------------

_FUNCS = {"sqrt": math.sqrt, "ln": math.log, "log10": math.log10, "exp": math.exp, "abs": abs, "min": min, "max": max,
          "sum": lambda *x: sum(x), "mean": lambda *x: sum(x) / len(x)}


_ADD, _MUL = (ast.Add, ast.Sub), (ast.Mult, ast.Div, ast.Pow)
_OPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "**"}


def grouping(expr: str) -> str:
    """The expression as calc reads it, every operation inside another in brackets ("1 - 0.8626*100" ->
    "1 - (0.8626 * 100)"), when + or - meets * / or ** without brackets that show the order; "" otherwise."""
    text = expr.replace("%", "").replace("×", "*").replace("÷", "/").replace("^", "**").replace("−", "-")
    try:
        tree = ast.parse(text, mode="eval").body
    except SyntaxError:
        return ""

    def bare(n, parent) -> bool:              # a * / ** inside a + or - with no brackets of its own
        if not (isinstance(n, ast.BinOp) and isinstance(n.op, _MUL) and isinstance(parent.op, _ADD)):
            return False
        before, after = text[:n.col_offset].rstrip(), text[n.end_col_offset:].lstrip()
        return not (before.endswith("(") and after.startswith(")"))

    def show(n) -> str:
        if isinstance(n, ast.BinOp):
            side = lambda c: f"({show(c)})" if isinstance(c, ast.BinOp) else show(c)
            return f"{side(n.left)} {_OPS[type(n.op)]} {side(n.right)}"
        if isinstance(n, ast.UnaryOp):
            return f"-{show(n.operand)}" if isinstance(n.op, ast.USub) else show(n.operand)
        if isinstance(n, ast.Call):
            return f"{getattr(n.func, 'id', '')}({', '.join(show(a) for a in n.args)})"
        return ast.get_source_segment(text, n) or ""
    mixed = any(bare(c, n) for n in ast.walk(tree) if isinstance(n, ast.BinOp) for c in (n.left, n.right))
    return show(tree) if mixed else ""


def evaluate(expr: str) -> tuple:
    """(value, the numbers written in it) of + - * / ** and ( ) on numbers, with sqrt, ln, log10, exp, abs, min, max,
    sum, mean. Percent signs are dropped (12.5% is 12.5). Anything else is refused."""
    text = expr.replace("%", "").replace("×", "*").replace("÷", "/").replace("^", "**").replace("−", "-")
    if re.search(r"\blog\s*\(", text):
        raise ToolError("calc: write log10( ) or ln( ), not log( )")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise ToolError(f"calc cannot read {expr!r}: numbers with + - * / ( ) and sqrt, ln, log10, exp, abs, min, max, "
                        "sum, mean") from None
    inputs = []

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            seg = ast.get_source_segment(text, n) or repr(n.value)
            inputs.append(seg)
            return float(n.value)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            x, y = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Div) and y == 0:
                raise ToolError("calc: division by zero")
            if isinstance(n.op, ast.Pow) and abs(y) > 64:
                raise ToolError("calc: an exponent above 64")
            ops = {ast.Add: lambda: x + y, ast.Sub: lambda: x - y, ast.Mult: lambda: x * y, ast.Div: lambda: x / y,
                   ast.Pow: lambda: x ** y}
            return ops[type(n.op)]()
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
            try:
                return float(_FUNCS[n.func.id](*[ev(a) for a in n.args]))
            except (ValueError, TypeError, ZeroDivisionError, OverflowError) as e:
                raise ToolError(f"calc: {n.func.id}( ) cannot take these values ({e})") from None
        raise ToolError(f"calc cannot use {ast.get_source_segment(text, n) or type(n).__name__!r}: numbers with + - * / "
                        "( ) and sqrt, ln, log10, exp, abs, min, max, sum, mean")
    try:
        value = ev(tree)
    except OverflowError:
        raise ToolError("calc: the result is too large") from None
    if isinstance(value, complex) or not math.isfinite(value):
        raise ToolError("calc: the result is not a finite number")
    return value, inputs


# --- the ledger -----------------------------------------------------------------------------------------------------

def normalize(tool: str, args: dict) -> str:
    """One key for one call: names in capitals, lists without repeats in order, spacing collapsed, defaults written."""
    fn = TOOLS[tool]
    full = {p: q.default for p, q in inspect.signature(fn).parameters.items() if p != "f" and q.default is not q.empty}
    full.update(args)
    out = {}
    for k, v in full.items():
        if v is None:
            continue
        if k in ("curves", "zones", "statistics"):
            v = [v] if isinstance(v, str) else list(v)
            v = list(dict.fromkeys(str(x).strip().upper() if k != "statistics" else str(x).strip() for x in v))
        elif k in ("condition", "where"):
            v = re.sub(r"\s+", " ", re.sub(r"\s*(<=|>=|==|!=|=|<|>)\s*", r" \1 ", str(v).strip()))
            v = " ".join(t if t.lower() in ("and", "or") else t.upper() for t in v.split(" "))
            v = re.sub(r"(?<![<>=!]) = (?!=)", " == ", v)
        elif k in ("a", "b", "curve", "y", "x"):
            v = str(v).strip().upper()
        elif isinstance(v, str):
            v = v.strip()
        out[k] = v
    return tool + json.dumps(out, sort_keys=True)


def door_args(f: Formation, name: str, args: dict) -> dict:
    """The arguments that decide what a call computes: the tool's own, and the ones the call door reads (schemas.call)
    where they change it: "by" where the user's zones frame the interval (the lithology zones instead), and under
    reach "well" "zones" and "where" for every tool (a selection; agent.selection). Two calls that differ in them are
    two results, never one served for the other."""
    own = known_args(name, args)
    v = f.view
    resolved = getattr(TOOLS.get(name), "defaults_for", None)    # a default the view decides (runs' limit)
    if resolved is not None:
        own.update({k: d for k, d in resolved(f).items() if own.get(k) is None})
    door = (("by",) if getattr(v, "lithology_zones", None) else ()) + \
        (("zones", "where") if getattr(v, "reach", "focus") == "well" else ())
    own.update({k: args[k] for k in door if k not in own and args.get(k) not in (None, "", [])})
    return own


class Ledger:
    def __init__(self, f: Formation):
        self.f = f
        self.items: list = []
        self.errors: list = []                 # (tool, arguments, message)
        self._keys: dict = {}
        # a conversation (petroharness.session): where the current question's items start, and the earlier items that
        # read a curve a later question computed again (item id -> (curve, the item that computed it again))
        self.turn_start: int = 0
        self.superseded: dict = {}
        # a conversation's settings change (petroharness.session: Conversation.adopt): the well was interpreted again;
        # the items opened before it -> the change, in words ("the settings change before question 3: m 2 -> 1.8")
        self.before: dict = {}
        # the lines the last get or find showed, as data: {item id: [line]} (take_fetched; the session keeps them)
        self._fetched: dict = {}

    def has(self, tool: str, args: dict) -> bool:
        """Whether an identical call is already opened."""
        try:
            return normalize(tool, door_args(self.f, tool, args)) in self._keys
        except (KeyError, ToolError):
            return False

    # opening
    def open(self, tool: str, raw) -> tuple:
        """Run one call, or return the item an identical call opened. A rejected call raises ToolError (recorded)."""
        name = str(tool).strip()
        try:
            shown = list(TOOLS)                                                            # the lookups the brief lists
            if name not in shown:
                raise ToolError(f"no tool {name!r}; tools: {', '.join(shown)}")
            args = fit(name, arguments(raw))
            key = normalize(name, door_args(self.f, name, args))
            if key in self._keys:
                return self._keys[key], False
            before = {n: id(a) for n, a in self.f.view.calculated.items()} if self.turn_start else {}
            r = call(self.f, name, args)
        except ToolError as e:
            self.errors.append((name, raw, str(e)))
            raise
        eid = f"E{len(self.items) + 1}"                   # a cut text names this item in its get
        item = Item(eid, name, args, key, list(r.rows), r.text.replace(CUT_GET, f"get {eid} with find"), list(r.numbers))
        self.items.append(item)
        self._keys[key] = item
        again = [n for n, a in self.f.view.calculated.items() if n in before and id(a) != before[n]]
        if again:
            self._supersede(again, eid)
        return item, True

    def _supersede(self, curves: list, by: str) -> None:
        """A later question of a conversation computed these curves again under the same names: the earlier
        questions' items that name them keep their text (it is what was shown then) but say so when read again, and
        the same call asked again is computed anew instead of served from them."""
        for e in self.items[:self.turn_start]:
            hit = next((c for c in curves if re.search(rf"(?<![A-Z0-9_]){re.escape(c)}(?![A-Z0-9_])", f"{e.call_text()} {e.text}")), None)
            if hit and e.id not in self.superseded:
                self.superseded[e.id] = (hit, by)
                if self._keys.get(e.key) is e:
                    del self._keys[e.key]

    def rewell(self, f: Formation, change: str) -> None:
        """The well interpreted again under changed settings: the items go on (their ids stay and continue), each
        item opened so far says when read again that it rests on the earlier settings (`change`, in words), and the
        same call asked again is computed anew on the new well instead of served from them."""
        self.f = f
        for e in self.items:
            self.before.setdefault(e.id, change)
        self._keys = {}

    def show(self, item: Item, new: bool = True) -> str:
        """The item whole: a call opened before shows its item again in full, never only a pointer to it."""
        if item.id in self.before:                        # read again after the settings changed
            return (f"[{item.id}] (opened before {self.before[item.id]}: these values rest on the earlier settings; "
                    f"{item.call_text()}) {item.text}")
        if item.id in self.superseded:                    # read again after a later question computed its curve again
            curve, by = self.superseded[item.id]
            return (f"[{item.id}] (opened before {curve} was computed again in [{by}]: these are the earlier values; "
                    f"{item.call_text()}) {item.text}")
        return f"[{item.id}] {item.text}" if new else f"[{item.id}] (opened before: {item.call_text()}) {item.text}"

    def zone_of(self, depth: float) -> Optional[str]:
        """The zone holding a depth of this formation, or 'between zones' (None with no formation)."""
        if self.f is None:
            return None
        from petroharness.agent.engine import zone_at
        return zone_at(self.f, depth)

    def by_id(self, eid) -> Optional[Item]:
        k = str(eid).strip().strip("[]").strip().upper()
        return next((e for e in self.items if e.id == k), None)

    # views
    def digest(self, item: Item) -> str:
        """The item in at most DIGEST_CHARS: itself when small; else its summary lines (verbatim, in order) and how to
        fetch the rest."""
        full = f"[{item.id}] {item.text}"
        if item.id in self.before:                        # opened before the settings changed: said in its digest
            full = f"[{item.id}] (before {self.before[item.id]}) {item.text}"
        section = item.tool == "section"
        if len(full) <= (SECTION_DIGEST_CHARS if section else DIGEST_CHARS):
            return full
        lines = item.lines
        short = lambda ln: ln if len(ln) <= 200 else ln[:200].rsplit(",", 1)[0] + " ..."
        chosen, used = {0}, len(item.id) + 3 + len(short(lines[0])) + 1
        room = (SECTION_DIGEST_CHARS if section else DIGEST_CHARS) - 130

        def take(idx) -> None:
            nonlocal used
            new = [i for i in idx if i not in chosen]
            size = sum(len(short(lines[i])) + 1 for i in new)
            if new and used + size <= room:
                chosen.update(new)
                used += size
        if section:                                                # a section's reading is its
            for i, ln in enumerate(lines):                         # classes: thresholds and both views over the zones
                if ln.startswith(("  thresholds", "    zones pooled: ")):   # first, then each class with its runs
                    take([i])
            for i, ln in enumerate(lines):
                if _CLASS.match(ln):
                    take([i])
        labels = [i for i, ln in enumerate(lines) if _P0.match(ln)]
        for k, i in enumerate(labels):                             # each curve with its pooled value, curve by curve
            end = labels[k + 1] if k + 1 < len(labels) else len(lines)
            pooled = next((j for j in range(i + 1, end) if lines[j].startswith(("  zones pooled", "  these zones pooled"))), None)
            take([i] + ([pooled] if pooled is not None else []))
        for rule in (_P1, _P2):                                    # then what it adds up to, then how it was made
            for i, ln in enumerate(lines):
                if rule.match(ln):
                    take([i])
        if item.tool in TOOLSET and TOOLSET[item.tool].table:      # a computed table reads in order: header, rows, facts
            for i in range(1, len(lines)):
                take([i])
        keep = [short(lines[i]) for i in sorted(chosen)]
        left = len(lines) - len(keep)
        zs = sorted(zones_in("\n".join(lines)), key=lambda z: int(z[1:]))
        what = (f"a zone ({zs[0]}-{zs[-1]})" if zs else "") + (", " if zs else "") + "a curve, class, parameter or depth"
        hint = f"  ({left} more lines: get {item.id} with find: {what})"
        mark = f"(before {self.before[item.id]}) " if item.id in self.before else ""
        out = "\n".join([f"[{item.id}] {mark}{keep[0]}"] + keep[1:] + [hint])
        return out if len(out) < len(full) else full

    def get(self, eid, find: str) -> str:
        """Lines of one item that match find (get_lines, with name parts); the item whole without a find; on a miss,
        what find was read as and the names the item holds."""
        item = self.by_id(eid)
        if item is None:
            return f"{eid}: no such item; opened: {', '.join(e.id for e in self.items) or 'none'}"
        zs, words = _terms(find)
        if not zs and not words:
            return self.show(item, False)
        out = get_lines(item, find, parts=True, zone_at=self.zone_of)
        if not out:
            names = ", ".join(_names(item)[:MISS_NAMES])
            return f"[{item.id}] nothing in {item.id} matches {find} ({read_as(find)})" + (f"; its names: {names}" if names else "")
        mark = (f" (opened before {self.before[item.id]}: these values rest on the earlier settings)"
                if item.id in self.before else "")
        text = "\n".join([f"[{item.id}] {item.call_text()} (find: {find}){mark}"] + out)
        cap = max(GET_CHARS, max_chars())                    # a tool's output is at most the result cap: any line fits
        if len(text) > cap:
            kept = text[:cap].rsplit("\n", 1)[0]
            out = out[:max(0, kept.count("\n"))]               # the lines the cut text still shows
            text = kept + f"\n... ({len(text) - cap} more characters: narrow find with a zone or a word)"
        self._fetched[item.id] = list(out)                    # what this get showed, as data
        return text

    def find(self, find: str) -> str:
        """get over every item: which items match, first; then each item's lines while they fit; then the ones left."""
        ids = [e.id for e in self.items if get_lines(e, find, parts=True, zone_at=self.zone_of)]
        if not ids:
            return f"no opened item matches {find} ({read_as(find)})"
        out, left = [f"{find} is in {', '.join(ids)}"], []
        used = len(out[0]) + len(out[0]) + 60                       # the ids line, and room to name those left out
        for eid in ids:
            g = self.get(eid, find)
            if used + len(g) + 2 > FIND_CHARS:
                left.append(eid)
                self._fetched.pop(eid, None)                       # not shown: not fetched
                continue
            out.append(g)
            used += len(g) + 2
        if left:
            out.append(f"(not shown here: {', '.join(left)}; get one of them)")
        return "\n\n".join(out)

    def take_fetched(self) -> dict:
        """{item id: [line]} the get or find since the last take showed (the cut lines and items left out not), and
        clears it: the lines as data, so no reader parses the tool's own text for them."""
        got, self._fetched = self._fetched, {}
        return got

    def listing(self) -> str:
        return "\n".join(f"  {e.id} {e.call_text()}" for e in self.items)

    def calc(self, expression: str, shown: str = "") -> tuple:
        """Arithmetic on numbers opened items show (or the map and question in shown) as an item of its own, so a
        computed number can be cited: "78.8 + 58.4 + 11" -> [E9] calc 78.8 + 58.4 + 11 = 148.2. Each input is a
        number some item or shown text shows at its stated precision, or a small whole number (at most 100: a count, a
        percent); at least one input is shown. A repeated expression returns its item."""
        expr = re.sub(r"\s+", " ", str(expression or "").strip()).rstrip("=").strip()
        try:
            if not expr:
                raise ToolError("calc needs an expression, e.g. \"78.8 + 58.4 + 11\" or \"100 * 12.5 / 150.2\"")
            value, inputs = evaluate(expr)
            if not inputs or not any(op in expr for op in "+-*/(,"):
                raise ToolError(f"calc {expr!r} computes nothing: write an operation on shown numbers")
            text_nums = N.shown_values(shown)
            where, unshown, any_shown = [], [], False
            for raw in inputs:
                v, half = _claimed(raw)
                src = next((e.id for e in self.items if any(matches(v, half, x) for x in shown_values(e))), None)
                if src is None and any(matches(v, half, x) for x in text_nums):
                    src = "map or question"
                if src is not None:
                    any_shown = True
                    where.append(f"{raw} ({src})")
                elif float(raw).is_integer() and abs(float(raw)) <= 100:
                    where.append(f"{raw} (constant)")
                else:
                    unshown.append(raw)
            if unshown:
                raise ToolError(f"calc inputs must be numbers an opened result shows, as shown: {', '.join(unshown)} is "
                                "in none (open the result that shows it, or use the number as a result shows it). A "
                                "quantity Petrophys computes (a volume in place, a conversion, a fit) comes from its "
                                "function: search for it (e.g. {\"summarize\": {\"search\": \"<words>\"}}) and run it.")
            if not any_shown:
                raise ToolError("calc needs at least one number an opened result shows")
        except ToolError as e:
            self.errors.append(("calc", expression, str(e)))
            raise
        key = "calc" + json.dumps({"expression": expr.replace(" ", "")})
        if key in self._keys:
            return self._keys[key], False
        from petroharness.agent.map import num
        line = f"calc {expr} = {num(value)}"
        read = grouping(expr)                    # the order calc used, where the written form leaves it open
        rows = [(line, [value])] + ([(f"  read as: {read}", [])] if read else []) + [(f"  inputs: {', '.join(where)}", [])]
        item = Item(f"E{len(self.items) + 1}", "calc", {"expression": expr}, key, rows, "\n".join(r for r, _ in rows),
                    [value])
        self.items.append(item)
        self._keys[key] = item
        return item, True

