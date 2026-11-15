# v3.5.6 lock (2026-11-14)

v3.5.6 is the single-formation harness measured as arm FD (commit d16b767 with six switches set), locked on branch
`v3.5.6-lock` without changing what it does. This file records what was measured, the steps of the lock, how each step
was proven not to change behaviour, and the environment.

## The measured build

- **Code:** d16b767 with the switches `zone_order`, `see_first`, `stop_check`, `writer_points`, `writer_fresh` and
  `fresh_doubts` set (`CHANGELOG.md`, 3.5.6, says what each does). Seventeen other switches were measured and not
  adopted.
- **Models:** K2-Horizon-7B and Qwen3.5-27B GRPO, each at its card's settings (vLLM).
- **Data:** WellLogBench single-formation questions, all 347 (GeoLink 221, Costa 76, Danish 50), raw LAS, interpreted
  by Petrophys 916ca46 with each dataset's context profile.
- **Runs:** two full runs of each model, 1,388 answers in all, from a frozen copy of d16b767.
- **Judge:** GPT-5, official prompt, once per run. No Numerical Accuracy criterion.

## Result (x10 scale, mean of the two runs)

| Answering model | Version | RA | W | Runs (RA) |
|---|---|---|---|---|
| K2-Horizon-7B | 3.5.3 | 66.76 | 66.36 | |
| K2-Horizon-7B | 3.5.6 | 67.46 | 66.67 | 67.31, 67.60 |
| Qwen3.5-27B GRPO | 3.5.3 | 62.41 | 64.05 | |
| Qwen3.5-27B GRPO | 3.5.6 | 65.73 | 66.22 | 65.80, 65.65 |

- K2-Horizon-7B, 3.5.6 against 3.5.3: RA +0.69 [-0.78, +2.12], W +0.31.
- Qwen3.5-27B GRPO, 3.5.6 against the same build without the two writer changes: RA +2.21 [+0.90, +3.59].
- On one harness, K2-Horizon-7B against Qwen3.5-27B GRPO: RA +1.73 [+0.47, +3.02], W +0.44.
- Tokens per question: K2-Horizon-7B 307k (3.5.3: 281k), Qwen3.5-27B GRPO 268k (3.5.3: 225k).
- On the revised references (benchmark_revised_4, same answers): K2-Horizon-7B RA 67.46, W 66.61; Qwen3.5-27B GRPO RA
  65.85, W 66.27.

## The lock

One commit per step on branch `v3.5.6-lock`, from d16b767:

- **K1, a standalone folder.** A clone of the measured commit with its own environment (Python 3.10, the pinned
  requirements, Petrophys 916ca46 installed as a package). Nothing in the folders the measurements ran from changed.
- **K2, the measured build is the code** (1db9b7e). The six switches are built in. The 17 switches not adopted are
  removed with their code, their 15 prompt texts and the units only they ran (386 lines). `agent/options.py` keeps the
  switch framework with no fields.
  *Proof:* for each of the 1,388 saved runs, every model request was rebuilt from the recorded replies (each message
  of each call, its schema, token cap and retry flag) and compared with the one d16b767 sent, together with the status
  and the answer: 1,388 of 1,388 identical.
- **K2b, the tests assert the measured build** (bf3dba9, 9379aa2). Tests only. `tests/agent/test_measured_build.py`
  replaces the switch tests. The tests' shared formations are built on the default reporting settings, which removed
  34 failures that came from running the suite under a benchmark's data settings.
- **K3, golden tapes** (bdf55c5). The 36 golden questions (the selection is unchanged: 12 per dataset, two per
  category) recorded live on K2-Horizon-7B: 33 ok, 3 unresolved numbers. They replay exactly on the lock's code,
  component versions included.
- **K4, docs, version and one provenance fix.** Version 3.5.6, the changelog entry, this file. Full suite after it:
  1,424 passed, 11 skipped, 0 failed. The line that names
  the Petrophys build no longer takes the commit of a repository the virtual environment happens to sit in: an
  installed Petrophys is named by the commit pip recorded, else by a hash of its installed files. No prompt, tool
  result or answer reads that line; the prepared-well cache is keyed by it and is rebuilt once. Full suite at K3: 1,423 passed, 11 skipped,
  0 failed.
- **K5, smoke.** The lock's own command (`petroharness --las ... --question ...`) answered one question on one LAS
  interval with each model: both ok, 8 investigation steps each, and the two answers report the same net pay,
  porosity and saturation figures.

## Check it yourself

```bash
.venv/bin/python -m pytest tests -q            # the suite: tapes, prompt fixture, lint, generality, UI
PYTHONPATH=src:tests/agent WELLLOGBENCH=<data configs> \
    .venv/bin/python tests/agent/record_golden.py replay   # the 36 tapes, replayed with no model
```

The data tests need `WELLLOGBENCH` (the folder of the datasets' data configs) and `PETROHARNESS_DATA` (one of them).
Without them those tests skip.

## Known limits

- Replaying many questions in several threads of one process is not fully deterministic: one or two of 1,388 runs can
  differ in a calculation result. The proof above replays one run per process. Real batch runs use many threads and
  have the same exposure; the cause is in the on-request calculation path and is not yet found.
- The answers of Qwen3.5-27B GRPO still add detail the reference lacks more often than those of K2-Horizon-7B (66 to
  71% of answers against 54 to 59%). Every further writer change that was tried did not help or cost accuracy.
