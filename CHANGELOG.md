# Changelog

## 1.0.0 (2026-11-17)

Questions that need an investigation are answered as 0.2.1 answers them; a direct question now takes a short route
(below), measured on the whole benchmark with both models. With `--investigate` every request is the 0.2.1 build's,
proven on its 1,388 saved runs. The rest is new around the question: conversations, the evidence graph, figures.

- **Conversations.** Ask, read the answer, ask again: `petroharness chat` keeps one interval of one well open. A later
  question sees what the earlier ones found, reads their results again instead of computing them again, and may cite
  them. Result ids go on across questions. `docs/SESSIONS.md`.
- **Three graphs.** The question graph is the measured one. A later-question graph answers follow-ups on the same
  session, and lets the model choose a brief or a full reply. A session graph carries each question from the message
  to its committed record: `open -> turn -> project -> figures -> commit`. `docs/SESSION_GRAPH.md`.
- **One session log.** Every conversation is one append-only log with the texts it names kept by hash. A
  conversation is resumed from it, and what the model is shown of earlier questions is built from it by code.
- **The evidence graph and the audit trail.** `petroharness audit SESSION` writes, for each answer, the claims with
  the results they cite, the numbers with the results that show them, the curves those read, the Petrophys steps and
  parameters behind them, and the LAS file's hash. It needs only the session folder. `petroharness report SESSION`
  writes a whole conversation as one document. The web UI links each answer's audit trail. `docs/EVIDENCE.md`.
- **Methods and parameters under every answer**, read from the well's record by code.
- **Figures, drawn by Petrophys.** Where a plot says it better than text, the model chooses among the plots of the
  answer's results and the standard displays of the interval (density-neutron, Pickett, Buckles, flow units, triple
  combo and others). The harness draws nothing itself. A conversation also opens with Petrophys' log display of the
  interval. Never in a benchmark run.
- **Direct questions get a short route.** The model first says whether a question is direct (a value, a setting, a
  count or a fact that one or two lookups state) or needs an investigation. A direct question takes one or two
  look steps and a short answer with its basis: three model calls instead of eight or more. Where the lookups do not
  state what is asked, the question still gets an investigation (the look step or the writer hands it over). This is the default
  everywhere (the command, chat, the web UI, benchmark mode); `--investigate` gives every question the full
  investigation, the 0.2.1 route. Measured on all 347 benchmark questions, two runs per model, GPT-5 judge, against the two 0.2.1
  runs: K2-Horizon-7B W 67.03 against 66.67, Qwen3.5-27B GRPO 66.57 against 66.23 (both within the run-to-run
  interval); the questions read as direct (12-13% and 6%) score higher, at about a quarter of their tokens. Thinking is not
  reduced on the route: in the look steps that cost about 7 points of reference alignment and saved no time.
  `docs/GRAPH.md`.
- **The setup record.** `petroharness setup` prints what answers a question, with one hash; every conversation logs
  it and every trace names it. `docs/SETUP.md`.
- **The web UI** is laid out as a chat: one question box docked at the bottom, with the conversation's well, interval,
  interpretation settings and options as chips above it, and the runs in a drawer. While an answer is open, the next
  question continues its conversation (no separate follow-up box), and the earlier questions stay above it, each a
  box that opens to its whole answer and figures; *New conversation* starts another. Under each
  answer: its figures, the methods and parameters, the audit trail, and **How it was computed**, a graph from the
  measured logs through the Petrophys steps (method, parameters) and the results to the answer's numbers; click a
  number to see its path. **Interpretation settings**: every setting `petrophys.interpret` takes, with Petrophys's
  own help, choices and defaults, and the harness's zone rule (minimum zone thickness, shale-volume bands), previewed
  on the well before asking; the API's `ask(..., interpretation=)` takes the same settings. `docs/UI.md`.
- **Changing a setting in a conversation.** A setting changed mid-conversation (`/set m=1.8` in `petroharness chat`,
  `Conversation.adopt`, or the web UI's Interpretation chip) holds from the next question on: the well is interpreted
  again as a new generation, the ledger goes on and marks what was opened before as resting on the earlier settings
  (the same call asked again is computed anew), the next questions' prompts and the answer's header name the change,
  the log keeps it (a `settings` event, replayed on resume), and the evidence graph gives each answer the curves and
  parameters of its own generation. A conversation without a change sends the requests it sent before (the public
  mini set and the golden tapes replay unchanged). Seen live on K2-Horizon-7B: m 2 -> 1.8 on a conversation's fifth
  question; the answer cited m = 1.8 from the saturation step and compared its SW with the earlier result. Not
  judged on the benchmark: a benchmark question never changes a setting. `docs/SESSIONS.md`.
- **Field notes.** A YAML file of a team's standing choices for a field (`name`, `settings`, `notes`): its settings in
  force from the start under the user's own, each marked as the field notes'; its notes with every question as the
  user's statement; named in the answer's header; kept in the log (content and SHA-256). `--field-notes`, `field_notes=`,
  the web UI's Options. Never in a benchmark run. `docs/SESSIONS.md`.
- **Fix: a cutoff set in the settings panel** (VCL, SW or porosity) no longer stops the interpretation: the policy the
  view describes the well with takes the user's cutoff, as Petrophys used it.
- **Answers carry no evidence ids.** The delivered answer has no evidence id in any form a model writes one: a
  bracket that cites and says something keeps what it says ("(E10, n = 161)" becomes "(n = 161)"), a label naming
  part of the writer's input goes with its id, and an id used as a noun becomes "the result". On the 3,123 saved
  answers of the 1.0 model comparison, ids had been left in up to 48% of a model's answers; with this code, none.
  The trace keeps the writer's draft (`trace["draft"]`), so a later delivery change is judged on the same drafts.
  Judged with GPT-5 on K2-Horizon-7B, the changed answers against the old delivery: +0.02 W per changed answer on
  two saved runs (201 answers), −0.09 on two fresh runs (338 answers), both within the judge's noise.
- **One definition per tool.** Each tool is one `Tool` (`petroharness.tools.spec`) in `agent/toolset.py`: its
  function, arguments, description, group and how a call of it is listed. The lists that lived in six places are read
  from the definitions; every request is unchanged. `docs/TOOLS.md`, "Adding a tool".
- **Gates in the repository.** `tests/gate`: a public mini set (a recorded conversation on a Petrophys sample well,
  replayed with no model server and no private data) and the request gate as a tool. `CONTRIBUTING.md`, a CI
  workflow and the repository's own lint configuration.
- **Fixes:** a result id written as a possessive ("from E5's zone means") no longer leaves a stranded "'s" when the
  ids are taken out of the answer; an installed Petrophys is named by its own build; the web UI reports a run finished only once its
  record is saved.

## 0.2.1 (2026-11-14)

- **The writer reads the results for each point itself.** The writer is given the question's points and every result
  the investigation opened, not the investigation's claims. The limits the investigation found come with them, by
  point, so a result the investigation judged unusable is not repeated as a finding.
- **Each point gets its own part.** Rule 10 of the writer's brief: each of the question's points has its part, with its
  finding, the numbers and intervals it rests on and what limits it, and a table where zones or curves are compared.
- **The investigation ends on what it has seen.** A `done` while opened results are still withheld waits one step and
  shows them first. Once every point is settled, the step asks for the brief's "Before you finish" checks.
- **An order over a few zones is said to be untestable.** An exact rank test cannot test an order over fewer than five
  zones. The tool now says so, without direction words.
- **Measured** on the 347 single-formation questions of WellLogBench (GPT-5 judge, two full runs of each model):

  | Answering model | Version | RA | W |
  |---|---|---|---|
  | K2-Horizon-7B | 0.2.0 | 66.76 | 66.36 |
  | K2-Horizon-7B | 0.2.1 | 67.46 | 66.67 |
  | Qwen3.5-27B GRPO | 0.2.0 | 62.41 | 64.05 |
  | Qwen3.5-27B GRPO | 0.2.1 | 65.73 | 66.22 |

  The changes were made for answering models other than the default. They do not cost the default model anything:
  K2-Horizon-7B is +0.69 RA [-0.78, +2.12] against 0.2.0. A question costs more tokens than in 0.2.0 (K2-Horizon-7B
  281k to 307k, Qwen3.5-27B GRPO 225k to 268k).
- **No switches.** The six changes were measured as switches and are now the code. The 17 switches that were measured
  and not adopted are removed with their code and texts; `agent/options.py` defines none.
- **Tests.** `tests/agent/test_measured_build.py` asserts each of the six changes. The tests build their formations on
  the default reporting settings, so the suite gives the same result under any data settings. The 36 golden tapes
  were recorded again on K2-Horizon-7B.
- **Fix:** an installed Petrophys in a virtual environment inside a git repository was named in traces by that
  repository's commit. It is now named by its own build.

## 0.2.0 (2026-11-01)

- **The writer concludes from all the evidence.** The investigation still builds its claims as results come in. The
  writer now reads them with every result the investigation opened, in full, and where the two differ, the results
  decide. A provenance card goes with them: for each curve they name, its meaning, its status (measured, model
  output, parameter, fallback input), the record's cautions, and what its zoned values show about how they were made
  (constant, or held at a limit). One set of reporting rules (C9 `write`). A zone table inserted in the answer is
  not repeated in the text.
- **Each run names its rock.** A class's runs list each zone with its lithology (`Z2 (SAND) 4245.0-4253.6`), so a
  screen's flag is read against the rock it falls in.
- **Differences with their size.** On one scale, `compare` gives the zone means' mean difference against the spread
  of a - b, and `mean / sd` on every row.
- **Reporting settings in the data config.** `data.basis: zones` gives the tools' statistics on the lithology zones
  only. `data.conventions` lists the data's own reporting conventions, shown to the investigation and the writer.
  Both are empty by default, and then every prompt is the general one. A benchmark's conventions go in its data
  config (benchmark mode), never in the package.
- **Permeability guide:** flow units are reported as depth intervals with their class, starting from the workflow's
  FZI classes (Ebanks 1987; Amaefule et al. 1993); clustering is an alternative beside them; a porosity-only basis
  is a limit of the units, not a reason to deny them.
- **The web UI tells the interpretation as a story.** A run opens on *Interpretation*, conclusion first, the way a
  petrophysical report reads: the answer and how sure it is; the well as Petrophys interpreted it (a log plot and the
  zone table, the zones the answer names marked); how the answer was reached, part by part, each finding with a chart
  of the zone values it rests on, the net-pay cutoff, why it matters and what could change it; what limits the answer;
  then the whole written answer, where any number traces to the results that show it. The detail sits behind it:
  *Well logs* (the full plot, values at the cursor's depth), *Evidence* (each claim with the results it rests on, laid
  out as tables), the *Investigation log* (every stage and step, for audit) and *Details*.
  - `petroharness.ask` takes `on_view`, called with the interval's view once Petrophys has interpreted the well.
- **Fixes:** drafting left in the writer's reply ("Need ensure ...") is cut or sent back; `get` by class and zone
  reads runs written with their zone's rock.
- **No switches:** `agent/options.py` defines none; `--writer` sets only the repair rounds.
- **Documentation:** `docs/ARCHITECTURE.md` opens with a diagram of the whole harness and describes the reporting
  settings.

## 0.1.2 (2026-10-29)

- **Petrophys on request.** The model can now ask Petrophys for what the record does not hold.
  - `calculate` recomputes a property with another method or parameters, through Petrophys's own workflow step,
    with the steps that read its outputs. Examples: SW with Simandoux, VCL with Larionov, porosity with a
    limestone matrix, permeability with Timur, a stated Rw.
  - `what_if` tries several values of one input against a target.
  - `estimate` reads a parameter from the well's own logs: Rw, Archie m, GR endpoints, the clay point, apparent
    matrix, temperature.
  - `check` adds held readings, the parts of bad hole and core depth shift.
  - `classify` adds gas, minerals, flow units, electrofacies and moveable hydrocarbons.
  - `summarize` adds pay with HCPT at any cutoffs.
  - `calibrate` adds the core fit, poro-perm transforms, predicted shear and elastic properties.
- **Every Petrophys function by request.**
  - Each verb takes `search` and `run` over about 300 public Petrophys functions, from a registry generated from
    the installed library.
  - One binder fills each function's inputs: curves by role or name, conditions as masks, the record's numbers, the
    interval's limits.
  - Outputs become curves of the question, values and tables.
- **The record as the default.** Every input not given comes from the record, and each result says where each
  input came from.
- **Tools grouped by request.** The model sees its tools under seven verbs: describe, compare and group, check,
  calculate, classify, summarize, calibrate.
- **Own wells:** a well whose default interpretation sets the porosity cutoff per lithology no longer stops the run.
- **Documentation:** `docs/TOOLS.md`.

## 0.1.1 (2026-10-29)

- **Any chat model.** PetroHarness runs on any chat model behind an OpenAI-compatible endpoint (vLLM, SGLang, Ollama,
  LM Studio or a hosted API):
  - `--model NAME` names the served model, through the packaged generic card;
  - `--model-card FILE` loads a model card with its own request settings (reasoning, sampling, template variables,
    the output cap's name, structured output);
  - K2-Horizon-7B stays the default.

  The command, the web UI, benchmark mode and the Python API take the same options. The endpoints come from
  `PETROHARNESS_MODEL_URL`. The model's name is recorded in `answer.md` and in the trace, and shown in the web UI.
- **Documentation:** a new README, `docs/MODELS.md` (serving, model cards, reasoning models, hosted APIs) and
  `docs/DEVELOPMENT.md` (configuration, benchmark mode, testing, layout).
- **Citation:** the paper (ADIPEC 2026, SPE-236034-MS) in the README and in `CITATION.cff`.

## 0.1.0 (2026-10-29)

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
