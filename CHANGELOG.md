# Changelog

## 1.3.0 (2026-11-27)

WellLogLLM, our post-trained model, is the default, and the web UI connects any model.

- **WellLogLLM-3.7B by default.** With no model option and no `PETROHARNESS_MODEL_URL`, `petroharness --launch-ui`
  and `petroharness` answer with WellLogLLM-3.7B as a GGUF in Ollama on this computer, with or without a GPU: Ollama
  pulls it from Hugging Face (`sambal/WellLogLLM-3.7B-GGUF`, 5.4 GB for Q8_0) the first time, and PetroHarness makes a
  copy with the 65,536-token context the harness needs.
- **The Model dialog.** The model's name in the top bar opens it: WellLogLLM-3.7B or any model in Ollama, a vLLM
  server (with the commands that serve WellLogLLM-7B and -3.7B, and its API key), or OpenRouter (its models listed with
  context window and price). It switches the model while the server runs; questions already asked keep theirs. The
  choice is kept for the next start and for the command (`model.json`), and API keys in `keys.json`, readable by their
  owner only and never sent to the page. A server listening beyond this computer keeps the model it was started with.
- **WellLogLLM-7B as a GGUF too** (`sambal/WellLogLLM-7B-GGUF`, 9.6 GB in Q8_0), in the dialog beside the 3.7B: on a
  Mac, both run on the GPU through Metal, as any model in Ollama does.
- **What is not ideal, said.** Before connecting, the dialog checks this computer for the model chosen: memory, GPU
  (Apple silicon, NVIDIA or AMD) and the disk space for the download, with what to do; once connected, it loads the
  model and says where Ollama put it, and a model not all on the GPU is marked in the top bar and by the command.
- **Model cards** `welllogllm_7b`, `welllogllm_3_7b` (vLLM), `welllogllm_7b_gguf` and `welllogllm_3_7b_gguf`
  (Ollama): K2-Horizon-7B's request settings under WellLogLLM's names; the GGUF cards ask for JSON in the prompt alone
  and allow longer requests.
- **Install and set up** (`docs/INSTALL.md`): every step per system, the sizes, where the choice is kept, and what to
  do when something goes wrong. The README's quick start starts from it.
- The endpoint health check carries the card's API key, so a server that wants one shows as healthy.

## 1.2.0 (2026-11-26)

PetroHarness installs from PyPI, and credits the data behind its results and its examples.

- **`pip install petroharness`.** PetroHarness and Petrophys are on PyPI; PetroHarness depends on `petrophys==3.0.0`,
  the release it is tested with, in place of a Petrophys commit installed from GitHub. Installing from a clone is in
  the README's quick start and in CONTRIBUTING.
- **Data and acknowledgements.** `THIRD_PARTY_DATA.md`, shipped in the package, credits the WellLogBench data the
  results come from (GeoLink, COSTA, the Danish wells of GEUS) and the Petrophys sample wells the quick start, the
  documentation and the tests use (GeoLink, COSTA, Taranaki, the Kansas Geological Survey, Teapot Dome), each with its
  licence; the README has a section on it.
- **Petrophys's documentation** is at [welllogbench.com/petrophys/docs](https://welllogbench.com/petrophys/docs/).
- **One build of Petrophys per release.** An installed Petrophys is identified by its own files, not the bytecode pip
  writes at install, so a release is the same build on every Python version; the public mini set replays with
  Petrophys 3.0.0 from PyPI.

## 1.1.1 (2026-11-26)

PetroHarness on Petrophys's merged mineral solver. On wells with a lithology log every value is as in 1.1.0; mineral
volumes and the lithology zones solved from them change on wells without a lithology log or without NPHI.

- **Petrophys 821afba.** The pin moves to Petrophys's latest dev (8 commits after 3a9378e).
  - Petrophys has one mineral solver (`MultiMineralSolver`) where it had two versions: where a sample has NPHI and
    PHIE it takes them as given, elsewhere it solves porosity with the minerals (quartz and calcite, or calcite and
    dolomite in carbonate, where the logs resolve no more). The `mineral_solver_version` setting is gone from
    Petrophys and from the settings panel, and the record no longer lists it. The `classify` minerals tool says
    "multi-mineral solver" without a version.
  - Mineral volumes and the lithology zones solved from them change on wells without a lithology log or without
    NPHI. The benchmark's wells read the same: on the 36 golden questions the only change in what the model is sent
    is the record line `mineral_solver_version 1`, gone.
  - New in Petrophys's record, shown as it writes them: warnings of net pay where the gamma ray reads shale and
    neutron-density clean, and of held readings; why SW is 1 below 0.01 v/v porosity, why minerals are zero where
    clay and porosity fill the rock, and how a sandstone- or dolomite-scale neutron is converted to limestone.

## 1.1.0 (2026-11-25)

PetroHarness on Petrophys's latest calculations, and a one-line start for the web UI.

- **`petroharness --launch-ui`** starts the web UI and opens it in your browser (`petroharness ui --open`; any of
  the UI's options go with it, e.g. `--model`, `--model-url`, `--port`). On a Linux machine with no display it opens
  nothing and prints the address to open, with the SSH port forward for a remote machine.
- **The README starts with the quick start:** install, connect a model (vLLM, SGLang, Ollama or a hosted API), launch
  the UI.
- **Petrophys 3a9378e.** The pin moves to Petrophys's latest dev.
  - Its functions have shorter names (`fit_poro_perm`, `gradient_from_bht`, `pay_averages`, `bad_hole_flags`, ...):
    the tools call them so, and each result names the function it came from.
  - Figures are drawn by its new plots, on `petrophys` (`pp.plot`, `pp.crossplot`, `pp.pickett_plot`, ...). Flow
    units are drawn from the core plugs, and the net flags (`zone_flags_plot`) take the place of the net-pay summary
    plot. A Pickett or Hingle plot shows clean rock only, and its caption counts the samples it draws.
  - A temperature, gradient or depth setting carries its unit (`bht`, `td`, `surface_temp`, `temperature_gradient`,
    `rw_meas_temp`, `rmf_meas_temp`, `rm_meas_temp`): the settings panel, `/set` and `ask(interpretation=...)` take
    `"110 degC"`, or a number in the unit shown. Settings under the earlier names (`bht_f`, `td_ft`, ...) are refused.
  - Its record is worded in petrophysical terms. The card the model reads states the same facts as before: the
    saturation routing, the net-pay cutoffs and the curves RQI, PHI_Z, FZI, MHI and PHIT are computed from.
  - What Petrophys computes changes where it changed: Rw from your settings before the LAS header's, salt, anhydrite
    and gypsum out of net rock, SW and SXO 1 where effective porosity is below 0.01 v/v, the mineral solve, and the
    menu of `check` (28 functions, depth matching among them).

## 1.0.0 (2026-11-23)

A stop button in the web UI, and three fixes for conversations and for questions typed freely. A single question on
one interval is answered as in 0.9.1: its prompts and its replies do not change.

- **Web UI: a question that is waiting or running can be stopped.** While a question waits or is being answered,
  the button of the box at the bottom is Stop. A question still waiting is taken off the queue; one running ends as
  soon as the model call in flight is left, usually within a second. A stopped question is no failure: it has no
  answer, the work it had done stays on the page, and the next question continues the same conversation
  (`docs/UI.md`, *Stopping a question*; `POST /api/stop/ID`).
- **After a change that cuts the zones anew, a zone id of before is not read as the zone of that id now.** A zone
  rule cuts the zones anew, and so do the lithology domain of a well without a lithology log and zones of your own;
  `Z3` then names another stretch than it did, and a later question compared the two as one zone. The next questions
  are now shown the zones as they were, each with where its depths lie now; a result opened before says that its zone
  ids are the zones of then; and a zone asked of such a result is found by the zones it was opened under. The
  session's log keeps the zones of before (`zones_before`). See `docs/SESSIONS.md`, *What a settings change does*.
- **The reply that reads a question says what the model means.** Where you type freely (a conversation, the web
  UI), the reply that reads a question is typed by a schema. Three faults came from what that schema could not hold:
  - A question about the well was now and then answered with "That is outside what I do here". The reply had to
    choose the kind of answer from three words, and a reply whose reasoning meant another word came out as `outside`.
    The kind of answer is now the model's own word, and only `outside` is read as outside.
  - A request outside the well's logs was now and then investigated. The reply had to name a topic for a request
    that needs none, and then went on as for a question about the well. Such a reply may now name no topic.
  - After a stretch chosen by its depths for a name the tops file lists more than once (`/scope 874-1250 m` for "the
    Manganui"), the next question was often computed on another unit with a similar name. The scope in force was
    shown by a label the reply could not write back. It is now shown as the reply writes it: a name the map lists
    once, else its depths.
- **A reply that fills with whitespace is ended and asked again.** A server that types a reply by a grammar may let
  whitespace stand between its tokens, and a model now and then wrote nothing else up to the token cap: about 2 in
  1,000 questions waited eight minutes before the question was read again. The two calls with a reply schema (reading
  the question, choosing the figures) are now read as they stream, and a reply that runs 400 characters of
  whitespace on end is ended there and asked again, in seconds.

## 0.9.1 (2026-11-23)

The harness, its prompts and its tools are as in 0.9.0: no answer changes.

- **Web UI: a step shows what it produced beside its reasoning.** On the Interpretation page, each step of the work
  lists its points to settle (step 1), what it looked at, the results it opened and the findings it added or revised,
  each with its grade, then the model's reasoning for the call; the settle step lists its edits, and a repair what
  the checker found. In the Investigation log, the cards of the read, each step, the settle step, the writer and each
  repair end with the call's reasoning. Both views build a step from the same parts.
- **Web UI fixes.**
  - A dropped finding keeps its small badge; it drew as a large block.
  - The answer block shows the items of a list its opening introduces, each by its first sentence; the opening alone
    ended on its colon.
  - A long curve name stays inside its box in *How it was computed*.
  - The reasoning lines shown skip more lines that only announce the reply.
- **Docs.**
  - `docs/TOUR.md`: one question from start to finish in the web UI, in pictures, with the command that does the same.
  - `docs/TRACE.md`: reading the work behind an answer: the calls of a question, which text is checked and which is
    not, a step part by part, the reasoning, and where each of these is in the files.
  - `docs/EXAMPLES.md`: five more worked examples, each with the steps of its investigation: a direct question, a
    conversation that changes the pay cutoffs, a whole well, your own zones, the solved minerals against the
    lithology log.
  - The web UI's screenshots are retaken on the page as it is, several with numbered callouts.

## 0.9.0 (2026-11-23)

- **Licence.** PetroHarness is released under CC BY 4.0 (`LICENSE`).
- **The default model card asks the server for `k2-horizon-7b`**, the name docs/MODELS.md serves K2-Horizon-7B
  under. A server that serves it under another name adds this one (vLLM: `--served-model-name OTHER k2-horizon-7b`).
- **No Petrophys function that reads or writes a file is offered.** The verbs reach 304 functions; CSV and LAS
  readers are left out, and an optional output path is not offered.
- **Fixes to answers.**
  - A curve recomputed under the same name with other values is no longer served stale.
  - `where: "Z1-Z5"` covers every zone of the range, and a range written deeper first ("Z5-Z2") no longer selects
    every zone.
  - A curve a verb writes never takes a name the record holds (it gets `_LIB`).
  - Two parts of one result that start alike are both written.
  - An answer that cites your field notes or your scope is no longer taken for the model's working notes.
  - A table of your own (medians, NET_PAY runs) is no longer removed as a repeat of the zone table.
  - The repair request reads arithmetic written before a number whole.
- **Inputs.** A LAS logged bottom up is refused where it is read, with the fix. `petroharness setup --las ... --zones
  FILE` includes your zones in the data settings it prints, so its hash is the one your conversation logs.
- **Conversations.** A later question starts with no scope of its own when its reading fails.
- **A well without a lithology log is zoned by the lithology Petrophys's mineral solver gives** (the code curve its
  lithology step writes, read with Petrophys's own labels), and only with neither by shale-volume bands. The record
  says so (`lithology.source` `mineral solver`, with the solver's domain, method, inputs and decisions); the solved
  curve is never called a lithology log. Wells with a lithology log, every benchmark well among them, are zoned as
  before.
- **Web UI.**
  - A full-screen log viewer (Well logs, and under the Interpretation page's plot): zoom and move along depth with
    the curves drawn at the window's own detail, the interval or the whole well, every curve of the well to add as a
    track, a linear or log scale and edge values per track, and each curve marked measured (LAS) or computed by
    Petrophys, with a filter for either. Two reads serve it: `/api/run/<id>/logview` and `/logdata`.
  - Under the well plot: how the lithology zones were made (Petrophys's run, its steps, the flow from the curves to
    the zones) and a question about the lithology, whose buttons ask the question again with the solver's domain
    changed. The start page says Petrophys runs its default dynamic workflow and where to change it. Zones read from
    a lithology are called lithology zones.
  - The Interpretation page is one column: the well (the zone table and a lithology summary fold under the plot),
    then the work as it happens, one line per model call with the last lines of the model's reasoning, then the
    answer. The "Writing the answer…" placeholder is gone; the work folds to one line once the answer is in.
  - The model's reasoning streams into the page as the model writes it: the web UI's client streams each call
    (`LLM.stream_to`; every other run sends its requests as before) and the call in flight is the job's `live` state.
    Each call's reasoning is kept for the page (`LLM.last_reasoning`, the `reply` event's `thinking`); no check reads
    it, and traces are unchanged. A conversation's tape records a streamed call as a whole one.
  - Uploads are never rewritten in place.
  - The run list and follow-ups no longer fail while other questions start or finish.
- **Running many questions at once.**
  - The well cache prepares a well once and reads only the pickles you wrote.
  - A benchmark killed while writing resumes.
- **Leaner code.** About 1,100 lines no run reaches are gone (ten catalog computations and their helpers, dead
  configuration keys, pass-through functions), and seven fallbacks that could only hide a broken Petrophys import.
- **One default interpretation.** A data settings file that names no `interpret`, no `interpreter` and no engine
  now has Petrophys interpret each LAS (`petrophys.interpret` with the library's settings and the policy's cutoffs),
  as a question always did. The installed-library route, which applied an Rw rule of its own, is gone, and with it
  the policy keys `gr_endpoints`, `rw` and `interpretation_scope: formation`. Wells cached before are interpreted
  again once.
- **Ten more fixes to answers.**
  - Over the writer's budget, the results the claims cite and the newest ones stay whole and the oldest uncited ones
    become digests; before, the text was cut at the budget and the newest results were lost.
  - A later question's settle step and its listing of opened results read that question's results and the earlier
    ones it cites; before, every result of the conversation, so that after about 35 none of its own was whole.
  - The writer's checker counts as shown the prompt the writer got; before, a rebuilt subset without the data's
    conventions, the stretch or the earlier questions.
  - `pay_summary` names each average as Petrophys took it: the core-corrected curve read for PHIE and PERM, and a
    geometric mean for every permeability.
  - `runs` lists every interval where its condition holds, uncut by zone boundaries, under every reach.
  - A curve a verb writes is read as a flag or as class codes by the rule every lookup uses.
  - `classify` with no zone named reads every sample of the interval and labels it as the lookups do.
  - The reasoning a server leaves in a reply before the card's `reasoning_end` is taken off every reply, a retry's
    too.
  - The map's analyzer notes count Petrophys's own per-sample labels and quote its recorded rules.
  - A name the settings' tops table lists more than once for the well is refused, as `--tops` reads it; before, its
    shallowest row was taken without a word.
- **Two switches stay off**, each waiting on a fix: `tight_numbers` (a stricter number check) and `cell_thickness` (n
  samples counted as n steps of thickness). Turn one on with `PETROHARNESS_SET=<name>=true`
  (docs/reference/EXTENDING.md, section 12).
- **Docs.** The settings sheet's tables and the prompt components' table are generated from the code, like the tool
  tables, and a test checks that every file a page names exists. EXTENDING has recipes for a dataset config and a
  component text.
- **Tests run without data.** Petrophys's sample wells are read from Petrophys, the public mini set must run in CI,
  and only a test marked `data` is skipped without data settings.

## 0.7.0 (2026-11-21)

- **The harness asks back instead of guessing.** A question that names a unit the tops file lists more than once, a
  unit whose row the tops reader cannot use, a name close to several units, or a bare name several units share is
  answered with a question back and the choices; nothing is computed until you choose (status `ask_user`). A request
  outside the well's logs is answered with what the harness does and example questions (status `outside`).
- **Your own zones.** `--zones FILE` (CSV, TSV or Excel: zone, top, bottom) frames the answer in place of the
  lithology zones; a zone with no sample of the log is said under every question. In `petroharness chat`, `/zones`
  changes them.
- **A question can reach any stretch of the well.** The stretches a question is about (units of the tops file, your
  zones, depth ranges, the whole well) are read from its words; `/scope` and `/frame` set them in a conversation. A
  tool's `zones` can name any of these, and the result says what it computed on.
- **Unit names in any spelling.** A unit is found however a question writes it (Fm., Formation, Gp., plurals,
  abbreviations); a unit the tops file does not have is said under the question.
- **Notes before the answer.** A measurement the record does not hold, or holds with no value in the interval, and a
  unit the tops file lacks are said before the numbers.
- **Counts beside shares, richer conditions.** A share of samples is written with its count ("12 of 768 samples
  (1.6%)"). Conditions take a curve's own percentile (`GR < p25`), `|` and `&`, chains and comparison words; a limit
  that is no count of intervals is said instead of refused; totals cover the whole interval where samples lie outside
  the zones.
- **What-ifs state their changes.** Each changed curve gives its change beside every zone's baseline and changed
  value, the zones' range on each side and of the change, and how many of the interval's samples changed.
- **A new tool, `values_at`:** the values of curves at given depths.
- **Inputs checked before a question runs.** A LAS whose depth goes back (spliced logging runs, a repeated section)
  or repeats is refused with the file line and the fix. A tops file is checked as it loads: rows to fix, names listed
  more than once, formations beyond the log, a file in feet labelled metres. A name the tops file lists twice is
  chosen by its top (`--tops FILE --formation NAME --top D`).
- **Labels read from the record as data.** Class codes, the clay-volume rule, net-pay exclusions and parameter notes
  come from Petrophys's record of the run, one rule each.
- **The model names each input of a Petrophys function** by the kind Petrophys declares (a curve, a number, a choice,
  a condition, the depth window); a required input left out is asked for, with this well's curves of that kind, the
  record's value and the default.
- **The number checker reads numbers as answers write them** (thousands separators, numbers in words, a band edge
  after a minus), and its repair request says where each number stands.
- **Web UI.** One-click sample wells from Petrophys, drag and drop of a LAS, tops, zones or field-notes file, the
  formations as buttons and questions to start with; the question back as a card with clickable choices; notes before
  the answer; tops and zones files checked as they load; a line under the progress bar saying what the run is doing
  and the time such questions usually take on this server.
- **Petrophys 7aa9968.** The pin moves to Petrophys's latest dev: 308 functions reachable through the verbs, more
  curve aliases, and warnings on invalid scientific inputs.
- **Documentation** checked against the code, with the zones, scope and chat commands, the new statuses and the web
  UI's start page.

## 0.5.0 (2026-11-17)

Questions that need an investigation are answered as 0.2.1 answers them; a direct question now takes a short route
(below), measured on the whole benchmark with both models. With `--investigate` every request is the 0.2.1 build's,
proven on its 1,388 saved runs. The rest is new around the question: conversations, the evidence graph, figures.

- **Conversations.** Ask, read the answer, ask again: `petroharness chat` keeps one interval of one well open. A later
  question sees what the earlier ones found, reads their results again instead of computing them again, and may cite
  them. Result ids go on across questions. `docs/SESSIONS.md`.
- **Three graphs.** The question graph is the measured one. A later-question graph answers follow-ups on the same
  session, and lets the model choose a brief or a full reply. A session graph carries each question from the message
  to its committed record: `open -> turn -> project -> figures -> commit`. `docs/SESSION_GRAPH.md`.
- **One session log.** Every conversation is one append-only log with the texts it names kept by hash. A
  conversation is resumed from it, and what the model is shown of earlier questions is built from it by code.
- **The evidence graph and the audit trail.** `petroharness audit SESSION` writes, for each answer, the claims with
  the results they cite, the numbers with the results that show them, the curves those read, the Petrophys steps and
  parameters behind them, and the LAS file's hash. It needs only the session folder. `petroharness report SESSION`
  writes a whole conversation as one document. The web UI links each answer's audit trail. `docs/EVIDENCE.md`.
- **Methods and parameters under every answer**, read from the well's record by code.
- **Figures, drawn by Petrophys.** Where a plot says it better than text, the model chooses among the plots of the
  answer's results and the standard displays of the interval (density-neutron, Pickett, Buckles, flow units, triple
  combo and others). The harness draws nothing itself. A conversation also opens with Petrophys' log display of the
  interval. Never in a benchmark run.
- **Direct questions get a short route.** The model first says whether a question is direct (a value, a setting, a
  count or a fact that one or two lookups state) or needs an investigation. A direct question takes one or two
  look steps and a short answer with its basis: three model calls instead of eight or more. Where the lookups do not
  state what is asked, the question still gets an investigation (the look step or the writer hands it over). This is the default
  everywhere (the command, chat, the web UI, benchmark mode); `--investigate` gives every question the full
  investigation, the 0.2.1 route. `docs/GRAPH.md`.
- **The setup record.** `petroharness setup` prints what answers a question, with one hash; every conversation logs
  it and every trace names it. `docs/SETUP.md`.
- **The web UI** is laid out as a chat: one question box docked at the bottom, with the conversation's well, interval,
  interpretation settings and options as chips above it, and the runs in a drawer. While an answer is open, the next
  question continues its conversation (no separate follow-up box), and the earlier questions stay above it, each a
  box that opens to its whole answer and figures; *New conversation* starts another. Under each
  answer: its figures, the methods and parameters, the audit trail, and **How it was computed**, a graph from the
  measured logs through the Petrophys steps (method, parameters) and the results to the answer's numbers; click a
  number to see its path. **Interpretation settings**: every setting `petrophys.interpret` takes, with Petrophys's
  own help, choices and defaults, and the harness's zone rule (minimum zone thickness, shale-volume bands), previewed
  on the well before asking; the API's `ask(..., interpretation=)` takes the same settings. `docs/UI.md`.
- **Changing a setting in a conversation.** A setting changed mid-conversation (`/set m=1.8` in `petroharness chat`,
  `Conversation.adopt`, or the web UI's Interpretation chip) holds from the next question on: the well is interpreted
  again as a new generation, the ledger goes on and marks what was opened before as resting on the earlier settings
  (the same call asked again is computed anew), the next questions' prompts and the answer's header name the change,
  the log keeps it (a `settings` event, replayed on resume), and the evidence graph gives each answer the curves and
  parameters of its own generation. A conversation without a change sends the requests it sent before (the public
  mini set and the golden tapes replay unchanged). Seen live on K2-Horizon-7B: m 2 -> 1.8 on a conversation's fifth
  question; the answer cited m = 1.8 from the saturation step and compared its SW with the earlier result. Not
  judged on the benchmark: a benchmark question never changes a setting. `docs/SESSIONS.md`.
- **Field notes.** A YAML file of a team's standing choices for a field (`name`, `settings`, `notes`): its settings in
  force from the start under the user's own, each marked as the field notes'; its notes with every question as the
  user's statement; named in the answer's header; kept in the log (content and SHA-256). `--field-notes`, `field_notes=`,
  the web UI's Options. Never in a benchmark run. `docs/SESSIONS.md`.
- **Fix: a cutoff set in the settings panel** (VCL, SW or porosity) no longer stops the interpretation: the policy the
  view describes the well with takes the user's cutoff, as Petrophys used it.
- **Answers carry no evidence ids.** The delivered answer has no evidence id in any form a model writes one: a
  bracket that cites and says something keeps what it says ("(E10, n = 161)" becomes "(n = 161)"), a label naming
  part of the writer's input goes with its id, and an id used as a noun becomes "the result". On the 3,123 saved
  answers of the 1.0 model comparison, ids had been left in up to 48% of a model's answers; with this code, none.
  The trace keeps the writer's draft (`trace["draft"]`), so a later delivery change is judged on the same drafts.
  Judged with GPT-5 on K2-Horizon-7B, the changed answers against the old delivery: +0.02 W per changed answer on
  two saved runs (201 answers), −0.09 on two fresh runs (338 answers), both within the judge's noise.
- **One definition per tool.** Each tool is one `Tool` (`petroharness.tools.spec`) in `agent/toolset.py`: its
  function, arguments, description, group and how a call of it is listed. The lists that lived in six places are read
  from the definitions; every request is unchanged. `docs/TOOLS.md`, "Adding a tool".
- **Gates in the repository.** `tests/gate`: a public mini set (a recorded conversation on a Petrophys sample well,
  replayed with no model server and no private data) and the request gate as a tool. `CONTRIBUTING.md`, a CI
  workflow and the repository's own lint configuration.
- **Fixes:** a result id written as a possessive ("from E5's zone means") no longer leaves a stranded "'s" when the
  ids are taken out of the answer; an installed Petrophys is named by its own build; the web UI reports a run finished only once its
  record is saved.

## 0.2.1 (2026-11-14)

- **The writer reads the results for each point itself.** The writer is given the question's points and every result
  the investigation opened, not the investigation's claims. The limits the investigation found come with them, by
  point, so a result the investigation judged unusable is not repeated as a finding.
- **Each point gets its own part.** Rule 10 of the writer's brief: each of the question's points has its part, with its
  finding, the numbers and intervals it rests on and what limits it, and a table where zones or curves are compared.
- **The investigation ends on what it has seen.** A `done` while opened results are still withheld waits one step and
  shows them first. Once every point is settled, the step asks for the brief's "Before you finish" checks.
- **An order over a few zones is said to be untestable.** An exact rank test cannot test an order over fewer than five
  zones. The tool now says so, without direction words.
- **No switches.** The six changes were measured as switches and are now the code. The 17 switches that were measured
  and not adopted are removed with their code and texts; `agent/options.py` defines none.
- **Tests.** `tests/agent/test_measured_build.py` asserts each of the six changes. The tests build their formations on
  the default reporting settings, so the suite gives the same result under any data settings. The 36 golden tapes
  were recorded again on K2-Horizon-7B.
- **Fix:** an installed Petrophys in a virtual environment inside a git repository was named in traces by that
  repository's commit. It is now named by its own build.

## 0.2.0 (2026-11-01)

- **The writer concludes from all the evidence.** The investigation still builds its claims as results come in. The
  writer now reads them with every result the investigation opened, in full, and where the two differ, the results
  decide. A provenance card goes with them: for each curve they name, its meaning, its status (measured, model
  output, parameter, fallback input), the record's cautions, and what its zoned values show about how they were made
  (constant, or held at a limit). One set of reporting rules (C9 `write`). A zone table inserted in the answer is
  not repeated in the text.
- **Each run names its rock.** A class's runs list each zone with its lithology (`Z2 (SAND) 4245.0-4253.6`), so a
  screen's flag is read against the rock it falls in.
- **Differences with their size.** On one scale, `compare` gives the zone means' mean difference against the spread
  of a - b, and `mean / sd` on every row.
- **Reporting settings in the data config.** `data.basis: zones` gives the tools' statistics on the lithology zones
  only. `data.conventions` lists the data's own reporting conventions, shown to the investigation and the writer.
  Both are empty by default, and then every prompt is the general one. A benchmark's conventions go in its data
  config (benchmark mode), never in the package.
- **Permeability guide:** flow units are reported as depth intervals with their class, starting from the workflow's
  FZI classes (Ebanks 1987; Amaefule et al. 1993); clustering is an alternative beside them; a porosity-only basis
  is a limit of the units, not a reason to deny them.
- **The web UI tells the interpretation as a story.** A run opens on *Interpretation*, conclusion first, the way a
  petrophysical report reads: the answer and how sure it is; the well as Petrophys interpreted it (a log plot and the
  zone table, the zones the answer names marked); how the answer was reached, part by part, each finding with a chart
  of the zone values it rests on, the net-pay cutoff, why it matters and what could change it; what limits the answer;
  then the whole written answer, where any number traces to the results that show it. The detail sits behind it:
  *Well logs* (the full plot, values at the cursor's depth), *Evidence* (each claim with the results it rests on, laid
  out as tables), the *Investigation log* (every stage and step, for audit) and *Details*.
  - `petroharness.ask` takes `on_view`, called with the interval's view once Petrophys has interpreted the well.
- **Fixes:** drafting left in the writer's reply ("Need ensure ...") is cut or sent back; `get` by class and zone
  reads runs written with their zone's rock.
- **No switches:** `agent/options.py` defines none; `--writer` sets only the repair rounds.
- **Documentation:** `docs/ARCHITECTURE.md` opens with a diagram of the whole harness and describes the reporting
  settings.

## 0.1.2 (2026-10-29)

- **Petrophys on request.** The model can now ask Petrophys for what the record does not hold.
  - `calculate` recomputes a property with another method or parameters, through Petrophys's own workflow step,
    with the steps that read its outputs. Examples: SW with Simandoux, VCL with Larionov, porosity with a
    limestone matrix, permeability with Timur, a stated Rw.
  - `what_if` tries several values of one input against a target.
  - `estimate` reads a parameter from the well's own logs: Rw, Archie m, GR endpoints, the clay point, apparent
    matrix, temperature.
  - `check` adds held readings, the parts of bad hole and core depth shift.
  - `classify` adds gas, minerals, flow units, electrofacies and moveable hydrocarbons.
  - `summarize` adds pay with HCPT at any cutoffs.
  - `calibrate` adds the core fit, poro-perm transforms, predicted shear and elastic properties.
- **Every Petrophys function by request.**
  - Each verb takes `search` and `run` over about 300 public Petrophys functions, from a registry generated from
    the installed library.
  - One binder fills each function's inputs: curves by role or name, conditions as masks, the record's numbers, the
    interval's limits.
  - Outputs become curves of the question, values and tables.
- **The record as the default.** Every input not given comes from the record, and each result says where each
  input came from.
- **Tools grouped by request.** The model sees its tools under seven verbs: describe, compare and group, check,
  calculate, classify, summarize, calibrate.
- **Own wells:** a well whose default interpretation sets the porosity cutoff per lithology no longer stops the run.
- **Documentation:** `docs/TOOLS.md`.

## 0.1.1 (2026-10-29)

- **Any chat model.** PetroHarness runs on any chat model behind an OpenAI-compatible endpoint (vLLM, SGLang, Ollama,
  LM Studio or a hosted API):
  - `--model NAME` names the served model, through the packaged generic card;
  - `--model-card FILE` loads a model card with its own request settings (reasoning, sampling, template variables,
    the output cap's name, structured output);
  - K2-Horizon-7B stays the default.

  The command, the web UI, benchmark mode and the Python API take the same options. The endpoints come from
  `PETROHARNESS_MODEL_URL`. The model's name is recorded in `answer.md` and in the trace, and shown in the web UI.
- **Documentation:** a new README, `docs/MODELS.md` (serving, model cards, reasoning models, hosted APIs) and
  `docs/DEVELOPMENT.md` (configuration, benchmark mode, testing, layout).
- **Citation:** the paper (ADIPEC 2026, SPE-236034-MS) in the README and in `CITATION.cff`.

## 0.1.0 (2026-10-29)

First public release.

- **One question, one interval, from the raw LAS.** Petrophys interprets the well (through `petrophys.interpret`
  with optional context profiles, a batch interpreter, or a pinned engine). The interval is a formation from a tops
  file, a depth interval, or the whole well, and it is zoned by its lithology log (shale-volume bands without one).
- **The question graph** (LangGraph): READ, the first look, up to 8 investigation steps, settle, the writer, its
  checker and repairs. Every step is one model call rebuilt from the state.
- **Topics chosen by the model.** The READ call picks the question's topic areas (14 areas, owned by the harness) and
  lists the measurements it names; what the question names that the record lacks is said once.
- **Tools** for lookups (`stats`, `runs`, `compare`, `overlap`, `profile`, `crossplot`, `lag_correlation`,
  `section`, `step`), named computations, and `get`, `find` and `calc` on the ledger. Analyzer sections show each
  class as located runs; every line names its basis and the status of its curve.
- **One summary layer** for every tool that summarises a curve: each zone, the zones pooled, the whole interval;
  statistics, rankings, thresholds and classes chosen by the shape of the data, never by a curve's name.
- **The ledger and the claims.** Every result is kept whole with an id; the answer is a set of graded claims that
  cite results, checked by code for facts about the record and the citations.
- **A pluggable skill library** (`skills: <path> | none`, `PETROHARNESS_SKILLS`). The packaged library has one guide
  per topic area and two common guides, written from the literature, with the provenance of every line.
- **The writer and its checker**: numbers no result shows, words about the process, statements the record
  contradicts and working notes are sent back for repair; a code-composed zone table; a configurable report style.
- **Traces** with every model call attributed to its components (C1-C10) and their versions, the skill library
  read, and token use.
- **Questions about your own wells** (`petroharness --las WELL.las --question ...`, the default command): the
  interval from a tops file and a formation name, from explicit depths, or the whole well.
- **A web UI** (`petroharness ui`): the same questions in the browser, with live progress, saved runs, ratings and
  replay.
- **Benchmark mode** (`petroharness benchmark`): a question file with reference answers run in parallel, for
  validation; resumable, with an answer file and a trace per question.
- **Tests**: the generality contract (G1-G8), the dataset-name lint, and three regression gates (golden tapes, the
  prompt fixture, the ledger replay).
- Python 3.10; dependencies pinned in `requirements.lock`; Petrophys pinned at
  916ca46c37980ceac56a0c4ac94b2eb0f8d8632c.
