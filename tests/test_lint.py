"""No benchmark literals (wells, formations, depths) in prompts, rules or policies, and no dataset identifiers
in the code, rules or prompts (AGENTS.md rule 2: the harness must work on any well).

Where a dataset may be named: the dataset adapter, i.e. the configuration defaults (src/petroharness/config.py),
the resources' policy and profiles, and configs/. Tests may mention anything.
"""

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _files(*patterns: str) -> list[Path]:
    return sorted({p for pattern in patterns for p in ROOT.glob(pattern) if p.is_file() and "__pycache__" not in p.parts})


# What the model reads: the components' texts (src/petroharness/agent/components), the topic areas and the packaged
# skill libraries' guides (a guide's sources.yaml is its provenance record and is never shown to the model)
MODEL_TEXTS = ("src/petroharness/agent/components/**/*.md", "src/petroharness/agent/components/**/*.json",
               "src/petroharness/agent/components/**/*.yaml", "src/petroharness/resources/skills/*/*/SKILL.md",
               "src/petroharness/resources/topics.yaml")
RESOURCE_FILES = ("src/petroharness/resources/rules/**/*", "src/petroharness/resources/policy/**/*",
                  "src/petroharness/resources/profiles/**/*", "src/petroharness/resources/models/**/*", "configs/**/*")
GUARDED = _files(*RESOURCE_FILES, "src/petroharness/**/*.py", *MODEL_TEXTS)
# Text the LLM reads, and the configuration: no depth literals in any form.
LLM_FACING = _files(*RESOURCE_FILES, *MODEL_TEXTS)
# Code, rules, prompts, policies, profiles, configs and engine recipes: no dataset identifiers. The dataset's names and
# paths are the user's (configs/data.local.yaml, untracked; PETROHARNESS_DATA), never the harness's.
DATASET_FREE = [p for p in _files(*RESOURCE_FILES, "src/petroharness/**/*.py")
                if p != ROOT / "configs" / "data.local.yaml"]

DATASET_IDENTIFIERS = {
    "dataset name": re.compile(r"geolink", re.I),
    "national well/stratigraphy registry": re.compile(r"\bNPD\b|\bnorw(?:ay|egian)\b|\bnorth sea\b", re.I),
    "NPD well-name regex": re.compile(r"\[/_\]|\[_/\]|\\d\+/\\d\+-"),           # e.g. \d+[/_]\d+-\d+
    "NPD top-rank regex": re.compile(r"\(FM\|GP\|MB\)"),                      # ' (FM|GP|MB)\.' (Fm./Gp./Mb. tops)
    "lithology workbook": re.compile(r"Litho_Nomenclature|Nomenclature_Kingdom|Lithology Attribute", re.I),
}

# (file, line) -> why the identifier may stay. Each entry must still match a line, so none outlives its reason.
ALLOWED = {
    ("src/petroharness/resources/rules/curves.yaml", "north_sea: North Sea shaly-sand"):
        "display name of the library's saturation-model identifier 'north_sea' (a method name, not dataset data)",
}
# Violations in files owned by another work stream, listed so this lint passes until they are fixed. Remove an entry
# with its fix (the stale-entry check below fails once the line is gone).
PENDING: dict = {}

DEPTH_UNIT = r"(?:m|ft|feet|foot|metres?|meters?)(?![A-Za-z])"
DECIMAL_DEPTH = re.compile(r"(?<![\d.])\d{3,5}\.\d+\s*(m\b|ft\b|–|-\s*\d)")
INTEGER_OR_FEET_DEPTH = re.compile(rf"(?<![\w.,])(?:\d{{3,5}}|\d{{1,2}},\d{{3}})(?:\.\d+)?\s*{DEPTH_UNIT}", re.I)


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _stem(name) -> str:
    """A unit's name without its rank (Fm., Gp., Mb., Formation, Group, Member), in capitals."""
    return re.split(r"\s+(?:FM|GP|MB)\.|\s+(?:FORMATION|GROUP|MEMBER)\b", str(name).upper())[0].strip()


def _sample_names() -> tuple[set[str], set[str]]:
    """The wells the repository itself runs on, with no data settings (CI): Petrophys's sample wells, as the web UI
    offers them (the mini set's among them), and the units of their tops."""
    from petroharness.ui.adapter import samples
    from petroharness.well.tops import read_tops
    wells, formations = set(), set()
    for s in samples():
        names = [n for n in (s["well"], Path(s["las"]).stem) if len(n) >= 4]
        wells |= {n.upper() for n in names}
        if s["tops"]:
            formations |= {_stem(n) for n in read_tops(s["tops"]["path"], names, None, s["unit"]).names()}
    return wells, {f for f in formations if len(f) >= 4}


def _benchmark_names() -> tuple[set[str], set[str]]:
    """The sample wells' names, and the benchmark's where data settings name it (its LAS folder and tops table)."""
    wells, formations = _sample_names()
    try:
        from _reference import CFG
    except Exception as e:  # noqa: BLE001  (no data settings: the sample wells alone)
        if "WHAT: no data settings" not in str(e):
            raise
        return wells, formations
    found = {p.stem.upper() for p in CFG.data.las_dir.glob("*.las")}
    wells |= found | {w.replace("_", "/") for w in found}
    tops = pd.read_csv(CFG.data.tops_csv)
    formations |= {f for f in (_stem(n) for n in tops["form"].dropna()) if len(f) >= 4}
    return wells, formations


def test_guarded_files_exist():
    assert len(GUARDED) >= 4 and len(DATASET_FREE) >= 4


def test_no_well_or_formation_names():
    wells, formations = _benchmark_names()
    hits = []
    for path in GUARDED:
        text = path.read_text().upper()
        hits += [f"{path.name}: well {w}" for w in wells if w in text]
        hits += [f"{path.name}: formation {f}" for f in formations
                 if re.search(rf"(?<![A-Z]){re.escape(f)}(?![A-Z])", text)]
    assert not hits, (
        f"{hits[:10]} — WHY: benchmark names in prompts/rules/policies leak the test set. "
        "FIX: state the rule in general petrophysical terms.")



def test_no_depth_literals():
    hits = [f"{p.name}: {m.group(0)}" for p in GUARDED for m in DECIMAL_DEPTH.finditer(p.read_text())]
    hits += [f"{p.name}: {m.group(0)}" for p in LLM_FACING for m in INTEGER_OR_FEET_DEPTH.finditer(p.read_text())]
    assert not hits, f"{hits[:10]} — FIX: remove depth values; use synthetic examples without real depths."


def _dataset_hits() -> dict[tuple[str, str], str]:
    hits = {}
    for path in DATASET_FREE:
        for line in path.read_text(errors="ignore").splitlines():
            for kind, rx in DATASET_IDENTIFIERS.items():
                if rx.search(line):
                    hits[(_rel(path), line.strip())] = kind
    return hits


def test_no_dataset_identifiers_in_code_rules_or_prompts():
    hits = _dataset_hits()
    bad = [f"{f}: {kind}: {line[:120]}" for (f, line), kind in hits.items() if (f, line) not in ALLOWED | PENDING]
    assert not bad, (f"{bad[:10]} — WHY: the harness must work on any well; a dataset's names, file layouts and "
                     "conventions belong to the user's data settings. FIX: move the value to configs/data.local.yaml (a DataPaths "
                     "or EvalPaths key in src/petroharness/config.py) and read it from there.")
    stale = [k for k in {**ALLOWED, **PENDING} if k not in hits]
    assert not stale, f"{stale} — WHY: the line is gone or does not name the dataset. FIX: remove the entry."


def test_lint_patterns_catch_what_they_are_for():
    """The patterns themselves: depth literals in integer, decimal and feet form, and dataset identifiers."""
    for text in ("top at 2500 m", "8200 ft", "8,200 ft", "2500m MD", "1234.5 metres", "3000 feet"):
        assert INTEGER_OR_FEET_DEPTH.search(text), text
    for text in ("clipped <= 10000 mD", "petrophys c41417f", "per 10 m of depth", "0.5 m", "max_chars: 1200",
                 "2500 ms"):
        assert not INTEGER_OR_FEET_DEPTH.search(text), text
    assert DECIMAL_DEPTH.search("2456.5 ft") and DECIMAL_DEPTH.search("2456.5–2470.0")
    found = lambda text: [k for k, rx in DATASET_IDENTIFIERS.items() if rx.search(text)]
    assert found('codes = prep.curve("LITHOLOGY_GEOLINK")') == ["dataset name"]
    assert found(r"ignore: ['\d+[/_]\d+-\d+(?:\s?[A-Z])?']") == ["NPD well-name regex"]
    assert found(r'_UNIT_RE = re.compile(r" (FM|GP|MB)\.")') == ["NPD top-rank regex"]
    assert found('sheet["Lithology Attribute"]') == ["lithology workbook"]
    assert found("Norwegian North Sea wells") == ["national well/stratigraphy registry"]
    assert not found("zones from shale-volume bands; FM tops; geology")
