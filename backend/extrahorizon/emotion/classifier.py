"""Facial emotion classifier (EmotiEffLib ``enet_b0_8_va_mtl``, ONNX, local CPU).

EfficientNet-B0 trained on AffectNet by A. Savchenko et al. (EmotiEffLib / HSEmotion):
8 expression classes + valence + arousal from a 224×224 RGB face crop. One ONNX session is
shared by all camera sessions (ONNX Runtime sessions are safe for concurrent ``run`` calls).
Imported lazily — never on the chat path.

Input preparation (matters for accuracy):
* the face is **rotated upright** (eyes level, from the landmarks);
* the crop is a square over the whole face mesh plus 10 % (the framing of AffectNet face crops,
  no aspect distortion) — rotation, crop and resize in one affine warp;
* the crop and its mirror image are classified in one batch and their logits averaged
  (test-time augmentation: less noise, no left/right artefacts) — ≈10 ms per face.
The raw logits are kept: per-person calibration works on them (``calibration.py``).
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import cv2
import numpy as np

from ..vision.types import EMOTIONS, EmotionReading

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# MediaPipe face-mesh indices used to level the eyes
LEFT_EYE, RIGHT_EYE = [33, 133], [362, 263]


class EmotionClassifier:
    def __init__(self, model_path: Path, threads: int = 2, tta: bool = True) -> None:
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, threads)
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self._session = ort.InferenceSession(str(model_path), sess_options=so, providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name
        self.size = 224
        out = self._session.get_outputs()[0].shape[-1]
        self.has_va = out == len(EMOTIONS) + 2
        self.tta = tta

    @staticmethod
    def crop(bgr: np.ndarray, box: list[float], margin: float = 0.12) -> np.ndarray | None:
        """Square crop around a normalised face box (fallback without landmarks), as RGB."""
        h, w = bgr.shape[:2]
        x, y, bw, bh = box
        cx, cy = (x + bw / 2) * w, (y + bh / 2) * h
        side = max(bw * w, bh * h) * (1 + 2 * margin)
        x0, y0 = int(round(cx - side / 2)), int(round(cy - side / 2))
        x1, y1 = int(round(cx + side / 2)), int(round(cy + side / 2))
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        if x1 - x0 < 24 or y1 - y0 < 24:
            return None
        return cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)

    @staticmethod
    def crop_aligned(bgr: np.ndarray, pts: np.ndarray, size: int = 224, margin: float = 0.10) -> np.ndarray | None:
        """Upright square face crop from 478 face-mesh landmarks (pixels), as RGB ``size``×``size``.

        The square spans the whole face mesh (forehead to chin, cheek to cheek) plus ``margin`` —
        the framing of AffectNet face crops, with no aspect distortion; rotation, crop and resize
        are one affine warp (edges replicated if the face touches the frame border)."""
        le, re = pts[LEFT_EYE].mean(axis=0), pts[RIGHT_EYE].mean(axis=0)
        angle = math.degrees(math.atan2(re[1] - le[1], re[0] - le[0]))
        centre = (le + re) / 2
        rot = cv2.getRotationMatrix2D((float(centre[0]), float(centre[1])), angle, 1.0)
        up = np.c_[pts, np.ones(len(pts))] @ rot.T  # landmarks in the upright face frame
        x0, y0 = up.min(axis=0)
        x1, y1 = up.max(axis=0)
        side = max(x1 - x0, y1 - y0) * (1.0 + margin)
        if side < 24:
            return None
        s = size / side
        m = rot * s
        m[:, 2] -= s * np.array([(x0 + x1) / 2 - side / 2, (y0 + y1) / 2 - side / 2])
        face = cv2.warpAffine(bgr, m, (size, size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return cv2.cvtColor(face, cv2.COLOR_BGR2RGB)

    def _prepare(self, rgb: np.ndarray) -> np.ndarray:
        x = cv2.resize(rgb, (self.size, self.size), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        return ((x - _MEAN) / _STD).transpose(2, 0, 1).astype(np.float32)

    def predict(self, face_rgb: np.ndarray) -> EmotionReading:
        t0 = time.perf_counter()
        x = self._prepare(face_rgb)
        batch = np.stack([x, x[:, :, ::-1]]) if self.tta else x[np.newaxis]
        out = self._session.run(None, {self._input: np.ascontiguousarray(batch)})[0].mean(axis=0)
        if not np.isfinite(out).all():  # the caller turns this into "no estimate" (unknown), never neutral
            raise ValueError("non-finite expression-model output")
        logits = out[: len(EMOTIONS)].astype(np.float64)
        p = np.exp(logits - logits.max())
        p /= p.sum()
        valence = arousal = None
        if self.has_va:
            valence = float(np.clip(out[len(EMOTIONS)], -1.0, 1.0))
            arousal = float(np.clip(out[len(EMOTIONS) + 1], -1.0, 1.0))
        return EmotionReading(
            probs=tuple(float(v) for v in p), valence=valence, arousal=arousal,
            ms=(time.perf_counter() - t0) * 1000, logits=tuple(float(v) for v in logits),
        )
