# The gates

A change to the harness is either meant to alter what the model is sent, or it is not. These tools prove which.

| Gate | Proves | Needs | Run |
|---|---|---|---|
| Public mini set | A recorded conversation on a Petrophys sample well replays request for request, with the same answers | Nothing: no model server, no private data | `pytest tests/gate -q` |
| Golden tapes | 36 recorded benchmark questions replay with the same requests, answers and traces | The benchmark's data settings (`WELLLOGBENCH`) | `pytest tests/agent/test_golden_tapes.py -q` |
| Request gate | Every request of every saved run of the reference runs is rebuilt unchanged: the head's route, and the `--investigate` route on the 3.5.6 runs | The benchmark's data and the saved runs | `python tests/gate/request_gate.py record ...` then `compare` |

Use them in that order. The mini set takes a few minutes and runs anywhere. The request gate is the widest and is the
one a maintainer runs before a change to the question graph is merged.

## The public mini set

`tests/gate/mini/<name>/` holds one recorded conversation: `set.json` (the sample well, the formation, the questions,
the interval, the Petrophys build and the setup it was recorded with, and what each question must reproduce) and, for
each question, its tape (every model request and reply) and its answer.

`test_mini.py` starts the same conversation on the same sample well and answers the model's calls from the tape. The
replayer compares each request with the recorded one and stops at the first difference, naming the call and the place.
The answers, the results opened, the number links, the steps behind them and the figures chosen must come out the
same. Then the interval's display and the audit trail are checked.

Record it again only when a change is meant to alter what the model is sent or how a conversation runs:

```bash
PETROHARNESS_MODEL_URL=http://HOST:PORT/v1 python tests/gate/record_mini.py
```

A different Petrophys version computes different curves, so different prompts. The test then skips and says which
version the set was recorded with.

## The request gate

```bash
# on the reference build, once
python tests/gate/request_gate.py record --runs RUNS --prefix PREFIX --ids IDS.json --card CARD --out base/PREFIX.jsonl
# on the changed code
python tests/gate/request_gate.py record --runs RUNS --prefix PREFIX --ids IDS.json --card CARD --out new/PREFIX.jsonl
python tests/gate/request_gate.py compare base/PREFIX.jsonl new/PREFIX.jsonl
```

For each saved run the question is run again with the model's replies taken from the run's trace, and every request
the code builds is hashed: each message of each call, its schema, its token cap, its temperature and its retry flag,
with the status and the answer. `compare` counts every difference by kind and exits 0 when there is none.

Replay one run at a time per process (`--workers 1`, the default), and start one process per run set to use the
machine's cores. Replays in several threads of one process are not fully deterministic.

## When a gate fails

A failure means the change reaches the model. If that was not intended, the difference named is the bug. If it was
intended, it is a behaviour change: measure it end to end (`docs/DEVELOPMENT.md`), then record the tapes and the mini
set again in the same change.
