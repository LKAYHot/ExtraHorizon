"""Process-wide vision resources: availability check, thread pool, camera slots."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .model_fetch import ensure_model

log = logging.getLogger("extrahorizon.vision")


def _import_mediapipe() -> None:
    import mediapipe  # noqa: F401
    from mediapipe.tasks.python.vision import FaceLandmarker  # noqa: F401


class VisionService:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.available = False
        self.reason: str | None = "starting"
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, settings.vision_workers), thread_name_prefix="eh-vision"
        )
        self._slots = asyncio.Semaphore(max(1, settings.vision_max_sessions))

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "model": self.settings.vision_model_path.name,
        }

    async def startup(self) -> None:
        s = self.settings
        if not s.vision_enabled:
            self.available, self.reason = False, "disabled"
            return
        loop = asyncio.get_running_loop()
        ok, reason = await loop.run_in_executor(
            self.executor,
            lambda: ensure_model(s.vision_model_path, allow_download=s.vision_auto_download),
        )
        if not ok:
            self.available, self.reason = False, reason
            return
        # Import check only. We deliberately do NOT create a landmarker here: Google's
        # MediaPipe wheels send usage metrics when a task session ends, and that must only
        # happen after the user has turned the camera on (consent). A landmarker that fails
        # later is reported to that camera session as "vision_unavailable"; chat is unaffected.
        try:
            await loop.run_in_executor(self.executor, _import_mediapipe)
        except Exception as e:  # noqa: BLE001
            log.exception("MediaPipe failed to import")
            self.available, self.reason = False, f"mediapipe_error: {type(e).__name__}"
            return
        self.available, self.reason = True, None
        log.info("vision ready (MediaPipe Face Landmarker, local CPU; created per camera session)")

    def create_analyzer(self):
        from .analyzer import FaceAnalyzer

        s = self.settings
        return FaceAnalyzer(
            s.vision_model_path,
            max_faces=s.vision_max_faces,
            min_detection_confidence=s.vision_min_detection_confidence,
            min_presence_confidence=s.vision_min_presence_confidence,
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
