"""A formation tops table as people keep one: a CSV (or TSV, or Excel sheet) with a name and a top depth per row and,
optionally, a base, a depth unit and a well. Its columns are found by what they mean (a few common header names),
never by one dataset's layout; a two- or three-column file without a header (name, top[, base]) is read too.

A formation's interval: from its top to its stated base (included), else to the next deeper top in the table (not
included), else to the end of the log."""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from petroharness.well.formation import FormationNotFound

# Header names by meaning, in order of preference (headers are compared lower-case, punctuation as "_").
NAME_COLUMNS = ("formation", "formation_name", "name", "top_name", "zone", "horizon", "unit")
TOP_COLUMNS = ("top", "top_depth", "top_md", "md", "depth")
BASE_COLUMNS = ("bottom", "bottom_depth", "bottom_md", "base", "base_depth", "base_md")
UNIT_COLUMNS = ("depth_unit", "depth_units", "units", "unit")
WELL_COLUMNS = ("well", "well_name", "wellname", "well_id", "uwi", "api")
DEPTH_UNITS = {"m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
               "ft": "ft", "f": "ft", "feet": "ft", "foot": "ft"}
FEET_PER_METRE = 1 / 0.3048


def depth_unit_name(text) -> str | None:
    """'m' or 'ft' for a depth unit's usual spellings (M, metres, FT, F, feet, ...); None for anything else."""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return None
    return DEPTH_UNITS.get(re.sub(r"[\s.]", "", str(text)).lower())


def convert(depth: float, unit: str, to: str) -> float:
    """A depth from one unit (m or ft) to another."""
    if unit == to:
        return depth
    return depth * FEET_PER_METRE if to == "ft" else depth / FEET_PER_METRE


def name_key(name) -> str:
    """How names are matched: case, spaces and punctuation ignored ('Mount Messenger' = 'MOUNT-MESSENGER')."""
    return re.sub(r"[\W_]+", "", str(name)).casefold()


def _header(column) -> tuple[str, str | None]:
    """A header as a key and the depth unit it states, if any: 'Top (ft)' -> ('top', 'ft'), 'TOP_MD_M' ->
    ('top_md', 'm'), 'Formation Name' -> ('formation_name', None)."""
    text, unit = str(column).strip().lower(), None
    bracket = re.search(r"[(\[]\s*([a-z. ]+?)\s*[)\]]", text)
    if bracket and depth_unit_name(bracket.group(1)):
        unit, text = depth_unit_name(bracket.group(1)), text[:bracket.start()] + text[bracket.end():]
    key = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    suffix = re.fullmatch(r"(.+)_(m|ft|feet|metres|meters)", key)
    if unit is None and suffix and suffix.group(1) in TOP_COLUMNS + BASE_COLUMNS:
        key, unit = suffix.group(1), depth_unit_name(suffix.group(2))
    return key, unit


@dataclass(frozen=True)
class Top:
    name: str                    # as the table writes it
    top: float
    base: float | None        # the stated base, if the table has one for this row
    unit: str | None          # m or ft; None: the LAS's own unit
    line: int                    # the row's line in the file (1 = the first line)


@dataclass(frozen=True)
class FormationInterval:
    name: str
    top: float
    base: float | None        # None: to the end of the log
    closed: bool                 # the base is the formation's stated base (included), not the next top
    unit: str | None          # m or ft; None: the LAS's own unit
    base_from: str               # "stated base", "next top <name>" or "end of log"


@dataclass
class TopsTable:
    path: Path
    tops: list[Top]
    columns: dict                # role -> the file's column (name, top, base, unit, well)
    wells: tuple = ()            # the wells the table was filtered to (empty: no well column)

    def names(self) -> list[str]:
        return list(dict.fromkeys(t.name for t in self.tops))

    def within(self, iv: FormationInterval) -> list:
        """The table's other units inside the interval: (name, top, base), shallowest first (_units_within)."""
        return _units_within(self, iv)

    def interval(self, formation: str, top: float | None = None) -> FormationInterval:
        """The formation's interval (see the module's docstring). A name matches case-, space- and
        punctuation-insensitively; a name the table lists twice (a repeated section) is chosen by `top`, the top of
        the row meant as the file writes it."""
        key = name_key(formation)
        hits = [t for t in self.tops if name_key(t.name) == key]
        where = f" for well {self.wells[0]}" if self.wells else ""
        if not hits:
            names = self.names()
            close = difflib.get_close_matches(str(formation), names, n=3, cutoff=0.6)
            hint = f" Did you mean {', '.join(repr(c) for c in close)}?" if close else ""
            raise FormationNotFound(
                f"WHAT: formation {formation!r} is not in the tops file {self.path.name}{where}.{hint} WHY: its interval "
                f"comes from its row there. FIX: use one of the names it lists ({', '.join(names)}), or give the "
                "interval's depths (--top/--base) instead of the tops file.")
        listed = "; ".join(f"line {t.line}: top {t.top:g}" + (f", base {t.base:g}" if t.base is not None else "")
                           for t in hits)
        if top is not None:
            hits = [t for t in hits if abs(t.top - top) <= 1e-6 * max(1.0, abs(top))][:1] or []
            if not hits:
                raise FormationNotFound(
                    f"WHAT: formation {formation!r} has no row with top {top:g} in {self.path.name}{where} ({listed}). "
                    "FIX: give the top of one of its rows (--top D), as the file writes it.")
        if len(hits) > 1:
            raise FormationNotFound(
                f"WHAT: formation {formation!r} is listed {len(hits)} times in {self.path.name}{where} ({listed}). "
                "WHY: a repeated name (e.g. a repeated section) does not say which interval is meant. FIX: choose the "
                "one you mean by its top: --formation NAME --tops FILE --top D, or give its depths alone: --formation "
                "NAME --top D --base D.")
        hit = hits[0]
        if hit.base is not None:
            if hit.base <= hit.top:
                raise ValueError(f"WHAT: {self.path.name} line {hit.line} gives {hit.name!r} a base ({hit.base:g}) "
                                 f"not below its top ({hit.top:g}). FIX: correct the row.")
            return FormationInterval(hit.name, hit.top, hit.base, True, hit.unit, "stated base")
        deeper = sorted(((_in_unit(t.top, t.unit, hit.unit), t.name) for t in self.tops
                         if _in_unit(t.top, t.unit, hit.unit) > hit.top), key=lambda x: x[0])
        if deeper:
            return FormationInterval(hit.name, hit.top, deeper[0][0], False, hit.unit, f"next top {deeper[0][1]}")
        return FormationInterval(hit.name, hit.top, None, False, hit.unit, "end of log")


def _units_within(table: "TopsTable", iv: FormationInterval) -> list:
    """The table's other units inside an interval (a group's formations, a formation's members): (name, top, base) in
    the interval's unit, shallowest first. Inside: its top and base within the interval's, and not the interval's own
    span. A name listed twice is left out (its rows do not say which is meant), as is one with no base."""
    if iv.base is None:
        return []
    keys = [name_key(t.name) for t in table.tops]
    out, eps = [], 1e-6 * max(1.0, abs(iv.base))
    for t in table.tops:
        key = name_key(t.name)
        if key == name_key(iv.name) or keys.count(key) > 1:
            continue
        try:
            u = table.interval(t.name)
        except (ValueError, LookupError):
            continue
        if u.base is None:
            continue
        top, base = _in_unit(u.top, u.unit, iv.unit), _in_unit(u.base, u.unit, iv.unit)
        if top >= iv.top - eps and base <= iv.base + eps and (top > iv.top + eps or base < iv.base - eps):
            out.append((t.name, top, base))
    return sorted(out, key=lambda x: (x[1], x[2]))


def _in_unit(depth: float, unit: str | None, to: str | None) -> float:
    return depth if unit is None or to is None else convert(depth, unit, to)


def _read_frame(path: Path, header) -> pd.DataFrame:
    """The table in a tops file (CSV, tab- or semicolon-separated, or Excel); one that cannot be read as a table is a
    ValueError saying where (WHAT / FIX)."""
    try:
        if path.suffix.lower() in (".xlsx", ".xls"):
            return pd.read_excel(path, header=header, dtype=str)
        first = next((ln for ln in path.read_text(errors="replace", encoding="utf-8").splitlines() if ln.strip()), "")
        sep = "\t" if "\t" in first else ";" if ";" in first and "," not in first else ","
        return pd.read_csv(path, sep=sep, header=header, dtype=str, skipinitialspace=True, skip_blank_lines=True)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        said = " ".join(str(exc).split()).replace("Error tokenizing data. C error: ", "")
        raise ValueError(f"WHAT: the tops file {path.name} cannot be read as a table ({said}). FIX: give every row "
                         "the same columns, separated by commas (leave a missing value empty, e.g. 'B,1100,'), with "
                         "a header line naming them (formation,top[,base][,depth_unit][,well]).") from exc


def _number(text) -> float | None:
    if text is None or (isinstance(text, float) and pd.isna(text)) or not str(text).strip():
        return None
    try:
        return float(str(text).strip().replace(",", ""))
    except ValueError:
        return None


def _roles(frame: pd.DataFrame) -> tuple[dict, dict]:
    """role -> column, and column -> the depth unit its header states."""
    keys, hints = {}, {}
    for col in frame.columns:
        key, unit = _header(col)
        keys.setdefault(key, col)
        if unit:
            hints[col] = unit
    roles = {}
    for key in UNIT_COLUMNS:
        col = keys.get(key)
        if col is None:
            continue
        values = [v for v in frame[col].dropna().astype(str) if v.strip()]
        if key != "unit" or (values and all(depth_unit_name(v) for v in values)):
            roles["unit"] = col
            break
    for role, names in (("name", NAME_COLUMNS), ("top", TOP_COLUMNS), ("base", BASE_COLUMNS), ("well", WELL_COLUMNS)):
        col = next((keys[k] for k in names if k in keys and keys[k] != roles.get("unit")), None)
        if col is not None:
            roles[role] = col
    return roles, hints


def read_tops(path, well_names: Iterable[str] = (), depth_unit: str | None = None,
              las_unit: str | None = None) -> TopsTable:
    """Read a tops table. `well_names`: the names this LAS goes by (its file stem, its WELL/UWI/API header); a table
    with a well column is filtered to them. A depth's unit: the table's unit column, else the unit its header states,
    else `depth_unit` (the user's), else `las_unit` (the LAS's own). The table and the user stating different units is
    an error."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"WHAT: no tops file at {path}. FIX: give the path of a CSV with one row per top "
                                "(columns such as formation,top[,base][,depth_unit]).")
    stated = depth_unit_name(depth_unit) if depth_unit else None
    if depth_unit and stated is None:
        raise ValueError(f"WHAT: depth unit {depth_unit!r} is not m or ft. FIX: give m or ft.")
    las_unit = depth_unit_name(las_unit) if las_unit else None
    frame = _read_frame(path, 0)
    roles, hints = _roles(frame)
    if ("name" not in roles or "top" not in roles) and 2 <= frame.shape[1] <= 3 \
            and _number(frame.columns[1]) is not None:                   # name,top[,base] without a header line
        frame = _read_frame(path, None)
        frame.columns = ["name", "top", "base"][:frame.shape[1]]
        roles, hints, first_line = {c: c for c in frame.columns}, {}, 1
    else:
        first_line = 2
    missing = [r for r in ("name", "top") if r not in roles]
    if missing:
        raise ValueError(
            f"WHAT: the tops file {path.name} has no {' or '.join(missing)} column (its columns: "
            f"{', '.join(map(str, frame.columns))}). WHY: each row needs a formation name and its top depth. FIX: name "
            f"the columns: the name one of {', '.join(NAME_COLUMNS)}; the top one of {', '.join(TOP_COLUMNS)}; "
            f"optionally a base ({', '.join(BASE_COLUMNS)}), a depth_unit and a well column.")
    rows = frame.reset_index(drop=True)
    wells: tuple = ()
    if "well" in roles:
        want = {name_key(w) for w in well_names if str(w or "").strip()}
        have = rows[roles["well"]].astype(str)
        keep = have.map(name_key).isin(want)
        if not keep.any():
            listed = ", ".join(dict.fromkeys(v for v in have if v.strip() and v != "nan"))
            raise FormationNotFound(
                f"WHAT: the tops file {path.name} has no rows for this well (it goes by "
                f"{', '.join(repr(w) for w in well_names if str(w or '').strip()) or 'no name'}; the file's "
                f"{roles['well']} column lists {listed}). WHY: a table with a well column is read for this well only. "
                "FIX: put this well's name (the LAS file's name or its WELL header) in that column, or drop the "
                "column from a table that holds only this well.")
        wells = tuple(dict.fromkeys(have[keep]))
        rows = rows[keep]
    tops = []
    for i, row in rows.iterrows():
        line = int(i) + first_line
        name = str(row[roles["name"]]).strip() if pd.notna(row[roles["name"]]) else ""
        top = _number(row[roles["top"]])
        if not name and top is None:
            continue
        if not name or top is None:
            raise ValueError(f"WHAT: {path.name} line {line} has {'no name' if not name else 'no numeric top'} "
                             f"({row[roles['name']]!r}, {row[roles['top']]!r}). FIX: give every row a name and a "
                             "top depth, or delete the row.")
        base = _number(row[roles["base"]]) if "base" in roles else None
        table_unit = None
        if "unit" in roles and pd.notna(row[roles["unit"]]) and str(row[roles["unit"]]).strip():
            table_unit = depth_unit_name(row[roles["unit"]])
            if table_unit is None:
                raise ValueError(f"WHAT: {path.name} line {line} gives depth unit {row[roles['unit']]!r}, not m or "
                                 "ft. FIX: write m or ft.")
        table_unit = table_unit or hints.get(roles["top"])
        if table_unit and stated and table_unit != stated:
            raise ValueError(f"WHAT: the tops file {path.name} states its depths in {table_unit} and the depth unit "
                             f"given is {stated}. WHY: one of them is wrong. FIX: drop --depth-unit (the file's unit "
                             "is used) or correct the file.")
        tops.append(Top(name=name, top=top, base=base, unit=table_unit or stated or las_unit, line=line))
    if not tops:
        raise ValueError(f"WHAT: the tops file {path.name} has no rows with a name and a top. FIX: fill it in.")
    return TopsTable(path=path, tops=tops, columns=dict(roles), wells=wells)
