"""Build a .y4m "virtual camera" clip for browser tests (Chromium's
--use-file-for-fake-video-capture). It lets the automated e2e test drive the REAL
camera path (browser capture → JPEG → WebSocket → MediaPipe → engine) without
pointing a real webcam at anyone.

Source image: the official MediaPipe test portrait (downloaded once, git-ignored).

    uv run python scripts/make_fake_camera.py --faces 1 --out ../frontend/e2e/.cache/face.y4m
    uv run python scripts/make_fake_camera.py --faces 2 --out ../frontend/e2e/.cache/two_faces.y4m
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

PORTRAIT_URL = "https://storage.googleapis.com/mediapipe-assets/portrait.jpg"
CACHE = Path(__file__).resolve().parents[1] / "tests" / ".cache" / "portrait.jpg"
W, H = 640, 480


def portrait() -> np.ndarray:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(PORTRAIT_URL, timeout=30) as r:
            CACHE.write_bytes(r.read())
    img = cv2.imread(str(CACHE))
    if img is None:
        raise SystemExit("could not read the portrait image")
    return img


def frame(faces: int) -> np.ndarray:
    canvas = np.full((H, W, 3), (38, 30, 24), np.uint8)
    if faces == 0:
        return canvas
    src = portrait()
    tiles = [src] if faces == 1 else [src, cv2.flip(src, 1)]
    tw = W // len(tiles)
    for i, t in enumerate(tiles):
        scale = min(tw / t.shape[1], H / t.shape[0])
        r = cv2.resize(t, (int(t.shape[1] * scale) // 2 * 2, int(t.shape[0] * scale) // 2 * 2), interpolation=cv2.INTER_AREA)
        x0 = i * tw + (tw - r.shape[1]) // 2
        y0 = (H - r.shape[0]) // 2
        canvas[y0 : y0 + r.shape[0], x0 : x0 + r.shape[1]] = r
    return canvas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faces", type=int, default=1, choices=(0, 1, 2))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--fps", type=int, default=15)
    args = ap.parse_args()
    img = frame(args.faces)
    yuv = cv2.cvtColor(img, cv2.COLOR_BGR2YUV_I420).tobytes()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("wb") as f:
        f.write(f"YUV4MPEG2 W{W} H{H} F{args.fps}:1 Ip A1:1 C420jpeg\n".encode())
        for _ in range(int(args.seconds * args.fps)):
            f.write(b"FRAME\n")
            f.write(yuv)
    print(f"wrote {args.out} ({args.faces} face(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
