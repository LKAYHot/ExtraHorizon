# ExtraHorizon — architecture

```
┌──────────────────────────── Browser tab (SvelteKit SPA, Svelte 5) ─────────────────────────────┐
│ Sidebar: brand · New session · Rika persona · subject · microphone · voice cues · status       │
│ Chat: header orb (listening / hearing / thinking / speaking) · messages with voice-cue chips,  │
│       "spoken" / "interrupted" / "speaking" tags, the expression note sent with each answer    │
│       composer: mic toggle (hands-free) · live caption · filler · Stop (Esc) · typed chat (SSE) │
│ Expression panel: camera + labelled face box · Recalibrate · expression now (8 bars,           │
│       sensitivity Calm/Balanced/Expressive, calibration progress) · mood map ·                 │
│       stacked timeline (+ table) · "What Rika is told" · Demo simulation · privacy             │
│ VisionController: getUserMedia → OffscreenCanvas 480 px → JPEG → [seq|jpeg] ─ WS /api/vision │
│ VoiceController:  getUserMedia(chosen mic, AEC, NS, AGC) → AudioWorklet → PCM16 24 kHz ─ WS    │
│                   /api/live · device list (enumerateDevices, devicechange, live switch)        │
│                   TtsPlayer: turn-tagged PCM → gapless WebAudio, instant stop                  │
└──────────────┬───────────────────────────────┬─────────────────────────────▲──────────────────┘
   localhost   │ WS /api/vision                │ WS /api/live (both ways)    │ SSE /api/chat
               ▼                               ▼                             │
┌────────────────────────────── Python process (FastAPI + uvicorn) ────────────────────────────────┐
│ OriginGuard + TrustedHost (no cross-site driving of the tutor, camera or microphone sockets)       │
│ VisionConnection: latest-frame-wins → FaceAnalyzer (MediaPipe + EmotiEffLib ONNX, thread pool;    │
│   upright square crop + mirror averaged) → quality gates → Session.calib (Calibrator: baseline,    │
│   neutral vs expression relative to it, which expression, hallmarks, pose) → Session.emotion        │
│   → tick / calibration / emotion_note / marker                                                     │
│ LiveConnection: VadSegmenter (Silero ONNX) → utterances → OpenAIRealtimeStt (speech only)          │
│   → turn logic: FillerBank · speculative ChatPlan (gated) · confirm/replace · barge-in ·           │
│     stop commands · continued sentences · echo guard · final-transcript watchdog                   │
│ TurnRunner (one turn): LLM stream → deltas → Speaker (TtsSplitter → FishSession → SilenceCap)     │
│   → audio frames on the live socket; commit on done / interrupted; nothing on errors              │
│ SessionStore (per tab, in memory, TTL/LRU): history · calibration · emotion engine · timeline ·   │
│   plan · speaker                                                                                   │
│ Serves frontend/build · health · reset · interrupt · state                                        │
└───────┬───────────────────────────────┬──────────────────────────────────┬─────────────────────────┘
        │ speech segments (PCM)          │ chat text + expression note      │ answer text with voice cues
        ▼                                ▼                                  ▼
 OpenAI Realtime transcription    OpenAI Chat Completions (stream)    Fish Audio live TTS (WebSocket)
 gpt-live-transcribe               gpt-6-luna (fallback gpt-5.5)       drama-3-preview, voice c5d8…
```

## Data flow of the key chains

1. **Camera → expression.** The browser keeps one frame in flight; the backend analyses it in a worker thread
   (MediaPipe ≈7–15 ms + expression model ≈10 ms for the aligned crop and its mirror), gates quality, and answers
   with a `tick`. Frames are never queued, stored or forwarded.
2. **Calibration.** Per session the first ~2.5 s of a relaxed face become the learner's baseline (status
   `calibrating` meanwhile). Every later frame is read relative to it: *whether* the face shows an expression from
   how far the classes it shows now have gained on neutral since the relaxed face, *which* expression from how the
   face reads now (nudged by hallmark facial actions); frames far from the calibration pose or while the learner
   talks count less. Recalibrate / sensitivity arrive over the same socket (see [EMOTIONS.md](EMOTIONS.md),
   [CONTRACT.md](CONTRACT.md)).
3. **Expression → prompt.** The engine keeps a smoothed distribution and a stable dominant expression; `describe()`
   turns it into words (+ visible facial actions). Each question snapshots it into `emotion_context`; its `note`
   is added as a system message phrased as what she sees on the call ("unchanged" when the learner's face is the
   same as last time). The UI previews the note live (`emotion_note`) and shows the exact note per answer.
4. **Voice in.** Mic frames (from the microphone the learner chose) → Silero VAD; only utterances (+pre-roll) go to OpenAI; at end of speech the filler plays
   and (if the live transcript has words) a speculative turn starts behind a gate; the final transcript confirms or
   replaces it. See [VOICE.md](VOICE.md) for all turn-taking rules.
4. **Voice out.** The turn streams LLM text to the chat and, through the splitter, to Fish Audio; audio frames are
   forwarded with the turn number only after the gate is open (speculation never speaks early). Barge-in / stop /
   a newer question / reset abort the speaker and send `audio_stop`.
5. **Commit.** A turn is committed to history on `done` (or `interrupted` with the partial text); errors, discarded
   speculation and merged turns commit nothing.

## Concurrency notes

* Everything that mutates a session runs on the event loop; frame analysis and the VAD model factory run in executors.
* One `ChatPlan` is current per session; a newer one cancels the older (`superseded`); the **first** cancel reason
  wins (e.g. `interrupted` keeps the partial answer even if `superseded` follows).
* A speculative plan's voice is held behind `plan.gate`; aborting a speaker that never released audio does **not**
  send `audio_stop` (the filler and the replacement answer share the turn number).
* The live socket has a single writer (queue); audio frames of stopped turns are dropped server-side.

## Failure handling

| Failure | Behaviour |
|---|---|
| Camera denied / missing / busy / unplugged | camera status in the UI, banner "chat and voice still work", expression `unknown` |
| No / several faces, bad light, head turned | `unknown` with a reason, gaps in the timeline, no note in the prompt |
| Vision or expression model missing / MediaPipe broken | vision unavailable in health and socket; chat and voice unaffected (models are imported lazily) |
| Microphone denied / missing | clear message under the composer; typing works |
| Chosen microphone unplugged / unavailable | falls back to the system default (the list shows it); a live switch keeps the conversation |
| Resting face misread (e.g. "angry" while relaxed) | per-person calibration; **Recalibrate**; **Calm** sensitivity; 90 s without a face → learn again |
| Voice detection model missing | `vad_unavailable` → mic off with a message |
| Speech-to-text unreachable / error | `stt_error` toast (rate-limited); a lost final transcript falls back to the live one after 3 s |
| Fish Audio unreachable / error / quota | `tts_error`; the answer still streams as text; a breaker pauses redialling for 30 s |
| She hears herself (speakers) | stricter barge-in bar while audible + browser AEC + echo guard on the transcript |
| Learner pauses mid-sentence | continuation joins the utterances (≤ 3 s, before she answers aloud) |
| WebSocket drop | vision: expression `unknown`; live: spoken turn cancelled; exponential reconnect (0.5 → 5 s) |
| Backend restart | new `boot_id` → the tab clears its view with a toast |
| Missing key / 401 / 404 / 429 / 5xx / network | `error` with code + message; UI error card with Retry (typed) |
| LLM too slow / stalls | first-token 15 s, idle 20 s, total 60 s → `llm_timeout`; client watchdog 25 s |
| Second tab with the same session | newer sockets supersede the older ("Use here" button) |
| Remote browser without the key / with an expired cookie | the access gate (key prompt) instead of the app; `401` → back to the gate; no key on the server → "Remote access is off" |
| Tunnel down / server stopped (remote demo) | the gate shows "server not reachable — retrying"; `demo-host.ps1` restarts a stopped server; Cloudflare shows 502/530 (docs/REMOTE_DEMO.md) |
| Proxy closes a silent WebSocket (~100 s) | keepalive pings (vision 20 s, voice 15 s); reconnect with back-off otherwise |

## Remote demo (the presenter's PC behind Cloudflare Tunnel)

```
laptop browser ─HTTPS─▶ Cloudflare edge ═ tunnel ═▶ cloudflared (service on the PC) ─▶ http://127.0.0.1:8080
                                                                                       AccessGuard → the app
```

The server still binds to loopback; `access.py` classifies every request (`local` / `cloudflare` / `proxy` /
`network` — tunnel requests also come from 127.0.0.1, only the headers tell them apart) and `AccessGuard`
lets non-local requests into `/api/*` and the sockets only with the signed access cookie issued by
`POST /api/access`. A remote browser gets a lighter camera profile (8 fps, JPEG 0.7) and honest "via
Cloudflare" wording. `scripts/demo-host.ps1` runs and supervises it; details in [REMOTE_DEMO.md](REMOTE_DEMO.md).

## Utility-coordination analysis ([ANALYSIS.md](ANALYSIS.md))

```
question / Coordination button ─▶ Session.plan_chat (mode run | context) ─▶ TurnRunner._run_analysis
   CoordService.analyze: ArcGIS REST (14 layers + the county's conflict list; memory 6 h, last copy on disk)
     → verify (dataset checks, record checks, parts merged) → overlaps (local metric plane, STR-tree, GEOS)
     → county cross-check → report (findings, pairs, highlights, simplified footprints)
   ─▶ SSE / live: analysis {running → progress → ready | error}
   ─▶ fact sheet (the only facts she may state) + report rules → LLM (3,000 tokens; first paragraph voiced)
   ─▶ grounding check (numbers ≥ 10, dates, finding IDs vs the sheet) → done.analysis.check
Browser: AnalysisPanel replaces the Expression panel — tiles · pair picker · Leaflet map (OSM tiles) ·
   Findings (re-check live) · Schedules (SVG) · Sources & checks (rules form → POST /api/coord/analyze)
```

| Failure | Behaviour |
|---|---|
| A county layer does not answer | its last good copy is used and labelled (in the panel, the report and her fact sheet); without a copy the layer is left out and named as unreadable; a read with a failed layer is retried after a minute |
| No layer can be read | the analysis fails: `analysis` error event / `502 analysis_source`; her fact sheet says FAILED and she says so plainly |
| The written report reaches its length limit | a visible note ends it (the map and findings list have everything) |
| She writes a number, date or ID that is not in the sheet | the answer is marked *not in the verified data: …* |
| Map tiles unreachable | the map keeps the projects and overlaps without streets |

## Hackathon hub ([HUB.md](HUB.md))

```
roadblock / "find me a teammate" / "where can I learn …" / "how much time is left" / the Hub panel
   ─▶ Session.plan_chat (hub: run | context | ship — only when the analysis does not claim the message)
   ─▶ TurnRunner._run_hub (a spoken question searches only once the final transcript confirms it)
     HubService.unstuck: scrub first (paths, hosts, IPs, ports, e-mails, keys, random-looking strings), then the signature
       → in parallel: Stack Exchange · GitHub issues · npm / PyPI (cache 1 h, the sources' limits respected)
       → verify + audit (matching, accepted/voted, fixed, registry facts; old flagged) → rank → S1…
       → the board: what teams learned (K…), mentors (M…), open requests about the same
     HubService.learn: GitHub examples/tutorials · DEV Community · top questions → L…
     HubService.people: the board's cards → matches within teams of four (P…), mentors (M…); then real public
       people: GitHub's user search (language + the event's city) → the first profiles' public repositories →
       verified leads (P…); Stack Overflow's top answerers for the stack (M…). Help board: unsolved questions.
   ─▶ SSE / live: hub {running → progress per source → ready | error | cancelled}
   ─▶ hub fact sheet + reply rules → LLM (1,800 tokens; first paragraph voiced; tools in follow-ups)
   ─▶ grounding check (figures, versions, dates, hub IDs vs the sheet, her look-ups, the learner's words) → done.hub.check
Board (people, help requests, what teams learned): backend/data/hub_board.json, entries owned by a browser token
(sent as X-Hub-Token on every hub request; only issued tokens accepted); in her sheet board text is one line per field,
marked as data, never instructions.
Browser: HubPanel — Get unstuck · People · Help board · Ship; hub IDs in her answers are buttons.
```

| Failure | Behaviour |
|---|---|
| A source cannot be read (rate limit, 403, timeout) | named in the panel and her sheet ("do not guess what it would have said"); the other sources still answer |
| The stack's GitHub repository moved (422) | the search runs everywhere instead |
| Nothing verified | she says so plainly and suggests a mentor or the help board (*Still stuck?* drafts the request) |
| She writes a figure, version, date or ID that is not in the sheet | the answer is marked *not in the verified data: …* |
| The server lost the session (restart, sweep) | the browser's token (`X-Hub-Token`) keeps its entries its own; `hello` restores the kept ship plan; a 401 `no_token` says hello and retries once |
| Someone writes instructions or IDs on the board | one line per field under "data, never instructions"; an ID written on the board is not a result (her answer citing it is flagged) |

## Why this shape

One Python process serves the UI, the API and both sockets on one port (fewer moving parts on demo day). Local
models run on the CPU next to the data they need (frames, microphone audio); only text and speech segments leave
the machine, each to the one service that needs it. The reference project (AzIAIBetter) contributed the design
language and the Fish Audio know-how; see EXTERNAL_DEPENDENCIES.md.
