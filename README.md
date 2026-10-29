<div align="center">

<img src="src/petroharness/ui/static/img/petroharness_logo.svg" alt="PetroHarness" width="440">

### Ask a well a question. Get an answer you can audit.

PetroHarness turns a raw LAS file and a question in plain language into a petrophysical interpretation.<br>
Petrophys computes it, a language model investigates it step by step, and code checks the result.<br>
Every number in the answer traces back to the log.

**Petrophys calculates · the model investigates · the harness records · you decide**

[![Version](https://img.shields.io/badge/version-3.5.2-011e3f)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-3.10-011e3f)](#install)
[![Models](https://img.shields.io/badge/models-any%20OpenAI--compatible%20LLM-ef6719)](docs/MODELS.md)
[![Default model](https://img.shields.io/badge/default-K2--Horizon--7B-ef6719)](docs/MODELS.md)
[![Calculations](https://img.shields.io/badge/calculations-Petrophys-197e6f)](https://github.com/sambalshikhar/petrophys)
[![Paper](https://img.shields.io/badge/paper-ADIPEC%202026%20%C2%B7%20SPE--236034--MS-011e3f)](#citation)

[Quick start](#quick-start) · [How it works](#how-it-works) · [Your own wells](docs/USAGE.md) · [Models](docs/MODELS.md) · [Web UI](docs/UI.md) · [Architecture](docs/ARCHITECTURE.md) · [Citation](#citation)

<img src="docs/images/ui-answer.png" alt="The PetroHarness web UI: a question about the Mount Messenger formation of a well, answered, with the interval used, the topic areas read, the skills used and the zone table" width="100%">

</div>

## Why PetroHarness

Interpreting a well log is a chain of small expert decisions. Which curves can be trusted? Which zones matter? Which
cutoff applies? What does a reading mean? A language model handed the whole log at once guesses at them. PetroHarness
gives the model a petrophysicist's way of working instead, and keeps a record of every step.

<table>
<tr>
<td width="33%" valign="top">

#### Every number is traceable
Each number in an answer cites the result it came from. Each result keeps the tool call that opened it, and each
value in it names its source: a measurement, or the Petrophys step that computed it. The trace can rebuild every
prompt.

</td>
<td width="33%" valign="top">

#### An investigation, not a data dump
The model reads a map of the well, then opens only what it needs, zone by zone, over up to eight steps. Along the way
it builds claims that cite their evidence.

</td>
<td width="33%" valign="top">

#### Any LAS file
You give a raw LAS file, and formation tops from any table, a depth window or the whole well. No lithology log? The
well is zoned by shale volume. Depths can be in feet or metres, even mixed.

</td>
</tr>
<tr>
<td valign="top">

#### Petrophys calculates
Clay volume, porosity, saturation, permeability, net pay, analyzer classes and statistics all come from
[Petrophys](https://github.com/sambalshikhar/petrophys). Ask for another method (Simandoux, Timur, a new Rw, other
cutoffs) and the model has Petrophys compute it, from about 300 of its functions.

</td>
<td valign="top">

#### Code checks, the model decides
Code checks each claim's citations and numbers, and any statement that data is missing, and shows the model the
facts it finds. Code never rewrites a grade, a verdict or a sentence.

</td>
<td valign="top">

#### Bring your own model
Use any chat model behind an OpenAI-compatible endpoint: vLLM, SGLang, Ollama, LM Studio or a hosted API.
K2-Horizon-7B is the default. Serve the model yourself and the well data stays on your machines.

</td>
</tr>
</table>

## See the investigation

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/ui-progress.png" alt="The progress tab: the topic areas the model read, then each step with its points, the tools it called and the results it opened"></td>
<td width="50%" valign="top"><img src="docs/images/ui-claims.png" alt="The claims tab: each claim with its grade, what it means, what weakens it, and the results it cites"></td>
</tr>
<tr>
<td valign="top"><b>Follow it live.</b> You can see the topic areas the model chose, and each step's working points, tool calls and opened results, as they happen.</td>
<td valign="top"><b>Check every claim.</b> Each claim shows its grade, what it means, what weakens it and the results it cites. Code's fact checks appear beside it.</td>
</tr>
</table>

## What you can ask

PetroHarness answers questions about one interval of one well: a formation, a depth window or the whole log. A
question can touch any of the topic areas below. The model chooses the topics a question needs, and the skill library
holds a sourced guide for each.

| Rock | Fluids | Reservoir quality | Data and methods |
|---|---|---|---|
| lithology and mineralogy | water saturation | porosity | data quality |
| shale and clay | hydrocarbon detection | permeability and rock quality | statistics and data analysis |
| log facies and stratigraphy | fluid contacts | net reservoir and pay | core-log integration |
| elastic properties | invasion and movability | | |

For example:

> *Where are the best reservoir intervals in this formation? Give their porosity, shale volume and water saturation, and say whether any of them looks hydrocarbon-bearing.*
>
> *Are there any hydrocarbon indicators in this well?*
>
> *How reliable are the density and neutron logs over this interval, and where is the hole washed out?*
>
> *Is there a fluid contact in this sand, and at what depth?*
>
> *Can you compute saturation with Simandoux and give me the statistics?*
>
> *How does net pay change if the water saturation cutoff is 0.5?*

## How it works

```mermaid
flowchart LR
    las["Raw LAS file"]:::input
    where["Tops file, depths,<br/>or the whole well"]:::input
    q["Your question"]:::input
    pp["Petrophys<br/>interprets the well"]:::petrophys
    rec[("The record<br/>zones, curves, classes,<br/>statistics")]:::record
    read["Read<br/>topics and named<br/>measurements"]:::model
    inv["Investigate<br/>up to 8 steps: tools,<br/>ledger, cited claims"]:::model
    skills[("Skill library<br/>sourced guides")]:::record
    settle["Settle<br/>final claims"]:::model
    write["Write and check<br/>repairs"]:::model
    out["Answer and<br/>full trace"]:::output

    las --> pp
    where --> pp
    pp --> rec
    rec -- "map and first look" --> inv
    q --> read --> inv
    skills -. "guides" .-> inv
    inv --> settle --> write --> out

    classDef input fill:#ffffff,stroke:#011e3f,color:#011e3f
    classDef petrophys fill:#e3f2ee,stroke:#197e6f,color:#0f4f45
    classDef record fill:#f0eeea,stroke:#9aa0aa,color:#1c2433
    classDef model fill:#e6ecf4,stroke:#011e3f,color:#011e3f
    classDef output fill:#fdeee4,stroke:#ef6719,color:#7a3410
```

| Stage | What happens |
|---|---|
| **1 · The well** | Petrophys interprets the raw LAS and cuts it to your interval. The interval is zoned by its lithology log, or by shale-volume bands when there is none. |
| **2 · Read** | The model chooses the topic areas the question touches, and lists the measurements the question names. |
| **3 · Investigate** | Up to eight steps, each one model call rebuilt from the state. The model opens results with tools (statistics zone by zone, analyzer classes as located depth runs, profiles, comparisons, crossplots, overlaps, arithmetic), has Petrophys compute what the record does not hold (another method, an estimate, a what-if, any of its functions), and adds, revises or drops claims that cite them. Code checks each claim as it arrives. |
| **4 · Settle** | With every opened result in view, the claims become final. |
| **5 · Write and check** | The writer composes the answer from the settled claims. A checker sends back numbers no result shows, statements the record contradicts and leftover working notes, for repair. |

The parts in detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The question graph, node by node:
[docs/GRAPH.md](docs/GRAPH.md). The design rules: [docs/DESIGN.md](docs/DESIGN.md).

## Quick start

### Install

```bash
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install "petrophys @ git+https://github.com/sambalshikhar/petrophys.git@916ca46c37980ceac56a0c4ac94b2eb0f8d8632c"
.venv/bin/pip install -e . --no-deps
```

This installs the `petroharness` command. Petrophys is pinned at commit `916ca46`.

### Connect a model

Point PetroHarness at any OpenAI-compatible endpoint:

```bash
export PETROHARNESS_MODEL_URL=http://localhost:8000/v1     # several servers: comma-separated
```

The default model is K2-Horizon-7B. To use any other chat model, give its served name with `--model`:

```bash
petroharness --model Qwen/Qwen3-32B --las well.las --question "..."
```

How to serve a model with vLLM, SGLang or Ollama, a reasoning model's settings, a hosted API, and model cards:
[docs/MODELS.md](docs/MODELS.md).

### Ask

```bash
petroharness --las well.las --tops tops.csv --formation "Mount Messenger" \
    --question "Where are the best reservoir intervals, and is any of them hydrocarbon-bearing?"
```

| You have | Choose the interval with |
|---|---|
| a tops file | `--tops tops.csv --formation NAME` (CSV, TSV or Excel; its columns are found by meaning) |
| depths | `--top 5340 --base 5600 --depth-unit ft` |
| neither | nothing: the whole well is the default |

The answer is printed. `answer.md` and `trace.json` are written to `./petroharness-out/<well>/`; the trace holds
every model call and every result opened. With no lithology log, the well is zoned by shale volume
(`--lithology-curve` names one the harness does not find, and `--formation-lithology` states what you know). Every
option, with examples on three wells: [docs/USAGE.md](docs/USAGE.md).

### In the browser

```bash
petroharness ui                      # http://127.0.0.1:7860
```

In the browser you can:

- pick a LAS file and the interval, and ask your question;
- follow every model call live;
- read the answer with its claims, its citations and the record behind it.

Runs are saved, and can be rated and replayed. See [docs/UI.md](docs/UI.md).

### From Python

```python
from petroharness.ask import ask

result = ask("well.las", "Are there any hydrocarbon indicators?", tops="tops.csv", formation="Oread",
             model="Qwen/Qwen3-32B", model_url="http://localhost:8000/v1")
print(result.answer)          # result.trace: every call and every result opened
```

## Make it yours

| Part | How to change it |
|---|---|
| **Models** | Any chat model, by name or by a model card with its own request settings. See [docs/MODELS.md](docs/MODELS.md). |
| **Petrophys tools** | Every public Petrophys function is reachable by request; a function added to Petrophys appears with no change here. See [docs/TOOLS.md](docs/TOOLS.md). |
| **Skill library** | Plug in your own guides with `--skills PATH`, or run with none (`--skills none`). A library is checked as it loads. See [skills/README.md](src/petroharness/resources/skills/README.md). |
| **Interpretation** | Petrophys's default workflow, a Petrophys context profile (`--profile`), or an interpreter of your own. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#configuration). |
| **Benchmark mode** | Run a question file with reference answers in parallel, for validation (`petroharness benchmark`). See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#benchmark-mode). |

## Built on Petrophys

<table>
<tr>
<td width="200" align="center" valign="middle">
<a href="https://github.com/sambalshikhar/petrophys">
<img src="docs/images/brand/petrophys-logo.png" alt="Petrophys" width="180">
</a>
</td>
<td valign="middle">

[Petrophys](https://github.com/sambalshikhar/petrophys) turns well logs into traceable petrophysical
interpretations: clay volume, porosity, water saturation, permeability, rock quality and net pay. Every step records
its method, inputs, outputs and parameters, and every skipped step records why. PetroHarness reads that record. It
never recomputes petrophysics on its own. Documentation: [petrophys.netlify.app](https://petrophys.netlify.app).

</td>
</tr>
</table>

## Documentation

| Guide | What it covers |
|---|---|
| [docs/USAGE.md](docs/USAGE.md) | asking about your own wells: intervals, tops files, units, lithology, output, the Python API |
| [docs/TOOLS.md](docs/TOOLS.md) | the tools by request, and Petrophys's functions: calculate, estimate, what_if, check, classify, summarize, calibrate |
| [docs/MODELS.md](docs/MODELS.md) | models: serving, model cards, reasoning models, hosted APIs |
| [docs/UI.md](docs/UI.md) | the web UI: options, the parts of the page, its API |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | the parts, and how a question flows through them |
| [docs/GRAPH.md](docs/GRAPH.md) | the question graph, node by node |
| [docs/DESIGN.md](docs/DESIGN.md) | the design rules and the generality contract |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | configuration, benchmark mode, testing and the code layout |
| [AGENTS.md](AGENTS.md) | the rules for changing the code |
| [CHANGELOG.md](CHANGELOG.md) | the releases |

## Citation

If you use PetroHarness in your work, please cite the paper:

> **PetroHarness: An Open-Source Agentic Harness for Auditable Formation Evaluation**<br>
> S. Shikhar, Z. Kabashev, S. Umurzak, M. Lee, L. Barillas, S. Bharadwaj, J. Thomas, J. Lahoud, F. Castanedo, H. Cholakkal<br>
> ADIPEC 2026, paper SPE-236034-MS<br>
> Mohamed bin Zayed University of Artificial Intelligence (MBZUAI) · Khalifa University · Inception42 · AIQ; Abu Dhabi, United Arab Emirates

```bibtex
@inproceedings{shikhar2026petroharness,
  title     = {PetroHarness: An Open-Source Agentic Harness for Auditable Formation Evaluation},
  author    = {Shikhar, S. and Kabashev, Z. and Umurzak, S. and Lee, M. and Barillas, L. and Bharadwaj, S. and Thomas, J. and Lahoud, J. and Castanedo, F. and Cholakkal, H.},
  booktitle = {ADIPEC 2026},
  number    = {SPE-236034-MS},
  publisher = {Society of Petroleum Engineers},
  year      = {2026}
}
```

<div align="center">
<br>
<img src="src/petroharness/ui/static/img/petroharness_logo.svg" alt="PetroHarness" width="160">
&nbsp;&nbsp;&nbsp;
<img src="docs/images/brand/petrophys-logo.png" alt="Petrophys" width="110">
</div>
