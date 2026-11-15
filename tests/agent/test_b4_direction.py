"""Direction tests, offline part (D1-D4: decide, ceiling, sources, computations; one researched guide per area, the
index one line per guide, the Compare lines lookups that parse and render on every configured dataset), on the plugged
skill library (the packaged researched one in the suite).

    .venv/bin/python -m pytest tests/agent/test_b4_direction.py -q -s   (PETROHARNESS_DATA selects the dataset)
"""
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.agent.direction import areas, parse_source, plugged, source_names  # noqa: E402
from petroharness.agent.toolset import TOOLSET  # noqa: E402
COMPUTED = tuple(t.name for t in TOOLSET if t.table)       # the computed tables: here when they run
from petroharness.agent.engine import ToolError  # noqa: E402

LIB = plugged()                # the plugged skill library (the packaged researched one in the suite)
if LIB is None:
    pytest.skip("no skill library plugged (PETROHARNESS_SKILLS=none)", allow_module_level=True)

VERDICT = re.compile(r"\bnever\b|\bmust\b|\bshould\b|not independent|cannot be (assessed|determined|validated|established|trusted)|"
                     r"not determinable|unvalidated|uncalibrated|no core plugs|as established|\bconfirmed\b|commercial|"
                     r"producib|unreliable|means nothing", re.I)
# The researched area guides state textbook knowledge in general terms. Modal and topic words in it ('model and
# porosity must match', 'Rwa above 3 x RW suggests producible hydrocarbon' as a published rule of thumb, 'is not
# independent evidence', 'uncalibrated estimates') are that prose, not verdicts on a well; its lines are held to the
# verdict words proper. The harness's own text (every Compare line and note, and the common guides) is held to all of
# VERDICT. Conclusions written as rules are G3's (tests/test_generality.py::test_no_prescriptions).
VERDICT_ON_A_WELL = re.compile(r"cannot be (assessed|determined|validated|established|trusted)|not determinable|unvalidated|"
                               r"no core plugs|as established|\bconfirmed\b|commercial|means nothing", re.I)
DATASETS = re.compile(r"geolink|costa|\bvolve\b|kharaib|equinor|\bnpd\b|norw(ay|egian)|north sea", re.I)   # not 'involve'
DEPTH = re.compile(r"(?<![\d.])\b\d{3,5}(\.\d+)?\s*(m|ft)\b")      # not a decimal's digits ('every 0.1524 m')
ZONE = re.compile(r"\bZ\d+\b")
PARTS = ("when", "consider", "compare", "decide", "know", "misread", "ceiling")
ROOT = Path(__file__).resolve().parents[2]
COMMON = LIB.common
# A Do not state line names what the data cannot establish and what would (the data, test or measurement that settles
# it), or it is a method's limit of validity ('under oil-based mud, do not apply ...').
WOULD = re.compile(r"\b(would|establish\w*|measures?|measured|settles?|decides?|confirm|needs?|needed|supply|test it|only "
                   r"estimated|compute them|ideally with|do not apply)\b", re.I)


def texts(parts=("consider", "compare", "decide", "know", "misread")):
    for name, f in LIB.facets.items():
        yield name, "\n".join([f["when"]] + [x for part in parts for x in f.get(part) or []])


def verdict(name: str, part: str):
    """The verdict lint for a part of a guide: all of VERDICT for the harness's own text, the verdict words proper for
    the researched library's lines."""
    return VERDICT if part == "compare" or name in COMMON else VERDICT_ON_A_WELL


def ceilings():
    for name, f in LIB.facets.items():
        for x in f["ceiling"]:
            yield name, x


# --- D1 lint ----------------------------------------------------------------------------------------------------------

def test_d1_no_verdicts_no_dataset_names_no_depths():
    hits = []
    for name, t in texts():
        hits += [(name, "dataset", m.group(0)) for m in DATASETS.finditer(t)]
        hits += [(name, "depth", m.group(0)) for m in DEPTH.finditer(t)]
    for name, f in LIB.facets.items():
        for part in ("consider", "compare", "decide", "know", "misread"):
            for x in f.get(part) or []:
                hits += [(name, part, "verdict", m.group(0)) for m in verdict(name, part).finditer(x)]
    assert not hits, hits


def test_d1_the_lint_patterns():
    assert not DATASETS.search("questions that involve depth matching") and DATASETS.search("Volve wells")
    assert not DEPTH.search("sampled every 0.1524 m (0.5 ft)") and DEPTH.search("top at 2500 m")
    assert VERDICT.search("PEF is unreliable") and not VERDICT_ON_A_WELL.search("PEF is unreliable for lithology")
    assert VERDICT_ON_A_WELL.search("pay is confirmed") and VERDICT_ON_A_WELL.search("commercial pay")


def test_d1_every_facet_has_its_parts_and_no_judge():
    for name, f in LIB.facets.items():
        assert f.get("when") and f.get("consider") and f.get("compare") and f.get("decide") and f.get("ceiling"), name
        assert not set(f) - set(PARTS) - {"option", "areas"}, (name, set(f))     # option: listed while on; no 'names' (question words)
        assert all(isinstance(x, str) and x.strip() for p in PARTS[1:] for x in f.get(p) or []), name


def test_d1_ceilings_name_a_limit_not_a_verdict_on_this_well():
    """A ceiling says what these data cannot establish and what would establish it (the area guides' form:
    'what logs cannot establish, and what would'); it never names a zone, a depth or a dataset."""
    bad = []
    for name, x in ceilings():
        if name not in COMMON and not WOULD.search(x):
            bad.append((name, "no data, test or measurement named that would settle it", x))
        if re.search(r"\bfrom (logs|these logs)\b|logs alone|logs (cannot|do not)", x) and not WOULD.search(x):
            bad.append((name, "a log limit without what would establish it", x))
        bad += [(name, "zone/depth/dataset", m.group(0)) for r in (ZONE, DEPTH, DATASETS) for m in r.finditer(x)]
    assert not bad, bad


def test_d1_decide_lines_are_criteria_for_any_well():
    bad = []
    for name, f in LIB.facets.items():
        for x in f["decide"]:
            bad += [(name, m.group(0)) for r in (verdict(name, "decide"), ZONE, DEPTH, DATASETS) for m in r.finditer(x)]
    assert not bad, bad


def test_d1_no_line_repeated_within_a_facet():
    for name, f in LIB.facets.items():
        seen = [x.strip().lower() for p in PARTS[1:] for x in f.get(p) or []]
        assert len(seen) == len(set(seen)), name


# --- D4 sources: every decide and ceiling line has its class and source -----------------------------------------------

def _sources():
    return LIB.sources                                 # the guides' provenance (<guide>/sources.yaml, refs.yaml)


def test_d4_every_reference_is_used():
    """Every refs.yaml entry is cited, and every citation's key (the chapter or topic cited follows it) is an entry."""
    src = _sources()
    key = lambda x: re.match(r"[A-Za-z0-9_-]+", x).group(0)
    used = {key(x) for f in src["facets"].values() for p in f.values() for r in p for x in r.get("refs") or []}
    assert used == set(src["refs"]), (set(src["refs"]) - used, used - set(src["refs"]))


def test_d1_every_indexed_facet_exists_and_every_facet_is_indexed():
    used = set()
    groups = {"common": LIB.common, **{a: LIB.on(a) for a in areas()}}
    for c, names in groups.items():                          # every area's guides and the common ones
        for name in names:
            assert name in LIB.facets, (c, name)
            used.add(name)
    assert used == set(LIB.facets), set(LIB.facets) - used


# --- D3 sizes ---------------------------------------------------------------------------------------------------------

INDEX_MAX, GUIDE_MAX = 4000, 9000      # one line per guide (about 3,550); the researched guides 6,200-9,000 with
#   their Compare lines (permeability with its flow units)


@pytest.mark.parametrize("topics", [[], ["porosity", "water_saturation"], ["data_quality"]])
def test_d3_the_index_is_one_line_per_guide_under_its_area(topics):
    text = LIB.index(topics)
    lines = text.splitlines()
    assert len(lines) == 1 + len(areas()) + 1 + len(LIB.common) and len(text) <= INDEX_MAX, (len(lines), len(text))
    for a in areas():
        assert sum(ln == f"  {a}: {LIB.facets[a]['when']}" for ln in lines) == 1, a
    assert lines[1:1 + len(topics)] == [f"  {a}: {LIB.facets[a]['when']}" for a in topics]
    head = lines.index("  common:")
    assert lines[head + 1:head + 3] == [f"    {g}: {LIB.facets[g]['when']}" for g in LIB.common]


def test_d3_sizes():
    big = [("index", len(LIB.index()))] if len(LIB.index()) > INDEX_MAX else []      # every guide, one line
    big += [(n, len(LIB.guide(n))) for n in LIB.facets if len(LIB.guide(n)) > GUIDE_MAX]
    assert not big, big


# --- D2 sources -------------------------------------------------------------------------------------------------------

parse = parse_source
names_in = source_names


def sources() -> list:
    out = []
    for name, f in LIB.facets.items():
        for entry in f["compare"]:
            p = parse(entry)
            if p:
                out.append((name, entry, *p))
    return out


TOOL_NAMES = ("stats", "runs", "compare", "profile", "section", "step", "crossplot", "overlap", *COMPUTED)
TEMPLATES_MAX = 5            # recipes whose value the model gives (a threshold, a condition, its own curves), per guide;
#   statistics_data_analysis, whose methods apply to any curve, has five


def test_d2_every_source_parses():
    """Every area guide's Compare line is a tool call, 1 to 12 a guide, none repeated; at most five are recipes with a
    value the model gives (a template of a tool: 'runs CONDITION', 'adjacent_jumps CURVE threshold=VALUE'), the rest
    lookups that render for the formation. The common guides keep their own templates."""
    for name, f in LIB.facets.items():
        if name in COMMON:
            continue
        lines = f["compare"]
        assert 1 <= len(lines) <= 12 and len(set(lines)) == len(lines), name
        templates = [e for e in lines if parse_source(e) is None]
        assert len(templates) <= TEMPLATES_MAX, (name, templates)
        assert all(e.split()[0] in TOOL_NAMES for e in templates), (name, templates)
    assert len(sources()) >= len(areas()) * 3
    for name, entry, tool, kw in sources():
        assert tool in TOOL_NAMES, entry


NOTE = re.compile(r"^(?P<call>\S.*?\S)   \((?P<note>[^()]+)\)$")
CONCLUDES = re.compile(r"\b(means?|meaning|indicates?|indicating|suggest\w*|implies|points? to|shows? that|is a sign|"
                       r"evidence of|good|poor|best|worst|strong|weak)\b", re.I)


def test_d2_each_compare_line_has_a_plain_note_on_what_it_shows():
    """Each area guide's Compare line ends in a short note on what the lookup shows: never what to conclude from it
    (no reading words, no grades, no verdict words, no conclusion forms of G3)."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_generality import PRESCRIPTIONS
    bad = []
    for name, f in LIB.facets.items():
        if name in COMMON:
            continue
        for e in f["compare"]:
            m = NOTE.match(e)
            if not m:
                bad.append((name, "no note", e))
                continue
            note = m.group("note")
            if len(note) > 120 or CONCLUDES.search(note) or VERDICT.search(note) \
                    or any(re.search(p, note, re.I) for p in PRESCRIPTIONS):
                bad.append((name, "note", note))
    assert not bad, bad


@pytest.mark.data
def test_d2_sources_run_where_their_data_is_and_say_what_exists_elsewhere():
    from test_b2_tools import F
    from petroharness.agent.toolset import TOOLS
    ran, bad = Counter(), []
    for t, f in F():
        steps = {m.step for m in f.inv.methods}
        keys = {s.key for s in f.inv.sections}
        for facet, entry, tool, kw in sources():
            need = names_in(kw)
            if tool in COMPUTED:                            # a computation is here when it runs (its own checks)
                here = None
            elif tool == "section":
                here = kw["key"] in keys
            elif tool == "step":
                here = kw["name"] in steps
            elif tool == "stats":
                curves = {c.upper() for c in kw["curves"]}
                here = bool(curves & set(f.inv.curves)) and (need - curves) <= set(f.inv.curves)
            else:
                here = need <= set(f.inv.curves)
            try:
                TOOLS[tool](f, **kw)
                ok = True
            except ToolError as e:
                ok, msg = False, str(e)
            if here and not ok:
                bad.append((t.well, entry, msg[:120]))
            if here is False and not ok and not re.search(r"curves with data|sections:|steps:|in a section", msg):
                bad.append((t.well, entry, "error does not say what exists", msg[:120]))
            ran[entry] += ok
    never = [e for _, e, _, _ in sources() if not ran[e]]
    print(f"\nD2: {len(sources())} sources; never ran on this dataset: {len(never)}")
    for e in never:
        print("   ", e)
    assert not bad, bad[:10]


@pytest.mark.data
def test_d2_a_guide_for_a_formation_lists_only_what_runs_there():
    from test_b2_tools import F
    from petroharness.agent.toolset import TOOLS
    from petroharness.agent.direction import gated
    bad, dropped = [], 0
    for t, f in F():
        for name in LIB.facets:
            text = LIB.guide(name, f)
            block = re.search(r"^Compare:\n((?:  - .*\n?)*)", text, re.M)
            if block and re.search(r"\b(no|without|missing|absent|lacks?)\b", block.group(1), re.I):
                bad.append((t.well, name, "says what is absent"))
            for raw in LIB.facets[name]["compare"]:
                entry = gated(raw)[1]
                p = parse_source(entry)
                listed = f"  - {entry}" in text
                if p is None:
                    if not listed:
                        bad.append((t.well, name, "template dropped", entry))
                    continue
                try:
                    TOOLS[p[0]](f, **p[1])
                    ok = True
                except ToolError:
                    ok = False
                if listed and not ok:
                    bad.append((t.well, name, "listed but fails", entry))
                dropped += not listed
    print(f"\nD2: sources left out of guides because their data is not here: {dropped}")
    assert not bad, bad[:10]


def test_d2_the_gate_mechanism_for_candidate_lines():
    """The skills are generic (no switch tags; tests/agent/test_skills.py). A candidate line under measurement may carry a
    gate: '[option] text' shows while the option is on, '[!option] text' while it is off, several tags must all hold."""



# --- the index and the Compare lines on a formation of each configured dataset --------------------------------------

def _dataset_configs() -> list:
    """The data config in use and the dataset configs beside it (YAML files with exactly a data and an eval section whose
    LAS folder exists): on this machine GeoLink, Costa and Danish."""
    import yaml
    from petroharness.config import data_file
    here = data_file()
    if not here.exists():
        return []
    out = []
    for p in sorted(here.parent.glob("*.yaml")):
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except Exception:  # noqa: BLE001  (not a data config)
            continue
        if isinstance(d, dict) and set(d) == {"data", "eval"} and Path(str(d["data"].get("las_dir"))).is_dir() \
                and d["eval"].get("questions") and Path(str(d["eval"]["questions"])).exists():
            out.append(p)
    return out


def _formations(path: Path) -> list:
    """The formations of a dataset config, each once, built as the harness builds them (the config passed explicitly,
    whatever PETROHARNESS_DATA names), on the default reporting settings (every basis, no conventions, whatever the
    data file sets: test_b0_inventory.default_reporting)."""
    import warnings
    import yaml
    from petroharness.agent.inventory import from_view
    from petroharness.agent.tools import Formation
    from petroharness.config import DataPaths, EvalPaths, HarnessConfig
    from petroharness.record.store import build as build_store
    from petroharness.tasks import load_tasks
    from petroharness.well.view import FormationView
    d = yaml.safe_load(path.read_text())
    cfg = HarnessConfig(data=DataPaths(**{**d["data"], "basis": "all", "conventions": []}), eval=EvalPaths(**d["eval"]))
    tasks, _ = load_tasks(cfg.eval.questions, cfg.data.las_dir)
    out, seen = [], set()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for t in tasks:
            k = (str(t.las_path), t.formation)
            if k in seen:
                continue
            seen.add(k)
            v = FormationView.build(t, cfg.for_tasks())
            s = build_store(v)
            out.append((t, Formation(from_view(v, s), v, s)))
    return out


def _rendered(f, name: str) -> list:
    block = re.search(r"^Compare:\n((?:  - .*\n?)*)", LIB.guide(name, f), re.M)
    return [ln[4:] for ln in block.group(1).splitlines()] if block else []


@pytest.mark.data
def test_the_index_renders_and_each_guide_it_names_renders_for_a_formation():
    """The step prompt's DIRECTION for a formation: one line per guide, and each guide it names renders for that
    formation (its Compare lines those that run there)."""
    from test_b2_tools import F
    t, f = F()[0]
    text = LIB.index(["porosity"])
    named = [ln.strip().split(":", 1)[0] for ln in text.splitlines()[1:] if not ln.strip().endswith(":")]
    assert sorted(named) == sorted(LIB.facets) and len(named) == len(set(named))
    for name in named:
        g = LIB.guide(name, f)
        assert g.startswith(f"{name} (when: {LIB.facets[name]['when']})") and "\nDecide:\n" in g, name


@pytest.mark.data
@pytest.mark.parametrize("config", _dataset_configs(), ids=lambda p: p.stem)
def test_every_compare_line_parses_and_renders_on_each_configured_dataset(config):
    """Every Compare line of every guide parses (a lookup, or a template: a recipe the model fills); on each formation
    of the dataset a guide lists exactly the lookups that run there (a listed line runs, an unlisted one fails there),
    templates always; and each area guide lists at least one lookup on some formation of the dataset."""
    from petroharness.agent.toolset import TOOLS
    fs = _formations(config)
    assert fs, config
    bad, shown = [], Counter()
    for t, f in fs:
        for name in LIB.facets:
            listed = _rendered(f, name)
            for entry in LIB.facets[name]["compare"]:
                p = parse_source(entry)
                if p is None:                               # a template (a recipe the model fills): always listed
                    if entry not in listed:
                        bad.append((t.well, name, "template dropped", entry))
                    continue
                try:
                    TOOLS[p[0]](f, **p[1])
                    ok = True
                except ToolError:
                    ok = False
                if ok != (entry in listed):
                    bad.append((t.well, name, "listed but fails" if not ok else "runs but not listed", entry))
                shown[name] += ok
    bad += [("dataset", name, "no line runs on any formation") for name in LIB.facets if name not in COMMON and not shown[name]]
    print(f"\n{config.stem}: {len(fs)} formations; lines that ran, by guide: {dict(shown)}")
    assert not bad, bad[:10]
