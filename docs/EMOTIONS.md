# Facial expression → emotion estimate → what Rika "sees"

ExtraHorizon estimates how the learner's face **looks** (not what they feel) and lets the tutor
adapt her tone and pacing to it, like a person on a video call. Everything below runs on the local
CPU; frames are analysed in memory and discarded.

## Why calibration — and why it must not "correct" everything

Expression classifiers are biased per person, camera and light. Measured on a real learner
(laptop webcam below eye level, heavy brows, a headset), with two screenshots of each situation:

* **all five** EmotiEffLib models (four crop variants each) read the *relaxed* face as **anger 0.69–0.97**;
* the same person's real angry faces (a snarl; lips pressed together) read anger 0.98 / 0.76 as well —
  what changed was that **neutral dropped** (neutral log-odds −4.5 at rest → −7…−9);
* MediaPipe's brow blendshapes were unusable for this face: *brow down* was 0.34–0.48 at rest and ≈0 in a snarl.

The first calibration (shift every class toward a reference + demand matching blendshapes) fixed the
relaxed face but erased that person's anger: a snarl read *Neutral 49 % / Disgusted 30 %*, pressed lips
*Neutral 70 % / Disgusted 29 %*. The current method keeps the classifier's judgement of **what** the face
looks like and re-centres only **whether** it shows an expression, relative to the person's relaxed face.

## Pipeline (per frame, ≤ 12 fps, one frame in flight)

1. **Browser**: the camera frame is downsized to 480 px, JPEG-encoded and sent over the localhost
   WebSocket `/api/vision` (the next frame only after the previous one was answered → no backlog).
2. **MediaPipe Face Landmarker** (VIDEO mode, up to 3 faces): face count, 478 landmarks, 52 blendshapes
   (facial actions such as brow down, smile, jaw open) and the head pose.
3. **Quality gates** (`vision/quality.py`) → *unknown* with a reason, never "neutral": no face · several
   faces (we never read one of several people) · face too small · head turned (|yaw| > 35°, |pitch| > 30°) ·
   too dark / overexposed · undecodable frame.
4. **Expression model** — EmotiEffLib `enet_b0_8_va_mtl` (ONNX): the face is rotated upright (eyes level) and
   cropped as a square over the whole face mesh + 10 % (the framing of AffectNet face crops, no aspect
   distortion), classified together with its mirror image (logits averaged) → **8 classes** + **valence/arousal**, ≈10 ms.
5. **Per-person calibration** (`emotion/calibration.py`):
   * **baseline** — the first ~2.5 s of a relaxed face (medians of the logits, valence/arousal, blendshapes, head
     pose); frames while the learner talks (voice detection), with the jaw open or the head turned are skipped; a
     passing smile is absorbed by the median. The UI shows *Calibrating… look at the screen with a relaxed face*;
     **Recalibrate** repeats it; after 90 s without a face it happens again automatically;
   * **neutral or an expression?** — the relaxed face reads neutral with the preset's `p_ref` (0.9 for Balanced;
     a very neutral face keeps half of its extra neutrality). The **intensity** of an expression is how far the
     classes the face shows now have moved against neutral since the relaxed face — log-odds gains weighted by
     their current probability. A stern face that snarls (anger gains as neutral drops) and a stern face that
     smiles (happiness replaces anger while the neutral share hardly moves) both count; low-probability noise barely does;
   * **which expression?** — the classifier's reading of the face *now* among the non-neutral classes (a stern face
     that snarls is angry, not "disgusted"), limited to classes that gained on neutral since the relaxed face (a
     stern face that smiles is happy, not angry) and softly weighted by missing **hallmark facial actions**: disgust
     without a raised upper lip or wrinkled nose, happiness without a smile, surprise without raised brows / wide
     eyes / an open jaw, … (FACS-style, baseline-relative). This only moves probability between expressions —
     never into neutral. Anger has no hallmark requirement (brow blendshapes are not reliable enough);
   * **pose and talking** — frames far from the calibration pose count less in the smoothing (full weight within
     ±6° pitch / ±8° yaw, 0.1 at ~24° / 30°) and get a small neutral bonus (0.1 log-odds per degree of pitch beyond
     5°, capped at 1 — a clear expression is never pushed into neutral, it just counts less); while the learner talks
     frames count half, need a clearer face, and mouth words (smiling, baring teeth, lips pressed…) are not used;
   * **valence/arousal** — the relaxed face's bias is removed in proportion to how relaxed the face reads
     (a relaxed face → a neutral mood; an angry face keeps its negative, high-energy reading);
   * **slow adaptation** — while the classifier reads the face like the relaxed face, the baseline follows light
     and posture drift (τ ≈ 60 s), at most one log-odds unit per class (0.25 per blendshape, 12° of pose) away from the
     calibrated face — a slowly creeping expression is never absorbed.
6. **Emotion engine** (`emotion/engine.py`, per session): time-based smoothing weighted per frame; an expression is
   reported only once it is clearly there (≥ the sensitivity floor) and has led for the hold time by the margin;
   otherwise the face is described as neutral.

### Sensitivity (UI: Calm · Balanced · Expressive, env `EH_EMOTION_SENSITIVITY`)

| | relaxed face reads neutral | smoothing α @10 fps | switch hold | margin | "clearly there" floor |
|---|---|---|---|---|---|
| Calm | 0.95 | 0.15 | 1.6 s | 0.15 | 0.50 |
| **Balanced** (default) | 0.90 | 0.20 | 1.0 s | 0.12 | 0.42 |
| Expressive | 0.85 | 0.30 | 0.8 s | 0.08 | 0.32 |

### Checked on the learner's own frames (offline, screenshots they shared; local models only)

Calibrated on one relaxed frame, then each frame held for 3 s at 10 fps with logit noise, through the production
Calibrator + engine (Balanced):

| Frame | Raw model | First calibration | Now |
|---|---|---|---|
| relaxed face, two frames (head pitch 10° apart), calibrated on either | anger 0.95 / 0.83 | neutral | **Neutral 0.79–0.93** |
| snarl (teeth bared, brows down) ×2 | anger 0.98–0.99 | Neutral 0.41–0.47 / Disgusted | **Angry 0.89–0.96** — "baring teeth" |
| lips pressed together, brows down | anger 0.76 / disgust 0.24 | Neutral 0.70 / Disgusted 0.28 | **Angry 0.72–0.83** — "lips pressed together" |

Over 5 minutes of a relaxed face drifting between the two relaxed frames (head pitch changing by 10°, logit noise
up to σ 0.7), no expression was reported in any preset (0 % of the time). A snarl is reported after 1.3 s
(Balanced; 1.0 s Expressive, 2.2 s Calm) and the face is Neutral again 1.3–1.4 s after it relaxes.

## What the tutor receives

Only when exactly one face is clearly in view (and after calibration), one system message right before the question,
phrased as her own view of the learner on the call:

```
[What you see on the learner's webcam right now] The learner looks clearly angry. Visible right now: baring teeth. Overall mood: negative, high energy. Before that (a few seconds ago) they looked neutral.
```

* Words only — no numbers, no images, no landmarks. "Visible right now" names only facial actions that fit the
  expression it reports (a snarl stretches the lips, but the note never calls it "smiling") plus head pose. If the
  expression has not changed since the learner last spoke, the note says so ("only mention it if it matters"), so
  she does not comment on the same face every turn.
* The persona treats it as her eyes on a video call: asked "can you see me?" she says yes; she mentions what she sees
  only now and then, briefly and in character ("Why the frown? Did I lose you?"), never talks about estimates,
  readings, cameras or guesses, and believes the learner if they say she read them wrong. With no clear face there is
  no message and she does not pretend to see.
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
* Which expression is shown still comes from the classifier: when it confuses two expressions for a face (e.g. anger vs.
  disgust), calibration cannot fully separate them; the hallmark facial actions only nudge the choice.
* Calibration assumes the face is relaxed during the first seconds; if not (e.g. a held smile), press **Recalibrate**.
* An expression is not an emotion (Barrett et al., 2019): she describes how the learner *looks*, never claims to know
  how they feel, and accepts being corrected.
* The model's weights were trained on AffectNet (non-commercial research license) — fine for this non-commercial
  hackathon demo; a product would need a model with a suitable license.
* One face only; several faces → unknown by design.

## Tuning

`backend/scripts/vision_probe.py --seconds 30 --csv probe.csv` prints the gate, the raw top class, the calibration
progress, the calibrated dominant expression, the neutral log-odds, the pose weight and the visible actions from
**your** webcam (ask before running it for someone else); the CSV has raw and calibrated probabilities per frame.
Knobs: `EH_EMOTION_SENSITIVITY`, `EH_EMOTION_CALIBRATION_S`, `EH_EMOTION_ADAPT_TAU_S`, `EH_EMOTION_RECALIBRATE_AFTER_S`,
the gates `EH_MIN_FACE_WIDTH`, `EH_MAX_ABS_YAW_DEG`, `EH_MAX_ABS_PITCH_DEG`, `EH_MIN_BRIGHTNESS`; the presets
(`SENSITIVITY`), the hallmark ranges (`HALLMARK`), the gain gate and the pose/talk bonuses live in `emotion/calibration.py`.
