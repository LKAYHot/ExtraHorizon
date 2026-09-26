# ExtraHorizon — API & message contract (v2.2: calibrated emotions + voice + remote access)

The single source of truth for everything that crosses the frontend ⇄ backend boundary.
Change it **first**, then both sides, then the tests (`backend/tests/test_api.py`,
`test_live.py`, `frontend/src/lib/*.test.js`, `frontend/e2e`).

All routes live under `/api`. In dev the Vite server proxies `/api` (HTTP + WS) to the backend;
in the demo build FastAPI serves the UI and the API from one origin.

| Route | Purpose |
|---|---|
| `GET /api/access` · `POST /api/access` · `DELETE /api/access` | remote access: status · log in with the key · log out |
| `GET  /api/health` (`?deep=1` also pings the LLM) | status of every component |
| `POST /api/chat` → `text/event-stream` | a typed question (also spoken on the live socket if open) |
| `POST /api/session/interrupt` | stop button without the live socket |
| `POST /api/session/reset` | new session |
| `GET  /api/session/{session_id}/state` | restore the view after a refresh |
| `WS   /api/vision?session_id=…` | camera frames → expression estimates |
| `WS   /api/live?session_id=…` | the voice conversation (mic in, voice out) |

## Sessions

* A session id is a lowercase UUID created by the browser tab (`sessionStorage` → survives a refresh; a new tab
  gets a new session; a duplicated tab detects the live owner over a `BroadcastChannel` and takes a fresh id).
* Sessions live **in memory only** (idle TTL, LRU cap) and own: the emotion engine, timeline, chat history, the
  turn in flight, the voice being spoken, the simulation flag. Sessions never share state.
* `boot_id` changes on every backend start; a client that sees a new one clears its local view.
* One vision socket and one live socket per session: a newer socket supersedes the older one
  (`{"type":"superseded"}`, close code 4001). When the vision socket closes the expression becomes *unknown*
  (`vision_disconnected`) and simulation is switched off; when the live socket closes a spoken turn in flight is cancelled.
* Host/Origin: loopback names always, plus the host of `EH_PUBLIC_URL`; other machines only via explicit
  `EH_ALLOWED_HOSTS` + `EH_ALLOWED_ORIGINS` (never `*`). Cross-site HTTP gets 403; cross-site WebSockets are refused.

## Remote access (`/api/access`, docs/REMOTE_DEMO.md)

* **Transport** of a request: `local` (loopback peer, no proxy header, loopback `Host`) · `cloudflare`
  (`CF-Connecting-IP`/`CF-Ray` present — Cloudflare Tunnel's requests also arrive from 127.0.0.1) · `proxy`
  (`X-Forwarded-For`/`X-Real-IP`/`Forwarded`) · `network` (another machine directly).
* Every non-`local` request to `/api/*` (except `/api/access`) and both WebSockets need the access cookie:
  HTTP → `401 {"code":"access_required"}`; WebSocket → closed before accept (code 4401; browsers see 1006).
  Without `EH_ACCESS_KEY` on the server: `403 {"code":"remote_disabled"}` / close 4403. Static UI files stay public.
* `GET /api/access` → `{"required": bool, "ok": bool, "configured": bool, "transport": "local|cloudflare|proxy|network", "public_url": "https://…"|null}`.
* `POST /api/access {"key": "…"}` (same origin) → `200` + `Set-Cookie: eh_access=v1.<issued>.<HMAC>; HttpOnly; Secure (https);
  SameSite=Strict; Max-Age=14 days` · `401 wrong_key` · `429 too_many_attempts {retry_after_s}` + `Retry-After`
  (8 wrong keys per client, 60 overall, per 10 min) · `403 remote_disabled`. A local request gets `ok` without a cookie.
* `DELETE /api/access` → clears the cookie.

## `GET /api/health`

```json
{
  "status": "ok", "boot_id": "b1c9…", "version": "0.2.0", "persona": "Rika",
  "llm":    {"provider": "openai", "model": "gpt-6-luna", "configured": true, "reachable": null, "last_error": null},
  "vision": {"available": true, "reason": null, "model": "face_landmarker.task", "emotion_model": "enet_b0_8_va_mtl.onnx"},
  "emotion": {"sensitivity": "balanced", "alpha": 0.2, "reference_fps": 10.0, "switch_hold_s": 1.0,
              "switch_margin": 0.12, "min_prob": 0.42, "calibration_s": 2.5},   // server defaults (EH_EMOTION_*)
  "tts":    {"provider": "fish", "model": "drama-3-preview", "voice": "c5d8…", "configured": true,
             "state": "ok|degraded|down|off", "last_error": null, "warm": 1},
  "stt":    {"provider": "openai", "model": "gpt-live-transcribe", "configured": true, "vad": true, "vad_reason": null},
  "fillers": "idle|preparing|ready|failed",
  "sessions": 1,
  "client": {"transport": "local|cloudflare|proxy|network"}   // how THIS request arrived
}
```

## `POST /api/chat` → Server-Sent Events

Request: `{"session_id": "…uuid…", "message": "Explain recursion to me.", "subject": "Computer Science"}`
(`message` 1–4000 chars; `subject` optional). HTTP errors before the stream: `422` with `{"code","message"}`
(e.g. `empty_message`).

| event | data |
|---|---|
| `meta` | `{request_id, source: "text"\|"voice", model, turn_no, voice: bool, user_message: {id, role, text, source, created}, assistant_message_id, emotion_context}` |
| `delta` | `{text}` — append to the answer (contains voice cues like `[smug]`) |
| `done` | `{assistant_message_id, finish_reason, ttft_ms, elapsed_ms, model, created, interrupted: false}` — committed to history |
| `interrupted` | same as `done` with `interrupted: true` — stopped by barge-in / stop; the partial answer is committed and marked |
| `error` | `{code, message, retryable}` — nothing committed |

`emotion_context` (also stored with the assistant message): `{available: true, dominant, strength, source: "camera"|"simulation", text, note, unchanged?}` or
`{available: false, reason, source, text, note: null}`. `note` is **the exact system message** added to the prompt;
`unchanged: true` = the same dominant expression as when the learner last spoke (the note then asks her not to comment again).

Error codes: `llm_not_configured`, `llm_auth`, `llm_forbidden`, `llm_model`, `llm_rate_limited`, `llm_timeout`,
`llm_unreachable`, `llm_upstream`, `llm_bad_request`, `llm_empty`, `llm_error`, `superseded` (a newer question of the
same session replaced this one), `reset`, `interrupted` (stopped before any text).

Timeouts: first token ≤ `EH_LLM_FIRST_TOKEN_TIMEOUT_S` (15 s), gap ≤ `EH_LLM_IDLE_TIMEOUT_S` (20 s), whole answer ≤
`EH_LLM_TOTAL_TIMEOUT_S` (60 s); the browser runs its own idle watchdog.

**Sent to the LLM:** the persona prompt, up to 10 previous exchanges (text only), the expression note (when
available), the per-turn reply rules, the question. Never images, landmarks, probabilities or numbers.

## `POST /api/session/interrupt` · `POST /api/session/reset` · `GET /api/session/{id}/state`

* interrupt: `{"session_id"}` → `{"ok": true, "stopped": bool}` — same effect as the stop button on the live socket.
* reset: `{"session_id"}` → `{"ok": true, "epoch": 3, "boot_id": "…"}` — clears history, emotion engine, timeline,
  stops the voice and cancels a turn in flight; both sockets get `reset` + `snapshot`. Idempotent.
* state: `{session_id, boot_id, epoch, subject, messages: [...], timeline, emotion}`; messages are
  `{id, role, text, source, created, model?, ttft_ms?, emotion_context?, interrupted?}`.

## `WS /api/vision?session_id=…`

Client → server:

* **binary** — one camera frame: 4-byte big-endian `seq` + JPEG (≤ 512 KB). The client keeps one frame in flight
  (next after the `tick` with the same `seq`, or 1.5 s), capped at `max_fps`; the server keeps only the latest pending frame.
* `{"type":"camera","status":"active|off|initializing|denied|unavailable|ended|paused"}` — frames are used only while `active`.
* `{"type":"sim","enabled":true,"emotion":"happiness","intensity":0.8}` (10 Hz while on) · `{"type":"sim","enabled":false}` — labelled Demo simulation.
* `{"type":"calibrate"}` — learn the learner's relaxed face again (Recalibrate button).
* `{"type":"sensitivity","level":"calm|balanced|expressive"}` — sent on every connect (the learner's choice wins over
  the server default) and when changed; unknown levels are ignored.
* `{"type":"ping","t":…}` — the browser sends one every 20 s (proxies close silent WebSockets after ~100 s).

Server → client:

```jsonc
{"type": "hello", "session_id": "…", "boot_id": "…", "server_time": 1790…, "client_is_loopback": true,
 "transport": "local|cloudflare|proxy|network",   // client_is_loopback = transport is "local"
 // config: a remote browser gets max_fps ≤ EH_REMOTE_MAX_FPS (8) and jpeg_quality ≤ EH_REMOTE_JPEG_QUALITY (0.7)
 "vision": {"available": true, "reason": null, "model": "…", "emotion_model": "…"},
 "config": {…health emotion…, "max_fps": 12, "frame_width": 480, "jpeg_quality": 0.8}}
{"type": "snapshot", "epoch": 3, "timeline": {...}, "emotion": {...}|null, "context": {...}, "sim": {"enabled": false},
 "calibration": {"state": "collecting|ready", "progress": 0.4, "sensitivity": "balanced"}}
{"type": "tick", "seq": 42|null, "t": 1790…,
 "vision": {"faces": 1, "boxes": [[x, y, w, h]], "pose": {"yaw": 1.4, "pitch": 4.7, "roll": 0.8}, "brightness": 121.0,
            "raw": {"probs": {"anger": 0.01, …}, "valence": 0.2, "arousal": 0.1} | null,   // the model as is, before calibration
            "proc_ms": 14.2, "emotion_ms": 6.1, "quality": "ok|unknown", "reason": null|"no_face|multiple_faces|face_too_small|head_turned|too_dark|overexposed|bad_frame|no_emotion_estimate",
            "used_by_engine": true,
            "calibration": {"state": "collecting|ready", "progress": 1.0, "sensitivity": "balanced"},  // absent while simulating
            "weight": 0.64, "actions": ["frowning, brows pulled down"]} | null,  // weight/actions: only once calibrated
 "emotion": {"source": "camera|simulation", "status": "ok|unknown|calibrating", "reason": null|"calibrating"|"…",
             "probs": {"anger": 0.02, …, "surprise": 0.05} | null, "valence": 0.31 | null, "arousal": 0.12 | null,
             "dominant": "happiness" | null, "dominant_prob": 0.62 | null, "dominant_for_s": 4.2} | null,
 "calibration": {…}}   // top-level only on the tick answering {"type":"calibrate"} (vision: null, emotion: calibrating)
{"type": "calibration", "calibration": {"state": "ready", "progress": 1.0, "sensitivity": "calm"}}   // answer to "sensitivity"
{"type": "emotion_note", "context": {"available": true, "dominant": "happiness", "strength": "mostly", "source": "camera", "text": "…", "note": "[What you see on the learner's webcam right now] …"}}   // only when the words change
{"type": "marker", "marker": {"t": 1790…, "kind": "emotion|answer", "label": "happy|Answer|Interrupted", "ref": "happiness|m_…"}}
{"type": "assistant_interrupted", "message_id": "m_…"}
{"type": "reset", "epoch": 4}
{"type": "superseded"}
{"type": "error", "code": "vision_unavailable|vision_busy|bad_frame|frame_too_large|bad_message", "message": "…"}
{"type": "pong", "t": 123}
```

Timeline: `{"samples": [[t_ms, status, source, dominant|null, probs[8]|null, valence|null, arousal|null], …], "markers": [...]}`;
`probs` in the model's class order `anger, contempt, disgust, fear, happiness, neutral, sadness, surprise`.
Unknown and calibrating samples have `probs: null` (a gap, never zeros).

## `WS /api/live?session_id=…`

Client → server:

* **binary** — microphone audio, PCM16 little-endian mono **24 kHz**, any frame size (the UI sends 40 ms).
* `{"type":"mic","on":true|false}` — voice mode on/off (connects/closes speech-to-text; audio is ignored while off).
* `{"type":"voice_out","on":true|false}` — speak answers (Fish Audio) or text only.
* `{"type":"playback","playing":true|false}` — the browser is (not) playing tutor audio (barge-in rules apply while true).
* `{"type":"interrupt"}` — stop button. · `{"type":"ping","t":…}`.

Server → client:

```jsonc
{"type": "hello", "boot_id": "…", "persona": "Rika", "fillers": "ready", "vad": true,
 "config": {"input_sample_rate": 24000, "output_sample_rate": 44100, "barge_in": true, "vad_end_silence_ms": 550, "merge_window_s": 3.0},
 "tts": {…health tts…}, "stt": {"provider": "openai", "model": "gpt-live-transcribe", "configured": true}}
{"type": "vad", "speaking": true, "utt": 3, "continues": 2|null, "barge": false}   // continues: joins the paused sentence
{"type": "vad", "speaking": false, "utt": 3, "turn_no": 5}
{"type": "stt", "utt": 3, "text": "Explain recursion", "final": false}             // live transcript of one utterance
{"type": "heard", "utt": 3, "turn_no": 5, "text": "Explain recursion to me."}      // the whole question (joined)
{"type": "stt_ignored", "utt": 3, "turn_no": 5, "reason": "empty|echo|stop|stopped", "text": "Wait, stop."}   // stopped: Stop/barge-in/reset came first
{"type": "turn", "event": "meta|delta|done|interrupted|error|dropped", "turn_no": 5, "data": {…as in SSE…}}  // dropped: {reason: "merged|discarded|stopped"} — remove the turn (it was never heard)
{"type": "filler", "turn_no": 5, "text": "Hmm..."}
{"type": "audio_begin", "turn_no": 5, "kind": "filler|answer", "sample_rate": 44100}
// binary: 4-byte big-endian turn_no + PCM16LE mono audio of that turn (a filler and its answer share the turn number)
{"type": "audio_end", "turn_no": 5, "failed": null|"…"}
{"type": "audio_stop", "turn_no": 5}          // stop playing this turn now; later frames of it are never sent
{"type": "barge_in", "by": "voice|button"}   // stop everything now
{"type": "assistant_interrupted", "message_id": "m_…"}
{"type": "stt_error"|"tts_error", "message": "…"} · {"type": "error", "code": "vad_unavailable|stt_unavailable|bad_message", "message": "…"}
{"type": "superseded"} · {"type": "reset", "epoch": 4} · {"type": "snapshot", …} · {"type": "pong", "t": …}
```

Player rules (browser): frames of the current turn are scheduled back to back; a frame with a newer turn number
cuts the older turn; frames of a stopped or older turn are dropped; `barge_in` stops everything.

## Emotion engine (single place that decides the expression)

```
input      : 8 class probabilities + logits + valence/arousal per frame (camera: upright square face crop, averaged
             with its mirror image) + 52 blendshapes + head pose; or per tick (labelled simulation, no calibration)
unknown    : no face | >1 face | small face | head turned | too dark/bright | bad frame | no estimate
             | camera off/paused | vision socket closed | gap > max_gap_s (1 s)
             → probs = null, dominant = null, smoothing restarts (never "neutral")
calibrate  : per session, the first ~2.5 s (≥ 15 frames) of a relaxed face → baseline (medians of logits, VA,
             blendshapes, pose); frames while the learner talks / jaw open / head turned are skipped (until 8 s);
             status "calibrating" meanwhile; {"type":"calibrate"} or 90 s without a face → learn again
gain       : g_k = (z_k − z_neutral) − (zb_k − zb_neutral)   per class, since the relaxed face (log-odds)
neutral    : P(neutral) = σ(m_rest − Σ_k p_k·max(0, g_k) + pose bonus + talk bonus)
             m_rest = logit(p_ref) (+ half of the relaxed face's extra neutrality, if any); p_k = the raw probabilities;
             pose bonus 0.1 per degree of pitch beyond 5° / 0.06 per degree of yaw beyond 8°, ≤ 1; talk bonus 0.5
which      : the other 1 − P(neutral) is shared by p_k · σ((g_k − 0.5)/0.5) · hallmark_k — the face as it reads now,
             among classes that gained on neutral; hallmark_k (0.35/0.5 … 1) = its FACS-style facial actions relative
             to the relaxed face (disgust: upper lip / nose; happiness: smile; surprise: brows / eyes / jaw; …;
             anger: none) — it only moves probability between expressions, never into neutral
va         : v' = v − P(neutral)·(v_base − 0), a' = a − P(neutral)·(a_base + 0.1)
weight     : head pose vs the calibration pose (1 within ±6° pitch / ±8° yaw → 0.1 at ~24° / 30°),
             × 0.5 while the learner talks; the smoothing step is scaled by it
adapt      : the baseline follows drift (τ 60 s) only while the classifier reads the face like the relaxed face
             (intensity < 0.3, near the calibration pose, silent), at most 1 log-odds per class / 0.25 per blendshape /
             12° / 0.3 VA away from the calibrated face; frames with non-finite model output never reach it
smooth     : per class EMA, time-based: a = (1 − (1 − α)^(Δt·reference_fps)) · weight
dominant   : a non-neutral expression needs ≥ min_prob; a new leader must lead for ≥ switch_hold_s by
             ≥ switch_margin; a faded expression returns to neutral
presets    : calm       p_ref 0.95, α 0.15, hold 1.6 s, margin 0.15, min_prob 0.50
             balanced   p_ref 0.90, α 0.20, hold 1.0 s, margin 0.12, min_prob 0.42   (default)
             expressive p_ref 0.85, α 0.30, hold 0.8 s, margin 0.08, min_prob 0.32
note       : words only, phrased as her own view on the call — "[What you see on the learner's webcam right now]
             The learner looks clearly angry. Visible right now: baring teeth. …" (strength: clearly/mostly/somewhat;
             visible actions only if they fit the reported expression, plus head pose; mood: positive/neutral/negative +
             energy; the previous expression and roughly when) — no digits
```
