# ExtraHorizon — pitch & demo script

## 30-second pitch

Online learners get stuck silently. A human tutor sees the frown and says "let me put it
another way"; a chatbot just keeps talking. **ExtraHorizon** is an AI tutor that watches for
that moment — *on your own computer*. A local vision model turns facial-expression cues into
a smoothed **confusion estimate**; when it stays high for about two seconds after an answer,
the tutor offers to explain differently — with an analogy, one concrete example and short
steps — and shows exactly *why* it adapted. Your video never goes to the cloud; the language
model only receives a one-line note that the last explanation may not have landed. (The MediaPipe library does
report anonymous usage metrics to Google — never images — and we say so on screen.)

## Demo (60–90 s)

| t | Do | Say |
|---|---|---|
| 0:00 | App open, camera **Active** (consent card clicked once before the show — the browser remembers it), face box, signal ≈ 0.1 | "The camera is analysed right here by a local model — this number is an *estimate*, not a mind-reader." |
| 0:10 | Type **Explain recursion to me.** | "Normal tutor answer, streaming from the LLM." |
| 0:25 | Frown for ~2–3 s while "reading" | "Watch the meter: it has to stay above the line for two seconds — one frown frame does nothing." |
| 0:30 | **Possible confusion detected** + button appears | "That's an event from the state engine, with a cooldown so it never spams." |
| 0:35 | Click **Explain differently** | "It re-explains with an analogy, an example and three short steps." |
| 0:50 | Open **Why it adapted** | "Here's the real signal value, the rule, the strategy, and the exact note sent to the model — no numbers, no images." |
| 1:05 | Relax; *After: … (observed)* appears | "It only claims the confusion went down because it actually measured that." |
| 1:15 | **Reset demo** | "Clean slate for the next person." |

If the camera misbehaves: say so, open **Demo simulation mode** (it is labelled SIMULATED
everywhere) and show the same engine → context → answer chain. Never present simulation as
recognition.

## Honest claims (identical in UI, README and pitch)

* Video frames stay on this computer: downsized in the browser, sent over localhost to the
  Python process, analysed in memory, discarded. Not stored. Not sent to OpenAI.
* OpenAI receives the chat text, earlier answers of the session, and — only after the click —
  a short note that possible confusion was observed.
* Google's MediaPipe library sends Google anonymous usage metrics (performance/utilisation, e.g.
  frame counts and latency) while the camera is on; per Google's privacy notice it never sends the
  images. The camera starts only after an explicit click on a card that says so.
* The signal is a heuristic *confusion proxy* from expression cues (brow lowering, lid
  tightening, lip press; smiling suppresses it). It can be wrong; it only ever *offers* help.

## Final rehearsal plan (on the demo laptop, ~20 min)

1. `.\scripts\setup.ps1` (if the repo was freshly cloned) → `.\scripts\start.ps1 -Open`.
2. `/api/health?deep=1` → LLM reachable, vision available.
3. Run `backend/scripts/vision_probe.py --seconds 90` with the presenter in the venue light:
   neutral ≤ 0.25, frown > 0.65 within 1 s, smile low, look-away → unknown. Adjust `.env`
   (see `docs/CONFUSION_PROXY.md`) if needed, restart.
4. Walk through the manual matrix rows still marked *not tested* in `docs/TEST_MATRIX.md`
   (live frown, unplug camera mid-session) and update them to pass/fail.
5. Rehearse the script above 3× with a timer; **Reset demo** between runs.
6. Prepare the fallback: know where the simulation card is; have `-MockLLM` ready if Wi-Fi dies.
