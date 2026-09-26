# ExtraHorizon — pitch & demo script

## 30-second pitch

Chatbots make you type, wait, and read a wall of text. A good tutor *talks* with you — answers
right away, notices when you look lost, and stops when you jump in. **ExtraHorizon** is that
tutor: **Rika**, a tsundere anime girl with an expert's rigour. You just talk; she answers in an
expressive voice within about two seconds, covers her thinking time with a natural "Hmm…", stops
the instant you talk over her, and waits when you pause mid-sentence. A model running **on your own
computer** first learns *your* relaxed face in three seconds, then reads your facial expression relative
to it — happy, surprised, anxious, neutral… — so a resting face or a lowered head isn't "angry". She sees
you like on a video call and adapts her tone and pacing. Your video never leaves the laptop; the language
model only gets a few words like *"the learner looks mostly anxious; frowning"*.

## Demo (60–90 s)

| t | Do | Say |
|---|---|---|
| 0:00 | App open, camera **Active** (consent given before the show), face box labelled *Neutral* (calibrated before the show; **Recalibrate** if the light changed), Expression panel live | "The camera is analysed right here. It first learned *my* relaxed face, so it reads changes from it — eight expressions, valence and energy. It's an *estimate* of how a face looks, not a mind-reader." |
| 0:08 | Mic on (green). **"Can you see me?"** | She: "Yeah, I can see you — you look pretty relaxed." |
| 0:12 | **"Explain recursion to me."** | "No typing — I just talk." |
| 0:13 | Filler "Hmph." → her answer, in character, cue chips in the chat | "Filler the moment I stop, answer about two seconds later — and look at the stage directions: that's how the voice model performs her." |
| 0:25 | Talk over her: **"Wait, stop."** | "She stops instantly — and 'wait, stop' alone doesn't trigger a new answer." |
| 0:30 | **"Can you give me… (pause) …a simpler example?"** | "I paused mid-sentence — it waited and joined both parts." |
| 0:45 | Frown clearly / smile; point at the panel and **What Rika is told** | "This exact sentence is all the model gets about my face — no numbers, no images. A tiny brow twitch doesn't count; a real frown does, and she slows down." |
| 1:00 | Open an answer's **expression sent** chip | "Every answer shows what went into its prompt." |
| 1:10 | **"Where do the utilities' construction plans overlap?"** | "Second skill: she reads Miami-Dade's public utility plans live, verifies every record and flags where two utilities will dig near each other at the same time." |
| 1:20 | The map opens on F1 (blue sewer main × orange state road, white overlap); **Sources & checks** | Read the tiles aloud (on 2026-09-26: "2,815 records read, 386 verified future projects, every exclusion counted — and 64 of our 80 intersecting pairs are on the county's own conflict list"). "Every number she wrote is checked against this data." |
| 1:30 | **New session** | "Clean slate for the next person." |

If the camera misbehaves: say so, open **Demo simulation mode** (labelled SIMULATED / NOT LIVE everywhere) and pick
an expression — the same engine → note → answer chain. Never present simulation as recognition. If the Wi-Fi dies:
`start.ps1 -MockLLM -MockVoice` (labelled offline doubles).

## Honest claims (identical in UI, README and pitch)

* Video frames stay on this computer: downsized in the browser, sent over localhost to the Python process,
  analysed in memory (MediaPipe + an on-device expression model), discarded. Not stored. Not sent anywhere.
* Microphone: speech is detected locally; only the parts where you speak go to OpenAI for transcription.
* OpenAI (chat) receives your messages, her earlier answers, and — only when one face is clearly in view and
  calibrated — a short words-only description of your *apparent* expression and visible facial actions (no numbers,
  no images). She treats it as what she sees on the call, mentions it rarely, and believes you if you say she read
  you wrong; the app labels every reading as an estimate.
* Fish Audio receives the text of her answers to speak them.
* Google's MediaPipe library sends Google anonymous usage metrics while the camera is on; per Google never images.
* Facial-expression estimates are imperfect and biased; calibration removes one person's resting-face bias, not
  every error. An expression is not a feeling.
* Utility-coordination analysis: public Miami-Dade County data, read live and verified; the overlaps are measured, the
  suggested ways to coordinate are general practice, not the agencies' decisions; dates are plans and change. Power,
  gas and telecom layers are published but empty today, so the utilities compared are WASD's and DTPW's networks
  against each other and against FDOT/DTPW road work. Her report's figures are checked against the verified data.
  The map tiles come from OpenStreetMap's servers.
* **Remote demo (the PC at home, the laptop on stage):** say it plainly — "the heavy lifting runs on my PC at home;
  this laptop just streams the camera and microphone to it over HTTPS through Cloudflare Tunnel". Then the video does
  *not* stay on the laptop: it goes through Cloudflare to the PC, is analysed there in memory and discarded — the app
  shows exactly this wording, and it is protected by an access key.

## Remote demo checklist (PC at home → laptop at the venue)

1. At home: `.\scripts\demo-host.ps1 -Check` → all `[ok]`; `-Install` if the PC must restart it by itself; sleep off.
2. `cd backend; uv run python scripts/demo_check.py --base <public URL> --access-key-env --speech ..\frontend\e2e\.cache\question.wav`
   → PASS through the tunnel.
3. On the laptop, before the show: open the URL on the venue network, enter the key (`-ShowKey` at home), camera
   + microphone permission, headphones; one question end to end. If the venue upload is weak: `EH_REMOTE_MAX_FPS=6`.
4. Fallback if the tunnel or the home connection fails: run locally on the laptop (`.\scripts\start.ps1 -Open`)
   and say so — slower, but everything is real; or `-MockLLM -MockVoice` (labelled offline doubles).

## Final rehearsal plan (on the demo laptop, ~25 min)

1. `.\scripts\setup.ps1` (fresh clone) → keys in `.env` → `.\scripts\start.ps1 -Open`.
2. `/api/health?deep=1` → LLM reachable, voice `ok`, speech recognition + VAD configured, fillers `ready`, vision available.
3. `cd backend; uv run python scripts/demo_check.py --runs 3` → PASS (real providers, simulated expression).
4. With the presenter: `scripts/vision_probe.py --seconds 60` in the venue light — relaxed for the first 3 s
   (calibration), then neutral / small brow movements / lowered head (must stay neutral) / clear smile / clear frown
   / look-away → unknown; pick Calm / Balanced / Expressive or adjust `.env` (docs/EMOTIONS.md).
5. Voice in the venue: choose the right microphone in the app (not the webcam's); headphones or moderate speaker
   volume; test barge-in and a mid-sentence pause; if she
   interrupts herself, raise `EH_BARGE_IN_THRESHOLD`; if she cuts you off, raise `EH_VAD_END_SILENCE_MS`.
6. Utility-coordination analysis on the venue network: ask the question once (the county's data is then cached for
   6 h); check the map tiles load; the panel's **Read the county's data again** refreshes before the show.
7. Walk through the manual rows still marked *not tested* in docs/TEST_MATRIX.md and update them.
8. Rehearse the script 3× with a timer; **New session** between runs.
