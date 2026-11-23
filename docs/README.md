# PetroHarness documentation

PetroHarness runs formation evaluation from a raw LAS file: Petrophys interprets the log, a language model
investigates the interval step by step with Petrophys's tools, and code checks and records every step, so every number
in an answer traces back to the log. Start with the reading path for what you want to do.

![The Brent Group in GeoLink well 30/6-5](images/geolink-30_6-5-brent.png "The interval most examples in these pages evaluate: the Brent Group (2841–2958 m) in GeoLink well 30/6-5, a well that ships with Petrophys, with a lithology log and core. Data: GeoLink, CC BY-SA 4.0.")

## 1. Start here

| You want to | Read, in this order |
|---|---|
| See what it does with hard questions | [EXAMPLES](EXAMPLES.md) → [USAGE](USAGE.md) |
| Evaluate a formation in your own wells | [README quick start](../README.md) → [USAGE](USAGE.md) → [SESSIONS](SESSIONS.md) → [UI](UI.md) |
| Run it with your own model | [MODELS](MODELS.md) → [Model cards and configuration](reference/CONFIGURATION.md) |
| Choose how Petrophys interprets the well | [Interpretation settings](reference/INTERPRETATION_SETTINGS.md) → [Well preparation](reference/WELL_PREPARATION.md) |
| Understand how an answer is produced | [ARCHITECTURE](ARCHITECTURE.md) → [GRAPH](GRAPH.md) → [Investigation state](reference/INVESTIGATION_STATE.md) → [Writer and checker](reference/WRITER_AND_CHECKER.md) |
| Check an answer, number by number | [EVIDENCE](EVIDENCE.md) → [Records](reference/RECORDS.md) |
| Script it or build on it | [Python API](reference/PYTHON_API.md) → [Command line](reference/CLI.md) → [Web UI API](reference/WEB_UI_API.md) |
| Add a tool, a guide or a model | [DESIGN](DESIGN.md) → [Extending](reference/EXTENDING.md) → [Testing](reference/TESTING.md) |

## 2. Guides

How to do something, with examples.

| Page | What it covers |
|---|---|
| [EXAMPLES](EXAMPLES.md) | Complex questions answered: two formations compared, net pay's sensitivity, logs against core, missing logs, a carbonate against a clastic reading, a fluid contact |
| [USAGE](USAGE.md) | Evaluating a formation from any LAS file: intervals, tops files, units, lithology, output |
| [SESSIONS](SESSIONS.md) | Conversations: follow-up questions, figures, settings mid-conversation, field notes, resume |
| [UI](UI.md) | The web UI: the page, its options and its runs |
| [MODELS](MODELS.md) | Serving a model, model cards, reasoning models, hosted APIs |
| [TOOLS](TOOLS.md) | What the model can ask Petrophys for, by kind of request |

## 3. Concepts and architecture

How the parts fit together and why they are built this way.

| Page | What it covers |
|---|---|
| [ARCHITECTURE](ARCHITECTURE.md) | The parts, and how a question flows through them |
| [GRAPH](GRAPH.md) | The three graphs: the question graph node by node with the direct route, the later-question graph and the session graph |
| [EVIDENCE](EVIDENCE.md) | Auditing an answer: the evidence graph, the audit trail, the report, and the setup record under one hash |
| [DESIGN](DESIGN.md) | The design rules and the generality contract |

## 4. Reference

Every command, field, setting, tool, record and step, with types, defaults and where each is defined.

**Using PetroHarness**

| Page | What it covers |
|---|---|
| [Command line](reference/CLI.md) | Every command and flag of `petroharness`, and the chat commands |
| [Python API](reference/PYTHON_API.md) | `ask()`, `prepare()`, `Conversation` and the result objects |
| [Configuration](reference/CONFIGURATION.md) | The data config file, environment variables and precedence |
| [Interpretation settings](reference/INTERPRETATION_SETTINGS.md) | Every Petrophys setting, the zone rule, cutoffs and field notes |
| [Web UI API](reference/WEB_UI_API.md) | The HTTP routes, jobs, progress events and storage of `petroharness ui` |

**How an answer is made**

| Page | What it covers |
|---|---|
| [Well preparation](reference/WELL_PREPARATION.md) | From the raw LAS to the interval: units, tops, zones, the interpretation, the map |
| [Investigation state](reference/INVESTIGATION_STATE.md) | The ledger, claims and points, the step loop, budgets and replies |
| [Prompt components](reference/PROMPT_COMPONENTS.md) | The ten text components, their versions, and how each request is built |
| [Tools](reference/TOOLS_REFERENCE.md) | Every tool the model can call, with arguments and results |
| [Petrophys integration](reference/PETROPHYS_INTEGRATION.md) | The verbs, the function registry, the binder and the figures |
| [Skills](reference/SKILLS.md) | The skill library: topic areas, guide format, provenance, your own library |
| [Writer and checker](reference/WRITER_AND_CHECKER.md) | Writing, checking, repairing and delivering the answer |
| [Records](reference/RECORDS.md) | `answer.md`, `trace.json`, the session log, the setup record, the evidence graph |

**Words used throughout**

| Page | What it covers |
|---|---|
| [Glossary](reference/GLOSSARY.md) | The terms these pages use, in one place |

## 5. Working on the code

| Page | What it covers |
|---|---|
| [Testing](reference/TESTING.md) | The test suite, its markers, and every regression gate |
| [Extending](reference/EXTENDING.md) | Recipes: a tool, a guide, a report style, a model card, a figure, a switch |
| [DEVELOPMENT](DEVELOPMENT.md) | Configuration, benchmark mode, testing and the code layout |
| [CONTRIBUTING](../CONTRIBUTING.md) | Where a contribution goes and how to show a change is safe |
| [AGENTS](../AGENTS.md) | The rules for changing the code |
| [CHANGELOG](../CHANGELOG.md) | The releases |

## 6. How these pages are organised

Each page opens with what most readers need: a short lede, a figure or diagram, and the shortest path through the
topic; the rest sits in collapsible blocks titled by what they hold. Reference pages open with "At a glance" (the key
facts in one table or diagram) and "How it works" (the flow, with the function that does each step), then one section
per command, class, tool, setting group or file format. Code locations are paths under
[`src/petroharness/`](../src/petroharness/), so every statement can be checked against the code.

The examples run on wells that ship with Petrophys, each chosen for the case it shows:

| Case | Well | Data |
|---|---|---|
| A clastic reservoir with a lithology log, core and a tops file: the main example | GeoLink 30/6-5, Brent Group | GeoLink, CC BY-SA 4.0 |
| Core against the logs, the interval given by depth | GeoLink 25/5-1 | GeoLink, CC BY-SA 4.0 |
| Missing logs (no neutron, no PEF) and an evaporite section | GeoLink 16/7-1 | GeoLink, CC BY-SA 4.0 |
| A mineral solve with a vendor lithology log | GeoLink 15/9-14 | GeoLink, CC BY-SA 4.0 |
| No lithology log: zones from the lithology Petrophys's mineral solver gives | Taranaki tuhua-7, cheal-1 | Taranaki Basin Curated Well Logs Dataset (New Zealand Petroleum & Minerals), CDLA-Sharing-1.0 |
| A carbonate logged in feet, one tops table for many wells | COSTA HW-3 to HW-32 | Costa Gomes, Geiger and Arnold (2022), COSTA model, Heriot-Watt University, CC BY |
| Bad curve units and a generic tops file | KGS 1046123714 (Morgan No. 1-17) | Kansas Geological Survey (kgs.ku.edu) |
| Old wells in feet, a whole-log question | Teapot 17-WX-21, 44-MDX-10 | Teapot Dome (NPR-3), RMOTC, U.S. Department of Energy |
