---
name: extrahorizon-vision-tuning
description: Check and tune ExtraHorizon's local facial-expression pipeline (MediaPipe face landmarker → quality gates → upright square crop + mirror → EmotiEffLib 8-emotion + valence/arousal ONNX model → per-person calibration (relaxed-face baseline, neutral-vs-expression relative to it, which expression from the face as it reads now, hallmark facial actions, pose/talk) → per-session emotion engine with sensitivity presets → words-only note of what Rika "sees"). Use this whenever the expression flickers, stays Unknown or Calibrating, reads Angry / Unimpressed / Sad on a relaxed face, shows Neutral or the wrong class (e.g. Disgusted) for a clear expression, jumps when the head moves or the brows twitch, the note says something odd, a face is not detected, someone asks how the emotion estimate or calibration works or wants to change it, or the user says "подстрой камеру", "эмоции не те", "показывает злость", "калибровка", "слишком дёргается" — even if they don't mention MediaPipe.
---

# Tuning the expression estimate

Pipeline (all local, per frame): browser frame (480 px JPEG) → `vision/analyzer.py` (MediaPipe: face count,
478 landmarks, 52 blendshapes, head pose) → `vision/quality.py` (unknown if no face / >1 face / small / turned /
too dark / too bright / no estimate) → `emotion/classifier.py` (face rotated upright, square crop over the face mesh + 10 %, the crop
and its mirror in one batch, logits averaged → 8 classes + valence/arousal) → `emotion/calibration.py`
(`Calibrator`: baseline of the learner's relaxed face; P(neutral) from how far the classes the face shows now
have gained on neutral since then; which expression from the face as it reads now; hallmark facial actions;
pose/talking bonus + weight; slow adaptation) → `emotion/engine.py` (weighted time-based EMA, `min_prob` floor,
hold + margin, faded → neutral, `describe()` → words + visible actions) → `context.emotion_note()`.
Method, measured results and limitations: `docs/EMOTIONS.md`.

Why calibration exists: on a real user's relaxed face the raw model said **anger 0.90–0.97**. Never "fix" such a
report by lowering a global threshold — find which stage is wrong (baseline? intensity? which-class? pose? engine?) and
measure. And never "fix" it by moving probability into neutral: the first calibration did that (it shifted every
class and demanded brow blendshapes) and erased the same learner's real anger — a snarl read Neutral / Disgusted.
MediaPipe's brow blendshapes are unreliable on some faces (brow-down 0.4 at rest, ~0 in a snarl).

## 1. Measure first — with consent

`backend/scripts/vision_probe.py` runs the production pipeline (with calibration) on a local webcam and prints,
twice a second: the gate, the raw top class, the calibration progress, the calibrated dominant expression,
valence/arousal, the pose weight and the visible facial actions; `--csv` saves the raw numbers.
**It turns on the user's physical camera: ask before running it**, or give the user the command:

```powershell
cd backend
uv run python scripts/vision_probe.py --seconds 60 --csv probe.csv
```

Protocol (≈60 s): first 3 s relaxed, looking at the screen, silent (calibration) → 10 s relaxed with small
movements (brows, blinking, head a little lower/higher) → 5 s big smile → 5 s relaxed → 5 s surprised (brows up,
mouth open) → 5 s clear frown → look away → second person briefly in frame → too far away.

Without a webcam: a still image the user shares can be analysed **locally** (MediaPipe + the classifier +
`Calibrator` fed the same relaxed frame ~30 times, then the test frame); keep such images and crops in the
scratchpad, never in the repository. The UI's labelled **Demo simulation mode** drives the engine, not the model.

## 2. What good looks like

- Relaxed face → *Neutral* after calibration, including small brow movements and a slightly lowered head
  (the probe shows the actions, e.g. "frowning", with a weight < 1, but the dominant stays Neutral).
- A clear smile → *Happy* within ~1 s; a clear frown held ~1–2 s → *Annoyed*/*Angry*; no flicker between two classes.
- Look away / two faces / far away → *Unknown* with the right reason; the note disappears from the prompt.
- *Calibrating…* ends within ~3 s with a still, relaxed face (talking and a turned head are skipped; after 8 s
  frames are accepted anyway).

## 3. Knobs

| Symptom | Adjust |
|---|---|
| Relaxed face reads an expression | **Recalibrate** with a relaxed face first; then sensitivity **Calm** (UI) / `EH_EMOTION_SENSITIVITY=calm` |
| Real expressions are missed | **Expressive** / `EH_EMOTION_SENSITIVITY=expressive`; check the probe's actions for that expression |
| Dominant flickers / too sluggish | the presets set α, hold, margin and the floor together (`SENSITIVITY` in `emotion/calibration.py`) |
| A clear expression stays Neutral | the probe's "neutral log-odds" should fall well below 0; check the raw top class and the gain gate (`GAIN_MID`) |
| The right amount, the wrong class | the classifier's confusion (e.g. anger ↔ disgust): the class's `HALLMARK` range / formula in `hallmarks()` (`emotion/calibration.py`) — it only moves probability between expressions |
| Head movement still moves the estimate | `pose_weight()` ranges (full weight within ±6° pitch / ±8° yaw) |
| Calibration takes too long / too short | `EH_EMOTION_CALIBRATION_S` (2.5), `EH_EMOTION_CALIBRATION_MIN_FRAMES` (15) |
| Light/posture drift over minutes | `EH_EMOTION_ADAPT_TAU_S` (60; only while the classifier reads the relaxed face, bounded by `ADAPT_MAX_*` in `emotion/calibration.py`) |
| Someone else sits down | automatic after `EH_EMOTION_RECALIBRATE_AFTER_S` (90) without a face, or **Recalibrate** |
| Flickers unknown | lower `EH_MIN_FACE_WIDTH`, widen `EH_MAX_ABS_YAW_DEG` / `EH_MAX_ABS_PITCH_DEG`, better light (`EH_MIN_BRIGHTNESS`) |
| Short dropouts restart smoothing | raise `EH_EMOTION_MAX_GAP_S` (1.0 → 1.5) |

`.env` changes need a backend restart. After changing code or defaults run `uv run pytest` — `test_calibration.py`,
`test_emotion.py` and `test_vision.py` encode the invariants; then the e2e demo spec (virtual camera, real models).

## Invariants — never tune these away

- Unknown is **unknown**: no face / several faces / poor quality → no distribution, no dominant, no note. Never "neutral".
- Nothing is reported before the learner's baseline exists (status `calibrating`, a gap in the timeline).
- A non-neutral expression needs matching baseline-relative facial actions; adaptation never absorbs a visible expression.
- Durations are wall-clock seconds, not frame counts.
- The LLM receives words only (no digits, images, landmarks, probabilities), phrased as what she sees on the call;
  the UI labels every reading as an *estimate*.
- Simulation is labelled everywhere, skips calibration and never presented as recognition.
- Update `docs/EMOTIONS.md` (and EXTERNAL_DEPENDENCIES.md if the model or its use changes) when the method changes.
