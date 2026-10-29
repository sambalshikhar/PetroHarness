# Changelog

## 3.5.0 (2026-10-29)

First public release.

- **One question, one interval, from the raw LAS.** Petrophys interprets the well (through `petrophys.interpret`
  with optional context profiles, a batch interpreter, or a pinned engine). The interval is a formation from a tops
  file, a depth interval, or the whole well, and it is zoned by its lithology log (shale-volume bands without one).
- **The question graph** (LangGraph): READ, the first look, up to 8 investigation steps, settle, the writer, its
  checker and repairs. Every step is one model call rebuilt from the state.
- **Topics chosen by the model.** The READ call picks the question's topic areas (14 areas, owned by the harness) and
  lists the measurements it names; what the question names that the record lacks is said once.
- **Tools** for lookups (`stats`, `runs`, `compare`, `overlap`, `profile`, `crossplot`, `lag_correlation`,
  `section`, `step`), named computations, and `get`, `find` and `calc` on the ledger. Analyzer sections show each
  class as located runs; every line names its basis and the status of its curve.
- **One summary layer** for every tool that summarises a curve: each zone, the zones pooled, the whole interval;
  statistics, rankings, thresholds and classes chosen by the shape of the data, never by a curve's name.
- **The ledger and the claims.** Every result is kept whole with an id; the answer is a set of graded claims that
  cite results, checked by code for facts about the record and the citations.
- **A pluggable skill library** (`skills: <path> | none`, `PETROHARNESS_SKILLS`). The packaged library has one guide
  per topic area and two common guides, written from the literature, with the provenance of every line.
- **The writer and its checker**: numbers no result shows, words about the process, statements the record
  contradicts and working notes are sent back for repair; a code-composed zone table; a configurable report style.
- **Traces** with every model call attributed to its components (C1-C10) and their versions, the skill library
  read, and token use.
- **Questions about your own wells** (`petroharness --las WELL.las --question ...`, the default command): the
  interval from a tops file and a formation name, from explicit depths, or the whole well.
- **A web UI** (`petroharness ui`): the same questions in the browser, with live progress, saved runs, ratings and
  replay.
- **Benchmark mode** (`petroharness benchmark`): a question file with reference answers run in parallel, for
  validation; resumable, with an answer file and a trace per question.
- **Tests**: the generality contract (G1-G8), the dataset-name lint, and three regression gates (golden tapes, the
  prompt fixture, the ledger replay).
- Python 3.10; dependencies pinned in `requirements.lock`; Petrophys pinned at
  916ca46c37980ceac56a0c4ac94b2eb0f8d8632c.
