# Facial expression → emotion estimate → what Rika "sees"

ExtraHorizon estimates how the learner's face **looks** (not what they feel) and lets the tutor
adapt her tone and pacing to it, like a person on a video call. Everything below runs on the local
CPU; frames are analysed in memory and discarded.

## Why calibration

Expression classifiers are biased per person, camera and light. Measured on a real user with a
relaxed face (headphones, laptop webcam below eye level): the raw model said **anger 0.90–0.97**;
lowering the head a little pushed it further. Fixed thresholds cannot solve that — ExtraHorizon
first learns *this* learner's relaxed face and reads every expression relative to it.

## Pipeline (per frame, ≤ 12 fps, one frame in flight)

1. **Browser**: the camera frame is downsized to 480 px, JPEG-encoded and sent over the localhost
   WebSocket `/api/vision` (the next frame only after the previous one was answered → no backlog).
2. **MediaPipe Face Landmarker** (VIDEO mode, up to 3 faces): face count, 478 landmarks, 52 blendshapes
   (facial actions such as brow down, eye squint, smile, jaw open) and the head pose.
3. **Quality gates** (`vision/quality.py`) → *unknown* with a reason, never "neutral": no face · several
   faces (we never read one of several people) · face too small · head turned (|yaw| > 35°, |pitch| > 30°) ·
   too dark / overexposed · undecodable frame.
4. **Expression model** — EmotiEffLib `enet_b0_8_va_mtl` (ONNX): the face is rotated upright (eyes level),
   cropped the way the model was trained (brows-to-chin detector-style box), classified together with its mirror
   image (the logits are averaged) → **8 classes** + **valence/arousal**, ≈10 ms.
5. **Per-person calibration** (`emotion/calibration.py`):
   * **baseline** — the first ~2.5 s of a relaxed face (medians of logits, valence/arousal, blendshapes, head pose);
     frames while the learner talks (voice detection) or with the head turned are skipped; a passing smile is
     absorbed by the median. The UI shows *Calibrating… look at the screen with a relaxed face*;
     **Recalibrate** repeats it; after 90 s without a face it happens again automatically;
   * **bias correction** — logits are shifted so the baseline face maps to a typical neutral distribution
     (neutral ≈ 0.7): a prior correction in logit space. A real expression still moves the logits away from the
     baseline and shows up; valence/arousal are corrected the same way;
   * **facial-action evidence** — each non-neutral class must be backed by the matching baseline-relative change
     of the blendshapes (FACS-style action units): anger = brows down + lids tight + lips pressed; happiness =
     smile + cheek raise; surprise = brows up + eyes wide; sadness = mouth corners down + inner brows up; fear =
     inner brows up + eyes wide + mouth stretched; disgust = nose wrinkled + upper lip raised; contempt = a
     one-sided smile. Without evidence the class is damped toward neutral — small brow shifts no longer read as anger;
   * **pose weighting** — full weight within ±6° pitch / ±8° yaw of the calibration pose, down to 0.1 at ~24° / 30°:
     a lowered head barely moves the estimate and needs more facial evidence; while the learner talks frames count half;
   * **slow adaptation** — while the face is clearly relaxed, the baseline follows light and posture drift (τ ≈ 60 s);
     it never absorbs a visible expression.
6. **Emotion engine** (`emotion/engine.py`, per session): time-based smoothing weighted per frame; an expression is
   reported only once it is clearly there (≥ the sensitivity floor) and has led for the hold time by the margin;
   otherwise the face is described as neutral.

### Sensitivity (UI: Calm · Balanced · Expressive, env `EH_EMOTION_SENSITIVITY`)

| | smoothing α @10 fps | switch hold | margin | "clearly there" floor | evidence needed |
|---|---|---|---|---|---|
| Calm | 0.15 | 1.6 s | 0.15 | 0.50 | ×1.35 |
| **Balanced** (default) | 0.20 | 1.2 s | 0.12 | 0.42 | ×1.0 |
| Expressive | 0.30 | 0.8 s | 0.08 | 0.32 | ×0.75 |

### Checked on the user's own frames (offline, two screenshots they shared)

| Frame | Raw model | After calibration on the relaxed frame |
|---|---|---|
| relaxed face, head slightly down | anger 0.90 | **neutral 0.90** |
| slight frown, head level (10° pitch away from the calibration) | anger 0.97 | **neutral 0.77** — "frowning, brows pulled down" noted, weight 0.64 |
| a real smile (MediaPipe test portrait) | happiness 1.00 | **happiness 1.00** (a real expression still shows) |

## What the tutor receives

Only when exactly one face is clearly in view (and after calibration), one system message right before the question,
phrased as her own view of the learner on the call:

```
[What you see on the learner's webcam right now] The learner looks mostly annoyed. Visible right now: frowning, brows pulled down. Overall mood: negative, moderate energy. Before that (a few seconds ago) they looked relaxed.
```

* Words only — no numbers, no images, no landmarks. If the expression has not changed since the learner last spoke,
  the note says so ("only mention it if it matters"), so she does not comment on the same face every turn.
* The persona treats it as her eyes on a video call: asked "can you see me?" she says yes; she mentions what she sees
  only now and then, briefly and in character ("Why the frown? Did I lose you?"), and never talks about estimates,
  readings, cameras or guesses. With no clear face there is no message and she does not pretend to see.
* During the labelled Demo simulation the bracket says *labelled demo simulation set by hand*, and simulated history
  never feeds a camera description.
* The UI stays explicit: the panel labels everything as an *estimate*, shows the exact message per answer
  ("expression sent" chip) and previews it live in **What Rika is told**.

## Visualisation (right panel)

* **Camera** — mirrored preview, face box coloured by the dominant expression (dashed violet while calibrating), a label
  on the face, **Recalibrate**.
* **Expression now** — the dominant expression, its strength and duration, the mood in words, all eight calibrated
  probabilities as labelled bars, the calibration progress, the sensitivity switch.
* **Mood map** — valence × energy with the current point and a 20 s trail.
* **Expression timeline** — stacked area of the eight shares over 60 s; unknown and calibration periods are gaps (rug
  below, never zeros); simulated spans marked; answer markers and expression-change ticks; hover crosshair; table view.
* Colours: the documented dark categorical palette of the dataviz reference, one colour per expression everywhere,
  stack order validated for colour-vision deficiency (worst adjacent CVD ΔE 9.4, normal-vision ΔE 19.3).

## Demo simulation (labelled)

The **Demo simulation mode** card replaces the camera with a chosen expression and intensity (10 Hz) that drives the
**same** engine and note; every sample is tagged `simulation` and the UI shows **SIMULATED** / **NOT LIVE**.

## Limitations (say them)

* Expression recognition is imperfect and biased (lighting, pose, glasses, age, skin tone, culture); calibration removes
  the *resting-face* bias of one person, not every error. Posed expressions are recognised better than spontaneous ones.
* Calibration assumes the face is relaxed during the first seconds; if not, press **Recalibrate**.
* An expression is not an emotion (Barrett et al., 2019): she describes how the learner *looks*, never claims to know
  how they feel, and accepts being corrected.
* The model's weights were trained on AffectNet (non-commercial research license) — fine for this non-commercial
  hackathon demo; a product would need a model with a suitable license.
* One face only; several faces → unknown by design.

## Tuning

`backend/scripts/vision_probe.py --seconds 30 --csv probe.csv` prints the gate, the raw top class, the calibrated
dominant expression, valence/arousal and the pose weight from **your** webcam (ask before running it for someone
else). Knobs: `EH_EMOTION_SENSITIVITY`, `EH_EMOTION_CALIBRATION_S`, `EH_EMOTION_ADAPT_TAU_S`,
`EH_EMOTION_RECALIBRATE_AFTER_S`, the gates `EH_MIN_FACE_WIDTH`, `EH_MAX_ABS_YAW_DEG`, `EH_MAX_ABS_PITCH_DEG`,
`EH_MIN_BRIGHTNESS`; per-class evidence thresholds live in `emotion/calibration.py`.
