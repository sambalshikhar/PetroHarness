# The evidence graph and the audit trail

Every answer rests on results, every result on curves, every computed curve on a Petrophys step with its parameters,
and every measured curve on the LAS file. The evidence graph holds those links as data. The audit trail is that graph
written out for one answer.

- [Get an audit trail](#get-an-audit-trail)
- [What the graph holds](#what-the-graph-holds)
- [In Python](#in-python)
- [How it is built](#how-it-is-built)
- [Limits today](#limits-today)

## Get an audit trail

```bash
petroharness audit SESSION                 # every answered question of the conversation
petroharness audit SESSION --question 2    # one question
petroharness audit SESSION --json          # the whole graph as JSON
```

`SESSION` is a conversation's folder ([SESSIONS.md](SESSIONS.md)). The command needs nothing else: no well, no
Petrophys run and no model. For each answer it lists:

1. the claims the investigation settled, each with the results it cites;
2. the numbers the answer states, each with the results that show it;
3. each of those results: the question it was opened in, its call, the curves it read, the SHA-256 of its text;
4. each curve: measured (the LAS file) or computed, and by which step;
5. each step Petrophys ran: its method, what it read, its parameters;
6. the LAS file with its SHA-256, the Petrophys build, the harness commit and the model.

The same trail is in the web UI (the "Audit trail" link under an answer), and a whole conversation can be written
as one document, with each answer, its figures, its methods and parameters and its audit trail:

```bash
petroharness report SESSION                # writes SESSION/report.md
```

## What the graph holds

| Node | What it is |
|---|---|
| `las` | The LAS file: its path and SHA-256 |
| `curve:<NAME>` | A curve: measured or computed, with its unit |
| `step:<name>` | A workflow step Petrophys ran: its method and parameters |
| `Q<n>` | Question n |
| `E<k>` | A result the investigation opened: the tool, its arguments, the SHA-256 of its text |
| `A<n>` | The answer to question n |
| `C<n>.<k>` | A settled claim of question n |
| `F<n>.<k>` | A figure of answer n |

| Link | From, to |
|---|---|
| `from` | A measured curve, the LAS file |
| `computed_by` | A computed curve, the step that wrote it |
| `reads` | A step, a curve it read. A result, a curve its call names |
| `opened` | A question, a result opened while answering it |
| `answered_by` | A question, its answer |
| `states` | An answer, a claim it settled |
| `cites` | A claim, a result it rests on |
| `shows` | An answer, a result that shows a number the answer states (the link carries the numbers) |
| `carries` | An answer, a figure |
| `draws` | A figure, the result it plots |

A result opened in an earlier question and cited by a later one is one node: the ids go on across the conversation.

## In Python

```python
from petroharness.evidence import EvidenceGraph

g = EvidenceGraph.from_log("my-session")
trail = g.trail(2)                      # what answer 2 rests on, back to the LAS file
trail["numbers"]                        # {"0.2697": ["E7", "E12"], ...}
[s["step"] for s in trail["steps"]]     # the Petrophys steps behind it
g.out("C2.1", "cites")                  # the results a claim cites
g.to_json()                             # the whole graph, in a fixed order
```

## How it is built

- **From the session log alone.** `log.jsonl` and `blobs/` hold everything the graph needs. Building it twice gives
  the same graph, and resuming a conversation does not change it.
- **The well's record is kept once.** When the first question has run, the curves and steps as Petrophys recorded them
  are written to the log (a `record` event naming a blob). A new one is written only when the record changes, for
  example after a curve is computed on request.
- **Generations after a settings change.** A settings change ([SESSIONS.md](SESSIONS.md), "Changing a setting")
  interprets the well again: its record from then on is a new generation, with its own curve and step nodes
  (`curve:SW@gen2`, `step:saturation@gen2`). A result links to the curves of the generation in force when it was
  opened, so each answer's trail shows the parameters it was made with, and lists the changes made before it. A
  conversation without a change builds the graph it built before.
- **The number links use the checker's own matching.** The check that every number of an answer comes from a result
  is applied result by result, so the graph says which results show each number.
- **Nothing here reaches a prompt.** The graph is read off the record of a conversation, after each answer is final,
  so it cannot change an answer. This is the session graph's `project` node ([SESSION_GRAPH.md](SESSION_GRAPH.md)).

## Limits today

- A link from a result to a curve comes from the curve names in the result's call. A result that reads curves its
  call does not name (a section of the record) has no curve links.
- A number that is supported by arithmetic on two shown numbers, or by the zone table, has no single result and is
  not listed.
- The trail stops at the LAS file's hash. Checking the file against it is the reader's step.
