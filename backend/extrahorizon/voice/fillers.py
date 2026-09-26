"""Conversational fillers ("Hmm...", "Uhh... let me see", "Hmph.") in the tutor's voice.

They are synthesized once with the same Fish voice/model, cached on disk
(``cache/fillers``, git-ignored) and played the instant the learner stops talking —
covering the transcription + first-token + first-audio gap (~1.5 s) with something
natural instead of silence. Picked without immediate repeats and softer when the learner
looks sad or anxious.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .silence import SilenceCap

log = logging.getLogger("extrahorizon.fillers")

# (text with a drama cue, mood group)
FILLERS: tuple[tuple[str, str], ...] = (
    ("[thinking, drawn out] Hmm...", "neutral"),
    ("[hesitant, thinking out loud] Uhh... let me see.", "neutral"),
    ("[huffy, short] Hmph.", "tsun"),
    ("[exasperated, with a sigh] Ugh... fine.", "tsun"),
    ("[flustered] W-well...", "tsun"),
    ("[curious, rising] Ehh?", "neutral"),
    ("[soft, thoughtful hum] Mmm...", "gentle"),
    ("[gentle, a little worried] Okay, okay...", "gentle"),
    ("[smug] Heh.", "playful"),
)
MAX_FILLER_S = 1.6


@dataclass
class Filler:
    text: str
    group: str
    pcm: bytes


class FillerBank:
    def __init__(self, tts: Any, settings: Any) -> None:
        self.tts = tts
        self.s = settings
        self.items: list[Filler] = []
        self._recent: list[str] = []
        self._task: asyncio.Task | None = None
        self.state = "idle"

    @property
    def ready(self) -> bool:
        return bool(self.items)

    def _cache_path(self, text: str) -> Path:
        key = f"{self.s.fish_model}|{self.s.fish_reference_id}|{self.s.tts_sample_rate}|{text}"
        return Path(self.s.cache_dir) / "fillers" / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".pcm")

    def _trim(self, pcm: bytes) -> bytes:
        cap = SilenceCap(self.s.tts_sample_rate, cap_ms=250, lead_ms=0)
        out = cap.feed(pcm)
        max_bytes = int(self.s.tts_sample_rate * MAX_FILLER_S) * 2
        return out[:max_bytes]

    def start(self) -> None:
        if self.s.fillers_enabled and getattr(self.tts, "configured", False) and self._task is None:
            self._task = asyncio.create_task(self.prepare())

    async def prepare(self) -> None:
        self.state = "preparing"
        for text, group in FILLERS:
            path = self._cache_path(text)
            try:
                if path.exists() and path.stat().st_size > 2000:
                    pcm = path.read_bytes()
                else:
                    pcm = self._trim(await self.tts.synthesize(text))
                    if len(pcm) < 2000:
                        continue
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(pcm)
                self.items.append(Filler(text, group, pcm))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — fillers are a nicety, never fatal
                log.warning("filler %r not prepared: %s", text, e)
        self.state = "ready" if self.items else "failed"
        log.info("fillers ready: %d/%d", len(self.items), len(FILLERS))

    def pick(self, mood: str | None = None) -> Filler | None:
        if not self.items:
            return None
        prefer = {"sadness": "gentle", "fear": "gentle", "anger": "gentle", "happiness": "playful"}.get(mood or "")
        pool = [f for f in self.items if f.text not in self._recent]
        if prefer:
            preferred = [f for f in pool if f.group in (prefer, "neutral")]
            pool = preferred or pool
        else:
            pool = [f for f in pool if f.group != "gentle"] or pool
        choice = random.choice(pool or self.items)
        self._recent = ([choice.text] + self._recent)[:3]
        return choice

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
