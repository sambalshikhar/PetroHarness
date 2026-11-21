"""The user's zones: a table of zone tops and bottoms (CSV, TSV or Excel) that frames a question in place of the
lithology zones (docs/designs/zones-and-intervals.md, brick 3). Petrophys reads it as it reads formation tops
(petrophys.io.geology_reader.read_formations: the name column zone, zone_name, name or formation; top or from; bottom,
base or to; an optional well column, filtered to this well, and depth_unit column); each sample of the question is
labelled by Petrophys (petrophys.model.formation_tops.label_depths: top <= depth < bottom; overlapping rows refused).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional


def read_zones(path, well_names: Iterable[str] = (), sheet: Optional[str] = None) -> list[dict]:
    """The zones of this well in the table at `path` -> [{name, top, base, closed, unit, line}] in the table's order of
    depth, in the table's depth unit (None: the LAS's own). `well_names`: the names this LAS goes by, for a table with a
    well column. A table without bottoms, with several wells none of which is this one, or one Petrophys cannot read is
    refused with what to fix."""
    from petrophys.io.geology_reader import read_formations
    from petroharness.well.tops import depth_unit_name
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"WHAT: no zones file at {path}. FIX: give the path of the zones table (CSV or Excel).")
    kw = {"sheet_name": sheet} if sheet else {}
    names = [str(n) for n in well_names if str(n or "").strip()]
    try:
        table = read_formations(path, **kw)
    except ValueError as e:
        if "Multiple wells" not in str(e):
            raise ValueError(f"WHAT: Petrophys could not read the zones file {path.name}: {e}. WHY: the zones are read "
                             "as formation tops are. FIX: give a table with a zone name, top and bottom column per "
                             "row (zone,top,bottom[,well][,depth_unit]).") from None
        table = None
        for n in names:
            try:
                table = read_formations(path, well_name=n, **kw)
                break
            except ValueError:
                continue
        if table is None:
            raise ValueError(f"WHAT: the zones file {path.name} lists several wells ({str(e).split(':', 1)[-1].strip()}), "
                             f"none of them this well ({', '.join(names) or 'no name in the LAS header'}). WHY: a "
                             "table with a well column is read for this well only. FIX: name this well in its well "
                             "column, or give a table of this well's zones.") from None
    if "bottom_depth" not in table:
        raise ValueError(f"WHAT: the zones file {path.name} gives tops only. WHY: a zone is read between its own top and "
                         "bottom. FIX: add a bottom column (zone,top,bottom), or give the file as the tops file "
                         "(--tops) to name units whose base is the next top.")
    unit_default = table.attrs.get("depth_unit")
    out = []
    for i, row in enumerate(table.itertuples(index=False), start=2):
        r = row._asdict()
        unit = r.get("depth_unit") or unit_default
        named = depth_unit_name(unit) if unit not in (None, "") else None
        if unit not in (None, "") and named is None:
            raise ValueError(f"WHAT: the zones file {path.name} line {i} gives depth unit {unit!r}. FIX: give m or ft.")
        out.append({"name": str(r["formation_name"]).strip(), "top": float(r["top_depth"]),
                    "base": float(r["bottom_depth"]), "closed": False, "unit": named, "line": i})
    if not out:
        raise ValueError(f"WHAT: the zones file {path.name} has no zone. FIX: give one row per zone: zone,top,bottom.")
    return sorted(out, key=lambda z: (z["top"], z["base"]))
