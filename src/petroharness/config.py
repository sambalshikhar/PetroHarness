"""The harness configuration: data paths (configs/data.local.yaml or PETROHARNESS_DATA), the model endpoint, the
resources (policy, registries). One object; a YAML overlay changes it, a typo raises."""

from __future__ import annotations

import copy
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")      # a misspelt key is an error, not a silent default

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOURCES = Path(__file__).resolve().parent / "resources"     # the policy, profiles, registries, skills, model card
DATA_FILE_ENV = "PETROHARNESS_DATA"
LOCAL_DATA_FILE = REPO_ROOT / "configs" / "data.local.yaml"
SKILLS_ENV = "PETROHARNESS_SKILLS"
DEFAULT_SKILLS = "skills/researched"     # the packaged researched library (relative to RESOURCES)


def data_file() -> Path:
    """The user's data settings file: PETROHARNESS_DATA, else configs/data.local.yaml."""
    return Path(os.environ.get(DATA_FILE_ENV) or LOCAL_DATA_FILE)


@lru_cache(maxsize=8)
def _read_settings(path: str, mtime: float) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    unknown = sorted(set(data) - {"data", "eval"})
    if unknown:
        raise ValueError(f"WHAT: {path} has sections {unknown}. FIX: give 'data' (and optionally 'eval') only.")
    return data


# Data settings given in code (petroharness ask builds them from the LAS file it is asked about): while set, they stand
# in for the settings file.
_GIVEN_SETTINGS = ContextVar("petroharness_given_settings", default=None)


@contextmanager
def given_settings(settings: dict):
    """Use these settings ({'data': {...}, 'eval': {...}}, and optionally 'skills': a skill library or "none") instead
    of the settings file (and PETROHARNESS_SKILLS) inside the block."""
    token = _GIVEN_SETTINGS.set(copy.deepcopy(settings))
    try:
        yield
    finally:
        _GIVEN_SETTINGS.reset(token)


def user_settings(section: str) -> dict:
    """One section ('data' or 'eval') of the user's data settings."""
    given = _GIVEN_SETTINGS.get()
    if given is not None:
        return copy.deepcopy(given.get(section) or {})
    path = data_file()
    if not path.exists():
        raise ValueError(f"WHAT: no data settings at {path}. WHY: the harness ships no dataset paths; the LAS "
                         "directory, the formation tops and the lithology code workbook are the user's. FIX: copy "
                         f"configs/data.example.yaml to configs/data.local.yaml and fill it in, or set {DATA_FILE_ENV}.")
    return copy.deepcopy(_read_settings(str(path), path.stat().st_mtime).get(section) or {})


class LithologyColumns(_Strict):
    """Columns of the lithology nomenclature workbook: the numeric lithology code and its label."""

    code: str = "code"
    label: str = "lithology"


class DataPaths(_Strict):
    """Harness inputs, the user's (configs/data.local.yaml). Reference outputs are deliberately absent (EvalPaths)."""

    las_dir: Path
    # Tops table: a formation's interval when the task gives only its name (formation info with top and base needs none).
    tops_csv: Optional[Path] = None
    # The petrophys batch interpreter that is this data's workflow of record, as "module:function" or
    # "/path/adapter.py:function" (the contract of
    # petrophys process_las_directory_with_workflow: (input_dir, output_dir, well_names=...) -> one BatchLasResult per
    # well). Null: data.interpret, else the policy's engine, else petrophys.interpret with the library's settings.
    interpreter: Optional[str] = None
    # Options for petrophys.interpret, which then interprets each LAS: e.g. {context_profile: NAME} (a name
    # petrophys.reporting.context_profiles.list_context_profiles() gives) for a well of a petrophys context package
    # (interpreted as that package's context does), or {} for the library's defaults. Null:
    # data.interpreter, else the policy's engine, else petrophys.interpret with the library's settings and the policy's
    # cutoffs.
    interpret: Optional[dict[str, Any]] = None
    # The unit depths, thicknesses and zone limits are shown in: m, ft, or "las" for each LAS's own depth unit. Null: the
    # policy's depth_unit (metres).
    depth_unit: Optional[str] = None
    # Field nomenclature workbook: overrides the library's built-in lithology code table (policy lithology.codes).
    lithology_nomenclature: Optional[Path] = None
    lithology_columns: LithologyColumns = Field(default_factory=LithologyColumns)
    # The lithology log's LAS mnemonic, or several (the first a well has with data is used). Null: the LAS's own
    # curve whose mnemonic or description names a lithology or facies log and holds integer codes; a well without
    # one is zoned by Petrophys's solved lithology, else by shale-volume bands (formation.find_lithology_curve).
    lithology_curve: Optional[Union[str, list[str]]] = None
    # How a formation is split into zones: "lithology_runs" (runs of the lithology log, thin runs dropped) or
    # "formation" (the whole formation interval is one zone, labelled by the log's majority lithology: data whose
    # context lays out one group per formation).
    zone_layout: Literal["lithology_runs", "formation"] = "lithology_runs"
    # The zone rule, where a user changes it (petroharness.well.settings: the web UI's interpretation settings). Null:
    # the policy's (zones.min_thickness_m, zones.fallback_vcl_bands). A lithology run thinner than the minimum (metres)
    # is not a zone; the bands are the VCL edges that zone a well with neither a lithology log nor a solved lithology.
    zone_min_thickness_m: Optional[float] = None
    zone_vcl_bands: Optional[list[float]] = None
    # The statistics' bases: "all" (each zone, the zones pooled, and the whole interval where it differs, with what the
    # samples outside the zones hold) or "zones" (each zone and the zones pooled only: data whose references report on
    # the lithology zones, a benchmark's convention, set in its data file).
    basis: Literal["all", "zones"] = "all"
    # The class-table set the Petrophys analyzers classify with (a set a Petrophys context package ships, for data that
    # package's context interprets). Null: the policy's (analyzers.class_tables: the library's current tables).
    analyzer_class_tables: Optional[str] = None
    # Reporting conventions of this data (each a sentence), shown to the investigation and the writer as the data's
    # conventions: how its own reports name or group what the record holds (a benchmark's convention, set in its data
    # file). Empty: none, and no prompt changes.
    conventions: list[str] = Field(default_factory=list)
    # What a tool's zones may name (docs/ARCHITECTURE.md): "well", anywhere in the well (a unit of the
    # tops file, a depth range, besides the zones of the interval asked about), or "focus", the interval's zones only
    # (a benchmark's convention, set in its data file: its questions are about the interval).
    reach: Literal["focus", "well"] = "well"
    # The tops file's units of this well (set by a question from its tops file, petroharness.ask): each {name, top,
    # base, closed, unit, line}, in the file's unit (None: the LAS's own). Read under reach "well".
    units: list[dict] = Field(default_factory=list)
    # The tops file's rows left out of the units (a row whose base is not below its top), each {name, line, top, base,
    # unit, why}: a question naming one is asked back, the row to fix (agent.read.ask_back), not told the unit is absent.
    units_left_out: list[dict] = Field(default_factory=list)
    # The user's zones (set by a question from its zones file, petroharness.ask: well.user_zones.read_zones), each
    # {name, top, base, closed, unit, line} in the file's unit: they frame the question in place of the lithology
    # zones, which stay available (ids L1..); empty: the lithology zones frame it.
    zones: list[dict] = Field(default_factory=list)
    zones_source: Optional[str] = None      # the zones file's name, as the map names it
    cache_dir: Path = REPO_ROOT / ".cache" / "wells"
    # Pinned interpretation engines (a policy's workflow of record), one directory per engine name.
    engines_dir: Optional[Path] = None
    # Tops table: column names, and which top names count (regex on the upper-cased name; null keeps every top).
    tops_columns: dict[str, str] = {"well": "uwi", "name": "form", "top": "top"}
    top_name_pattern: Optional[str] = None
    # Depth unit of the tops table, which records none (m or ft). Null: the LAS file's own depth unit (tops are
    # normally picked on the logs' depth index). The view converts both to the policy's unit (metres).
    tops_depth_unit: Optional[str] = None


class EvalPaths(_Strict):
    """Reference material, the user's (configs/data.local.yaml, section eval). Only tests, diagnostics and the
    evaluation scripts may read these."""

    questions: Optional[Path] = None
    reference_context_dir: Optional[Path] = None
    gt_dir: Optional[Path] = None


class ModelConfig(_Strict):
    base_url: str = "http://localhost:8000/v1"     # an OpenAI-compatible server (vLLM's default port)
    model: str = ""                                # the served model's name: the card's, or --model ("" names none)
    label: Optional[str] = None                    # the model's name as people read it (the UI); default: model
    api_key_env: str = "PETROHARNESS_API_KEY"  # local vLLM accepts any key
    temperature: float = 0.0
    max_tokens_spec: int = 3000
    max_tokens_writer: int = 6000
    timeout_s: float = 600.0
    max_retries: int = 3
    enable_thinking: bool = False
    # Sent as chat_template_kwargs; None -> {"enable_thinking": enable_thinking}. Other model
    # families use their own template variables (e.g. {"reasoning_effort": "high"}).
    chat_template_kwargs: Optional[dict[str, Any]] = None
    # The one retry after an empty reply (e.g. a reasoning model that spent every token thinking) sends these
    # chat_template_kwargs instead, e.g. thinking off or the lowest effort: a plain answer beats no answer.
    # None: the retry repeats the first call's settings.
    retry_template_kwargs: Optional[dict[str, Any]] = None
    # A call that needs little reasoning (the choice of an answer's figures among listed plots) sends these
    # chat_template_kwargs instead, e.g. the lowest effort or thinking off. None: every call thinks as the first does.
    # Not the look steps of a direct question: with thinking reduced there, the answers lost accuracy (docs/GRAPH.md).
    light_template_kwargs: Optional[dict[str, Any]] = None
    # Where the server leaves the reasoning in a light call's reply, the marker that ends it: the reply is the text
    # after the last marker. None: the reply is taken as it comes.
    reasoning_end: Optional[str] = None
    top_p: Optional[float] = None     # None -> server default
    # A reasoning model thinks before it answers. Its reply cut off by the token cap is a failed reply, not a short
    # one (the cut may sit inside the reasoning, which some parsers then return as the answer).
    reasoning: bool = False
    # Request shape (defaults: an OpenAI-compatible vLLM/SGLang server). Hosted APIs may reject unknown fields,
    # a non-default temperature, or max_tokens on reasoning models.
    send_template_kwargs: bool = True
    send_temperature: bool = True
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    structured_output: Literal["json_schema", "json_object", "none"] = "json_schema"
    # Replayed assistant turns carry an empty reasoning field (some chat templates require it, some servers reject
    # it). None: only for reasoning models.
    replay_reasoning_field: Optional[bool] = None


class ResourcePaths(_Strict):
    policy_file: Path = RESOURCES / "policy" / "reference_v2.yaml"     # the workflow of record's settings
    rules_dir: Path = RESOURCES / "rules"     # registries: curves, judgements, shapes, checks, catalog, topics


class HarnessConfig(_Strict):
    data: DataPaths = Field(default_factory=lambda: DataPaths(**user_settings("data")))
    eval: Optional[EvalPaths] = Field(default_factory=lambda: EvalPaths(**user_settings("eval")))
    model: ModelConfig = Field(default_factory=ModelConfig)
    resources: ResourcePaths = Field(default_factory=ResourcePaths)
    # The skill library the model reads guides from: a library folder (absolute, or relative to the package's resources;
    # src/petroharness/resources/skills/README.md), or "none" for a run with no guides. PETROHARNESS_SKILLS overrides it.
    skills: str = DEFAULT_SKILLS

    @classmethod
    def load(cls, *paths: Optional[Path]) -> "HarnessConfig":
        """Defaults, overlaid by each YAML file in order (later files win, key by key). The endpoints a run uses are
        PETROHARNESS_MODEL_URL's (or --model-url), set per question (src/petroharness/models.py)."""
        payload: dict = {"data": user_settings("data"), "eval": user_settings("eval")}
        for path in paths:
            if path is not None:
                _merge(payload, yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
        return cls.model_validate(payload)

    def for_tasks(self) -> "HarnessConfig":
        """The configuration a task may see: identical, but without any evaluation (reference) paths."""
        return self.model_copy(update={"eval": None})

    def api_key(self) -> str:
        return os.environ.get(self.model.api_key_env, "EMPTY")


def skills_setting(cfg: Optional[HarnessConfig] = None) -> str:
    """The skill library in force: the one given in code (given_settings' 'skills': petroharness's --skills) when
    set, else PETROHARNESS_SKILLS when set (a run chooses without editing a config), else the configuration's skills,
    else the packaged researched library."""
    given = str((_GIVEN_SETTINGS.get() or {}).get("skills") or "").strip()
    return given or os.environ.get(SKILLS_ENV, "").strip() or (cfg.skills if cfg is not None else DEFAULT_SKILLS)


def _merge(into: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(into.get(k), dict):
            _merge(into[k], v)
        else:
            into[k] = v
    return into
