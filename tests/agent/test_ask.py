"""One question about any LAS file, the console script's default command (src/petroharness/ask.py). The tops reader
(src/petroharness/well/tops.py) on tables shaped like real ones, the interval rules, the data settings built from the
LAS, the command line and its dispatch (benchmark mode included), and one run end to end with a stub model on a
sample well (data).

    .venv/bin/python -m pytest tests/agent/test_ask.py -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
from petroharness import ask as A
from petroharness.well.formation import FormationNotFound
from petroharness.well.tops import read_tops

SAMPLES = Path(os.environ.get("PETROHARNESS_SAMPLE_LAS", "sample_las"))   # a folder of sample wells; tests skip without it

# shaped like a state survey's tops export: tops only, a unit column, extra columns
KS = """formation,top,depth_unit,depth_ref,source_file
Topeka,3782.0,ft,KB,tops.txt
Heebner,3950.0,ft,KB,tops.txt
Lansing-Kansas City,3991.0,ft,KB,tops.txt
LKC G,4080.0,ft,KB,tops.txt
Stark,4179.0,ft,KB,tops.txt
Mississippian,4618.0,ft,KB,tops.txt
"""
# shaped like a basin data set's formation list: top and bottom, a unit column, a repeated section
NZ = """formation_name,top_depth,bottom_depth,depth_unit
Mount Messenger,590.5500,873.8616,m
Manganui,874.0140,1250.7468,m
Taimana,1250.8992,1326.7944,m
Manganui,2164.9944,2347.4172,m
"""
# several wells in one table
WELLS = """Well Name,Zone,Top MD (m)
WELL-A,Alpha,1000
WELL-A,Beta,1100
WELL-B,Alpha,2000
WELL-B,Gamma,1050
"""

LAS = """~Version
VERS. 2.0 :
WRAP. NO :
~Well
STRT.{u} 1000.0 :
STOP.{u} 1004.0 :
STEP.{u} 0.5 :
NULL. -999.25 :
WELL. Test Well 1 :
~Curve
DEPT.{u} : depth
GR.API : gamma ray
~A
1000.0 50
1000.5 60
1001.0 70
1001.5 80
1002.0 90
1002.5 80
1003.0 70
1003.5 60
1004.0 50
"""


def _file(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


@pytest.fixture
def las(tmp_path):
    return _file(tmp_path, "TW1.las", LAS.format(u="M"))


# --- the tops reader ---------------------------------------------------------------------------------------------------

def test_tops_only_the_base_is_the_next_deeper_top(tmp_path):
    table = read_tops(_file(tmp_path, "ks.csv", KS))
    assert table.columns == {"unit": "depth_unit", "name": "formation", "top": "top"}
    got = table.interval("Lansing-Kansas City")
    assert (got.name, got.top, got.base, got.closed, got.unit) == ("Lansing-Kansas City", 3991.0, 4080.0, False, "ft")
    assert got.base_from == "next top LKC G"
    last = table.interval("Mississippian")
    assert (last.base, last.closed, last.base_from) == (None, False, "end of log")


def test_a_stated_bottom_is_the_base_and_is_included(tmp_path):
    table = read_tops(_file(tmp_path, "nz.csv", NZ))
    got = table.interval("Mount Messenger")
    assert (got.top, got.base, got.closed, got.unit, got.base_from) == (590.55, 873.8616, True, "m", "stated base")


def test_a_row_without_its_bottom_takes_the_next_top(tmp_path):
    table = read_tops(_file(tmp_path, "t.csv", "name,top,base\nA,100,\nB,150,180\n"))
    assert (table.interval("A").base, table.interval("A").closed) == (150.0, False)
    assert (table.interval("B").base, table.interval("B").closed) == (180.0, True)


@pytest.mark.parametrize("asked", ["lansing kansas city", "LANSING-KANSAS  CITY", " Lansing_Kansas City "])
def test_names_match_whatever_the_case_spaces_and_punctuation(tmp_path, asked):
    assert read_tops(_file(tmp_path, "ks.csv", KS)).interval(asked).top == 3991.0


def test_a_name_not_in_the_table_lists_the_names_and_the_close_ones(tmp_path):
    table = read_tops(_file(tmp_path, "nz.csv", NZ))
    with pytest.raises(FormationNotFound) as err:
        table.interval("Mount Mesenger")
    text = str(err.value)
    assert text.startswith("WHAT: formation 'Mount Mesenger' is not in the tops file nz.csv")
    assert "Did you mean 'Mount Messenger'?" in text and "Mount Messenger, Manganui, Taimana" in text
    assert "WHY:" in text and "FIX:" in text


def test_a_repeated_name_must_be_given_by_its_depths(tmp_path):
    with pytest.raises(FormationNotFound, match=r"listed 2 times .*line 3: top 874.014, base 1250.75.*line 5: top "
                                                r"2164.99.*--formation NAME --top D --base D"):
        read_tops(_file(tmp_path, "nz.csv", NZ)).interval("manganui")


def test_a_well_column_keeps_this_wells_rows(tmp_path):
    path = _file(tmp_path, "wells.csv", WELLS)
    table = read_tops(path, ["tw1", "Well-A"])
    assert table.columns == {"name": "Zone", "top": "Top MD (m)", "well": "Well Name"} and table.wells == ("WELL-A",)
    assert [t.name for t in table.tops] == ["Alpha", "Beta"] and {t.unit for t in table.tops} == {"m"}
    got = table.interval("alpha")
    assert (got.top, got.base) == (1000.0, 1100.0)          # the next top of this well, not another well's
    with pytest.raises(FormationNotFound, match=r"no rows for this well .*'other'.*lists WELL-A, WELL-B"):
        read_tops(path, ["other"])


@pytest.mark.parametrize("header, unit", [("name,Top (ft)", "ft"), ("zone,top_md_m", "m"), ("horizon,TOP [M]", "m"),
                                          ("name,depth", None)])
def test_a_unit_in_the_header(tmp_path, header, unit):
    table = read_tops(_file(tmp_path, "h.csv", f"{header}\nA,100\nB,200\n"))
    assert table.interval("A").unit == unit and table.interval("A").base == 200.0


def test_the_unit_given_then_the_las_unit_when_the_table_states_none(tmp_path):
    path = _file(tmp_path, "t.csv", "formation,top\nA,100\nB,200\n")
    assert read_tops(path, depth_unit="ft", las_unit="M").tops[0].unit == "ft"
    assert read_tops(path, las_unit="F").tops[0].unit == "ft"
    assert read_tops(path).tops[0].unit is None


def test_the_table_and_the_unit_given_disagreeing_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="states its depths in ft and the depth unit given is m"):
        read_tops(_file(tmp_path, "ks.csv", KS), depth_unit="metres")
    assert read_tops(_file(tmp_path, "ks.csv", KS), depth_unit="FT").tops[0].unit == "ft"


def test_mixed_units_compare_in_one_unit(tmp_path):
    table = read_tops(_file(tmp_path, "t.csv", "name,top,unit\nA,100,m\nB,350,ft\nC,120,m\n"))
    got = table.interval("A")
    assert got.base == pytest.approx(350 * 0.3048) and got.base_from == "next top B"


def test_a_unit_column_named_unit_versus_a_name_column_named_unit(tmp_path):
    table = read_tops(_file(tmp_path, "t.csv", "unit,top\nUpper sand,100\nLower sand,150\n"))
    assert table.columns == {"name": "unit", "top": "top"}
    assert table.interval("upper sand").base == 150.0


@pytest.mark.parametrize("text", ["A,100\nB,200\n", "A,100,150\nB,200,250\n", "name\ttop\nA\t100\nB\t200\n",
                                  "name;top\nA;100\nB;200\n"])
def test_other_layouts(tmp_path, text):
    assert read_tops(_file(tmp_path, "t.txt", text)).interval("a").top == 100.0


def test_an_excel_sheet(tmp_path):
    import pandas as pd
    path = tmp_path / "tops.xlsx"
    pd.DataFrame({"Formation": ["A", "B"], "Top (m)": [100.0, 150.0], "Base (m)": [140.0, None]}).to_excel(path, index=False)
    got = read_tops(path).interval("b")
    assert (got.top, got.base, got.unit, got.base_from) == (150.0, None, "m", "end of log")
    assert read_tops(path).interval("a").base == 140.0


def test_a_table_without_a_name_or_top_column(tmp_path):
    with pytest.raises(ValueError, match=r"has no top column \(its columns: formation, thickness\).*formation, "
                                         r"formation_name, name"):
        read_tops(_file(tmp_path, "t.csv", "formation,thickness\nA,10\n"))
    with pytest.raises(ValueError, match="line 3 has no numeric top"):
        read_tops(_file(tmp_path, "t.csv", "formation,top\nA,100\nB,deep\n"))
    with pytest.raises(FileNotFoundError, match="no tops file"):
        read_tops(tmp_path / "missing.csv")


# --- the interval ------------------------------------------------------------------------------------------------------

def test_the_whole_well_by_default(las):
    got = A._interval(las, None, None, None, None, None, {})
    assert got == {"name": "whole well", "top": 1000.0, "base": 1004.0, "closed": True, "unit": "m",
                   "from": "the whole log (no formation or depths given)", "las_unit": "m", "report": "m"}


def test_depths_given_named_or_not(las):
    got = A._interval(las, None, None, 1001.0, 1003.0, None, {})
    assert (got["name"], got["top"], got["base"], got["closed"], got["unit"]) == \
           ("depth interval 1001-1003 m", 1001.0, 1003.0, True, "m")
    named = A._interval(las, "Upper sand", None, 1001.0, 1003.0, None, {})
    assert named["name"] == "Upper sand" and named["from"] == "depths given"


def test_depths_in_another_unit_and_one_end_left_open(las):
    got = A._interval(las, None, None, 3285.0, None, "ft", {})
    assert got["unit"] == "ft" and got["report"] == "ft" and got["base"] == pytest.approx(1004.0 / 0.3048)
    got = A._interval(las, None, None, None, 1002.0, None, {})
    assert (got["top"], got["base"]) == (1000.0, 1002.0)


def test_the_answer_unit_follows_the_unit_given(las):
    assert A._interval(las, None, None, None, None, "ft", {})["report"] == "ft"      # the whole well, shown in feet


def test_a_formation_from_the_tops_file(las, tmp_path):
    tops = _file(tmp_path, "tops.csv", "formation,top\nUpper,1000.5\nLower,1002\n")
    got = A._interval(las, "upper", tops, None, None, None, {})
    assert (got["name"], got["top"], got["base"], got["closed"], got["unit"]) == ("Upper", 1000.5, 1002.0, False, "m")
    assert got["from"] == "tops file tops.csv, base: next top Lower"


def test_interval_errors(las, tmp_path):
    tops = _file(tmp_path, "tops.csv", "formation,top\nUpper,1000.5\nLower,1002\n")
    with pytest.raises(ValueError, match="both a tops file and depths"):
        A._interval(las, "Upper", tops, 1000.0, None, None, {})
    with pytest.raises(ValueError, match="tops file is given without a formation.*Upper, Lower"):
        A._interval(las, None, tops, None, None, None, {})
    with pytest.raises(ValueError, match="named without its depths.*--tops FILE.*--top D --base D"):
        A._interval(las, "Upper", None, None, None, None, {})
    with pytest.raises(ValueError, match=r"base \(1001\) is not below the top \(1003\)"):
        A._interval(las, None, None, 1003.0, 1001.0, None, {})
    with pytest.raises(ValueError, match="'yards' is not m or ft"):
        A._interval(las, None, None, 1001.0, 1003.0, "yards", {})


def test_a_formation_named_alone_uses_the_settings_tops_table(las):
    got = A._interval(las, "Upper", None, None, None, None, {"tops_csv": "/data/tops.csv"})
    assert got["top"] is None and got["from"] == "the settings' tops table tops.csv"


# --- the data settings -------------------------------------------------------------------------------------------------

def _policy():
    from petroharness.config import ResourcePaths
    return ResourcePaths().policy_file


def test_settings_built_from_the_las(las, tmp_path, monkeypatch):
    monkeypatch.delenv("PETROHARNESS_DATA", raising=False)
    data, source = A._settings(las, None, None, None, tmp_path / "c", _policy())
    assert source == "built from the LAS"
    assert data == {"las_dir": str(las.parent), "cache_dir": str(tmp_path / "c"),
                    "interpret": {"vcl_cutoff": 0.3, "sw_cutoff": 0.7}}       # the policy's net-pay cutoffs
    data, _ = A._settings(las, None, "costa", "LITH", tmp_path / "c", _policy())
    assert data["interpret"] == {"context_profile": "costa"} and data["lithology_curve"] == "LITH"


def test_a_settings_file_is_the_base(las, tmp_path, monkeypatch):
    path = _file(tmp_path, "s.yaml", "data:\n  las_dir: /elsewhere\n  interpret: {sw_model: indonesia}\n"
                                     "  lithology_nomenclature: /x.xlsx\n")
    monkeypatch.delenv("PETROHARNESS_DATA", raising=False)
    data, source = A._settings(las, path, None, None, tmp_path / "c", _policy())
    assert source == str(path) and data["las_dir"] == "/elsewhere" and data["lithology_nomenclature"] == "/x.xlsx"
    assert data["interpret"] == {"sw_model": "indonesia", "vcl_cutoff": 0.3, "sw_cutoff": 0.7}
    monkeypatch.setenv("PETROHARNESS_DATA", str(path))
    assert A._settings(las, None, None, None, tmp_path / "c", _policy())[1] == str(path)
    with pytest.raises(FileNotFoundError, match="no data settings file"):
        A._settings(las, tmp_path / "none.yaml", None, None, tmp_path / "c", _policy())


def test_given_settings_stand_in_for_the_file(monkeypatch):
    from petroharness.config import HarnessConfig, given_settings, user_settings
    monkeypatch.setenv("PETROHARNESS_DATA", "/no/such/file.yaml")
    with given_settings({"data": {"las_dir": "/w"}}):
        assert user_settings("data") == {"las_dir": "/w"} and user_settings("eval") == {}
        assert str(HarnessConfig.load().data.las_dir) == "/w"
    with pytest.raises(ValueError, match="no data settings"):
        user_settings("data")


def test_skills_none_reaches_the_config(monkeypatch, tmp_path):
    from petroharness.agent import direction
    from petroharness.config import HarnessConfig, given_settings, skills_setting
    kw = A.options(A.parser().parse_args(["--las", "a.las", "--question", "q", "--skills", "none"]))
    assert kw["skills"] == "none"
    assert A.options(A.parser().parse_args(["--las", "a.las", "--question", "q"]))["skills"] is None
    monkeypatch.setenv("PETROHARNESS_SKILLS", "skills/researched")         # the option wins over the environment
    with given_settings({"data": {"las_dir": str(tmp_path)}, "skills": kw["skills"]}):
        cfg = HarnessConfig.load()
        assert skills_setting(cfg) == "none" and direction.plugged(cfg) is None
    assert skills_setting() == "skills/researched"                          # outside the run: as before
    monkeypatch.delenv("PETROHARNESS_SKILLS")
    with given_settings({"data": {"las_dir": str(tmp_path)}}):              # unset: the packaged library
        assert direction.plugged(HarnessConfig.load()).name == "researched"


def test_the_model_endpoint(monkeypatch):
    from petroharness.models import MODELS
    monkeypatch.delenv("PETROHARNESS_MODEL_URL", raising=False)
    monkeypatch.delenv("K2H_TOOL_URLS", raising=False)
    with pytest.raises(ValueError, match="no model endpoint.*PETROHARNESS_MODEL_URL"):
        A._model_key(None, None)
    assert A._model_key(None, lambda cfg: None) == "k200t"                 # a stub model needs none
    key = A._model_key("http://h1:8100/v1,http://h2:8100/v1", None)
    assert MODELS[key] == (MODELS["k200t"][0], ["http://h1:8100/v1", "http://h2:8100/v1"])
    monkeypatch.setenv("PETROHARNESS_MODEL_URL", ",".join(MODELS["k200t"][1]))
    assert A._model_key(None, None) == "k200t"
    monkeypatch.delenv("PETROHARNESS_MODEL_URL")
    monkeypatch.setenv("K2H_TOOL_URLS", "http://h3:8100/v1")              # read too
    assert MODELS[A._model_key(None, None)][1] == ["http://h3:8100/v1"]


def test_any_chat_model_by_its_served_name(monkeypatch):
    from petroharness.models import GENERIC_CARD, MODELS, label
    key = A._model_key("http://h:8000/v1", None, "Qwen/Qwen3-32B")
    assert MODELS[key] == (GENERIC_CARD, ["http://h:8000/v1"], "Qwen/Qwen3-32B")
    assert A._model_label(key) == "Qwen/Qwen3-32B" and label(MODELS["k200t"][0]) == "K2-Horizon-7B"
    assert A._model_key(None, lambda cfg: None, "m") != "k200t"            # a stub model with a name: the generic card
    with pytest.raises(ValueError, match="names no model.*--model NAME"):
        A._model_key("http://h:8000/v1", None, model_card="generic")
    with pytest.raises(ValueError, match="no model card 'nope'.*generic, k2_horizon_7b_grpo200"):
        A._model_key("http://h:8000/v1", None, model_card="nope")


def test_a_model_card_of_your_own(tmp_path):
    from petroharness.models import MODELS
    card = _file(tmp_path, "my.yaml", "model:\n  model: gpt-x\n  label: GPT X\n  send_template_kwargs: false\n"
                                      "  max_tokens_param: max_completion_tokens\n")
    key = A._model_key("https://api.example.com/v1", None, model_card=str(card))
    assert MODELS[key] == (str(card.resolve()), ["https://api.example.com/v1"]) and A._model_label(key) == "GPT X"
    bad = _file(tmp_path, "bad.yaml", "model:\n  model: m\n  temprature: 0.2\n")
    with pytest.raises(ValueError, match="temprature"):                    # a misspelt field is an error
        A._model_key("http://h/v1", None, model_card=str(bad))


def test_the_run_asks_for_the_named_model(monkeypatch, tmp_path):
    """graph.answer builds the client from the card, with the served name --model gives."""
    from petroharness.agent import graph
    from petroharness.config import given_settings
    from petroharness.tasks import Task
    seen = []

    def factory(cfg):
        seen.append((cfg.model.model, cfg.model.send_template_kwargs, cfg.model.base_url))
        raise RuntimeError("stop here")

    key = A._model_key("http://h:8000/v1", None, "my-model")
    task = Task(task_id="t0", question="q", well="W", formation="F", las_path=tmp_path / "W.las")
    with given_settings({"data": {"las_dir": str(tmp_path)}}), pytest.raises(RuntimeError, match="stop here"):
        graph.answer(task, key, 1, llm_factory=factory)
    assert seen == [("my-model", False, "http://h:8000/v1")]


# --- the command line --------------------------------------------------------------------------------------------------

def test_the_command_line(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = A.parser().parse_args(["--las", "w/TW1.las", "--question", "How porous?", "--formation", "Upper", "--tops",
                                  "t.csv", "--depth-unit", "ft", "--lithology-curve", "LITH", "--formation-lithology",
                                  "sandstone", "--model-url", "http://h:8100/v1"])
    kw = A.options(args)
    assert kw == {"las": Path("w/TW1.las"), "question": "How porous?", "formation": "Upper", "tops": Path("t.csv"),
                  "top": None, "base": None, "depth_unit": "ft", "lithology_curve": "LITH",
                  "formation_lithology": "sandstone", "profile": None, "out": Path.cwd() / "petroharness-out" / "TW1",
                  "model_url": "http://h:8100/v1", "model": None, "model_card": None, "settings": None, "skills": None,
                  "max_steps": None}
    kw = A.options(A.parser().parse_args(["--las", "a.las", "--question", "q", "--model", "Qwen/Qwen3-32B"]))
    assert (kw["model"], kw["model_card"]) == ("Qwen/Qwen3-32B", None)
    qf = _file(tmp_path, "q.txt", "What is the net pay?\n")
    kw = A.options(A.parser().parse_args(["--las", "a.las", "--question-file", str(qf), "--top", "10", "--base", "20.5",
                                          "--out", "o"]))
    assert (kw["question"], kw["top"], kw["base"], kw["out"]) == ("What is the net pay?\n", 10.0, 20.5, Path("o"))


@pytest.mark.parametrize("argv", [["--question", "q"], ["--las", "a.las"],
                                  ["--las", "a.las", "--question", "q", "--question-file", "f"],
                                  ["--las", "a.las", "--question", "q", "--top", "deep"]])
def test_command_line_errors(argv, capsys):
    with pytest.raises(SystemExit) as ex:
        A.parser().parse_args(argv)
    assert ex.value.code == 2


def test_wrong_inputs_exit_2_with_the_message(tmp_path, capsys):
    assert A.main(["--las", str(tmp_path / "none.las"), "--question", "q"]) == 2
    assert "WHAT: no LAS file at" in capsys.readouterr().err


def _dispatch(monkeypatch, argv):
    """What the console script runs for these arguments: ("own well", argv) or ("benchmark", argv)."""
    from petroharness import cli
    got = []
    monkeypatch.setattr(A, "main", lambda a: got.append(("own well", a)) or 0)
    monkeypatch.setattr(cli, "benchmark", lambda a=None: got.append(("benchmark", a)))
    monkeypatch.setattr(sys, "argv", ["petroharness", *argv])
    cli.main()
    return got


def test_the_console_script_asks_about_a_well_by_default(monkeypatch):
    own = ["--las", "x.las", "--question", "q"]
    assert _dispatch(monkeypatch, own) == [("own well", own)]
    assert _dispatch(monkeypatch, ["ask", *own]) == [("own well", own)]          # the explicit form
    assert _dispatch(monkeypatch, []) == [("own well", [])]                     # (argparse then asks for --las)


def test_benchmark_mode_and_the_older_arm_form(monkeypatch):
    batch = ["--arm", "A1", "--rep", "1", "--ids", "ids.json", "--gt-dir", "gt"]
    assert _dispatch(monkeypatch, ["benchmark", *batch]) == [("benchmark", batch)]
    assert _dispatch(monkeypatch, batch) == [("benchmark", batch)]              # scripts' form: still the benchmark
    assert _dispatch(monkeypatch, ["--cats", "porosity", "--arm=A2"]) == [("benchmark", ["--cats", "porosity", "--arm=A2"])]


def test_the_older_arm_form_reaches_the_batch_runner(monkeypatch, capsys):
    """Not stubbed: the batch runner's own parser reads the arguments (here it stops at a missing --ids)."""
    from petroharness import cli
    monkeypatch.setattr(sys, "argv", ["petroharness", "--arm", "A1", "--gt-dir", "gt"])
    with pytest.raises(SystemExit) as ex:
        cli.main()
    err = capsys.readouterr().err
    assert ex.value.code == 2 and err.startswith("usage: petroharness benchmark") and "--ids" in err


def test_the_help_shows_the_own_well_usage_and_names_benchmark_mode(monkeypatch, capsys):
    from petroharness import cli
    for argv, want in ((["--help"], ["usage: petroharness [-h] --las LAS", "petroharness benchmark --help"]),
                       (["benchmark", "--help"], ["usage: petroharness benchmark", "--arm ARM", "--gt-dir"])):
        monkeypatch.setattr(sys, "argv", ["petroharness", *argv])
        with pytest.raises(SystemExit) as ex:
            cli.main()
        out = capsys.readouterr().out
        assert ex.value.code == 0 and all(w in out for w in want), out[:400]


# --- end to end with a stub model (data: a sample well) ----------------------------------------------------------------

@pytest.mark.data
@pytest.mark.parametrize("skills", [None, "none"])
def test_a_question_about_a_sample_well_end_to_end(tmp_path, monkeypatch, skills):
    from test_read import Stub
    las, tops = SAMPLES / "tuhua-7.las", SAMPLES / "formations_tuhua-7.csv"
    if not las.exists() or not tops.exists():
        pytest.skip(f"no sample wells at {SAMPLES} (PETROHARNESS_SAMPLE_LAS)")
    monkeypatch.delenv("PETROHARNESS_DATA", raising=False)
    monkeypatch.delenv("PETROHARNESS_SKILLS", raising=False)
    llm = Stub([{"topics": ["porosity", "water_saturation"], "named": ["RDEP"]}])
    r = A.ask(las, "What are the porosity and water saturation in this formation?", formation="mount messenger",
              tops=tops, out=tmp_path / "out", skills=skills, llm_factory=lambda cfg: llm)
    assert r.ok and r.status == "ok", r.trace.get("traceback")
    assert r.interval == {"name": "Mount Messenger", "top": 590.55, "base": 873.8616, "unit": "m",
                          "samples": r.interval["samples"], "from": "tops file formations_tuhua-7.csv, base: stated base"}
    assert r.interval["samples"] > 1000
    a = r.trace["ask"]
    assert a["lithology"]["source"] == "shale-volume bands" and a["zones"]           # no lithology log in this LAS
    assert a["interpret"] == {"vcl_cutoff": 0.3, "sw_cutoff": 0.7} and a["settings"] == "built from the LAS"
    assert r.trace["formation"] == "Mount Messenger" and r.trace["well"] == "tuhua-7"
    library = "none" if skills == "none" else "researched"
    assert r.trace["skills"]["library"] == library and a["skills"]["library"] == library and a["skills_given"] == skills
    assert ("DIRECTION\n" in llm.prompt("step_1")) == (skills is None)          # the guide index only with a library
    assert "WELL tuhua-7, FORMATION Mount Messenger" in llm.prompt("step_1")
    assert r.answer.startswith("## Porosity")
    md = (tmp_path / "out" / "answer.md").read_text()
    assert md.startswith("# tuhua-7: Mount Messenger") and "590.55-873.862 m" in md and "## Porosity" in md
    assert ("Skill library:** none (no guides)" in md) == (skills == "none")
    assert json.loads((tmp_path / "out" / "trace.json").read_text())["ask"]["interval"]["top"] == 590.55
    assert any((tmp_path / "out" / ".cache").rglob("*.pkl"))                       # the interpreted well, cached
