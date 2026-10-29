# PetroHarness

PetroHarness answers a petrophysics question about one interval of one well, starting from the well's raw LAS file.

- **Petrophys calculates.** Every petrophysical number comes from the Petrophys library: the interpretation of the
  LAS, the analyzers' classes, the statistics.
- **The harness lets the model investigate step by step, and records every step.** The model never sees all the data
  at once. It reads a map of what the record holds, asks for results with tools, and builds its answer as claims that
  cite those results. Every result is kept in full with an id, and every model call is written to the trace.
- **The model interprets and writes.** Presence, fluid, mobility, rankings and verdicts are the model's readings of
  computed facts. The model is K2-Horizon-7B.
- **Code checks what it writes.** Code shows the model facts about the record and its citations: a number no result
  shows, an item cited but not opened, data said missing that the interval has. The model decides what to do with
  them; code never changes its grades, verdicts or text.

The point is auditability. Each number in an answer can be traced to the result that holds it, each result to the
tool call that opened it, and each prompt can be rebuilt from the trace.

## How it works

1. **The well.** The raw LAS is interpreted by Petrophys and cut to the interval the user asks about: a formation
   named in a tops file, or a depth interval; with neither, the interval is the whole well. The interval is split into
   zones by its lithology log (by shale-volume bands where the well has none). Zones are the unit of analysis.
2. **The map.** The model first reads the interval as plain facts: its zones, its curves and what each one is, the
   workflow's steps and sections.
3. **READ.** One call in which the model chooses the topic areas the question touches and lists the measurements it
   names. A measurement the question names that this well's record lacks is said once, under the question.
4. **The first look.** The key curves of the chosen topics, zone by zone, opened before the first step.
5. **The steps.** Up to 8. Each step is one model call rebuilt from the state. The model adds, revises and drops
   claims, and asks for lookups, guides and calculations. Code runs them into the ledger and checks each claim as it
   arrives. When the model says it is done, code accepts that only if every point it set has a settled claim
   (graded, cited, unflagged) and no claim is left as a hypothesis or flagged; otherwise it refuses once and names
   what is open. The investigation also ends when two steps in a row only rephrase a settled answer, and at the step cap.
6. **Settle.** A last step with every opened result in view; the claims become final.
7. **Write.** The writer writes the answer from the claims and the results they cite. A checker looks for numbers no
   result shows, words about the investigation instead of the formation, statements the record contradicts and
   working notes left in the text, and asks for repairs (up to two rounds). Code places the zone table.

The parts, and how a question flows through them: `docs/ARCHITECTURE.md`. The question graph, node by node:
`docs/GRAPH.md`. The design rules: `docs/DESIGN.md`.

## Install

Python 3.10. The environment is pinned in `requirements.lock`. Petrophys is pinned at commit
916ca46c37980ceac56a0c4ac94b2eb0f8d8632c.

```bash
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install "petrophys @ git+https://github.com/sambalshikhar/petrophys.git@916ca46c37980ceac56a0c4ac94b2eb0f8d8632c"
.venv/bin/pip install -e . --no-deps        # the lock already holds every dependency
```

The package installs the command `petroharness`.

## Serving the model

The harness talks to an OpenAI-compatible endpoint. The model is K2-Horizon-7B (its GRPO checkpoint, served as
`k2-horizon-7b-grpo200`), served by vLLM 0.30 or later with native tool calling:

```bash
vllm serve /path/to/k2-horizon-7b-grpo200 --served-model-name k2-horizon-7b-grpo200 --port 8100 \
    --trust-remote-code --dtype bfloat16 --max-model-len 131072 \
    --reasoning-parser k2_horizon --chat-template-content-format string \
    --enable-auto-tool-choice --tool-call-parser k2_horizon
```

`--chat-template-content-format string` is required: the model's chat template reads each message's content as a
string, and without the flag the user text does not reach the model.

The model card, `src/petroharness/resources/models/k2_horizon_7b_grpo200.yaml`, sets how the harness calls it:
reasoning effort high (low for the one retry after an empty reply), temperature 1.0, top_p 0.95, and up to 32,768
output tokens for a step and for the writer. A reply cut off by the token cap is a failed reply, not a short one.

Point the harness at the servers with `K2H_TOOL_URLS`, a comma-separated list of base URLs. Each question uses one
of them, chosen by its task id and run number, so a batch spreads over the servers.

```bash
export K2H_TOOL_URLS=http://host-a:8100/v1,http://host-b:8100/v1
```

The API key is read from `PETROHARNESS_API_KEY` (a local vLLM server accepts any key).

## Using it on your own wells

Asking about your own well is the default command. Give the LAS file, the question and, if you have it, the interval:

```bash
export K2H_TOOL_URLS=http://host-a:8100/v1          # where the model is served (comma-separate several servers)

# a formation from a tops file
petroharness --las well.las --tops tops.csv --formation "Mount Messenger" \
    --question "Where are the best reservoir intervals in this formation, and is any of them hydrocarbon-bearing?"

# a depth interval (both depths included; the LAS's own depth unit unless --depth-unit says otherwise)
petroharness --las well.las --top 5340 --base 5600 --depth-unit ft --question "..."

# the whole well (the default when no interval is given)
petroharness --las well.las --question "..."
```

- **Tops file:** a CSV, TSV or Excel table, one row per top. Its columns are found by meaning (`formation`,
  `formation_name`, `name`; `top`, `top_depth`, `md`; an optional `bottom`/`base`; an optional depth unit; an optional
  well column). The interval runs from the formation's top to its stated base, else to the next deeper top, else to
  the end of the log. Formation information in another form (a list in a report or an email) becomes such a table
  in a few lines; `docs/USAGE.md` shows how.
- **No lithology log:** the well is zoned by shale-volume bands, and Petrophys's default interpretation does the rest.
  `--lithology-curve MNEMONIC` names a lithology or facies log the harness does not find on its own;
  `--formation-lithology TEXT` states what you know about the formation's rock.
- **Skills:** `--skills none` runs without the guide library; `--skills PATH` plugs in your own.
- **Output:** the answer is printed, and `answer.md` and `trace.json` (every model call and every result opened) are
  written to `./petroharness-out/<well>/` (`--out DIR`).
- **From Python:** `from petroharness.ask import ask; result = ask("well.las", "...", tops="tops.csv",
  formation="Mount Messenger")`.

The full guide, with every option, units, curve names and examples on three wells: `docs/USAGE.md`.

## Web UI

`petroharness ui` serves a page for the same questions in the browser: choose a LAS file (a path or an upload), the
interval (a formation from a tops file, a depth interval, or the whole well) and the question; follow the
investigation as it happens; then read the answer with the claims, the results they cite and the record behind it.
Every run is saved, can be rated and replayed.

```bash
export K2H_TOOL_URLS=http://host-a:8100/v1
petroharness ui                                   # http://127.0.0.1:7860
ssh -L 7860:localhost:7860 server                 # from your machine, when it runs on a remote server
```

The page asks through the same entry point as the command (`petroharness.ask`) and changes no prompt. Options, the
parts of the page and its API: `docs/UI.md`.

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
| `K2H_TOOL_URLS` | the model servers, comma-separated |
| `PETROHARNESS_API_KEY` | the API key sent to the servers |
| `PETROHARNESS_SKILLS` | the skill library: a folder or `none` |
| `PETROHARNESS_COMPONENTS` | another copy of the component texts (`src/petroharness/agent/components`), to compare two versions |
| `PETROHARNESS_SET` | switches under test, `name=true,...`; 3.5.0 defines none |

Hosted tracing stays off: the harness refuses to start when `LANGSMITH_TRACING` (or a LangChain equivalent) is on,
because LangSmith would send every prompt, with the well data, to its service.

## Benchmark mode (validation)

Benchmark mode runs a question file with reference answers, in parallel, and saves an answer and a trace for each.
It is for validating the harness on a question set; for your own wells, use the default command above.

```bash
export PETROHARNESS_DATA=/path/to/data.yaml
export K2H_TOOL_URLS=http://host-a:8100/v1,http://host-b:8100/v1
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
| `--models KEY` | the model key (default `k200t`: the model card above) |
| `--workers N` | questions run at once (default 12) |
| `--max-steps N` | the step cap (default 8) |
| `--writer open` | the writer's variant: `open` (default; everything opened in view, up to two repair rounds) or `''` |
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
  models.py profile.py registry.py   the model key, the report style, the registries
  well/         the raw LAS read and interpreted by Petrophys, viewed interval by interval; the summary layer;
                the tops reader (well/tops.py)
  record/       the workflow's record as evidence: analyzer sections, the evidence catalog, the record's facts
  agent/        the map, the tools, the ledger and claims, the question graph, the writer
  agent/components/   every fixed text the model reads, by component (C1-C10)
  resources/    the policy, the report style, the registries, the topic areas, the skill libraries, the model card
configs/        data.example.yaml
tests/          unit and data tests; tests/agent the harness's own; tests/golden the tapes
docs/           USAGE.md (your own wells), UI.md (the web UI), ARCHITECTURE.md, GRAPH.md and graph.mmd
                (the question graph), DESIGN.md
```

`AGENTS.md` holds the rules for changing the code; `CHANGELOG.md` the releases.

## License

No license has been chosen yet: this repository has no `LICENSE` file.
