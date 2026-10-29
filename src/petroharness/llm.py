"""OpenAI-compatible client for the vLLM endpoint: token accounting, retries, the reasoning field."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
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
        if getattr(self, "seed_base", None) is not None:     # measurement: reproducible sampling per call site
            import hashlib
            kwargs["seed"] = int(hashlib.sha256(f"{self.seed_base}|{stage}".encode()).hexdigest()[:8], 16) % (2 ** 31)
        if json_schema is not None and m.structured_output == "json_schema":
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": stage, "schema": json_schema}}
        elif json_schema is not None and m.structured_output == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        t0 = time.perf_counter()
        resp, shrunk = self._create(kwargs)
        choice = resp.choices[0]
        content = choice.message.content or ""
        reasoning = getattr(choice.message, "reasoning", None) or getattr(choice.message, "reasoning_content", None) or ""
        usage.add(stage, resp.usage, time.perf_counter() - t0, content_chars=len(content),
                  reasoning_chars=len(reasoning), finish_reason=choice.finish_reason)
        if shrunk:
            usage.log[-1]["max_tokens_shrunk"] = shrunk
        if retry and m.retry_template_kwargs is not None:
            usage.log[-1]["template_kwargs"] = dict(m.retry_template_kwargs)
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

    def replays_reasoning(self) -> bool:
        m = self.cfg.model
        return m.reasoning if m.replay_reasoning_field is None else m.replay_reasoning_field

    def template_kwargs(self, retry: bool = False) -> dict:
        m = self.cfg.model
        if retry and m.retry_template_kwargs is not None:
            return dict(m.retry_template_kwargs)
        return dict(m.chat_template_kwargs) if m.chat_template_kwargs is not None else {"enable_thinking": m.enable_thinking}

