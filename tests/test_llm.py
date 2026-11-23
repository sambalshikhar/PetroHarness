"""LLM client plumbing that must hold for any served model family."""

from types import SimpleNamespace

import pytest

from petroharness.config import HarnessConfig, ModelConfig
from petroharness.llm import LLM, Usage, assistant_turn

pytestmark = pytest.mark.usefixtures("plain_settings")       # a model client: no well, no data settings file


def test_default_template_kwargs_switch_thinking_off():
    assert LLM(HarnessConfig()).template_kwargs() == {"enable_thinking": False}


def test_model_family_template_kwargs_pass_through():
    cfg = HarnessConfig(model=ModelConfig(chat_template_kwargs={"reasoning_effort": "high"}))
    assert LLM(cfg).template_kwargs() == {"reasoning_effort": "high"}


def test_usage_without_reasoning_logs_the_basic_entry():
    u = Usage()
    u.add("writer", SimpleNamespace(prompt_tokens=100, completion_tokens=50), 1.0, content_chars=200)
    assert u.log[-1] == {"stage": "writer", "prompt_tokens": 100, "completion_tokens": 50, "seconds": 1.0}


def test_usage_splits_reasoning_from_content():
    u = Usage()
    u.add("writer", SimpleNamespace(prompt_tokens=100, completion_tokens=1000), 1.0,
          content_chars=1000, reasoning_chars=3000, finish_reason="length")
    entry = u.log[-1]
    assert entry["content_tokens"] == 250 and entry["finish_reason"] == "length"
    assert u.completion_tokens == 1000


def test_assistant_turn_carries_empty_reasoning_only_after_a_reasoning_call():
    u = Usage()
    u.add("writer", SimpleNamespace(prompt_tokens=10, completion_tokens=5), 1.0, content_chars=20)
    assert assistant_turn("draft", u) == {"role": "assistant", "content": "draft"}
    u.add("repair", SimpleNamespace(prompt_tokens=10, completion_tokens=50), 1.0, content_chars=20, reasoning_chars=200)
    assert assistant_turn("draft", u) == {"role": "assistant", "content": "draft", "reasoning": ""}


class _FakeClient:
    def __init__(self, content, finish, reasoning=None):
        msg = SimpleNamespace(content=content, reasoning=None, reasoning_content=reasoning)
        resp = SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)],
                               usage=SimpleNamespace(prompt_tokens=5, completion_tokens=50))
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: resp))


def test_truncated_reply_is_discarded_for_a_reasoning_model():
    llm = LLM(HarnessConfig(model=ModelConfig(reasoning=True)))
    llm.client = _FakeClient("I think the answer might be", "length")
    u = Usage()
    assert llm.chat("writer", [], u, 10) == "" and u.log[-1]["discarded"]


def test_truncated_reply_is_kept_for_a_non_reasoning_model():
    llm = LLM(HarnessConfig())
    llm.client = _FakeClient("A long answer cut", "length")
    assert llm.chat("writer", [], Usage(), 10) == "A long answer cut"


def test_the_last_calls_reasoning_is_kept_for_the_page_and_never_in_the_reply():
    """LLM.last_reasoning: the server's reasoning text of the last call (the web UI shows it); the reply is the content."""
    llm = LLM(HarnessConfig(model=ModelConfig(reasoning=True)))
    assert llm.last_reasoning == ""
    llm.client = _FakeClient("the reply", "stop", reasoning="First PHIE, then SW.")
    assert llm.chat("step_1", [], Usage(), 10) == "the reply" and llm.last_reasoning == "First PHIE, then SW."
    llm.client = _FakeClient("next", "stop")                   # a call without reasoning leaves none from before
    assert llm.chat("step_2", [], Usage(), 10) == "next" and llm.last_reasoning == ""


def _chunk(reasoning=None, content=None, finish=None, usage=None, extra=False):
    """One streamed chunk as the OpenAI client gives it; vLLM's reasoning arrives as an extra field (model_extra)."""
    delta = SimpleNamespace(content=content, reasoning=None if extra else reasoning, reasoning_content=None,
                            model_extra={"reasoning": reasoning} if extra and reasoning else {})
    choices = [] if usage is not None and reasoning is None and content is None else [SimpleNamespace(delta=delta, finish_reason=finish)]
    return SimpleNamespace(choices=choices, usage=usage)


class _Streams:
    """A client that streams its reply, and records each request."""

    def __init__(self, chunks):
        self.requests = []

        def create(**kw):
            self.requests.append(kw)
            return iter(chunks) if kw.get("stream") else SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="whole", reasoning="r", reasoning_content=None),
                                         finish_reason="stop")], usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4))
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


STREAM = [_chunk(reasoning="First "), _chunk(reasoning="PHIE.", extra=True), _chunk(content='{"a": '),
          _chunk(content="1}", finish="stop"), _chunk(usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22))]


def test_a_listener_gets_the_call_as_it_streams_and_the_reply_is_the_same():
    llm, u, heard = LLM(HarnessConfig(model=ModelConfig(reasoning=True))), Usage(), []
    llm.client = cl = _Streams(STREAM)
    llm.stream_to = lambda kind, text: heard.append((kind, text))
    assert llm.chat("step_1", [{"role": "user", "content": "q"}], u, 100) == '{"a": 1}'
    assert heard == [("reasoning", "First "), ("reasoning", "PHIE."), ("content", '{"a": '), ("content", "1}")]
    assert llm.last_reasoning == "First PHIE."
    assert u.log[-1]["prompt_tokens"] == 11 and u.log[-1]["completion_tokens"] == 22 and u.log[-1]["reasoning_chars"] == 11
    assert cl.requests[0]["stream"] is True and cl.requests[0]["stream_options"] == {"include_usage": True}


def test_without_a_listener_the_request_is_not_streamed():
    llm = LLM(HarnessConfig(model=ModelConfig(reasoning=True)))
    llm.client = cl = _Streams(STREAM)
    assert llm.chat("step_1", [], Usage(), 100) == "whole"
    assert "stream" not in cl.requests[0] and "stream_options" not in cl.requests[0]


def test_a_failing_listener_never_fails_the_call():
    llm = LLM(HarnessConfig(model=ModelConfig(reasoning=True)))
    llm.client = _Streams(STREAM)
    llm.stream_to = lambda kind, text: 1 / 0
    assert llm.chat("step_1", [], Usage(), 100) == '{"a": 1}'


def test_a_streamed_reply_cut_by_the_length_is_discarded_as_a_whole_one_is():
    llm, u = LLM(HarnessConfig(model=ModelConfig(reasoning=True))), Usage()
    llm.client = _Streams([_chunk(reasoning="long "), _chunk(content="I think", finish="length")])
    llm.stream_to = lambda kind, text: None
    assert llm.chat("writer", [], u, 10) == "" and u.log[-1]["discarded"]


def test_reasoning_model_turn_always_carries_the_field():
    u = Usage()
    u.add("repair", SimpleNamespace(prompt_tokens=10, completion_tokens=5), 1.0, content_chars=20)   # no reasoning this turn
    assert assistant_turn("draft", u, reasoning_model=True)["reasoning"] == ""


class _Capture:
    def __init__(self):
        self.kwargs = None
        msg = SimpleNamespace(content="ok", reasoning=None, reasoning_content=None)
        resp = SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))

        def create(**kw):
            self.kwargs = kw
            return resp
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def test_default_profile_sends_the_plain_request():
    cfg = HarnessConfig()
    cfg.model.model = "served-name"                   # the default names no model: a card or --model gives one
    llm = LLM(cfg)
    llm.client = cap = _Capture()
    llm.chat("spec", [{"role": "user", "content": "q"}], Usage(), 3000, json_schema={"type": "object"})
    assert cap.kwargs == {"model": "served-name", "messages": [{"role": "user", "content": "q"}], "max_tokens": 3000,
                          "temperature": 0.0, "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                          "response_format": {"type": "json_schema", "json_schema": {"name": "spec", "schema": {"type": "object"}}}}


def test_retry_after_an_empty_reply_uses_the_profile_retry_settings():
    cfg = HarnessConfig(model=ModelConfig(reasoning=True, chat_template_kwargs={"enable_thinking": True},
                                          retry_template_kwargs={"enable_thinking": False}))
    llm, u = LLM(cfg), Usage()
    llm.client = cap = _Capture()
    llm.chat("writer", [], u, 100)
    assert cap.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}
    llm.chat("writer_retry", [], u, 100, retry=True)
    assert cap.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert u.log[-1]["template_kwargs"] == {"enable_thinking": False} and "template_kwargs" not in u.log[0]
    plain = LLM(HarnessConfig())                     # no retry settings: the retry repeats the first call
    assert plain.template_kwargs(retry=True) == plain.template_kwargs()



def test_config_typos_raise_and_overlays_merge(tmp_path):
    import pytest
    from pydantic import ValidationError
    bad = tmp_path / "bad.yaml"
    bad.write_text("model:\n  temprature: 0.2\n")
    with pytest.raises(ValidationError):
        HarnessConfig.load(bad)
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text("model:\n  temperature: 0.7\n  top_p: 0.9\n")
    b.write_text("model:\n  top_p: 0.5\n")
    m = HarnessConfig.load(a, b).model
    assert (m.temperature, m.top_p) == (0.7, 0.5)


def test_a_retrys_reply_loses_the_reasoning_left_before_the_marker():
    """A retry runs with thinking off; the server may leave the reasoning in the reply before the card's
    reasoning_end. Every call's reply loses it (a retry's, a plain call's), and the usage log says so."""
    card = ModelConfig(reasoning_end="</think>", retry_template_kwargs={"enable_thinking": False})
    llm = LLM(HarnessConfig(model=card))
    llm.client = _FakeClient("Let me draft this.</think>The answer.", "stop")
    u = Usage()
    assert llm.chat("writer", [], u, 10, retry=True) == "The answer." and u.log[-1]["reasoning_left"]
    u = Usage()
    assert llm.chat("writer", [], u, 10) == "The answer." and u.log[-1]["reasoning_left"]   # and a plain call's
