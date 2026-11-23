"""OpenAI-compatible client for the vLLM endpoint: token accounting, retries, the reasoning field."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional

from openai import OpenAI

from petroharness.config import HarnessConfig


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    log: list[dict] = field(default_factory=list)

    def add(self, stage: str, usage: Any, seconds: float, content_chars: int = 0, reasoning_chars: int = 0,
            finish_reason: Optional[str] = None) -> None:
        p = getattr(usage, "prompt_tokens", 0) or 0
        c = getattr(usage, "completion_tokens", 0) or 0
        self.calls += 1
        self.prompt_tokens += p
        self.completion_tokens += c
        self.seconds += seconds
        entry = {"stage": stage, "prompt_tokens": p, "completion_tokens": c, "seconds": round(seconds, 2)}
        if reasoning_chars:
            # Completion tokens include the reasoning; only the content goes back into a repair prompt.
            entry["reasoning_chars"] = reasoning_chars
            entry["content_tokens"] = round(c * content_chars / (content_chars + reasoning_chars))
        if finish_reason and finish_reason != "stop":
            entry["finish_reason"] = finish_reason
        self.log.append(entry)


def assistant_turn(content: str, usage: Usage, reasoning_model: bool = False) -> dict:
    """The model's last answer as a conversation turn for a follow-up call. Earlier reasoning is not
    replayed (the usual multi-turn practice). For a reasoning model, or after any call that returned reasoning,
    the turn carries an empty reasoning field, which some chat templates require (a reasoning model may skip
    thinking on one turn, so the last call alone is not enough)."""
    turn = {"role": "assistant", "content": content}
    if reasoning_model or (usage.log and usage.log[-1].get("reasoning_chars")):
        turn["reasoning"] = ""
    return turn


def _field(obj, name: str):
    """A field of a streamed delta, also when the client keeps a server's own field (vLLM's reasoning) as an extra."""
    return getattr(obj, name, None) or (getattr(obj, "model_extra", None) or {}).get(name)


class LLM:
    def __init__(self, cfg: HarnessConfig):
        self.cfg = cfg
        self.client = OpenAI(base_url=cfg.model.base_url, api_key=cfg.api_key(),
                             timeout=cfg.model.timeout_s, max_retries=cfg.model.max_retries)

    def chat(self, stage: str, messages: list[dict], usage: Usage, max_tokens: int,
             json_schema: Optional[dict] = None, temperature: Optional[float] = None, retry: bool = False) -> str:
        """One completion. retry=True marks the single retry after an empty reply (profile retry settings)."""
        m = self.cfg.model
        kwargs: dict[str, Any] = {"model": m.model, "messages": messages, m.max_tokens_param: max_tokens}
        if m.send_temperature:
            kwargs["temperature"] = m.temperature if temperature is None else temperature
        if m.send_template_kwargs:
            kwargs["extra_body"] = {"chat_template_kwargs": self.template_kwargs(retry)}
        if m.top_p is not None:
            kwargs["top_p"] = m.top_p
        if json_schema is not None and m.structured_output == "json_schema":
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": stage, "schema": json_schema}}
        elif json_schema is not None and m.structured_output == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        t0 = time.perf_counter()
        resp, shrunk = self._streamed(kwargs) if self.stream_to is not None else self._create(kwargs)
        choice = resp.choices[0]
        content = choice.message.content or ""
        reasoning = getattr(choice.message, "reasoning", None) or getattr(choice.message, "reasoning_content", None) or ""
        self.last_reasoning = reasoning
        usage.add(stage, resp.usage, time.perf_counter() - t0, content_chars=len(content),
                  reasoning_chars=len(reasoning), finish_reason=choice.finish_reason)
        if shrunk:
            usage.log[-1]["max_tokens_shrunk"] = shrunk
        if retry and m.retry_template_kwargs is not None:
            usage.log[-1]["template_kwargs"] = dict(m.retry_template_kwargs)
        elif self.light and m.light_template_kwargs is not None:
            usage.log[-1]["light"] = True
        if m.reasoning_end and m.reasoning_end in content:      # reasoning the server left in the reply: any call's
            content = content.rsplit(m.reasoning_end, 1)[1].lstrip()
            usage.log[-1]["reasoning_left"] = True
        if choice.finish_reason == "length" and self.cfg.model.reasoning:
            usage.log[-1]["discarded"] = "truncated reasoning reply"
            return ""                     # callers retry or keep their previous draft
        return content


    def _create(self, kwargs: dict):
        """The completion. A request the server refuses for exceeding the context window ("maximum context length is
        C tokens ... your prompt contains at least P input tokens") is sent once more with the output allowance shrunk
        to fit; the prompt is kept. Returns (response, the shrunk allowance or None)."""
        try:
            return self.client.chat.completions.create(**kwargs), None
        except Exception as exc:
            m = re.search(r"maximum context length is (\d+) tokens.*?contains? at least (\d+) input tokens", str(exc), re.S)
            key = self.cfg.model.max_tokens_param
            if not m or key not in kwargs:
                raise
            room = int(m.group(1)) - int(m.group(2)) - 1024
            if room < 1024:
                raise
            return self.client.chat.completions.create(**(kwargs | {key: room})), room

    def _streamed(self, kwargs: dict):
        """The completion streamed: each piece of reasoning and of content goes to stream_to as it arrives. Returns
        (a response shaped as the whole one: its message, finish reason and usage; the shrunk allowance or None)."""
        stream, shrunk = self._create(kwargs | {"stream": True, "stream_options": {"include_usage": True}})
        content, reasoning, finish, used = [], [], None, None
        for chunk in stream:
            used = getattr(chunk, "usage", None) or used
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            finish = choice.finish_reason or finish
            delta = choice.delta
            for kind, text, into in (("reasoning", _field(delta, "reasoning") or _field(delta, "reasoning_content"), reasoning),
                                     ("content", getattr(delta, "content", None), content)):
                if text:
                    into.append(text)
                    self._tell(kind, text)
        message = SimpleNamespace(content="".join(content), reasoning="".join(reasoning), reasoning_content=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=used), shrunk

    def _tell(self, kind: str, text: str) -> None:
        try:
            self.stream_to(kind, text)
        except Exception:  # noqa: BLE001  (a listener never fails the call)
            pass

    def replays_reasoning(self) -> bool:
        m = self.cfg.model
        return m.reasoning if m.replay_reasoning_field is None else m.replay_reasoning_field

    light = False                     # the calls that follow need little reasoning (set_light)
    last_reasoning = ""               # the last call's reasoning text, for the web UI to show; the run never reads it
    stream_to = None                  # a listener for a call's text as it arrives (the web UI): stream_to(kind, text),
                                      # kind "reasoning" or "content". None (every run but the web UI's): the reply
                                      # comes whole, the request as it always was

    def set_light(self, on: bool) -> None:
        """From here on, calls use the card's light thinking setting (light_template_kwargs), or its normal one again.
        A card without a light setting is not changed by this."""
        self.light = bool(on)

    def template_kwargs(self, retry: bool = False) -> dict:
        m = self.cfg.model
        if retry and m.retry_template_kwargs is not None:
            return dict(m.retry_template_kwargs)
        if self.light and m.light_template_kwargs is not None:
            return dict(m.light_template_kwargs)
        return dict(m.chat_template_kwargs) if m.chat_template_kwargs is not None else {"enable_thinking": m.enable_thinking}

