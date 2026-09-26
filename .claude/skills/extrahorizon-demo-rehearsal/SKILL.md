---
name: extrahorizon-demo-rehearsal
description: Prepare, rehearse and troubleshoot the 60–90 second ExtraHorizon ShellHacks demo (camera → local confusion signal → stable event → "Explain differently" → visibly different answer → "Why it adapted" → Reset). Use this when the user asks to rehearse, "прогнать демо", check demo readiness, fill in the manual test matrix, prepare the pitch, handle a failure on stage (no camera, no Wi-Fi, LLM down), or decide what can honestly be claimed — even if they only say "готово к показу?" or "what if the camera fails".
---

# Demo rehearsal

The one thing the demo must prove: **camera → local signal → stable event → context →
visibly different LLM answer**, with an honest explanation on screen. Everything else is secondary.

## Before the show (5 minutes)

1. `.\scripts\start.ps1 -Open` on the demo laptop (loopback only — then the UI may say video stays on this device).
2. `curl http://127.0.0.1:8765/api/health?deep=1` → `llm.reachable: true`, `vision.available: true`.
3. In the UI: click **Turn on camera** once (consent card; the browser remembers it), then camera **Active**, face box visible, "calibrating … %" finishes, signal shows a number (not "—").
4. Good light on the face, laptop camera at eye level, only the presenter in frame (two faces = ambiguous, by design).
5. `cd backend && uv run python scripts/demo_check.py --runs 3` → all PASS (checks the real LLM path end-to-end with the labelled simulation input).
6. Click **Reset demo**.

## The 60–90 s script

1. "ExtraHorizon is a tutor that notices when an explanation may not be landing." Point at the camera card: *local MediaPipe, estimate*.
2. Type **Explain recursion to me.** → answer streams (~0.5–1 s to first token).
3. Read for a second, then frown deliberately (brows down, eyes narrowed) for ~2–3 s. The meter turns orange, "above threshold 1.2 / 2.0 s", then **Possible confusion detected** + the **Explain differently** button.
4. Click it → a different explanation (analogy → example → 3 short steps), badge *Adapted*.
5. Open **Why it adapted**: the real smoothed value, the rule (EMA α 0.2, > 0.65 for ≥ 2 s, 15 s cooldown), the strategy, and the exact note sent to the model (no numbers, no images).
6. Relax your face → after ~2 s low, *After: … stayed below 0.45 … (observed)* appears — only if it was really measured. Never narrate an improvement that the UI did not show.
7. **Reset demo** before the next judge.

## Fallbacks (say what is happening — never pass one off as live recognition)

| Problem | Do this |
|---|---|
| Camera denied/busy/unplugged | UI already says "Vision unavailable — chat still works". Retry camera; else open **Demo simulation mode** (it is striped + labelled SIMULATED everywhere) and say "this is the manual simulation input driving the same engine". |
| Face not detected | More light, move closer, face the camera, one person only; **Recalibrate** with a neutral face. |
| Wi-Fi / OpenAI down | Error card with **Retry** appears (no endless spinner). Restart with `-MockLLM` for a labelled offline run. |
| Event fires too easily / never | Tune per `extrahorizon-vision-tuning` (thresholds live in `.env`). |

## Manual matrix (record in docs/TEST_MATRIX.md as pass / fail / not tested)

Camera allowed / denied · no face · two faces · camera unplugged mid-session · WebSocket drop
(stop + start backend) · backend restart (tab clears with a toast) · missing API key · LLM timeout
(`EH_LLM_FIRST_TOKEN_TIMEOUT_S=0.01`) · page refresh (conversation restored) · repeated reset ·
10 consecutive full runs. Items needing a physical webcam must be run by a person — if you (an
agent) could not do one, mark it **not tested** and list it for the final rehearsal instead of
claiming it passed.

## Claims that are true (keep README, UI and pitch aligned)

- Video: downsized frames go over **localhost** to the Python process, are analysed in memory and discarded; never stored, never sent to OpenAI.
- OpenAI receives: chat text, earlier answers of the session, and (only after the click) a short adaptation note without numbers.
- Google receives MediaPipe usage metrics (performance/utilisation, no images per Google's notice) while the camera is on — measured: HTTPS to a Google server ~1 min into a camera session and at its end. No switch exists; hence the explicit camera consent card. Never claim "nothing but the LLM leaves the machine".
- The signal is a heuristic *confusion proxy (estimate)* from facial expression coefficients — not a validated emotion classifier and not the learner's inner state.
