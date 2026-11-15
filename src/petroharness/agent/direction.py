"""Direction: the topic areas (resources/topics.yaml, the harness's) and the pluggable skill library (a folder of guides:
resources/skills/README.md). With a library plugged, the model always sees the index (one line per guide, under the
topic areas the guide serves, the topics it chose first) and a guide call opens one guide's lines. With none
(skills: none), there is neither."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
TOPICS = RESOURCES / "topics.yaml"        # the topic areas: the harness's, the same whatever library is plugged
PARTS = (("consider", "Consider"), ("compare", "Compare"), ("decide", "Decide"), ("know", "Know"),
         ("misread", "Easily misread"), ("ceiling", "Do not state"))
_FRONT = ("when", "areas", "option")     # a skill's frontmatter besides its name: the index line, the topic areas it
#   serves, a measurement gate
ROWS = ("decide", "know", "misread", "ceiling")     # the parts whose lines carry a provenance row (G2)
CLASSES = {"a": "literature, with references", "g": "a general guideline", "b": "a workflow fact, named"}
REF_KEY = re.compile(r"^[A-Za-z0-9_-]+")             # a row's ref: a refs.yaml key, then the chapter or topic cited
GUIDE_NAME = re.compile(r"[a-z][a-z0-9_]*")
LIBRARY_KEYS = ("name", "description", "common")


# --- the topic areas (the harness's) ----------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def areas() -> dict:
    """The topic areas (topics.yaml), in its order: {name: {when, families, overview}}."""
    return dict(yaml.safe_load(TOPICS.read_text())["areas"])


def families(topics) -> list:
    """The workflow's analyzer families the topics read, in topic order, each once (no topics: none)."""
    ax = areas()
    return list(dict.fromkeys(f for t in topics or () if t in ax for f in ax[t].get("families") or ()))


def overview(topics) -> list:
    """The topics' first-look curves (topics.yaml overview), in topic order, each once."""
    ax = areas()
    return list(dict.fromkeys(c for t in topics or () if t in ax for c in ax[t].get("overview") or ()))


# --- the skill format -------------------------------------------------------------------------------------------------

def write_skill(name: str, facet: dict) -> str:
    """A facet as SKILL.md: frontmatter (name, when, areas, and option where the facet has one), then one section per
    part, one bullet per line, each line verbatim (its [option] tag included)."""
    front = {"name": name, **{k: facet[k] for k in _FRONT if k in facet}}
    dump = lambda k, v: yaml.safe_dump({k: v}, allow_unicode=True, width=10 ** 6,          # areas: [a, b]
                                       default_flow_style=None if isinstance(v, list) else False)
    out = ["---", "".join(dump(k, v) for k, v in front.items()).rstrip("\n"), "---", "", f"# {name}"]
    for key, label in PARTS:
        if key in facet:
            out += ["", f"## {label}"] + [f"- {line}" for line in facet[key]]
    return "\n".join(out) + "\n"


def read_skill(text: str) -> dict:
    """SKILL.md -> the facet (the inverse of write_skill; anything else in the file is an error, so drift is caught)."""
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("a skill starts with --- frontmatter ---")
    end = lines.index("---", 1)
    front = yaml.safe_load("\n".join(lines[1:end]))
    extra = set(front) - {"name", *_FRONT}
    if extra:
        raise ValueError(f"skill {front.get('name')}: unknown frontmatter {sorted(extra)} (name, when, areas, option)")
    facet, labels, part = {"when": front["when"]}, {label: key for key, label in PARTS}, None
    for ln in lines[end + 1:]:
        if not ln or ln == f"# {front['name']}":
            continue
        if ln.startswith("## "):
            part = labels[ln[3:]]
            facet[part] = []
        elif ln.startswith("- ") and part:
            facet[part].append(ln[2:])
        else:
            raise ValueError(f"skill {front['name']}: unexpected line {ln[:60]!r}")
    facet.update({k: front[k] for k in _FRONT[1:] if k in front})
    return facet


def switch_on(name: str) -> bool:
    """A gate's switch (src/petroharness/agent/options.py) as set; an unknown name raises."""
    from petroharness.agent import options
    o = options.get()
    if hasattr(o, name):
        return bool(getattr(o, name))
    raise KeyError(f"no switch {name!r} (switches: {', '.join(options.as_dict()) or 'none'})")


PLACEHOLDER = re.compile(r"\b(CURVE|CURVES|NAME|KEY|CONDITION|VALUE|A|B)\b")


_GATE = re.compile(r"^\[(!?)([a-z][a-z0-9_]*)\]\s*")


def gated(entry: str) -> tuple:
    """(shown, text) of a facet entry: '[option] text' is shown only while that option (src/petroharness/agent/options.py) is on, and
    '[!option] text' only while it is off (the line an option replaces); several tags must all hold
    ('[a][!b] text': shown while a is on and b is off)."""
    text, shown = str(entry), True
    while True:
        m = _GATE.match(text)
        if not m:
            break
        on = switch_on(m.group(2))
        shown = shown and (not on if m.group(1) else on)
        text = text[m.end():]
    return (shown, text) if text != str(entry) else (True, entry)


def parse_source(entry: str):
    """'stats PHIE, SW where NET_PAY   (note)' -> (tool, kwargs); None for a template ('stats CURVES'). A computation
    takes its main argument: 'zone_classes gas', 'lithology_stats PHIE, PERM', 'pay_summary'."""
    e = re.sub(r"\s+\([^)]*\)\s*$", "", gated(entry)[1]).strip()
    if PLACEHOLDER.search(e):
        return None
    tool, _, rest = e.partition(" ")
    rest = rest.strip()
    if tool in ("stats", "profile"):
        body, _, where = rest.partition(" where ")
        names = [c.strip() for c in body.split(",")]
        kw = {"curves": names} if tool == "stats" else {"curve": names[0]}
        if where:
            kw["where"] = where.strip()
        return tool, kw
    if tool == "compare":
        a, b = rest.split()
        return tool, {"a": a, "b": b}
    if tool == "crossplot":                                  # 'crossplot RHOB NPHI': y on x; 'log_y' fits log10(y)
        words = rest.split()
        return tool, {"y": words[0], "x": words[1], **{w: True for w in words[2:] if w in ("log_y", "log_x")}}
    if tool == "runs":
        return tool, {"condition": rest}
    if tool == "section":
        return tool, {"key": rest}
    if tool == "step":
        return tool, {"name": rest}
    from petroharness.agent.toolset import TOOLSET                           # the computations: the main argument, if any
    if tool in TOOLSET and TOOLSET[tool].table:
        if not rest:
            return tool, {}
        main = TOOLSET[tool].lead
        if not main:
            raise KeyError(tool)
        return tool, {main: [c.strip() for c in rest.split(",")] if main == "curves" else rest}
    raise ValueError(f"unknown tool in {entry!r}")


def source_names(kw: dict) -> set:
    """The curve and flag names a source reads."""
    out = set()
    for k in ("curves", "curve", "a", "b", "y", "x"):
        v = kw.get(k)
        out |= set(v if isinstance(v, list) else [v] if v else [])
    out -= {"DEPTH"} if kw.get("x") == "DEPTH" or kw.get("y") == "DEPTH" else set()
    for k in ("where", "condition"):
        if kw.get(k):
            out |= {t for t in re.findall(r"[A-Za-z][A-Za-z0-9_]*", kw[k]) if t.lower() not in ("and", "or")}
    return {n.upper() for n in out}


def runs_here(formation, tool: str, kw: dict) -> bool:
    """Whether a source has its data in this formation (stats: one of its curves is enough; a computation: it runs)."""
    from petroharness.agent.toolset import TOOLSET
    if tool in TOOLSET and TOOLSET[tool].table:
        from petroharness.agent.engine import ToolError
        try:
            TOOLSET[tool].run(formation, **kw)
            return True
        except ToolError:
            return False
    curves = set(formation.inv.curves)
    if tool == "section":
        return kw["key"] in {s.key for s in formation.inv.sections}
    if tool == "step":
        return kw["name"] in {m.step for m in formation.inv.methods}
    need = source_names(kw)
    if tool == "stats":
        asked = {c.upper() for c in kw["curves"]}
        return bool(asked & curves) and (need - asked) <= curves
    return need <= curves


# --- a skill library --------------------------------------------------------------------------------------------------

@dataclass(eq=False)
class Library:
    """A skill library, loaded and checked (load): library.yaml's name, description and common guides; every guide
    (common first, then by the first topic area each serves, in topics.yaml's order); the guides' provenance rows and
    the refs; every guide line (C6's texts, for attribution); a version (a hash of the library's files)."""
    path: Path
    name: str
    description: str
    common: tuple
    facets: dict
    sources: dict
    lines: tuple
    version: str

    def on(self, area: str) -> list:
        """The guides that serve a topic area, in the library's order."""
        return [g for g, f in self.facets.items() if area in f["areas"]]

    def listed(self, name: str) -> bool:
        """A guide with an 'option' key is listed in the index only while that option (src/petroharness/agent/options.py)
        is on: a new guide is measured before it reaches every dataset."""
        opt = (self.facets.get(name) or {}).get("option")
        return not opt or switch_on(opt)

    def index(self, topics=()) -> str:
        """One line per guide, under each topic area it serves: the chosen topics' areas first, then common, then the
        other areas in topics.yaml's order. An area whose one guide is named for it is that guide's line."""
        ax = areas()
        chosen = [t for t in dict.fromkeys(topics or ()) if t in ax]
        groups = [(t, self.on(t)) for t in chosen] + [("common", list(self.common))] \
            + [(t, self.on(t)) for t in ax if t not in chosen]
        lines = ["Direction by topic area" + (", your topics first" if chosen else "") + " (guide FACET reads one):"]
        for name, guides in groups:
            shown = [g for g in guides if self.listed(g)]
            if shown == [name]:
                lines.append(f"  {name}: {self.facets[name]['when']}")
            elif shown:
                lines.append(f"  {name}:")
                lines += [f"    {g}: {self.facets[g]['when']}" for g in shown]
        return "\n".join(lines)

    def guide(self, name: str, formation=None) -> str:
        key = str(name).strip().lower()
        f = self.facets.get(key)
        if f is None:
            return f"no facet {name!r}; facets: {', '.join(self.facets)}"
        lines = [f"{key} (when: {f['when']})"]
        for part, title in PARTS:
            items = [t for shown, t in map(gated, f.get(part) or []) if shown]
            if part == "compare" and formation is not None:      # only what can run here; absence goes unsaid
                items = [e for e in items if (p := parse_source(e)) is None or runs_here(formation, *p)]
            if items:
                lines.append(f"{title}:")
                lines += [f"  - {x}" for x in items]
        return "\n".join(lines)

    def calls(self, name: str, formation=None) -> list:
        """A guide's Compare calls as it renders them for the formation, without their notes (its short form)."""
        f = self.facets.get(str(name).strip().lower()) or {}
        items = [t for shown, t in map(gated, f.get("compare") or []) if shown]
        if formation is not None:
            items = [e for e in items if (p := parse_source(e)) is None or runs_here(formation, *p)]
        return [re.sub(r"\s+\([^)]*\)\s*$", "", e).strip() for e in items]

    def sections(self, name: str, formation) -> list:
        """The workflow sections a guide's compare list names that this formation has (opened with the guide): the
        workflow's own reading of the guide's question."""
        f = self.facets.get(str(name).strip().lower())
        if f is None or formation is None:
            return []
        have = {s.key for s in formation.inv.sections}
        out = []
        for shown, entry in map(gated, f.get("compare") or []):
            p = parse_source(entry) if shown else None
            if p and p[0] == "section" and p[1]["key"] in have and p[1]["key"] not in out:
                out.append(p[1]["key"])
        return out

    def workflow_stats(self, name: str, formation) -> list:
        """The plain stats lines of a guide's compare list whose curves are all the workflow's own (computed by a step
        or an analyzer) and present here, as stats arguments: the workflow's measure of the guide's question, opened
        with the guide as its sections are (otherwise a data-coverage question is answered from per-curve counts
        while the workflow's DATA_COMPLETENESS, named in the guide, stays unopened)."""
        f = self.facets.get(str(name).strip().lower())
        if f is None or formation is None:
            return []
        have = formation.inv.curves
        out = []
        for shown, entry in map(gated, f.get("compare") or []):
            p = parse_source(entry) if shown else None
            if not p or p[0] != "stats" or set(p[1]) != {"curves"}:
                continue
            cs = [c.upper() for c in p[1]["curves"]]
            if cs and all(c in have and getattr(have[c], "source", "") in ("computed", "analyzer") for c in cs):
                if {"curves": cs} not in out:
                    out.append({"curves": cs})
        return out


class LibraryError(ValueError):
    """A skill library that cannot be used: each problem as WHAT / WHY / FIX."""


def plugged(cfg=None) -> Optional[Library]:
    """The library a run reads (config.skills_setting: PETROHARNESS_SKILLS, else the configuration's skills, else the
    packaged researched library), loaded and checked; None for "none"."""
    from petroharness.config import skills_setting
    setting = skills_setting(cfg).strip()
    if setting.lower() == "none":
        return None
    path = Path(setting).expanduser()
    return load((path if path.is_absolute() else RESOURCES / path).resolve())


def stamp(library: Optional[Library]) -> dict:
    """The trace's record of the library a run read."""
    if library is None:
        return {"library": "none", "version": None}
    return {"library": library.name, "version": library.version}


def _guide_dirs(path: Path) -> list:
    """A library's guide folders: every folder in it but hidden and cache ones."""
    return sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith((".", "__")))


def _files(path: Path) -> list:
    """The files a library is made of, by their path in it."""
    out = [path / "library.yaml", path / "refs.yaml"]
    for d in _guide_dirs(path):
        out += [d / "SKILL.md", d / "sources.yaml"]
    return [p for p in out if p.is_file()]


@lru_cache(maxsize=8)
def load(path: Path) -> Library:
    """A library folder, read and checked as it loads: every problem is said at once (WHAT / WHY / FIX), so a bad
    library stops a run before its first question, not in the middle of one."""
    from petroharness.config import SKILLS_ENV
    path = Path(path)
    if not (path / "library.yaml").is_file():
        raise LibraryError(f"WHAT: no skill library at {path} (no library.yaml there). WHY: a library is a folder with "
                           f"library.yaml, refs.yaml and one folder per guide (src/petroharness/resources/skills/"
                           f"README.md). FIX: set skills, or {SKILLS_ENV}, to a library folder (absolute, or relative "
                           f"to {RESOURCES}), or to none for a run with no guides.")
    bad = []                                                # (what, why, fix)

    def read_yaml(p: Path, empty):
        try:
            got = yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else empty
        except (yaml.YAMLError, UnicodeDecodeError) as e:
            bad.append((f"{p.relative_to(path)} is not readable YAML ({str(e).splitlines()[0][:120]})",
                        "every file of a library is read as it loads", "correct the file"))
            return empty
        if not isinstance(got if got is not None else empty, type(empty)):
            bad.append((f"{p.relative_to(path)} holds a {type(got).__name__}", f"it holds a {type(empty).__name__}",
                        "see the layout in src/petroharness/resources/skills/README.md"))
            return empty
        return got if got is not None else empty

    meta = read_yaml(path / "library.yaml", {})
    if set(meta) != set(LIBRARY_KEYS):
        bad.append((f"library.yaml has the keys {sorted(meta)}", f"it holds {', '.join(LIBRARY_KEYS)} and nothing else",
                    "give name (a word), description (one line) and common (the guides listed for every question)"))
    common = meta.get("common") or []
    if not isinstance(common, list):
        bad.append((f"common is {common!r}", "common is the list of guides listed for every question",
                    "write common: [<guide>, ...], or common: []"))
        common = []
    common = [str(g) for g in common]
    refs = read_yaml(path / "refs.yaml", {})
    topics = areas()
    facets, rows = {}, {}
    for d in _guide_dirs(path):
        name = d.name
        if not (d / "SKILL.md").is_file():
            bad.append((f"the folder {name} has no SKILL.md", "every folder of a library is a guide",
                        f"add {name}/SKILL.md, or move the folder out of the library"))
            continue
        if not GUIDE_NAME.fullmatch(name):
            bad.append((f"the guide name {name!r} is not lower case letters, digits and underscores",
                        "the model's guide calls are read in lower case", "rename the folder and the guide"))
        try:
            f = read_skill((d / "SKILL.md").read_text(encoding="utf-8"))
            front = yaml.safe_load((d / "SKILL.md").read_text(encoding="utf-8").split("---")[1])
        except (ValueError, KeyError, TypeError, AttributeError, IndexError, yaml.YAMLError) as e:
            bad.append((f"{name}/SKILL.md does not parse ({e!s:.120})", "a guide is read in one strict format",
                        "write it as src/petroharness/resources/skills/README.md shows (frontmatter, then one ## "
                        "section per part, one bullet per line)"))
            continue
        if front.get("name") != name:
            bad.append((f"{name}/SKILL.md is named {front.get('name')!r}", "a guide is called by its folder's name",
                        f"set name: {name}"))
        if not isinstance(f.get("areas"), list):
            bad.append((f"{name} declares no areas", "the index lists a guide under the topic areas it declares",
                        f"add areas: [...] to its frontmatter (names from {TOPICS}), or areas: [] for a common guide"))
            f["areas"] = []
        unknown = [a for a in f["areas"] if a not in topics]
        if unknown:
            bad.append((f"{name} declares areas that are not topic areas: {unknown}",
                        "the harness owns the topic areas; a library cannot add one", f"use names from {TOPICS}"))
        for entry in [x for part, _ in PARTS for x in f.get(part) or []] + ([f"[{f['option']}] "] if f.get("option") else []):
            try:
                gated(entry)
            except KeyError as e:
                bad.append((f"{name}: {e.args[0]} in {entry[:60]!r}", "a gate tag names a live switch",
                            "remove the tag, or name a switch of src/petroharness/agent/options.py"))
        for entry in f.get("compare") or []:
            try:
                parse_source(entry)
            except (ValueError, KeyError, IndexError):
                bad.append((f"{name}: the Compare line {entry[:60]!r} is not a lookup the harness can run",
                            "Compare lines are rendered for the formation as the guide is read; one that cannot be "
                            "read would fail mid-run", "write a tool call (stats, runs, compare, profile, section, "
                            "step, crossplot or a computation) or a template (stats CURVES)"))
        src = read_yaml(d / "sources.yaml", {})
        if set(src) - set(ROWS):
            bad.append((f"{name}/sources.yaml has the parts {sorted(set(src) - set(ROWS))}",
                        f"rows are kept for {', '.join(ROWS)}", "rename or remove them"))
        for part in ROWS:
            lines, got = f.get(part) or [], src.get(part) or []
            if len(got) != len(lines):
                bad.append((f"{name} has {len(lines)} {part} lines and {len(got)} sources rows",
                            "every Decide, Know, Easily misread and Do not state line has its provenance row, in "
                            "order (G2)", f"give one row per line in {name}/sources.yaml"))
            for i, r in enumerate(got, 1):
                where = f"{name} {part} {i}"
                if not isinstance(r, dict) or r.get("class") not in CLASSES:
                    bad.append((f"{where}: no class", "a row's class is " + "; ".join(f"{k} ({v})" for k, v in
                                                                                      CLASSES.items()),
                                "set class: a, g or b"))
                    continue
                cited = [str(x) for x in r.get("refs") or []]
                if r["class"] == "a" and not cited:
                    bad.append((f"{where}: class a with no refs", "a literature line names its source",
                                "add refs (keys of refs.yaml)"))
                if r["class"] == "b" and not r.get("fact"):
                    bad.append((f"{where}: class b with no fact", "a workflow-fact line names the fact",
                                "add fact: the workflow fact it states"))
                missing = [x for x in cited if not REF_KEY.match(x) or REF_KEY.match(x).group(0) not in refs]
                if missing:
                    bad.append((f"{where}: refs not in refs.yaml: {missing}", "every reference a row cites is defined",
                                "add the entries to refs.yaml, or correct the keys"))
        facets[name], rows[name] = f, src
    absent = [g for g in common if g not in facets]
    if absent:
        bad.append((f"common names guides the library lacks: {absent}", "common guides are listed for every question",
                    "add the guides, or remove them from common"))
    unlisted = [g for g, f in facets.items() if not f["areas"] and g not in common]
    if unlisted:
        bad.append((f"the guides {unlisted} serve no topic area and are not common",
                    "the index would never list them, so the model would never read them",
                    "give each its areas, or list it under common"))
    if not facets:
        bad.append(("the library has no guides", "a library is a folder of guides",
                    "add guides, or run with skills: none"))
    if bad:
        raise LibraryError(f"skill library {path} cannot be used ({len(bad)} problem{'s' * (len(bad) > 1)}):\n"
                           + "\n".join(f"- WHAT: {w}. WHY: {y}. FIX: {x}." for w, y, x in bad))
    first = {a: i for i, a in enumerate(topics)}
    order = [g for g in common] + sorted((g for g in facets if g not in common),
                                         key=lambda g: (min(first[a] for a in facets[g]["areas"]), g))
    h = hashlib.sha1()
    for p in _files(path):
        h.update(str(p.relative_to(path)).encode() + b"\0" + p.read_bytes())
    return Library(path=path, name=str(meta["name"]), description=str(meta["description"]), common=tuple(common),
                   facets={g: facets[g] for g in order}, sources={"refs": refs, "facets": {g: rows[g] for g in order}},
                   lines=tuple(x for g in order for part, _ in PARTS for x in facets[g].get(part) or []),
                   version=h.hexdigest()[:12])
