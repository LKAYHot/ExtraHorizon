"""Voice out: Fish cue handling, the streaming splitter, silence trimming, fillers and the
Fish Audio WebSocket client (against a fake server — no network, no credits)."""

from __future__ import annotations

import asyncio
import math

import numpy as np
import ormsgpack
import pytest

from extrahorizon.voice.fillers import FILLERS, FillerBank
from extrahorizon.voice.fish import FishEngine, FishSession, MockTts, fish_url
from extrahorizon.voice.silence import SilenceCap
from extrahorizon.voice.splitter import TtsSplitter
from extrahorizon.voice.tags import is_sound_or_timing, iter_parts, speakable, strip_tags

from .conftest import make_settings

SR = 44100


def tone(seconds: float, amp: float = 0.3) -> bytes:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * math.pi * 220 * t) * 32767).astype("<i2").tobytes()


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * SR)


# ---------------------------------------------------------------------- cues
def test_cues_are_parsed_stripped_and_classified():
    text = "[huffy and flustered] Hmph. [sighing] Fine, I'll explain."
    assert [k for k, _ in iter_parts(text)] == ["tag", "text", "tag", "text"]
    assert strip_tags(text) == "Hmph. Fine, I'll explain."
    assert is_sound_or_timing("sighing") and is_sound_or_timing("break") and is_sound_or_timing("Laughing")
    assert not is_sound_or_timing("huffy and flustered")


def test_speakable_keeps_cues_and_removes_what_must_not_be_read():
    s = speakable("[smug] Use `len(x)` — see **this**: https://example.com/x ```python\nprint(1)\n``` [ curious] ok [1")
    assert "[smug]" in s and "[curious]" in s  # cue kept (and tidied)
    assert "`" not in s and "**" not in s and "print(1)" not in s and "[break]" in s
    assert "the link" in s and "https" not in s
    assert "[1" not in s  # a stray bracket would be read aloud


def test_maths_is_spoken_in_words_not_as_latex():
    s = speakable(r"[calm] If position is \(x(t)=t^2\), the speed is \(2t\); \[ \frac{a}{b} \le \pi \]")
    assert "\\" not in s and "t squared" in s and "a over b" in s and "is at most pi" in s
    assert s.startswith("[calm]")  # a "\[" is not mistaken for a voice cue
    assert speakable("It costs $5 and $10.") == "It costs $5 and $10."  # money stays money


# ---------------------------------------------------------------------- splitter
def run_split(deltas: list[str], **kw) -> list[str]:
    sp = TtsSplitter(**kw)
    out: list[str] = []
    for d in deltas:
        out += sp.feed(d)
    return out + sp.flush()


def test_first_chunk_leaves_early_at_a_clause():
    sp = TtsSplitter(first_chars=36, chunk_chars=140)
    out = sp.feed("[huffy] Hmph, it is not like I wanted to explain this to you, but")
    assert out and out[0].startswith("[huffy] Hmph, it is not like I wanted to explain this to you,")


def test_never_cuts_inside_a_cue_and_glues_cue_only_pieces():
    out = run_split(["Okay then. [huffy and fl", "ustered] Fine. [sighing]", " I'll do it."])
    assert all(c.count("[") == c.count("]") for c in out)
    joined = " ".join(out)
    assert "[huffy and flustered] Fine." in joined
    assert not any(strip_tags(c).strip(" .,!?") == "" for c in out)  # no chunk made of cues only


def test_delivery_cue_is_carried_to_the_continuation_but_sounds_are_not():
    long = "[soft, a little embarrassed] " + "this sentence keeps going and going, " * 6 + "[chuckling] even for you."
    out = run_split([long], first_chars=36, chunk_chars=80)
    assert len(out) >= 3
    for c in out[1:]:
        assert c.startswith("[soft, a little embarrassed]")
    assert sum(c.count("[chuckling]") for c in out) == 1


def test_markdown_and_code_are_not_sent_to_the_voice():
    out = run_split(["Use **this**:\n```python\nprint(1)\n```\nDone."])
    joined = " ".join(out)
    assert "print(1)" not in joined and "**" not in joined and "Done." in joined


# ---------------------------------------------------------------------- silence
def test_silence_cap_trims_dead_air_but_not_speech():
    cap = SilenceCap(SR, cap_ms=700, lead_ms=120)
    out = cap.feed(silence(2.0) + tone(0.5) + silence(3.0) + tone(0.5))
    secs = len(out) / 2 / SR
    assert 0.5 + 0.12 + 0.7 + 0.5 - 0.02 <= secs <= 0.5 + 0.12 + 0.7 + 0.5 + 0.03
    assert cap.trimmed_ms > 4000


def test_silence_cap_handles_odd_byte_chunks():
    cap = SilenceCap(SR, cap_ms=700, lead_ms=120)
    data = tone(0.2)
    out = b"".join(cap.feed(data[i : i + 1001]) for i in range(0, len(data), 1001))
    assert out == data


# ---------------------------------------------------------------------- fillers
@pytest.mark.asyncio
async def test_fillers_are_synthesized_once_cached_and_varied(tmp_path):
    s = make_settings(cache_dir=tmp_path)
    bank = FillerBank(MockTts(SR, delay_s=0), s)
    await bank.prepare()
    assert bank.ready and len(bank.items) == len(FILLERS) and bank.state == "ready"
    picks = [bank.pick().text for _ in range(6)]
    assert all(a != b for a, b in zip(picks, picks[1:]))  # no immediate repeats
    assert all(bank.pick("sadness").group in ("gentle", "neutral") for _ in range(5))

    class NoTts:
        configured = True

        async def synthesize(self, text: str) -> bytes:
            raise AssertionError("cached fillers must not be synthesized again")

    again = FillerBank(NoTts(), s)
    await again.prepare()
    assert len(again.items) == len(FILLERS)


# ---------------------------------------------------------------------- Fish Audio client
class FakeFishServer:
    """Speaks the msgpack protocol of wss://api.fish.audio/v1/tts/live[/with-timestamp]."""

    def __init__(self, fail: str | None = None, lead_silence_s: float = 0.0) -> None:
        self.received: list[dict] = []
        self._q: asyncio.Queue = asyncio.Queue()
        self.fail = fail
        self.lead = lead_silence_s
        self.closed = False
        self.state = None

    async def send(self, data: bytes) -> None:
        msg = ormsgpack.unpackb(data)
        self.received.append(msg)
        ev = msg.get("event")
        if ev == "flush":
            if self.fail:
                self._q.put_nowait(ormsgpack.packb({"event": "error", "error": self.fail}))
                return
            self._q.put_nowait(ormsgpack.packb({"event": "audio", "audio": b""}))  # alignment-only frame
            self._q.put_nowait(ormsgpack.packb({"event": "audio", "audio": silence(self.lead) + tone(0.2)}))
            self.lead = 0.0
        elif ev == "stop":
            self._q.put_nowait(ormsgpack.packb({"event": "finish", "reason": "stop"}))

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._q.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        self.closed = True
        self._q.put_nowait(None)


def fish_settings(**kw):
    return make_settings(tts_provider="fish", fish_api_key="test-key-not-real", **kw)


@pytest.mark.asyncio
async def test_fish_session_protocol_and_audio():
    s = fish_settings()
    ws = FakeFishServer(lead_silence_s=2.0)
    session = FishSession(ws, s)
    await session.begin()
    await session.send("[huffy] Hmph.")
    await session.send("[proud] Fine.")
    await session.finish()
    pcm = b"".join([c async for c in session.audio()])
    start = ws.received[0]
    assert start["event"] == "start"
    req = start["request"]
    assert req["reference_id"] == "c5d8a284092847df9e3c7308aeedc5f2" and req["format"] == "pcm"
    assert req["sample_rate"] == SR and req["latency"] == "balanced"
    assert [m["event"] for m in ws.received[1:]] == ["text", "flush", "text", "flush", "stop"]
    assert ws.received[1]["text"].startswith("[huffy] Hmph.")
    assert session.failed == ""
    # two 0.2 s replies; the 2 s of leading model silence was cut to the 120 ms cap
    assert 0.39 <= len(pcm) / 2 / SR <= 0.4 + 0.121


@pytest.mark.asyncio
async def test_fish_error_event_ends_the_reply_with_a_reason():
    session = FishSession(FakeFishServer(fail="quota exceeded"), fish_settings())
    await session.begin()
    await session.send("Hello.")
    chunks = [c async for c in session.audio()]
    assert chunks == [] and "quota exceeded" in session.failed


def test_drama_model_uses_the_timestamp_endpoint():
    assert fish_url(fish_settings(fish_model="drama-3-preview")).endswith("/v1/tts/live/with-timestamp")
    assert fish_url(fish_settings(fish_model="s1")).endswith("/v1/tts/live")


@pytest.mark.asyncio
async def test_fish_engine_dials_with_model_header_and_keeps_a_warm_socket(monkeypatch):
    import websockets.asyncio.client as client

    dials = []

    async def fake_connect(url, additional_headers=None, **kw):
        dials.append((url, dict(additional_headers or {})))
        ws = FakeFishServer()
        ws.state = __import__("websockets.protocol", fromlist=["State"]).State.OPEN
        return ws

    monkeypatch.setattr(client, "connect", fake_connect)
    engine = FishEngine(fish_settings())
    await engine.warmup()
    assert engine.status()["warm"] == 1
    session = await engine.open_session()
    assert isinstance(session, FishSession)
    url, headers = dials[0]
    assert url.endswith("/with-timestamp") and headers["model"] == "drama-3-preview"
    assert headers["Authorization"] == "Bearer test-key-not-real"
    await session.abort()
    await engine.aclose()


@pytest.mark.asyncio
async def test_unreachable_fish_opens_the_breaker(monkeypatch):
    import websockets.asyncio.client as client

    calls = 0

    async def failing_connect(*a, **kw):
        nonlocal calls
        calls += 1
        raise OSError("network down")

    monkeypatch.setattr(client, "connect", failing_connect)
    engine = FishEngine(fish_settings())
    for _ in range(3):
        with pytest.raises(Exception):
            await engine.open_session()
    assert engine.status()["state"] == "down"
    with pytest.raises(Exception):
        await engine.open_session()
    assert calls == 3  # no more dialing while the breaker is open
