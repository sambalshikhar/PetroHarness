# Skills: pluggable libraries of domain guides

The guides the model reads come from a **skill library**: a folder of guides, plugged into a run by one setting.
The harness owns the topic areas (`../topics.yaml`: the 14 areas the READ call chooses
from, with their analyzer families and first-look curves). A library does not define areas; each of its guides
declares the areas it serves. The harness works the same with any library, or with none.

The packaged library, and the default, is `researched/`: one guide per topic area and two common guides (`answer`,
`route`). The area guides were written from the petrophysics literature (textbooks, handbooks, society and survey
material, service-company glossaries) by writers who never saw the benchmark questions or their references. An
independent reviewer then checked every line against rules A-G: no answers; no per-guide choice instructions; no
harness conventions; numbers verified or softened; general; consistent; short. A test checks the library for overlap
with the benchmark (`test_no_benchmark_overlap`, below).

The guides give direction, not verdicts. Each says:
- what to consider;
- which results to set side by side;
- the methods and criteria a call needs, stated generally, with their uncertainty;
- textbook facts;
- how evidence is easily misread;
- what logs cannot establish, and what would.

What to conclude is the model's job. The numbers come from Petrophys.

## Plugging a library

One setting picks the library: `skills` in the harness configuration, or the environment variable
`PETROHARNESS_SKILLS`, which overrides it (a run chooses without editing a config).
- **A path:** a library folder, absolute or relative to `src/petroharness/resources` (the default is
  `skills/researched`).
- **`none`:** a run with no guides.

```bash
PETROHARNESS_SKILLS=/path/to/my_library python -m petroharness.cli ...      # another library
PETROHARNESS_SKILLS=none python -m petroharness.cli ...                     # no library
```

The library is loaded and checked before the run starts (`direction.plugged`, `direction.load`). A bad library stops
the run there, before its first question, with every problem listed as WHAT / WHY / FIX. The checks:
- `library.yaml` holds `name`, `description` and `common`, and each common guide exists;
- every folder is a guide, its `SKILL.md` parses, and its `name` is the folder's name (lower case, digits, `_`);
- every guide declares `areas`, each one a topic area of `topics.yaml`; a guide that serves no area must be common;
- every Decide, Know, Easily misread and Do not state line has its `sources.yaml` row (class `a`, `g` or `b`);
  class `a` has references, class `b` names its fact, and every cited reference is a key of `refs.yaml`;
- every Compare line is a lookup the harness can run, or a template, and every switch tag names a live switch.

The trace records the library a run read: `skills: {"library": <its name, or "none">, "version": <a hash of its
files>}`.

## How the model sees a library (two tiers)

1. **Always in the step prompt: the index (DIRECTION).** One line per guide, `name: when`, under each topic area the
   guide serves. The areas the model chose in its READ call come first, then the library's common guides, then the
   other areas in `topics.yaml`'s order. An area whose one guide is named for it is one line (the researched library).
2. **On demand: the guide.** The model reads a guide with the action `guide <name>` (up to 2 a step, outside the lookup
   cap). Its sections are rendered for the formation in hand: the Compare list shows only what this formation can run.

The first time a guide is read, the code also opens two kinds of lookup from its Compare list:
- the workflow sections it names, for the analyzer families of the topics the model chose;
- up to two `stats` lines whose curves are all the workflow's own.

**With no library** (`none`): no DIRECTION, no guide action, no section opened by a guide. The model-facing texts say
nothing about guides: the brief's DIRECTION mention and guide bullet, step 1's guide sentence and example guide call,
and the "guide" in the not-run note are component fragments included only when a library is plugged
(`agent/components/README.md`). A guide call is said back as not run, like any action the harness does not read. The
READ call, the topics, the first look and the map's notes work as with a library: they use the topic areas.

`src/petroharness/agent/direction.py` loads a library and renders the index and the guides.

## Layout

```
skills/
  README.md             this file: the library format
  researched/           the packaged library (the default)
    library.yaml        name, a one-line description, common (the guides listed for every question)
    refs.yaml           the literature the provenance cites (key: the reference, or each citing guide's entry where
                        they cite one work differently)
    <guide>/SKILL.md    the guide
    <guide>/sources.yaml  the provenance of its Decide, Know, Easily misread and Do not state lines
```

The library's guide order is its common guides first, then the others by the first topic area each serves. It orders
the index within an area, and the list of guides the model is given when it asks for one that does not exist.

**`SKILL.md`** is frontmatter (`name`, `when`, `areas`), then one section per part, one bullet per line:

```
---
name: porosity
when: Questions on how porous a zone or interval is, ...
areas: [porosity]
---

# porosity

## Consider          questions to ask of the data
## Compare           lookups, rendered for the formation
## Decide            methods and criteria, stated generally, with their uncertainty; the last line, the answer's
                    shape beside them in one of five forms: locate, quantify, relate, classify or explain
                    ("Answer shape: locate (depth runs, each graded). ...")
## Know              textbook facts, with references; workflow facts
## Easily misread    traps, stated as fact
## Do not state      what logs cannot establish, and what would
```

`areas` lists the topic areas the guide serves (names from `topics.yaml`); a common guide has `areas: []`.

The Compare section holds lookups, not rules:
- each line is a tool call that parses (`stats PHIT, PHIE`, `runs NET_PAY`, `step porosity`, `section
  porosity.<key>`, a computation such as `zone_contrast PERM`);
- up to five lines a guide are recipes with a value the model gives, written with the placeholders (`runs
  CONDITION`, `stats CURVES where CONDITION`, `adjacent_jumps CURVE threshold=VALUE`): shown on every formation;
- each line has a short note in parentheses on what the lookup shows, never what to conclude; the note says what the
  tool computes (a least-squares line with its R2 and n, the depth runs top to base, n of N and the statistics), so a
  reading is not taken for a test the tool does not run; `overlap A B` lays two conditions side by side
  where a guide relates them;
- every test or comparison the guide's Consider and Decide lines describe has a Compare line with the call that runs
  it (the reviewed pairs: tests/agent/fixtures/guide_recipes.yaml). A guide names only methods the harness can
  run: a line whose test no tool runs on the record says which tool comes closest ("Closest here: ...");
- a guide has at most 12 lines, the most general first;
- every section the analyzers write is named by at least one guide's Compare list (a test over the three
  datasets).

The format is strict:
- `direction.read_skill` rejects anything else, including frontmatter keys other than `name`, `when`, `areas` and a
  gate `option`;
- a test checks that each file reads and writes back to the same bytes;
- write one finding per bullet, with no line breaks inside a bullet.

**Skills are generic.** A skill reads as plain domain guidance, with no switches in it (`test_skills_are_generic`).
While a new line, or a new skill, is measured against the current one, it may carry a switch: `[option] text` at the
start of the line (`[!option] text` for the line it replaces), or `option: <name>` in the frontmatter. The tag names
a live switch in src/petroharness/agent/options.py; a library whose tag names no switch does not load. Once the
measurement decides, the switch goes with its tags: an adopted line keeps its text, and a rejected one is deleted.

## Provenance

`sources.yaml` has one list per part (`decide`, `know`, `misread`, `ceiling`), with one row per line, in order (rule
G2, docs/DESIGN.md). Each row gives:
- **class:**
  - `a`: literature, with references;
  - `g`: a general guideline (references optional);
  - `b`: a fact about the workflow or the harness, with the fact named (`fact`).
- **refs:** keys of `refs.yaml`, each optionally followed by the chapter or topic cited ("Mavko2009 (Vp-Vs relations)").
- **verified** (the review set it on rows that state a number):
  - `textbook`: a widely documented value;
  - `opened`: the reviewer read the source;
  - `softened`: worded as varying by source.
- **note:** the review's note. A row of a common guide may also carry `origin` (what motivated the line).

A reader's reporting convention lives in the report style (`profiles/report_style.yaml`), not here. A loss on a
benchmark question is never a line's justification.

## Rules

- Every line the model reads in Decide, Know, Easily misread and Do not state has its provenance row; a class-a row has
  references, and every reference is defined (checked as the library loads, and by `tests/agent/test_skills.py`, which
  runs over whatever library is plugged).
- The harness states no conclusion: `tests/test_generality.py::test_no_prescriptions` (G3).
- No benchmark words, and no 6-gram shared with a benchmark question or reference answer:
  `test_no_benchmark_words`, `test_no_benchmark_overlap` (G5), over every library the package ships. The test lists
  the generic n-grams it allows, each with its reason.
- No well, formation or dataset names, depths or zone ids (`tests/test_lint.py`, `tests/agent/test_b4_direction.py`
  D1).
- Every Compare line parses and runs where its data is. A guide rendered for a formation lists only what runs there
  (D2, on the configured dataset and on the datasets configured beside it).
- Sizes (D3):
  - the index is one line per guide and at most 4,000 characters;
  - a guide is at most 8,500.

## Changing a skill, or writing a library

1. Edit the guide's `SKILL.md`, and the line's `sources.yaml` row: its class, references and verification. A new
   reference goes into `refs.yaml`. A change that is measured first goes in under a switch (see "Skills are generic").
   A new library is a new folder in this layout; it needs no code change.
2. Run `tests/agent/test_skills.py` (with `PETROHARNESS_SKILLS` naming a new library), `tests/agent/test_b4_direction.py`,
   `tests/test_generality.py` and `tests/test_lint.py`.
3. A change to what the model reads changes behaviour, and the golden tapes will differ. Measure it end to end
   (AGENTS.md, rule 8) and say in the commit what you measured.
