# The session graph and the later-question graph

A conversation is a sequence of questions about one interval of one well ([SESSIONS.md](SESSIONS.md)). Two more
LangGraph graphs carry it, beside the question graph ([GRAPH.md](GRAPH.md)). This file is their blueprint: every node
and route below exists under the same name in `src/petroharness/session/graph.py` and
`src/petroharness/agent/graph.py`. `docs/graph_session.mmd` and `docs/graph_later.mmd` are the graphs drawn from the
code, and `tests/session/test_session_graph.py` keeps these files equal to the code.

- [The three graphs](#the-three-graphs)
- [The session graph](#the-session-graph)
- [The later-question graph](#the-later-question-graph)
- [Where additions attach](#where-additions-attach)

## The three graphs

| Graph | Runs | Entry | Blueprint |
|---|---|---|---|
| Question graph | The first question: the well is built, read, investigated, settled, written and checked | `agent.graph.GRAPH` | [GRAPH.md](GRAPH.md), `graph.mmd` |
| Later-question graph | Every later question, on the session the earlier ones left | `agent.graph.LATER` | this file, `graph_later.mmd` |
| Session graph | One question of a conversation, from the message to its committed record; a question graph runs inside its `turn` node | `session.graph.SESSION` | this file, `graph_session.mmd` |

The question graph is the measured one. Nothing in this file changes it: the first question of a conversation sends
exactly the requests a single `petroharness` run sends.

## The session graph

```text
open -> turn -> project -> figures -> commit
          |        |__________________^        figures off, or prepared tasks
          |___________________________^        a question with no answer
```

**Run context** (`Ctx`): the conversation. Its log, its live session (the interval, the ledger, the claims) and its
list of questions are the domain state, changed in place by the nodes. Nothing is checkpointed: the log is how a
conversation is resumed.

**State**: the question (`task`, `question`, `sent`), what the first node sets (`n`, `folder`, `start`, `shown`), what
the question graph's node returns (`got`, `items`, `settled`, `cited`), then `rests`, `shows`, `figs` and the
committed `out`.

### Nodes

| Node | Kind | What it does |
|---|---|---|
| `open` | code | Logs the question, and moves the session to it with the earlier questions as the prompts will show them |
| `turn` | graph | Runs the question graph (first question) or the later-question graph; logs each result it opened; reads its settled claims |
| `project` | code | Reads off the answer what the reader and the evidence graph need: the steps and parameters it rests on, and which results show each number it states |
| `figures` | model | One call chooses among the plots Petrophys can draw from what the answer rests on; Petrophys draws them |
| `commit` | code | Writes the question's files and its `turn_end` event, and adds it to the conversation |

### Routes

| From | Route | To |
|---|---|---|
| `open` | always | `turn` |
| `turn` | `after_turn`: the question has an answer | `project`, else `commit` |
| `project` | `after_project`: the conversation draws figures | `figures`, else `commit` |
| `figures` | always | `commit` |

What comes after the answer cannot change it: `project` and `figures` read the answer and its results, and the
answer's text is never passed back through the model. A conversation on prepared tasks (a benchmark run) takes no
model call and no plot from them.

## The later-question graph

The question graph without `build` (the well is not prepared again; the ledger and its ids go on), entered at `read`,
with one more route: after an investigation, a later question can also be answered in the short form.

| From | Route | To |
|---|---|---|
| `close` | `after_close_later`: as the question graph's `after_close`; where that goes to the full writer, `reply_form` picks the node | `no_answer`, `settle`, `write`, `write_brief` |
| `settle` | `reply_form`: the answer length the model chose in step 1 (`"reply": "brief"` or `"full"`) | `write`, `write_brief` |

The length is the model's decision, said in step 1 of a later question; the route only carries it to the writer node.
Where the READ call reads the depth (a user's conversation, by default: [GRAPH.md](GRAPH.md), "The direct route"),
step 1 is not asked for the length. Every node and every other route is the question graph's.

## Where additions attach

A feature that reads an answer (an export, a check list, a sensitivity table) is a node of the session graph after
`turn`, with its own route. A feature that changes how a later question is answered is a node or a route of the
later-question graph. The question graph takes no additions: a change to it is a measured change
([DEVELOPMENT.md](DEVELOPMENT.md)).
