"""Live check of the expression pipeline on YOUR webcam — 100 % locally (ask before running
it for someone else: it turns the camera on).

Prints, ~2× per second: faces, the quality gate, the raw top expression of the on-device
model, the calibration progress, the calibrated + smoothed dominant expression, the pose
weight, visible facial actions, valence/arousal and the processing time; optionally writes
every frame to CSV for tuning (EH_EMOTION_*, EH_MIN_FACE_WIDTH, EH_MAX_ABS_YAW_DEG, …).
Keep a relaxed face for the first ~3 seconds (calibration).

    cd backend
    uv run python scripts/vision_probe.py --seconds 30 --csv probe.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time

import cv2

from extrahorizon.config import EMOTION_MODEL, FACE_LANDMARKER, get_settings
from extrahorizon.emotion.calibration import Calibrator
from extrahorizon.emotion.classifier import EmotionClassifier
from extrahorizon.emotion.engine import OK, UNKNOWN, EmotionConfig, EmotionEngine, EmotionObservation
from extrahorizon.vision.analyzer import FaceAnalyzer
from extrahorizon.vision.model_fetch import ensure_asset
from extrahorizon.vision.quality import assess_quality
from extrahorizon.vision.types import EMOTIONS


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--csv", help="write every analysed frame here")
    a = ap.parse_args()
    s = get_settings()
    for asset, path in ((FACE_LANDMARKER, s.vision_model_path), (EMOTION_MODEL, s.emotion_model_path)):
        ok, reason = ensure_asset(asset, path)
        if not ok:
            print(f"{path.name}: {reason}", file=sys.stderr)
            return 1
    analyzer = FaceAnalyzer(s.vision_model_path, max_faces=s.vision_max_faces, emotion=EmotionClassifier(s.emotion_model_path))
    engine = EmotionEngine(EmotionConfig.from_settings(s))
    calib = Calibrator(s.emotion_calibration_s, s.emotion_calibration_min_frames, s.emotion_adapt_tau_s, s.emotion_sensitivity)
    cap = cv2.VideoCapture(a.camera)
    if not cap.isOpened():
        print("camera not available", file=sys.stderr)
        return 1
    writer = None
    if a.csv:
        f = open(a.csv, "w", newline="", encoding="utf-8")  # noqa: SIM115
        writer = csv.writer(f)
        writer.writerow(["t", "faces", "quality", "reason", *EMOTIONS, "valence", "arousal", "yaw", "pitch",
                         *[f"cal_{k}" for k in EMOTIONS], "cal_margin", "weight", "dominant", "proc_ms"])
    t0 = time.monotonic()
    last_print = 0.0
    try:
        while time.monotonic() - t0 < a.seconds:
            ok, frame = cap.read()
            if not ok:
                continue
            w = s.frame_width
            frame = cv2.resize(frame, (w, int(frame.shape[0] * w / frame.shape[1])))
            t = time.monotonic()
            r = analyzer.analyze_bgr(frame)
            status, reason = assess_quality(r, s)
            em = r.emotion
            good = status == OK and em is not None
            corr = calib.observe(t, em, r.blendshapes, r.pose) if good else None
            if good and corr is None:
                obs = EmotionObservation(t, None, status="calibrating", reason="calibrating")
            elif good:
                obs = EmotionObservation(t, corr.probs, corr.valence, corr.arousal, OK, None, weight=corr.weight,
                                         actions=corr.actions)
            else:
                obs = EmotionObservation(t, None, None, None, UNKNOWN, reason)
            state, _ = engine.update(obs)
            if writer:
                probs = em.probs if em else [None] * len(EMOTIONS)
                cal = [round(x, 4) for x in corr.probs] if corr else [None] * len(EMOTIONS)
                writer.writerow([round(t - t0, 3), r.faces, status, reason, *probs,
                                 em.valence if em else None, em.arousal if em else None,
                                 *(r.pose[:2] if r.pose else (None, None)), *cal,
                                 round(corr.margin, 3) if corr else None, round(corr.weight, 2) if corr else None,
                                 state.dominant, round(r.proc_ms, 1)])
            if t - last_print > 0.5:
                last_print = t
                top = max(zip(EMOTIONS, em.probs), key=lambda kv: kv[1]) if em else ("-", 0.0)
                va = f"v {state.valence:+.2f} a {state.arousal:+.2f}" if state.valence is not None else ""
                cal = "calibrating %d%%" % round(calib.progress * 100) if not calib.ready else "calibrated"
                extra = f"neutral log-odds {corr.margin:+.1f} w {corr.weight:.2f} {list(corr.actions)}" if corr else ""
                print(f"{t - t0:5.1f}s faces={r.faces} {status:7s} {reason or '':16s} raw={top[0]}:{top[1]:.2f} {cal:15s} "
                      f"dominant={state.dominant or 'unknown':10s} {va} {extra} {r.proc_ms:.0f} ms")
    finally:
        cap.release()
        analyzer.close()
        if writer:
            f.close()
    print("\nThe description the tutor would get now:", engine.describe(time.monotonic())["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
