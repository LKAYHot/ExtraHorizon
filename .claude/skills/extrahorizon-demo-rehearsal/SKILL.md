---
name: extrahorizon-demo-rehearsal
description: Prepare, rehearse and troubleshoot the 60–90 second ExtraHorizon ShellHacks demo (calibrate to the presenter's face → "Can you see me?" → talk to Rika hands-free → filler + spoken answer with voice cues → barge-in "wait, stop" → paused sentence joined → facial expression visualised and sent as a words-only note → New session). Use this when the user asks to rehearse, "прогнать демо", check demo readiness, fill in the manual test matrix, prepare the pitch, handle a failure on stage (no camera, no microphone, echo, no Wi-Fi, LLM or Fish Audio down), or decide what can honestly be claimed — even if they only say "готово к показу?" or "what if the mic fails".
---

# Demo rehearsal

The demo must prove two chains, with honest explanations on screen:
**voice → fast in-character spoken answer you can interrupt**, and
**camera → calibrated on-device expression estimate → words-only note of what she sees → adapted tone**;
optionally a third: **"Where do the utilities' construction plans overlap?" → live county data verified → map +
findings → her grounded report** (docs/ANALYSIS.md, skill `extrahorizon-coord-analysis`; run it once before the show
so the county's data is cached, read the numbers from the tiles — they change with the county's data).

If the laptop is only the screen and the PC at home does the work (Cloudflare Tunnel), prepare with the
`extrahorizon-remote-demo` skill first (`demo-host.ps1 -Check`, `demo_check.py --access-key-env` through the
tunnel) and say on stage that the processing runs on the home PC via Cloudflare.

## Before the show (5 minutes)

1. `.\scripts\start.ps1 -Open` on the demo laptop (loopback only — then the UI may say video stays on this device).
2. `http://127.0.0.1:8765/api/health?deep=1` → `llm.reachable: true`, `tts.state: ok`, `stt.configured: true`, `stt.vad: true`, `fillers: ready`, `vision.available: true`.
3. `cd backend && uv run python scripts/demo_check.py --runs 2 --speech ../frontend/e2e/.cache/question.wav` → PASS (real providers; expression from the labelled simulation).
4. In the UI: **Turn on camera** once (consent) → sit as you will present, relaxed, looking at the screen, silent for
   ~3 s (**Calibrating…**) → face box *Neutral*; small brow movements / nodding must stay Neutral (else **Recalibrate**,
   or **Calm**). **Mic** → disclosure → pick the right microphone (not the webcam's) → on (the browser remembers it).
5. Headphones, or speakers at moderate volume (her voice must not trigger barge-in). Good light, one person in frame.
   After changing seats or light: **Recalibrate**.
6. **New session**.

## The 60–90 s script

See `docs/PITCH.md` (table with timings and lines). Core beats: "Can you see me?" (she says yes, in character) →
speak "Explain recursion to me." → filler → answer in
~2 s with stage-direction chips → talk over her "Wait, stop." (she stops; no new answer) → a question with a pause in
the middle (joined) → point at **What Rika is told** and an answer's **expression sent** chip → **New session**.

## Fallbacks (say what is happening — never pass one off as live)

| Problem | Do this |
|---|---|
| Camera denied/busy/unplugged | UI says "Camera unavailable — chat and voice still work". Retry; else **Demo simulation mode** (labelled SIMULATED / NOT LIVE) and say so. |
| Expression stays Unknown | more light, closer, face the screen, one person only. |
| Reads Angry / Unimpressed while relaxed | **Recalibrate** with a relaxed face; **Calm** sensitivity. |
| Stuck on Calibrating… | look at the screen, relaxed and silent for 3 s (talking / turned head are skipped). |
| Wrong microphone | choose it in the Microphone list (sidebar or under the chat) — it switches live. |
| Microphone denied/unavailable | allow it in the address bar; otherwise type — she still speaks the answers. |
| She interrupts herself (echo) | headphones / lower volume; raise `EH_BARGE_IN_THRESHOLD` (0.6 → 0.7) or `EH_BARGE_IN_MIN_MS` (350 → 500). |
| A noisy room / the audience cuts her off | turn off **Let me interrupt her** (sidebar) before the demo: she always finishes, speech during her turn is ignored ("she finishes first"), Stop / Esc still stops her. |
| She cuts you off | raise `EH_VAD_END_SILENCE_MS` (550 → 700). |
| Fish Audio down / quota | answers still stream as text (toast "Voice output problem"); keep going or restart with `-MockVoice` (labelled tone). |
| Wi-Fi / OpenAI down | error card with Retry; restart with `-MockLLM -MockVoice` for a labelled offline run. |

## Manual matrix (record in docs/TEST_MATRIX.md as pass / fail / not tested)

Camera allowed / denied · calibration (relaxed → Neutral, small movements stay Neutral, clear smile / frown show) ·
no face · two faces · camera unplugged mid-session · mic allowed / denied · microphone switch · spoken
question with a real person · barge-in with speakers vs headphones · "wait, stop" · a paused sentence · Russian
question (answered in English) · noisy room · WebSocket drop · backend restart · missing keys · LLM timeout · page
refresh · repeated New session · 10 consecutive runs. Items needing a physical webcam/microphone and a person must
be run by a person — if you (an agent) could not do one, mark it **not tested**.

## Claims that are true (keep README, UI and pitch aligned)

- Video: downsized frames go over **localhost** to the Python process, analysed in memory (MediaPipe + on-device expression model), discarded; never stored, never sent to any cloud service.
- Microphone: speech detected locally; only speech segments (+0.4 s pre-roll) go to OpenAI for transcription.
- OpenAI (chat) receives the messages, earlier answers and — only with one clear, calibrated face — a short words-only description of the *apparent* expression and visible facial actions (no numbers, no images).
- Fish Audio receives her answer text (and the filler phrases once).
- Google receives MediaPipe usage metrics while the camera is on (no images per Google). Never claim "nothing leaves the machine".
- Expressions are estimates of how a face looks, imperfect and biased — not feelings. Calibration removes one person's resting-face bias, not every error.
