"""A pluggable skill library. The harness owns the topic areas (resources/topics.yaml); a library is a folder; one
setting picks it (skills: <path> | none, PETROHARNESS_SKILLS overrides). With the researched library plugged the
prompts are the no-change fixture's (tests/agent/fixtures/prompts.json.gz) byte for byte; with none no model-facing text
speaks of guides and a guide call is said back as not run; a second library is listed and read; a bad library fails
at load, every problem said at once.

    .venv/bin/python -m pytest tests/agent/test_skill_library.py -q   (PETROHARNESS_DATA selects the dataset)
"""
import gzip
import json
import re
import shutil
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness.agent import components as C, direction, loop  # noqa: E402
from petroharness.config import DEFAULT_SKILLS, RESOURCES, SKILLS_ENV, HarnessConfig  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MINI = (FIXTURES / "skill_library_mini").resolve()          # a second library: two guides on two areas
PROMPTS = FIXTURES / "prompts.json.gz"                         # the fixture's strings, rendered by prompt_fixture.py
ROWS = json.loads(gzip.decompress(PROMPTS.read_bytes()))["tasks"] if PROMPTS.exists() else []   # kept with the
#   benchmark data, outside the public repository; the fixture tests skip without it
RESEARCHED = direction.load((RESOURCES / DEFAULT_SKILLS).resolve())     # the packaged researched library


def _cfg(**kw):
    """A configuration with no data settings read (the skill setting is all these tests use)."""
    return HarnessConfig.model_validate({"data": {"las_dir": "/nonexistent"}, "eval": None, **kw})


# --- the setting ------------------------------------------------------------------------------------------------------

def test_the_default_is_the_packaged_researched_library(monkeypatch):
    monkeypatch.delenv(SKILLS_ENV, raising=False)
    lib = direction.plugged()
    assert DEFAULT_SKILLS == "skills/researched" and HarnessConfig.model_fields["skills"].default == DEFAULT_SKILLS
    assert lib.name == "researched" and lib.path == (RESOURCES / DEFAULT_SKILLS).resolve()
    assert lib is direction.plugged(_cfg()) and re.fullmatch(r"[0-9a-f]{12}", lib.version)
    assert direction.stamp(lib) == {"library": "researched", "version": lib.version}
    assert direction.stamp(None) == {"library": "none", "version": None}


def test_the_setting_a_path_or_none_and_the_environment_overrides_it(monkeypatch):
    monkeypatch.delenv(SKILLS_ENV, raising=False)
    cfg = _cfg(skills=str(MINI))                                    # an absolute path
    assert direction.plugged(cfg).name == "mini" and cfg.for_tasks().skills == str(MINI)
    assert direction.plugged(_cfg(skills="none")) is None and direction.plugged(_cfg(skills=" None ")) is None
    assert direction.plugged(_cfg(skills=DEFAULT_SKILLS)).name == "researched"     # relative to the package's resources
    monkeypatch.setenv(SKILLS_ENV, "none")                          # the environment overrides the configuration
    assert direction.plugged(cfg) is None and direction.plugged() is None
    monkeypatch.setenv(SKILLS_ENV, str(MINI))
    assert direction.plugged(_cfg(skills="none")).name == "mini"
    with pytest.raises(ValueError, match="skill"):                  # a misspelt key raises (the config is strict)
        _cfg(skill="none")


def test_a_folder_that_is_no_library_fails_with_what_why_fix(tmp_path):
    with pytest.raises(direction.LibraryError, match=r"^WHAT: no skill library at .*\. WHY: .*\. FIX: .*none"):
        direction.load(tmp_path)


# --- the texts with and without a library -------------------------------------------------------------------------------

def test_the_guide_fragments_are_in_with_a_library_and_out_with_none(monkeypatch):
    """C1 brief, C5 step 1 and C8 not_run: with a library their guide fragments are in place; with none the same texts
    without them, and nothing in them speaks of guides."""
    monkeypatch.delenv(SKILLS_ENV, raising=False)
    lib, n = RESEARCHED, str(loop.ACTIONS)
    on, off = loop.brief(lib), loop.brief(None)
    assert C.text("C1", "brief_direction") in on and C.text("C1", "brief_guide").replace("{ACTIONS}", n) in on
    assert off == on.replace(C.text("C1", "brief_direction"), "").replace(C.text("C1", "brief_guide").replace("{ACTIONS}", n), "")
    on1, off1 = loop.step1(lib), loop.step1(None)
    call = C.fill("C5", "step1_guide_call", guide="net_reservoir_pay")    # the researched guide on the example's topic
    assert call == '{"guide": "net_reservoir_pay"}, ' and call in on1
    assert off1 == on1.replace(C.text("C5", "step1_guides").replace("{ACTIONS}", n), "").replace(call, "")
    assert json.loads(off1[off1.index('{"asks"'):])["next"][0] == {"section": {"key": "hydrocarbon.petrophysical_hydrocarbon_indicators"}}
    note_on = C.fill("C8", "not_run", items="x", guide=C.text("C8", "not_run_guide"))
    note_off = C.fill("C8", "not_run", items="x", guide="")
    assert note_on.endswith("get, find, guide and calc.") and note_off.endswith("get, find and calc.")
    for text in (off, off1, note_off):
        assert "guide" not in text.lower() and "DIRECTION" not in text
    assert loop.brief() == on and loop.step1() == on1                 # left out: the plugged library (researched)


def test_with_no_library_a_guide_call_is_no_action():
    assert loop.coerce_action({"guide": "porosity"}) == ("guide", "porosity")
    for a in ({"guide": "porosity"}, {"tool": "guide", "facet": "porosity"}, {"action": "guide", "name": "x"}):
        assert loop.coerce_action(a, guides=False) is None, a
    assert loop.coerce_action({"stats": ["SW"]}, guides=False) == ("tool", "stats", {"curves": ["SW"]})


def test_a_second_library_example_names_its_own_guide():
    mini = direction.load(MINI)
    text = loop.step1(mini)                                         # no guide on the example's topic: its first guide
    assert json.loads(text[text.index('{"asks"'):])["next"][0] == {"guide": "clay_volume"}
    assert loop.brief(mini) == loop.brief(RESEARCHED)               # any library: the same brief


# --- a second library ---------------------------------------------------------------------------------------------------

def test_a_second_library_is_listed_under_the_areas_its_guides_serve():
    mini = direction.load(MINI)
    assert mini.name == "mini" and mini.common == () and list(mini.facets) == ["clay_volume", "pore_space"]
    assert mini.on("porosity") == ["pore_space"] and mini.on("shale_clay") == ["clay_volume"] and not mini.on("fluid_contacts")
    when = {g: f["when"] for g, f in mini.facets.items()}
    assert mini.index(["porosity"]).splitlines() == [
        "Direction by topic area, your topics first (guide FACET reads one):",
        "  porosity:", f"    pore_space: {when['pore_space']}",
        "  shale_clay:", f"    clay_volume: {when['clay_volume']}"]                 # no common; no empty area
    assert mini.index().splitlines()[0] == "Direction by topic area (guide FACET reads one):"
    assert mini.guide("pore_space").startswith(f"pore_space (when: {when['pore_space']})\nConsider:\n")
    assert mini.guide("porosity") == "no facet 'porosity'; facets: clay_volume, pore_space"


class Stub:
    """A model by stage: READ from its reply, step 1 from its reply, then done; the writer a short answer. Every call
    is kept."""

    def __init__(self, step1):
        self.step1, self.sent = step1, []

    def replays_reasoning(self):
        return True

    def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
        self.sent.append({"stage": stage, "messages": messages})
        usage.log.append({"stage": stage, "prompt_tokens": sum(len(m["content"]) for m in messages) // 4})
        if stage.startswith("read"):
            r = {"topics": ["porosity", "shale_clay"],
                 "named": ["PHIE"]}
        elif stage == "step_1":
            r = self.step1
        elif stage.startswith(("step_", "settle")):
            r = {"edits": [], "next": [], "done": True}
        else:                                                   # the writer and its repairs
            r = "## Porosity\nThe porosity is read zone by zone.\n\n{{ZONE_TABLE}}"
        return r if isinstance(r, str) else json.dumps(r)

    def prompt(self, stage):
        return next(c["messages"][-1]["content"] for c in self.sent if c["stage"] == stage)


def _run(monkeypatch, nxt):
    """One question through the question graph, the model stubbed; step 1 runs the actions nxt. The session is built
    after the setting is made (it plugs the library in force)."""
    from test_b2_tools import F
    from petroharness.agent import graph
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.loop import Session
    from petroharness.agent.map import render
    t, f = next(((t, f) for t, f in F() if "PHIE" in f.inv.curves and "VCL" in f.inv.curves), (None, None))
    if t is None:
        pytest.skip("no formation with PHIE and VCL in this dataset")
    s = Session(t, f, render(f.inv), Ledger(f))
    monkeypatch.setattr(Session, "build", classmethod(lambda cls, task, cfg: s))
    llm = Stub({"asks": "How porous is the formation?", "points": ["How does porosity vary by zone?"],
                "intent": "characterize", "focus": "porosity",
                "edits": [{"op": "add", "point": 1, "text": "Porosity is likely moderate", "grade": "hypothesis"}],
                "next": nxt, "done": False})
    out = graph.answer(t, "k200t", 1, 2, "open", "profile", llm_factory=lambda cfg: llm)
    assert not out["trace"].get("error"), out["trace"].get("traceback")
    return s, llm, out


@pytest.mark.data
def test_a_second_library_plugged_by_the_environment_is_listed_and_read_in_a_run(monkeypatch):
    monkeypatch.setenv(SKILLS_ENV, str(MINI))
    s, llm, out = _run(monkeypatch, [{"guide": "pore_space"}, {"stats": {"curves": ["PHIE"]}}])
    mini, tr = direction.load(MINI), out["trace"]
    assert s.library is mini and tr["skills"] == {"library": "mini", "version": mini.version}
    step1 = llm.prompt("step_1")
    assert f"\n\nDIRECTION\n{mini.index(['porosity', 'shale_clay'])}\n\n" in step1 and "net_reservoir_pay" not in step1
    want = mini.sections("pore_space", s.f)                             # opened first, then its workflow stats
    assert tr["guides"] == ["pore_space"] and tr["steps"][0]["guide_sections"][:len(want)] == want
    step2 = llm.prompt("step_2")
    assert f"GUIDE {mini.guide('pore_space', s.f)}" in step2
    line = mini.facets["pore_space"]["consider"][0]                     # a guide line in GUIDES is C6's
    at = step2.index(line)
    user = next(c for c in tr["calls"] if c["stage"] == "step_2")["messages"][1]["segments"]
    assert [seg[0] for seg in user if seg[2] <= at < seg[3]] == ["C6"]


# --- none ---------------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_with_no_library_no_model_facing_text_speaks_of_guides_and_the_run_completes(monkeypatch):
    monkeypatch.setenv(SKILLS_ENV, "none")
    s, llm, out = _run(monkeypatch, [{"stats": {"curves": ["PHIE"]}}])
    tr = out["trace"]
    assert s.library is None and tr["skills"] == {"library": "none", "version": None} and tr["guides"] == []
    assert out["status"] in ("ok", "unresolved_numbers") and out["answer"].strip()
    stages = [c["stage"] for c in llm.sent]
    assert {"read", "step_1", "step_2", "settle", "writer"} <= set(stages), stages
    for c in llm.sent:                                 # the brief, READ, the steps, settle, the writer and its repairs
        for m in c["messages"]:
            assert "guide" not in m["content"].lower() and "DIRECTION" not in m["content"], (c["stage"], m["role"])
    assert "TOPIC AREAS:" in llm.prompt("read") and tr["topics"] == ["porosity", "shale_clay"]   # the harness's areas


@pytest.mark.data
def test_with_no_library_a_guide_call_comes_back_as_not_run(monkeypatch):
    monkeypatch.setenv(SKILLS_ENV, "none")
    s, llm, out = _run(monkeypatch, [{"guide": "porosity"}, {"stats": {"curves": ["PHIE"]}}])
    rec = out["trace"]["steps"][0]
    assert rec["unread"] == ['{"guide": "porosity"}'] and rec["guide_sections"] == [] and s.guides == []
    assert rec["actions"] == ['stats {"curves": ["PHIE"]}']
    step2 = llm.prompt("step_2")
    note = C.fill("C8", "not_run", items='{"guide": "porosity"}', guide="")
    assert note in step2 and note.endswith("Actions are the tools listed (as {\"tool name\": {arguments}}), get, find and calc.")
    assert "GUIDE" not in step2 and "guide" not in step2.replace('{"guide": "porosity"}', "").lower()
    assert s.run(("guide", "porosity"))[0] == C.fill("C8", "not_run", items="guide porosity", guide="")


# --- a bad library fails at load ------------------------------------------------------------------------------------------

def _copy(tmp_path) -> Path:
    lib = tmp_path / "lib"
    shutil.copytree(MINI, lib)
    return lib


def _edit_skill(lib: Path, name: str, change) -> None:
    p = lib / name / "SKILL.md"
    f = direction.read_skill(p.read_text())
    change(f)
    p.write_text(direction.write_skill(name, f))


def test_a_guide_on_an_unknown_area_fails_at_load(tmp_path):
    lib = _copy(tmp_path)
    _edit_skill(lib, "pore_space", lambda f: f["areas"].append("pore_pressure"))
    with pytest.raises(direction.LibraryError) as e:
        direction.load(lib)
    assert ("- WHAT: pore_space declares areas that are not topic areas: ['pore_pressure']. WHY: the harness owns the "
            "topic areas; a library cannot add one. FIX: use names from ") in str(e.value)


def test_a_line_with_no_sources_row_fails_at_load(tmp_path):
    lib = _copy(tmp_path)
    _edit_skill(lib, "clay_volume", lambda f: f["decide"].append("Compare shale volume with porosity zone by zone."))
    with pytest.raises(direction.LibraryError, match=r"WHAT: clay_volume has 2 decide lines and 1 sources rows\. WHY: "
                                                      r"every Decide, Know, Easily misread and Do not state line has "
                                                      r"its provenance row"):
        direction.load(lib)


def test_every_problem_of_a_library_is_said_at_once(tmp_path):
    lib = _copy(tmp_path)
    (lib / "library.yaml").write_text("name: bad\ndescription: x\ncommon: [answer]\nextra: 1\n")
    (lib / "notes").mkdir()                                             # a folder with no SKILL.md
    _edit_skill(lib, "pore_space", lambda f: f["compare"].append("plot PHIE   (a lookup the harness has not)"))
    _edit_skill(lib, "clay_volume", lambda f: f.update(areas=[]))       # neither common nor on an area
    (lib / "clay_volume" / "sources.yaml").write_text("decide: [{class: a}]\nknow: [{class: a, refs: [Nobody1999]}]\n"
                                                      "ceiling: [{class: b}]\n")
    with pytest.raises(direction.LibraryError) as e:
        direction.load(lib)
    msg = str(e.value)
    want = ["library.yaml has the keys", "the folder notes has no SKILL.md",
            "pore_space: the Compare line 'plot PHIE", "clay_volume decide 1: class a with no refs",
            "clay_volume know 1: refs not in refs.yaml: ['Nobody1999']", "clay_volume ceiling 1: class b with no fact",
            "common names guides the library lacks: ['answer']", "the guides ['clay_volume'] serve no topic area"]
    assert msg.startswith(f"skill library {lib} cannot be used ({len(want)} problems):"), msg.splitlines()[0]
    for w in want:
        assert f"- WHAT: {w}" in msg, w
    assert all(" WHY: " in ln and " FIX: " in ln for ln in msg.splitlines()[1:])


def test_the_version_follows_the_files(tmp_path):
    lib = _copy(tmp_path)
    before = direction.load(lib).version
    direction.load.cache_clear()
    p = lib / "pore_space" / "SKILL.md"
    p.write_text(p.read_text().replace("zone by zone.", "zone by zone, side by side."))
    assert direction.load(lib).version != before
    assert direction.load(MINI).version == before          # a copy has its source's version: content and paths in it


# --- with the researched library plugged, the prompts are the fixture's ----------------------------------------------------

def test_the_prompt_fixture():
    """12 tasks (6 GeoLink, 3 Costa, 3 Danish), five strings each, labelled v3.5."""
    if not ROWS:
        pytest.skip("the prompt fixture is not in this checkout")
    import prompt_fixture
    assert [r["dataset"] for r in ROWS] == ["geolink"] * 6 + ["costa"] * 3 + ["danish"] * 3
    assert all(set(prompt_fixture.STRINGS) <= set(r) and all(r[k] for k in prompt_fixture.STRINGS) for r in ROWS)
    assert json.loads(gzip.decompress(PROMPTS.read_bytes()))["rendered_by"] == "v3.5"


@lru_cache(maxsize=None)
def _tasks(ds: str) -> dict:
    """{qa_id: (task, its configuration)} of a dataset configured beside the data config in use."""
    import prompt_fixture
    from petroharness.config import data_file
    path = data_file().parent / f"{ds}.yaml"
    if not path.exists():
        return {}
    qa_ids = [r["qa_id"] for r in ROWS if r["dataset"] == ds]
    return {q: (t, cfg) for _, q, t, cfg in prompt_fixture.tasks({ds: path}, {ds: qa_ids})}


@pytest.mark.data
@pytest.mark.parametrize("i", range(len(ROWS)), ids=lambda i: f"{ROWS[i]['dataset']}-{ROWS[i]['qa_id'][-4:]}")
def test_with_the_researched_library_plugged_the_prompts_are_the_fixtures(i, monkeypatch):
    """The brief, the READ prompt, the step-1 user prompt, the DIRECTION index and the step-2 user prompt (after two
    guides and an action the harness does not read), byte for byte."""
    import warnings
    import prompt_fixture
    monkeypatch.delenv(SKILLS_ENV, raising=False)
    row = ROWS[i]
    got = _tasks(row["dataset"]).get(row["qa_id"])
    if got is None:
        pytest.skip(f"no {row['dataset']} data config beside the one in use")
    task, cfg = got
    assert task.task_id == row["task_id"] and direction.plugged(cfg).name == "researched"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        now = prompt_fixture.render(task, cfg, i)
    for k in prompt_fixture.STRINGS:
        if now[k] != row[k]:
            at = next((j for j, (a, b) in enumerate(zip(now[k], row[k])) if a != b), min(len(now[k]), len(row[k])))
            pytest.fail(f"{k} differs from the prompt fixture at {at}: {row[k][max(0, at - 60):at + 60]!r} -> {now[k][max(0, at - 60):at + 60]!r}")
