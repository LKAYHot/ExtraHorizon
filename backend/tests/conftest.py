"""Shared fixtures. Tests never read the real .env and never call OpenAI."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from extrahorizon.config import Settings
from extrahorizon.llm import BaseLLM, LLMError, StreamInfo

CACHE = Path(__file__).parent / ".cache"
PORTRAIT_URL = "https://storage.googleapis.com/mediapipe-assets/portrait.jpg"


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in list(os.environ):
        if k.startswith("EH_") or k == "OPENAI_API_KEY":
            monkeypatch.delenv(k, raising=False)


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        llm_provider="mock",
        openai_api_key=None,
        vision_enabled=False,
        static_dir=Path("__no_ui__"),
        # fast but proportionally identical engine timings for tests
        hold_s=0.3,
        cooldown_s=1.5,
        max_gap_s=0.75,
        relief_hold_s=0.3,
        llm_first_token_timeout_s=0.4,
        llm_idle_timeout_s=0.4,
        llm_total_timeout_s=5.0,
        mock_llm_delay_s=0.0,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


class FakeLLM(BaseLLM):
    """Scriptable provider double. ``script`` is consumed one entry per request:
    "ok" | "error" | "hang" | "stall" | "fail_mid"."""

    provider = "fake"
    model = "fake-model"

    def __init__(self, script: list[str] | None = None, text: str = "Recursion is a function calling itself.") -> None:
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


@pytest.fixture(scope="session")
def model_path() -> Path:
    from extrahorizon.config import BACKEND_DIR
    from extrahorizon.vision.model_fetch import ensure_model

    path = BACKEND_DIR / "models" / "face_landmarker.task"
    ok, reason = ensure_model(path)
    if not ok:
        pytest.skip(f"MediaPipe model unavailable: {reason}")
    return path
