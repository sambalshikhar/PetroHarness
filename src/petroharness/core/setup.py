"""The setup of a run: one flat, frozen record of what the run is made of. Two runs with the same setup hash were
answered by the same harness code, prompt texts, Petrophys build, function list, skill library, model settings and
data settings; where the hashes differ, the records say in which part.

    setup = of(cfg, writer="open", fmt="profile", max_steps=8, mode="interactive")
    setup.hash()            # 12 hex characters
    setup.to_dict()         # the record, as it goes in a session log and a trace
    differences(a, b)       # the parts in which two records differ

    petroharness setup [--model-card CARD | --model NAME] [--settings FILE] [--skills DIR] [--json]
    petroharness setup --las WELL.las [--formation NAME --tops TOPS.csv | --top T --base B] [...] [--json]

With --las (and the interval, as for a question) the data settings are built from the well as a question builds them,
and the hash is the one a conversation about that interval logs. Without --las the data part covers the settings file
alone (--settings, else PETROHARNESS_DATA, else none).

Nothing here is read by a prompt. The endpoint, the API key and the timeouts are not part of a setup: they say where a
model is reached, not what answers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# model settings that say where and how patiently the model is reached, not what it is asked
_NOT_THE_MODEL = ("base_url", "api_key_env", "timeout_s", "max_retries", "label")
# data settings that are places on this machine, not choices
_PLACES = ("las_dir", "tops_csv", "cache_dir", "engines_dir", "lithology_nomenclature")


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]


def harness_commit() -> str:
    """The harness's commit, for a source checkout ("" for an installed package: git answers for any folder inside a
    repository, so only a tracked source file counts)."""
    here = Path(__file__).resolve()
    try:
        git = lambda *a: subprocess.run(["git", "-C", str(here.parent), *a], capture_output=True, text=True, timeout=10)
        if git("ls-files", "--error-unmatch", here.name).returncode != 0:
            return ""
        dirty = git("status", "--porcelain", "--", str(ROOT / "src")).stdout.strip()
        return git("rev-parse", "--short", "HEAD").stdout.strip() + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return ""


def stable_repr(v) -> str:
    """A default value written the same way in every process: sets and dict keys sorted (their order follows the
    process's hash seed), object addresses (" at 0x...") dropped."""
    import re
    if isinstance(v, (set, frozenset)):
        return f"{type(v).__name__}({sorted(stable_repr(x) for x in v)})"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{stable_repr(k)}: {stable_repr(x)}" for k, x in sorted(v.items(), key=lambda kv: stable_repr(kv[0]))) + "}"
    if isinstance(v, (list, tuple)):
        inner = ", ".join(stable_repr(x) for x in v)
        return f"[{inner}]" if isinstance(v, list) else f"({inner})"
    return re.sub(r" at 0x[0-9a-fA-F]+", "", repr(v))


def functions_hash() -> str:
    """The Petrophys functions the tools offer, as one hash: each function's name, verb and parameters. The list is
    part of the investigation's brief, so a Petrophys release that adds a function changes it. The same in every
    process (stable_repr)."""
    from petroharness.agent import library_api as A
    return _sha([[fn.qualified, fn.verb, [[p, str(a), stable_repr(d)] for p, (a, d, _) in fn.params.items()]]
                 for fn in A.registry()])


@dataclass(frozen=True)
class Setup:
    harness: str            # the package's version
    commit: str             # the harness's commit ("" for an installed package)
    petrophys: str          # the Petrophys build (version and its own commit or installed-files hash)
    components: dict        # prompt component -> version (the texts every call is built from)
    functions: str          # hash of the Petrophys functions the tools offer
    skills: dict            # the skill library read: its name and version
    model: str              # the model's name as served
    card: str               # hash of the model's request settings (temperature, token caps, template settings, ...)
    data: str               # hash of the data settings in force (interpretation, zones, bases, conventions)
    policy: str             # hash of the interpretation policy file
    writer: str             # the writer's repair rounds ("open": two; "": one)
    fmt: str                # the reader format
    max_steps: int          # the investigation's step cap
    mode: str               # "interactive" (a LAS file and a question) or "tasks" (prepared questions)
    depth: bool             # the model first says whether a question is direct (a short route) or an investigation

    def to_dict(self) -> dict:
        return asdict(self)

    def hash(self) -> str:
        return _sha(self.to_dict())


def of(cfg, *, writer: str = "open", fmt: str = "profile", max_steps: int | None = None, mode: str = "interactive",
       depth: bool = True) -> Setup:
    """The setup a configuration answers under (cfg: the HarnessConfig of the run, with its model card applied)."""
    from petroharness import __version__
    from petroharness.agent import components as C
    from petroharness.agent import direction
    from petroharness.agent.loop import MAX_STEPS
    from petroharness.well.prepare import library_identity
    model = cfg.model.model_dump()
    data = {k: v for k, v in cfg.data.model_dump().items() if k not in _PLACES}
    policy = Path(cfg.resources.policy_file)
    return Setup(harness=__version__, commit=harness_commit(), petrophys=library_identity(),
                 components=dict(C.versions()), functions=functions_hash(),
                 skills=direction.stamp(direction.plugged(cfg)), model=str(model.get("model")),
                 card=_sha({k: v for k, v in model.items() if k not in _NOT_THE_MODEL + ("model",)}),
                 data=_sha(data), policy=hashlib.sha256(policy.read_bytes()).hexdigest()[:12] if policy.is_file() else "",
                 writer=writer, fmt=fmt, max_steps=int(max_steps or MAX_STEPS), mode=mode, depth=bool(depth))


def config_for(model: str | None = None, model_card: str | None = None, settings=None, skills: str | None = None):
    """The configuration a question would run under, with no well in hand: the model card (the default one, a card,
    or the generic card for a served model's name), a data settings file (`settings`, else PETROHARNESS_DATA, else
    none) and the skill library."""
    import yaml

    from petroharness.ask import library_given
    from petroharness.config import DATA_FILE_ENV, RESOURCES, HarnessConfig, given_settings
    from petroharness.models import MODELS, register
    cfg_file, _, *named = MODELS[register(["http://setup/v1"], model_card, model)]
    settings = settings or os.environ.get(DATA_FILE_ENV) or None
    if settings is not None and not Path(settings).is_file():
        raise FileNotFoundError(f"WHAT: no data settings file at {settings}. FIX: give an existing YAML file "
                                f"(configs/data.example.yaml shows the keys), or unset {DATA_FILE_ENV}.")
    given = (yaml.safe_load(Path(settings).read_text(encoding="utf-8")) or {}) if settings else {}
    given.setdefault("data", {}).setdefault("las_dir", ".")
    library = library_given(skills)
    if library:
        given["skills"] = library
    with given_settings(given):
        cfg = HarnessConfig.load(RESOURCES / cfg_file)
        if named:
            cfg.model.model = named[0]
        return cfg.for_tasks(), given


def differences(a: dict, b: dict) -> list:
    """The parts in which two setup records differ (a component by its id), [] when they are the same setup."""
    out = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) == b.get(k):
            continue
        if isinstance(a.get(k), dict) and isinstance(b.get(k), dict):
            out += [f"{k}.{j}" for j in sorted(set(a[k]) | set(b[k])) if a[k].get(j) != b[k].get(j)]
        else:
            out.append(k)
    return out


def text(s: Setup) -> str:
    """The record as it is printed."""
    d = s.to_dict()
    lines = [f"setup {s.hash()}"]
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"  {k}:")
            lines += [f"    {j}: {w}" for j, w in v.items()]
        else:
            lines.append(f"  {k}: {v if v != '' else '(none)'}")
    return "\n".join(lines)


# the options that describe a well's interval: they need --las
_INTERVAL = ("formation", "tops", "top", "base", "depth_unit", "lithology_curve", "formation_lithology", "field_notes",
             "profile")


def for_well(args) -> Setup:
    """The setup a question about the interval of `args.las` answers under: the data settings built from the LAS as
    ask() and a conversation build them (petroharness.ask.prepare), the configuration as each question's
    (agent.graph.task_config)."""
    import tempfile

    from petroharness import ask as A
    from petroharness.agent.graph import task_config
    from petroharness.config import given_settings
    from petroharness.models import register
    las = Path(args.las).expanduser().resolve()
    if not las.is_file():
        raise FileNotFoundError(f"WHAT: no LAS file at {las}. FIX: give the path of the well's LAS file.")
    key = register(["http://setup/v1"], args.model_card, args.model)
    notes = interpretation = None
    if args.field_notes:
        from petroharness.well.notes import load
        notes = load(args.field_notes)
        interpretation = dict(notes["settings"])
    with tempfile.TemporaryDirectory(prefix="petroharness-setup-") as tmp:
        p = A.prepare(las, key, formation=args.formation, tops=args.tops, top=args.top, base=args.base,
                      depth_unit=args.depth_unit, lithology_curve=args.lithology_curve,
                      formation_lithology=args.formation_lithology, profile=args.profile, settings=args.settings,
                      skills=args.skills, interpretation=interpretation, field_notes=notes, cache=Path(tmp))
        task, _ = A.task_for(p, "(the setup)")
        with given_settings(p.given):
            return of(task_config(task, key, 1), max_steps=args.max_steps, mode="interactive",
                      depth=not args.investigate)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="petroharness setup", description=(
        "Print the setup questions are answered under: the harness, its prompt components, the Petrophys build and "
        "function list, the skill library, the model's request settings and the data settings, with one hash over "
        "them. Two runs with the same hash were made of the same parts. With --las (and the interval, as for a "
        "question) the data settings are built from that well as a question builds them, so the hash is the one a "
        "conversation about it logs; without --las the data part covers the settings file alone."))
    from petroharness.ask import interval_options, run_options
    ap.add_argument("--las", type=Path, help="a well's LAS file: print the setup of a question about it")
    interval_options(ap)
    run_options(ap, endpoint=False)
    ap.add_argument("--json", action="store_true", help="the record as JSON")
    args = ap.parse_args(argv)
    from petroharness.config import given_settings
    try:
        if args.las is not None:
            s = for_well(args)
        else:
            stray = [o for o in _INTERVAL if getattr(args, o) is not None]
            if stray:
                raise ValueError(f"WHAT: --{stray[0].replace('_', '-')} describes a well's interval, and no well was "
                                 "given. FIX: add --las WELL.las, or leave the interval options out.")
            cfg, given = config_for(args.model, args.model_card, args.settings, args.skills)
            with given_settings(given):
                s = of(cfg, max_steps=args.max_steps, mode="interactive", depth=not args.investigate)
    except (ValueError, LookupError, OSError) as exc:
        print(f"petroharness setup: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"hash": s.hash(), **s.to_dict()}, indent=1) if args.json else text(s))
    return 0
