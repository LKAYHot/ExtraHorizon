"""Per-session timeline of *measured* engine outputs and markers.

Only what the engine actually produced is stored (unknown periods stay unknown —
they are gaps in the chart, never zeros). Kept in memory for ``window_s``.
"""

from __future__ import annotations

from collections import deque
from typing import Any

Sample = tuple[int, float | None, float | None, str, str]  # t_ms, raw, smoothed, status, source


class Timeline:
    def __init__(self, window_s: float = 180.0, max_samples: int = 6000) -> None:
        self.window_ms = int(window_s * 1000)
        self._samples: deque[Sample] = deque(maxlen=max_samples)
        self._markers: deque[dict[str, Any]] = deque(maxlen=300)

    def clear(self) -> None:
        self._samples.clear()
        self._markers.clear()

    def add_sample(self, t_ms: int, raw: float | None, smoothed: float | None, status: str, source: str) -> None:
        self._samples.append(
            (t_ms, None if raw is None else round(raw, 3), None if smoothed is None else round(smoothed, 3), status, source)
        )

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
        markers = [m for m in self._markers if m["t"] >= cutoff]
        return {"samples": [list(s) for s in samples], "markers": markers}


def _decimate(samples: list[Sample], max_points: int) -> list[Sample]:
    """Bucket by time; per bucket keep the peak smoothed value (events stay visible)
    and one unknown sample if the bucket had any (gaps stay visible)."""
    buckets = max(1, max_points // 2)
    t0, t1 = samples[0][0], samples[-1][0]
    span = max(1, t1 - t0)
    out: list[Sample] = []
    cur: list[Sample] = []
    cur_idx = 0
    for s in samples:
        idx = min(buckets - 1, (s[0] - t0) * buckets // span)
        if idx != cur_idx and cur:
            out.extend(_bucket_repr(cur))
            cur = []
        cur_idx = idx
        cur.append(s)
    if cur:
        out.extend(_bucket_repr(cur))
    return out


def _bucket_repr(bucket: list[Sample]) -> list[Sample]:
    known = [s for s in bucket if s[2] is not None]
    unknown = [s for s in bucket if s[2] is None]
    rep: list[Sample] = []
    if known:
        rep.append(max(known, key=lambda s: s[2]))
    if unknown:
        rep.append(unknown[-1])
    rep.sort(key=lambda s: s[0])
    return rep
