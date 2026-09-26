"""Runtime configuration.

Every tunable of the demo lives here and can be overridden from the environment
or the repo-level ``.env`` file (prefix ``EH_``; the OpenAI key uses the standard
``OPENAI_API_KEY``). The engine/proxy numbers are *working hypotheses* from the
spec (alpha 0.2, threshold 0.65, 2 s hold, 15 s cooldown) and are meant to be
re-tuned after a trial with the real camera (see docs/CONFUSION_PROXY.md).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
FACE_LANDMARKER_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EH_",
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ------------------------------------------------------------------ server
    host: str = "127.0.0.1"
    port: int = 8765
    static_dir: Path = REPO_ROOT / "frontend" / "build"
    # extra browser origins allowed to call the API / open the vision socket
    # (the server's own origin and the Vite dev server are always allowed)
    allowed_origins: list[str] = Field(default_factory=list)
    # extra Host names accepted besides loopback (needed for LAN access when bound to 0.0.0.0);
    # never "*" — an open Host check lets a DNS-rebinding web page drive the API and camera socket
    allowed_hosts: list[str] = Field(default_factory=list)
    log_level: str = "info"

    # ------------------------------------------------------------------ LLM (one provider: OpenAI)
    llm_provider: Literal["openai", "mock"] = "openai"
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "EH_OPENAI_API_KEY")
    )
    openai_base_url: str | None = None
    llm_model: str = "gpt-6-luna"
    # used only when the primary model is rejected as unknown (404) before streaming
    llm_fallback_model: str | None = "gpt-5.5"
    # "none" = no hidden reasoning → lowest latency; empty string = don't send it
    llm_reasoning_effort: str = "none"
    llm_max_output_tokens: int = 700
    llm_first_token_timeout_s: float = 15.0
    llm_idle_timeout_s: float = 20.0
    llm_total_timeout_s: float = 60.0
    llm_history_turns: int = 8  # previous exchanges sent as context
    mock_llm_delay_s: float = 0.03  # per streamed word of the offline mock

    # ------------------------------------------------------------------ vision
    vision_enabled: bool = True
    vision_model_path: Path = BACKEND_DIR / "models" / "face_landmarker.task"
    vision_auto_download: bool = True
    vision_max_faces: int = 3  # detect up to N so that ">1 face" is recognised
    vision_min_detection_confidence: float = 0.5
    vision_min_presence_confidence: float = 0.5
    vision_workers: int = 4
    vision_max_sessions: int = 4  # concurrent camera sessions (one landmarker each)
    frame_width: int = 480
    jpeg_quality: float = 0.75
    max_fps: float = 12.0
    max_frame_bytes: int = 512 * 1024

    # quality gates → "unknown"
    min_face_width: float = 0.11  # fraction of frame width
    max_abs_yaw_deg: float = 32.0
    max_abs_pitch_deg: float = 28.0
    min_brightness: float = 40.0  # mean luma of the face box, 0..255
    max_brightness: float = 235.0

    # neutral-baseline calibration (per session)
    calibration_s: float = 2.5
    calibration_min_samples: int = 10

    # confusion proxy (see vision/proxy.py) — weights of a noisy-OR over
    # baseline-corrected blendshape deviations
    proxy_w_brow: float = 0.85
    proxy_w_lid: float = 0.45
    proxy_w_press: float = 0.30
    proxy_scale_brow: float = 0.30
    proxy_scale_lid: float = 0.30
    proxy_scale_press: float = 0.30
    proxy_min_scale: float = 0.12
    proxy_smile_start: float = 0.15
    proxy_smile_full: float = 0.45

    # ------------------------------------------------------------------ state engine
    ema_alpha: float = 0.2
    ema_reference_fps: float = 10.0
    threshold: float = 0.65
    hold_s: float = 2.0
    cooldown_s: float = 15.0
    max_gap_s: float = 0.75
    relief_threshold: float = 0.45
    relief_hold_s: float = 2.0
    relief_window_s: float = 60.0
    rearm_threshold: float = 0.55  # after an event, fire again only once smoothed fell below this (or a new answer)
    event_ttl_s: float = 180.0

    # ------------------------------------------------------------------ sessions
    max_sessions: int = 64
    session_idle_ttl_s: float = 3600.0
    timeline_window_s: float = 180.0
    timeline_snapshot_points: int = 400

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "mock":
            return True
        key = self.openai_api_key.get_secret_value().strip() if self.openai_api_key else ""
        return bool(key)

    def public_engine_config(self) -> dict:
        return {
            "alpha": self.ema_alpha,
            "reference_fps": self.ema_reference_fps,
            "threshold": self.threshold,
            "hold_s": self.hold_s,
            "cooldown_s": self.cooldown_s,
        }

    def public_vision_config(self) -> dict:
        return {
            **self.public_engine_config(),
            "max_fps": self.max_fps,
            "frame_width": self.frame_width,
            "jpeg_quality": self.jpeg_quality,
            "calibration_s": self.calibration_s,
            "relief_threshold": self.relief_threshold,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
