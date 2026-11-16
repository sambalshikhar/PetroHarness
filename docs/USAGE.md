# Asking about any LAS file

`petroharness` answers one petrophysics question about one well from its LAS file. The well does not have to belong
to any data set the harness knows: give the LAS, the question and, if you have it, the interval you are asking about.
Petrophys interprets the log, the harness investigates and records, and a language model reads the results and writes
the answer (K2-Horizon-7B by default, or any chat model: [MODELS.md](MODELS.md)). (`petroharness benchmark` is the validation mode, which runs a benchmark's questions; this page does not
need it.)

The examples use three sample wells kept in one folder, `$S` below:

| file | depth unit | curves (as the file names them) | formation info |
|---|---|---|---|
| `1046123714.las` | ft | GR, RILD, RILM, RHOB, DPOR, CNLS, DT, SP, ... | `1046123714_formation_tops.csv` (tops only) |
| `tuhua-7.las` | m | GR, RESD, RESM, DENS, NEUT, DTC, PEF, ... | `formations_tuhua-7.csv` (tops and bottoms) |
| `teapot_17-wx-21.las` | ft (written `F`) | GRD, ILD, ILM, RHOB, NPHI, DT, SP, ... | none |

None of the three has a lithology log.

## Before you start

- **The package.** Install PetroHarness and Petrophys as the README's Install section says. The command is
  `petroharness` (in the virtual environment: `.venv/bin/petroharness`); `petroharness --help` lists the options.
- **The model.** Tell the harness where the model is served (an OpenAI-compatible `/v1` endpoint):

  ```bash
  export PETROHARNESS_MODEL_URL=http://host-a:8100/v1              # several servers: comma-separated
  ```

  or pass `--model-url http://host-a:8100/v1` on each call. The default model is K2-Horizon-7B. For any other chat
  model, add `--model NAME` (its served name), or `--model-card FILE` for a card of your own
  ([MODELS.md](MODELS.md)).
- **No data settings file is needed.** The harness builds its data settings from the LAS file. (A settings file is
  optional; see "A data settings file" below.)

## Quick start

```bash
petroharness --las $S/tuhua-7.las \
    --tops $S/formations_tuhua-7.csv --formation "Mount Messenger" \
    --question "Where are the best reservoir intervals in this formation? Give their porosity, shale volume and water saturation, and say whether any of them looks hydrocarbon-bearing."
```

The answer is printed. A short record of what was run goes to stderr:

```
petroharness: tuhua-7.las, Mount Messenger: 590.55-873.862 m (1860 samples; tops file formations_tuhua-7.csv, base: stated base)
  lithology: no lithology log: zones from shale-volume bands (VCL below 0.3, 0.3-0.6, above 0.6); 6 zones
  status: ok; 7 steps; skill library: researched (version 060950583ecb); settings: built from the LAS
  wrote /home/me/petroharness-out/tuhua-7/answer.md and trace.json
```

The first run on a well interprets it (a few seconds for a typical LAS); the interpreted well is cached in the
output folder, so later questions about the same well start straight away. An investigation and its answer take a
few minutes, depending on the model server. A direct question (a value, a setting, a count that one or two lookups
state) takes a short route and is answered in about a minute; the header of `answer.md` says which route was taken,
and `--investigate` gives every question the full investigation.

## Choosing the interval

A question is about one interval of the well. There are three ways to give it.

### 1. A formation from a tops file

```bash
petroharness --las $S/1046123714.las \
    --tops $S/1046123714_formation_tops.csv --formation "Lansing-Kansas City" \
    --question "What are the porosity and water saturation in this formation, and is it a hydrocarbon-bearing interval?"
```

The interval runs from the formation's top to:

1. its **stated base**, when the file has a bottom/base column with a value on that row (the base is included);
2. else the **next deeper top** in the file, whatever its rank (that top is not included);
3. else the **end of the log**.

So with a tops-only file, a group whose members are also listed stops at its first member: in
`1046123714_formation_tops.csv`, "Lansing-Kansas City" (3991 ft) runs to "LKC G" (4080 ft), the next top. To ask
about the whole group, give its base: add a `bottom` column to that row, or ask with depths (form 2).

Names match whatever the case, spacing and punctuation: `"lansing kansas city"` finds `Lansing-Kansas City`. A name
the file does not have stops with a list of the names it has (and the close ones). A name the file lists twice (a
repeated section, as `Manganui` in `formations_tuhua-7.csv`) stops too, listing both occurrences: ask about the one
you mean with its depths, `--formation Manganui --top 2164.9944 --base 2347.4172`.

### 2. A depth interval

```bash
petroharness --las $S/teapot_17-wx-21.las --top 5340 --base 5600 --depth-unit ft \
    --question "Is this interval a clean reservoir rock? What are its porosity and water saturation, and does any part of it look hydrocarbon-bearing?"
```

Both depths are included. `--formation NAME` labels the interval (`--formation "lower sand" --top 5340 --base 5600`);
without it, the interval is called by its depths (`depth interval 5340-5600 ft`). Leaving out `--top` starts at the
top of the log; leaving out `--base` runs to its end.

### 3. The whole well (the default)

```bash
petroharness --las $S/teapot_17-wx-21.las \
    --question "Which intervals in this well look like the best reservoirs, and are any of them hydrocarbon-bearing?"
```

With no tops file and no depths, the question is about the whole log, from its first sample to its last. A long log
has many zones (over a hundred in this well), and its top often lies behind casing, where only some curves were
recorded and porosity and saturation are not meaningful: in `teapot_17-wx-21.las` the density and resistivity logs
start near 500 ft, below the casing shoe, while gamma ray and neutron run to surface. A question about one interval
gets a more focused and more reliable answer when you give that interval; for a whole-well overview, start the
interval below the casing (`--top 505`).

## Turning formation information into a tops file

Formation information often arrives unstructured: a list in an email, a table in a well report, picks read off a
log print. Write it as a small CSV, one row per top:

```csv
formation,top,bottom,depth_unit
Mount Messenger,590.55,873.86,m
Manganui,874.01,1250.75,m
```

Only `formation` and `top` are required. For example, an email that says

> Tops (KB, ft): Topeka 3782, Heebner 3950, Lansing-Kansas City 3991, Stark 4179, Pawnee 4362, Mississippian 4618

becomes

```csv
formation,top,depth_unit
Topeka,3782,ft
Heebner,3950,ft
Lansing-Kansas City,3991,ft
Stark,4179,ft
Pawnee,4362,ft
Mississippian,4618,ft
```

and a report table with "Formation | Top MD (m) | Base MD (m)" columns can be saved from the spreadsheet as CSV as it
is.

What the reader accepts:

| role | header names it recognises (any case; spaces or punctuation read as `_`) | required |
|---|---|---|
| name | `formation`, `formation_name`, `name`, `top_name`, `zone`, `horizon`, `unit` | yes |
| top | `top`, `top_depth`, `top_md`, `md`, `depth` | yes |
| base | `bottom`, `bottom_depth`, `bottom_md`, `base`, `base_depth`, `base_md` | no |
| depth unit | `depth_unit`, `units`, `unit` (when it holds m/ft) | no |
| well | `well`, `well_name`, `wellname`, `well_id`, `uwi`, `api` | no |

- A unit may also sit in the header: `Top (ft)`, `TOP [M]`, `top_md_m`.
- Other columns (depth reference, source, comments) are ignored.
- Commas, tabs or semicolons separate the columns. An Excel sheet (`.xlsx`) is read as well.
- A file with only names and tops and no header line (`Topeka,3782`) is read as name,top (a third column as base).
- A table of several wells needs a well column. The rows whose well matches this LAS are used: the LAS file's name
  (without `.las`) or its WELL, UWI or API header, compared ignoring case and punctuation.
- Rows can be in any order. A row without a base takes the next deeper top.
- When tops are given in true vertical depth or subsea, convert them to the log's measured depth first: the harness
  reads them on the LAS's depth index.

## Depth units

- `--depth-unit m|ft` states the unit of the depths you give (`--top`/`--base`, or a tops file that states none) and
  is also the unit of the depths in the answer.
- A tops file's own unit (a unit column, or a unit in its header) wins over the default; a file that states one unit
  and `--depth-unit` another is an error, so a wrong unit is never applied silently.
- Without either, depths are taken in the LAS's own depth unit (the unit of its index curve, `DEPT.M` or `DEPT.FT`),
  and the answer uses it too.
- Depths in another unit than the LAS's are converted (a metre tops file on a feet log works).

## Without a lithology log

Most LAS files carry no lithology (or facies) log, and none is needed:

- **Petrophys's default interpretation** runs on every LAS. It standardizes the curve names and units and computes
  every step the curves allow: clay volume, porosity, a multi-mineral lithology (quartz, calcite, dolomite, anhydrite
  volumes and a computed lithology label), water saturation, permeability and net reservoir/pay flags, each step
  with its method and parameters recorded. Net pay uses the harness's cutoffs, which it passes to Petrophys and
  checks in the record: clay volume below 0.30 and water saturation below 0.70 (porosity cutoffs by lithology
  family, as Petrophys's standards set them).
- **Zones** are then runs of shale-volume bands: clean (VCL below 0.3), shaly (0.3 to 0.6) and shale-prone (above
  0.6). The stderr record and `trace.json` say so ("zones from shale-volume bands").
- A LAS that has a lithology log (a curve whose mnemonic or description says lithology or facies, holding integer
  codes) is detected and zoned by it. Name it with `--lithology-curve MNEMONIC` when detection misses it or finds two.
- `--formation-lithology "fine sandstone with siltstone"` passes on what you know of the formation's lithology. It
  reaches the model with the question, marked as the operator's statement.

For wells of a Petrophys context package, `--profile NAME` interprets the LAS as that package's context does (the
profile fixes the settings and needs the package's own raw LAS).

## Skill library

During the investigation the model can read short domain guides, one per topic area (porosity, water saturation,
hydrocarbon detection, ...), from a **skill library**. The guides give direction (what to compare, which methods
apply, how evidence is easily misread), never answers; the numbers always come from Petrophys.

- **With the packaged library (the default).** Nothing to set.
- **Without guides:** `--skills none`.
- **Your own library:** `--skills path/to/my_library`, a folder laid out as the packaged one
  (`src/petroharness/resources/skills/README.md` describes the layout and the checks a library must pass; a library
  that fails them stops the run before the first model call, with the problems listed).

Without `--skills`, the environment variable `PETROHARNESS_SKILLS` chooses, if set. The library used is recorded in
`answer.md`, on stderr and in `trace.json` (`skills`: its name and version).

```bash
petroharness --las $S/tuhua-7.las --tops $S/formations_tuhua-7.csv --formation "Mount Messenger" \
    --skills none --question "What is the average porosity of this formation?"
```

## Asking for other methods

The record holds the interpretation Petrophys ran with its defaults. Ask for another method, parameter or
calculation, and the model has Petrophys compute it:

```bash
petroharness --las $S/1046123714.las --tops $S/1046123714_formation_tops.csv --formation Topeka \
    --question "Can you compute saturation with Simandoux and give me the statistics?"
petroharness --las $S/1046123714.las --tops $S/1046123714_formation_tops.csv --formation Oread \
    --question "What would the water saturation be if Rw were 0.03 ohm.m at 105 degF?"
petroharness --las $S/tuhua-7.las --tops $S/formations_tuhua-7.csv --formation "Mount Messenger" \
    --question "Fit a saturation-height function assuming the free-water level is at 870 m."
```

- **Other inputs come from the record.** Every input the question does not change is taken from the record, and the
  answer says where each one came from.
- **New curves.** A recomputed curve gets its own name, such as `SW_SIMANDOUX`, beside the record's.
- **Missing inputs.** When Petrophys needs an input the well does not carry, the answer says what to provide: Rwb
  for dual water, CEC for Waxman-Smits, TVD for a pressure method.

Every verb and how a call is bound: `docs/TOOLS.md`.

## Curve names

LAS files from different companies and decades name the same log differently: the samples use RILD, RESD and ILD for
deep resistivity, CNLS, NEUT and NPHI for neutron porosity, DENS and RHOB for bulk density, GR and GRD for gamma ray.
Petrophys standardizes the usual mnemonics and units (to RDEP, NPHI, RHOB, GR, ...). The record the model reads
lists both names where they differ ("RDEP = Resistivity - Deep (same values as RESD)").

A curve Petrophys does not recognise is kept under its own name and used by no calculation. The record the model
reads then lists the standard log among the "measured logs not in the input", and `trace.json` shows it too. In
`tuhua-7.las`, for example, the medium resistivity `RESM` is not recognised, so RMED is listed as not in the input
and no medium/deep invasion ratio is computed. To map such a curve:

- **A curve-name mapping** (needs a Petrophys whose `interpret` takes `curve_aliases`, as the pinned one does). Put it
  in a small settings file and pass `--settings mapping.yaml`:

  ```yaml
  data:
    interpret:
      curve_aliases: {RESM: RMED}        # your mnemonic: the standard one; or the path of a CSV with curve,standard columns
  ```

  With it, RMED is read from RESM and the invasion ratio RMED/RDEP is computed.

- **Or rename the curve in the LAS** (any Petrophys):

  ```python
  import lasio
  las = lasio.read("well.las")
  las.curves["GAMMA_X"].mnemonic = "GR"
  las.write("well_renamed.las", version=2.0)
  ```

## The output

`--out DIR` (default `./petroharness-out/<LAS name>/`) receives:

| file | what it holds |
|---|---|
| `answer.md` | the question, the interval used, how the zones were made, the skill library, the status, then the answer |
| `trace.json` | the full record: every model call's prompt size and reply, each step's actions and results, the claims, the checker's rounds, and under `ask` the inputs, the interval, the zones, the data settings and the Petrophys version used |
| `.cache/` | the interpreted well, reused by later questions about the same LAS (delete it to re-interpret) |

A second question with the same `--out` replaces `answer.md` and `trace.json`: give each question its own folder to
keep them all.

The exit status is 0 when the question was answered, 1 when the run failed (the message and `trace.json` say why;
for example, Petrophys could not interpret the LAS) and 2 when the inputs are wrong (a missing file, a formation the
tops file lacks, an interval outside the log). Status `unresolved_numbers` in the record means the answer kept a
number the checker could not find in any computed result: read that number with care.

## More than one question

`petroharness` answers one question and stops. To keep an interval open and go on asking, use `petroharness chat`
with the same interval options ([SESSIONS.md](SESSIONS.md)). A conversation's folder is also what the other commands
read:

| Command | What it gives |
|---|---|
| `petroharness chat --las WELL.las ...` | a conversation: any number of questions about one interval, each starting from what the earlier ones found |
| `petroharness audit SESSION` | each answer's audit trail, back to the LAS file's hash ([EVIDENCE.md](EVIDENCE.md)) |
| `petroharness report SESSION` | the conversation as one document: answers, figures, methods and parameters, audit trails |
| `petroharness setup` | what answers a question (code, prompts, Petrophys, model and data settings), with one hash ([SETUP.md](SETUP.md)) |

## From Python

```python
from petroharness.ask import ask

r = ask("tuhua-7.las", "What are the porosity and water saturation in this formation?",
        formation="Mount Messenger", tops="formations_tuhua-7.csv", out="out/tuhua-mm")
print(r.status, r.interval)        # ok {'name': 'Mount Messenger', 'top': 590.55, 'base': 873.8616, 'unit': 'm', ...}
print(r.answer)
```

The keyword arguments mirror the command's options (`formation`, `tops`, `top`, `base`, `depth_unit`,
`lithology_curve`, `formation_lithology`, `profile`, `out`, `model`, `model_card`, `model_url`, `settings`, `skills`).
`interpretation` changes what Petrophys interprets the well with, and the zone rule, setting by setting
(`petroharness.well.settings.schema()` lists them with their defaults and help; unset settings keep their defaults):

```python
r = ask("tuhua-7.las", "Which zone has the best reservoir quality?", formation="Mount Messenger",
        tops="formations_tuhua-7.csv", interpretation={"rw": 0.05, "sw_model": "indonesia", "m": 2.2,
                                                       "zone_min_thickness_m": 1.0})
```

Without `out`, nothing is written. Wrong inputs raise `ValueError` (a formation the tops file lacks: `FormationNotFound`), with a message that
says what is wrong, why it matters and how to fix it.

## A data settings file (optional)

`--settings FILE` (or the environment variable `PETROHARNESS_DATA`) gives a data settings file to start from, with
the keys of `configs/data.example.yaml` under `data:`. Use one for what the command line does not cover: a lithology
code workbook (`lithology_nomenclature`), Petrophys options (`interpret`: a curve mapping, or workflow settings such as
`{gr_min: 30, gr_max: 120}` for gamma-ray clean and shale endpoints you know, or `{sw_model: indonesia}`), or a
shared cache folder (`cache_dir`). The shale-volume bands, and so the zones, follow Petrophys's clay volume: when its
automatic gamma-ray endpoints do not suit the well, state them this way. The command's options win over the file. When
`PETROHARNESS_DATA` is set in your shell for other work, unset it before asking about a new well, or its settings
apply (the stderr record names the settings used).

## Options

| option | meaning |
|---|---|
| `--las PATH` | the well's LAS file (required) |
| `--question TEXT` / `--question-file PATH` | the question (one of them is required) |
| `--formation NAME` | the formation: looked up in `--tops`, or a label for `--top`/`--base` |
| `--tops PATH` | a tops table (see above) |
| `--top D`, `--base D` | the interval's depths |
| `--depth-unit m\|ft` | the unit of the depths given and of the answer's depths |
| `--lithology-curve MNEMONIC` | the lithology log (default: detected; none: shale-volume bands) |
| `--formation-lithology TEXT` | the formation's lithology as you know it |
| `--profile NAME` | a Petrophys context profile, for wells of a known context package |
| `--out DIR` | the output folder (default `./petroharness-out/<LAS name>/`) |
| `--model NAME` | any chat model, by its served name (default: K2-Horizon-7B) |
| `--model-card CARD` | a model card: a YAML file or a packaged card's name ([MODELS.md](MODELS.md)) |
| `--model-url URL` | the model endpoint(s), comma-separated (default `PETROHARNESS_MODEL_URL`) |
| `--settings PATH` | a data settings file to start from |
| `--skills PATH\|none` | the skill library (default: the packaged one); `none` for no guides |
| `--max-steps N` | the investigation's step cap (default: the harness's) |
| `--investigate` | give every question a full investigation (default: the model first says whether the question is direct, a value or a fact that one or two lookups state; a direct question gets a short route and a short answer) |
