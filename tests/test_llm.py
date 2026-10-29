"""LLM client plumbing that must hold for any served model family."""

from types import SimpleNamespace

from petroharness.config import HarnessConfig, ModelConfig
from petroharness.llm import LLM, Usage, assistant_turn


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
    def __init__(self, content, finish):
        msg = SimpleNamespace(content=content, reasoning=None, reasoning_content=None)
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
    llm = LLM(HarnessConfig())
    llm.client = cap = _Capture()
    llm.chat("spec", [{"role": "user", "content": "q"}], Usage(), 3000, json_schema={"type": "object"})
    assert cap.kwargs == {"model": "qwen/qwen3.6-27b", "messages": [{"role": "user", "content": "q"}], "max_tokens": 3000,
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
