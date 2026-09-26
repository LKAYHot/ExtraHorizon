"""Streaming silence limiter for PCM s16le mono (Fish audio → browser player).

drama-3-preview sometimes "plays a pause": seconds of digital silence at the start of a
reply or between sentences (measured here: 5.3 s before the first word of a flustered
line; the owner's AzIAIBetter notes report 5-7 s in ~2 of 13 sad lines). Dead air kills a
live conversation, so:

* leading silence (before the first sound of a reply) is cut to ``lead_ms``;
* any later silence run is cut to ``cap_ms``;
* speech is never touched. Frame = 10 ms; "silence" = RMS below -55 dBFS.

Pure class, one instance per reply; state survives chunk boundaries (odd bytes too).
Idea and thresholds adapted from the owner's AzIAIBetter project (tts/silence.py).
"""

from __future__ import annotations

import numpy as np

SILENCE_FLOOR_DB = -55.0
_FLOOR = 10 ** (SILENCE_FLOOR_DB / 20)


class SilenceCap:
    def __init__(self, sample_rate: int, cap_ms: int, lead_ms: int) -> None:
        self.sample_rate = int(sample_rate)
        self.cap = max(0, int(self.sample_rate * cap_ms / 1000))
        self.lead = max(0, int(self.sample_rate * lead_ms / 1000))
        self.frame = max(1, int(self.sample_rate * 0.01))
        self.run = 0
        self.heard = False  # any sound yet in this reply?
        self.trimmed = 0
        self._odd = b""

    @property
    def trimmed_ms(self) -> int:
        return round(self.trimmed * 1000 / self.sample_rate)

    def feed(self, pcm: bytes) -> bytes:
        data = self._odd + pcm
        if len(data) % 2:
            data, self._odd = data[:-1], data[-1:]
        else:
            self._odd = b""
        if not data:
            return b""
        x = np.frombuffer(data, dtype="<i2")
        keep = np.ones(len(x), dtype=bool)
        cut = False
        for start in range(0, len(x), self.frame):
            frame = x[start : start + self.frame]
            level = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64)))) / 32768.0
            if level >= _FLOOR:
                self.run = 0
                self.heard = True
                continue
            limit = self.cap if self.heard else self.lead
            allowed = max(0, limit - self.run)
            self.run += len(frame)
            if allowed < len(frame):
                keep[start + allowed : start + len(frame)] = False
                self.trimmed += len(frame) - allowed
                cut = True
        return x[keep].tobytes() if cut else data
