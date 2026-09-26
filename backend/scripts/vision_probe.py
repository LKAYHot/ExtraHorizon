"""Live tuning helper for the confusion proxy — uses YOUR webcam, 100 % locally.

Runs the exact production pipeline (FaceAnalyzer → quality gates → ConfusionProxy →
StateEngine, including the browser's downsizing + JPEG round trip) on frames from a
local camera and prints ~4 lines per second, so you can see how a neutral face, a
deliberate frown, a smile, looking away or a second person move the numbers.
Nothing is stored — except the optional CSV of numbers you ask for. Note: like the app,
this uses Google's MediaPipe wheel, which sends Google anonymous usage metrics (no images,
per Google) while a face-landmarker session runs.

    cd backend
    uv run python scripts/vision_probe.py                    # camera 0, 60 s
    uv run python scripts/vision_probe.py --camera 1 --seconds 120 --csv probe.csv
    uv run python scripts/vision_probe.py --preview          # OpenCV window: q = quit, c = recalibrate

Tune with EH_* variables in the repo .env (see docs/CONFUSION_PROXY.md), then rerun.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time

import cv2

from extrahorizon.config import get_settings
from extrahorizon.engine import CALIBRATING, OK, EngineConfig, Observation, StateEngine
from extrahorizon.vision.analyzer import FaceAnalyzer
from extrahorizon.vision.model_fetch import ensure_model
from extrahorizon.vision.proxy import ConfusionProxy, ProxyParams, assess_quality, extract_features


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]  # cp1251 consoles
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--csv", help="write every analysed frame to this CSV file")
    ap.add_argument("--preview", action="store_true", help="show an OpenCV window with the face box and numbers")
    args = ap.parse_args()

    s = get_settings()
    ok, reason = ensure_model(s.vision_model_path, allow_download=s.vision_auto_download)
    if not ok:
        print(f"MediaPipe model unavailable: {reason}")
        return 1
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(args.camera, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        print(f"Camera {args.camera} could not be opened (busy in another app? wrong index?)")
        return 1

    analyzer = FaceAnalyzer(s.vision_model_path, s.vision_max_faces, s.vision_min_detection_confidence, s.vision_min_presence_confidence)
    proxy = ConfusionProxy(ProxyParams.from_settings(s))
    engine = StateEngine(EngineConfig.from_settings(s))
    writer = None
    if args.csv:
        f = open(args.csv, "w", newline="", encoding="utf-8")  # noqa: SIM115
        writer = csv.writer(f)
        writer.writerow(["t", "faces", "status", "reason", "brow_lower", "lid_tighten", "lip_press", "smile",
                         "proxy_raw", "smoothed", "held_s", "event", "yaw", "pitch", "brightness", "proc_ms"])

    print(f"threshold {s.threshold} · hold {s.hold_s}s · alpha {s.ema_alpha} · calibrating {s.calibration_s}s — keep a neutral face first")
    print("   t   status        brow  lid  press smile |  raw  smooth held")
    t0 = time.monotonic()
    last_print = 0.0
    period = 1.0 / s.max_fps
    try:
        while time.monotonic() - t0 < args.seconds:
            tick = time.monotonic()
            ok_frame, frame = cap.read()
            if not ok_frame:
                print("camera returned no frame")
                break
            h = int(frame.shape[0] * s.frame_width / frame.shape[1])
            small = cv2.resize(frame, (s.frame_width, h), interpolation=cv2.INTER_AREA)
            jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, int(s.jpeg_quality * 100)])[1].tobytes()
            r = analyzer.analyze_jpeg(jpeg)
            t = time.monotonic() - t0
            status, why = assess_quality(r, s)
            feats, value = None, None
            if status == OK and r.blendshapes is not None:
                feats = extract_features(r.blendshapes)
                reading = proxy.update(t, feats)
                if reading.status == CALIBRATING:
                    status, why = CALIBRATING, f"calibrating {reading.progress:.0%}"
                else:
                    value = reading.value
            else:
                proxy.note_absence(t)
            state, events = engine.update(Observation(t, value, status if status != CALIBRATING else "calibrating", why))
            fired = ",".join(e.kind for e in events)
            if writer:
                writer.writerow([f"{t:.3f}", r.faces, state.status, why or "",
                                 *(f"{feats[k]:.3f}" if feats else "" for k in ("brow_lower", "lid_tighten", "lip_press", "smile")),
                                 "" if value is None else f"{value:.3f}", "" if state.smoothed is None else f"{state.smoothed:.3f}",
                                 f"{state.held_s:.2f}", fired, *(f"{x:.1f}" for x in (r.pose or (0, 0, 0))[:2]),
                                 "" if r.brightness is None else f"{r.brightness:.0f}", f"{r.proc_ms:.1f}"])
            if t - last_print >= 0.25 or events:
                last_print = t
                f4 = " ".join(f"{feats[k]:.2f}" for k in ("brow_lower", "lid_tighten", "lip_press", "smile")) if feats else " —    —    —    — "
                raw = "  —  " if value is None else f"{value:.2f}"
                sm = "  —  " if state.smoothed is None else f"{state.smoothed:.2f}"
                label = (why or state.status)[:13]
                print(f"{t:5.1f}  {label:<13} {f4} | {raw}  {sm}  {state.held_s:.1f}s {'<< ' + fired if fired else ''}")
            if args.preview:
                view = frame.copy()
                for x, y, w, hh in r.boxes:
                    H, W = view.shape[:2]
                    cv2.rectangle(view, (int(x * W), int(y * H)), (int((x + w) * W), int((y + hh) * H)), (255, 170, 120), 2)
                txt = f"{state.status} {why or ''} smooth={state.smoothed if state.smoothed is None else round(state.smoothed, 2)}"
                cv2.putText(view, txt, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 255), 2)
                cv2.imshow("ExtraHorizon vision probe (q = quit, c = recalibrate)", cv2.flip(view, 1))
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("c"):
                    proxy.reset()
            time.sleep(max(0.0, period - (time.monotonic() - tick)))
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        analyzer.close()
        if args.preview:
            cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
