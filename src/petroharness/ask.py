"""One question about one LAS file, any well: the console script's default command (docs/USAGE.md).

    petroharness --las WELL.las --question "..." [--formation NAME --tops TOPS.csv | [--formation NAME]
                 --top D --base D] [--depth-unit m|ft] [--lithology-curve MNEMONIC] [--formation-lithology TEXT]
                 [--profile NAME] [--out DIR] [--model NAME | --model-card CARD] [--model-url URL]

The interval asked about: a formation of a tops file (well/tops.py reads it), explicit depths, or by default the whole
well. No data settings file is needed: the data settings are built from the LAS (a file given with --settings or
PETROHARNESS_DATA is the base they start from). Petrophys interprets the LAS with its default workflow (net-pay cutoffs
as the harness policy states them), or with a context profile (--profile). A LAS without a lithology log is zoned by
shale-volume bands. Writes answer.md and trace.json to the output folder and prints the answer.

The model: any chat model behind an OpenAI-compatible endpoint (--model NAME, or a model card with --model-card;
default: K2-Horizon-7B's card; petroharness.models, docs/MODELS.md), at --model-url or PETROHARNESS_MODEL_URL.

The same in Python: petroharness.ask.ask(las, question, formation=..., tops=...) -> AskResult.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from petroharness.well.tops import depth_unit_name, read_tops

# The policy's net-pay cutoffs as petrophys.interpret options (DynamicWorkflowConfig): the harness checks that the
# interpretation used the policy's cutoffs, and the library's own defaults for these differ.
POLICY_CUTOFFS = {"vcl_cutoff": "vcl_max", "sw_cutoff": "sw_max"}
WHOLE_WELL = "whole well"


@dataclass
class AskResult:
    answer: str
    status: str                   # ok, unresolved_numbers (a number no result shows survived the checker), error: ...
    trace: dict
    interval: dict                # what was asked about: name, top, base, unit, from
    out_dir: Path | None = None
    files: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.status.startswith("error")


# --- the inputs ------------------------------------------------------------------------------------------------------

def _las_header(las: Path) -> tuple[str | None, list[str]]:
    """(the LAS's depth unit as m/ft, or None; the names the well goes by: file stem, WELL, UWI and API headers)."""
    import lasio

    head = lasio.read(str(las), ignore_data=True)
    unit = depth_unit_name(head.curves[0].unit) if len(head.curves) else None
    names = [las.stem]
    for key in ("WELL", "UWI", "API", "APIN"):
        item = head.well.get(key) if key in head.well else None
        if item is not None and str(item.value).strip():
            names.append(str(item.value).strip())
    return unit, names


def _log_range(las: Path) -> tuple[float, float]:
    """The first and last depth of the log, in the LAS's own unit."""
    import numpy as np

    from petroharness.well.prepare import read_depth

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        depth = read_depth(las)
    return float(np.nanmin(depth)), float(np.nanmax(depth))


def _settings(las: Path, settings: Path | None, profile: str | None, lithology_curve, cache_dir: Path,
              policy_file: Path) -> tuple[dict, str]:
    """The data settings for this LAS and where they came from: a settings file's (--settings, else PETROHARNESS_DATA)
    data section as the base, else none; the LAS's folder as the data folder; petrophys.interpret with a context
    profile, else the library's defaults with the policy's net-pay cutoffs."""
    from petroharness.config import DATA_FILE_ENV
    from petroharness.well.prepare import load_policy

    path = settings or (Path(os.environ[DATA_FILE_ENV]) if os.environ.get(DATA_FILE_ENV) else None)
    data: dict = {}
    if path is not None:
        if not Path(path).is_file():
            raise FileNotFoundError(f"WHAT: no data settings file at {path}. FIX: give an existing YAML file "
                                    f"(configs/data.example.yaml shows the keys), or unset {DATA_FILE_ENV}.")
        data = dict((yaml.safe_load(Path(path).read_text()) or {}).get("data") or {})
    data.setdefault("las_dir", str(las.parent))
    data.setdefault("cache_dir", str(cache_dir))
    if lithology_curve:
        data["lithology_curve"] = lithology_curve
    if profile:
        if data.get("interpreter"):
            raise ValueError(f"WHAT: --profile {profile} and the settings' data.interpreter are both set. FIX: keep one.")
        data["interpret"] = {"context_profile": profile}
    elif not data.get("interpreter"):
        options = dict(data.get("interpret") or {})
        if not options.get("context_profile"):           # a profile fixes its own settings
            cutoffs = load_policy(policy_file).get("cutoffs") or {}
            for option, key in POLICY_CUTOFFS.items():
                if cutoffs.get(key) is not None:
                    options.setdefault(option, cutoffs[key])
        data["interpret"] = options
    return data, (str(path) if path is not None else "built from the LAS")


def _interval(las: Path, formation: str | None, tops: Path | None, top: float | None, base: float | None,
              depth_unit: str | None, data: dict) -> dict:
    """The interval asked about: {name, top, base, closed, unit (m/ft, or None for the LAS's own), from, report}.
    top None: the settings' tops table gives the named formation's interval (FormationView)."""
    stated = depth_unit_name(depth_unit) if depth_unit else None
    if depth_unit and stated is None:
        raise ValueError(f"WHAT: depth unit {depth_unit!r} is not m or ft. FIX: give m or ft.")
    las_unit, names = _las_header(las)
    if tops is not None:
        if top is not None or base is not None:
            raise ValueError("WHAT: both a tops file and depths (--top/--base) are given. WHY: either gives the "
                             "interval. FIX: keep one: --formation NAME --tops FILE, or --top D --base D.")
        table = read_tops(tops, names, stated, las_unit)
        if not formation:
            raise ValueError(f"WHAT: a tops file is given without a formation. FIX: add --formation with one of its "
                             f"names: {', '.join(table.names())}.")
        got = table.interval(formation)
        source = f"tops file {Path(tops).name}, base: {got.base_from}"
        out = {"name": got.name, "top": got.top, "base": got.base, "closed": got.closed, "unit": got.unit,
               "from": source}
    elif top is not None or base is not None:
        unit = stated or las_unit
        if top is None or base is None:
            first, last = _log_range(las)
            factor = 1.0 if unit is None or las_unit is None else _factor(las_unit, unit)
            top = first * factor if top is None else top
            base = last * factor if base is None else base
        if base <= top:
            raise ValueError(f"WHAT: the base ({base:g}) is not below the top ({top:g}). FIX: give --top above --base "
                             "(depths increase downwards).")
        label = unit or "(LAS depth unit)"
        out = {"name": formation or f"depth interval {top:g}-{base:g} {label}", "top": float(top),
               "base": float(base), "closed": True, "unit": unit, "from": "depths given"}
    elif formation:
        if not data.get("tops_csv"):
            raise ValueError(f"WHAT: formation {formation!r} is named without its depths. WHY: the interval comes "
                             "from a tops file or from depths. FIX: add --tops FILE (a CSV with formation,top[,base]), "
                             "or give the depths: --top D --base D.")
        out = {"name": formation, "top": None, "base": None, "closed": False, "unit": None,
               "from": f"the settings' tops table {Path(data['tops_csv']).name}"}
    else:
        first, last = _log_range(las)
        out = {"name": WHOLE_WELL, "top": first, "base": last, "closed": True, "unit": las_unit,
               "from": "the whole log (no formation or depths given)"}
    out["las_unit"] = las_unit
    out["report"] = stated or out["unit"] or las_unit
    return out


def _factor(unit: str, to: str) -> float:
    from petroharness.well.tops import convert
    return convert(1.0, unit, to)


def _model_key(model_url: str | None, llm_factory, model: str | None = None, model_card: str | None = None) -> str:
    """The model registry key (petroharness.models): the model card (--model-card; else the generic card when --model
    names the served model; else K2-Horizon-7B's) and the endpoints (--model-url, else PETROHARNESS_MODEL_URL;
    comma-separated)."""
    from petroharness.models import URL_ENVS, env_urls, register

    urls = [u.strip() for u in model_url.split(",") if u.strip()] if model_url else env_urls()
    if not urls:
        if llm_factory is not None and not (model or model_card):
            return "k200t"
        if llm_factory is None:
            raise ValueError("WHAT: no model endpoint. WHY: the model answers through an OpenAI-compatible endpoint "
                             f"(/v1). FIX: set {URL_ENVS[0]}=http://HOST:PORT/v1 (several, comma-separated) or pass "
                             "--model-url.")
        urls = ["http://stand-in/v1"]               # a stand-in model (tests) is reached through no endpoint
    return register(urls, model_card, model)


# --- one question ----------------------------------------------------------------------------------------------------

def ask(las, question: str, *, formation: str | None = None, tops=None, top: float | None = None,
        base: float | None = None, depth_unit: str | None = None, lithology_curve: str | None = None,
        formation_lithology: str | None = None, profile: str | None = None, out=None,
        model_url: str | None = None, model: str | None = None, model_card: str | None = None, settings=None,
        skills: str | None = None, max_steps: int | None = None, llm_factory: Callable | None = None,
        on_view: Callable | None = None, direct: bool = True) -> AskResult:
    """One question about one LAS file -> AskResult (answer, status, trace, the interval used). The interval: the
    formation `formation` of the tops file `tops`; or the depths `top`/`base` (`formation` names it); or, with
    neither, the whole well. `depth_unit` (m or ft): the unit of the depths given and of the answer's depths (default:
    the tops file's, else the LAS's own). `skills`: the skill library the model reads guides from (a library folder, or
    "none" for no guides; None: PETROHARNESS_SKILLS, else the packaged library). `model`: the served model's name
    (any chat model; the generic card); `model_card`: a model card's YAML file or a packaged card's name (default:
    K2-Horizon-7B's); `model_url`: the endpoint(s), comma-separated (default: PETROHARNESS_MODEL_URL). `out`: a folder
    for answer.md and trace.json (None: nothing is written). `on_view(view)`: called with the interval's view
    (petroharness.well.view.FormationView) once Petrophys has interpreted the well, before the first model call (the
    web UI plots the logs from it). `direct`: the model first says whether the question is direct (a value, a setting
    or a fact that one or two lookups state: a short route and a short answer) or needs an investigation (docs/GRAPH.md,
    "The direct route"); False: always an investigation.
    Errors in the inputs raise ValueError (FormationNotFound for a name a tops file lacks); a failed run returns
    status "error: ..." with the traceback in the trace."""
    from petroharness.agent import graph
    from petroharness.cli import COMMIT
    from petroharness.config import given_settings

    las = Path(las).expanduser().resolve()
    if not las.is_file():
        raise FileNotFoundError(f"WHAT: no LAS file at {las}. FIX: give the path of the well's LAS file.")
    question = str(question or "").strip()
    if not question:
        raise ValueError("WHAT: the question is empty. FIX: give the question to answer.")
    key = _model_key(model_url, llm_factory, model, model_card)
    out_dir = Path(out).expanduser().resolve() if out is not None else None
    with tempfile.TemporaryDirectory(prefix="petroharness-ask-") as tmp:
        cache = out_dir / ".cache" if out_dir is not None else Path(tmp)
        p = prepare(las, key, formation=formation, tops=tops, top=top, base=base, depth_unit=depth_unit,
                    lithology_curve=lithology_curve, formation_lithology=formation_lithology, profile=profile,
                    settings=settings, skills=skills, cache=cache)
        task, sent = task_for(p, question)
        check(p, task, on_view)
        with given_settings(p.given):
            got = graph.answer(task, key, 1, max_steps or graph.MAX_STEPS, "open", "profile",
                               llm_factory=llm_factory, commit=COMMIT, depth=direct)
    trace = got["trace"]
    trace["answer"] = got["answer"]
    trace["ask"] = ask_record(p, question, sent, trace)
    result = AskResult(answer=got["answer"], status=got["status"], trace=trace, interval=p.used, out_dir=out_dir)
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        result.files = {"answer": out_dir / "answer.md", "trace": out_dir / "trace.json"}
        result.files["answer"].write_text(_answer_md(result, las))
        result.files["trace"].write_text(json.dumps(trace, indent=1, default=str))
    return result


@dataclass
class Prepared:
    """One interval of one LAS, ready for questions: what ask() and a conversation (petroharness.session) set up
    before the model runs. `check` fills the view, the interval as used and the zoning's source."""
    las: Path
    key: str                      # the model registry key
    data: dict                    # the data settings built for this LAS
    source: str                   # where they came from
    span: dict                    # the interval asked about (_interval)
    said: str                     # the operator's lithology for the formation, when given
    given: dict                   # the settings every question of this interval runs under (config.given_settings)
    skills_given: str | None = None
    lithology_curve: str | None = None
    view: object = None
    used: dict = field(default_factory=dict)
    litho: dict = field(default_factory=dict)


def prepare(las: Path, key: str, *, formation=None, tops=None, top=None, base=None, depth_unit=None,
            lithology_curve=None, formation_lithology=None, profile=None, settings=None, skills=None,
            cache: Path) -> Prepared:
    """The data settings and the interval for this LAS (the arguments as ask()'s), with `cache` as the folder the
    interpreted well is kept in."""
    from petroharness.config import ResourcePaths
    data, source = _settings(las, Path(settings) if settings else None, profile, lithology_curve, cache,
                             ResourcePaths().policy_file)
    span = _interval(las, formation, Path(tops) if tops else None, top, base, depth_unit, data)
    las_unit = span["las_unit"]
    data.setdefault("depth_unit", "las" if span["report"] in (None, las_unit) else span["report"])
    library = str(skills or "").strip()
    if library and library.lower() != "none" and Path(library).expanduser().exists():
        library = str(Path(library).expanduser().resolve())      # a folder of the user's (relative to here)
    given = {"data": data, "eval": {}, **({"skills": library} if library else {})}
    return Prepared(las=las, key=key, data=data, source=source, span=span,
                    said=str(formation_lithology or "").strip(), given=given, skills_given=skills,
                    lithology_curve=lithology_curve)


def task_for(p: Prepared, question: str, turn: int = 1):
    """(the task of one question about the prepared interval, the question as the model reads it). `turn`: the
    question's number in a conversation (the first question's task is ask()'s)."""
    from petroharness.tasks import Task
    span, las_unit = p.span, p.span["las_unit"]
    sent = question
    if p.said and p.data.get("zone_layout", "lithology_runs") != "formation":
        # the zones are lithology-log runs or shale-volume bands: the operator's lithology reaches the model with
        # the question (the "formation" layout shows it on the zone)
        sent = f"{question}\n\n(The operator states this formation's lithology: {p.said}.)"
    ident = f"{p.las}|{question}|{span}" + (f"|question {turn}" if turn > 1 else "")
    task = Task(task_id="a" + hashlib.sha256(ident.encode()).hexdigest()[:10],
                question=sent, well=p.las.stem, formation=span["name"], las_path=p.las, top=span["top"],
                base=span["base"], depth_unit=None if span["top"] is None else
                ("las" if span["unit"] in (None, las_unit) else span["unit"]),
                base_closed=span["closed"], formation_lithology=p.said.upper() or None)
    return task, sent


def check(p: Prepared, task, on_view: Callable | None = None) -> None:
    """The interval checked before any model call: Petrophys interprets the well, the interval must hold samples and a
    named lithology curve data. Fills p.view, p.used and p.litho; `on_view(view)` is then called."""
    from petroharness.config import DataPaths, HarnessConfig
    from petroharness.well.view import FormationView
    las, span, las_unit = p.las, p.span, p.span["las_unit"]
    cfg = HarnessConfig(data=DataPaths(**p.data), eval=None)
    view = FormationView.build(task, cfg)
    n = int(view.mask.sum())
    if n == 0:
        first, last = (float(view.prep.depth.min()), float(view.prep.depth.max())) if view.prep.depth.size else (0, 0)
        raise ValueError(f"WHAT: the interval {span['name']!r} has no samples in {las.name} (the log runs "
                         f"{first:g}-{last:g} {las_unit or ''}). FIX: check the depths and their unit "
                         "(--depth-unit).")
    if p.lithology_curve and view.lithology_curve is None:
        raise ValueError(f"WHAT: the lithology curve {p.lithology_curve!r} has no data in {las.name} (its curves: "
                         f"{', '.join(view.prep.input_curves)}). WHY: the zones come from it. FIX: name one of "
                         "those curves (as Petrophys names it), or leave --lithology-curve out.")
    if on_view is not None:
        on_view(view)
    depth = view.depth
    p.view = view
    p.used = {"name": span["name"], "top": round(float(view.interval.top), 4),
              "base": round(float(view.interval.base if view.interval.base is not None else depth[-1]), 4),
              "unit": view.report_unit, "samples": n, "from": span["from"]}
    if view.lithology_curve:
        p.litho = {"source": "lithology log", "curve": view.lithology_curve,
                   "how": "named" if p.lithology_curve else "detected"}
    elif view.vcl_bands:
        p.litho = {"source": "shale-volume bands", "curve": "VCL", "bands": list(view.vcl_bands)}
    else:
        p.litho = {"source": "none", "curve": None}


def ask_record(p: Prepared, question: str, sent: str, trace: dict) -> dict:
    """The trace's `ask` block: the inputs of one question and what was asked about."""
    from petroharness.well.prepare import library_identity
    return {"las": str(p.las), "question": question, "question_sent": sent if sent != question else None,
            "interval": p.used, "lithology": p.litho,
            "zones": [{"zone": z.zone_id, "lithology": z.lithology, "top": z.top, "base": z.base}
                      for z in p.view.zones],
            "model": _model_label(p.key), "settings": p.source, "skills": trace.get("skills"),
            "skills_given": p.skills_given,
            "interpret": p.data.get("interpret"), "interpreter": p.data.get("interpreter"),
            "petrophys": library_identity()}


def _model_label(key: str) -> str:
    """The model as people read it: its name, from --model or its card."""
    from petroharness.models import MODELS, label
    file, _, *named = MODELS[key]
    return label(file, named[0] if named else None)


def _interval_text(iv: dict) -> str:
    return f"{iv['top']:g}-{iv['base']:g} {iv['unit']} ({iv['samples']} samples; {iv['from']})"


def _lithology_text(litho: dict) -> str:
    if litho["source"] == "lithology log":
        return f"zones from the lithology log {litho['curve']} ({litho['how']})"
    if litho["source"] == "shale-volume bands":
        lo, hi = litho["bands"]
        return f"no lithology log: zones from shale-volume bands (VCL below {lo:g}, {lo:g}-{hi:g}, above {hi:g})"
    return "no lithology log and no shale volume: the interval is not zoned by lithology"


def _skills_text(stamp) -> str:
    stamp = stamp or {}
    if stamp.get("library") in (None, "none"):
        return "none (no guides)"
    return f"{stamp['library']}" + (f" (version {stamp['version']})" if stamp.get("version") else "")


def _route_text(trace: dict) -> str:
    from petroharness.agent.graph import route_text
    return route_text(trace)


def _answer_md(result: AskResult, las: Path) -> str:
    a = result.trace["ask"]
    head = [f"# {las.stem}: {result.interval['name']}", "",
            f"- **Question:** {a['question']}",
            f"- **Interval:** {_interval_text(result.interval)}",
            f"- **Lithology:** {_lithology_text(a['lithology'])}",
            f"- **Model:** {a['model']}",
            f"- **Skill library:** {_skills_text(a['skills'])}",
            f"- **Status:** {result.status}, {_route_text(result.trace)}", "", "---", ""]
    body = result.answer if result.answer else f"(no answer: {result.trace.get('error', result.status)})"
    return "\n".join(head) + body.rstrip() + "\n"


# --- the command -----------------------------------------------------------------------------------------------------

EXAMPLES = """examples:
  petroharness --las well.las --formation "Mount Messenger" --tops tops.csv \\
      --question "What are the porosity and water saturation, and is it hydrocarbon-bearing?"
  petroharness --las well.las --top 5300 --base 5600 --depth-unit ft --question "..."
  petroharness --las well.las --question "..."          (the whole well)

The model: K2-Horizon-7B by default; any chat model with --model NAME (as the server lists it), or a model card with
--model-card (docs/MODELS.md). Its endpoint: PETROHARNESS_MODEL_URL=http://HOST:PORT/v1 (comma-separated for several)
or --model-url.

Other commands (each has --help):
  petroharness chat --las well.las ...     keep an interval open and go on asking (docs/SESSIONS.md)
  petroharness audit SESSION               each answer's trail back to the LAS file (docs/EVIDENCE.md)
  petroharness report SESSION              a conversation as one document
  petroharness setup                       what answers a question, with one hash (docs/SETUP.md)
  petroharness ui                          ask in the browser, with live progress and saved runs (docs/UI.md)
  petroharness benchmark                   validation mode: the harness on a benchmark's questions"""


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="petroharness", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description="Answer one petrophysics question about one LAS file: a formation from "
                                             "a tops file, a depth interval, or the whole well.", epilog=EXAMPLES)
    ap.add_argument("--las", required=True, type=Path, help="the well's LAS file")
    q = ap.add_mutually_exclusive_group(required=True)
    q.add_argument("--question", help="the question")
    q.add_argument("--question-file", type=Path, help="a text file holding the question")
    interval_options(ap)
    ap.add_argument("--out", type=Path, help="the output folder (default: ./petroharness-out/<LAS name>)")
    run_options(ap)
    return ap


def interval_options(ap: argparse.ArgumentParser) -> None:
    """The interval, lithology and profile options (ask and chat)."""
    where = ap.add_argument_group("the interval (default: the whole well)")
    where.add_argument("--formation", help="the formation's name (in the tops file; or a label for --top/--base)")
    where.add_argument("--tops", type=Path, help="a tops table (CSV): formation,top[,base][,depth_unit][,well]")
    where.add_argument("--top", type=float, help="the interval's top depth")
    where.add_argument("--base", type=float, help="the interval's base depth")
    where.add_argument("--depth-unit", help="m or ft: the unit of the depths given and of the answer's depths "
                                            "(default: the tops file's, else the LAS's own)")
    lith = ap.add_argument_group("lithology")
    lith.add_argument("--lithology-curve", help="the lithology log's mnemonic (default: detected; none: zones from "
                                                "shale-volume bands)")
    lith.add_argument("--formation-lithology", help="the formation's lithology as you know it, e.g. 'sandstone'")
    ap.add_argument("--profile", help="a Petrophys context profile for wells of a known package (default: "
                                      "Petrophys's default interpretation)")


def run_options(ap: argparse.ArgumentParser) -> None:
    """The model, settings, skills and step-cap options (ask and chat)."""
    llm = ap.add_argument_group("the model (default: K2-Horizon-7B)")
    llm.add_argument("--model", help="the served model's name, for any chat model on an OpenAI-compatible endpoint "
                                     "(as the server lists it at /v1/models)")
    llm.add_argument("--model-card", help="a model card: a YAML file (docs/MODELS.md), or a packaged card's name")
    llm.add_argument("--model-url", help="the model endpoint(s), comma-separated (default: PETROHARNESS_MODEL_URL)")
    ap.add_argument("--settings", type=Path, help="a data settings YAML to start from (default: PETROHARNESS_DATA "
                                                  "if set, else none)")
    ap.add_argument("--skills", help="the skill library the model reads guides from: a library folder, or 'none' for "
                                     "no guides (default: PETROHARNESS_SKILLS if set, else the packaged library)")
    ap.add_argument("--max-steps", type=int, default=None, help="the investigation's step cap (default: the "
                                                                "harness's)")
    ap.add_argument("--investigate", action="store_true",
                    help="give every question a full investigation (default: the model first says whether the "
                         "question is direct, a value or a fact that one or two lookups state, and a direct question "
                         "gets a short route and a short answer)")


def options(args: argparse.Namespace) -> dict:
    """The parsed command line as ask()'s arguments."""
    question = args.question if args.question is not None else Path(args.question_file).read_text()
    return {"las": args.las, "question": question, "formation": args.formation, "tops": args.tops, "top": args.top,
            "base": args.base, "depth_unit": args.depth_unit, "lithology_curve": args.lithology_curve,
            "formation_lithology": args.formation_lithology, "profile": args.profile,
            "out": args.out if args.out is not None else Path.cwd() / "petroharness-out" / Path(args.las).stem,
            "model_url": args.model_url, "model": args.model, "model_card": args.model_card, "settings": args.settings,
            "skills": args.skills, "max_steps": args.max_steps, "direct": not args.investigate}


def main(argv: list | None = None) -> int:
    """petroharness ...: the answer on stdout, what was run on stderr. Exit status 0 (answered), 1 (the run
    failed; the trace says why), 2 (the inputs are wrong)."""
    args = parser().parse_args(argv)
    try:
        kw = options(args)
        result = ask(**kw)
    except (ValueError, LookupError, OSError) as exc:
        print(f"petroharness: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:                     # the interpretation failed (Petrophys could not interpret the LAS)
        print(f"petroharness: {exc}", file=sys.stderr)
        return 1
    a = result.trace["ask"]
    print(f"petroharness: {Path(a['las']).name}, {result.interval['name']}: {_interval_text(result.interval)}",
          file=sys.stderr)
    print(f"  lithology: {_lithology_text(a['lithology'])}; {len(a['zones'])} zones", file=sys.stderr)
    print(f"  model: {a['model']}; status: {result.status}; {len(result.trace.get('steps') or [])} steps; skill library: "
          f"{_skills_text(a['skills'])}; settings: {a['settings']}", file=sys.stderr)
    if result.files:
        print(f"  wrote {result.files['answer']} and {result.files['trace'].name}", file=sys.stderr)
    if not result.ok:
        print(f"  error: {result.trace.get('error', result.status)}", file=sys.stderr)
        return 1
    print(result.answer)
    return 0
