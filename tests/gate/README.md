# The gates

A change to the harness is either meant to alter what the model is sent, or it is not. These tools prove which.

| Gate | Proves | Needs | Run |
|---|---|---|---|
| Public mini set | A recorded conversation on a Petrophys sample well replays request for request, with the same answers | Nothing: no model server, no private data | `pytest tests/gate -q` |
| Golden tapes | 36 recorded benchmark questions replay with the same requests, answers and traces | The benchmark's data settings (`WELLLOGBENCH`) | `pytest tests/agent/test_golden_tapes.py -q` |
| Request gate | Every request of every saved run of the reference runs is rebuilt unchanged: the head's route, and the `--investigate` route on runs made with it | The benchmark's data and the saved runs | `python tests/gate/request_gate.py record ...` then `compare` |

Use them in that order. The mini set takes a few minutes and runs anywhere. The request gate is the widest and is the
one a maintainer runs before a change to the question graph is merged.

## The public mini set

`tests/gate/mini/<name>/` holds one recorded conversation: `set.json` (the sample well, the formation, the questions,
the interval, the Petrophys build and the setup it was recorded with, and what each question must reproduce) and, for
each question, its tape (every model request and reply) and its answer.

`test_mini.py` starts the same conversation on the same sample well and answers the model's calls from the tape. The
replayer compares each request with the recorded one and stops at the first difference, naming the call and the place.
The answers, the results opened, the number links, the steps behind them and the figures chosen must come out the
same. Then the interval's display and the audit trail are checked.

Record it again only when a change is meant to alter what the model is sent or how a conversation runs:

```bash
PETROHARNESS_MODEL_URL=http://HOST:PORT/v1 python tests/gate/record_mini.py
```

A different Petrophys version computes different curves, so different prompts. The test then skips and says which
version the set was recorded with.

## The request gate

```bash
# on the reference build, once
python tests/gate/request_gate.py record --runs RUNS --prefix PREFIX --ids IDS.json --card CARD --out base/PREFIX.jsonl
# on the changed code
python tests/gate/request_gate.py record --runs RUNS --prefix PREFIX --ids IDS.json --card CARD --out new/PREFIX.jsonl
python tests/gate/request_gate.py compare base/PREFIX.jsonl new/PREFIX.jsonl
```

For each saved run the question is run again with the model's replies taken from the run's trace, and every request
the code builds is hashed: each message of each call, its schema, its token cap, its temperature and its retry flag,
with the status and the answer. `compare` counts every difference by kind and exits 0 when there is none.

Replay one run at a time per process (`--workers 1`, the default), and start one process per run set to use the
machine's cores. Replays in several threads of one process are not fully deterministic.

## When a gate fails

A failure means the change reaches the model. If that was not intended, the difference named is the bug. If it was
intended, it is a behaviour change: measure it end to end (`docs/DEVELOPMENT.md`), then record the tapes and the mini
set again in the same change.

## Gates that need the benchmark's data

The golden tapes, the prompt fixture, the ledger replay and the request gate read the benchmark's data and recorded
runs, which are kept with the benchmark, not in the public repository.

<a id="the-golden-tapes"></a>
<details>
<summary>The golden tapes</summary>

Recorded first questions from three benchmark datasets, 12 each, replayed through the question graph with no server
(`tests/agent/test_golden_tapes.py`, `tests/agent/record_golden.py`). They are kept with the benchmark data, not in the
public repository; without them the test has no cases.

| Name | Type | Default | Meaning | Defined in |
|---|---|---|---|---|
| `selection.json` | JSON | | `questions` (`task_id`, `qa_id`, `category`), `model` (the model registry key the tapes were recorded with), `code`, `commit`, `recorded` (`live` or `replay`), `tapes_from` (`code`, `commit` of the live recording). | `record_golden.main` |
| `<task>.tape.jsonl.gz` | gzip JSON lines | | One line per call: `{"n", "request", "reply": {"content", "tool_calls", "finish_reason", "reasoning", "usage"}}`. | `tape.record` |
| `<task>.result.json.gz` | gzip JSON | | `{"answer", "status", "trace"}` as `graph.answer` returned it. | `record_golden.one` |
| Test | pytest, `data` | one case per question | Sets `PETROHARNESS_DATA=$WELLLOGBENCH/<dataset>.yaml` and `PETROHARNESS_SET=""`, loads the task, replays the tape through `graph.answer(..., llm_factory=Taped)` and compares with `tape.compare_run(..., versions=False)`; a difference in version stamps only is a warning. | `test_golden_tape_replays_identically` |
| `record_golden.py replay [DATASET ...]` | recorder | all datasets | Keeps every tape and rewrites each result from it; exits with `<dataset> <task>: <error>` when the code makes a request the tape does not hold, or `N recorded calls never made`. | `record_golden.one` |
| `record_golden.py live [--workers N] DATASET ...` | recorder | `--workers 12` | Records new tapes and results from the model at `PETROHARNESS_MODEL_URL`, N questions at a time. | `record_golden.one` |

```bash
WELLLOGBENCH=/path/to/configs .venv/bin/python -m pytest -o addopts= -q -m data -n 12 tests/agent/test_golden_tapes.py
WELLLOGBENCH=/path/to/configs PYTHONPATH=src:tests/agent .venv/bin/python tests/agent/record_golden.py replay
WELLLOGBENCH=/path/to/configs PETROHARNESS_MODEL_URL=http://localhost:8000/v1 PYTHONPATH=src:tests/agent \
    .venv/bin/python tests/agent/record_golden.py live --workers 12 <dataset>
```

- What `tape.compare_run` compares, in order: a `TapeMismatch` error in the replay; calls left on the tape; the
  answer; the status; then the trace without its volatile keys (`VOLATILE`: `harness`, `commit`, `seconds`,
  `traceback`) and without the usage log's `seconds`. The setup is compared by its parts (`setup_parts` less
  `harness` and `commit`); its hash, which covers the commit, is left out.
- Switches: a switch the recording does not know must be off (`trace.options: new switches on: [...]`); a switch the
  code no longer has passes only when the recording ran it at the value now fixed in code (`fixed`).
- Keys of `ADDED` (`calls`, `components`, `draft_chars`) that only the replay has are skipped.
- Each question builds its formation, about 10 s each, so run the test with `-n`.
- `record_golden.py` records the checkout's commit (`git rev-parse --short HEAD`) in `selection.json`: record from a
  clean checkout of the commit the tapes are for.

</details>

<a id="the-prompt-fixture"></a>
<details>
<summary>The prompt fixture</summary>

Five rendered prompts for each of 12 tasks, compared byte for byte with the packaged skill library plugged
(`tests/agent/fixtures/prompts.json.gz`, `tests/agent/test_skill_library.py`, `tests/agent/prompt_fixture.py`). Like
the golden tapes it is recorded on benchmark wells and is not in the public repository.

| Name | Type | Default | Meaning | Defined in |
|---|---|---|---|---|
| `STRINGS` | tuple | `brief`, `read`, `step1`, `direction`, `step2` | The brief (system prompt); the READ prompt; the step-1 user prompt with its first look; the DIRECTION index; the step-2 user prompt after step 1 read two guides and one action the harness does not read. | `prompt_fixture.STRINGS` |
| Fixture file | gzip JSON | | `{"rendered_by": LABEL, "tasks": [{"dataset", "qa_id", "task_id", "brief", "read", "step1", "direction", "step2"}]}`; 6 tasks of the first dataset, 3 of each other. | `prompt_fixture.main` |
| `test_the_prompt_fixture` | pytest | | Checks the fixture's shape and its `rendered_by` label. | `test_skill_library.py` |
| `test_with_the_researched_library_plugged_the_prompts_are_the_fixtures` | pytest, `data` | one case per task | Renders each task with `prompt_fixture.render` (a stub model, no call) and fails at the first differing character, showing 60 characters each side. | `test_skill_library.py` |
| Rendering | script | | `PYTHONPATH=<src> PETROHARNESS_DATA=<a dataset's yaml> python tests/agent/prompt_fixture.py IDS_DIR OUT.json.gz LABEL`; `IDS_DIR` holds `smoke_ids_<dataset>.json` (`{"qa_ids": [...]}`), and each dataset's config is `<dataset>.yaml` beside `PETROHARNESS_DATA`. | `prompt_fixture.main` |

```bash
PETROHARNESS_DATA=/path/to/configs/<dataset>.yaml \
    .venv/bin/python -m pytest -o addopts= -q -m data tests/agent/test_skill_library.py
```

- The tasks are rendered with each dataset's default reporting settings (`data.basis: all`, no conventions), so the
  general and the benchmark data files render the same fixture.
- When re-rendering, keep the label `test_the_prompt_fixture` expects, or update the test with the fixture.

</details>

<a id="the-ledger-replay"></a>
<details>
<summary>The ledger replay</summary>

Rebuilds saved investigations through the ledger with no model call, to show that the tools still open the same
results and the claim checks still flag the same claims (`tests/agent/replay.py`).

| Name | Type | Default | Meaning | Defined in |
|---|---|---|---|---|
| `PREFIX` | argument | required | Saved runs under the repository's `runs/`: every `runs/PREFIX_*/traces/*.json`. | `replay.main` |
| `OUT.json` | argument | required | Where the rows are written. | `replay.main` |
| `--baseline` | switch | off | Measure the traced answers: no settle step and no writer, so no model call. Without it, the settle step and the writer run on each rebuilt session (endpoints from `PETROHARNESS_MODEL_URL`, the default model card). | `replay.main` |
| `--variant NAME` | text | `""` | The writer variant to run. | `replay.main` |
| `--format` | `profile` or `default` | `profile` | The answer format. | `replay.main` |
| `--limit N` | integer | 0 (all) | Only the first N traces. | `replay.main` |
| `rebuild(trace, task, cfg)` | function | | Opens the traced first look and every traced action in order (a call that failed then fails now; one that runs now but failed then is dropped), restores the claims and re-checks them. Reports `opened_equal`, `flags_equal`, `n_opened`. | `replay.rebuild` |
| `metrics(s, answer, trace)` | function | | The writer's per-answer checks (untraced numbers, claim coverage, notes, points, absence said, confidence, tables, unknown names, zone naming, format, verdict clauses, contradictions). | `replay.metrics` |

```bash
PETROHARNESS_DATA=/path/to/data.yaml .venv/bin/python tests/agent/replay.py <prefix> out/replay.json --baseline
```

```text
<prefix> variant=(current) baseline=True: rebuilt exactly N of M
{ "n": M, ... }
```

- Each output row is `{"task_id", "topics", "rebuild", "answer", "metrics", "verify_rounds", "settle"}`.
- A change that should not alter the investigation keeps "rebuilt exactly" at its value on the reference runs.
- The data config must hold the question file (`eval.questions`) and the LAS folder the runs used.

</details>

<a id="the-request-gate"></a>
<details>
<summary>The request gate</summary>

Rebuilds every request of every saved run of a reference build and hashes it, so two builds can be compared over far
more questions than the golden tapes hold (`tests/gate/request_gate.py`).

| Name | Type | Default | Meaning | Defined in |
|---|---|---|---|---|
| `record --runs RUNS` | folder | required | Saved runs, laid out as the benchmark runner writes them: `RUNS/<PREFIX>_<category>/traces/<task id>.json`. | `request_gate.record` |
| `--prefix PREFIX` | text | required | The runs' prefix (`<arm>_<model>` of benchmark mode). | `request_gate.main` |
| `--ids IDS.json` | file | required | `{"qa_ids": [...]}`: the questions to replay. | `request_gate.record` |
| `--card CARD` | model card | required | The card the runs were made with (`models.register` with an unused URL). | `request_gate.record` |
| `--writer` | text | `open` | The writer's repair rounds the runs used. | `request_gate.main` |
| `--out FILE` | path | required | The hash file: one JSON line per run, `{"task_id", "calls": [[stage, [message hashes], schema hash, max_tokens, temperature, retry], ...], "status", "answer"}` (answer hashed). | `request_gate.record` |
| `--workers N` | integer | 1 | Replays per process. Keep 1: replays in several threads of one process are not fully deterministic. | `request_gate.main` |
| `--investigate` | switch | off | The runs gave every question the full investigation. | `request_gate.main` |
| `compare BASE NEW [BASE2 NEW2 ...]` | files | pairs | Counts every difference by kind (number of calls, stage, messages, parameters, status, answer, run missing, file missing) and prints up to 10 examples; exits 0 only when every run is equal. | `request_gate.compare` |

```bash
# on the reference build
PETROHARNESS_DATA=/path/to/data.yaml PYTHONPATH=/path/to/reference/src python tests/gate/request_gate.py record \
    --runs RUNS --prefix PREFIX --ids IDS.json --card CARD --out base/PREFIX.jsonl
# on the changed code
PETROHARNESS_DATA=/path/to/data.yaml PYTHONPATH=src python tests/gate/request_gate.py record \
    --runs RUNS --prefix PREFIX --ids IDS.json --card CARD --out new/PREFIX.jsonl
python tests/gate/request_gate.py compare base/PREFIX.jsonl new/PREFIX.jsonl
```

```text
PREFIX           N/N identical

N/N runs identical (calls, messages, parameters, status, answer)
```

- A replay is not the run again: a step's reply is rebuilt from the fields its trace kept (`step_reply`), and the
  writer's and a repair's reply is the run's final answer (`Replies`). Both builds get the same replies, which is what
  the gate compares.
- `record` exits 1 when any replay raised (its status is `ERROR ...`), and prints
  `PREFIX: N runs, M calls, K replay errors`.
- Start one process per run set to use several cores.

</details>
