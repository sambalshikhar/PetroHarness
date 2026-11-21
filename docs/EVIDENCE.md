# The evidence graph and the audit trail

Every answer rests on results, every result on curves, every computed curve on a Petrophys step with its parameters,
and every measured curve on the LAS file. The evidence graph holds those links as data, rebuilt from a conversation's
session folder alone. The audit trail is that graph written out for one answer.

```mermaid
flowchart TB
    Q2["Q2 · question<br/>Which zone has the best reservoir quality,<br/>and how does the log permeability compare with the core?"]:::ask
    A2["A2 · answer<br/>status ok, text SHA-256 8579e354…"]:::ask
    C21["C2.1 · settled claim<br/>Z19 carries the highest rock-quality scores …<br/>PERM_CC mean 1627.6 mD"]:::ask
    F21["F2.1 · figure<br/>crossplot of PERM_CC against PERM"]:::ask
    E11["E11 · result<br/>stats of PERM, PERM_CC, PHIE, PHIE_CC, FZI, …"]:::result
    E17["E17 · result<br/>compare PERM_CC with PERM, 12 zones"]:::result
    PCC["curve:PERM_CC · mD<br/>computed"]:::curve
    STEP["step:permeability<br/>method auto, strategy same_well_core+coates"]:::petrophys
    RDEP["curve:RDEP · ohm.m<br/>measured"]:::curve
    LAS["las · 30_6-5.las<br/>SHA-256 5ecf2c53…"]:::las
    Q2 -->|answered_by| A2
    A2 -->|states| C21
    A2 -->|carries| F21
    C21 -->|cites| E11
    F21 -->|draws| E17
    A2 -.->|"shows 1627.6"| E11
    E11 -->|reads| PCC
    E17 -->|reads| PCC
    PCC -->|computed_by| STEP
    STEP -->|reads| RDEP
    RDEP -->|from| LAS

    classDef ask fill:#fdeee4,stroke:#ef6719,color:#7a3410
    classDef result fill:#ffffff,stroke:#9aa0aa,color:#1c2433
    classDef curve fill:#f0eeea,stroke:#9aa0aa,color:#1c2433
    classDef petrophys fill:#e3f2ee,stroke:#197e6f,color:#0f4f45
    classDef las fill:#ffffff,stroke:#011e3f,color:#011e3f
```

One path through the graph of the Brent Group conversation on GeoLink 30/6-5: a claim of the second answer, back to
the LAS file. The whole graph of that conversation holds 153 nodes (2 questions, 2 answers, 15 claims, 18 results, 6
figures, 90 curves, 18 steps, the LAS file and the session) and 287 links.

## Get an audit trail

```bash
petroharness audit SESSION                 # every answered question of the conversation
petroharness audit SESSION --question 2    # one question
petroharness audit SESSION --json          # the whole graph as JSON (with --question: that question's trail)
petroharness audit SESSION --out FILE      # write to a file instead of standard output
```

`SESSION` is a conversation's folder ([Conversations](SESSIONS.md)). The command needs nothing else: no well, no
Petrophys run and no model. For each answer it writes these sections:

| Section | What it lists |
|---|---|
| Claims and the results they cite | The claims the investigation settled, each with its grade and the results it cites |
| Numbers the answer states and the results that show them | Each number, with every result that shows it |
| Results | Each result: the question it was opened in, its call, the curves it read, the SHA-256 of its text |
| Curves | Each curve: measured (the LAS file) or computed, and by which step |
| Steps Petrophys ran | Each step: its method, what it read, its parameters |
| Figures | Each figure, with the result it was drawn from |
| Source | The LAS file with its SHA-256, the Petrophys build, the harness commit, the model and the setup hash |

An excerpt of `petroharness audit brent --question 2`, the second Brent question (`[…]` marks what is left out):

```markdown
# Audit trail: question 2

**Question:** Which zone has the best reservoir quality, and how does the log permeability compare with the core?

**Answer:** status ok; text SHA-256 `8579e354dcdbb2060f80a6f2eedd9e87c9d671807cbd9afa3140d918d785b32c`
[…]
## Claims and the results they cite

1. Z19 carries the highest rock-quality scores: RQI mean 2.4187, FZI mean 9.2246 and PERM_CC mean 1627.6 mD (E11), but its SW mean is 1, so it is a clean, porous, fully water-bearing sand rather than a hydrocarbon-producing unit. (moderate): E11, E15
[…]
## Numbers the answer states and the results that show them

| Number | Shown by |
|---|---|
| 2951.66 | E1, E2, E3, E4, E5, E6, E8, E9, E10, E11, E12, E13, E14, E15, E16, E17 |
| 2955.01 | E1, E2, E3, E4, E5, E6, E8, E9, E10, E11, E12, E13, E14, E15, E16, E17 |
| 1627.6 | E1, E9, E10, E11, E17 |
[…]
## Results

| Result | Asked in | Call | Curves it read | Text SHA-256 |
|---|---|---|---|---|
| E11 | question 2 | `stats(curves=["PERM", "PERM_CC", "PHIE", "PHIE_CC", "FZI", "RQI", "VCL", "PHIT", "SW"])` | PERM, PERM_CC, PHIE, PHIE_CC, FZI, RQI, VCL, PHIT, SW | `54e8013eac8c2c69` |
| E15 | question 2 | `section(key="permeability.overall_permeability_interpretation")` | - | `81b73733aac4b624` |
| E17 | question 2 | `compare(a="PERM_CC", b="PERM", zones=["Z1", "Z4", "Z5", "Z6", "Z7", "Z9", "Z13", "Z14", "Z15", "Z18", "Z19", "Z20"], tolerance=0.1)` | PERM_CC, PERM | `0a605f176a00227d` |
[…]
## Curves

| Curve | Unit | Where it comes from |
|---|---|---|
| PERM | mD | computed by step `permeability` |
| PERM_CC | mD | computed by step `permeability` |
[…]
| RDEP | ohm.m | measured (the LAS file) |
[…]
## Steps Petrophys ran

- **permeability**: auto. Read PHIE, SW, RDEP, RESFLAG. Parameters: bvw_irr = 0.0637761; core_min_points = 3; empirical_method = coates; fallback_method = coates; method = auto; peer_core_enabled = no; peer_core_models = 0; peer_wells_considered = 0; perm_max_clip_md = 10000; same_well_core_models = 1; strategy = same_well_core+coates; swirr_app_method = buckles_bvw_irr; swirr_source = buckles_bvw_irr.
[…]
## Source

- LAS file: `[…]/petrophys/datasets/geolink/30_6-5.las`, SHA-256 `5ecf2c53826981f978c2efb47fe016abf94dac62e83dbdb54eee115596f801b9`
- Petrophys: 3.0.0@files-c5de047fe601
- PetroHarness commit: <commit>
- Model: K2-Horizon-7B
- Setup (petroharness setup; the session log's setup event holds its parts): d70dbbf039dd

Every result's text is kept in the session folder under its SHA-256 (`blobs/`).
```

The same trail is in the web UI: the "Audit trail" link under an answer opens it, and "How it was computed" draws the
graph behind the answer.

![How it was computed, in the web UI](images/ui-30_6-5-brent-lineage.png "How it was computed, under an answer about the Brent Group of GeoLink 30/6-5 in the web UI: the measured logs, the Petrophys steps that computed the curves the answer rests on, the results the model opened, the findings it settled and the answer. A number clicked in the answer, here 2841.0, lights its path: the results that show it and the steps behind them.")

A whole conversation can be written as one document, with each answer, its figures, its methods and parameters and its
audit trail:

```bash
petroharness report SESSION                # writes SESSION/report.md (--out FILE for another place)
```

## What the graph holds

Nine kinds of node and ten kinds of link. A result opened in an earlier question and cited by a later one is one node:
the ids go on across the conversation.

<details>
<summary>Every node kind</summary>

| Node | What it is |
|---|---|
| `las` | The LAS file: its path and SHA-256 |
| `session` | The conversation: its mode, interval, model, Petrophys build and harness commit; the settings changes; the setup hashes (every one, and the last) |
| `curve:<NAME>` | A curve: measured or computed, with its unit |
| `step:<name>` | A workflow step Petrophys ran: its method and parameters |
| `Q<n>` | Question n |
| `E<k>` | A result the investigation opened: the tool, its arguments, the SHA-256 of its text |
| `A<n>` | The answer to question n |
| `C<n>.<k>` | A settled claim of question n |
| `F<n>.<k>` | A figure of answer n |

</details>

<details>
<summary>Every link kind</summary>

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

</details>

## In Python

On the Brent session folder:

```python
from petroharness.evidence import EvidenceGraph

g = EvidenceGraph.from_log("brent")
trail = g.trail(2)                      # what answer 2 rests on, back to the LAS file
trail["numbers"]["1627.6"]              # ['E1', 'E9', 'E10', 'E11', 'E17']
[s["step"] for s in trail["steps"]]     # the Petrophys steps behind it: ['permeability', 'porosity',
                                        # 'core_correction', 'rock_quality', 'vclay', 'saturation', 'net_pay',
                                        # 'normalization']
g.out("C2.1", "cites")                  # ['E11', 'E15']: the results a claim cites
g.to_json()                             # the whole graph, in a fixed order
```

A trail holds the question, the answer, its claims, numbers, results, curves and steps, the settings changes made
before it, its figures, the LAS file and the session.

## How it is built

- **From the session log alone.** `log.jsonl` and `blobs/` hold everything the graph needs. Building it twice gives
  the same graph, and resuming a conversation does not change it.
- **Nothing here reaches a prompt.** The graph is read off the record of a conversation, after each answer is final,
  so it cannot change an answer. This is the session graph's `project` node ([SESSION_GRAPH](SESSION_GRAPH.md)).

<details>
<summary>The well's record, generations and the number links</summary>

- **The well's record is kept once.** When the first question has run, the curves and steps as Petrophys recorded them
  are written to the log (a `record` event naming a blob). A new one is written only when the record changes, for
  example after a curve is computed on request.
- **Generations after a settings change.** A settings change ([Conversations](SESSIONS.md), "Changing a setting")
  interprets the well again: its record from then on is a new generation, with its own curve and step nodes
  (`curve:SW@gen2`, `step:saturation@gen2`). A result links to the curves of the generation in force when it was
  opened, so each answer's trail shows the parameters it was made with, and lists the changes made before it. A
  conversation without a change builds the graph it built before.
- **The number links use the checker's own matching.** The check that every number of an answer comes from a result
  is applied result by result, so the graph says which results show each number. The answer is read as the checker
  reads it: the well's name and the checks' ignore patterns removed, small counts left out.

</details>

## Limits

- A link from a result to a curve comes from the curve names in the result's call. A result that reads curves its
  call does not name (a section of the record) has no curve links: E15 in the excerpt above reads "-".
- A number that is supported by arithmetic on two shown numbers, or only by what else the writer was shown (the zone
  table, the map, the curve card, the points and limits) or by the question, has no single result and is not listed.
- The trail stops at the LAS file's hash. Checking the file against it is the reader's step.
