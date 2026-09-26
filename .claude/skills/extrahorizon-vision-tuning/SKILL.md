---
name: extrahorizon-vision-tuning
description: Calibrate and tune ExtraHorizon's local confusion proxy (MediaPipe Face Landmarker blendshapes → baseline-corrected noisy-OR → EMA state engine) against a real webcam — threshold, hold time, cooldown, feature weights/scales, quality gates. Use this whenever the event fires too easily or never, the signal is noisy, a face is not detected, "calibrating" never finishes, someone asks how the proxy works or wants to change it, or the user says "подстрой камеру", "не срабатывает", "слишком чувствительно" — even if they don't mention MediaPipe.
---

# Tuning the confusion proxy

Pipeline (all local, `backend/extrahorizon/vision/`): browser frame (480 px JPEG) →
`FaceAnalyzer` (MediaPipe Face Landmarker, 52 blendshapes + head pose) → `assess_quality`
(unknown if no face / >1 face / small / turned / too dark / too bright) → `ConfusionProxy`
(per-session neutral baseline, then a noisy-OR of brow lowering, lid tightening and lip press,
suppressed by smiling) → `StateEngine` (time-based EMA, threshold + hold, cooldown).
Full rationale and limitations: `docs/CONFUSION_PROXY.md`.

## 1. Measure first — with consent

`backend/scripts/vision_probe.py` runs the exact production pipeline on a local webcam and
prints the numbers (≈4 lines/s) and events; `--csv` saves numbers only, `--preview` shows a window.
**It turns on the user's physical camera: ask before running it**, or give the user the
command to run themselves:

```powershell
cd backend
uv run python scripts/vision_probe.py --seconds 90 --csv probe.csv
```

Protocol (≈90 s): 5 s neutral (calibration) → 10 s reading neutrally → 3 × (frown 3 s, relax 5 s)
→ 5 s smile → look away → second person briefly in frame → too far from camera.

## 2. What good looks like

- Neutral reading: smoothed ≤ ~0.25, never above threshold.
- Deliberate frown: raw ≥ 0.8 within ~0.5 s, smoothed crosses 0.65 in < 1 s, one event after ~2 s.
- Smile: proxy stays low (smile factor → 0).
- Look away / two faces / far away: status `unknown` with the right reason, hold resets.

## 3. Knobs (repo-root `.env`, restart the backend)

| Symptom | Adjust |
|---|---|
| Frown doesn't reach threshold | lower `EH_PROXY_SCALE_BROW` (0.30 → 0.22) or raise `EH_PROXY_W_BROW` (≤ 0.95) |
| Neutral face drifts high | recalibrate with a truly neutral face; raise `EH_PROXY_SCALE_*`; check light (squint from glare) |
| Fires during concentration | raise `EH_THRESHOLD` (0.65 → 0.72) or `EH_HOLD_S` (2 → 2.5) |
| Flickers unknown | lower `EH_MIN_FACE_WIDTH`, widen `EH_MAX_ABS_YAW_DEG/PITCH`, better light (`EH_MIN_BRIGHTNESS`) |
| Too sluggish | raise `EH_EMA_ALPHA` (0.2 → 0.3) |
| Repeats too soon | raise `EH_COOLDOWN_S` |

After changing defaults in `config.py` (not just `.env`), run `uv run pytest` — engine and vision
tests encode the invariants.

## Invariants — never tune these away

- Unknown is **unknown**: no face / several faces / poor quality → `smoothed = None`, hold reset. Never map it to 0 ("neutral") or to confused.
- Durations are wall-clock seconds, not frame counts.
- One event per episode; cooldown respected.
- The LLM never receives numbers, images, landmarks or blendshapes — only the abstract note from `context.py`.
- Simulation is labelled everywhere and never presented as recognition.
- Describe it as a *proxy / estimate*; update docs/CONFUSION_PROXY.md when the method changes.
