# Models

PetroHarness works with any chat model behind an OpenAI-compatible chat completions endpoint. That includes a model
you serve yourself with vLLM, SGLang, Ollama or LM Studio, and a hosted API.

The harness sends plain chat requests, with no native tool calling. The model replies in JSON at each investigation
step and in Markdown when it writes the answer. The default model is K2-Horizon-7B.

## What the model needs

- **An OpenAI-compatible endpoint:** a base URL ending in `/v1` that answers `POST /chat/completions` (and lists its
  models at `GET /models`, which the web UI uses for its health check).
- **A context window of 64k tokens or more.** Prompts run up to about 40,000 tokens, and each reply needs room on top.
  When a request does not fit, the harness sends it once more with a smaller output allowance.
- **JSON replies on request.** Each investigation step asks, in its prompt, for one JSON object. A reply that is not
  valid JSON is salvaged where it can be, or sent back once to be fixed. The READ call also carries its reply's JSON schema, for servers that
  support structured output (`structured_output` below).

## Choosing the model

| you want | how |
|---|---|
| K2-Horizon-7B (the default) | nothing: its model card is the default |
| any chat model, by its served name | `--model NAME`: the generic card, with that name |
| full control over the request | `--model-card FILE`: a model card of your own |

The endpoints come from `--model-url` or `PETROHARNESS_MODEL_URL`, comma-separated. A batch spreads its questions
over them, and the web UI sends each question to the least busy one. The API key is read from the environment variable
the card names (`PETROHARNESS_API_KEY` unless the card says otherwise). A local server accepts any key.

The same options work for the command, the web UI (`petroharness ui --model ...`), benchmark mode
(`petroharness benchmark --model ...`) and Python (`ask(..., model="...", model_card="...")`).

### Examples

**vLLM**

```bash
vllm serve Qwen/Qwen3-32B --port 8000 --max-model-len 65536
petroharness --model Qwen/Qwen3-32B --model-url http://localhost:8000/v1 --las well.las --question "..."
```

**SGLang**

```bash
python -m sglang.launch_server --model-path Qwen/Qwen3-32B --port 30000 --context-length 65536
petroharness --model Qwen/Qwen3-32B --model-url http://localhost:30000/v1 --las well.las --question "..."
```

**Ollama.** Its default context window is far smaller than the harness needs, so raise it:

```bash
OLLAMA_CONTEXT_LENGTH=65536 ollama serve
ollama pull qwen3:32b
petroharness --model qwen3:32b --model-url http://localhost:11434/v1 --las well.las --question "..."
```

**K2-Horizon-7B** (the default card), served by vLLM 0.30 or later:

```bash
vllm serve /path/to/k2-horizon-7b-grpo200 --served-model-name k2-horizon-7b-grpo200 --port 8100 \
    --trust-remote-code --dtype bfloat16 --max-model-len 131072 \
    --reasoning-parser k2_horizon --chat-template-content-format string \
    --enable-auto-tool-choice --tool-call-parser k2_horizon
export PETROHARNESS_MODEL_URL=http://localhost:8100/v1
petroharness --las well.las --question "..."
```

`--chat-template-content-format string` is required: the model's chat template reads each message's content as a
string, and without the flag the user's text does not reach the model.

## Model cards

A model card is a YAML file with one section, `model`. It holds the served model's name and how to call it. The
packaged cards are in `src/petroharness/resources/models/`:

- `k2_horizon_7b_grpo200.yaml`: K2-Horizon-7B, the default.
- `generic.yaml`: any chat model, named with `--model`. It sends no sampling settings and no chat-template variables,
  so the model's own defaults apply.

`--model-card` takes a card's file, or a packaged card's name (`--model-card generic`). With both `--model` and
`--model-card`, `--model` names the model the card describes. A misspelt field stops the run before its first
question.

### A reasoning model

A model that thinks before it answers needs two things.

- The server's reasoning parser, so that the thinking arrives apart from the reply. For example, vLLM's
  `--reasoning-parser` for the model's family.
- A card that says so:

```yaml
model:
  model: Qwen/Qwen3-32B
  label: Qwen3-32B
  reasoning: true                                  # a reply cut off by the token cap is a failed reply
  chat_template_kwargs: {enable_thinking: true}
  retry_template_kwargs: {enable_thinking: false}  # the one retry after an empty reply: a plain answer
  temperature: 0.6
  top_p: 0.95
  max_tokens_spec: 32768                           # thinking counts against the output cap
  max_tokens_writer: 32768
  timeout_s: 3600
```

### A hosted API

Hosted APIs reject fields they do not know, and some models accept only their default sampling:

```yaml
model:
  model: your-model-name
  label: Your Model
  api_key_env: OPENAI_API_KEY                      # the variable that holds your key
  send_template_kwargs: false                      # no chat_template_kwargs in the request
  send_temperature: false                          # the model's default sampling
  max_tokens_param: max_completion_tokens          # the cap's name on APIs that use it
  reasoning: true
  replay_reasoning_field: false
  max_tokens_spec: 32768
  max_tokens_writer: 32768
```

```bash
export OPENAI_API_KEY=...
petroharness --model-card my_api.yaml --model-url https://api.openai.com/v1 --las well.las --question "..."
```

With a hosted API, the prompts go to that provider, and the prompts include the well's data.

### Fields

| field | default | meaning |
|---|---|---|
| `model` | (required) | the served model's name, as the server lists it at `/v1/models` |
| `label` | `model` | the model's name as people read it: shown in the web UI and in `answer.md` |
| `api_key_env` | `PETROHARNESS_API_KEY` | the environment variable that holds the API key |
| `temperature` | `0.0` | sampling temperature (sent when `send_temperature`) |
| `top_p` | the server's | nucleus sampling |
| `max_tokens_spec` | `3000` | the output cap of an investigation step and of the settle step |
| `max_tokens_writer` | `6000` | the output cap of the writer and of a repair |
| `timeout_s` | `600` | the time one request may take, in seconds |
| `max_retries` | `3` | the client's retries after a connection error or a server error |
| `reasoning` | `false` | the model thinks before it answers: a reply cut off by the token cap is discarded, and the step retries or keeps its last draft |
| `chat_template_kwargs` | `{enable_thinking: <enable_thinking>}` | chat-template variables sent with each request (vLLM, SGLang) |
| `enable_thinking` | `false` | the template variable sent when `chat_template_kwargs` is not set |
| `retry_template_kwargs` | none | the template variables of the one retry after an empty reply |
| `light_template_kwargs` | none | the template variables of a call that needs little reasoning, for example `{reasoning_effort: low}` or `{enable_thinking: false}`. Used by the call that chooses an answer's figures. Without it every call thinks alike |
| `reasoning_end` | none | where the server leaves the reasoning in a light call's reply, the marker that ends it; the reply is the text after the last marker |
| `send_template_kwargs` | `true` | whether to send `chat_template_kwargs` at all |
| `send_temperature` | `true` | whether to send `temperature` |
| `max_tokens_param` | `max_tokens` | the name of the output cap: `max_tokens` or `max_completion_tokens` |
| `structured_output` | `json_schema` | how JSON replies are requested: `json_schema` (the reply's schema), `json_object`, or `none` (the prompt alone) |
| `replay_reasoning_field` | as `reasoning` | whether replayed assistant turns carry an empty `reasoning` field (some chat templates need it; some APIs reject it) |

The output caps of the generic card are 16,384 tokens for a step and for the writer. Raise them for a model that
thinks at length.

## The model in the record

- Each answer's `answer.md` names the model.
- `trace.json` records every request to the model and its reply: the stage, the tokens in and out, the time taken and
  the finish reason.
- The web UI shows the model in its header and on each run.
