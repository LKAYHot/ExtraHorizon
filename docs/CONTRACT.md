# ExtraHorizon — API & message contract (v2.3: calibrated emotions + voice + remote access + utility-coordination analysis)

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
| `GET  /api/coord/catalog` | the analysis' sources, rules and status (docs/ANALYSIS.md) |
| `POST /api/coord/analyze` | run / re-run the analysis for a session (no chat turn) |
| `GET  /api/coord/report?session_id=…` · `DELETE …` | the session's analysis on screen · close it |
| `POST /api/coord/recheck` | read one finding's two records again from the county's service |
| `GET  /api/coord/finding?session_id=…&id=F450` | one finding of the analysis on screen (also one the panel does not list) |

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
  "coord": {"enabled": true, "offline": false},   // the utility-coordination analysis (offline = TEST fixtures)
  "sessions": 1,
  "client": {"transport": "local|cloudflare|proxy|network"}   // how THIS request arrived
}
```

## `POST /api/chat` → Server-Sent Events

Request: `{"session_id": "…uuid…", "message": "Explain recursion to me.", "subject": "Computer Science", "analysis": false}`
(`message` 1–4000 chars; `subject` optional; `analysis: true` runs the utility-coordination analysis before the
answer — so does a message that asks for it, see below). HTTP errors before the stream: `422` with `{"code","message"}`
(e.g. `empty_message`).

| event | data |
|---|---|
| `meta` | `{request_id, source: "text"\|"voice", model, turn_no, voice: bool, user_message: {id, role, text, source, created}, assistant_message_id, emotion_context}` |
| `delta` | `{text}` — append to the answer (contains voice cues like `[smug]`) |
| `done` | `{assistant_message_id, finish_reason, ttft_ms, elapsed_ms, model, created, interrupted: false}` — committed to history |
| `interrupted` | same as `done` with `interrupted: true` — stopped by barge-in / stop; the partial answer is committed and marked |
| `error` | `{code, message, retryable}` — nothing committed |
| `focus` | the map follows the conversation: `{ids: ["F146"], total, label, project: uid|null, source: "question"|"tool"|"answer", report_id, findings: [finding objects the panel does not list], within?: true}` — at most 50 ids (`total` = how many matched); `within: true` = her answer picks one finding out of what the map already shows (the spotlight stays); a focus for another `report_id` than the panel's is dropped |
| `tool` | she looked something up (follow-up analysis turns): `{name: "find_findings"|"get_project"|"show_on_map"|"recheck_finding", summary}` — the summary names the filters and a non-default order ("DTPW · Paving · closest first"); the same look-up twice in a turn is one tag |
| `recheck` | a live re-check she ran: `{id: "F135", result: {…as POST /api/coord/recheck…}, report_id}` |
| `working` | `{what: "look-up", name}` every 5 s while a look-up runs (a live re-check reads the county's service) — keeps the stream alive; clients may ignore it |
| `analysis` | only in an analysis turn, before the first `delta`: `{state: "running"}` → `{state: "progress", phase, step, source?, title?, records?, message?}` (per layer read and per step; `phase: "waiting"` every 5 s while the county's service is slow) → `{state: "ready", report_id, findings, by_category, projects, plans, offline}` or `{state: "error", message}` (she then says plainly that it failed); `{state: "cancelled"}` when the turn ends before the analysis did (Stop, a newer question, an error) |

**Analysis turns** (docs/ANALYSIS.md §6). `run` (the analysis runs first): `analysis: true`, or — with no analysis
on screen — a message naming the utilities and asking where they overlap / to compare their plans (English or
Russian; ordinary tutoring questions never match), or — with one on screen — such a message asking for it *again*.
`context` (answered from the analysis on screen, no new run): with one on screen, a message about it (a finding or
project ID, the utilities, overlaps, the map, the county…). Anything else is an ordinary turn. `meta.analysis` =
`{mode: "run"|"context", report_id|null}` or `null`. Her prompt then holds the **fact sheet** (the only facts she may
state) and the report rules; `max_completion_tokens` is `EH_COORD_MAX_OUTPUT_TOKENS` (3000), the total time
`EH_COORD_LLM_TOTAL_TIMEOUT_S` (150 s), and only her first paragraph is voiced (up to the first line break).
In `context` turns she has **tools** (docs/ANALYSIS.md §6): the request offers `find_findings`, `get_project`,
`show_on_map`, `recheck_finding`; a round that asks for tools gets their results (`tool` events; `focus` / `recheck`
as they apply) and the next round continues her answer (at most 3 look-up rounds; the round after the third is sent
with `tool_choice: "none"`). After each round's results a short system note repeats the language rule right before
she answers. Finding IDs spoken as words are read ("F сто сорок шесть" = F146): the finding's details go into the
sheet, the ID is appended to her prompt, and a `focus` moves the map before she answers. The map then follows her
answer too: with nothing focused yet, the first finding she names; after a question or look-up focused several
findings, the first of *those* she names (`within`). Analysis answers are in English even to Russian questions,
unless the message itself asks for Russian ("по-русски", "на русском", "in Russian"): a question in Russian is followed
in her prompt by one more system message with the language rule.
`done.analysis` and `interrupted.analysis` = `{mode, report_id, live?: <the terminal analysis event>, tools?: [{name,
summary}], check: {ok,
checked, unknown: ["2426", "62", "March 5, 2027", "80%", "F999", …]}}` — the grounding check (numbers ≥ 10 and numbers
with units, dates in any common form, percentages, finding IDs; a number from a project's name or ID only in its
context) against the sheet; the same object is stored with the assistant message (`live` keeps the result card
after a reload). A report cut at the length limit ends with a visible note. A spoken analysis question runs the
analysis only once the final transcript confirms it.

`emotion_context` (also stored with the assistant message): `{available: true, dominant, strength, source: "camera"|"simulation", text, note, unchanged?}` or
`{available: false, reason, source, text, note: null}`. `note` is **the exact system message** added to the prompt;
`unchanged: true` = the same dominant expression as when the learner last spoke (the note then asks her not to comment again).

Error codes: `llm_not_configured`, `llm_auth`, `llm_forbidden`, `llm_model`, `llm_rate_limited`, `llm_timeout`,
`llm_unreachable`, `llm_upstream`, `llm_bad_request`, `llm_empty`, `llm_error`, `superseded` (a newer question of the
same session replaced this one), `reset`, `interrupted` (stopped before any text).

Timeouts: first token ≤ `EH_LLM_FIRST_TOKEN_TIMEOUT_S` (15 s), gap ≤ `EH_LLM_IDLE_TIMEOUT_S` (20 s), whole answer ≤
`EH_LLM_TOTAL_TIMEOUT_S` (60 s); the browser runs its own idle watchdog.

**Sent to the LLM:** the persona prompt, up to 10 previous exchanges (text only), the expression note (when
available), the per-turn reply rules, the question; in analysis turns the fact sheet (public county records — never
their contact e-mails or phone numbers). Never images, landmarks, probabilities or camera numbers.

## `POST /api/session/interrupt` · `POST /api/session/reset` · `GET /api/session/{id}/state`

* interrupt: `{"session_id"}` → `{"ok": true, "stopped": bool}` — same effect as the stop button on the live socket.
* reset: `{"session_id"}` → `{"ok": true, "epoch": 3, "boot_id": "…"}` — clears history, emotion engine, timeline,
  stops the voice and cancels a turn in flight; both sockets get `reset` + `snapshot`. Idempotent.
* state: `{session_id, boot_id, epoch, subject, messages: [...], timeline, emotion}`; messages are
  `{id, role, text, source, created, model?, ttft_ms?, emotion_context?, interrupted?, analysis?}`.
  Reset also forgets the session's analysis and its rules.

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
{"type": "stt_ignored", "utt": 3, "turn_no": 5, "reason": "empty|echo|stop|stopped|backchannel", "text": "Wait, stop."}   // stopped: Stop/barge-in/reset came first; backchannel: "okay"/"угу" while her analysis report is written silently
{"type": "turn", "event": "meta|analysis|focus|tool|recheck|delta|done|interrupted|error|dropped", "turn_no": 5, "data": {…as in SSE…}}  // dropped: {reason: "merged|discarded|stopped"} — remove the turn (it was never heard)
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

## Utility-coordination analysis (`/api/coord/*`, docs/ANALYSIS.md)

Errors: `404 analysis_disabled` (`EH_COORD_ENABLED=false`), `404 no_analysis`, `404 no_finding`,
`409 session_reset` (the session was reset while the analysis ran), `422 bad_session_id` / validation,
`502 analysis_source` (no project layer of the county could be read and no copy exists).

While her analysis report is still being written after the spoken summary, the learner's voice on `/api/live` is
not a barge-in: a listening noise ("okay", "угу") is ignored (`stt_ignored`, reason `backchannel`); a real question
ends the report as `interrupted` (the written part kept and grounding-checked) and is answered.

* `GET /api/coord/catalog` → `{region, publisher, status: {enabled, offline, sources, loaded_at}, sources: [{key, title,
  kind, utility, url, item_url}], conflicts: {key, title, url, item_url}, defaults: {distance_m, window_days, area_m}}`.
* `POST /api/coord/analyze {"session_id", "refresh"?: bool, "distance_m"?: 0–5000, "window_days"?: 0–3650, "area_m"?: >0–20000}`
  → the report (rules given here are remembered for the session's later runs — only once they produced an analysis);
  it becomes the analysis on screen.
* `GET /api/coord/report?session_id=…` → the analysis on screen · `DELETE` → `{"ok": true}` (answers go back to normal).
* `POST /api/coord/recheck {"session_id", "finding_id": "F12"}` → `{finding, checked_at, ok, records: [{uid, found,
  changed: ["status", "end", "no longer passes the checks: <reason>", …], live: {project_id, status, start, end, parts},
  record_url} | {uid, found: false, error: "record no longer published" | "HTTP 503" …}], distance_m_live?,
  distance_matches?}` (a record the service did not answer for means "could not re-check", not "changed") — both projects are read again **by
  project ID** (the county republishes its layers; object IDs change), verified again like the analysis, parts merged.
  Links (`record_url`, `county.record_url`) are query pages by project ID too.

The report:

```jsonc
{"id": "3f9c…", "generated_at": "2026-09-26T15:41:02+00:00", "generated_at_local": "2026-09-26 11:41 (UTC−04:00)",
 "offline": false,                      // true = the synthetic TEST fixtures (EH_COORD_OFFLINE_DIR), labelled everywhere
 "stale_note": null | "UtilCoordWater: live read failed (…); using the copy read at …",
 "region": {"name", "center": [lat, lon], "bbox": [w, s, e, n], "check": "the county's boundary" | "a bounding box"},
 "publisher": "Miami-Dade County (ArcGIS account MDPublisher)",
 "params": {"distance_m": 150, "window_days": 60, "area_m": 1500, "today": "2026-09-26"},
 "sources": [{"key", "title", "kind", "url", "item_url", "utility", "reported", "received", "candidates", "verified",
              "excluded": [{"code", "count", "label"}], "notes": [{"code", "count", "label"}],
              "checks": [{"code": "publisher|https|schema|complete|fresh", "ok", "detail"}], "last_edit", "fetched_at", "error"}],
 "conflicts_source": {"key", "title", "url", "item_url", "reported", "received", "error", "last_edit", "checks": [...]},
 "boundary_source": {"key": "MiamiDadeBoundary", "title", "url", "item_url", "error", "last_edit", "checks": [... "reference"]},
 "plans": [{"key", "label": "WASD · Water", "agency", "facility", "kind", "utility", "count"}],
 "summary": {"records_reported", "records_received", "records_excluded", "records_passed", "records_merged",
             "projects_verified", "excluded": [{"code", "count", "label"}], "findings", "by_category": {"both", "near", "same_time"}, "plans"},
 "crosscheck": {"county_pairs", "our_intersecting", "our_intersecting_confirmed", "our_intersecting_not_listed",
                "county_pairs_between_verified_projects", "county_pairs_we_also_flag", "county_pairs_same_project",
                "county_pairs_we_do_not_flag": [...], "county_pairs_we_do_not_flag_count",
                "county_pairs_with_excluded_project": {"<reason>": n},    // a pair with two excluded projects counts twice …
                "county_pairs_with_excluded_project_total"},              // … each pair once here
 "pairs": [{"plans": ["FDOT · Roadway", "WASD · Water"], "total", "both", "near", "same_time"}],
 "highlights": ["F1", "F2", …],        // what her fact sheet leads with
 "findings": [{"id": "F1", "a": "<uid>", "b": "<uid>", "plans": [a, b], "category": "both|near|same_time",
               "distance_m", "shared_area_m2",
               "overlap_days",        // > 0: days both are scheduled (end dates count); ≤ 0: −(days between them), 0 = back to back
               "gap_days", "window": [start, end] (nulls when apart),
               "reasons": [...], "actions": [...], "score", "geometry": {GeoJSON}, "county": {"listed", "object_id", "record_url"}}],
 "findings_total": 583,               // "findings" lists the 300 strongest + the 25 best of every pair + every highlighted one;
                                      // all of them stay on the server for her tools (never in a response)
 "projects_index": [{"uid", "source", "object_id", "project_id", "name", "scope", "agency", "agency_short", "facility",
                     "kind", "plan", "plan_short", "status", "agency_status", "start", "end", "updated",
                     "record_url", "notes", "parts"}],     // no contact data
 "projects_geojson": {"type": "FeatureCollection", "features": [{"id": uid, "geometry", "properties": {"uid", "plan", "kind"}}]}}  // simplified to 3 m
```

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
