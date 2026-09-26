# The confusion proxy — method, parameters, limitations

ExtraHorizon does **not** detect emotions. It computes a *confusion proxy*: a number
in [0, 1] derived from visible facial-expression coefficients that prior research has
associated with confusion during learning. The UI always labels it **estimate**, the
LLM never sees it, and a sustained rise only *offers* a different explanation.

## Pipeline (all on the local machine)

```
browser: getUserMedia → draw on canvas at 480 px width → JPEG q=0.75
   │  one frame in flight, ≤ 12 fps, over a localhost WebSocket
   ▼
FaceAnalyzer (backend/extrahorizon/vision/analyzer.py)
   MediaPipe Face Landmarker (VIDEO mode, CPU/XNNPACK, ~7 ms/frame on the dev laptop):
   478 landmarks, 52 blendshape coefficients, 4×4 head transform
   ▼
assess_quality (vision/proxy.py) — anything unreliable becomes `unknown` + reason
   no face · >1 face (ambiguous: never adapt to a random face) · face width < 11 % of the
   frame · |yaw| > 32° or |pitch| > 28° · face-box brightness < 40 or > 235 · undecodable frame
   ▼
ConfusionProxy (vision/proxy.py)
   1. per-session neutral baseline: median of each feature over the first 2.5 s of good
      frames (restarts after a >1.5 s break; re-captured after 45 s without a face,
      on Reset, or via the Recalibrate button)
   2. features (mean of left/right coefficients):
        brow_lower  = browDown        ≈ AU4 brow lowerer        (main cue)
        lid_tighten = eyeSquint       ≈ AU7 lid tightener
        lip_press   = mouthPress      ≈ AU24 lip presser
        smile       = mouthSmile      ≈ AU12 (suppressor)
        blink       = eyeBlink        (gates lid_tighten: closing eyes fake a squint)
   3. deviation above the personal baseline, headroom-aware:
        d = clamp((x − base) / max(0.12, min(scale, 0.9·(1 − base))), 0, 1)
   4. noisy-OR: raw = 1 − (1 − 0.85·d_brow)(1 − 0.45·d_lid·(1 − blink_gate))(1 − 0.30·d_press)
   5. smile suppression: raw × (1 − clamp((Δsmile − 0.15) / 0.30, 0, 1))
   ▼
StateEngine (engine.py) — the only place that decides
   time-based EMA  a = 1 − (1 − α)^(Δt·10), α = 0.2 (≙ α 0.2 per frame at 10 fps, any real fps)
   event when smoothed > 0.65 continuously for ≥ 2.0 s (wall clock) and not in the 15 s cooldown;
   then disarmed until smoothed < 0.55 or a new answer arrives (one event per episode)
   unknown / gap > 0.75 s → smoothed = None, hold timer reset
   after an adapted answer: smoothed < 0.45 for ≥ 2 s within 60 s → "decrease observed" (info only)
```

Why these choices:

* **Brow lowering first.** Studies of learners in tutoring systems reported AU4 (brow
  lowering) and AU7 (lid tightening) as the facial actions most consistently co-occurring
  with confusion (e.g. McDaniel et al., 2007, *Facial features for affective state
  detection in learning environments*, CogSci; Grafsgaard et al., 2011, *Predicting
  facial indicators of confusion with hidden Markov models*, ACII; D'Mello & Graesser's
  work on confusion in learning). We use them as *cues*, not as a validated classifier.
* **Personal baseline.** Resting faces differ a lot: on the MediaPipe test portrait
  `browDown` is ≈ 0.8 while the person smiles broadly. Without a baseline that face would
  read "confused" forever. With it, only the *change* counts.
* **Noisy-OR.** A strong brow lowering alone can cross the threshold (0.85 ≥ 0.65); lid
  tightening and lip press add evidence but cannot trigger an event on their own
  (0.45 and 0.30 < 0.65) — this keeps squinting at a bright screen from firing alone.
* **Smile suppression.** Smiling raises cheeks and squint coefficients; it is not confusion.
* **Time-based EMA + 2 s hold + cooldown.** One frame of frowning never triggers; frame-rate
  changes (slow laptop, background tab) do not change the timing; one event per episode.
* **Unknown is unknown.** Absent or ambiguous data is never mapped to "neutral" (0) or
  "confused"; the timeline shows gaps, the meter shows "—" with the reason.

## Parameters

All live in `backend/extrahorizon/config.py` and can be overridden in `.env`
(`EH_*`, listed in `.env.example`). The engine numbers are the spec's working
hypotheses; the proxy weights/scales are first guesses validated on synthetic
blendshape vectors and the MediaPipe test portrait, **not yet on a real camera**
(see "Tuning" below).

| Name | Default | Meaning |
|---|---|---|
| `EH_EMA_ALPHA` / `EH_EMA_REFERENCE_FPS` | 0.2 / 10 | smoothing |
| `EH_THRESHOLD` | 0.65 | smoothed proxy must exceed … |
| `EH_HOLD_S` | 2.0 | … continuously for this many seconds |
| `EH_COOLDOWN_S` | 15 | no new event for this long after one |
| `EH_REARM_THRESHOLD` | 0.55 | after an event, the next one needs a drop below this (or a new answer) |
| `EH_MAX_GAP_S` | 0.75 | a longer gap without data counts as unknown |
| `EH_RELIEF_THRESHOLD` / `EH_RELIEF_HOLD_S` | 0.45 / 2.0 | "decrease observed" rule |
| `EH_CALIBRATION_S` | 2.5 | neutral-baseline duration |
| `EH_PROXY_W_*`, `EH_PROXY_SCALE_*` | see config | cue weights / expected rise |
| `EH_PROXY_SMILE_START` / `_FULL` | 0.15 / 0.45 | smile suppression ramp |
| `EH_MIN_FACE_WIDTH`, `EH_MAX_ABS_YAW_DEG`, `EH_MAX_ABS_PITCH_DEG`, `EH_MIN_BRIGHTNESS` | 0.11, 32, 28, 40 | quality gates |

## Tuning with the real camera

`backend/scripts/vision_probe.py` runs the identical pipeline on a local webcam and
prints features, raw/smoothed values and events (optionally to CSV). Protocol and
knob table: `.claude/skills/extrahorizon-vision-tuning/SKILL.md`. Expected behaviour:
neutral reading ≤ ~0.25; a deliberate frown crosses 0.65 in < 1 s and fires once after
~2 s; smiling stays low; looking away / two faces → unknown.

## Limitations (say these out loud)

* It measures **expressions, not states**. Brow lowering also happens with concentration,
  frustration, disagreement, bright light, glasses sliding, or just someone's habit.
  Confusion without a visible expression is invisible to it.
* Weights and scales are heuristic and were not fitted on a labelled dataset; accuracy is
  unknown. Treat every event as "possible confusion", which is exactly how the UI words it.
* MediaPipe blendshapes vary with lighting, camera quality, head pose, occlusion (hands,
  masks), facial hair and glasses; the quality gates catch the gross cases only.
* One calibrated person at a time. Several faces → unknown by design.
* Performance across ages, skin tones, cultures and camera setups has **not** been evaluated in
  this project (see Google's MediaPipe Face Landmarker model card for the model's own evaluation).
* The demo presenter frowns deliberately — that shows the causal chain works; it is not
  evidence that spontaneous confusion is detected reliably.
