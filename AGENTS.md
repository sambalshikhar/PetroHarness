# Working on PetroHarness

What the harness is: `README.md`, `docs/ARCHITECTURE.md`, `docs/GRAPH.md`. The code layout, configuration and tests:
`docs/DEVELOPMENT.md`. The design rules: `docs/DESIGN.md`.

## Rules (each with its reason)

1. **The harness never reads reference outputs.** No reference answers, reference context files or question ids in
   the harness; only tests and evaluation scripts may read them. *Why: no leakage.*
2. **No dataset names or literals** (wells, formations, depths, values) in code, rules, prompts, the policy or the
   report style; dataset facts live in the data config. `tests/test_lint.py` enforces it. *Why: the harness must
   work on any well.*
3. **Code computes and states facts; the model interprets.** Presence, fluid, mobility and ranking are the model's
   readings of computed facts, never rules fitted to expected answers. *Why: the answer must rest on the data in
   hand.*
4. **Petrophys calculates.** A tool computes petrophysics only through Petrophys, or is a listed generic data
   operation (`tests/test_petrophys_integration.py`). *Why: one source of truth, auditable.*
5. **One model answers, whichever it is.** Every call in a run goes to the one model its card names (any chat model on
   an OpenAI-compatible endpoint; K2-Horizon-7B by default). No helper model in any role, and no code path for one
   model only: what differs between models is the card's request settings (`docs/MODELS.md`). *Why: the answer and
   its trace are one model's work, and the harness must serve any model.*
6. **Every step is one call rebuilt from the state.** No multi-turn conversation inside the investigation. *Why:
   what the model sees at each step is exactly what the trace records.*
7. **A change that should not alter behaviour passes the golden tapes** (`tests/agent/test_golden_tapes.py`), the
   prompt fixture (`tests/agent/fixtures/prompts.json.gz`, compared by `tests/agent/test_skill_library.py`) and the
   ledger replay (`tests/agent/replay.py`). A change that should is a switch (`agent/options.py`, off by default)
   until it is measured. *Why: the proof of no change, and comparable A/Bs.*
8. **Measure end to end.** Judge a behaviour change by the answers on a fixed set of questions, against a control run
   at the same time, with two runs of each; read the answers yourself before any automatic scoring. Record
   what you measured with the change (commit message or PR). *Why: scores of a single run are noisy, and a check that
   passes on one part can leave the answers worse.*
9. **Leave a clean state:** tests pass, no stray files, nothing in `runs/` committed. *Why: the next person starts
   clean.*
10. **Keep the generality contract** (`docs/DESIGN.md`, G1-G8; the tests in `tests/test_generality.py`): no
    evaluation label enters the run; every model-facing line has a stated provenance; the harness states no
    conclusion; no rule is keyed to question wording; no evaluation text or words in model-facing text; where several
    bases or conventions are valid, the tools show them and the model chooses; lithology zones are the unit of
    analysis; the model decides, and code never decides for it or corrects its decisions. *Why:
    the harness must be general, so that no gain comes from fitting a particular set of questions.*
