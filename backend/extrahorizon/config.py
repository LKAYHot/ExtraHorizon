"""Runtime configuration.

Every tunable lives here and can be overridden from the environment or the repo-level
``.env`` file (prefix ``EH_``; the provider keys use their standard names
``OPENAI_API_KEY`` and ``FISH_API_KEY``).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
MODELS_DIR = BACKEND_DIR / "models"


@dataclass(frozen=True)
class ModelAsset:
    """A downloadable model file pinned by URL (commit/version) and SHA-256."""

    filename: str
    url: str
    sha256: str
    license: str


FACE_LANDMARKER = ModelAsset(
    "face_landmarker.task",
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    "Apache-2.0 (Google MediaPipe)",
)
EMOTION_MODEL = ModelAsset(
    "enet_b0_8_va_mtl.onnx",
    "https://github.com/sb-ai-lab/EmotiEffLib/raw/af833487321c3efdcb1768a91a6c656a1986fdf6/"
    "models/affectnet_emotions/onnx/enet_b0_8_va_mtl.onnx",
    "c43e056ad388d4a8dc911832b8291435b2af537f967e5870ebd731574ec7e812",
    "EmotiEffLib code Apache-2.0; weights trained on AffectNet (research use)",
)
SILERO_VAD = ModelAsset(
    "silero_vad.onnx",
    "https://github.com/snakers4/silero-vad/raw/bfdc0193023f121ea5b3cc7b176dbed570a68a59/"
    "src/silero_vad/data/silero_vad.onnx",
    "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
    "MIT (Silero VAD)",
)
# kept for older imports
FACE_LANDMARKER_URL = FACE_LANDMARKER.url
FACE_LANDMARKER_SHA256 = FACE_LANDMARKER.sha256


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
    # extra browser origins / Host names (LAN use); never "*" (DNS rebinding)
    allowed_origins: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] = Field(default_factory=list)
    log_level: str = "info"
    cache_dir: Path = BACKEND_DIR / "cache"

    # ------------------------------------------------------------------ LLM (one provider: OpenAI)
    llm_provider: Literal["openai", "mock"] = "openai"
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "EH_OPENAI_API_KEY")
    )
    openai_base_url: str | None = None
    llm_model: str = "gpt-6-luna"
    llm_fallback_model: str | None = "gpt-5.5"  # only if the primary is rejected (404) before streaming
    llm_reasoning_effort: str = "none"  # "none" = no hidden reasoning → lowest latency
    llm_max_output_tokens: int = 600
    llm_first_token_timeout_s: float = 15.0
    llm_idle_timeout_s: float = 20.0
    llm_total_timeout_s: float = 60.0
    llm_history_turns: int = 10  # previous exchanges sent as context
    mock_llm_delay_s: float = 0.03  # per streamed word of the offline mock

    # ------------------------------------------------------------------ persona
    persona_name: str = "Rika"

    # ------------------------------------------------------------------ vision (face + emotions)
    vision_enabled: bool = True
    vision_model_path: Path = MODELS_DIR / FACE_LANDMARKER.filename
    emotion_model_path: Path = MODELS_DIR / EMOTION_MODEL.filename
    vision_auto_download: bool = True
    vision_max_faces: int = 3  # detect up to N so that ">1 face" is recognised
    vision_min_detection_confidence: float = 0.5
    vision_min_presence_confidence: float = 0.5
    vision_workers: int = 4
    vision_max_sessions: int = 4  # concurrent camera sessions (one landmarker each)
    frame_width: int = 480
    jpeg_quality: float = 0.8
    max_fps: float = 12.0
    max_frame_bytes: int = 512 * 1024

    # quality gates → "unknown"
    min_face_width: float = 0.11  # fraction of frame width
    max_abs_yaw_deg: float = 35.0
    max_abs_pitch_deg: float = 30.0
    min_brightness: float = 35.0  # mean luma of the face box, 0..255
    max_brightness: float = 240.0

    # ------------------------------------------------------------------ emotion engine
    # calm | balanced | expressive — smoothing, switch hold/margin, the "clearly there" floor and
    # how much facial evidence an expression needs (emotion/calibration.py SENSITIVITY)
    emotion_sensitivity: Literal["calm", "balanced", "expressive"] = "balanced"
    emotion_reference_fps: float = 10.0
    emotion_max_gap_s: float = 1.0  # longer gap without a face → unknown, smoothing restarts
    emotion_history_s: float = 60.0  # how far back the prompt's "recently" looks
    # per-person calibration: the relaxed face is learned first, expressions are read against it
    emotion_calibration_s: float = 2.5
    emotion_calibration_min_frames: int = 15
    emotion_adapt_tau_s: float = 60.0  # the baseline follows light/posture drift while relaxed
    emotion_recalibrate_after_s: float = 90.0  # no face this long → learn the face again

    # ------------------------------------------------------------------ voice out: Fish Audio TTS
    tts_enabled: bool = True
    fish_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("FISH_API_KEY", "EH_FISH_API_KEY")
    )
    tts_provider: Literal["fish", "mock"] = "fish"
    fish_model: str = "drama-3-preview"
    fish_reference_id: str = "c5d8a284092847df9e3c7308aeedc5f2"
    fish_ws_url: str | None = None  # None = by model (drama-* → /v1/tts/live/with-timestamp)
    fish_latency: str = "balanced"  # drama/s2: only "balanced" is fast (normal: 1.3-1.9 s)
    tts_sample_rate: int = 44100
    fish_chunk_length: int = 200
    fish_temperature: float = 0.7
    fish_top_p: float = 0.8
    fish_speed: float = 1.0
    fish_volume: float = 0.0
    fish_warm_connections: int = 1
    fish_connect_timeout_s: float = 6.0
    fish_silence_timeout_s: float = 8.0  # server silent after flush/stop → give up
    tts_max_leading_silence_ms: int = 120  # drama sometimes opens with seconds of silence
    tts_max_silence_ms: int = 700  # … and "plays" 1-5 s pauses mid-reply
    tts_first_chunk_chars: int = 36  # first TTS chunk may be cut at a comma after this many chars
    tts_chunk_chars: int = 140  # later chunks prefer full sentences up to this size

    # ------------------------------------------------------------------ voice in: speech-to-text
    stt_provider: Literal["openai", "mock", "off"] = "openai"
    stt_model: str = "gpt-live-transcribe"
    stt_language: str | None = None  # None = auto (English + Russian both work)
    stt_noise_reduction: Literal["near_field", "far_field", "off"] = "far_field"
    stt_prompt: str = (
        "A student talks to Rika, an AI tutor, about programming, maths and science: recursion, "
        "base case, algorithms, functions, loops, arrays, derivatives, integrals, probability, "
        "physics, chemistry."
    )
    stt_context_bias: bool = True  # add the tutor's last words to the prompt (domain terms)
    stt_final_timeout_s: float = 3.0
    stt_speculative: bool = True  # start the LLM on the live transcript at end-of-speech

    # voice activity detection (Silero VAD, local) → turn-taking and barge-in
    vad_model_path: Path = MODELS_DIR / SILERO_VAD.filename
    vad_threshold: float = 0.5
    vad_min_speech_ms: int = 220  # this much speech opens an utterance (coughs/clicks don't)
    vad_end_silence_ms: int = 550  # this much silence ends it (commas are shorter)
    vad_preroll_ms: int = 400  # audio before the detected onset that is still sent to STT
    vad_max_utterance_s: float = 30.0
    barge_in: bool = True
    barge_in_threshold: float = 0.6  # stricter while the tutor is talking (echo, noise)
    barge_in_min_ms: int = 350  # speech this long during playback interrupts the tutor
    # the learner paused mid-sentence and went on: if she has not started answering aloud
    # yet, the new words continue the same question instead of interrupting it
    voice_merge_window_s: float = 3.0
    fillers_enabled: bool = True
    filler_min_utterance_ms: int = 600  # no filler after a very short "yes"/"no"

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

    @property
    def tts_configured(self) -> bool:
        if not self.tts_enabled:
            return False
        if self.tts_provider == "mock":
            return True
        key = self.fish_api_key.get_secret_value().strip() if self.fish_api_key else ""
        return bool(key)

    @property
    def stt_configured(self) -> bool:
        if self.stt_provider == "off":
            return False
        return self.stt_provider == "mock" or self.llm_configured_openai

    @property
    def llm_configured_openai(self) -> bool:
        key = self.openai_api_key.get_secret_value().strip() if self.openai_api_key else ""
        return bool(key)

    def public_emotion_config(self) -> dict:
        from .emotion.calibration import SENSITIVITY

        pre = SENSITIVITY[self.emotion_sensitivity]
        return {
            "sensitivity": self.emotion_sensitivity,
            "alpha": pre["alpha"],
            "reference_fps": self.emotion_reference_fps,
            "switch_hold_s": pre["hold"],
            "switch_margin": pre["margin"],
            "min_prob": pre["min_prob"],
            "calibration_s": self.emotion_calibration_s,
        }

    def public_vision_config(self) -> dict:
        return {
            **self.public_emotion_config(),
            "max_fps": self.max_fps,
            "frame_width": self.frame_width,
            "jpeg_quality": self.jpeg_quality,
        }

    def public_voice_config(self) -> dict:
        return {
            "input_sample_rate": 24000,
            "output_sample_rate": self.tts_sample_rate,
            "barge_in": self.barge_in,
            "vad_end_silence_ms": self.vad_end_silence_ms,
            "merge_window_s": self.voice_merge_window_s,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
