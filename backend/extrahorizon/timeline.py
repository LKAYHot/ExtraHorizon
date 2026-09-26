"""Per-session timeline of *measured* emotion estimates and markers.

Only what the engine produced is stored; unknown periods stay unknown (gaps in the
chart, never zeros). Kept in memory for ``window_s``.

Sample layout (compact for the socket):
  [t_ms, status, source, dominant|None, probs[8]|None, valence|None, arousal|None]
"""

from __future__ import annotations

from collections import deque
from typing import Any


class Timeline:
    def __init__(self, window_s: float = 180.0, max_samples: int = 6000) -> None:
        self.window_ms = int(window_s * 1000)
        self._samples: deque[list[Any]] = deque(maxlen=max_samples)
        self._markers: deque[dict[str, Any]] = deque(maxlen=300)

    def clear(self) -> None:
        self._samples.clear()
        self._markers.clear()

    def add_sample(self, t_ms: int, state: dict[str, Any]) -> list[Any]:
        probs = state.get("probs")
        sample = [
            t_ms,
            state["status"],
            state["source"],
            state.get("dominant"),
            None if probs is None else [round(v, 2) for v in probs.values()],
            None if state.get("valence") is None else round(state["valence"], 2),
            None if state.get("arousal") is None else round(state["arousal"], 2),
        ]
        self._samples.append(sample)
        return sample

    def add_marker(self, t_ms: int, kind: str, label: str, ref: str | None = None) -> dict[str, Any]:
        m = {"t": t_ms, "kind": kind, "label": label, "ref": ref}
        self._markers.append(m)
        return m

    def __len__(self) -> int:
        return len(self._samples)

    def snapshot(self, now_ms: int, max_points: int = 400) -> dict[str, Any]:
        cutoff = now_ms - self.window_ms
        samples = [s for s in self._samples if s[0] >= cutoff]
        if len(samples) > max_points:
            samples = _decimate(samples, max_points)
        return {"samples": samples, "markers": [m for m in self._markers if m["t"] >= cutoff]}


def _decimate(samples: list[list[Any]], max_points: int) -> list[list[Any]]:
    """Bucket by time; keep the last known sample of each bucket, plus one unknown sample
    when the bucket had any (gaps stay visible)."""
    buckets = max(1, max_points // 2)
    t0, t1 = samples[0][0], samples[-1][0]
    span = max(1, t1 - t0)
    out: list[list[Any]] = []
    cur: list[list[Any]] = []
    cur_idx = 0
    for s in samples:
        idx = min(buckets - 1, (s[0] - t0) * buckets // span)
        if idx != cur_idx and cur:
            out.extend(_repr(cur))
            cur = []
        cur_idx = idx
        cur.append(s)
    if cur:
        out.extend(_repr(cur))
    return out


def _repr(bucket: list[list[Any]]) -> list[list[Any]]:
    known = [s for s in bucket if s[4] is not None]
    unknown = [s for s in bucket if s[4] is None]
    rep = ([known[-1]] if known else []) + ([unknown[-1]] if unknown else [])
    rep.sort(key=lambda s: s[0])
    return rep
