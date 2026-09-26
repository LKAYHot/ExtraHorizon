"""Voice activity detection (Silero VAD, ONNX, local CPU) and turn segmentation.

Silero VAD v5 (MIT) scores 32 ms windows at 16 kHz in ~0.1 ms on a laptop CPU and stays
reliable in noise (checked here at SNR ≈ 5 dB). Browser audio arrives as 24 kHz PCM16;
it is resampled on the fly.

``VadSegmenter`` turns probabilities into conversation events:

* ``start``  — ≥ ``min_speech_ms`` of speech (a leaky counter, so one noisy dip does not
  reset it) opens an utterance; the last ``preroll_ms`` of audio is included so the first
  syllable is not lost;
* ``audio``  — utterance audio to stream to speech-to-text;
* ``end``    — ≥ ``end_silence_ms`` of silence closes it (comma pauses are shorter);
* while the tutor's voice is audible (``strict``) the bar to open an utterance is higher:
  ``barge_in_threshold`` held for ``barge_in_min_ms`` (her own voice leaking from the
  speakers, a door, a cough must not interrupt her). Such a ``start`` has ``barge=True``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

FRAME_16K = 512  # 32 ms
CONTEXT_16K = 64
FRAME_24K = 768  # 32 ms at 24 kHz
FRAME_MS = 32


class SileroVad:
    def __init__(self, model_path: Path) -> None:
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self._s = ort.InferenceSession(str(model_path), sess_options=so, providers=["CPUExecutionProvider"])
        self._sr = np.array(16000, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._ctx = np.zeros((1, CONTEXT_16K), dtype=np.float32)

    def prob(self, frame16: np.ndarray) -> float:
        x = np.concatenate([self._ctx, frame16.reshape(1, -1).astype(np.float32)], axis=1)
        out, self._state = self._s.run(None, {"input": x, "state": self._state, "sr": self._sr})
        self._ctx = x[:, -CONTEXT_16K:]
        return float(out[0][0])


def to16k(frame24: np.ndarray) -> np.ndarray:
    """768 samples @24 kHz → 512 @16 kHz (linear interpolation; plenty for VAD)."""
    src = np.arange(len(frame24), dtype=np.float32)
    dst = np.arange(FRAME_16K, dtype=np.float32) * (len(frame24) / FRAME_16K)
    return np.interp(dst, src, frame24).astype(np.float32)


@dataclass
class VadEvent:
    kind: str  # start | audio | end
    audio: bytes = b""
    duration_ms: int = 0
    prob: float = 0.0
    barge: bool = False  # start: opened under the strict (tutor audible) bar


class VadSegmenter:
    def __init__(self, vad: Any, settings: Any) -> None:
        self.vad = vad
        self.s = settings
        self._buf = b""
        preroll_frames = max(1, int(settings.vad_preroll_ms / FRAME_MS))
        self._preroll: deque[bytes] = deque(maxlen=preroll_frames)
        self.in_utt = False
        self._speech_ms = 0
        self._silence_ms = 0
        self._utt_ms = 0
        self._voiced_ms = 0
        self._barge_ms = 0
        self.last_prob = 0.0

    def reset(self) -> None:
        self._buf = b""
        self._preroll.clear()
        self.in_utt = False
        self._speech_ms = self._silence_ms = self._utt_ms = self._voiced_ms = self._barge_ms = 0
        if hasattr(self.vad, "reset"):
            self.vad.reset()

    def process(self, pcm24: bytes, strict: bool) -> list[VadEvent]:
        """``strict``: the tutor's voice is audible right now (barge-in rules apply)."""
        s = self.s
        events: list[VadEvent] = []
        self._buf += pcm24
        nbytes = FRAME_24K * 2
        while len(self._buf) >= nbytes:
            raw, self._buf = self._buf[:nbytes], self._buf[nbytes:]
            x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            p = self.vad.prob(to16k(x))
            self.last_prob = p
            if not self.in_utt:
                self._preroll.append(raw)
                if strict:
                    self._speech_ms = 0
                    if not s.barge_in:
                        continue
                    # stricter bar while the tutor talks (echo / noise must not interrupt her)
                    self._barge_ms = self._barge_ms + FRAME_MS if p >= s.barge_in_threshold else 0
                    if self._barge_ms >= s.barge_in_min_ms:
                        events.append(self._open(barge=True))
                    continue
                self._barge_ms = 0
                self._speech_ms = self._speech_ms + FRAME_MS if p >= s.vad_threshold else max(0, self._speech_ms - FRAME_MS // 2)
                if self._speech_ms >= s.vad_min_speech_ms:
                    events.append(self._open())
            else:
                self._utt_ms += FRAME_MS
                events.append(VadEvent("audio", audio=raw, prob=p))
                if p >= s.vad_threshold - 0.15:
                    self._silence_ms = 0
                    self._voiced_ms += FRAME_MS
                else:
                    self._silence_ms += FRAME_MS
                if self._silence_ms >= s.vad_end_silence_ms or self._utt_ms >= s.vad_max_utterance_s * 1000:
                    events.append(VadEvent("end", duration_ms=self._voiced_ms))
                    self.in_utt = False
                    self._speech_ms = self._silence_ms = self._utt_ms = self._voiced_ms = self._barge_ms = 0
                    self._preroll.clear()
        return events

    def _open(self, barge: bool = False) -> VadEvent:
        audio = b"".join(self._preroll)
        self._preroll.clear()
        self.in_utt = True
        self._silence_ms = 0
        self._utt_ms = len(audio) // 2 * 1000 // 24000
        self._voiced_ms = self._speech_ms or self._barge_ms
        self._speech_ms = self._barge_ms = 0
        return VadEvent("start", audio=audio, barge=barge)
