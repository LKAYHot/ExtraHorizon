"""Download + verify the MediaPipe Face Landmarker model (official Google asset).

    uv run python -m extrahorizon.vision.model_fetch
"""

from __future__ import annotations

import hashlib
import logging
import sys
import urllib.request
from pathlib import Path

from ..config import FACE_LANDMARKER_SHA256, FACE_LANDMARKER_URL, get_settings

log = logging.getLogger("extrahorizon.vision")


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
    url: str = FACE_LANDMARKER_URL,
    sha256: str = FACE_LANDMARKER_SHA256,
    timeout_s: float = 30.0,
) -> tuple[bool, str | None]:
    """Return ``(ok, reason)``. Never raises."""
    try:
        if path.exists():
            if sha256_of(path) == sha256:
                return True, None
            log.warning("vision model at %s has an unexpected checksum — re-downloading", path)
        if not allow_download:
            return False, "model_missing"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".download")
        log.info("downloading MediaPipe face landmarker model from %s", url)
        with urllib.request.urlopen(url, timeout=timeout_s) as r, tmp.open("wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
        if sha256_of(tmp) != sha256:
            tmp.unlink(missing_ok=True)
            return False, "model_checksum_mismatch"
        tmp.replace(path)
        return True, None
    except Exception as e:  # noqa: BLE001 — offline venue Wi-Fi must not crash the app
        log.warning("vision model unavailable: %s", e)
        return False, "model_download_failed"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = get_settings()
    ok, reason = ensure_model(s.vision_model_path)
    print(f"{s.vision_model_path}: {'OK' if ok else 'FAILED — ' + str(reason)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
