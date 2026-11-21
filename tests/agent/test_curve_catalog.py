"""The curve catalog and the step records in plain words.

- Every curve the workflow writes into a record of the configured datasets (GeoLink, Costa, Danish) has a one-line
  meaning in the catalog (resources/rules/curves.yaml `meanings`): what it is, its kind (a measurement, a model output,
  a flag, a class or a parameter) and its inputs, whatever its source. The map shows the line (under a workflow step,
  whose line says how the curve was made from which inputs, its first part); the tools label a curve with its first
  part.
- A fallback list of a step's inputs reads "X where present, otherwise Y", never "X, Y" or "X+Y" (which read as two
  inputs or a sum), in the step's inputs, equations and record lines, on the map and in the step tool.
- A curve a step wrote that holds one value for the whole well is labelled a parameter of its step.

    PYTHONPATH=src:tests:tests/agent PETROHARNESS_DATA=<geolink.yaml> python -m pytest tests/agent/test_curve_catalog.py -q
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness.record.card import fallback, input_text, plain_inputs  # noqa: E402
from petroharness.registry import load  # noqa: E402

CATALOG = load().curves["meanings"]
KIND = re.compile(r"; an? (measurement|model output|flag|class|parameter)\b")
COMPOSITE = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]*(?:[+/][A-Z][A-Z0-9_]*)+(?![A-Za-z0-9_])")


# --- the catalog's lines -----------------------------------------------------------------------------------------------

def test_every_catalog_line_says_what_the_curve_is_its_kind_and_no_source_story():
    for c, line in CATALOG.items():
        kinds = KIND.findall(line)
        assert len(kinds) == 1 and line.index(";") < KIND.search(line).start() + 1, (c, line)
        assert kinds[0] in ("measurement", "flag", "class") or " from " in line or "a parameter" in line, (c, line)
        assert not re.search(r"\{method\}|supplied|same values|the LAS\b|\bbenchmark\b|\breference\b", line), (c, line)
        assert len(line) <= 220, (c, len(line))


def test_the_catalog_names_no_dataset():
    """The lithology log's line is one entry for whatever curve is the lithology log (no LAS mnemonic of a dataset)."""
    assert not [c for c in CATALOG if re.search(r"geolink|costa|danish", c, re.I)]
    assert KIND.search(load().curves["lithology_log"]).group(1) == "class"


def test_flags_are_flags_and_swirr_app_is_a_model_output():
    """SWIRR_APP is per sample (Buckles) or one value for the whole well: its kind is read from its values, and it is
    a parameter only where its step lists that value (tests/test_label_fixes.py)."""
    reg = load()
    for c in reg.flags:
        assert "; a flag" in CATALOG[c], c
    assert "; a model output of the permeability step" in CATALOG["SWIRR_APP"]


# --- fallback lists and parameters in plain words ----------------------------------------------------------------------

@pytest.mark.parametrize("name, plain", [("PHIE+PHIT", "PHIE where present, otherwise PHIT"),
                                         ("RSHA+RXO+RMED", "RSHA where present, otherwise RXO where present, otherwise RMED"),
                                         ("SWIRR/SW", "SWIRR where present, otherwise SW"), ("RDEP", "RDEP"),
                                         ("reference VLIM/VDOL where available", "reference VLIM/VDOL where available")])
def test_a_fallback_list_in_plain_words(name, plain):
    assert fallback(name) == plain
    assert input_text(name) == (plain if plain == name else f"({plain})")


def test_only_the_steps_own_fallbacks_are_rewritten_in_its_lines():
    inputs = ["PHIE+PHIT", "SW"]
    assert plain_inputs("BVW = PHIE+PHIT * SW", inputs) == "BVW = (PHIE where present, otherwise PHIT) * SW"
    assert plain_inputs("RQI = 0.0314*sqrt(PERM/PHIE+PHIT)", inputs) == \
        "RQI = 0.0314*sqrt(PERM/(PHIE where present, otherwise PHIT))"
    assert plain_inputs("Missing samples use VCALC+VDOLO=1-VCL-PHIE_CC", inputs) == "Missing samples use VCALC+VDOLO=1-VCL-PHIE_CC"
    assert plain_inputs("NET_RES: + PHIE_CC+PHIE > 0.08", ["PHIE_CC+PHIE"]) == \
        "NET_RES: + (PHIE_CC where present, otherwise PHIE) > 0.08"


@pytest.mark.data
def test_the_rendered_step_records_read_in_plain_words():
    """On every formation of the configured dataset: no step line of the map shows a fallback input as "X+Y" (or
    "X/Y" in its inputs), each is written "where present, otherwise"; a curve a step wrote that holds one value for the
    whole well is labelled so (one value over the whole well as its step wrote it), on the map and in the step tool."""
    from test_b2_tools import F
    from petroharness.agent.map import render
    from petroharness.agent.toolset import TOOLS
    seen_fallback = seen_parameter = 0
    for t, f in F():
        text = render(f.inv)
        lines = text.splitlines()
        for m in f.inv.methods:
            if m.stage != "workflow":
                continue
            comps = [i for i in (m.inputs or []) if COMPOSITE.fullmatch(str(i))]
            i = next(k for k, ln in enumerate(lines) if ln.startswith(f"  step {m.step}: "))
            j = i + 1
            block = [lines[i]]
            while j < len(lines) and lines[j].startswith("    "):
                block.append(lines[j])
                j += 1
            for c in comps:
                assert not any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(c)}(?![A-Za-z0-9_])", b) for b in block), (t.well, m.step, c, block)
                assert f"({fallback(c)})" in block[0], (t.well, m.step, block[0])
                seen_fallback += 1
            out = TOOLS["step"](f, name=m.step).text
            for c in comps:
                assert f"({fallback(c)})" in out and not re.search(rf"inputs: [^\n]*(?<![A-Za-z0-9_]){re.escape(c)}(?![A-Za-z0-9_])", out)
        for c, cv in f.inv.curves.items():
            if cv.well_value is not None and cv.step:
                from petroharness.agent.map import num
                want = f"{c} {num(cv.well_value)}: one value over the whole well as the {cv.step} step wrote it ("
                assert want in text, (t.well, c)
                seen_parameter += 1
                if any(m.step == cv.step for m in f.inv.methods):
                    assert want in TOOLS["step"](f, name=cv.step).text, (t.well, c)
    assert seen_fallback and seen_parameter, (seen_fallback, seen_parameter)


# --- coverage on every configured dataset ------------------------------------------------------------------------------

def _datasets():
    from test_b4_direction import _dataset_configs
    return _dataset_configs()


@pytest.mark.data
@pytest.mark.parametrize("config", _datasets(), ids=lambda p: p.stem)
def test_every_derived_curve_of_each_dataset_has_its_catalog_line(config):
    """Every curve of every formation of the dataset that is not an input of the LAS (computed, the analyzers', a copy,
    or not recorded) has a catalog line; the map shows the analyzers' curves with it, and the tools label every curve
    with its first part (what it is)."""
    from test_b4_direction import _formations
    from petroharness.agent.inventory import lithology_logs
    missing, shown = set(), 0
    fs = _formations(config)
    for t, f in fs:
        logs = lithology_logs(f.view)
        for c, cv in f.inv.curves.items():
            line = load().curves["lithology_log"] if c.upper() in logs else CATALOG.get(c)
            if c.upper() in logs:                                  # the lithology log, whatever its name or source
                assert cv.catalog == line, (t.well, c, cv.catalog)
            if cv.source == "input":
                continue
            if line is None:
                missing.add(c)
                continue
            assert cv.catalog == line and cv.meaning_from == "registry", (t.well, c, cv.catalog)
            assert cv.meaning == line.split("; ")[0], (t.well, c, cv.meaning)          # the tools' label
            shown += 1
    assert not missing, sorted(missing)
    assert shown
    t, f = fs[0]
    from petroharness.agent.map import render
    text = render(f.inv)
    for c, cv in f.inv.curves.items():
        if cv.source == "analyzer" and c in CATALOG:           # whole, a twin beside what it is (map.render's what)
            head, _, rest = CATALOG[c].partition("; ")
            line = next((ln for ln in text.splitlines() if ln.startswith(f"  {c} = {head}")), "")
            assert line and f"; {rest}" in line if rest else line, (t.well, c)
