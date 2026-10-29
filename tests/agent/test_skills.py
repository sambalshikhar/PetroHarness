"""The skills (src/petroharness/resources/skills/README.md). Over whatever library is plugged (the packaged
researched one in the suite; PETROHARNESS_SKILLS picks another): generic (no switch tags), every file in canonical form,
the folders and the guides agree, and every line the model reads in Decide, Know, Easily misread and Do not state has
its provenance row (class a with references, every reference defined). Of the packaged researched library: one guide
per topic area and the two common guides, and the edits to the reviewed text.

    .venv/bin/python -m pytest tests/agent/test_skills.py -q
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness.agent import direction  # noqa: E402
from petroharness.config import DEFAULT_SKILLS, RESOURCES  # noqa: E402

LIB = direction.plugged()                              # None: PETROHARNESS_SKILLS=none (its tests are skipped)
RESEARCHED = direction.load((RESOURCES / DEFAULT_SKILLS).resolve())     # the packaged researched library
SKILLS = LIB.path if LIB else None
FOLDERS = sorted(p.name for p in SKILLS.iterdir() if p.is_dir() and not p.name.startswith((".", "__"))) if LIB else []
ROWS = ("decide", "know", "misread", "ceiling")        # the parts whose lines carry a provenance row
CLASSES = {"a", "g", "b"}                              # literature, general guideline, workflow fact (README, G2)
VERIFIED = {"textbook", "opened", "softened"}
KEY = re.compile(r"^[A-Za-z0-9_-]+")                   # a ref's key; the rest names the chapter or topic cited


@pytest.fixture
def lib():
    if LIB is None:
        pytest.skip("no skill library plugged (PETROHARNESS_SKILLS=none)")
    return LIB


def test_skills_are_generic(lib):
    """No switch tags and no switch gates: a skill reads as plain domain guidance."""
    for name, f in lib.facets.items():
        assert "option" not in f, name
        for part, _ in direction.PARTS:
            for line in f.get(part) or []:
                assert not direction._GATE.match(line), (name, line)


def test_one_guide_per_area_and_the_common_guides():
    """Each topic area has its own guide, named for it; answer and route are common; nothing else. The library order
    is common first, then by topic area."""
    assert RESEARCHED.name == "researched" and RESEARCHED.common == ("answer", "route")
    for area in direction.areas():
        assert RESEARCHED.on(area) == [area], area
    assert list(RESEARCHED.facets) == ["answer", "route", *direction.areas()]
    assert RESEARCHED.facets["answer"]["areas"] == RESEARCHED.facets["route"]["areas"] == []


@pytest.mark.parametrize("name", FOLDERS)
def test_skill_file_is_canonical(name, lib):
    """SKILL.md reads and writes back to the same bytes: one format, no stray lines, no hand-formatting drift."""
    text = (SKILLS / name / "SKILL.md").read_text()
    assert direction.write_skill(name, direction.read_skill(text)) == text


@pytest.mark.parametrize("name", FOLDERS)
def test_skill_has_its_parts(name, lib):
    text = (SKILLS / name / "SKILL.md").read_text()
    f = direction.read_skill(text)
    for part in ("when", "consider", "compare", "know", "decide", "ceiling"):
        assert f.get(part), f"{name}: no {part}"
    assert set(yaml.safe_load(text.split("---")[1])) == {"name", "when", "areas"}, name     # no 'names': topics route
    assert {p.name for p in (SKILLS / name).iterdir()} == {"SKILL.md", "sources.yaml"}, name


def test_folders_and_order_agree(lib):
    """Every folder is a guide; the library's order is common first, then by the first topic area each serves; every
    guide is common or serves an area (the index lists it)."""
    order = list(lib.facets)
    assert sorted(order) == FOLDERS and len(order) == len(set(order))
    named = set(lib.common) | {n for a in direction.areas() for n in lib.on(a)}
    assert named == set(order), named ^ set(order)
    first = {a: i for i, a in enumerate(direction.areas())}
    rest = [g for g in order if g not in lib.common]
    assert order[:len(lib.common)] == list(lib.common)
    assert rest == sorted(rest, key=lambda g: (min(first[a] for a in lib.facets[g]["areas"]), g))
    assert {p.name for p in SKILLS.iterdir() if p.is_file()} <= {"library.yaml", "refs.yaml", "README.md"}
    for name in FOLDERS:
        front = yaml.safe_load((SKILLS / name / "SKILL.md").read_text().split("---")[1])
        assert front["name"] == name


@pytest.mark.parametrize("name", FOLDERS)
def test_every_line_has_its_provenance(name, lib):
    """One row per Decide, Know, Easily misread and Do not state line, in order: a class; references for class a; the
    fact named for class b; the review's verification, where set, one of its three words."""
    f = lib.facets[name]
    src = lib.sources["facets"][name]
    assert set(src) <= set(ROWS), set(src) - set(ROWS)
    for part in ROWS:
        rows = src.get(part) or []
        assert len(rows) == len(f.get(part) or []), f"{name}.{part}: {len(rows)} rows, {len(f.get(part) or [])} lines"
        for i, r in enumerate(rows, 1):
            where = f"{name}.{part} {i}"
            assert r.get("class") in CLASSES, where
            assert r["class"] != "a" or r.get("refs"), f"{where}: class a without references"
            assert r["class"] != "b" or r.get("fact"), f"{where}: class b without its fact"
            assert r.get("verified") in VERIFIED | {None}, where
            assert all(isinstance(x, str) and KEY.match(x) for x in r.get("refs") or []), where


def test_every_reference_is_defined_and_every_entry_is_cited(lib):
    """Every cited key is a refs.yaml entry and every entry is cited. An entry is the reference, or, where guides cite
    one work with different entries (the chapters cited, what the reviewer opened), each citing guide's entry under its
    name: then exactly the guides that cite the key."""
    src = lib.sources
    by = {}
    for name, f in src["facets"].items():
        for rows in f.values():
            for r in rows:
                for x in r.get("refs") or []:
                    by.setdefault(KEY.match(x).group(0), set()).add(name)
    assert set(by) <= set(src["refs"]), f"not in refs.yaml: {sorted(set(by) - set(src['refs']))}"
    assert set(src["refs"]) <= set(by), f"cited by no row: {sorted(set(src['refs']) - set(by))}"
    for key, v in src["refs"].items():
        if isinstance(v, dict):
            assert set(v) == by[key] and len(v) > 1, (key, set(v) ^ by[key])
            assert all(isinstance(t, str) and t.strip() for t in v.values()), key
        else:
            assert isinstance(v, str) and v.strip(), key


def test_the_edits_to_the_reviewed_text():
    """The edits to the reviewed guides: (1) net pay Know 3 states no numeric cutoff ranges; (2) no
    service company is named in a guide line; (3) the zones-against-spread line said once by C9 aspects_rule is not
    repeated as a line of its own; (4) the published rules of thumb stay, with their source and 'values vary'."""
    f = RESEARCHED.facets
    k3 = f["net_reservoir_pay"]["know"][2]
    assert k3 == "Cutoffs are set per field from core, tests and sensitivity; published values vary by rock and fluid."
    for name, facet in f.items():
        for part, _ in direction.PARTS:
            for line in facet.get(part) or []:
                assert not re.search(r"\b(SLB|Schlumberger|Halliburton|Baker Hughes)\b", line), (name, line)
    gone = {"porosity": "Call two zones different only when",                 # (3) the reviewer's 'between and
            "elastic_properties": "Within a zone, look at the spread of Vp/Vs",     #   within zone comparison' lines
            "shale_clay": "Between zones, compare VCL medians",
            "log_facies_stratigraphy": "Compare sub-units within a zone"}
    for name, start in gone.items():
        assert not [x for x in f[name]["decide"] if x.startswith(start)], name
    rules = {("invasion_movability", "decide", "Flushed-zone saturation from Archie"): "(Asquith 1982; values vary)",
             ("hydrocarbon_detection", "decide", "Apparent water resistivity Rwa"): "(a service-company glossary; values vary)",
             ("net_reservoir_pay", "know", "Critical SW is commonly"): "; values vary.",
             ("permeability_rock_quality", "know", "Port-size classes by R35"): "Bounds vary slightly between papers.",
             ("statistics_data_analysis", "know", "A rule of thumb for permeability heterogeneity"): "Bands vary by source."}
    for (name, part, start), hedge in rules.items():                          # (4)
        line = next(x for x in f[name][part] if x.startswith(start))
        assert hedge in line, (name, line)
    assert any("service-company glossary" in x for x in f["data_quality"]["decide"])


def test_the_answer_guide_has_no_basis_lines():
    """answer: the general answering guidance, with no line that picks a basis for the model; route: the workflow-route
    guide."""
    a = RESEARCHED.facets["answer"]
    text = "\n".join(x for part, _ in direction.PARTS for x in a.get(part) or [])
    assert "the usual basis" not in text and "is read first from where both occur" not in text
    assert a["know"][0] == "The lithology zones are the groups the workflow reports on."
    assert "does not reverse the workflow's classes" in text


def test_read_skill_rejects_drift():
    with pytest.raises(ValueError):
        direction.read_skill("# no frontmatter\n")
    good = direction.write_skill("x", {"when": "w", "consider": ["a"], "compare": ["b"], "know": ["c"],
                                       "decide": ["d"], "ceiling": ["e"]})
    with pytest.raises(ValueError):
        direction.read_skill(good + "a stray paragraph\n")
    with pytest.raises(ValueError, match="unknown frontmatter"):
        direction.read_skill(good.replace("when: w\n", "when: w\nnames: [pay]\n"))
    tagged = direction.write_skill("x", {"when": "w", "areas": ["porosity", "shale_clay"], "consider": ["a"]})
    assert "\nareas: [porosity, shale_clay]\n" in tagged and direction.read_skill(tagged)["areas"] == ["porosity", "shale_clay"]
