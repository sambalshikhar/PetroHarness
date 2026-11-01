# Development

Configuration, benchmark mode, testing and the code layout. To install and to ask about a well, see the
[README](../README.md); for models, see [MODELS.md](MODELS.md).

## Configuration

### The data config

The data config says where the data is. Copy `configs/data.example.yaml` to `configs/data.local.yaml` (untracked), or
point `PETROHARNESS_DATA` at a file like it. A misspelt key is an error. `src/petroharness/config.py` documents every
key; the main ones:

| key | meaning |
|---|---|
| `data.las_dir` | one LAS file per well, named `<well>.las` |
| `data.tops_csv` | the tops table, for intervals given by a formation name; `tops_columns`, `top_name_pattern` and `tops_depth_unit` describe it |
| `data.lithology_curve` | the lithology log's mnemonic (or a list; the first with data is used). Left out: the LAS curve whose mnemonic or description names a lithology or facies log and holds integer codes |
| `data.lithology_nomenclature` | a workbook mapping lithology codes to labels (overrides the library's table); `lithology_columns` names its columns |
| `data.zone_layout` | `lithology_runs` (default: runs of the lithology log, thin runs dropped) or `formation` (the whole interval is one zone) |
| `data.depth_unit` | the unit depths and thicknesses are shown in: `m`, `ft` or `las` (each file's own); default metres |
| `data.interpret` | options for `petrophys.interpret`, which then interprets each LAS (below) |
| `data.interpreter` | a Petrophys batch interpreter, `module:function` or `/path/adapter.py:function`, that interprets the data instead |
| `data.engines_dir` | the folder of pinned interpretation engines, when the policy names one |
| `data.cache_dir` | where interpreted wells are cached (default `.cache/wells`), keyed by the LAS content and the interpretation settings |
| `data.basis` | `all` (default: each zone, the zones pooled and the whole interval) or `zones` (the tools' statistics on the zones only; the record keeps all three) |
| `data.conventions` | the data's reporting conventions, each a sentence, shown to the investigation and the writer (default none; below) |
| `eval.*` | question and reference files, read only by benchmark mode, the tests and evaluation scripts; a task never sees them |

**How each LAS is interpreted.** With `interpret` set, `petrophys.interpret` interprets the LAS with those options
(`{}` for the library's defaults). With `interpreter` set, that function does. With neither, the policy
(`src/petroharness/resources/policy/reference_v2.yaml`) decides: the pinned engine it names, from `engines_dir`, run
in a subprocess, or the installed library with the policy's corrections. Setting both `interpret` and `interpreter`
is an error.

**Context profiles.** For wells that belong to a Petrophys context package, `interpret: {context_profile: <name>}`
interprets each well as that package's context does: its preparation, the workflow, its QC and recomputation, with
every calculation in the step record the harness reads.

```yaml
data:
  las_dir: /path/to/las
  tops_csv: /path/to/formation_tops.csv
  interpret: {context_profile: <name>}
```

### The skill library

The guides the model reads come from a pluggable skill library. One setting picks it: `skills` in the harness
configuration, or `PETROHARNESS_SKILLS`, which overrides it. Its value is a library folder (absolute, or relative to
`src/petroharness/resources`) or `none`. The default is the packaged library, `skills/researched`: one guide per topic
area and two common guides (`answer`, `route`), written from the petrophysics literature, with the sources of every
line.

```bash
export PETROHARNESS_SKILLS=/path/to/my_library   # another library: library.yaml, refs.yaml,
                                                 # <guide>/SKILL.md, <guide>/sources.yaml
export PETROHARNESS_SKILLS=none                  # no library: no DIRECTION index, no guide action
```

The harness owns the topic areas (`src/petroharness/resources/topics.yaml`); a library's guides declare the areas they
serve. A library is checked as it loads, and a bad one stops the run before its first question, with each problem as
WHAT / WHY / FIX. Each trace records the library it read (`skills`: its name and a hash of its files). The format and
the checks: `src/petroharness/resources/skills/README.md`.

### Environment variables

| variable | meaning |
|---|---|
| `PETROHARNESS_DATA` | the data config (default `configs/data.local.yaml`) |
| `PETROHARNESS_MODEL_URL` | the model endpoints, comma-separated (`docs/MODELS.md`) |
| `PETROHARNESS_API_KEY` | the API key sent to the endpoints (a model card can name another variable) |
| `PETROHARNESS_SKILLS` | the skill library: a folder or `none` |
| `PETROHARNESS_COMPONENTS` | another copy of the component texts (`src/petroharness/agent/components`), to compare two versions |
| `PETROHARNESS_SET` | switches under test, `name=true,...`; this release defines none |

Hosted tracing stays off: the harness refuses to start when `LANGSMITH_TRACING` (or a LangChain equivalent) is on,
because LangSmith would send every prompt, with the well data, to its service.

## Benchmark mode

Benchmark mode runs a question file with reference answers, in parallel, and saves an answer and a trace for each.
It is for validating the harness on a question set; for your own wells, use the default command ([USAGE.md](USAGE.md)).

```bash
export PETROHARNESS_DATA=/path/to/data.yaml
export PETROHARNESS_MODEL_URL=http://host-a:8100/v1,http://host-b:8100/v1
.venv/bin/petroharness benchmark --arm run1 --cats porosity,saturation --ids ids.json --gt-dir /path/to/reference_files \
    --workers 40
```

**The question file** is the data config's `eval.questions`: a JSON list with one row per question.

```json
{"qa_id": "q0001", "question": "...", "las_path": "WELL_A.las", "formation": "EXAMPLE FM. TOP", "category": "porosity"}
```

- `las_path`: only the file name is used; the file is read from the data config's `las_dir`.
- `formation`: a top name, whose interval the tops table gives (the named top down to the next deeper top), or a
  depth interval, `{"name": ..., "top": ..., "base": ..., "depth_unit": "m" | "ft"}` (depths in the LAS's own depth
  unit when `depth_unit` is left out; an optional `"lithology"` states the formation's lithology).
- `category`: a group name. `--cats` selects groups, and the group names the output folder. The run itself never
  sees it.
- `qa_id`: the question's id. The run sees only an opaque task id made from it (`t` and 10 hex digits).

**The options:**

| option | meaning |
|---|---|
| `--arm NAME` | a name for the run; it starts every output folder's name |
| `--cats A,B` | the groups to run (default `hydrocarbon`) |
| `--ids FILE` | a JSON file `{"qa_ids": [...]}`: the questions to run |
| `--gt-dir DIR` | a folder of reference files, one per group (`single_formation_<group>_qa_pairs.json`); the runner copies the rows of the run's questions to `runs/gt_subsets/`, for scoring outside the harness. No question's run reads it. |
| `--rep N` | the run number (default 1); above 1 it is added to the folder names, and it changes which server a question uses |
| `--models KEY` | the model registry key (default `k200t`: K2-Horizon-7B's card) |
| `--model NAME` | any chat model, by its served name (the generic card; instead of `--models`) |
| `--model-card CARD` | a model card: a YAML file or a packaged card's name (instead of `--models`; `docs/MODELS.md`) |
| `--workers N` | questions run at once (default 12) |
| `--max-steps N` | the step cap (default 8) |
| `--writer open` | the writer's repair rounds: `open` (default) allows two, `''` one |
| `--format profile` | the answer format: the report style's (`profile`, default) or the writer's own (`default`) |

**The output**, under `runs/` in the checkout:

```
runs/<arm>_<model>[r<rep>]_<group>/traces/<task_id>.json        one per question: the answer, its status, every call
runs/<arm>_<model>[r<rep>]_<group>/responses/single_formation_<group>_qa_pairs.json
                                                                 the answers: {metadata, qa_pairs: [{qa_id, question, answer}]}
runs/gt_subsets/<arm>_<model>[r<rep>]/single_formation_<group>_qa_pairs.json
                                                                 the reference rows of the run's questions
runs/summaries/run_<arm>_r<rep>.json                             counts: ok, unresolved numbers, errors; mean steps
                                                                 and opened results per question
```

**A benchmark's reporting settings.** A benchmark whose reference answers follow reporting conventions of their
own (a basis, a way of naming units) states them in its data config, never in the package. The answers are then
benchmark mode's, and are reported apart from the general harness's:

```yaml
data:
  las_dir: /path/to/las
  tops_csv: /path/to/formation_tops.csv
  basis: zones                     # the tools' statistics on the lithology zones (the whole interval left out)
  conventions:                     # shown in every step prompt and to the writer, to be followed without being named
    - "Flow units are reported per lithology zone: each zone is named as a flow unit with its FZI class, porosity,
      permeability and quality."
```

A question's status is `ok`, `unresolved_numbers` (the checker still found numbers no result shows after the
repairs) or `error: <type>` (the trace holds the error and its traceback; the run goes on). A run resumes: a question
whose trace was written at the same commit, without an error, is not run again.

## Testing

```bash
PETROHARNESS_DATA=/path/to/data.yaml .venv/bin/python -m pytest -o addopts= -q -n 16 -p no:cacheprovider tests
```

Tests marked `data` need the files the data config names; they skip where a dataset lacks what a test needs.
Some tests need data that is not part of this repository, and skip without it:
- the golden tapes (`tests/golden/`) and the prompt fixture (`tests/agent/fixtures/prompts.json.gz`) are recorded on
  benchmark wells and kept with that data; the golden tests also read the data configs from `$WELLLOGBENCH`;
- the end-to-end tests of the own-well command and the web UI read sample wells from `$PETROHARNESS_SAMPLE_LAS`;
- the tests of saved runs read `$PETROHARNESS_RUNS` (a glob of run folders).

`tests/test_generality.py` holds one test per rule of the generality contract (`docs/DESIGN.md`), and
`tests/test_lint.py` keeps well, formation and dataset names and depth literals out of the code, rules and prompts.

Three regression gates show that a change alters nothing it does not mean to. They run wherever their data is
present: record golden tapes and a fixture on wells you have with the tools below. A change that alters behaviour
on purpose re-records the gate it changes, after checking that every difference is intended.

- **Golden tapes** (`tests/agent/test_golden_tapes.py`). `tests/golden/<dataset>/` holds, for each recorded question,
  every model request and reply (`<task>.tape.jsonl.gz`) and the result the code gave (`<task>.result.json.gz`). The
  test replays each question through the question graph with no server: every request must equal the recorded one
  field by field, and the answer, status and trace (component versions included) must equal the recording.
  `tests/agent/record_golden.py replay` rewrites the results from the tapes, and refuses when the code makes a request
  a tape does not hold; `record_golden.py live` records new tapes from the servers. The data configs are read from
  `$WELLLOGBENCH/<dataset>.yaml`.
- **The prompt fixture** (`tests/agent/test_skill_library.py`). `tests/agent/fixtures/prompts.json.gz` holds five
  prompts for each of 12 tasks: the brief, the READ prompt, the step-1 prompt with its first look, the DIRECTION
  index, and the step-2 prompt after two guides and an action the harness does not read. They are rendered with a stub
  model, and the test compares them byte for byte. `tests/agent/prompt_fixture.py` renders them.
- **The ledger replay** (`tests/agent/replay.py`). `replay.py PREFIX OUT.json --baseline` rebuilds each saved
  investigation of `runs/PREFIX_*/traces/` through the ledger, with no model call: the traced tool calls run again in
  order, and the claims are restored and re-checked. It reports how many rebuild exactly: the same opened results and
  the same claim flags. Without `--baseline` it also runs the settle step and the writer on each rebuilt session
  (this needs the servers).

## Layout

```
src/petroharness/
  cli.py        the command line: a question about one well (default) and benchmark mode
  ask.py        a question about any LAS file: the interval, the settings, the run, the output (and its Python API)
  ui/           the web UI: a standard-library server over ask, the page, saved runs
  config.py     the configuration (data config, model, resources, skill library)
  tasks.py      a question as the harness sees it: question, well, interval, LAS path
  llm.py        the client: token accounting, retries, the reasoning field
  tape.py       record and replay at the model boundary
  models.py     the model: model cards (resources/models) and endpoints
  profile.py registry.py   the report style, the registries
  well/         the raw LAS read and interpreted by Petrophys, viewed interval by interval; the summary layer;
                the tops reader (well/tops.py)
  record/       the workflow's record as evidence: analyzer sections, the evidence catalog, the record's facts
  agent/        the map, the tools, the ledger and claims, the question graph, the writer; library*.py: the
                verbs over Petrophys and the registry of its functions (docs/TOOLS.md)
  agent/components/   every fixed text the model reads, by component (C1-C10)
  resources/    the policy, the report style, the registries, the topic areas, the skill libraries, the model cards
configs/        data.example.yaml
tests/          unit and data tests; tests/agent the harness's own; tests/golden the tapes
docs/           USAGE.md (your own wells), MODELS.md (models), UI.md (the web UI), ARCHITECTURE.md, GRAPH.md and
                graph.mmd (the question graph), DESIGN.md, DEVELOPMENT.md (this file), images/
```

`AGENTS.md` holds the rules for changing the code; `CHANGELOG.md` the releases.
