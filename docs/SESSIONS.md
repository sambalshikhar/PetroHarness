# Conversations

A conversation is any number of questions about one interval of one well. Ask, read the answer, ask again: each
question is answered with what the earlier ones found in view. The first question is answered exactly as
`petroharness --las ... --question ...` answers it.

- [Start one](#start-one)
- [What a later question can do](#what-a-later-question-can-do)
- [Figures](#figures)
- [Methods and parameters](#methods-and-parameters)
- [The session folder](#the-session-folder)
- [Resume](#resume)
- [In Python](#in-python)
- [How it works](#how-it-works)
- [Limits today](#limits-today)

## Start one

```bash
petroharness chat --las WELL.las --formation "FORMATION NAME" --tops tops.csv
```

The interval, lithology, model, settings and skills options are the ones `petroharness` takes
([docs/USAGE.md](USAGE.md)). Then type a question and press Enter. An empty line or Ctrl-D ends the conversation.

Questions can also be given up front, and are asked in order before the prompt appears:

```bash
petroharness chat --las WELL.las --top 2450 --base 2510 --depth-unit m \
    --question "What is the porosity distribution in this interval?" \
    --question "What if I use the density porosity instead?" \
    --question "Now relate water saturation to porosity."
```

Answers go to standard output. What was run (the status, the number of investigation steps, the time, the folder of the
question) goes to standard error.

## What a later question can do

Anything the first question can, and it starts from what is already known. There is no list of follow-up kinds: the
model reads the question with the conversation in view and decides what it needs. For example:

- **Ask about an earlier answer.** "What formation water resistivity did the saturation use?" The results opened
  earlier are still there; the model reads them again instead of computing them again.
- **Try another method or parameter.** "What if I use the density porosity instead?" Petrophys computes the
  alternative and the answer compares it with what the earlier answer used.
- **Go further.** "Now relate water saturation to porosity." A new investigation on the same interval.
- **Narrow down.** "And only in the lower sand?"

Every answer is checked the same way as a first answer: each number in it must come from a result.

## Figures

An answer can carry figures where a plot says it better than text. Petrophys draws them
(`petrophys.visualization`): the harness has no drawing code of its own. Not every answer gets one.

Two kinds of plot are offered for an answer:

- **The plot of one of its results.** A statistics result gives a histogram of each curve by zone and the log viewer
  of its curves beside the zones' lithology; a crossplot or a comparison gives the crossplot with its line.
- **A standard display of the interval**, where the interval holds the curves and the answer's results rest on them:
  the density-neutron, M-N and MID lithology crossplots, the Pickett, Hingle and Buckles plots, the flow-unit plot,
  the triple combo and the net pay summary.

After an answer is written, one more model call is shown the question, the answer and these candidates. It chooses
which to show, or none. Petrophys then draws each on the interval's well. The answer's text is never passed back
through the model, so figures cannot change it.

What the harness adds around a Petrophys plot is only what the plot needs from the question:

- **The well.** The interval's samples, with the curves as the results read them (a curve computed on request is
  included; a result's condition is applied).
- **The zones**, as the log viewer's lithology track.
- **The numbers a plot takes**, each said in the caption with its source. A Pickett plot's Rw is the median of the
  interval's Rw curve; its exponents come from the well's record, or are Petrophys' defaults.
- **The caption**, which names the Petrophys function and the result or curves it drew.

A plot that is missing belongs in Petrophys. Once it is there, one line in `petroharness/figures.py` (`DISPLAYS`)
offers it.

When a conversation starts, Petrophys' log viewer also draws the whole interval once (`overview.png` in the session
folder, and the Well logs tab of the web UI): the standard tracks for the curves the well holds, beside the zones'
lithology.

Figures are files in the question's folder (`turns/NN/figures/`), linked at the end of `answer.md`. Turn them off with
`--no-figures`. A benchmark run never draws any.

## Methods and parameters

Every answer file ends with the methods and parameters the answer rests on: the workflow steps that computed the
curves the answer names (for example the porosity step with its matrix and fluid values, the saturation step with its
exponents), and the steps those read from (the clay volume behind the porosity). Each step is shown with its method,
the curves it computed, what it read, and its parameters.

Code reads this from the well's record after the answer is final. The model does not write it and never sees it, so it
cannot be wrong about what was used and it cannot change an answer. A curve computed on request during the
conversation (a what-if) is listed under the label it was computed with. The same list is in `trace.json` (`basis`) and
in `Turn.basis`.

## The session folder

A conversation lives in one folder (`--session DIR`; by default `./petroharness-sessions/<LAS name>-<time>`):

```text
log.jsonl              the events, in order: session_start, display, question, result, figure, turn_end, session_resume
overview.png           the interval's log display by Petrophys, drawn when the conversation starts
blobs/                 the texts the events name (each result as shown, each answer), kept once, by SHA-256
turns/01/answer.md     question 1's answer with its header, figures, methods and parameters
turns/01/trace.json    its full trace
turns/01/tape.jsonl    every model request and reply of the question
turns/01/figures/      its figures
.cache/                the interpreted well
```

`log.jsonl` is the record the conversation is resumed and audited from. One line per event:

| Event | What it records |
|---|---|
| `session_start` | The LAS file and its SHA-256, the inputs, the interval and zones used, the model, the Petrophys build, the harness commit |
| `display` | The interval's log display drawn when the conversation starts: its file and the Petrophys function |
| `question` | The question and its task |
| `result` | One result the question opened: its id (E1, E2, ...), the tool, the arguments, the SHA-256 of its text |
| `figure` | One figure drawn: its kind, the result it draws, its caption, its file |
| `turn_end` | The question's summary: status, how the answer opens, the settled claims with the results they cite, the results opened, steps, model calls, tokens, seconds |
| `session_resume` | A resume: the questions and results rebuilt, and any difference found |

## Resume

```bash
petroharness chat --resume DIR
```

The well is prepared again from the cache, and every recorded result is opened again in order. Each must come back
with the same id and the same text. A difference (for example after a Petrophys upgrade) is written to the
`session_resume` event and the conversation goes on.

## In Python

```python
from petroharness.session import Conversation

c = Conversation.start("WELL.las", "my-session", formation="FORMATION NAME", tops="tops.csv",
                       model_url="http://HOST:PORT/v1")
first = c.ask("What is the porosity distribution in this interval?")
print(first.answer)
second = c.ask("What if I use the density porosity instead?")
for figure in second.figures:
    print(figure["caption"], second.folder / figure["file"])

later = Conversation.resume("my-session", model_url="http://HOST:PORT/v1")
later.ask("Now relate water saturation to porosity.")
```

`Turn` has `number`, `question`, `answer`, `status`, `trace`, `folder`, `figures` and `basis`.

## How it works

- **The well is prepared once.** Petrophys interprets the LAS when the conversation starts. Later questions start
  without that wait.
- **One ledger for the whole conversation.** Every result has an id, and the ids go on across questions (E1 to E22 in
  the first question, E23 onward in the second). A later question lists the earlier results, reads any of them with
  `get` or `find`, and may cite them.
- **Each question is the same question graph.** A later question skips preparing the well and starts at the READ call.
  Its prompts carry one extra block, EARLIER IN THIS SESSION: each earlier question, how its answer opened, and its
  settled claims with the ids of their results. Code builds that block from the log; no model writes it. The newest
  questions are shown in full, older ones in short, the oldest as a count.
- **The writer of a later question** reads that question's own results and the earlier results its claims cite.
- **A result that went stale is marked.** When a later question computes a curve again under the same name, earlier
  results that read the old values say so when read again, and the same call is computed anew.
- **The first question is unchanged.** With no earlier question the extra block is empty, and every model request is
  the one a single `petroharness` run sends. The request gate checks this on recorded runs.

## Simple questions

The model first says whether a question is direct (a value, a setting, a count, a depth or a yes or no that one or two
lookups will state) or needs an investigation. A direct question skips the investigation: one or two look steps
open what is needed, and a short answer is written from those results, with its basis and the limit that matters.
"What is the average effective porosity?" then takes three model calls instead of eight or more. To give every
question a full investigation, start with `--investigate` ([GRAPH.md](GRAPH.md), "The direct route").

## Limits today

- One interval per conversation. Another interval of the same well is another conversation.
- A what-if is a comparison. It does not change the settings later questions use.
- A later question costs about as many model calls as a first question when it needs new results.
