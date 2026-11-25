# Contributing to PetroHarness

PetroHarness answers petrophysics questions about an interval of a well from its raw LAS file. Petrophys calculates,
a language model investigates, and the harness records every step. This page says where a contribution goes and how
to show that it does what you mean and nothing else.

- [Set up](#set-up)
- [Where a contribution goes](#where-a-contribution-goes)
- [Show that a change is safe](#show-that-a-change-is-safe)
- [The rules](#the-rules)
- [A pull request](#a-pull-request)

## Set up

```bash
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install "petrophys @ git+https://github.com/sambalshikhar/petrophys.git@3a9378e27eaab54077d326ba5fbbfc6de569f56b"
.venv/bin/pip install -e ".[dev]" --no-deps
.venv/bin/python -m pytest tests -q        # tests that need benchmark data or a model server skip
```

No model server is needed to run the tests. To ask a question you need one
([docs/MODELS.md](docs/MODELS.md)).

## Where a contribution goes

| You want to add | It goes in | What you write |
|---|---|---|
| A calculation, a method, a correction, a classification | [Petrophys](https://github.com/sambalshikhar/petrophys) | The function, in Petrophys. The harness lists every public Petrophys function for the model with no change here ([docs/TOOLS.md](docs/TOOLS.md)) |
| A tool of the harness itself (a lookup of the record, a computed table) | `src/petroharness/agent/toolset.py` ([docs/TOOLS.md](docs/TOOLS.md), "Adding a tool") | The function and one `Tool` definition. It changes what the model is sent, so it is a measured change: see below |
| A plot | Petrophys (`petrophys.visualization`) | The plot, in Petrophys, then one line in `DISPLAYS` in `src/petroharness/figures.py`. The harness draws nothing itself |
| Guidance for the model on a topic (how an expert works a kind of question) | A skill library ([docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), "The skill library") | A guide folder: text and recipes, no code |
| Support for a model | A model card ([docs/MODELS.md](docs/MODELS.md)) | A YAML file of request settings |
| Something that reads an answer: an export, a check list, a table | The session graph ([docs/GRAPH.md](docs/GRAPH.md#the-session-graph)) | A node after `turn`, with its route. It cannot change an answer |
| Something that needs what an answer rests on | The evidence graph ([docs/EVIDENCE.md](docs/EVIDENCE.md)) | A reader of `EvidenceGraph`, or a new node or link kind built from the session log |
| A change to how a later question of a conversation is answered | The later-question graph ([docs/GRAPH.md](docs/GRAPH.md#the-later-question-graph)) | A node or a route |
| A change to how the first question is answered | The question graph ([docs/GRAPH.md](docs/GRAPH.md#the-question-graph)) | A measured change: see below |

Science goes into Petrophys. The harness decides what to compute, records it and checks the answer; it does not
compute petrophysics (`tests/test_petrophys_integration.py` enforces this).

## Show that a change is safe

Most changes are meant to alter nothing the model is sent on a first question. Three gates prove it
([tests/gate/README.md](tests/gate/README.md)):

1. **The public mini set**, which anyone can run: `pytest tests/gate -q`. A recorded conversation on a Petrophys
   sample well must replay request for request.
2. **The golden tapes**, where the benchmark's data is present: `pytest tests/agent/test_golden_tapes.py -q`.
3. **The request gate**, run by a maintainer on every saved run of the reference build.

If a gate fails and you did not mean to change what the model is sent, the difference it names is the bug.

A change that is meant to alter what the model is sent on a first question is a **behaviour change**. It is judged by
the answers, not by the tests:

- measure it end to end on a fixed set of questions, against a control run at the same time, two runs of each;
- read the answers yourself before any automatic scoring;
- say in the pull request what you measured;
- record the tapes and the mini set again in the same change.

## The rules

The full list with reasons is in [AGENTS.md](AGENTS.md). The ones a first contribution meets:

1. **No dataset names or literals** (wells, formations, depths, values) in code, rules or prompts.
   `tests/test_lint.py` checks every guarded file.
2. **Code computes and states facts; the model interprets.** No rule fitted to an expected answer, and code never
   overrides a decision the model made.
3. **Every step is one model call rebuilt from the state.** No multi-turn chat inside an investigation.
4. **One model answers.** No helper model, and no code path for one model only: what differs is the model card.
5. **Every fixed text the model reads lives in a component** (`src/petroharness/agent/components/`), so each call's
   text can be traced to the file it came from.
6. **Errors say what, why and how to fix it.**

## A pull request

- One change per pull request, with its test.
- `ruff check src tests` and `pytest tests -q` pass.
- The description says what the change is for, which gate you ran, and, for a behaviour change, what you measured.
- New user-facing behaviour comes with its page in `docs/`.
- A contribution is released under the repository's licence, CC BY 4.0 ([LICENSE](LICENSE)).
