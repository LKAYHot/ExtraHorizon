"""Download + verify the local models (pinned URL + SHA-256, never "latest").

    uv run python -m extrahorizon.vision.model_fetch      # all three models
"""

from __future__ import annotations

import hashlib
import logging
import sys
import urllib.request
from pathlib import Path

from ..config import EMOTION_MODEL, FACE_LANDMARKER, SILERO_VAD, ModelAsset, get_settings

log = logging.getLogger("extrahorizon.models")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_model(
    path: Path,
    *,
    allow_download: bool = True,
    url: str = FACE_LANDMARKER.url,
    sha256: str = FACE_LANDMARKER.sha256,
    timeout_s: float = 60.0,
) -> tuple[bool, str | None]:
    """Return ``(ok, reason)``. Never raises."""
    try:
        if path.exists():
            if sha256_of(path) == sha256:
                return True, None
            log.warning("model at %s has an unexpected checksum — re-downloading", path)
        if not allow_download:
            return False, "model_missing"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".download")
        log.info("downloading %s from %s", path.name, url)
        with urllib.request.urlopen(url, timeout=timeout_s) as r, tmp.open("wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
        if sha256_of(tmp) != sha256:
            tmp.unlink(missing_ok=True)
            return False, "model_checksum_mismatch"
        tmp.replace(path)
        return True, None
    except Exception as e:  # noqa: BLE001 — offline venue Wi-Fi must not crash the app
        log.warning("model %s unavailable: %s", path.name, e)
        return False, "model_download_failed"


def ensure_asset(asset: ModelAsset, path: Path, *, allow_download: bool = True) -> tuple[bool, str | None]:
    return ensure_model(path, allow_download=allow_download, url=asset.url, sha256=asset.sha256)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = get_settings()
    ok_all = True
    for asset, path in (
        (FACE_LANDMARKER, s.vision_model_path),
        (EMOTION_MODEL, s.emotion_model_path),
        (SILERO_VAD, s.vad_model_path),
    ):
        ok, reason = ensure_asset(asset, path)
        ok_all &= ok
        print(f"{path.name}: {'OK' if ok else 'FAILED — ' + str(reason)}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
