"""Brick 4a of docs/designs/zones-and-intervals.md: a question's scope. Under reach "well" the READ call also says the
stretches of the well the question is about (its `scope`: a unit, a depth range, the user's zones, "the whole well";
[] for the interval); the harness checks it as a selection and makes it every lookup's default zones (a call's own
zones win; the well's step record and the interval's sections and classes are left as they are); step 1 says the
scope, or why a scope read was not used; the answer's header names it. Under reach "focus" (the benchmark) nothing
changes: no scope in the READ call, none applied.

A scripted model (the prompt fixture's Stub) on GeoLink 30/6-5's Brent Group with its tops file.

    .venv/bin/python -m pytest tests/test_scope.py -q
"""
import json
import re
from dataclasses import replace

import pytest

from _wells import CASES, task_cfg

DONE = {"focus": "x", "edits": [], "next": [], "done": True}


def _session(case=CASES["brent"]):
    from petroharness.agent.loop import Session
    from petroharness.config import given_settings
    task, cfg, data = task_cfg(case, "q")
    with given_settings({"data": data, "eval": {}}):
        return Session.build(task, cfg), data


def _read(s, reply, data):
    from prompt_fixture import Stub
    from petroharness.agent.loop import read_question
    from petroharness.config import given_settings
    from petroharness.llm import Usage
    llm, trace = Stub(reply if isinstance(reply, list) else [reply], DONE), {}
    with given_settings({"data": data, "eval": {}}):
        read_question(llm, s, Usage(), 3000, trace)
    return llm, trace


def _reply(scope=None):
    r = {"topics": ["porosity"], "named": ["porosity"], "depth": "investigate"}
    if scope is not None:
        r["scope"] = scope
    return json.dumps(r)


@pytest.fixture(scope="module")
def brent():
    return _session()


def test_the_read_call_asks_for_the_scope_under_reach_well(brent):
    s, data = brent
    llm, _ = _read(s, _reply([]), data)
    text = llm.sent["read"][1]
    assert "- scope: the stretches of the well the question is about" in text
    assert "This interval is one part of the well" in text and '"every interval in the well"): ["the whole well"]' in text
    assert '"named": ["..."], "scope": ["..."]' in text


def test_a_unit_the_question_names_is_every_lookups_default(brent):
    s, data = brent
    _, trace = _read(s, _reply(["Dunlin GP."]), data)
    assert s.scope == ["Dunlin GP."] and trace["scope"] == {"read": ["Dunlin GP."], "used": ["Dunlin GP."], "note": "",
                                                                     "merged": ""}
    text, _ = s.run(("tool", "stats", {"curves": ["PHIE"]}))
    assert "Selection: DUNLIN GP. 2958-3223 m" in text


def test_a_calls_own_zones_win_over_the_scope(brent):
    s, data = brent
    _read(s, _reply(["Dunlin GP."]), data)
    text, _ = s.run(("tool", "stats", {"curves": ["PHIE"], "zones": ["Z3"]}))
    assert "Selection:" not in text and "Z3 COAL" in text


def test_the_step_record_and_sections_are_not_scoped(brent):
    s, data = brent
    _read(s, _reply(["Dunlin GP."]), data)
    text, _ = s.run(("tool", "step", {"name": "rw"}))
    assert "Selection:" not in text and "ignored zones" not in text


def test_the_whole_well_is_the_wells_span(brent):
    s, data = brent
    _read(s, _reply(["the whole well"]), data)
    lo, hi = s.f.inv.well_span
    assert s.scope == [f"{lo:g}-{hi:g}"], (s.scope, s.scope_note[:200])
    text, _ = s.run(("tool", "stats", {"curves": ["GR"]}))
    assert f"Selection: {lo:g}-{hi:g} m" in text


def _typed(schema: dict, item: str) -> bool:
    """Whether a scope item is one the READ schema decodes to (its enum, or its depth-range pattern)."""
    import re
    kinds = schema["properties"]["scope"]["items"]["anyOf"]
    return any(item in k.get("enum", ()) or ("pattern" in k and re.fullmatch(k["pattern"], item)) for k in kinds)


def test_a_scope_item_is_typed_by_the_read_schema(brent):
    """The READ reply is decoded against its schema (the server's guided decoding), whose scope items are the names a
    selection reads or a depth range: an item with a note after it ('the whole well (590-2671 m) with the McKee
    interval', live round 5; 'TOP-BASE m (the unit, ...' left unclosed) cannot be written, where regexes once cut it
    back. Every typed name resolves alone; a duplicated unit is offered by its depths only."""
    from petroharness.agent import selection
    from petroharness.agent.loop import read_schema, scope_items
    s, _ = brent
    names = selection.names(s.f)
    schema = read_schema(True, True, tuple(names))
    for item in ["the whole well", "2841-2865 m", "2841.0193-2957.9102", "2800-3000 ft", "DUNLIN GP.", "Z3", "ALL"]:
        assert _typed(schema, item), item
    for item in ["the whole well (176.61-3556.08 m) with the Brent interval", "whole well: every interval",
                 "NESS FM. 2841-2865 m (Z1)", "2841-2865 m (the unit, the only stretch", "Nowhere Fm."]:
        assert not _typed(schema, item), item
    for n in names:
        selection.resolve(s.f, scope_items(s.f, [n]), force=True)        # each resolves alone (raises if not)


def test_no_scope_names_the_interval_in_force(brent):
    """Question suite B10: after a scope was cleared the next question kept it. Under reach well every question's
    prompt names the stretch in force, the interval itself when no scope is."""
    from petroharness.agent.loop import scope_text
    from petroharness.agent.selection import interval_name
    s, data = brent
    _read(s, _reply([]), data)
    assert scope_text(s).startswith(f"SCOPE: none: every lookup computes on the interval the session opened on, "
                                    f"{interval_name(s.f)}, unless its call names other zones.")


def test_a_scope_that_cannot_be_used_is_said_and_left_out(brent):
    from petroharness.agent.loop import scope_text
    s, data = brent
    _read(s, [_reply(["Nowhere Fm."]), _reply(["Nowhere Fm."])], data)        # asked again once, still unusable
    assert s.scope == [] and s.scope_note.startswith("The scope read from the question (Nowhere Fm.) is not used: ")
    assert scope_text(s).startswith("The scope read from the question")
    text, _ = s.run(("tool", "stats", {"curves": ["PHIE"]}))
    assert "Selection:" not in text


def test_a_scope_that_repeats_an_item_is_asked_once_more_then_read_once_each(brent):
    """Question suite B10, S02, H02 (3 of 304 READ replies): the scope listed "the whole well" three or eight times
    after the unit the question was about, and the union became the whole well. A scope's items are a set, which the
    schema the server decodes with does not hold: a reply that repeats one is asked once more (the READ retry);
    repeated again, the first such reply is read with each item once."""
    s, data = brent
    llm, trace = _read(s, [_reply(["Ness Fm.", "the whole well", "the whole well"]), _reply(["Ness Fm."])], data)
    assert trace["read"]["parse"] == "retry" and trace["scope"]["read"] == ["Ness Fm."], trace["scope"]
    llm, trace = _read(s, [_reply(["Ness Fm.", "Ness Fm."]), _reply(["Etive Fm.", "Etive Fm."])], data)
    assert trace["scope"]["read"] == ["Ness Fm."] and s.scope == ["Ness Fm."], trace["scope"]
    llm, trace = _read(s, [_reply(["Ness Fm.", "Etive Fm."])], data)        # no repeat: read as it is, no retry
    assert trace["read"]["parse"] == "ok" and trace["scope"]["read"] == ["Ness Fm.", "Etive Fm."]


def test_an_empty_scope_is_the_interval(brent):
    s, data = brent
    _read(s, _reply([]), data)
    assert s.scope == [] and s.scope_note == ""


def test_step_one_says_the_scope_and_the_first_look_is_on_it():
    """End to end with the scripted model (the prompt fixture's renderer): READ names the Dunlin; step 1's prompt
    carries the SCOPE line and its first look is computed on the Dunlin."""
    import prompt_fixture
    from petroharness.config import given_settings
    task, cfg, data = task_cfg(CASES["brent"], "e")
    real = prompt_fixture.reads
    prompt_fixture.reads = lambda i, areas: [_reply(["Dunlin GP."])]
    try:
        with given_settings({"data": data, "eval": {}}):
            got = prompt_fixture.render(task, cfg, 0)
    finally:
        prompt_fixture.reads = real
    assert "SCOPE: Dunlin GP. (the stretches this question is about)" in got["step1"]
    assert "Selection: DUNLIN GP. 2958-3223 m" in got["step1"]


def test_under_reach_focus_no_scope_is_asked_or_applied():
    s, data = _session(replace(CASES["brent"], data=(("reach", "focus"),)))
    llm, trace = _read(s, _reply(["Dunlin GP."]), data)
    assert "- scope:" not in llm.sent["read"][1] and s.scope == [] and "scope" not in trace


def test_the_read_schema_has_scope_only_under_reach_well():
    from petroharness.agent.loop import read_schema
    assert "scope" not in read_schema(True)["properties"] and read_schema(True) == read_schema(True, False)
    assert read_schema(True, True)["required"] == ["topics", "named", "depth", "scope"]


def test_a_scope_item_is_short_and_a_sentence_is_said_short():
    """Live: the model wrote its plans as scope items (a sentence each, eight of them). The schema types an item (a
    name a selection reads, or a depth range), and a note on one that cannot be used (a /scope the user typed, or a
    reply from a server without guided decoding) says it short."""
    from petroharness.agent.loop import SCOPE_ITEM_CHARS, read_schema
    long = "the well section 2841-2958 m covering the named units, the overlap of 2800-3000 m with the record"
    assert not _typed(read_schema(True, True, ("NESS FM.",)), long)
    s, data = _session()
    long = "the well section 2841-2958 m covering the named units, the overlap of 2800-3000 m with the record"
    _read(s, [_reply([long]), _reply([long])], data)                          # asked again once, still unusable
    assert s.scope == [] and long not in s.scope_note and long[:SCOPE_ITEM_CHARS] + "..." in s.scope_note


def test_all_under_a_scope_is_every_row_of_the_scope(brent):
    """Live (Z3, Z4 round 2): the model's runs call carried its usual "zones": ["ALL"], which won over the scope, so
    "every interval in the whole well" was listed on the interval alone. ALL names no stretch of its own."""
    s, data = brent
    _read(s, _reply(["the whole well"]), data)
    lo, hi = s.f.inv.well_span
    text, _ = s.run(("tool", "runs", {"condition": "GR < 60", "zones": ["ALL"]}))
    assert f"Selection: {lo:g}-{hi:g} m" in text.splitlines()[0], text[:120]
    text, _ = s.run(("tool", "stats", {"curves": ["GR"], "zones": ["Z3"]}))
    assert "Selection:" not in text                                   # a zone named: the call's own


def test_a_scope_on_the_intervals_own_samples_is_the_interval(brent):
    """Question suite (B08, B12): the READ wrote the interval's depth range as the scope; the selection was the interval
    again, and the user's zones came back twice (Z ids and rows R1, R2). The same samples are the interval."""
    from petroharness.agent.map import num
    s, data = brent
    v = s.f.view
    _read(s, _reply([f"{num(float(v.top))}-{num(float(v.base))} m"]), data)    # as the map writes the interval
    assert s.scope == [] and s.scope_note == ""
    _read(s, _reply(["2800-3000 m"]), data)                     # a stretch beyond the interval stays a scope
    assert s.scope == ["2800-3000 m"]


@pytest.mark.parametrize("items, used", [
    (["Ness Fm", "2841-2865 m"], ["Ness Fm"]),                       # a unit and its own range: one stretch
    (["DUNLIN GP.", "3000-3100 m"], ["DUNLIN GP."]),                 # a range inside a unit
    (["2900-3000 m", "2950-3100 m"], ["2900-3100 m"]),               # partly overlapping: their union
    (["Ness Fm", "DUNLIN GP."], ["Ness Fm", "DUNLIN GP."])])         # disjoint: rows
def test_a_scope_is_the_union_of_its_items(brent, items, used):
    """Question suite F2 (B01, B04, B15, K01): overlapping items were refused as rows and the whole scope dropped."""
    s, data = brent
    _read(s, _reply(items), data)
    assert s.scope == used and s.scope_note == "", (s.scope, s.scope_note[:200])


def test_an_overlap_names_a_range_once(brent):
    """F14, under D2: overlapping items join into one row and the note names each range once."""
    from petroharness.agent import selection
    s, _ = brent
    notes = []
    on, _ = selection.resolve(s.f, ["2841-2865 m", "2850-2900 m"], force=True, notes=notes)
    said = selection.header(on, notes)
    assert "Ness Fm. (2841-2865 m) and 2850-2900 m overlap: one row, 2841-2900 m" in said   # the unit's own range (R10)
    assert "2841-2865 m 2841-2865" not in said and "2841-2865 m) 2841" not in said
    assert "overlap" not in on.view.selection                                 # the name is the rows' only


def test_a_scope_that_names_no_stretch_is_asked_again_once_with_the_reason(brent):
    """A scope item that resolves to no stretch (an off-schema reply where the backend does not enforce the schema, or a
    range outside the well) dropped the whole scope; the READ prompt is sent again once, single-turn, with the
    resolver's reason, and the second reply's scope is used."""
    s, data = brent
    llm, trace = _read(s, [_reply(["Nowhere Fm."]), _reply(["Dunlin GP."])], data)
    assert s.scope == ["Dunlin GP."] and trace["scope"]["used"] == ["Dunlin GP."]
    again = llm.sent["read_scope"][-1]
    assert "SCOPE NOT USED" in again and "Nowhere Fm." in again and len(llm.sent["read_scope"]) == 2   # single turn
    assert trace["read_scope_again"]["scope"] == ["Dunlin GP."]


@pytest.mark.parametrize("question, scope", [
    ("What is the mean gamma ray of the Manganui?", ["Manganui"]),
    ("What is the mean gamma ray of the Manganui?", ["Mangahewa"]),     # suite T01: the scope read another unit
    ("what is the mean gamma ray of the manganui formation?", [])])
def test_a_unit_the_tops_file_lists_twice_is_asked_back_to_the_user(question, scope):
    """tuhua-7's tops file lists Manganui twice (874-1251 m, 2165-2347 m). A question naming it (or a scope read to it)
    is not computed on: which one is meant is the user's to say, or the file's to fix (user, 2026-11-20)."""
    from petroharness.agent.loop import Session
    from petroharness.config import given_settings
    task, cfg, data = task_cfg(CASES["tuhua"], "q")
    task = task.model_copy(update={"question": question})
    with given_settings({"data": data, "eval": {}}):
        s = Session.build(task, cfg)
    _, trace = _read(s, _reply(scope), data)
    assert s.ask_user and trace["ask_user"] == s.ask_user
    assert "Manganui 2 times" in s.ask_user and "874.014-" in s.ask_user and "2164.99" in s.ask_user
    assert "which one do you mean" in s.ask_user and "fix the tops file" in s.ask_user


def test_a_question_naming_no_unit_listed_twice_is_not_asked_back(brent):
    s, data = brent
    _, trace = _read(s, _reply(["Ness Fm."]), data)
    assert s.ask_user == "" and "ask_user" not in trace


def test_the_graph_ends_with_the_question_to_the_user_when_one_is_asked():
    from types import SimpleNamespace as NS
    from petroharness.agent.graph import ASK_USER, after_read, ask_user
    run = NS(context=NS(session=NS(ask_user="The tops file lists X 2 times ...")))
    assert after_read({}, run) == "ask_user"
    assert ask_user({}, run) == {"answer": "The tops file lists X 2 times ...", "status": ASK_USER}
    assert after_read({}, NS(context=NS(session=NS(ask_user="")))) == "first_look"


def _asked(case, question, scope=None):
    from petroharness.agent.loop import Session
    from petroharness.config import given_settings
    task, cfg, data = task_cfg(case, "q")
    task = task.model_copy(update={"question": question})
    with given_settings({"data": data, "eval": {}}):
        s = Session.build(task, cfg)
    _read(s, _reply(scope or []), data)
    return s


def _tops_variant(tmp_path, old, new):
    from _wells import Case, sample
    src = sample("formations_30_6-5.csv")
    text = open(src).read()
    assert old in text
    p = tmp_path / "tops.csv"
    p.write_text(text.replace(old, new))
    return Case("30/6-5", str(p), "BRENT GP.")


def test_a_unit_whose_tops_row_is_wrong_is_asked_back_with_the_row_to_fix(tmp_path):
    """Question suite U05: the Ness row gave its base above its top; the row was left out silently and the answer said
    the Ness is not in the tops file. The question is asked back with the row and what is wrong with it."""
    case = _tops_variant(tmp_path, "Ness Fm.,2841.0,2865.0,", "Ness Fm.,2865.0,2841.0,")
    s = _asked(case, "What is the mean gamma ray of the Ness Formation?", ["BRENT GP."])
    assert "row for Ness Fm. (line 15) cannot be used" in s.ask_user and "not below its top" in s.ask_user
    assert "fix the row" in s.ask_user


@pytest.mark.parametrize("question", ["What is the mean gamma ray of the Mangahua Formation?",
                                      "What is the mean gamma ray of the Mangahua Fm.?"])
def test_a_unit_name_close_to_units_of_the_file_is_asked_back_did_you_mean(question):
    """Question suite U02: "Mangahua" (no such unit; Mangahewa and Manganui are close) was answered as the interval."""
    s = _asked(CASES["tuhua"], question)
    assert "lists no unit Mangahua" in s.ask_user and "did you mean" in s.ask_user and "Mangahewa" in s.ask_user


def test_a_unit_close_to_none_is_said_under_the_question_not_asked():
    """Question suite U03: "Hugin" is no unit of the file and close to none: answered as absent (the note under the
    question, which the steps and the writer read), not asked back."""
    from petroharness.agent import vocabulary
    s = _asked(CASES["brent"], "What is the mean gamma ray of the Hugin Formation?")
    assert s.ask_user == "" and "Named but not a unit of the tops file: Hugin Formation" in s.unit_note
    assert s.unit_note in vocabulary.note(s) and "Ness Fm." in s.unit_note
    got = [f for f in vocabulary.facts(s) if f["kind"] == "absent_unit"]       # the same, as data for the reader
    assert len(got) == 1 and got[0]["names"] == ["Hugin Formation"] and "Ness Fm." in got[0]["units"]


@pytest.mark.parametrize("case", ["brent", "tuhua", "cheal", "hw3"])
def test_every_unit_of_the_file_asked_by_its_name_reads_as_it_is(case):
    """No false alarm: each unit of the tops file, asked about by its own name or with its rank word written out
    ("Ness Formation" for Ness Fm., "The Ness Formation is ..."), is neither asked back nor noted, unless the file lists
    it more than once."""
    from collections import Counter
    from petroharness.agent.loop import Session, ask_back
    from petroharness.config import given_settings
    task, cfg, data = task_cfg(CASES[case], "q")
    with given_settings({"data": data, "eval": {}}):
        s = Session.build(task, cfg)
    twice = {n for n, k in Counter(u.name for u in s.f.view.units).items() if k > 1}
    spelled = lambda n: re.sub(r"\s+Fm\.$", " Formation", re.sub(r"\s+GP\.$", " Group", n, flags=re.I), flags=re.I)
    for u in s.f.view.units:
        for q in (f"What is the mean gamma ray of the {u.name}?", f"The {spelled(u.name)} is thick here. What is its mean GR?"):
            asked = ask_back(s, [q])
            assert bool(asked) == (u.name in twice), (q, asked)
            assert s.unit_note == "", (q, s.unit_note)


def test_the_writer_corrects_a_premise_the_results_contradict():
    """Question suite U08: "the Ness is about 80 m thick" (24 m here) was answered without a word on it."""
    from petroharness.agent import components as C
    premise = C.text("C9", "premise")
    assert premise in C.prompt("C9", "write") and premise in C.prompt("C9", "reply_brief")


def _conventions(name: str) -> list:
    """A unit's name as users write it: as the file does, in either case, its rank word written out, abbreviated or
    plural or left out, with "the", without punctuation, hyphens as spaces, with a pick marker."""
    bare = re.sub(r"\s+(?:fm|gp|grp|mbr|formation|group|member)\.?$", "", name.strip(), flags=re.I)
    rank = re.search(r"\b(fm|gp|grp|mbr|formation|group|member)\.?$", name.strip(), re.I)
    word = {"fm": "Formation", "gp": "Group", "grp": "Group", "mbr": "Member"}.get(rank.group(1).lower(),
                                                                               rank.group(1)) if rank else ""
    out = [name, name.lower(), name.upper(), bare, f"the {bare}", bare.lower(), re.sub(r"[\W_]+", " ", name).strip(),
           bare.replace("-", " "), f"{name} Top"]
    if word:
        out += [f"{bare} {word}", f"{bare} {word.lower()}s", f"{bare.lower()} {word.lower()}",
                f"{bare} {'Fmn' if word == 'Formation' else word}"]
    return list(dict.fromkeys(out))


@pytest.mark.parametrize("case", ["brent", "tuhua", "cheal", "hw3"])
def test_a_unit_written_in_any_users_convention_is_that_unit(case):
    """User, 2026-11-20: users ask with their own naming conventions. Each unit of the tops file, written each way users
    write a unit (_conventions), selects that unit, and a question naming it is not asked back (a name the file lists
    twice, or one whose bare name several units share, is the user's to choose and is asked)."""
    from collections import Counter
    from petroharness.agent.loop import Session, ask_back
    from petroharness.agent.selection import _core, units_named
    from petroharness.config import given_settings
    task, cfg, data = task_cfg(CASES[case], "q")
    with given_settings({"data": data, "eval": {}}):
        s = Session.build(task, cfg)
    names = Counter(u.name for u in s.f.view.units)
    cores = Counter(_core(n) for n in names)
    checked = 0
    for name in names:
        for w in _conventions(name):
            got = {u.name for u in units_named(s.f, w)}
            if names[name] > 1 or cores[_core(name)] > 1:
                continue
            assert got == {name}, (w, got)
            assert ask_back(s, [f"What is the mean gamma ray of the {w}?"]) == "" and s.unit_note == "", w
            checked += 1
    assert checked >= len(names)


@pytest.mark.parametrize("case, question, scope", [("tuhua", "The upper one, please.", ["874.014-1250.7468 m"]),
                                                   ("brent", "Use 2841-2865 m for it.", ["2841-2865 m"])])
def test_the_users_answer_to_an_ask_is_not_asked_again(case, question, scope):
    """Question suite U15, U16: the user answered the question back ("the upper one", the depths), the READ restated
    the unit in its own words, and the harness asked again. Only the user's words are read for an ask."""
    s = _asked(CASES[case], question, scope)
    assert s.ask_user == "" and s.scope, (s.ask_user, s.scope)



def test_a_bare_name_several_units_share_is_asked_back_and_a_rank_word_picks_one(tmp_path):
    """Question suite N5: the file holds BRENT GP. and a Brent Fm.; "the Brent" was answered over the whole well.
    A bare name several differently named units share is asked back; "the Brent Group" or "Brent Fm." is one unit."""
    case = _tops_variant(tmp_path, "Ness Fm.,2841.0,2865.0,", "Ness Fm.,2841.0,2865.0,")
    p = tmp_path / "tops.csv"
    p.write_text(p.read_text().rstrip("\n") + "\nBrent Fm.,2880.0,2958.0,Sandstone,m,formation,BRENT GP.\n")
    s = _asked(case, "What is the mean gamma ray of the Brent?")
    assert "2 units called brent" in s.ask_user.lower() and "BRENT GP." in s.ask_user and "Brent Fm." in s.ask_user
    for q in ("What is the mean gamma ray of the Brent Group?", "What is the mean gamma ray of the Brent Fm.?"):
        assert _asked(case, q).ask_user == "", q


def test_the_premise_rule_covers_any_stated_fact():
    from petroharness.agent import components as C
    t = C.text("C9", "premise")
    assert all(w in t for w in ("value", "depth", "thickness", "lithology"))


def test_a_request_outside_the_wells_logs_is_answered_with_what_the_assistant_does():
    """Question suite P7: "Write me a poem about rocks" ran a seven-step investigation and wrote an ode (with a top
    misread as 2441 m). Under reach well the READ may read a request as outside the well's logs; it is answered with
    what this assistant does, nothing computed (status outside)."""
    s, data = _session()
    s.reads_depth = True                             # the route setting the CLI and the benchmark run with
    reply = json.dumps({"topics": ["porosity"], "named": [], "depth": "outside", "scope": []})
    llm, trace = _read(s, reply, data)
    assert s.depth == "outside" and s.ask_status == "outside" and trace.get("outside")
    assert "outside what I do here" in s.ask_user and "BRENT" in s.ask_user.upper()
    assert '"outside"' in llm.sent["read"][1] or "outside" in llm.sent["read"][1]
    from types import SimpleNamespace as NS
    from petroharness.agent.graph import after_read, ask_user
    run = NS(context=NS(session=s))
    assert after_read({}, run) == "ask_user" and ask_user({}, run)["status"] == "outside"


def test_outside_is_offered_only_where_users_type_freely():
    """The benchmark (reach focus) asks about its interval by construction: its READ schema offers no "outside", and a
    reply that says it anyway is an investigation."""
    from petroharness.agent.loop import _reading, read_schema
    assert "outside" in read_schema(True, True)["properties"]["depth"]["enum"]
    assert "outside" not in read_schema(True, False)["properties"]["depth"]["enum"]
    reply = json.dumps({"topics": ["porosity"], "named": [], "depth": "outside"})
    assert _reading(reply, True, outside=False)["depth"] == "investigate"


def test_the_users_zones_with_no_sample_here_are_said_not_dropped(tmp_path):
    """Question suite Z2: a zones file of "Brent" (2841-2958 m) and "Below TD" (3600-3700 m, the log ends at 3556 m);
    the second was left out silently and the answer said the record holds only one zone. Each zone with no sample is
    kept with why, and said under every question while the zones are in force."""
    from _wells import Case
    from petroharness.agent import vocabulary
    from petroharness.agent.loop import Session
    from petroharness.config import given_settings
    z = tmp_path / "zones.csv"
    z.write_text("zone,top,bottom\nBrent,2841,2958\nBelow TD,3600,3700\n")
    task, cfg, data = task_cfg(Case("30/6-5", "formations_30_6-5.csv", "BRENT GP.", zones=str(z)), "q")
    task = task.model_copy(update={"question": "Give the mean gamma ray of each of my zones."})
    with given_settings({"data": data, "eval": {}}):
        s = Session.build(task, cfg)
    assert [x[0] for x in s.f.view.user_zones_left] == ["Below TD"]
    assert "no sample of the log, which runs" in s.f.view.user_zones_left[0][3]
    _read(s, _reply([]), data)
    assert "Your zones with no sample here: Below TD 3600-3700 m" in s.unit_note
    assert s.unit_note in vocabulary.note(s)
    (got,) = [f for f in vocabulary.facts(s) if f["kind"] == "zones_left"]  # the same, as data for the reader
    assert [(z["name"], z["top"], z["base"], z["unit"]) for z in got["zones"]] == [("Below TD", 3600.0, 3700.0, "m")]
    assert got["zones"][0]["why"].startswith("no sample of the log, which runs")
    s.take_user_scope(task.model_copy(update={"scope": ["2841-2900 m"]}))   # a stretch the user chose: no question back,
    _read(s, _reply([]), data)                                             # and the zones are said all the same
    assert s.user_scope and "Your zones with no sample here: Below TD 3600-3700 m" in s.unit_note
    assert [f["kind"] for f in vocabulary.facts(s)] == ["zones_left"]


@pytest.mark.parametrize("question, scope, kind", [
    ("What is the mean gamma ray of the Manganui?", [], "listed_twice"),
    ("What is the mean gamma ray of the Mangahua Formation?", [], "did_you_mean")])
def test_a_question_back_carries_its_answers_to_pick(question, scope, kind):
    """The page shows a question back as buttons: each choice a question to send and, for a stretch, the scope set
    first (the UI had no way to act on "reply with /scope ...")."""
    s = _asked(CASES["tuhua"], question, scope)
    assert s.ask_user and s.ask_choices
    if kind == "listed_twice":
        assert [c["scope"] for c in s.ask_choices[:2]] == [["874.014-1250.75 m"], ["2164.99-2347.42 m"]]
        assert s.ask_choices[-1]["scope"] == ["874.014-1250.75 m", "2164.99-2347.42 m"]
        assert all(c["question"] == question for c in s.ask_choices)
    else:
        assert {c["label"] for c in s.ask_choices} >= {"Mangahewa"}
        assert any(c["question"] == "What is the mean gamma ray of the Mangahewa?" for c in s.ask_choices)
