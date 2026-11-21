"""The generality contract (docs/DESIGN.md, G1-G8; AGENTS.md rule 10): one test per rule.

    .venv/bin/python -m pytest tests/test_generality.py -q
"""
import ast
import dataclasses
import inspect
import io
import re
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]
AGENT = ROOT / "src" / "petroharness" / "agent"


def _code(path: Path) -> list:
    """The file's tokens that carry code or strings (comments and layout left out)."""
    skip = (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
    return [t for t in tokenize.generate_tokens(io.StringIO(path.read_text()).readline) if t.type not in skip]


def test_no_benchmark_inputs():
    """G1: the run takes a question, a well and a formation; no benchmark label (the category) enters it."""
    from petroharness import cli
    from petroharness.agent import graph, loop
    for fn in (graph.answer, loop.Session.build, cli.answer):
        assert "category" not in inspect.signature(fn).parameters, fn
    for cls in (graph.Run, loop.Session):
        assert "category" not in {f.name for f in dataclasses.fields(cls)}, cls
    bad = []                                              # no .category or category= in the agent's code
    for p in sorted(AGENT.glob("*.py")):
        toks = _code(p)
        bad += [f"{p.name}:{a.start[0]}" for a, b in zip(toks, toks[1:])
                if (a.string, b.string) == (".", "category") or (a.string, b.string) == ("category", "=")]
        bad += [f"{p.name}:{t.start[0]}" for t in toks
                if t.type == tokenize.STRING and re.search(r"\.category\b|\bcategory\s*=", t.string)]
    assert not bad, bad
    tree = ast.parse((ROOT / "src" / "petroharness" / "cli.py").read_text())       # cli: the run gets no category
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") in ("answer", "graph_answer")]
    assert len(calls) == 2
    for c in calls:
        names = {n.id for n in ast.walk(c) if isinstance(n, ast.Name)}
        assert "categor" not in ast.unparse(c) and not names & {"cat", "group", "index"}, ast.unparse(c)


# --- the model-facing texts (G3, G5) -------------------------------------------------------------------------------------

def _model_facing() -> list:
    """What the model reads as fixed text: the components' entries (C1-C10), the topic areas, and the guides of every
    skill library the package ships (resources/skills/<library>/<guide>/SKILL.md)."""
    comp = ROOT / "src" / "petroharness" / "agent" / "components"
    resources = ROOT / "src" / "petroharness" / "resources"
    return sorted({*comp.glob("*/*.md"), *comp.glob("*/*.json"), *resources.glob("skills/*/*/SKILL.md"),
                   resources / "topics.yaml"})


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


# G3: conclusion forms the harness never writes into a text the model reads. The list guards against these forms; it
# is not a ban on general prose.
PRESCRIPTIONS = {
    r"each zone is a": "flow units = the zones (C10 no_reversal_rule, flow_units decide 1, K14)",
    r"name .{0,40} first": "'Name the mobility candidates first' (invasion decide 1)",
    r"is the .{0,30}candidate": "a reading named as the candidate",
    r"name that as": "'name that as the control' (perm_controls decide 3)",
    r"the flow units .{0,20}(are|follow) the zones": "flow units = the zones (flow_units decide 1)",
}
# (file, matched text) -> why it may stay: the pattern's words in report style, not a conclusion.
PRESCRIPTION_ALLOWED = {}
# (file, matched text) -> a match awaiting the user's decision (allowed, or the text rewritten). Empty; a new entry comes
# with its decision.
PRESCRIPTION_PENDING = {}


def _prescriptions() -> dict:
    hits = {}
    for p in _model_facing():
        text = p.read_text(encoding="utf-8")
        for pat in PRESCRIPTIONS:
            for m in re.finditer(pat, text, re.I):
                hits[(_rel(p), m.group(0))] = pat
    return hits


def test_no_prescriptions():
    """G3: the harness states no conclusion; the conclusion forms of PRESCRIPTIONS are in no text the model reads."""
    hits = _prescriptions()
    known = {**PRESCRIPTION_ALLOWED, **PRESCRIPTION_PENDING}
    bad = [f"{f}: '{m}' ({PRESCRIPTIONS[pat]})" for (f, m), pat in hits.items() if (f, m) not in known]
    assert not bad, bad
    stale = [k for k in known if k not in hits]
    assert not stale, f"{stale}: the text is gone; remove the entry"


def test_the_prescription_patterns_catch_the_conclusion_forms():
    forms = ["The flow units at log resolution follow the zones and the workflow's FZI classes: each zone is a flow unit",
               "Name the mobility candidates first: flagged pay in reservoir rock with the separation",
               "differ in pore-throat size and connectivity, which their FZI and RQI measure: name that as the control",
               "Flow units: each zone is a flow unit of its FZI class, described zone by zone",
               "Low-BVW, low-SW reservoir rock is the moveable-hydrocarbon candidate"]
    for line in forms:
        assert any(re.search(p, line, re.I) for p in PRESCRIPTIONS), line
    for line in ["Rank the zones by both; where they pick different zones, name both with their basis.",
                 "A candidate is a control when quality and the candidate move together across most zones."]:
        assert not any(re.search(p, line, re.I) for p in PRESCRIPTIONS), line


# G6: phrases that choose a basis or convention for the model. The harness never uses one in a text the model reads:
# the components, the guides, the report style, and the strings of the code that writes tool output, the map and the
# prompts.
NO_PREFERENCE = {
    "the record's basis": "tool wording that ranked the zones pooled above the whole interval",
    "zones pooled first": "tool wording that ranked one basis above another",
    "the zone-level reading": "tool wording that ranked the zone-mean view above the samples",
    "strongest flow interval (highest mean": "the strongest zone by its mean alone, called the strongest",
    "the formation's statistic": "statistics guide: the zones pooled as the formation's statistic",
    "give first the zones whose means meet it": "answer guide: the zone-mean basis first",
    "2 and 3 std tiers": "outliers guide: a harness-chosen tier list",
    "exceedance at each": "borehole_qc guide: three DRHO limits",
    "one minus the mean of data_completeness": "data_coverage guide: one missing-data measure",
    "characterise the zones first": "pore_type and fluid_distribution guides: the zone-mean basis first",
    "thickness-weighted formation value": "porosity_level guide: one formation value",
    "with its shift and sign": "depth_alignment guide: one report shape",
    "lead with the lithology-zone basis": "the profile's writer rule",
    "classified (zoned) thickness": "the profile's rock-type share rule",
    "lithology_share_basis": "the profile's basis setting",
    "read each point zone by zone first": "settle_weaknesses: the zone-mean basis first",
    "that rule is the flag": "v5_rules: the workflow's flag as the answer's basis",
    "as well as mean permeability": "no_reversal_rule: a per-property ranking rule",
    "rank and compare zones on both": "brief_levels: a per-curve ranking rule (the values' shape decides the statistic)",
    "best zone": "formation_summary: a ranking called the best",
    "weakest zone": "formation_summary: a ranking called the weakest",
}
CODE = [ROOT / "src" / "petroharness" / d for d in ("agent", "record", "well")]


def _code_strings(path: Path) -> str:
    return "\n".join(t.string for t in _code(path) if t.type == tokenize.STRING)


def _preference_texts() -> list:
    texts = [(p, p.read_text(encoding="utf-8")) for p in _model_facing()]
    texts.append((ROOT / "src" / "petroharness" / "resources" / "profiles" / "report_style.yaml", None))
    texts[-1] = (texts[-1][0], texts[-1][0].read_text(encoding="utf-8"))
    texts += [(p, _code_strings(p)) for d in CODE for p in sorted(d.glob("*.py"))]
    return texts


def test_no_preference_phrases():
    """G6: none of these phrases (a basis or convention chosen for the model) is in any text the model reads."""
    bad = [f"{_rel(p)}: '{phrase}' ({why})" for p, text in _preference_texts() for phrase, why in NO_PREFERENCE.items()
           if phrase in text.lower()]
    assert not bad, bad
    assert not (ROOT / "src" / "petroharness" / "resources" / "profiles" / "reference_reporting.yaml").exists()
    from petroharness.agent import components as C
    assert "zone_basis_rule" not in C.meta("C10")["texts"] and "class_basis_rule" not in C.meta("C10")["texts"]
    assert all(phrase == phrase.lower() for phrase in NO_PREFERENCE)


def test_the_one_guideline_reaches_the_settle_step():
    """G6: one settle text covers bases and conventions, and no basis rule exists; the report style holds the format
    only."""
    import yaml
    from petroharness.agent import components as C, loop, writer
    rule = C.text("C9", "aspects_rule")
    assert rule.startswith("Where the way a number is summarised changes the answer")
    assert "exceeds the spread within them" in rule
    assert loop.ASPECTS_RULE == rule and not hasattr(writer, "ASPECTS_RULE")
    style = yaml.safe_load((ROOT / "src" / "petroharness" / "resources" / "profiles" / "report_style.yaml").read_text())
    assert set(style) == {"format"}
    policy = yaml.safe_load((ROOT / "src" / "petroharness" / "resources" / "policy" / "reference_v2.yaml").read_text())
    assert policy["reporting"]["profile"] == "profiles/report_style.yaml"


# G5: words that speak of the benchmark. "Reference" alone stays (a core reference, a reference curve, a depth reference).
BENCHMARK_WORDS = [re.compile(r"\bbenchmark", re.I), re.compile(r"\bjudge[sd]?\b", re.I),
                   re.compile(r"\breference answers?\b", re.I), re.compile(r"\breferences\b", re.I), re.compile(r"\bGT\b")]


def test_no_benchmark_words():
    """G5: no text the model reads speaks of a benchmark, a judge, reference answers, the references or a GT."""
    bad = [f"{_rel(p)}: {m.group(0)}" for p in _model_facing() for rx in BENCHMARK_WORDS
           for m in rx.finditer(p.read_text(encoding="utf-8"))]
    assert not bad, bad
    found = lambda t: [rx.pattern for rx in BENCHMARK_WORDS if rx.search(t)]
    assert found("as the benchmark expects") and found("the judge") and found("the reference answer")
    assert found("checked against the references") and found("the GT says")
    assert not found("the core reference and a reference curve") and not found("the judgement the question asks for")


def _grams(text: str, n: int = 6) -> set:
    words = re.findall(r"[a-z0-9_]+(?:\.[0-9]+)?", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _curve_mnemonics() -> set:
    from petroharness.agent import vocabulary
    from petroharness.registry import DEFAULT_RULES_DIR, Registry
    return {m.lower() for m in vocabulary.mnemonics(Registry(DEFAULT_RULES_DIR).curves)}


# (file, 6-gram) -> why it may stay: standard vocabulary that the benchmark's answers use too, not text taken from them.
OVERLAP_ALLOWED = {
    ("src/petroharness/agent/components/C4_tools/tool_descriptions.json", "net rock net reservoir and net"):
        "the workflow's three net flags (NET_ROCK, NET_RES, NET_PAY) named in words",
    ("src/petroharness/agent/components/C4_tools/tool_descriptions.json", "rock net reservoir and net pay"):
        "the workflow's three net flags (NET_ROCK, NET_RES, NET_PAY) named in words",
    # The researched library: each is textbook vocabulary the reviewed guides share with an answer, not text taken from
    # one (the guides' writers never saw the benchmark).
    ("src/petroharness/resources/skills/researched/elastic_properties/SKILL.md", "s modulus and poisson s ratio"):
        "two elastic moduli named in a list (Young's modulus and Poisson's ratio)",
    ("src/petroharness/resources/skills/researched/elastic_properties/SKILL.md", "young s modulus and poisson s"):
        "two elastic moduli named in a list (Young's modulus and Poisson's ratio)",
    ("src/petroharness/resources/skills/researched/elastic_properties/SKILL.md", "vp vs or poisson s ratio"):
        "the two standard names of the velocity ratio's measure (Vp/Vs or Poisson's ratio)",
    ("src/petroharness/resources/skills/researched/fluid_contacts/SKILL.md", "water contact or a transition zone"):
        "the standard contact types and the transition zone named in the guide's when line",
    ("src/petroharness/resources/skills/researched/invasion_movability/SKILL.md", "nuclear magnetic resonance nmr logs would"):
        "a logging measurement named with its acronym, in the Do not state form 'what would establish it'",
    ("src/petroharness/resources/skills/researched/porosity/SKILL.md", "nuclear magnetic resonance nmr logs would"):
        "a logging measurement named with its acronym, in the Do not state form 'what would establish it'",
    ("src/petroharness/resources/skills/researched/net_reservoir_pay/SKILL.md", "alone pressure gradients fluid samples or"):
        "the standard fluid-typing data named in the Do not state form 'what would establish it'",
    ("src/petroharness/resources/skills/researched/permeability_rock_quality/SKILL.md", "mineral volumes vquar vcalc vdolo vanhy"):
        "a curve list with its heading",
    ("src/petroharness/resources/skills/researched/permeability_rock_quality/SKILL.md", "permeability is dominated by a few"):
        "a textbook property of the arithmetic mean of a log-normal variable (Jensen et al. 2000)",
    ("src/petroharness/resources/skills/researched/water_saturation/SKILL.md", "sw n a rw m rt"):
        "the symbols of the Archie equation (Archie 1942)",
}


def _benchmark_files() -> list:
    try:
        sys.path.insert(0, str(ROOT / "tests"))
        from _reference import CFG
        gt = CFG.eval.gt_dir
    except Exception:  # noqa: BLE001  (no data config: no benchmark files)
        return []
    if not gt or not Path(gt).parent.is_dir():
        return []
    return sorted(Path(gt).parent.glob("*/single_formation_*_qa_pairs.json"))


def test_no_benchmark_overlap():
    """G5: no 6-gram (6 words in a row, any case) of a model-facing text is in a benchmark question or reference answer
    (every dataset's single-formation QA pairs, found beside the data config's gt_dir; tests may read them, AGENTS.md
    rule 1). A 6-gram of curve mnemonics and 'and' only is a curve list, exempt."""
    import json
    files = _benchmark_files()
    if not files:
        pytest.skip("the benchmark's QA pairs are not here")
    bench = {}
    for f in files:
        for qa in json.loads(f.read_text()):
            for key, value in qa.items():
                if isinstance(value, str) and (key == "question" or "answer" in key):
                    for g in _grams(value):
                        bench.setdefault(g, f"{f.parent.name}/{qa.get('qa_id')}/{key}")
    assert len(bench) > 10000
    curve = _curve_mnemonics() | {"and"}
    hits = {}
    for p in _model_facing():
        for g in _grams(p.read_text(encoding="utf-8")):
            if g in bench and not set(g.split()) <= curve:
                hits[(_rel(p), g)] = bench[g]
    bad = [f"{f}: '{g}' (also in {src})" for (f, g), src in sorted(hits.items()) if (f, g) not in OVERLAP_ALLOWED]
    assert not bad, bad
    stale = [k for k in OVERLAP_ALLOWED if k not in hits]
    assert not stale, f"{stale}: not shared; remove the entry"


# --- question wording (G4) -----------------------------------------------------------------------------------------------

MATCHERS = {"search", "match", "fullmatch", "findall"}
RESOLVER = "vocabulary.py"          # the catalog vocabulary resolver: it alone reads the question's words


def _is_question(node) -> bool:
    return (isinstance(node, ast.Name) and node.id == "question") or (isinstance(node, ast.Attribute) and node.attr == "question")


def _question_matches(path: Path) -> list:
    """Calls of re.search / re.match / re.fullmatch / re.findall, or a pattern's .search / .match / .fullmatch /
    .findall, with the question text (question, task.question, s.task.question, self.question) in an argument.
    (Reading the question's numbers for number provenance, re.finditer, and removing the well's name from it, .sub,
    match no wording; a name that holds the question under another name is not followed.)"""
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in MATCHERS:
            args = list(node.args) + [k.value for k in node.keywords]
            if any(_is_question(x) for a in args for x in ast.walk(a)):
                out.append(f"{path.name}:{node.lineno}: {ast.unparse(node)[:100]}")
    return out


def test_no_question_patterns(tmp_path):
    """G4: no rule is keyed to question wording. Outside the vocabulary resolver, agent code runs no pattern over the
    question text."""
    bad = [x for p in sorted(AGENT.glob("*.py")) if p.name != RESOLVER for x in _question_matches(p)]
    assert not bad, bad
    probe = tmp_path / "probe.py"                             # the scan finds what it is for
    probe.write_text("import re\ndef f(s, question, P):\n    re.search('x', s.task.question)\n    P.match(question)\n"
                     "    re.findall('y', s.question)\n    re.finditer('[0-9]', question)\n    re.search('x', s.text)\n")
    assert len(_question_matches(probe)) == 3


def test_no_question_form_or_scope_rules():
    """G4/G8: the package has no question-form rules (SUGGEST, AFFECT), no asked-absent list with stand-ins and no
    fluid-point scope."""
    from petroharness.agent import loop, writer
    from petroharness.registry import DEFAULT_RULES_DIR, Registry
    assert not (AGENT / "forms.py").exists()
    for mod, names in ((loop, ("asked_absent", "scope_points", "FLUID_POINT")),
                       (writer, ("SUGGEST_RULE", "ABSENT_FORM_RULE", "asked_statistic", "lead_checks", "flow_unit_denials"))):
        assert not [n for n in names if hasattr(mod, n)], mod
    reg = Registry(DEFAULT_RULES_DIR)
    assert "asked_quantities" not in reg.curves
    assert not {"correlation", "lead_negation", "shape"} & set(reg.checks)
    assert all(set(v) == {"classes", "flags", "words"} for v in reg.checks["indicators"]["properties"].values())


@pytest.mark.data
def test_the_zone_table_follows_no_question_wording():
    """G4: the writer's zone table shows each zone's mean (and a log-normal curve's median beside it) whatever
    statistic the question's words name."""
    sys.path[:0] = [str(ROOT / "tests" / "agent"), str(ROOT / "tests")]
    from test_b5_loop import _session
    from petroharness.agent.claims import Claims
    from petroharness.agent.writer import zone_table
    s = _session()
    if "GR" not in s.f.inv.curves or len(s.f.view.zones) < 2:
        pytest.skip("no GR or a single zone here")
    s.claims = Claims(["p"], s.ledger, s.map, s.task.question, s.f.view, (s.task.well,))
    tables = []
    for q in ("What are the minimum and maximum GR values?", "Analyze the spread of GR.", "Give the P90 of GR.",
              "Describe GR."):
        s.task = s.task.model_copy(update={"question": q})
        tables.append(zone_table(s, s.claims, style="by_interval"))
    assert tables[0].startswith("| Depth Interval") and "Mean GR" in tables[0] and len(set(tables)) == 1


# --- the model decides (G8) ----------------------------------------------------------------------------------------------

# The fact checks code may run: they show facts and never decide.
APPROVED_FACT_CHECKS = {"K1", "K2", "K3", "K4", "K5", "K7", "K8", "K9", "K10", "K11"}
# The claim checks: each shows the model a fact about the record or its citations, or the claim format. A new flag
# needs its check id in APPROVED_FACT_CHECKS first.
FACT_FLAGS = {"K1", "K2", "K3", "K3_held", "K3_none", "K4", "K5_present", "K5_route", "K7_unavailable", "K7_absent", "K8",
              "K9", "K10", "K11"}
REPAIRS = {"fix", "skip", "not_done", "repair_contradictions", "repair_numbers", "repair_words", "repair_keep", "flags",
           "repair_leaks", "repair_names"}  # repair_leaks: working notes left in the answer; repair_names: a curve name
                                            #   the record does not hold, close to one it holds (O5)


def test_the_checks_are_the_approved_fact_checks():
    from petroharness.agent import components as C
    assert set(C.text("C2", "flags")) == FACT_FLAGS
    assert set(C.meta("C2")["texts"]) == REPAIRS
    for k in FACT_FLAGS - {"K3_held", "K3_none"}:
        assert k.split('_')[0] in APPROVED_FACT_CHECKS, k


NEGATIVE = "VCL does not control PERM in any zone: there is no relationship between them."
FLOW_UNITS = "The FZI classes do not define distinct flow units; the interval forms a single flow unit."
SIGNIFICANCE = "The correlation of VCL with PERM is not statistically significant."
MEANS = "so clay does not set the permeability differences between the zones"


@pytest.mark.data
def test_no_overrides():
    """G8: no check or repair decides for the model. Claims of the kinds a content check would push (a negative
    verdict without zone counts, flow units denied while FZI classes are open, a significance verdict) and an answer
    whose lead a writer repair would rewrite (a blanket negative lead, a coefficient in the lead, a denial of a classed
    property, a flow-unit denial) reach the settle step and the answer as the model wrote them: unflagged,
    unrepaired, its points its own (no point rewrite, no fluid-point scope)."""
    from types import SimpleNamespace as NS
    sys.path[:0] = [str(ROOT / "tests" / "agent"), str(ROOT / "tests")]
    from test_b2_tools import F
    from test_b5_loop import Script, chose
    from petroharness.llm import Usage
    from petroharness.agent.graph import write_answer
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.loop import Session, investigate, settle
    from petroharness.agent.map import render
    pick = None
    for t, f in F():
        key = next((x.key for x in f.inv.sections if x.key.endswith("flow_unit_classification_system")), None)
        if key and len(f.view.zones) >= 2 and all(f.view.available(c) for c in ("VCL", "PERM")):
            pick = (t, f, key)
            break
    if pick is None:
        pytest.skip("no formation with FZI classes, two zones, VCL and PERM")
    t, f, key = pick
    q = "Where do the logs suggest distinct flow units, and how does clay content affect permeability?"
    s = chose(Session(t.model_copy(update={"question": q}), f, render(f.inv), Ledger(f)), "permeability_rock_quality")
    asks = "Do the flow units differ, and does clay control permeability?"
    points = ["How does clay relate to permeability?", "Where is net pay?"]          # a fluid point in a non-fluid question
    step1 = {"asks": asks, "points": points, "intent": "explain", "focus": "f",
             "edits": [{"op": "add", "point": 1, "text": "Clay may control permeability", "grade": "hypothesis"}],
             "next": [{"section": {"key": key}}, {"compare": {"a": "VCL", "b": "PERM"}}], "done": False}
    edits = [{"op": "add", "point": p, "text": x, "ev": ["MAP"], "grade": "moderate", "means": MEANS}
             for p, x in ((1, NEGATIVE), (1, FLOW_UNITS), (2, SIGNIFICANCE), (3, "Permeability is computed in every zone."))]
    step2 = {"focus": "f", "edits": [{"op": "drop", "id": "C1", "why": "replaced"}] + edits, "next": [], "done": True}
    trace = {}
    investigate(Script([step1, step2]), s, Usage(), 4000, trace, max_steps=3)
    assert s.points == [asks] + points                                       # the model's points, unchanged
    opened = "\n".join(e.text for e in s.ledger.items)
    if re.search(r"\b(MEGA|MACRO|MESO|MICRO)_PORES\b", opened) is None:
        pytest.skip("the FZI section shows no class here")
    got = {c.text: c for c in s.claims.claims.values()}
    for text in (NEGATIVE, FLOW_UNITS, SIGNIFICANCE):
        assert got[text].flags == [] and got[text].grade == "moderate", (text, got[text].flags)
    assert s.claims.done_issues() == []
    llm = Script(['{"edits": [], "done": true}'])
    settle(llm, s, Usage(), 4000, {})
    shown = llm.sent[0][1][-1]["content"].split("YOUR ANSWER:\n", 1)[1].split("\n\nALL RESULTS", 1)[0]
    assert all(text in shown for text in (NEGATIVE, FLOW_UNITS, SIGNIFICANCE))
    assert not [ln for ln in shown.splitlines() if ln.strip().startswith("!")], shown        # no flag under any claim
    lead = NEGATIVE
    coef = next((m for e in s.ledger.items if e.tool == "compare" for ln in e.lines
                 for m in [re.search(r"\b(?:rank correlation|correlation)\s+(-?\d+\.\d+)", ln)] if m and re.search(r"\bn \d+", ln)),
                None)
    if coef:                                                                 # a coefficient an opened result shows, in the lead
        lead = f"With a rank correlation of {coef.group(1)} between VCL and PERM, {NEGATIVE}"
    draft = (f"## Answer\n{lead}\n\n## Flow units\n{FLOW_UNITS} No zones show macro pores or meso pores as distinct "
             f"units.\n\n## Conclusions\n{SIGNIFICANCE}\n")
    llm = Script([draft])
    wtrace = {}
    answer, status = write_answer(llm, s, NS(model=NS(max_tokens_writer=4000)), Usage(), wtrace, "open", "profile")
    assert [stage for stage, _ in llm.sent] == ["writer"], [stage for stage, _ in llm.sent]      # no repair round
    assert wtrace["verify_rounds"][0]["contradictions"] == []
    for text in (lead, FLOW_UNITS, SIGNIFICANCE, "No zones show macro pores or meso pores as distinct units."):
        assert text in answer, text
