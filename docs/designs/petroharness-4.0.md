# PetroHarness 4.0: an open, modular harness for conversations with a well

*   **Author:** sambal shikhar
*   **Status:** Draft
*   **Date:** 2026-11-14

Working name: "4.0" is a placeholder for the version after the 3.5.6 lock. Sources: `feature_concept.md`,
`concepts_brief.md` (review round 1), `concepts_brief_round2.md` (review round 2), `session_design.md`, `decisions.md`.

--------------------------------------------------------------------------------

## Overview

PetroHarness answers a petrophysics question about one interval of one well from its raw LAS file. Petrophys computes,
a language model investigates step by step, and code checks that every number in the answer comes from a result. The
current flow, called FD in this document (the 3.5.6 lock), scores level with or above the 3.5.3 release on the
347-question benchmark for both models it was measured with. Accuracy is therefore not the problem this design solves.

The problem is that the harness is a benchmark runner with one question in and one answer out. It is not yet something
a petrophysicist would keep open all day, and it is not yet something an outside contributor can extend without editing
its core. This design turns it into an open-source product with three properties:

1. **A conversation.** A session on one well and interval takes any follow-up, the way a coding assistant does, and
   keeps its history, evidence and traces so that every turn can be resumed, branched, replayed and audited.
2. **Outputs a petrophysicist can use and check.** Answers that carry plots where a plot says it better than text, the
   settings an answer rests on, uncertainty and sensitivity from Petrophys, an audit trail from each number back to the
   log, and an exportable report.
3. **A modular codebase.** Clear packages with one job each, one place to register a tool, one adapter to Petrophys,
   and data-only plugins that contributors add without touching the core.

The first turn of every session stays FD, byte for byte. That is what lets the benchmark keep guarding accuracy while
everything around the first turn changes.

## The Problem

**1. Nothing carries over between questions.** Each question prepares the well again, investigates from zero and
forgets everything when it ends. A follow-up such as "what if I use a different saturation model?" or "and in the lower
sand?" costs a full run (about 270,000 tokens and several minutes), and it cannot refer to what the previous answer
found. The saved runs in the web UI are separate folders with no link between them.

**2. The answer is text only, and what it rests on is buried.** A porosity distribution or a porosity-permeability
relationship is described in sentences and tables when a histogram or a crossplot would show it at a glance. The methods and parameters behind an answer (formation
water resistivity and where it came from, the saturation model, the cutoffs) are inside the trace, not in front of the
reader. Petrophys can already compute uncertainty (Monte Carlo), sensitivity (cutoff grids, parameter swings,
saturation models side by side) and a dozen plot types, and can run an expert's own workflow recipe. None of that
reaches the user. The link from an answer's sentence to the result it cites exists while the answer is written and is
removed before the answer is saved.

**3. Extending the harness means editing its core.** Adding one tool touches six or more places. Petrophys is imported
from 19 files, some of them reaching into its private modules. About 5,800 lines of code produce text the model reads
without belonging to a versioned prompt component. On the development branch every experiment added a switch and an
`if` branch (28 of them before the lock removed them).

**4. A contributor cannot prove a change is safe.** The proof that a change alters nothing is a replay of recorded
runs. The 36 golden tapes in the repository have been failing since an earlier commit, on version stamps rather than
on behaviour. The stronger check built for the lock (every model request of 1,388 saved runs rebuilt and compared)
lives in a lab folder and needs private benchmark runs.

**5. The repository is not ready to be published.** It has no license file, no contributing guide and no automated
checks on a pull request. Petrophys has all three.

## Goals

Each goal has a test. A goal without a passing test is not done.

*   **G1. An open conversation on one well and interval.** A session accepts any follow-up message. Every message goes
    to the same loop; the model decides what the turn needs (answer from evidence already held, open more, compute with
    another method, draw a figure, or run a full new investigation). Test: the three-turn chat from the owner's example
    (porosity distribution; a different method; saturation against porosity) runs as a scripted session on at least two
    public wells with both models.
*   **G2. Turn 1 is FD, byte for byte.** Test: every model request for the 1,388 saved FD runs, rebuilt through the
    session entry point, is identical to the lock's (the request-hash gate).
*   **G3. History that can be trusted.** One append-only log per session is the single source of truth. Tests: a session
    resumed after turn N builds identical requests for turn N+1; a session replays from its folder with no model
    server; a session branched at turn N shares turns 1 to N with its parent.
*   **G4. Every number can be followed to its source, across turns.** Test: on all 1,388 replays, every number the
    checker accepts has a recorded path (sentence, result, tool call, curve and its generation, Petrophys step, input
    file hash); the numbers it flags are exactly the ones with no path.
*   **G5. Accuracy does not drop.** Steps that change nothing the model sees are proven by G2's gate and are not
    judged. A change the model can see must keep W within 0.8 and RA within 1.3 of FD for each model, on two runs per
    arm paired over the 347 questions. Follow-up answers are measured with a chained benchmark (question B asked as
    turn 2 after question A, against B asked fresh; 286 of the 347 questions have a partner on the same well and
    formation).
*   **G6. Outputs a petrophysicist uses, delivered first where they cannot affect turn 1:** the audit trail with report
    export, a panel of the methods and parameters an answer used, a cutoff grid and a saturation-model table on request,
    and a data-quality checklist. Each has an acceptance test in the Technical Plan. After those: settings the user can
    change, and uncertainty on request.
*   **G7. Answers with plots, where a plot says it better.** Not every question needs one, and benchmark mode never
    draws any. In interactive use an answer can carry figures: a log plot of the interval with its zones, a crossplot
    behind a relationship, a histogram behind a distribution, a depth profile, a Pickett plot behind Rw or m. Petrophys
    draws each figure from the same data as the numbers the answer cites, so a plot and the text cannot disagree, and
    each caption is built from that result. After the answer is written, one more model call sees the answer and the
    cited results that have a plot form, and chooses which to show and where, or none. That call cannot change the
    answer's text, so the text is what benchmark mode would give. From turn 2 on the model also has a plot tool, for
    plots the user asks for directly. Tests: replaying the same model replies with plots on and off gives byte-identical
    answer text; every figure links to a cited result and every number in its caption comes from that result; a
    replayed session draws identical figures; a benchmark run makes no plot call.
*   **G8. A modular codebase.** Packages with one job each, where a package imports only the layers beneath it;
    Petrophys imported from one package; a tool defined in one place (its arguments, how it runs, how its result is
    shown to the model); every text the model reads owned by a versioned component. Tests: an import-contract test over
    the whole source tree; each restructuring commit passes G2's gate.
*   **G9. Contributions without core edits.** A contributor adds a guide pack, a workflow recipe built from Petrophys
    steps, a report template or field notes as data. Each is checked when it loads and fails with a message that says
    what is wrong and how to fix it. Tests: with no plugin enabled, G2's gate passes; a person new to the project adds
    and validates the example guide pack using only the documentation, with no edit under `src/`.
*   **G10. One setup for both models.** The same code and prompts serve K2-Horizon-7B and the 27B model; a setup file
    names the model card. Test: G2 and G5 run for both.
*   **G11. Ready to publish.** A license, a contributing guide, automated checks on every pull request (tests, lint,
    the no-dataset-names check, the gate on a small public set of recorded runs), and install from a package index.
    Test: a clean machine installs it and answers a question on a public sample well by following the README.

## Non-Goals

*   **Multi-well and cross-formation questions.** One well and one interval per session for now.
*   **Lower token use.** Parked: the one arm tested (three prompt-trimming switches) saved 14% of tokens and lost 1.2 W.
*   **Changing how turn 1 answers.** Improvements to FD are welcome later as measured changes; none is part of this
    design.
*   **Sorting follow-ups into kinds.** No classifier and no routing by message type. The model reads the message.
*   **Pausing a run to ask the user.** The harness asks for a parameter only between turns. In benchmark mode it never
    asks: it uses the default and records it.
*   **New science in the harness.** Calculations, methods and custom workflow steps belong in Petrophys or its extension
    packages.
*   **Code plugins from outside the repository in the first release.** The first plugin kinds are data only.
*   **Picking the best of several generated answers.** One answer by construction, as today.
*   **Model training.**
*   **Models that read images.** The models are used as text models. Plots are for the reader; the model asks for a plot
    by naming the result to draw, and never sees the picture.

## Open Questions

*   **Petrophys upstream work.** Five items are needed from Petrophys (a public data-quality report, metadata on step
    parameters, figures rendered to bytes, a step-level uncertainty wrapper, a dependency query). Who does them, and in
    what order beyond "the feature that needs each"?
*   **The form of a follow-up answer.** A short reply or the full report shape: the model's choice, but the writer's
    rules were written for reports. Do short turns keep the settle step and the writer as separate calls?
*   **Summarising a long session.** Code shortens earlier turns from their own structure, so a replay builds the same
    prompt. Should a model-written session summary also exist?
*   **License.** Petrophys is MIT. Is PetroHarness published under MIT as well?
*   **Hosted use.** Is a shared, multi-user deployment (accounts, permissions) wanted for the first release, or local use
    only?

## Critical User Journeys (CUJs)

### CUJ 1: The first question (unchanged from today)

*   **Given**: a LAS file, a formation or depth window, and a model endpoint.
*   **When**: the user asks a question.
*   **Then**: a session starts; the well is prepared once; the answer is the one FD gives today; the session folder
    holds the log, the evidence and the trace.

### CUJ 2: Any follow-up

*   **Given**: a session with at least one answered turn.
*   **When**: the user sends another message, for example "what Rw did you use?", "and in the lower sand?", "what if I
    use Simandoux?", "plot porosity against permeability", or a new question on another topic.
*   **Then**: the model answers using the session's evidence and opens or computes only what is missing; a lookup takes
    one or two model calls, a new topic takes a full investigation; the answer names the settings it used; every number
    in it links to a result from this turn or an earlier one.

### CUJ 3: An answer with plots

*   **Given**: a question whose answer is a distribution, a relationship or a variation with depth, for example "what is
    the porosity distribution in this formation?" or "how does permeability relate to porosity?".
*   **When**: the answer is written.
*   **Then**: the answer shows the histogram, crossplot or depth plot beside the text, drawn by Petrophys from the result
    the text cites; each figure has a caption naming that result; the exported report includes the figures; a question
    where a plot adds nothing gets none.

### CUJ 4: Adopting a setting

*   **Given**: a turn compared two methods.
*   **When**: the user says "use the second one from now on" or clicks "use this".
*   **Then**: a settings change is recorded with who asked and when; later answers use and name the new setting; earlier
    answers are marked as resting on the old one. Without that instruction the settings stay as they were.

### CUJ 5: Checking an answer

*   **Given**: an answer in the UI.
*   **When**: the reviewer selects a number.
*   **Then**: the UI shows the result it came from, the tool call, the curve and the Petrophys step that produced it,
    and the input file; the reviewer exports the answer as a report with its figures and an evidence appendix.

### CUJ 6: How sure is that?

*   **Given**: an answer that reports net pay or average water saturation.
*   **When**: the user asks how sensitive it is, or opens the sensitivity panel.
*   **Then**: Petrophys computes a cutoff grid, a table of saturation models, or P10/P50/P90 from stated parameter
    spreads; the base case equals the number in the answer; the result is stored as evidence with its inputs.

### CUJ 7: Coming back and branching

*   **Given**: a session closed yesterday.
*   **When**: the user reopens it, or branches from turn 3 to try the core-calibrated porosity.
*   **Then**: the session continues with its history and evidence; the branch shares turns 1 to 3 and diverges from
    there; both remain replayable.

### CUJ 8: Standing choices for a field

*   **Given**: a field-notes file with the team's Rw, m and n, cutoffs and preferred methods.
*   **When**: a session starts in that project.
*   **Then**: those choices are the settings in force, each marked as coming from the field notes, and every answer
    names them.

### CUJ 9: A contributor adds a guide pack

*   **Given**: a petrophysicist who knows how to evaluate pay in a tight carbonate and has never read the harness code.
*   **When**: they write the guide as a data file following the documentation and run the validation command.
*   **Then**: the pack loads or fails with a message naming the problem and the fix; with the pack off, the gate shows
    no change; with it on, the trace shows which prompt text came from the pack.

### CUJ 10: An expert brings their own workflow

*   **Given**: a Petrophys workflow recipe with the expert's methods and parameters.
*   **When**: a session starts with that recipe.
*   **Then**: missing inputs are reported before any model call; the investigation runs on the recipe's interpretation;
    the trace records the recipe's hash and the Petrophys version.

### CUJ 11: A maintainer restructures code

*   **Given**: a change that should alter nothing the model sees.
*   **When**: the maintainer runs the gate.
*   **Then**: every recorded request is rebuilt and compared; the change is accepted only when all are identical, and all
    differences are listed when they are not.

### CUJ 12: A benchmark run

*   **Given**: the 347 questions and a model endpoint.
*   **When**: the batch runner starts.
*   **Then**: each question is a one-turn session; nothing is asked of a user and no plot is drawn; answers and traces
    match FD's format, and the settings each answer used are in a separate result field.

## Technical Plan (Architecture)

### 1. What does not change

- **The turn.** One turn is today's FD question graph: read the question, a first look at the well, up to eight
  investigation steps, close, settle, write, check the numbers, repair, finalize. Each model call is still a single call
  rebuilt from stored state. The graph is compiled from a fixed builder that no plugin can reach.
- **The division of work.** Petrophys computes. The model reads, decides and writes. Code keeps the records, builds the
  prompts, runs the tools and checks that every number in an answer comes from a result. Code never changes what the
  model decided.
- **The proof of no change.** A change that should alter nothing the model sees is accepted only when every model
  request for the saved FD runs is rebuilt identically (section 9).

### 2. Two levels of state

Inside a turn the state is FD's and lives in memory, as today. Nothing is checkpointed or retried inside a turn. That
is what keeps turn 1 identical to FD.

Between turns, one append-only log per session is the single source of truth. Everything else is rebuilt from it.

| Holder | What it holds | Lifetime |
|---|---|---|
| Session log | Every event of the session, in order (section 4) | The session; on disk |
| Session state | Small: session id, well key, interval, setup, the list of turns (question, status, answer, cited ids), the settings in force with their sources, the table of curve generations, id counters, the log position | Rebuilt from the log when a session opens |
| Well context | The prepared well, its map and the Petrophys run. Never changed in place. | Built once per session; cached on disk by the hash of the LAS and the data settings |
| Curve generations | Every curve computed during the session (for example a second water saturation), each a new generation that records the call and the settings that made it | The session; values stored as blobs |
| Evidence store | Every result opened, by id (E1, E2, ...), with its call, its turn and the curve generations it read. Ids continue across turns. | A view rebuilt from the log |
| Turn state | FD's state for the turn in progress: the reading, the points, the claims, the step records | One turn; in memory |

A different interval is a new session.

### 3. The three graphs

```text
 user message
      |
 SESSION GRAPH (one LangGraph graph per session; its checkpoint is the log position and small control state)
      |
   open ----------> rebuild session state from the log; build the turn's input
      |                (the earlier-turns block, the settings in force, the evidence index; all empty on turn 1)
      v
   turn ----------> THE TURN GRAPH (FD, frozen), run inside this node
      |                build* -> read -> first look -> [ask -> decide -> act] x up to 8 -> close
      |                -> settle -> write -> verify <-> repair -> finalize      (* build only on turn 1)
      v
   figures -------> interactive mode only: one model call picks plots of cited results, Petrophys draws them
      |                (skipped in benchmark mode; cannot change the answer's text)
      v
   project -------> code only: the settings this answer used, the audit links, the data-quality list
      |
      v
   commit --------> append the turn's events to the log; hand the answer, figures and panels to the UI, CLI or API
```

**The control graph** is the session graph above. Its routes are code: benchmark mode skips `figures`; a failed turn
goes to `commit` with its error recorded. The places where additions attach are the session-level nodes (`open`,
`figures`, `project`), not the inside of a turn. Parallel investigation of independent points is the last phase and
uses fan-out inside the turn with a fixed merge order (section 10, phase 8).

**The evidence graph** is a view built from the log. It is what the audit trail, the UI and the report export read.

- Nodes: an input curve; a curve generation; a Petrophys step run (its parameters with their sources, the Petrophys
  version); a tool call; a result (its E id); a claim; an answer sentence; an artifact (a figure, a table, an
  uncertainty result).
- Links: computed from; read by; cites; shows (a number in a sentence to the row of the result it came from);
  supersedes (a newer generation of a curve); set by (a setting to the user message or file that set it).
- Rule: replaying the log rebuilds the same graph.

**The computation graph** is Petrophys's: each workflow step declares what it needs and what it produces. The harness
reads it through one adapter package. When a setting changes, only the steps downstream of it run again, and their
outputs are new curve generations. The harness's own probing code for these dependencies moves into the adapter until
Petrophys offers a public query for them.

### 4. The session log and the session folder

```text
sessions/<session id>/
  log.jsonl       one event per line: {session, turn, seq, time, type, ...}
  blobs/          large payloads named by their hash: prompts, replies, result values, curve generations
  artifacts/      figures and exported reports
(shared)  well-cache/   prepared wells, by the hash of the LAS and the data settings
```

| Event type | What it records |
|---|---|
| session_start | The well and interval, the hashes of the input files, the setup and its hash, the Petrophys version, the field notes used |
| user_message | The text, and any button action |
| model_call | The stage, the request, the reply, tokens, time |
| tool_call | The call, the value Petrophys returned, the text shown to the model, the curve generations read |
| claim_edit | The claim, its evidence ids, its grade |
| answer | The text, each sentence's links to results, the status of the number check |
| settings_change | The setting, the old and new values, who asked, in which turn |
| artifact | A figure or export: its specification, the results it draws, the file |
| error | What failed and where |

Today's per-question trace, the golden tapes and the UI's saved runs become views of this log. A session resumes by
rebuilding its state from the log, branches by copying the log up to a turn, and replays by answering each recorded
model request with its recorded reply.

### 5. What the model sees on a turn

Every call is rebuilt from session state, with a fixed size limit for each block:

| Block | Turn 1 | Later turns |
|---|---|---|
| The user's message | the question | the new message |
| Session so far | empty | each earlier turn as one entry: the question, the answer's opening conclusion, its settled claims, the ids of the evidence it rests on; older turns shorter, then counted |
| Settings in force | empty (as FD) | each method and parameter with its source, when it differs from the workflow's own |
| The map of the well | as FD | the same map, plus the curve generations made in the session |
| Evidence index | FD's OPENED block | the same block over the whole session; any result is fetched whole with `get` or `find` |
| Field notes | none in benchmark mode | the user's standing choices, when a file is given |

On turn 1 the new blocks are empty strings, so the requests are FD's byte for byte. The earlier-turns block is built by
code from the stored turns, never written by a model, so a replay builds the same prompt. The UI shows it to the user as
"what the model was given from earlier turns".

### 6. How a turn runs

Every message goes to the same loop. There is no list of message kinds. With the session in view, the model's first
step can settle the answer at once from evidence already held, or ask for more: open results, compute with another
method or parameter, draw a plot, or start a full investigation on a new topic. The loop ends by FD's done rule. A
lookup costs one or two calls; a new topic costs a full run.

Two things are adapted for later turns and decided in the implementation plan with their own tests:

- The writer on a later turn is given that turn's results whole, and earlier turns' results by id. Today's writer keeps
  the first 60,000 characters of results in order, which on a later turn would cut the newest ones.
- The form of the answer follows the message: a short reply for a lookup, the report shape for a full question. The
  same number check applies to both.

Computing an alternative never changes the settings in force. The alternative is a new curve generation with a label,
and results name the generation they read. The settings change only on the user's instruction (section 8).

### 7. Tools: one registration

A tool is defined once, in one object: its name, its arguments, the text that describes it to the model, how it runs,
which curves it reads, and how its value is shown to the model. The lists that today live in six places are generated
from these objects. The value Petrophys returns and the text shown to the model are both stored: the text for the
model and the number check, the value for figures, tables and export.

The first version of each definition wraps today's code and must reproduce today's text exactly (the request-hash gate
proves it). New tools arrive as definitions:

- **plot** (later turns, interactive mode): draw a named plot of named curves, zones and depths; the result is an
  evidence item that states what the plot shows, with the figure as its artifact.
- **uncertainty and sensitivity** (later turns): P10/P50/P90 of a reported quantity from stated parameter spreads, a
  cutoff grid, a parameter swing table. Needs a wrapper in Petrophys (section 11).

Tools are never hidden from the model step by step. The one trial of trimming the tool list cost accuracy.

### 8. Settings, field notes and plots

**Settings.** The methods and parameters behind an answer come from the Petrophys step records: each with its value,
unit and source (the LAS header, the workflow, a default, the field notes, or the user in turn N). Every answer carries
the list of settings its cited results depend on: as a header in interactive mode, as a separate result field in
benchmark mode. The user changes a setting by saying so or with a "use this" action. The change is logged, Petrophys
re-runs the downstream steps into new generations, and earlier answers are marked as resting on the old value.

**Field notes.** A data file of a team's standing choices for a field or project (Rw, m and n, cutoffs, preferred
methods, naming). It sets the settings in force at session start, each marked as coming from the field notes. It is
never read in benchmark mode.

**Plots.** Not for every question, and never in benchmark mode.

- A tool definition can say how its result is drawn: statistics as a histogram, a crossplot as a scatter with its fit,
  a profile as a depth plot, zone results as a log plot with the zones marked, a Pickett plot behind Rw or m.
- After the answer is final, the `figures` node lists the plot forms of the results the answer cites and asks the
  model, in one call, which to show and after which part of the answer, or none. Code places them. The answer's text
  is not passed back through the model, so it cannot change.
- Petrophys draws each figure from the same curve generations and the same selection as the cited result. The caption
  is built by code from that result (what is plotted, the interval, the sample count, the key numbers, the result id).
- Drawing runs in a separate process, because Petrophys's plot styling is a process-wide setting. A figure is
  identified by its specification and the hashes of its data, which is what a replay compares.
- On later turns the model can also call the plot tool for a plot the user asks for directly.

### 9. How every change is proven

| Gate | What it proves | When it runs |
|---|---|---|
| Request-hash gate | For all 1,388 saved FD runs, every model request rebuilt from the recorded replies is identical, compared where the request leaves for the model server; every difference is listed; run with 1 and 12 workers | Every change that should alter nothing the model sees |
| Golden tapes | Recorded questions replay with the same requests, answer and trace; behaviour and version stamps are judged separately | Every commit |
| Public mini set | A few recorded questions on a Petrophys sample well replay with no model server | Every pull request, on a contributor's machine too |
| Scripted sessions | Recorded multi-turn sessions on public wells replay byte for byte; a session resumed after turn N builds the same turn N+1 | Every change to the session, the log or later-turn prompts |
| Plugin gate | With a plugin installed but off, the request-hash gate passes; with it on, the changed calls are listed and attributed to it | Every plugin |
| Accuracy A/B | Both models, two runs per arm, paired over the 347 questions; W within 0.8 and RA within 1.3 of FD | Every change the model can see on turn 1 |
| Chained benchmark | Question B as turn 2 after question A, against B asked fresh | Follow-up quality |

After each promoted change to behaviour, the promoted runs become the new reference set for the request-hash gate.

### 10. The order of work

Each phase ends with its gates passing. Phases 0 to 4 change nothing the model sees on turn 1.

| Phase | What is built | What a user gets | Gates |
|---|---|---|---|
| 0. Close the lock, harden the proof | Commit the lock; move the request-hash gate into the repository and extend it (the second repair round, the client boundary, retry paths with a stub model, all differences listed); judge tapes on behaviour and stamps separately; the public mini set; license, contributing guide, pull-request checks | A published 3.5.6 that anyone can install and verify | Gate identical twice; a deliberately broken copy fails it |
| 1. Record what features need | Keep each sentence's links to results; record number-to-row matches and the step parameters with their sources; build the evidence graph from the trace | Nothing visible yet | Request-hash gate |
| 2. Outputs that cannot affect an answer | Audit trail and report export; the settings panel; the cutoff grid and saturation-model table on request; the data-quality checklist; the `figures` node and its plots | Answers with plots, a checkable audit trail, a report, sensitivity in seconds | Request-hash gate; each feature's test (section 12) |
| 3. The modular rework | One setup object and run context; one model client wrapper; tool definitions; every model-facing text into a versioned component; the Petrophys adapter; the session, well and turn state split; the package moves of section 13 | The same product on a codebase a contributor can read | Request-hash gate on every commit, through the old and the new entry point |
| 4. The log as the source of truth | Write the log alongside today's files, then make the trace, tapes, UI feed and evidence store views of it; resume as a rebuild | Sessions that survive a restart | The trace rebuilt from the log equals today's on all 1,388 runs; stop-and-resume test |
| 5. The conversation | The session graph, the earlier-turns block, settings in force, curve generations, the later-turn writer scope, the plot tool, field notes, the session timeline in the UI | Follow-ups on a well: anything the user asks | Request-hash gate on turn 1; scripted sessions on both models; the chained benchmark |
| 6. Changes the model can see | Uncertainty as a tool; the data-quality facts given to the writer; a guide pack in the default setup; a newer Petrophys function list | "How sure is that?" inside the conversation | Accuracy A/B for each |
| 7. Contributions | Guide packs chosen by setup; workflow recipes; report templates; commands to create and check a plugin; the plugin guide with one worked example of each kind | An expert adds a pack or a recipe without touching the core | Plugin gate; a clean-repository check |
| 8. Parallel parts | First the read-only actions of one step run together; then independent points as branches with a fixed merge order | Shorter waits on multi-part questions | Request-hash gate under random delays; then scripted sessions and an accuracy A/B |

**Build order.** The conversation is the feature the owner asked for first, and it should show where the module
boundaries belong before the layout is fixed. So the phases are built in this order: 0; 1; the parts of 3 that sessions
need (the setup object, the tape verdict split, the state split); 4; 5; 2 alongside (its outputs read the same log);
then the remaining moves of 3; then 6, 7 and 8. The cost is that session code is written against files that later
move, and those moves are proven again by the request-hash gate. (Decision T14, taken by the planner on the owner's
instruction to proceed on best judgement, 2026-11-14.)

### 11. What Petrophys needs to provide

In parallel, each as a Petrophys release that the request-hash gate checks before the harness adopts it:

- units, valid ranges and "what this affects" for every step parameter (for the settings panel and for asking);
- a public data-quality report (for the checklist);
- plots that take arrays or a copy of the well and return image bytes (for figures);
- a step-level uncertainty and sensitivity wrapper with a seed and stated default spreads (for "how sure is that?");
- a public query for step dependencies (for re-running only what a setting affects);
- recipes that load from a file with their version (already present as `Workflow.to_dict`).

The list of Petrophys functions is part of every first-turn prompt today. A setup therefore pins a snapshot of that
list, so that adding a function to Petrophys does not change the benchmark's prompts until the snapshot is updated on
purpose.

### 12. Acceptance tests for the features

| Feature | Test |
|---|---|
| Audit trail and export | On all 1,388 replays every number the checker accepts has a path to its result, call, curve generation, step and input file; the export is identical over two replays |
| Settings panel | Every row comes from a step record or a named default; only settings the cited results depend on are listed; no dataset or profile name appears |
| Cutoff grid, saturation-model table | The base case equals the number in the answer; the log shows no model call |
| Data-quality checklist | A washout injected into a copy of a public LAS is listed with its depths; a clean interval lists none |
| Plots | Replaying the same replies with plots on and off gives identical answer text; every figure links to a cited result; caption numbers come from that result; a replay draws the same figure specifications |
| Follow-ups | The three-turn example runs on two public wells with both models and replays byte for byte; a later turn that computes a second saturation cites the new generation everywhere except in a stated before-and-after; resuming after turn 2 gives identical turn-3 requests |
| Changing a setting | The answer header names the new value and who set it; only downstream steps re-ran; the earlier answer is marked |
| Uncertainty | P10 <= P50 <= P90; zero spread gives the deterministic value; the same seed gives the same numbers |
| Guide packs, recipes | Off: request-hash gate identical. A faulty pack fails with what is wrong and how to fix it. A recipe with a missing input reports it before any model call |

### 13. Target layout

Each package has one job and imports only the packages listed above it.

```text
src/petroharness/
  api/        the public contracts: turn input and result, evidence reference, setting, artifact, event,
              tool definition, plugin manifest
  core/       the setup (one flat, hashed, printable object), the run context, the model client wrapper,
              id counters, the prompt-component registry
  log/        the session log, the blob store, the views built from it (trace, tape, UI feed), rebuild and replay
  petro/      the only package that imports Petrophys: preparing the well, running steps, the step catalogue and
              dependencies, the pinned function list, recipes, drawing figures, uncertainty and sensitivity
  well/       the interval view, formations, tops, statistics (unchanged)
  record/     the workflow record, catalogue, sections, inventory
  tools/      the tool definitions and the engine that runs them
  evidence/   the evidence store, curve generations, claims, the number check, the evidence graph
  turn/       the FD question graph, frozen: the investigation, the writer, the prompt components
  session/    the session graph, session state, settings and field notes, the earlier-turns block
  plugins/    loaders and checks for guide packs, recipes, report templates
  surfaces/   the command line, the Python entry point, the web UI, report export, the panels
  resources/  policy, rules, topics, model cards (data only)
tests/gate/   the request-hash gate, the tape recorder, the scripted-session runner, the public mini set
```

The benchmark runner and the judge wrappers move out of the package into a separate evaluation tool.

## Implementation Status

Updated 2026-11-15. "Gate" below means the request gate of section 9 on the saved runs of the reference runs.

### Built

| Part of the plan | What exists | Proof |
|---|---|---|
| The 3.5.6 lock (phase 0) | The measured build as the code, golden tapes, version, changelog, lock record, smoke on both models | Gate 1,388 of 1,388; suite 1,424 passed; `docs/LOCK_v3.5.6.md` |
| The control graph (section 3) | The session graph `open -> turn -> project -> figures -> commit` and the later-question graph with the reply route, both LangGraph, both with blueprints kept equal to the code | Gate 1,388 of 1,388; blueprint tests; a live conversation and a live web UI run with a follow-up |
| The session log (section 4) | One append-only log per conversation with blobs by hash; resume rebuilds the session by opening the recorded results again | tests/session |
| What the model sees on a later question (section 5) | The earlier-questions block built by code from the log; the later writer reads its own results and the earlier ones its claims cite | tests/session; live conversations on both models |
| The evidence graph (section 3) | Rebuilt from the log alone: LAS file, curves, steps, questions, results, claims, answers, figures and their links; `petroharness audit` | tests/evidence |
| Settings behind an answer (section 8) | The methods and parameters an answer rests on, read from the record | tests/basis |
| Plots (section 8) | Petrophys draws; the model chooses; the harness binds the interval's well, the zones and the numbers | tests/figures; live |
| The setup object (section 13, `core/`) | One flat hashed record, printed by `petroharness setup`, logged per conversation | tests/core |
| The gates in the repository (section 9) | `tests/gate`: the request gate as a tool; the public mini set (three questions on a Petrophys sample well, 31 model calls) with its recorder | The tool reproduces the lab baseline on one run set; the mini set replays with no server and no private data, and fails on one changed word of a prompt, naming the call |
| Contributor readiness (phase 0) | CONTRIBUTING.md, CI workflow, the repository's lint configuration | Lint clean |
| One tool registration (section 7) | Each tool is one `Tool` (`tools/spec.py`) in `agent/toolset.py`: its function, arguments, description, group and listing; every list of tools is read from the definitions | Gate 1,388 of 1,388; the brief, schemas and listings compared equal before and after |
| The direct route (not in the plan; see below) | The model says in READ whether a question is direct; a direct question takes up to two look steps and a short answer, and a look step or the writer can hand it to an investigation. For every question, a user's and a benchmark's; `--investigate` keeps the 3.5.6 route | Two runs per model on 347 questions: K2-Horizon-7B W 67.03 against 66.67, Qwen3.5-27B GRPO 66.57 against 66.23; gate: `--investigate` 1,388 of 1,388 against 3.5.6 |
| Report export (phase 2) | `petroharness report SESSION`: a conversation as one document; the web UI links each answer's audit trail | tests/evidence; live |

### Differences from the plan as written

- **Session graph order.** Built as `open, turn, project, figures, commit`: the projections come before the figures
  because the figure candidates read them.
- **Drawing in process.** The plan put drawing in a separate process. Petrophys' plots are drawn in process, one at a
  time under a lock, each figure closed once saved.
- **A reply length route.** Not in the plan. A later question's answer length is the model's choice (brief or full)
  and routes to its own writer node. Measured on 20 follow-ups: chosen in 3 of 10 simple questions; the answer is then
  about a quarter of the length; the cost of the question does not change, because the investigation is the cost.
- **The public mini set** replays a whole conversation (first question, later questions, figures, audit trail), which
  also serves as the scripted-session gate.
- **The direct route.** Not in the plan, which kept the first question as 3.5.6 answered it. A question the model reads
  as direct (a value, a setting, a count) skips the investigation: three to four model calls instead of nine to
  twelve, about a quarter of the tokens, under a minute on an idle K2-Horizon-7B server. Measured on the whole
  benchmark before it became the default. Thinking is not reduced on it: reducing it in the look steps cost about 7
  points of reference alignment on both models and saved no time. The gate's base is now the reference runs of this
  route; the 3.5.6 route keeps its own base.

### Not built yet

| Part of the plan | Status |
|---|---|
| One model client wrapper with observers (section 13) | Not started: the tape, the attribution and the UI progress still wrap a call separately |
| The log as the only source of truth (phase 4) | Partly: the trace and the tape of each question are still written as files of their own |
| Changing a setting, curve generations, field notes (section 8) | Not started |
| Data-quality check list, sensitivity tables (phase 2) | Not started. A sensitivity question is answered by the `what_if` verb in a conversation; the check list waits for a public data-quality report in Petrophys (section 11) |
| Uncertainty as a tool, data-quality facts to the writer (phase 6) | Not started; each needs an accuracy A/B |
| Guide packs chosen by setup, recipes, plugin commands (phase 7) | Not started |
| Parallel parts (phase 8) | Not started |
| The target package layout (section 13) | New code is in `session/`, `evidence/`, `core/`; the existing packages have not moved |
| Follow-up quality | Measured on the code before the direct route (each benchmark question asked second in a conversation, against asked fresh): K2-Horizon-7B W +0.17 (level), Qwen3.5-27B GRPO W -1.11. A lookup follow-up now takes the direct route |

## Alternatives Considered

### Alternative A: Sort each follow-up into a kind and route by it

*   **Pros**: A lookup, a what-if and a new question would each take a short, fixed path; easy to test path by path.
*   **Cons**: Users ask things that fit no list. A wrong label sends the message down the wrong path.
*   **Reason for Rejection**: Rejected by author: a session must work like a coding assistant, where the user can ask
    anything and the model decides what the turn needs.

### Alternative B: One long conversation in the model's context, compacted when it grows

*   **Pros**: How coding assistants work; no code needed to decide what to show the model.
*   **Cons**: Prompts grow with the session; a compacted summary is model-written text that nothing checks; a replay no
    longer builds the same prompt; it drops the rule that each step is a single call rebuilt from state.
*   **Reason for Rejection**: Rejected by author: the evidence store outside the model's context already gives the model
    everything by id, and it keeps replay exact.

### Alternative C: Pause a run to ask the user for a parameter

*   **Pros**: The harness could ask at the moment a missing parameter matters.
*   **Cons**: LangGraph re-runs a paused node from its start, and the turn's working state cannot be checkpointed; a
    paused run also holds a worker.
*   **Reason for Rejection**: Rejected by author: the harness states the default it used and the user changes it in the
    next message.

### Alternative D: Every specialist as its own subgraph and plugin unit

*   **Pros**: A uniform way to add data quality, figures, uncertainty and report writers.
*   **Cons**: None of them makes a decision a model has to make; they are Petrophys calls and views of the log. A graph
    node with no state or rule of its own adds ceremony.
*   **Reason for Rejection**: Rejected by author: they are code functions at the session-level nodes; only the writer
    is a subgraph, and it already is one.

### Alternative E: Show the model fewer tools or a shorter map on later steps

*   **Pros**: 14% fewer tokens per question in the one arm tested.
*   **Cons**: That arm lost 1.6 RA and 1.2 W on two paired runs.
*   **Reason for Rejection**: Rejected by author: token work is parked; tools are never hidden step by step.

### Alternative F: Code plugins from outside the repository in the first release

*   **Pros**: Contributors could add checks, tools and views directly.
*   **Cons**: Outside code would need trust rules, an import contract and conformance tests before it could run next to
    the benchmark path; a plugin that changes prompts changes accuracy.
*   **Reason for Rejection**: Rejected by author: the first plugin kinds are data only; new science goes into Petrophys.

### Alternative G: Do the whole rework before any feature, or never do it

*   **Pros**: Rework first gives new features a clean home. No rework is the least effort.
*   **Cons**: Rework first delays everything a user can see by months. No rework leaves a core that outside contributors
    must edit.
*   **Reason for Rejection**: Rejected by author: the full layout is the end state, reached after the conversation and
    the first outputs exist.

### Alternative H: Let the model ask for plots during the first turn's investigation

*   **Pros**: The model could choose a plot while it reasons.
*   **Cons**: It changes the first turn's prompts, so the benchmark would no longer measure what users run.
*   **Reason for Rejection**: Rejected by author: plots are chosen in one call after the answer is final, and by a tool
    only on later turns; benchmark mode draws none.

--------------------------------------------------------------------------------

## Non-Functional Requirements

*   **Reproducibility.** Every session replays from its folder with no model server. Every trace records the setup hash,
    the Petrophys version and the hashes of the input files.
*   **Privacy.** A session folder holds the user's well data and questions. Nothing is sent anywhere except the model
    endpoint the user configured. Hosted tracing stays refused, as today.
*   **Performance.** Opening a session prepares the well once; later turns start without that wait. Drawing runs in a
    separate process so that one figure cannot disturb another run's styling.
*   **Rollback.** Every new behaviour is reachable only through the session entry and interactive mode. The benchmark
    path is the turn graph, proven identical by the gate at every step, so any phase can be reverted without touching
    measured behaviour.
