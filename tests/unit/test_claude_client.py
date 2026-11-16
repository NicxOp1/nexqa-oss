from types import SimpleNamespace

import pytest

from nexqa.core.cost_meter import cost_meter
from nexqa.integrations.claude_client import (
    ClaudeClient,
    ClaudeRefusalError,
    extract_json,
)


class _FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class _FakeAnthropic:
    """Records each request and returns a canned message."""

    def __init__(self, message):
        self.calls = []
        self._message = message
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeStream(self._message)


def _message(blocks, stop_reason="end_turn"):
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def test_complete_skips_thinking_blocks_and_tracks_cost():
    cost_meter.reset()
    fake = _FakeAnthropic(
        _message(
            [
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text="hello"),
            ]
        )
    )
    client = ClaudeClient(client=fake)

    assert client.complete("sys", "user", temperature=0.7) == "hello"
    assert cost_meter.get_report().claude_input_tokens == 10

    sent = fake.calls[0]
    assert "temperature" not in sent  # current models reject sampling params
    assert sent["thinking"] == {"type": "adaptive"}


def test_complete_raises_on_refusal():
    fake = _FakeAnthropic(_message([], stop_reason="refusal"))
    with pytest.raises(ClaudeRefusalError):
        ClaudeClient(client=fake).complete("sys", "user")


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Sure:\n```\n{"a": 1}\n```\nDone.',
    ],
)
def test_extract_json_handles_fences(text):
    assert extract_json(text) == {"a": 1}


def test_extract_json_rejects_empty():
    with pytest.raises(ValueError):
        extract_json("   ")
