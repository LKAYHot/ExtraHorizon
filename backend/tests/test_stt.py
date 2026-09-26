"""Realtime speech-to-text client (OpenAI transcription session) against a fake server."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from extrahorizon.voice.stt import MockStt, OpenAIRealtimeStt, create_stt

from .conftest import make_settings


class FakeRealtime:
    """Answers like wss://api.openai.com/v1/realtime?intent=transcription (item ids per commit)."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._q: asyncio.Queue = asyncio.Queue()
        self.items = 0
        self.audio = 0

    async def send(self, raw: str) -> None:
        m = json.loads(raw)
        self.sent.append(m)
        if m["type"] == "input_audio_buffer.append":
            self.audio += len(base64.b64decode(m["audio"]))
        elif m["type"] == "input_audio_buffer.commit":
            self.items += 1
            item = f"item_{self.items}"
            words = ["Explain", " recursion", " to", " me."] if self.items == 1 else ["Wait,", " stop."]
            self._q.put_nowait({"type": "input_audio_buffer.committed", "item_id": item})
            for w in words:
                self._q.put_nowait({"type": "conversation.item.input_audio_transcription.delta", "item_id": item, "delta": w})
            self._q.put_nowait({"type": "conversation.item.input_audio_transcription.completed", "item_id": item,
                                "transcript": "".join(words)})

    def __aiter__(self):
        return self

    async def __anext__(self):
        m = await self._q.get()
        if m is None:
            raise StopAsyncIteration
        return json.dumps(m)

    async def close(self) -> None:
        self._q.put_nowait(None)


@pytest.fixture
def fake_realtime(monkeypatch):
    import websockets.asyncio.client as client

    servers: list[FakeRealtime] = []
    headers: list[dict] = []

    async def connect(url, additional_headers=None, **kw):
        assert url.endswith("/v1/realtime?intent=transcription")
        headers.append(dict(additional_headers or {}))
        servers.append(FakeRealtime())
        return servers[-1]

    monkeypatch.setattr(client, "connect", connect)
    return servers, headers


async def test_session_setup_partials_and_finals(fake_realtime):
    servers, headers = fake_realtime
    s = make_settings(stt_provider="openai", openai_api_key="fake-openai-key-for-tests")
    stt = OpenAIRealtimeStt(s)
    partials, finals = [], []
    stt.on_partial = lambda u, t: partials.append((u, t))
    stt.on_final = lambda u, t: finals.append((u, t))
    await stt.start()
    ws = servers[0]
    assert headers[0]["Authorization"].startswith("Bearer ")
    cfg = ws.sent[0]["session"]["audio"]["input"]
    assert ws.sent[0]["type"] == "session.update" and ws.sent[0]["session"]["type"] == "transcription"
    assert cfg["transcription"]["model"] == "gpt-live-transcribe"
    assert cfg["turn_detection"] is None  # turn-taking is ours (local VAD)
    assert cfg["noise_reduction"] == {"type": "far_field"} and cfg["format"]["rate"] == 24000
    assert "recursion" in cfg["transcription"]["prompt"]  # domain vocabulary

    await stt.append(1, b"\x00\x01" * 4800)
    await stt.commit(1)
    await stt.append(2, b"\x00\x01" * 2400)
    await stt.commit(2)
    await asyncio.sleep(0.05)
    assert finals == [(1, "Explain recursion to me."), (2, "Wait, stop.")]
    assert partials[0] == (1, "Explain") and partials[3] == (1, "Explain recursion to me.")
    assert ws.audio == 2 * (4800 + 2400)
    await stt.close()


async def test_context_bias_updates_the_prompt_only_when_it_changes(fake_realtime):
    servers, _ = fake_realtime
    stt = OpenAIRealtimeStt(make_settings(stt_provider="openai", openai_api_key="fake-openai-key-for-tests"))
    await stt.start()
    ws = servers[0]
    await stt.set_context("The base case stops the recursion.")
    await stt.set_context("The base case stops the recursion.")
    updates = [m for m in ws.sent if m["type"] == "session.update"]
    assert len(updates) == 2  # the initial one + one change
    assert updates[-1]["session"]["audio"]["input"]["transcription"]["prompt"].endswith(
        "The tutor just said: The base case stops the recursion.")
    await stt.close()


async def test_missing_key_is_a_clear_error():
    stt = OpenAIRealtimeStt(make_settings(stt_provider="openai", openai_api_key=None))
    with pytest.raises(Exception, match="OPENAI_API_KEY"):
        await stt.start()


async def test_mock_stt_is_scripted_and_streams_partials():
    stt = MockStt(["Explain recursion to me."], final_delay_s=0.01)
    partials, finals = [], []
    stt.on_partial = lambda u, t: partials.append(t)
    stt.on_final = lambda u, t: finals.append(t)
    await stt.append(1, b"\x00" * 48000)  # 1 s of audio → two words
    await stt.commit(1)
    await asyncio.sleep(0.05)
    assert partials[-1] == "Explain recursion" and finals == ["Explain recursion to me."]


def test_factory():
    assert create_stt(make_settings(stt_provider="off")) is None
    assert isinstance(create_stt(make_settings(stt_provider="mock")), MockStt)
    assert isinstance(create_stt(make_settings(stt_provider="openai")), OpenAIRealtimeStt)


async def test_an_unreachable_service_never_stalls_the_audio_path(monkeypatch):
    import time

    import websockets.asyncio.client as client

    dials = 0

    async def slow_failing_connect(*a, **kw):
        nonlocal dials
        dials += 1
        await asyncio.sleep(0.3)
        raise OSError("unreachable")

    monkeypatch.setattr(client, "connect", slow_failing_connect)
    stt = OpenAIRealtimeStt(make_settings(stt_provider="openai", openai_api_key="fake-openai-key-for-tests"))
    errors, finals = [], []
    stt.on_error = errors.append
    stt.on_final = lambda u, t: finals.append((u, t))
    t0 = time.monotonic()
    for _ in range(50):  # 50 audio frames while the service is down
        await stt.append(1, b"\x00\x01" * 960)
    await stt.commit(1)
    assert time.monotonic() - t0 < 0.2  # nothing waited for the dial
    assert finals == [(1, "")]  # the utterance is finished at once (no transcript will come)
    await asyncio.sleep(0.5)
    assert dials == 1 and errors  # one background attempt, then back-off
    await stt.close()


async def test_a_dropped_connection_finishes_pending_utterances_with_their_live_text(fake_realtime):
    servers, _ = fake_realtime
    stt = OpenAIRealtimeStt(make_settings(stt_provider="openai", openai_api_key="fake-openai-key-for-tests"))
    finals = []
    stt.on_final = lambda u, t: finals.append((u, t))
    await stt.start()
    stt._pending_commit.append(7)  # committed, transcript not back yet
    stt._text[7] = "Explain recur"
    await servers[0].close()  # the server goes away
    await asyncio.sleep(0.05)
    assert finals == [(7, "Explain recur")]
    assert stt._pending_commit == [] and stt._item_to_utt == {}
    await stt.close()
