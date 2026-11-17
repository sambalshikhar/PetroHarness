# The question graph

The harness answers a question as a LangGraph state graph. This file is its blueprint: every node, state field and
route below exists in `src/petroharness/agent/graph.py` under the same name. `docs/graph.mmd` is the graph drawn
from the code, and `tests/agent/test_graph_flow.py` keeps both files equal to the code.

## Why a graph

- **Branches and retries:** a step can be unreadable and skipped, refused as done, converged, or capped; the answer
  can go round the repair loop.
- **State worth keeping:** each step's record, the claims, and what was opened.
- **Verifiable results:** the claims' done rule and the writer's number check are code, and they route.
- **Independent units:** questions, run as a batch.

Each stopping decision is a route that can be read, tested and logged on its own.

## Run context and state

**Run context** (`Run`, one per question, private to the nodes; never part of a state update):
- the inputs, set once: `task`, `cfg`, `llm`, `usage`, `writer`, `fmt`, and the token caps `max_tokens` and
  `max_tokens_writer`. No evaluation label is among them: the model's topics come from the `read` node;
- the domain state, changed in place by the nodes: `session` (the interval, the ledger, the claims, the points and
  the model's topics) and `trace` (the record of the run);
- prompt pieces built once by a node and reused: `system`, `head`, `first_look` (by `first_look`), `w_messages` and
  `w_table` (by `write`).

The domain state lives outside the graph state on purpose. A checkpoint cannot restore it, and a node must not be
retried, so the tapes, not LangGraph's checkpoints, are how a run is reproduced.

**State** is the control data that routes, and each step's scratch:

| field | merge | meaning |
|---|---|---|
| `k`, `max_steps` | overwrite | the step being taken (1..max_steps); the cap (default 8) |
| `new` | overwrite | NEW: what the last actions returned, shown in the next step |
| `shown_new` | overwrite | ids the last step's NEW shows whole (left out of OPENED's digests) |
| `withheld` | overwrite | ids the last step opened or asked again that NEW's budget left out: first in the next step's NEW |
| `guides_new` | overwrite | the guides the last step read: whole in the next prompt's GUIDES block, short after that |
| `refused`, `polish` | overwrite | done refused once by the done rule; steps in a row that only rephrased a settled answer |
| `text`, `user`, `reply`, `call_errors` | overwrite | this step's reply as recorded, its prompt, its step object (None: unreadable), call messages |
| `rec` | overwrite | this step's record |
| `steps` | append | the step records |
| `acts`, `notes`, `msgs`, `raw_edits`, `settled_before` | overwrite | `decide`'s hand-off to `act` |
| `finished` | overwrite | the investigation ended at `decide` or `act` |
| `draft` | overwrite | the writer's draft |
| `rounds` | append | the checker's rounds |
| `answer`, `status` | overwrite | the final answer and its status |

## Nodes

| node | kind | does |
|---|---|---|
| `build` | code | `Session.build`: the well prepared, the interval view, the workflow store, the inventory; the map |
| `read` | model | the READ call: one schema-guided call (one retry when unreadable) in which the model chooses the question's topic areas, most important first, and lists the measurements it names; the map's notes follow the topics' families |
| `first_look` | code | the note of what the question names that this well's record lacks; the key curves of the model's topics, the curves its READ reply names and the interval's reservoir curves, each with its core-calibrated twin where the record holds one (each zone, the zones pooled and the whole interval, with the default statistics), before step 1 |
| `look` | model | the direct route's step ("The direct route" below; off with `--investigate`): one call that says the opened results state what is asked, or names up to 4 lookups, which run into the ledger; no points and no claims. A reply that asks for an investigation, or cannot be read, starts the investigation |
| `ask` | model | build step k's prompt from the state (GUIDES with the guides read, the last step's whole and the earlier ones short, before NEW); one call (one retry after an empty reply); read the reply. The protocol is JSON (`parse`: read, salvage, or the model fixes its own syntax) |
| `skip` | code | an unreadable reply: the step is recorded, and NEW says so |
| `plan` | code (+ model once) | step 1 only: what the question asks, the points, the intent, the claims. One extra call when the reply's edits number points it does not list |
| `decide` | code | apply the claim edits; read the actions; a guide read the first time opens what bears on the READ's first topic: its sections of that topic's families and, for a guide on that topic, the workflow curves it names (no topics: nothing; with no skill library a guide call is said back as not run); the done check |
| `act` | code | run the actions into the ledger; build NEW within its budget from results only: the results the last step withheld first, a call opened before and a `get` without a term shown whole again, a result that does not fit withheld for the next step; a guide read goes to GUIDES, outside NEW; the convergence check |
| `close` | code | the investigation's record (steps, points, opened, claims) |
| `no_answer` | code | the question fails: step 1 was unreadable, so there are no claims to write from |
| `settle` | model | the final step with every opened result; the claims made final |
| `write` | model | the writer's draft from the settled claims, every opened result (the results decide where they differ), the provenance card of the curves they name, the zone table and the map; a retry after an empty reply, and the working-notes check |
| `write_brief` | model | the short answer of a direct question (and, in the later-question graph, of a later question the model chose to answer briefly): the writer's call under the short brief, with no zone table; the checker and the repair rounds follow as for `write`. A direct question's writer may hand the question to an investigation instead of answering, where the results do not state what is asked |
| `verify` | code | the checker: numbers no result (or the card, the map, the zone table, the question) shows, words about the process, statements the record contradicts, working notes left in the text |
| `repair` | model | one repair round on the checker's findings (at most two with the `open` writer, one otherwise) |
| `finalize` | code | the draft kept in the trace; the answer delivered from it (`delivered`: the zone table placed, evidence ids out, numbers as the results show them); the status |

## The direct route

Every question can take this route: a user's (`petroharness`, `petroharness chat`, the web UI) and a benchmark's.
The READ call also says what kind of answer the question asks for: `direct` for a value, a setting, a count, a depth
or a yes or no that one or two lookups will state, `investigate` for an interpretation that takes several results
weighed together. The decision is the model's; the graph carries it. `--investigate` (the command, chat, benchmark
mode; `direct=False` in Python; "A full investigation for every question" in the web UI) leaves the route out of the
READ call, and every question gets the investigation, a route the request gate proves unchanged.

| | An investigation | A direct question |
|---|---|---|
| Thinking | the model card's normal setting | the same: every call thinks as the card says |
| Steps | up to 8, with points and claims | up to 2 `look` steps of at most 4 lookups |
| Settle | one call | none |
| Answer | the report form | the short form: the answer first, then only what it rests on |
| Check | every number traced to a result; repairs | the same |

What a direct question saves is the route: no points, no claims, no settle call, a short answer. Every call on it
thinks as the model card says. Thinking was reduced in the `look` steps at first (the lowest effort, or thinking
off) and measured on both models: the direct answers lost about 7 points of reference alignment, because the step
stopped at a result near what was asked or chose a weaker lookup, and no time was saved that could be measured. A
writer at the lowest effort was seen to deny a fact its results stated.

A direct question can still get an investigation, which then starts from its own step 1 with the results already
open. Three things send it there: a `look` reply that asks for it, a `look` reply that cannot be read (or whose
lookups cannot be read), and the writer: where the results do not state what is asked, and do not show why it
cannot be had, the writer replies with the one word INVESTIGATE instead of an answer, so a value is called missing
only after an investigation has looked for it.

The writer reads every result the `look` steps were shown: the ones they opened, and on a later question of a
conversation the earlier questions' results they read again (a short answer has no claims to cite them by).

The model never judges its own completion. `decide` (the claims' done rule) and `verify` (the number check) are code,
and they route.

## Routes

| after | condition | to |
|---|---|---|
| `build` | always | `read` |
| `read` | always | `first_look` |
| `first_look` | `after_first_look`: the READ call read the question as direct | `look`, else `ask` |
| `look` | `after_look`: done, nothing to open, or the last look step | `close` |
| `look` | the reply asks for an investigation, or cannot be read | `ask` (the investigation's step 1, at normal thinking) |
| `look` | otherwise | `look` (k+1; NEW shows what was opened) |
| `ask` | reply unreadable | `skip` |
| `skip` | the skipped step was step 1, or the last step | `close` |
| `skip` | otherwise | `ask` (k+1; NEW says the reply could not be read) |
| `ask` | readable and k = 1 | `plan` |
| `ask` | readable and k > 1 | `decide` |
| `plan` | always | `decide` |
| `decide` | done, no actions or last step, and (done rule holds, done already refused once, or last step) | `close` |
| `decide` | otherwise | `act` (when done was refused: NEW says why, and the actions are dropped if the model set done) |
| `act` | converged (POLISH_STEPS steps in a row only rephrased) | `close` |
| `act` | otherwise | `ask` (k+1; `decide` always ends the last step, so `act` never runs at k = max_steps) |
| `close` | no answer state (step 1 unreadable) | `no_answer` |
| `close` | a direct question | `write_brief` |
| `close` | claims and opened results exist | `settle` |
| `close` | otherwise | `write` |
| `settle` | always | `write` |
| `write` | always | `verify` |
| `write_brief` | `after_write_brief`: a direct question its writer handed to an investigation | `ask`, else `verify` |
| `verify` | issues, rounds left, draft not empty | `repair` |
| `verify` | otherwise | `finalize` |
| `repair` | the repaired draft was kept (60% of the draft or shorter, or empty) | `finalize` |
| `repair` | accepted | `verify` |
| `finalize` | always | END |

## Reproducing a run: tapes

What the model sees is logged, so a run can be reconstructed from its log.
- **Record.** `petroharness.tape` records every model request and reply of a run. `tests/agent/record_golden.py
  live` records the golden questions (`tests/golden/`) from the servers.
- **Replay.** `tests/agent/test_golden_tapes.py` reruns each golden question through the graph from its tape, with no
  server. Every request must equal the recorded one field by field: the same prompts, in the same order, with the same
  parameters. The answer, the status and the trace (timings aside) must also equal the recording.
- A change to a node that should not alter behaviour is accepted only when every tape replays.
