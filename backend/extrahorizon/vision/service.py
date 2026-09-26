"""Process-wide vision resources: model availability, thread pool, camera slots,
and the shared emotion classifier."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..config import EMOTION_MODEL, FACE_LANDMARKER
from .model_fetch import ensure_asset

log = logging.getLogger("extrahorizon.vision")


def _import_runtime() -> None:
    import mediapipe  # noqa: F401
    import onnxruntime  # noqa: F401
    from mediapipe.tasks.python.vision import FaceLandmarker  # noqa: F401


class VisionService:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.available = False
        self.reason: str | None = "starting"
        self.emotion_available = False
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, settings.vision_workers), thread_name_prefix="eh-vision"
        )
        self._slots = asyncio.Semaphore(max(1, settings.vision_max_sessions))
        self._emotion = None
        self._emotion_lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "model": self.settings.vision_model_path.name,
            "emotion_model": self.settings.emotion_model_path.name if self.emotion_available else None,
        }

    async def startup(self) -> None:
        s = self.settings
        if not s.vision_enabled:
            self.available, self.reason = False, "disabled"
            return
        loop = asyncio.get_running_loop()
        ok, reason = await loop.run_in_executor(
            self.executor, lambda: ensure_asset(FACE_LANDMARKER, s.vision_model_path, allow_download=s.vision_auto_download)
        )
        if not ok:
            self.available, self.reason = False, reason
            return
        emo_ok, emo_reason = await loop.run_in_executor(
            self.executor, lambda: ensure_asset(EMOTION_MODEL, s.emotion_model_path, allow_download=s.vision_auto_download)
        )
        # Import check only. No MediaPipe task is created here: Google's MediaPipe wheels send
        # usage metrics when a task session runs, which must only happen after the user turned
        # the camera on (consent). A failure later is reported to that camera session.
        try:
            await loop.run_in_executor(self.executor, _import_runtime)
        except Exception as e:  # noqa: BLE001
            log.exception("vision runtime failed to import")
            self.available, self.reason = False, f"runtime_error: {type(e).__name__}"
            return
        self.emotion_available = emo_ok
        if not emo_ok:
            self.available, self.reason = False, f"emotion_{emo_reason}"
            return
        self.available, self.reason = True, None
        log.info("vision ready (MediaPipe Face Landmarker + EmotiEffLib emotion model, local CPU)")

    def emotion_classifier(self):
        """Shared ONNX session, created on first use (in a worker thread)."""
        with self._emotion_lock:
            if self._emotion is None:
                from ..emotion.classifier import EmotionClassifier

                self._emotion = EmotionClassifier(self.settings.emotion_model_path)
            return self._emotion

    def create_analyzer(self):
        from .analyzer import FaceAnalyzer

        s = self.settings
        return FaceAnalyzer(
            s.vision_model_path,
            max_faces=s.vision_max_faces,
            min_detection_confidence=s.vision_min_detection_confidence,
            min_presence_confidence=s.vision_min_presence_confidence,
            emotion=self.emotion_classifier(),
        )

    async def acquire_slot(self, timeout: float = 0.05) -> bool:
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout)
            return True
        except TimeoutError:
            return False

    def release_slot(self) -> None:
        self._slots.release()

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
