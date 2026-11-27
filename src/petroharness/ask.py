"""One question about one LAS file, any well: the console script's default command (docs/USAGE.md).

    petroharness --las WELL.las --question "..." [--formation NAME --tops TOPS.csv | [--formation NAME]
                 --top D --base D] [--depth-unit m|ft] [--lithology-curve MNEMONIC] [--formation-lithology TEXT]
                 [--profile NAME] [--out DIR] [--model NAME | --model-card CARD] [--model-url URL]

The interval asked about: a formation of a tops file (well/tops.py reads it), explicit depths, or by default the whole
well. No data settings file is needed: the data settings are built from the LAS (a file given with --settings or
PETROHARNESS_DATA is the base they start from). Petrophys interprets the LAS with its default workflow (net-pay cutoffs
as the harness policy states them), or with a context profile (--profile). A LAS without a lithology log is zoned by
the lithology Petrophys's mineral solver wrote, and by shale-volume bands when it wrote none. Writes answer.md and
trace.json to the output folder and prints the answer.

The model: any chat model behind an OpenAI-compatible endpoint (--model NAME, or a model card with --model-card;
default: K2-Horizon-7B's card; petroharness.models, docs/MODELS.md), at --model-url or PETROHARNESS_MODEL_URL.

The same in Python: petroharness.ask.ask(las, question, formation=..., tops=...) -> AskResult.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from petroharness.interval import (  # noqa: F401  (callers read the interval's names from ask too)
    Inputs,
    Prepared,
    WHOLE_WELL,
    _factor,
    _interpretation,
    _interval,
    _las_header,
    _log_range,
    _settings,
    _units,
    check,
    library_given,
    prepare,
    task_for,
)


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


def _model_key(model_url: str | None, llm_factory, model: str | None = None, model_card: str | None = None) -> str:
    """The model registry key (petroharness.models): the model card (--model-card; else the generic card when --model
    names the served model; else K2-Horizon-7B's) and the endpoints (--model-url, else PETROHARNESS_MODEL_URL;
    comma-separated)."""
    from petroharness.models import DEFAULT_KEY, URL_ENVS, env_urls, register

    urls = [u.strip() for u in model_url.split(",") if u.strip()] if model_url else env_urls()
    if not urls:
        if llm_factory is not None and not (model or model_card):
            return DEFAULT_KEY
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
        on_view: Callable | None = None, direct: bool = True, interpretation: dict | None = None,
        field_notes=None, zones=None, zones_sheet: str | None = None) -> AskResult:
    """One question about one LAS file -> AskResult (answer, status, trace, the interval used). The interval: the
    formation `formation` of the tops file `tops`; or the depths `top`/`base` (`formation` names it); or, with
    neither, the whole well. `depth_unit` (m or ft): the unit of the depths given and of the answer's depths (default:
    the tops file's, else the LAS's own). `interpretation`: settings Petrophys interprets the well with, and the zone
    rule ({setting: value}; petroharness.well.settings lists them; unset ones keep their defaults). `field_notes`: a
    field notes file (petroharness.well.notes): its settings are in force under `interpretation`'s, and its notes reach
    the model with the question. `skills`: the skill library the model reads guides from (a library folder, or
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
    inputs = Inputs(formation=formation, tops=tops, top=top, base=base, depth_unit=depth_unit,
                    lithology_curve=lithology_curve, formation_lithology=formation_lithology, profile=profile,
                    settings=settings, skills=skills, interpretation=interpretation, field_notes=field_notes,
                    zones=zones, zones_sheet=zones_sheet).loaded()
    out_dir = Path(out).expanduser().resolve() if out is not None else None
    with tempfile.TemporaryDirectory(prefix="petroharness-ask-") as tmp:
        cache = out_dir / ".cache" if out_dir is not None else Path(tmp)
        p = prepare(las, key, inputs, cache=cache)
        task, sent = task_for(p, question)
        check(p, task, on_view)
        with given_settings(p.given):
            got = graph.answer(task, key, 1, max_steps or graph.MAX_STEPS, "open", "profile",
                               llm_factory=llm_factory, commit=COMMIT, depth=direct, mode="interactive")
    trace = got["trace"]
    trace["answer"] = got["answer"]
    trace["ask"] = ask_record(p, question, sent, trace)
    result = AskResult(answer=got["answer"], status=got["status"], trace=trace, interval=p.used, out_dir=out_dir)
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        result.files = {"answer": out_dir / "answer.md", "trace": out_dir / "trace.json"}
        result.files["answer"].write_text(_answer_md(result, las), encoding="utf-8")
        result.files["trace"].write_text(json.dumps(trace, indent=1, default=str), encoding="utf-8")
    return result


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
            "petrophys": library_identity(),
            **({"zones_source": p.data["zones_source"]} if p.data.get("zones") and p.data.get("zones_source") else {}),
            **({"field_notes": {k: p.notes[k] for k in ("name", "sha256", "settings", "notes")}} if p.notes else {})}


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
    if litho["source"] == "mineral solver":
        return (f"no lithology log: lithology zones from Petrophys's mineral solver ({litho['curve']}, "
                f"{litho['domain']} domain, {litho['method'].replace('_', ' ')})")
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


def _settings_lines(trace: dict) -> list:
    """The header's lines on the field notes (when given) and on a conversation's settings, once they were changed."""
    from petroharness.well.settings import describe, values
    out = []
    fn = (trace.get("ask") or {}).get("field_notes")
    if fn:
        shown = values(fn["settings"])
        out.append(f"- **Field notes:** {fn['name']}" + (f" ({shown})" if shown else "")
                   + (f"; {len(fn['notes'])} note{'s' if len(fn['notes']) != 1 else ''} with the question"
                      if fn["notes"] else ""))
    s = trace.get("settings")
    if not s:
        return out
    if s.get("changed"):
        out.append(f"- **Settings changed for this question:** {describe(s['changed'])}")
    for e in [e for e in s.get("changes") or [] if e["turn"] < s.get("turn", 0)]:
        out.append(f"- **Settings changed before question {e['turn']}:** {describe(e['changes'])}")
    return out


def _answer_md(result: AskResult, las: Path) -> str:
    a = result.trace["ask"]
    head = [f"# {las.stem}: {result.interval['name']}", "",
            f"- **Question:** {a['question']}",
            f"- **Interval:** {_interval_text(result.interval)}",
            *([f"- **Scope:** {', '.join(result.trace['scope']['used'])} (the stretches the question is about)"]
              if (result.trace.get("scope") or {}).get("used") else []),
            *([f"- **Zones:** yours, from {a['zones_source']} ({len(a['zones'])}; the lithology zones are kept as L ids)"]
              if a.get("zones_source") else []),
            f"- **Lithology:** {_lithology_text(a['lithology'])}",
            f"- **Model:** {a['model']}",
            f"- **Skill library:** {_skills_text(a['skills'])}",
            f"- **Status:** {result.status}, {_route_text(result.trace)}", *_settings_lines(result.trace),
            "", "---", ""]
    body = result.answer if result.answer else f"(no answer: {result.trace.get('error', result.status)})"
    return "\n".join(head) + body.rstrip() + "\n"


# --- the command -----------------------------------------------------------------------------------------------------

EXAMPLES = """examples:
  petroharness --las well.las --formation "Upper Sand" --tops tops.csv \\
      --question "What are the porosity and water saturation, and is it hydrocarbon-bearing?"
  petroharness --las well.las --top 5300 --base 5600 --depth-unit ft --question "..."
  petroharness --las well.las --question "..."          (the whole well)

The model: any chat model with --model NAME (as the server lists it), or a model card with --model-card
(docs/MODELS.md), at PETROHARNESS_MODEL_URL=http://HOST:PORT/v1 (comma-separated for several) or --model-url. Without
them: the model chosen last in the web UI's Model dialog, else WellLogLLM-3.7B as a GGUF in Ollama on this computer
(downloaded the first time).

Other commands (each has --help):
  petroharness chat --las well.las ...     keep an interval open and go on asking (docs/SESSIONS.md)
  petroharness audit SESSION               each answer's trail back to the LAS file (docs/EVIDENCE.md)
  petroharness report SESSION              a conversation as one document
  petroharness setup                       what answers a question, with one hash (docs/EVIDENCE.md)
  petroharness --launch-ui                 ask in the browser: starts the web UI and opens it (docs/UI.md)
  petroharness ui                          the web UI alone, with live progress and saved runs (docs/UI.md)
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
    ap.add_argument("--zones", type=Path, help="your zones (CSV, TSV or Excel): zone,top,bottom[,depth_unit][,well]; "
                                               "they frame the answer in place of the lithology zones")
    ap.add_argument("--zones-sheet", help="the Excel sheet of the zones (default: the first)")
    where.add_argument("--top", type=float, help="the interval's top depth (with --tops: the top of the row meant, "
                       "for a formation the tops file lists twice)")
    where.add_argument("--base", type=float, help="the interval's base depth")
    where.add_argument("--depth-unit", help="m or ft: the unit of the depths given and of the answer's depths "
                                            "(default: the tops file's, else the LAS's own)")
    lith = ap.add_argument_group("lithology")
    lith.add_argument("--lithology-curve", help="the lithology log's mnemonic (default: detected; when the LAS has "
                                                "none, the zones are runs of the lithology Petrophys's mineral "
                                                "solver wrote, else shale-volume bands)")
    lith.add_argument("--formation-lithology", help="the formation's lithology as you know it, e.g. 'sandstone'")
    ap.add_argument("--field-notes", type=Path, help="a field notes file: the team's standing settings and notes for "
                                                     "this field (YAML: name, settings, notes; docs/SESSIONS.md)")
    ap.add_argument("--profile", help="a Petrophys context profile for wells of a known package (default: "
                                      "Petrophys's default interpretation)")


def run_options(ap: argparse.ArgumentParser, endpoint: bool = True) -> None:
    """The model, settings, skills and step-cap options (ask and chat; `petroharness setup` without the endpoint,
    which says where the model is reached, not what answers)."""
    llm = ap.add_argument_group("the model (default: K2-Horizon-7B)")
    llm.add_argument("--model", help="the served model's name, for any chat model on an OpenAI-compatible endpoint "
                                     "(as the server lists it at /v1/models)")
    llm.add_argument("--model-card", help="a model card: a YAML file (docs/MODELS.md), or a packaged card's name")
    if endpoint:
        llm.add_argument("--model-url", help="the model endpoint(s), comma-separated (default: "
                                             "PETROHARNESS_MODEL_URL)")
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
    question = args.question if args.question is not None else Path(args.question_file).read_text(encoding="utf-8")
    return {"las": args.las, "question": question, "formation": args.formation, "tops": args.tops, "top": args.top,
            "base": args.base, "depth_unit": args.depth_unit, "lithology_curve": args.lithology_curve,
            "formation_lithology": args.formation_lithology, "profile": args.profile,
            "out": args.out if args.out is not None else Path.cwd() / "petroharness-out" / Path(args.las).stem,
            "model_url": args.model_url, "model": args.model, "model_card": args.model_card, "settings": args.settings,
            "skills": args.skills, "max_steps": args.max_steps, "direct": not args.investigate,
            "field_notes": args.field_notes, "zones": getattr(args, "zones", None),
            "zones_sheet": getattr(args, "zones_sheet", None)}


def _progress():
    """What getting the model ready says on stderr: each step once, a download every 5%."""
    last = {"text": None, "pct": -1}

    def say(p: dict) -> None:
        text = p.get("text") or ""
        if p.get("total"):
            pct = int(100 * (p.get("done") or 0) / p["total"])
            if pct // 5 != last["pct"] // 5:
                print(f"  {text}: {pct}% of {p['total'] / 1e9:.1f} GB", file=sys.stderr, flush=True)
                last["pct"] = pct
        elif text != last["text"]:
            print(f"  {text}", file=sys.stderr, flush=True)
        last["text"] = text
    return say


def default_model(kw: dict) -> None:
    """The command given no model (no --model, --model-card, --model-url, PETROHARNESS_MODEL_URL): the model chosen
    last in the web UI's Model dialog, else WellLogLLM-3.7B as a GGUF in Ollama, made ready first (downloaded the first
    time; petroharness.connect). Sets kw's model_card and model_url."""
    from petroharness import connect as C
    from petroharness.models import env_urls
    if kw.get("model") or kw.get("model_card") or kw.get("model_url") or env_urls():
        return
    kept = C.saved()
    request = (kept or {}).get("request") if (kept or {}).get("route") == "ollama" else None
    if kept is None:
        request = {"route": "ollama", "model": "welllogllm"}
    if request:
        print("petroharness: getting the model ready in Ollama", file=sys.stderr, flush=True)
        try:
            choice = C.connect(request, report=_progress())
        except ValueError as exc:
            raise ValueError(f"{exc} Or give a model: --model-url URL with --model NAME or --model-card CARD, or "
                             "PETROHARNESS_MODEL_URL (docs/MODELS.md).") from None
        if kept is None:
            C.save_choice(choice | {"request": request})
        kept = choice
    kw["model_card"], kw["model_url"] = kept["model_card"], ",".join(kept["urls"])
    where = f", {kept['where']}" if kept.get("where") else ""
    print(f"petroharness: model {kept['label']} at {kw['model_url']}{where}", file=sys.stderr, flush=True)
    for w in kept.get("warnings") or []:                    # what is not ideal for the model on this computer
        print(f"petroharness: note: {w}", file=sys.stderr, flush=True)


def main(argv: list | None = None) -> int:
    """petroharness ...: the answer on stdout, what was run on stderr. Exit status 0 (answered), 1 (the run
    failed; the trace says why), 2 (the inputs are wrong)."""
    args = parser().parse_args(argv)
    try:
        kw = options(args)
        if Path(kw["las"]).is_file():               # a wrong LAS is said before any model is made ready
            default_model(kw)
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
