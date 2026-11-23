"""A streamed call on tape (src/petroharness/tape.py): the web UI streams its model calls (petroharness.llm.LLM with a
listener), and every conversation records a tape. The tape keeps the request without the streaming settings and the
reply put together, so a replay, streamed or not, sends the same request and gets the same reply."""
from types import SimpleNamespace

import pytest

from petroharness import tape
from petroharness.config import HarnessConfig, ModelConfig
from petroharness.llm import LLM, Usage

pytestmark = pytest.mark.usefixtures("plain_settings")       # a model client: no well, no data settings file


def _chunk(reasoning=None, content=None, finish=None, usage=None):
    delta = SimpleNamespace(content=content, reasoning=reasoning, reasoning_content=None, model_extra={})
    return SimpleNamespace(choices=[] if usage is not None else [SimpleNamespace(delta=delta, finish_reason=finish)], usage=usage)


class _Server:
    """Streams when asked to, else replies whole; the same reply either way."""

    def __init__(self):
        self.requests = []

        def create(**kw):
            self.requests.append(kw)
            if kw.get("stream"):
                return iter([_chunk(reasoning="Mean PHIE "), _chunk(reasoning="of Z1."), _chunk(content='{"a": 1}', finish="stop"),
                             _chunk(usage=SimpleNamespace(prompt_tokens=9, completion_tokens=8, total_tokens=17))])
            msg = SimpleNamespace(content='{"a": 1}', reasoning="Mean PHIE of Z1.", reasoning_content=None, tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                                   usage=SimpleNamespace(prompt_tokens=9, completion_tokens=8, total_tokens=17))
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def _llm(streams: bool) -> LLM:
    llm = LLM(HarnessConfig(model=ModelConfig(reasoning=True)))
    llm.client = _Server()
    if streams:
        llm.stream_to = lambda kind, text: None
    return llm


def test_a_streamed_call_is_taped_as_a_whole_one(tmp_path):
    whole, streamed = _llm(False), _llm(True)
    a = tape.record(whole, tmp_path / "whole.jsonl")
    b = tape.record(streamed, tmp_path / "streamed.jsonl")
    msgs = [{"role": "user", "content": "q"}]
    assert whole.chat("read", msgs, Usage(), 100) == streamed.chat("read", msgs, Usage(), 100) == '{"a": 1}'
    assert streamed.client.requests[0]["stream"] is True                       # it did stream
    assert b[0]["request"] == a[0]["request"] and "stream" not in b[0]["request"]
    assert b[0]["reply"] == a[0]["reply"]
    assert tape.load(tmp_path / "streamed.jsonl") == b


def test_a_tape_replays_to_a_streaming_client_and_to_a_whole_one(tmp_path):
    msgs = [{"role": "user", "content": "q"}]
    src = _llm(True)
    tape.record(src, tmp_path / "t.jsonl")
    src.chat("read", msgs, Usage(), 100)
    rec = tape.load(tmp_path / "t.jsonl")
    for streams in (True, False):
        llm, heard, u = _llm(streams), [], Usage()
        if streams:
            llm.stream_to = lambda kind, text: heard.append(kind)
        r = tape.replay(llm, rec)
        assert llm.chat("read", msgs, u, 100) == '{"a": 1}' and r.left() == 0
        assert llm.last_reasoning == "Mean PHIE of Z1." and u.log[-1]["completion_tokens"] == 8
        assert heard == (["reasoning", "content"] if streams else [])


def test_a_reply_left_as_it_ran_on_is_taped_as_far_as_it_was_read_and_replays_the_same(tmp_path):
    """A reply that runs whitespace is ended by its reader (llm.WHITESPACE_RUN). The tape keeps the call with what was
    read of it, so a replay makes the same call, meets the same reply and leaves it at the same place: an empty
    reply again, and the next call is the tape's next."""
    from petroharness.llm import RAN_ON, WHITESPACE_RUN
    ran_on = [_chunk(reasoning="topics first."), _chunk(content='{"topics": ["porosity"]')] \
        + [_chunk(content=" " * 50) for _ in range(40)]
    good = [_chunk(content='{"a": 1}', finish="stop"), _chunk(usage=SimpleNamespace(prompt_tokens=9, completion_tokens=8, total_tokens=17))]
    served = iter([iter(ran_on), iter(good)])
    src = LLM(HarnessConfig(model=ModelConfig(reasoning=True)))
    src.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: next(served))))
    calls = tape.record(src, tmp_path / "t.jsonl")
    msgs, u, schema = [{"role": "user", "content": "q"}], Usage(), {"type": "object"}
    assert src.chat("read", msgs, u, 100, json_schema=schema) == "" and u.log[-1]["finish_reason"] == RAN_ON
    assert src.chat("read_retry", msgs, u, 100, json_schema=schema) == '{"a": 1}'
    assert len(calls) == 2 and "stream" not in calls[0]["request"]
    kept = calls[0]["reply"]["content"]
    assert kept.startswith('{"topics"') and len(kept) - len(kept.rstrip()) == WHITESPACE_RUN and calls[0]["reply"]["finish_reason"] is None
    rec = tape.load(tmp_path / "t.jsonl")
    again, v = LLM(HarnessConfig(model=ModelConfig(reasoning=True))), Usage()
    r = tape.replay(again, rec)
    assert again.chat("read", msgs, v, 100, json_schema=schema) == "" and v.log[-1]["discarded"] == u.log[0]["discarded"]
    assert again.chat("read_retry", msgs, v, 100, json_schema=schema) == '{"a": 1}' and r.left() == 0
    timing = lambda log: [{k: x for k, x in e.items() if k != "seconds"} for e in log]
    assert timing(v.log) == timing(u.log)

