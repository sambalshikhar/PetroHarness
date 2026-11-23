"""The READ call (the model reads the question and chooses its topic areas) and what its topics key - the
first look, the index's order, the map's notes - with a stub model; a run whose READ replies cannot be read goes on.

    .venv/bin/python -m pytest tests/agent/test_read.py -q   (PETROHARNESS_DATA selects the dataset)
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness.agent import components as C  # noqa: E402
from petroharness.agent import direction  # noqa: E402
from petroharness.agent.prompts import CORE_CURVES, MINERAL_VOLUMES  # noqa: E402
from petroharness.agent.read import read_schema
from petroharness.llm import Usage  # noqa: E402
from _support.model import ScriptedModel  # noqa: E402

TOPICS = ROOT / "src" / "petroharness" / "resources" / "topics.yaml"
DONE = {"edits": [], "next": [], "done": True}
STEP1 = {"asks": "How porous is the formation?", "points": ["How does porosity vary by zone?"], "intent": "characterize",
         "focus": "porosity", "edits": [{"op": "add", "point": 1, "text": "Porosity is likely moderate", "grade": "hypothesis"}],
         "next": [], "done": True}
VALID = {"topics": ["porosity", "shale_clay"], "named": ["RDEP"]}


def read_model(reads, cls=ScriptedModel) -> ScriptedModel:
    """The READ replies from a list, step 1's object, then done; the writer (and its repairs) a short answer."""
    return cls({"read*": list(reads), "step_1": STEP1, "step_*": DONE, "settle*": DONE},
                         default="## Porosity\nThe porosity is read zone by zone.\n\n{{ZONE_TABLE}}")


def _formation(pred):
    from _support.formations import F
    got = next(((t, f) for t, f in F() if pred(f)), None)
    if got is None:
        pytest.skip("no formation of that kind in this dataset")
    return got


def _session(t, f):
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.state import Session
    from petroharness.agent.map import render
    return Session(t, f, render(f.inv), Ledger(f))


def _run(monkeypatch, reads, pred=lambda f: "PHIE" in f.inv.curves and "RDEP" in f.inv.curves, depth=True):
    """One question through the question graph on a built session, the model stubbed. depth: graph.answer's (False:
    every question investigated, --investigate)."""
    from petroharness.agent import graph
    from petroharness.agent.state import Session
    t, f = _formation(pred)
    s = _session(t, f)
    monkeypatch.setattr(Session, "build", classmethod(lambda cls, task, cfg: s))
    llm = read_model(reads)
    out = graph.answer(t, "k2-horizon-7b", 1, 2, "open", "profile", llm_factory=lambda cfg: llm, depth=depth)
    assert not out["trace"].get("error"), out["trace"].get("traceback")
    return s, llm, out


def _heads(text: str) -> list:
    """The area headings of the DIRECTION index, in order (an area's one guide is the area's line,
    'name: when'; common is a heading over its guides)."""
    return [ln.strip().split(":", 1)[0] for ln in text.splitlines()[1:] if re.match(r"^  \S", ln)]


def _direction(prompt: str) -> str:
    return prompt.split("DIRECTION\n", 1)[1].split("\n\n", 1)[0]


# --- the schema and the index ----------------------------------------------------------------------------------------

def test_the_read_schema_enum_is_the_index_areas():
    schema = read_schema()
    topics = schema["properties"]["topics"]
    assert topics["items"]["enum"] == list(yaml.safe_load(TOPICS.read_text())["areas"])
    assert (topics["minItems"], topics["maxItems"]) == (1, 4)
    assert set(schema["required"]) == set(schema["properties"]) == {"topics", "named"}       # nothing else
    assert schema["properties"]["named"]["maxItems"] == 12


@pytest.mark.parametrize("topics", [["permeability_rock_quality", "porosity"], ["data_quality"], []])
def test_the_index_lists_each_guide_under_each_of_its_areas_the_chosen_first(topics):
    lib = direction.plugged()
    if lib is None:
        pytest.skip("no skill library plugged (PETROHARNESS_SKILLS=none)")
    text = lib.index(topics)
    heads, areas = _heads(text), list(direction.areas())
    assert heads == topics + ["common"] + [a for a in areas if a not in topics]
    under, cur = {}, None
    for ln in text.splitlines()[1:]:
        name = ln.strip().split(":", 1)[0]
        if re.match(r"^  \S", ln):
            cur = name
            if not ln.endswith(":"):                                # the area's one guide, on the area's line
                under.setdefault(cur, []).append(name)
        else:
            under.setdefault(cur, []).append(name)
    want = {"common": list(lib.common), **{a: lib.on(a) for a in direction.areas()}}
    assert under == want
    counts = Counter(g for gs in under.values() for g in gs)
    for g in lib.facets:                                           # every guide, once per area it sits under
        assert counts[g] == sum(g in gs for gs in want.values()) >= 1, g


def test_families_and_overview_follow_the_topics_in_order():
    assert direction.families(["porosity", "shale_clay"]) == ["porosity", "lithology"]
    assert direction.families(["invasion_movability", "hydrocarbon_detection"]) == ["saturation", "permeability",
                                                                                    "hydrocarbon"]
    assert direction.families([]) == [] and direction.overview([]) == []
    ov = direction.overview(["water_saturation", "hydrocarbon_detection"])
    assert ov[:6] == ["SW", "RDEP", "RW", "PHIE", "VCL", "BVW"] and ov[6:] == ["CROSSOVER_FLAG", "NET_PAY"]


# --- the READ call in the run ----------------------------------------------------------------------------------------

@pytest.mark.data
@pytest.mark.parametrize("depth", [True, False], ids=["the route read", "investigate"])
def test_a_valid_reading_sets_the_topics_the_first_look_and_the_index(monkeypatch, depth):
    from petroharness.agent.read import READ
    from petroharness.agent.prompts import brief
    from petroharness.agent.map import render
    s, llm, out = _run(monkeypatch, [VALID], depth=depth)
    tr = out["trace"]
    assert tr["read"]["parse"] == "ok" and tr["topics"] == VALID["topics"] and "category" not in tr
    assert {k: tr["read"][k] for k in VALID} == VALID and tr["read"]["reply"] == json.dumps(VALID)
    assert s.topics == VALID["topics"] and s.families == ["porosity", "lithology"]
    assert s.map == render(s.f.inv, ["porosity", "lithology"]) and tr["map_chars"] == len(s.map)
    call = llm.sent[0]                     # the brief; C5 read, the question, the map, the areas; the schema
    assert call["stage"] == "read" and call["schema"] == read_schema(depth) and call["messages"][0]["content"] == brief()
    user = call["messages"][1]["content"]
    text = C.text("C5", "read_depth") if depth else READ               # the route asked for, or not (--investigate)
    assert user.startswith(text + "\n\nQUESTION:\n" + s.task.question) and "\nTHE MAP\n" in user
    assert tr["read"]["depth"] == "investigate" if depth else "depth" not in tr["read"]   # said nothing: investigate
    assert user.split("TOPIC AREAS:\n", 1)[1].splitlines() == [f"{n} - {a['when']}" for n, a in direction.areas().items()]
    assert {"C5", "C6", "C7"} <= {seg[0] for seg in tr["calls"][0]["messages"][1]["segments"]}
    look = [str(c) for c in s.ledger.items[0].args["curves"]]     # the topics' key curves, then the named curve
    own = [c for c in direction.overview(VALID["topics"]) if c in s.f.inv.curves][:8]
    assert look[:len(own)] == own and "RDEP" in look[len(own):]
    step1 = llm.prompt("step_1")
    assert _heads(_direction(step1)) == VALID["topics"] + ["common"] + [a for a in direction.areas()
                                                                        if a not in VALID["topics"]]
    assert "YOUR TOPICS: porosity, shale_clay\n\n" in step1 and "YOUR READING" not in step1
    assert "FIRST LOOK (each zone's key curves for the topics you chose: porosity, shale_clay; opened for you):" in step1


@pytest.mark.data
def test_an_unreadable_reply_then_a_valid_one_is_a_retry(monkeypatch):
    s, llm, out = _run(monkeypatch, ["The topics are porosity and clay.", VALID])
    tr = out["trace"]
    assert tr["read"]["parse"] == "retry" and tr["topics"] == VALID["topics"] and s.topics == VALID["topics"]
    assert [c["stage"] for c in llm.sent[:2]] == ["read", "read_retry"]
    assert llm.sent[1]["messages"] == llm.sent[0]["messages"] and llm.sent[1]["schema"] == llm.sent[0]["schema"]


@pytest.mark.data
def test_two_unreadable_replies_fail_the_reading_and_the_run_goes_on(monkeypatch):
    from petroharness.agent.map import render
    bad = ['{"topics": ["no_such_area"], "named": []}', ""]
    s, llm, out = _run(monkeypatch, bad)
    tr = out["trace"]
    assert tr["read"]["parse"] == "failed" and tr["topics"] == [] and s.topics == [] and s.families == []
    assert out["status"] in ("ok", "unresolved_numbers") and out["answer"].strip()
    assert s.map == render(s.f.inv)                                     # no topics: every note
    step1 = llm.prompt("step_1")
    assert "YOUR TOPICS" not in step1 and "FIRST LOOK (each zone's key curves, opened for you):" in step1
    assert _heads(_direction(step1)) == ["common"] + list(direction.areas())     # the index in its own order
    look = [str(c) for c in s.ledger.items[0].args["curves"]]
    assert look == [c for c in CORE_CURVES if c in s.f.inv.curves]      # the general first look


@pytest.mark.parametrize("reply, topics", [
    ('{"topics": ["porosity", "no_such_area", "porosity"], "named": []}', ["porosity"]),
    ('{"topics": ["porosity"], "asks": "a", "readings": ["x"], "named": ["GR"]}', ["porosity"]),   # other keys unread
    ('{"topics": [], "named": []}', None),
    ('["porosity"]', None),
    ('```json\n{"topics": ["porosity"]}\n```', None),
])
def test_what_counts_as_a_readable_reply(reply, topics):
    from petroharness.agent.read import _reading
    got = _reading(reply)
    if topics is None:
        assert got is None
    else:
        assert got["topics"] == topics and set(got) == {"topics", "named"}


# --- the first look: the named curves, the mineral volumes -----------------------------------------------------------

def _look(t, f, topics, named):
    from petroharness.agent.read import read_question
    from petroharness.agent.graph import investigate
    s = _session(t, f)
    llm = read_model([{"topics": topics, "named": named}])
    trace = {}
    read_question(llm, s, Usage(), 4000, trace)
    investigate(llm, s, Usage(), 4000, trace, max_steps=1)
    return s, [str(c) for c in s.ledger.items[0].args["curves"]]


OTHER = ("RDEP", "DTC", "PEF", "CALI")


@pytest.mark.data
def test_a_named_mnemonic_the_formation_has_is_in_the_first_look():
    from petroharness.agent.prompts import named_curves
    t, f = _formation(lambda f: "PHIE" in f.inv.curves and any(c in f.inv.curves for c in OTHER))
    extra = next(c for c in OTHER if c in f.inv.curves)
    assert extra not in direction.overview(["porosity"]) + list(CORE_CURVES)
    s, look = _look(t, f, ["porosity"], [extra])
    assert extra in look
    s, look = _look(t, f, ["porosity"], [])
    assert extra not in look                                          # it came from the reading
    assert named_curves(f, [extra.lower()]) == [extra]                # the whole name, any case
    if "RDEP" in f.inv.curves:                                        # the registry's vocabulary
        assert named_curves(f, ["deep resistivity"]) == ["RDEP"]
    if "RHOB" in f.inv.curves:
        assert named_curves(f, ["bulk density log"]) == ["RHOB"]
    if "PHIE" in f.inv.curves:
        assert named_curves(f, ["effective porosity (PHIE)"]) == ["PHIE"]


@pytest.mark.data
def test_a_named_mnemonic_the_formation_lacks_is_not():
    from petroharness.agent.prompts import named_curves
    t, f = _formation(lambda f: "PHIE" in f.inv.curves)
    reg = f.view.reg.curves["inventory"]
    absent = next(c for c in reg["raw"] + reg["derived"] if c not in f.inv.curves)
    assert named_curves(f, [absent, "a quantity no vocabulary names"]) == []
    s, look = _look(t, f, ["porosity"], [absent])
    assert absent not in look


@pytest.mark.data
def test_lithology_mineralogy_adds_the_mineral_volumes():
    t, f = _formation(lambda f: any(c in f.inv.curves for c in MINERAL_VOLUMES[1:]))
    have = [c for c in MINERAL_VOLUMES if c in f.inv.curves]
    s, look = _look(t, f, ["lithology_mineralogy"], [])
    assert all(c in look for c in have), (look, have)
    s, look = _look(t, f, ["porosity"], [])
    assert not [c for c in have if c in look and c not in direction.overview(["porosity"]) + list(CORE_CURVES)], look


# --- READ keeps to the question -------------------------------------------------------------------------------------

AMBIGUITY = ("If the question can be read in more than one way, say in point 1 which reading you answer, or answer each "
             "where they need different evidence.")


def test_the_read_text_asks_for_topics_and_named_only():
    from petroharness.agent.read import READ
    assert "- topics:" in READ and "- named:" in READ and "in its own words" in READ
    assert "readings" not in READ.lower() and "asks" not in READ.lower()
    assert READ.rstrip().endswith('{"topics": ["<area>"], "named": ["..."]}')


@pytest.mark.parametrize("plugged", [True, False])
def test_step_1_holds_the_ambiguity_sentence(plugged):
    from petroharness.agent.prompts import step1
    text = step1() if plugged else step1(None)
    assert AMBIGUITY in text and text.index("(point 1)") < text.index(AMBIGUITY) < text.index("For example")


@pytest.mark.data
@pytest.mark.parametrize("depth", [True, False], ids=["the route read", "investigate"])
def test_no_prompt_carries_readings_and_step_1_shows_the_topics(monkeypatch, depth):
    """A whole stub run: the READ prompt asks for topics and named (and the route) only, step 1 shows YOUR TOPICS and
    the ambiguity sentence, no message of any call (READ, steps, settle, writer) holds a readings field or YOUR
    READING, and point 1 is step 1's asks."""
    old = dict(VALID, asks="Probe asks sentence?", readings=["probe reading one", "probe reading two"])  # extra fields
    s, llm, out = _run(monkeypatch, [old], depth=depth)
    tr = out["trace"]
    want = {"reply", "parse", "topics", "named"} | ({"depth"} if depth else set())
    assert set(tr["read"]) == want and tr["read"]["topics"] == VALID["topics"]
    assert s.reading == {"topics": VALID["topics"], "named": VALID["named"], **({"depth": "investigate"} if depth else {})}
    step1 = llm.prompt("step_1")
    assert "YOUR TOPICS: porosity, shale_clay\n\n" in step1 and AMBIGUITY in step1
    for call in llm.sent:
        for m in call["messages"]:
            text = m["content"]
            assert '"readings"' not in text and "YOUR READING" not in text and "readings (1)" not in text, call["stage"]
            assert "probe reading" not in text and "Probe asks" not in text, call["stage"]
    assert s.points[0] == STEP1["asks"]                       # point 1 is step 1's asks


@pytest.mark.data
def test_a_step_records_its_own_prompt_tokens_not_a_fix_calls(monkeypatch):
    """Step 1's reply cannot be read and a fix call reformats it: the step's prompt_tokens are the step call's."""
    class Broken(ScriptedModel):
        def chat(self, stage, messages, usage, max_tokens, json_schema=None, temperature=None, retry=False):
            out = super().chat(stage, messages, usage, max_tokens, json_schema, temperature, retry)
            if stage == "step_1":
                usage.log[-1]["prompt_tokens"] = 18309
                return "{points: [How does porosity vary by zone?], edits: none"          # not JSON, not salvageable
            if stage == "step_1_fix":
                usage.log[-1]["prompt_tokens"] = 400
                return json.dumps(STEP1)
            return out

    from petroharness.agent import graph
    from petroharness.agent.state import Session
    t, f = _formation(lambda f: "PHIE" in f.inv.curves and "RDEP" in f.inv.curves)
    s = _session(t, f)
    monkeypatch.setattr(Session, "build", classmethod(lambda cls, task, cfg: s))
    llm = read_model([VALID], Broken)
    out = graph.answer(t, "k2-horizon-7b", 1, 2, "open", "profile", llm_factory=lambda cfg: llm, depth=False)
    step = out["trace"]["steps"][0]
    assert [c["stage"] for c in llm.sent][:3] == ["read", "step_1", "step_1_fix"]
    assert step["repaired"]["by"] == "fix" and step["prompt_tokens"] == 18309
