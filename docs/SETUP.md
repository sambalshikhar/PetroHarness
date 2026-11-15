# The setup of a run

A setup is one flat record of what answers a question: the harness code, its prompt components, the Petrophys build
and the functions it offers, the skill library, the model's request settings and the data settings. One hash stands
for the record. Two runs with the same hash were made of the same parts; where the hashes differ, the records say in
which part.

- [Print it](#print-it)
- [What it holds](#what-it-holds)
- [Where it is recorded](#where-it-is-recorded)
- [Compare two](#compare-two)

## Print it

```bash
petroharness setup                              # the default model, no data settings
petroharness setup --model-card my_card.yaml --settings field.yaml
petroharness setup --json
```

The options are the ones `petroharness` and `petroharness chat` take for the model, the settings and the skills
([USAGE.md](USAGE.md)).

## What it holds

| Part | What it is |
|---|---|
| `harness`, `commit` | The package's version, and its commit for a source checkout |
| `petrophys` | The Petrophys build: its version and its own commit, or a hash of its installed files |
| `components` | Each prompt component with its version: the texts every model call is built from |
| `functions` | One hash over the Petrophys functions the tools offer (name, verb, parameters). The list is part of the investigation's brief, so a Petrophys release that adds a function changes it |
| `skills` | The skill library: its name and version |
| `model`, `card` | The model's name as served, and a hash of its request settings (temperature, token caps, template settings) |
| `data`, `policy` | A hash of the data settings in force (interpretation, zones, bases, conventions), and of the interpretation policy file |
| `writer`, `fmt`, `max_steps` | The writer's repair rounds, the reader format, the investigation's step cap |
| `mode` | `interactive` (a LAS file and a question) or `tasks` (prepared questions) |
| `depth` | whether the model first says if a question is direct (a short route) or needs an investigation |

Where a model is reached (the endpoint, the API key, timeouts, retries) is not part of a setup, and neither are the
folders on this machine. They do not change what answers.

## Where it is recorded

- **The session log.** A `setup` event with the hash and every part, written before the first question and again
  only when the setup changes (for example a conversation resumed after an upgrade).
- **Every question's trace** (`trace.json`, `setup`): the hash.
- **The audit trail** (`petroharness audit`): the hash, in its Source section.

## Compare two

```python
from petroharness.core import setup

setup.differences(record_a, record_b)     # ["card", "components.C9"]: the parts that differ; [] for the same setup
```
