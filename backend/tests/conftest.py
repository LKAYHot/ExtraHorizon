"""Shared fixtures. Tests never read the real .env and never call OpenAI or Fish Audio."""

from __future__ import annotations

import asyncio
import json
import math
import os
import urllib.request
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from extrahorizon.config import Settings
from extrahorizon.llm import BaseLLM, LLMError, StreamInfo

CACHE = Path(__file__).parent / ".cache"
PORTRAIT_URL = "https://storage.googleapis.com/mediapipe-assets/portrait.jpg"


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in list(os.environ):
        if k.startswith("EH_") or k in ("OPENAI_API_KEY", "FISH_API_KEY"):
            monkeypatch.delenv(k, raising=False)


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        llm_provider="mock",
        openai_api_key=None,
        fish_api_key=None,
        tts_provider="mock",
        stt_provider="mock",
        vision_enabled=False,
        vision_auto_download=False,
        static_dir=Path("__no_ui__"),
        cache_dir=CACHE / "runtime",
        llm_first_token_timeout_s=0.4,
        llm_idle_timeout_s=0.4,
        llm_total_timeout_s=5.0,
        mock_llm_delay_s=0.0,
        stt_final_timeout_s=1.5,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


class FakeLLM(BaseLLM):
    """Scriptable provider double. ``script`` is consumed one entry per request:
    "ok" | "error" | "hang" | "stall" | "fail_mid" | "slow" (one word per 50 ms)."""

    provider = "fake"
    model = "fake-model"

    def __init__(self, script: list[str] | None = None,
                 text: str = "[smug] Hmph. Recursion is a function calling itself. [proud] Easy.") -> None:
        super().__init__()
        self.script = list(script or [])
        self.text = text
        self.requests: list[list[dict[str, str]]] = []
        self.closed = 0

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str | StreamInfo]:
        self.requests.append(messages)
        mode = self.script.pop(0) if self.script else "ok"
        try:
            if mode == "error":
                raise LLMError("llm_upstream", "Upstream failed (fake).", True)
            if mode == "hang":
                await asyncio.sleep(3600)
            words = self.text.split(" ")
            for i, w in enumerate(words):
                if mode == "slow":
                    await asyncio.sleep(0.05)
                yield w + (" " if i < len(words) - 1 else "")
                if mode == "stall" and i == 1:
                    await asyncio.sleep(3600)
                if mode == "fail_mid" and i == 1:
                    raise LLMError("llm_unreachable", "Connection dropped (fake).", True)
            yield StreamInfo(model=self.model, finish_reason="stop")
        finally:
            self.closed += 1


class FakeVision:
    """Stands in for VisionService without MediaPipe."""

    def __init__(self, available: bool = False, reason: str | None = "disabled", analyzer_factory=None) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self.available = available
        self.reason = reason
        self.executor = ThreadPoolExecutor(max_workers=2)
        self._factory = analyzer_factory

    def status(self) -> dict[str, Any]:
        return {"available": self.available, "reason": self.reason, "model": "fake"}

    async def startup(self) -> None:
        return None

    def create_analyzer(self):
        if self._factory is None:
            raise RuntimeError("no analyzer")
        return self._factory()

    async def acquire_slot(self, timeout: float = 0.05) -> bool:
        return True

    def release_slot(self) -> None:
        return None

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


class EnergyVad:
    """Deterministic stand-in for Silero: 'speech' = a 32 ms frame louder than -30 dBFS."""

    def reset(self) -> None:
        return None

    def prob(self, frame16: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(frame16, dtype=np.float64))))
        return 0.95 if rms > 0.03 else 0.02


def speech_pcm(seconds: float, rate: int = 24000, amp: float = 0.3) -> bytes:
    """Voiced-looking test signal (a 180 Hz tone + harmonics), PCM16 little-endian."""
    t = np.arange(int(seconds * rate)) / rate
    x = amp * (np.sin(2 * math.pi * 180 * t) + 0.4 * np.sin(2 * math.pi * 360 * t)) / 1.4
    return (x * 32767).astype("<i2").tobytes()


def silence_pcm(seconds: float, rate: int = 24000) -> bytes:
    return b"\x00\x00" * int(seconds * rate)


def new_sid() -> str:
    return str(uuid.uuid4())


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
        if name:
            events.append((name, data))
    return events


@pytest.fixture(scope="session")
def portrait_jpeg() -> bytes:
    """A real portrait photo from the official MediaPipe test assets (downloaded once,
    cached, git-ignored). Tests that need it are skipped when offline."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / "portrait.jpg"
    if not path.exists():
        try:
            with urllib.request.urlopen(PORTRAIT_URL, timeout=20) as r:
                path.write_bytes(r.read())
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"test image unavailable offline: {e}")
    return path.read_bytes()


def _asset(name: str):
    from extrahorizon import config
    from extrahorizon.vision.model_fetch import ensure_asset

    asset = {"face": config.FACE_LANDMARKER, "emotion": config.EMOTION_MODEL, "vad": config.SILERO_VAD}[name]
    path = config.MODELS_DIR / asset.filename
    ok, reason = ensure_asset(asset, path)
    if not ok:
        pytest.skip(f"{asset.filename} unavailable: {reason}")
    return path


@pytest.fixture(scope="session")
def model_path() -> Path:
    return _asset("face")


@pytest.fixture(scope="session")
def emotion_model_path() -> Path:
    return _asset("emotion")


@pytest.fixture(scope="session")
def vad_model_path() -> Path:
    return _asset("vad")
