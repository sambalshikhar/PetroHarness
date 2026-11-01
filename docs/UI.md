# Web UI

`petroharness ui` serves a page where you ask about a LAS file in the browser: choose the well, the interval and the
question, follow the investigation as it happens, then read the answer with the claims, the results and the record
behind it. Every run is saved, so you can come back to it, rate it and replay it. The page asks the same harness as
the `petroharness` command (`petroharness.ask`), with the same inputs, and changes no prompt.

## Start it

```bash
export PETROHARNESS_MODEL_URL=http://host-a:8100/v1     # the model servers; several: comma-separated
petroharness ui                                         # http://127.0.0.1:7860
```

The server needs nothing beyond the package (it uses the Python standard library). It prints where it listens, the
runs folder and the model endpoints, and runs until you stop it (Ctrl+C).

| option | meaning |
|---|---|
| `--host ADDRESS` | where to listen (default `127.0.0.1`, this machine only); `localhost` listens on both `127.0.0.1` and `::1`; `0.0.0.0` on every interface, so anyone who can reach the port can ask questions and read the saved runs |
| `--port N` | the port (default 7860) |
| `--runs DIR` | the folder for saved runs and uploads (default `./petroharness-ui-runs`) |
| `--workers N` | questions answered at once (default 4); more wait in a queue |
| `--model NAME` | any chat model, by its served name (default: K2-Horizon-7B; [MODELS.md](MODELS.md)) |
| `--model-card CARD` | a model card: a YAML file or a packaged card's name |
| `--model-url URLS` | the model endpoints, comma-separated (default `PETROHARNESS_MODEL_URL`) |

As for the command, a data settings file in `PETROHARNESS_DATA` is the base the settings start from, and
`PETROHARNESS_SKILLS` chooses the default skill library; unset them to ask about a new well with the defaults.

## Open it from another machine

The server listens on `127.0.0.1` by default. When it runs on a remote machine, forward the port:

- **SSH:** `ssh -L 7860:localhost:7860 HOST`, then open http://localhost:7860 on your own machine.
- **Your editor's port forwarding:** in VS Code, *Ports* → *Forward a Port* → `7860` (it often offers the port by
  itself once the server prints its address), then open http://localhost:7860.

## Asking a question

The panel on the left (the menu button shows or hides it):

1. **Well (LAS file).** A path on the server (*Load*), or *Upload a LAS…* from your machine. Once a file is chosen,
   the page shows its header: the well's name, the depth range and unit, the depth step, the samples and every curve
   (hover a curve for its unit and description; curves that look like a lithology log are marked).
2. **Interval.** One of:
   - **Whole well** (the default): from the log's first sample to its last. Near the top of a log, often behind
     casing, only some curves may be recorded, and porosity and saturation there are not meaningful: a named
     interval gets a more focused and more reliable answer.
   - **Formation (tops):** a tops file (a path, or *Upload a tops file…*), then a formation from the names the tops
     reader finds in it, each with the interval it would use (its top to its stated base, else to the next deeper
     top, else to the end of the log). A table with a well column is read for this well only. A name the file lists
     twice (a repeated section) cannot be chosen: ask about it by its depths. When the file states no depth unit,
     choose it (default: the LAS file's).
   - **Depths:** a top and a base (both included), their unit (default: the LAS file's) and an optional name. An
     empty top starts at the top of the log, an empty base runs to its end.
3. **Question,** in your own words. *Ask* (or Ctrl+Enter) sends it.
4. **More options** (all optional): the lithology curve (default: detected; with none, the zones are shale-volume
   bands), the formation's lithology as you know it (it reaches the model with the question, marked as your
   statement), a Petrophys context profile (for wells of a known context package), the skill library (the packaged
   one, none, or a library folder) and the investigation's step cap.

What is wrong in the inputs (a missing file, a formation the tops file lacks, a base above the top) is said at once,
with what to change, before the question waits for a worker.

## Following a run

The run's header shows the question, its status (queued, running, done, error), the LAS file, the interval, the time
so far and the model endpoint, with a bar of its phases: queue, interpret the well, read the question, investigate,
settle the claims, write, check. While all workers are busy, a new question shows its place in the queue.

## Reading the answer

**Interpretation** (the page a run opens on) tells the run as a petrophysicist reads a report, conclusion first:

1. **The answer:** its opening sentences, the number of findings by confidence, the results computed, and the
   checker's outcome (every number in the answer traced to a computed result, or not).
2. **The well:** the interval as Petrophys interpreted it, as a log plot (gamma ray, resistivity, density and neutron,
   shale volume, porosity, water saturation, permeability, the pay flags, the lithology column and the zones), and the
   zone table; the zones the answer names most are marked.
3. **How the answer was reached:** the parts the model split the question into, each with its findings. A finding
   gives its confidence and its reading, a chart of the zone values it rests on for each curve it names (with the
   net-pay step's cutoff, and the zones it names marked), why it matters and what could change it, and a link to the
   computed results it rests on. While the run goes on, the parts fill in with the model's working readings.
4. **What limits this answer**, from the answer's own limitations.
5. **The whole written answer**, section by section (the long ones folded to their opening lines and tables). Click a
   number to see every computed result line that shows it, and a zone to find it on the logs. Then rate the answer
   (good, partly or wrong) with a note.

The other tabs hold the detail behind it:

- **Well logs:** the full plot, track by track, each curve marked measured (LAS) or computed by Petrophys and shown on
  its conventional scale (else the range of its values). Move over the logs to read every curve at a depth; click a
  zone, or a row of the zone table, to pick it; zoom 2x or 4x.
- **Evidence:** by question part, each claim with its grade, what it means, what weakens it, the code's checks and the
  results it rests on, opened under it; *All results* lists every result the model read, laid out as tables (or as
  the text the model read), with a filter by curve, zone or word.
- **Investigation log:** the run as it happened, for audit: a strip of every stage (each step with the results it
  opened and the claims it added or revised), then each stage as a card: the well, the question as read, the first
  look, each step (its focus, what it looked at in plain words, the results it opened, its claims, any harness note),
  the settle step, the writer and the checker's rounds.
- **Details:** the run in numbers (steps, model calls, tokens, time); the interval and its zones; the topics, the
  named measurements and the skills used; the data settings and the Petrophys version; each model call's usage; the
  checker's rounds; the inputs.

`answer.md` and `trace.json` (the full record) can be opened from the run's header.

## Saved runs

Each run is a folder in the runs folder:

| file | what it holds |
|---|---|
| `<run id>/run.json` | the inputs, every live event, the answer, what the page shows of the trace, the rating |
| `<run id>/answer.md` | the answer with its header, as the command writes it |
| `<run id>/trace.json` | the full trace, as the command writes it |
| `uploads/` | the uploaded LAS and tops files |
| `.cache/` | the interpreted wells, shared by every run |

The **Runs** tab lists them, newest first, with their status and rating; filter by any word. *Ask again or edit*
puts a run's inputs back in the form. Runs a stopped server left unfinished are marked interrupted when it starts
again.

**Replay.** A finished run's *Replay* (or the address `#replay=<run id>&speed=8`) plays the run again from its saved
events, `speed` times faster: the READ, each step with its actions and results, the settle step, the writer and the
checker, then the answer. Nothing is recomputed and no model is called, so it works with the model servers down. In
the browser console, `__replay.open(id, 0)` then `__replay.seek(t)` shows the run as it stood `t` seconds in.

## Model endpoints and the queue

The top bar names the model (its card's label, or `--model`). The dots are the model endpoints, green when one answers
`/v1/models` with the model the harness asks for (hover for its address and how many questions it is answering). Each question goes to the least busy
endpoint that answers; `--workers` questions run at once, and the top bar counts the ones running and waiting.

## The API

The page uses a small JSON API, which also serves scripts:

| request | what it does |
|---|---|
| `GET /api/config` | the endpoints and their health, workers, queue, defaults, topic areas, context profiles, each tool's group |
| `GET /api/las?path=P` | a LAS file's header |
| `GET /api/tops?path=P&las=L[&unit=m]` | the formations a tops file names, with the interval each would use |
| `POST /api/upload?kind=las\|tops` | the file's bytes, its name in the `X-Filename` header; returns its path |
| `POST /api/ask` | the inputs (below); returns the run id |
| `GET /api/job/ID?since=N` | the status and the events from N on (each model call, the results the model read, the interval's logs once Petrophys has read the well); the answer and the result when done |
| `GET /api/runs` | the runs, newest first |
| `GET /api/run/ID` | a run in full; `/api/run/ID/answer.md` and `/api/run/ID/trace.json` its files |
| `POST /api/rate/ID` | `{"verdict": "good" \| "partly" \| "wrong", "note": "..."}` |

```bash
curl -s -X POST localhost:7860/api/ask -H 'Content-Type: application/json' -d '{
  "las": "/data/wells/tuhua-7.las",
  "question": "What are the porosity and water saturation in this formation?",
  "interval": {"mode": "tops", "tops": "/data/wells/formations_tuhua-7.csv", "formation": "Mount Messenger"}}'
```

`interval` is `{"mode": "whole"}` (the default), `{"mode": "tops", "tops": PATH, "formation": NAME[, "unit": "m"]}`
or `{"mode": "depths", "top": D, "base": D[, "unit": "ft"][, "name": LABEL]}`; the other inputs are
`lithology_curve`, `formation_lithology`, `profile`, `skills` (`default`, `none` or a folder) and `max_steps`.
