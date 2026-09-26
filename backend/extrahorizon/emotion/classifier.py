"""Facial emotion classifier (EmotiEffLib ``enet_b0_8_va_mtl``, ONNX, local CPU).

EfficientNet-B0 trained on AffectNet by A. Savchenko et al. (EmotiEffLib / HSEmotion):
8 expression classes + valence + arousal from a 224×224 RGB face crop. One ONNX session is
shared by all camera sessions (ONNX Runtime sessions are safe for concurrent ``run`` calls).
Imported lazily — never on the chat path.

Input preparation (matters for accuracy):
* the face is **rotated upright** (eyes level, from the landmarks) before cropping;
* the crop follows the framing the model was trained on (detector-style box: part of the
  forehead above the brows down to just below the chin, cheek to cheek);
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

# MediaPipe face-mesh indices used for the crop
BROWS = [70, 63, 105, 66, 107, 336, 296, 334, 293, 300, 46, 53, 52, 65, 55, 285, 295, 282, 283, 276]
LEFT_EYE, RIGHT_EYE = [33, 133], [362, 263]
CHIN, CHEEK_L, CHEEK_R = 152, 234, 454


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
    def crop_aligned(bgr: np.ndarray, pts: np.ndarray) -> np.ndarray | None:
        """Upright, detector-style face crop from 478 face-mesh landmarks (pixels), as RGB."""
        le, re = pts[LEFT_EYE].mean(axis=0), pts[RIGHT_EYE].mean(axis=0)
        angle = math.degrees(math.atan2(re[1] - le[1], re[0] - le[0]))
        centre = (le + re) / 2
        brow_y, chin_y = pts[BROWS, 1].min(), pts[CHIN, 1]
        span = max(chin_y - brow_y, 8.0)
        half = max(abs(pts[CHEEK_R, 0] - pts[CHEEK_L, 0]), span) * 0.9
        # only warp the neighbourhood of the face (cheap), then rotate it upright
        x0, y0 = int(max(0, centre[0] - 2 * half)), int(max(0, centre[1] - 2 * half))
        x1, y1 = int(min(bgr.shape[1], centre[0] + 2 * half)), int(min(bgr.shape[0], centre[1] + 2 * half))
        if x1 - x0 < 24 or y1 - y0 < 24:
            return None
        patch = bgr[y0:y1, x0:x1]
        m = cv2.getRotationMatrix2D((float(centre[0] - x0), float(centre[1] - y0)), angle, 1.0)
        upright = cv2.warpAffine(patch, m, (patch.shape[1], patch.shape[0]), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)
        p = np.c_[pts - [x0, y0], np.ones(len(pts))] @ m.T
        brow_y, chin_y = p[BROWS, 1].min(), p[CHIN, 1]
        span = chin_y - brow_y
        left, right = min(p[CHEEK_L, 0], p[CHEEK_R, 0]), max(p[CHEEK_L, 0], p[CHEEK_R, 0])
        top, bottom = brow_y - 0.22 * span, chin_y + 0.04 * span
        cx0, cy0 = int(max(0, left)), int(max(0, top))
        cx1, cy1 = int(min(upright.shape[1], right)), int(min(upright.shape[0], bottom))
        if cx1 - cx0 < 24 or cy1 - cy0 < 24:
            return None
        return cv2.cvtColor(upright[cy0:cy1, cx0:cx1], cv2.COLOR_BGR2RGB)

    def _prepare(self, rgb: np.ndarray) -> np.ndarray:
        x = cv2.resize(rgb, (self.size, self.size), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        return ((x - _MEAN) / _STD).transpose(2, 0, 1).astype(np.float32)

    def predict(self, face_rgb: np.ndarray) -> EmotionReading:
        t0 = time.perf_counter()
        x = self._prepare(face_rgb)
        batch = np.stack([x, x[:, :, ::-1]]) if self.tta else x[np.newaxis]
        out = self._session.run(None, {self._input: np.ascontiguousarray(batch)})[0].mean(axis=0)
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
