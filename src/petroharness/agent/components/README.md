# Harness components

Every text the harness sends to the model belongs to exactly one component. A component is a folder here:

| id | folder | owns |
|---|---|---|
| C1 | C1_system | the brief: role, protocol, reply format |
| C2 | C2_guardrails | the claim checks' messages (flags.json), done issues, the syntax fix, the writer checker's repair requests (with the working notes left in an answer) |
| C3 | C3_memory | the claims, the ledger, opened results (rendered by code it frames) |
| C4 | C4_tools | tool descriptions, argument vocabularies, the condition grammar, the zone selector |
| C5 | C5_orchestration | each stage's instructions (the reading, step 1, step k, the points request, settle with its bookkeeping lists), the section owners |
| C6 | C6_skills | the direction index over the topic areas (resources/topics.yaml) and the plugged skill library's guides (a library is data in its own folder, resources/skills/README.md; its lines are found in the prompts, and its version is the trace's `skills`); the GUIDES block of a step's prompt, a guide whole at the step after it is read and short after that |
| C7 | C7_scripts | tool outputs and the map (rendered by code it frames; the label of a step parameter written as a curve) |
| C8 | C8_middleware | the hooks' notes: actions left out, results withheld for NEW's budget (shown first at the next step), edits not applied, nothing new |
| C9 | C9_answer | the writer: its write texts (the full answer's rules, the short answer's, the table rule) and the parts of its prompt it frames (the provenance card, the zone table, the data's conventions; the prompt holds the question's points and limits, not the claims); the one guideline for bases and conventions (given to the settle step only, not the writer); the figure choice |
| C10 | C10_reading | how evidence is read and graded: caveats, levels and rankings, negatives, absence |

Files:
- `component.yaml`: `id`, `name`, `purpose`, `texts` (entry -> file), `frames` (code whose output it frames).
- An entry is a plain `.md` file holding the exact bytes the model reads (no stripping on load), or a `.json` file
  holding a list or a dict of such strings (rule lists, tool descriptions, flag templates).
- A template has `{name}` slots, filled in one pass (`components.fill`): a value is never read as a slot, and a slot
  without a value stays as written (JSON braces such as `{"points": ...}` are not slots).
- C5's `section_owners` maps a frame header (at a line start) to the component owning the section it opens.
- Text about guides is its own entry, a fragment filled into its template's slot only when a skill library is plugged
  (empty with none): C1 `brief_direction` and `brief_guide` (the brief's `{direction}` and `{guide_action}`),
  C5 `step1_guides` and `step1_guide_call` (step 1's `{guide_sentence}` and `{guide_call}`; the call names the
  library's guide on the example's topic), C8 `not_run_guide` (not_run's `{guide}`).

Versions and attribution:
- A component's version is the first 12 hex digits of SHA-1 over its files and its `frames`, sorted by path.
- Every model call is recorded in the trace (`calls`): each message's spans `[component, version, start, end]`
  cover it exactly. Entries found in the text are their component's; the rest belongs to the nearest preceding section
  header's owner, else to the message's owner by stage (`components.OWNERS`). `trace["components"]` holds the versions.
- `PETROHARNESS_COMPONENTS=<folder>` runs the harness on another copy of this folder: an A/B of component versions,
  or, with a golden tape replayed in collect mode (`tape.replay(llm, tape, collect=True)`), the calls an edit
  reaches.

A change touches one component; its commit says what it changes and what was measured (AGENTS.md, rule 8).
