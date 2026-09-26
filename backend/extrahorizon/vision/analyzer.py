"""Frame analysis: MediaPipe Face Landmarker + facial-emotion classifier (local CPU).

One ``FaceAnalyzer`` per camera session (VIDEO mode keeps a face tracker and
needs strictly increasing timestamps). ``analyze_jpeg`` is blocking and is always
called from the vision thread pool, never on the event loop. Frames are decoded,
analysed and dropped — nothing is stored.

Only ``service.create_analyzer`` imports this module (lazily), so a broken OpenCV /
NumPy / MediaPipe install disables vision but never the chat.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import cv2
import numpy as np

from .types import FrameResult


def head_pose(matrix: np.ndarray) -> tuple[float, float, float]:
    """Yaw/pitch/roll in degrees from MediaPipe's 4×4 facial transformation matrix."""
    r = np.asarray(matrix, dtype=np.float64)[:3, :3]
    norms = np.linalg.norm(r, axis=0, keepdims=True)
    norms[norms == 0] = 1.0
    r = r / norms
    pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
    yaw = math.degrees(math.atan2(-r[2, 0], math.hypot(r[2, 1], r[2, 2])))
    roll = math.degrees(math.atan2(r[1, 0], r[0, 0]))
    return yaw, pitch, roll


def _bbox(landmarks) -> list[float]:
    xs = [p.x for p in landmarks]
    ys = [p.y for p in landmarks]
    x0, x1 = max(0.0, min(xs)), min(1.0, max(xs))
    y0, y1 = max(0.0, min(ys)), min(1.0, max(ys))
    return [round(x0, 4), round(y0, 4), round(max(0.0, x1 - x0), 4), round(max(0.0, y1 - y0), 4)]


class FaceAnalyzer:
    def __init__(
        self,
        model_path: Path,
        max_faces: int = 3,
        min_detection_confidence: float = 0.5,
        min_presence_confidence: float = 0.5,
        emotion=None,
    ) -> None:
        # imported lazily so the API (and the chat) still starts if MediaPipe is broken
        import mediapipe as mp
        from mediapipe.tasks.python.core.base_options import BaseOptions
        from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions, RunningMode

        self._mp = mp
        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=RunningMode.VIDEO,
            num_faces=max_faces,
            min_face_detection_confidence=min_detection_confidence,
            min_face_presence_confidence=min_presence_confidence,
            min_tracking_confidence=0.5,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = FaceLandmarker.create_from_options(options)
        self._last_ts = 0
        self._emotion = emotion  # shared EmotionClassifier (or None → faces only)

    def close(self) -> None:
        try:
            self._landmarker.close()
        except Exception:  # noqa: BLE001 — best effort on shutdown
            pass

    def analyze_jpeg(self, data: bytes) -> FrameResult:
        t0 = time.perf_counter()
        bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None or bgr.size == 0:
            return FrameResult(ok=False, error="bad_frame", proc_ms=(time.perf_counter() - t0) * 1000)
        return self.analyze_bgr(bgr, t0)

    def analyze_bgr(self, bgr: np.ndarray, t0: float | None = None) -> FrameResult:
        t0 = time.perf_counter() if t0 is None else t0
        mp = self._mp
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        ts = max(self._last_ts + 1, int(time.monotonic() * 1000))
        self._last_ts = ts
        try:
            res = self._landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
        except Exception:  # noqa: BLE001 — a failed frame must never kill the session
            return FrameResult(ok=False, error="analysis_failed", proc_ms=(time.perf_counter() - t0) * 1000)

        boxes = [_bbox(lms) for lms in res.face_landmarks]
        out = FrameResult(ok=True, faces=len(boxes), boxes=boxes)
        if len(boxes) == 1:
            if res.face_blendshapes:
                out.blendshapes = {c.category_name: float(c.score) for c in res.face_blendshapes[0]}
            if res.facial_transformation_matrixes:
                out.pose = head_pose(res.facial_transformation_matrixes[0])
            x, y, w, h = boxes[0]
            out.face_width = w
            fh, fw = bgr.shape[:2]
            x0, y0 = int(x * fw), int(y * fh)
            x1, y1 = max(x0 + 1, int((x + w) * fw)), max(y0 + 1, int((y + h) * fh))
            roi = bgr[y0:y1, x0:x1]
            if roi.size:
                out.brightness = float(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).mean())
            if self._emotion is not None:
                lms = res.face_landmarks[0]
                pts = np.array([[p.x * fw, p.y * fh] for p in lms], dtype=np.float64)
                crop = self._emotion.crop_aligned(bgr, pts) if len(pts) >= 455 else None
                if crop is None:
                    crop = self._emotion.crop(bgr, boxes[0])
                if crop is not None:
                    try:
                        out.emotion = self._emotion.predict(crop)
                    except Exception:  # noqa: BLE001 — never lose the face result over it
                        out.emotion = None
        out.proc_ms = (time.perf_counter() - t0) * 1000
        return out
