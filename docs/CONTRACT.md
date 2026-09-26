# ExtraHorizon — API & message contract (v1)

This is the single source of truth for everything that crosses the
frontend ⇄ backend boundary. Change it **first**, then both sides, then the tests
(`backend/tests/test_api.py`, `frontend/src/lib/*.test.js`, `frontend/e2e`).

All routes live under `/api`. In dev the Vite server proxies `/api` (HTTP + WS)
to the backend; in the demo build FastAPI serves the UI and the API from one origin.

| Spec name (task)      | Implemented route                          |
|-----------------------|--------------------------------------------|
| `GET  /health`        | `GET  /api/health` (`?deep=1` also pings the LLM) |
| `POST /chat`          | `POST /api/chat` → `text/event-stream`     |
| `WS   /vision`        | `WS   /api/vision?session_id=…`            |
| `POST /session/reset` | `POST /api/session/reset`                  |
| (restore on refresh)  | `GET  /api/session/{session_id}/state`     |

## Sessions

* A session id is a lowercase UUID created by the browser tab
  (`crypto.randomUUID()`, kept in `sessionStorage` → survives refresh, a new tab
  gets a new session). The backend creates sessions lazily and keeps them **in
  memory only** (idle TTL, LRU cap). Nothing is written to disk.
* Every session owns its own: state engine (EMA, hold timer, cooldown),
  calibration baseline, chat history, events, timeline, simulation flag.
  Sessions never share state.
* `boot_id` changes on every backend start. If the client sees a new `boot_id`
  it knows server-side state is gone and clears its local view.
* Only one vision socket per session: a newer socket supersedes the older one
  (`{"type":"superseded"}`, close code 4001). When the last socket of a session closes,
  the engine records `unknown` (`vision_disconnected`) and simulation is switched off.
* A duplicated browser tab (which copies `sessionStorage`) detects the live owner of its
  id over a `BroadcastChannel` and takes a fresh id.
* Host/Origin: loopback names always; other machines only via explicit
  `EH_ALLOWED_HOSTS` + `EH_ALLOWED_ORIGINS` (never `*`, which would allow DNS rebinding).

## `GET /api/health`

```json
{
  "status": "ok",
  "boot_id": "b1c9…",
  "version": "0.1.0",
  "llm":    {"provider": "openai", "model": "gpt-6-luna", "configured": true,
             "reachable": null, "last_error": null},
  "vision": {"available": true, "reason": null, "model": "face_landmarker.task"},
  "engine": {"alpha": 0.2, "reference_fps": 10, "threshold": 0.65, "hold_s": 2.0,
             "cooldown_s": 15.0},
  "sessions": 1
}
```
`reachable` is `null` unless `?deep=1` (then `true|false`, one cheap model lookup,
5 s timeout). `provider: "mock"` means the explicitly-labelled offline scripted
tutor used for tests/rehearsal — the UI shows a *Mock LLM* badge.

## `POST /api/chat` → Server-Sent Events

Request (JSON):
```json
{"session_id": "…uuid…", "mode": "normal", "message": "Explain recursion to me.",
 "subject": "Computer Science"}
{"session_id": "…uuid…", "mode": "explain_differently", "event_id": "ev_…"}
```
* `normal` requires `message` (1–4000 chars).
* `explain_differently` requires an `event_id` of a `possible_confusion` event
  from the **same session** that is still `offered` and fired after the latest
  answer started. Otherwise `409` with `{"code": "no_active_event" | …}`.
* HTTP errors before the stream starts: `400/404/409/422` with
  `{"code": "...", "message": "..."}`.

Stream events (`event: <name>\ndata: <json>\n\n`):

| event   | data |
|---------|------|
| `meta`  | `{request_id, mode, model, user_message: {id, role, text, mode}, assistant_message_id, adaptation}` — `adaptation` is `null` for normal turns, otherwise `{event_id, strategy: {id,label,description}, signal: {source, smoothed, raw, held_s}, rule: {alpha, threshold, hold_s, cooldown_s}, instruction}` |
| `delta` | `{text}` — append to the answer |
| `done`  | `{assistant_message_id, finish_reason, ttft_ms, elapsed_ms, model}` — the exchange is now committed to history |
| `error` | `{code, message, retryable}` — stream ends; **nothing** is committed; the client shows *Retry* |

Error codes: `llm_not_configured`, `llm_auth`, `llm_forbidden`, `llm_model`,
`llm_rate_limited`, `llm_timeout`, `llm_unreachable`, `llm_upstream`,
`llm_bad_request`, `llm_error`, `superseded` (a newer request of the same session
replaced this one), `reset` (session was reset mid-stream).

Timeouts (config): first token ≤ `EH_LLM_FIRST_TOKEN_TIMEOUT_S` (15 s), gap
between chunks ≤ `EH_LLM_IDLE_TIMEOUT_S` (20 s), whole answer ≤
`EH_LLM_TOTAL_TIMEOUT_S` (60 s). The browser also runs its own idle watchdog, so
the UI can never stay in "thinking" forever.

**What is sent to the LLM provider:** system prompt, the session's previous
chat turns (text only), the new user text, and — only for `explain_differently`
— one short *adaptation note* (no numbers, no images, no landmarks).

## `POST /api/session/reset`

`{"session_id": "…"}` → `{"ok": true, "epoch": 3}`. Clears history, events,
timeline, engine (EMA, hold, cooldown), calibration baseline and cancels an
in-flight answer. The vision socket (if any) receives `reset` + `snapshot`.
Idempotent.

## `GET /api/session/{session_id}/state`

`{"session_id", "epoch", "boot_id", "subject", "messages": [...], "events": [...], "timeline": {...}}`
used to restore the view after a page refresh. Messages:
`{id, role: "user"|"assistant", text, mode, created, model?, adaptation?}`.

## `WS /api/vision?session_id=…`

Origin-checked, local only. Two kinds of client → server frames:

**Binary** — one camera frame: `4-byte big-endian uint32 seq` + `JPEG bytes`
(browser downsizes to `frame_width` px, JPEG quality `jpeg_quality`, ≤ 512 KB).
Flow control: the client keeps **one frame in flight** and sends the next one only
after the `tick` with the same `seq` (or a 1.5 s timeout), capped at `max_fps`.
The server additionally keeps only the latest pending frame (never queues).

**Text (JSON)**
```json
{"type": "camera", "status": "active|off|initializing|denied|unavailable|ended|paused"}   // paused = tab hidden; frames are ingested only while "active"
{"type": "sim", "enabled": true, "value": 0.8}     // Demo simulation mode (labelled in UI)
{"type": "sim", "enabled": false}
{"type": "calibrate"}                              // re-capture neutral baseline
{"type": "ping", "t": 123}
```

Server → client:

```jsonc
{"type": "hello", "session_id": "…", "boot_id": "…", "client_is_loopback": true,
 "vision": {"available": true, "reason": null},
 "config": {"alpha": 0.2, "reference_fps": 10, "threshold": 0.65, "hold_s": 2.0,
            "cooldown_s": 15, "max_fps": 12, "frame_width": 480, "jpeg_quality": 0.75,
            "calibration_s": 2.5}}

{"type": "snapshot", "epoch": 3, "events": [...], "timeline": {...}, "engine": {...}|null}

// one per processed frame and/or engine update
{"type": "tick", "seq": 42, "t": 1790394305123,
 "vision": {"faces": 1, "boxes": [[x, y, w, h]], "quality": "ok|unknown|calibrating",
            "reason": null, "pose": {"yaw": 1.4, "pitch": 4.7, "roll": 0.8},
            "brightness": 121.0,
            "features": {"brow_lower": 0.31, "lid_tighten": 0.2, "lip_press": 0.05, "smile": 0.02, "brow_raise_inner": 0.1},
            "baseline": {...}, "contrib": {...}, "proxy": 0.42,
            "calibration": {"progress": 0.4, "seconds": 2.5} | null,
            "proc_ms": 6.8, "used_by_engine": true} | null,
 "engine": {"source": "camera|simulation", "status": "ok|unknown|calibrating", "reason": null,
            "raw": 0.42, "smoothed": 0.38, "above": false, "held_s": 0.0, "hold_s": 2.0,
            "threshold": 0.65, "cooldown_left_s": 0.0, "armed": true} | null}

{"type": "event", "event": {"id": "ev_…", "kind": "possible_confusion|signal_decreased",
  "label": "Possible confusion detected", "t": 1790394305123, "source": "camera|simulation",
  "smoothed": 0.71, "raw": 0.74, "held_s": 2.03,
  "rule": {"alpha": 0.2, "reference_fps": 10, "threshold": 0.65, "hold_s": 2.0, "cooldown_s": 15},
  "answer_id": "m_…" | null, "status": "offered|used|expired|info"}}
{"type": "event_update", "event": {...}}                       // status change: used / expired
{"type": "marker", "marker": {"t": 1790394305123, "kind": "answer|event|adapted|decrease", "label": "…", "ref": "m_…|ev_…"}}
{"type": "calibrating"}                                          // ack of {"type": "calibrate"}
{"type": "reset", "epoch": 4}
{"type": "superseded"}
{"type": "error", "code": "vision_unavailable|bad_frame|frame_too_large|bad_message", "message": "…"}
{"type": "pong", "t": 123}
```

Timeline payload: `{"samples": [[t_ms, raw|null, smoothed|null, status, source], ...],
"markers": [{"t": t_ms, "kind": "answer|event|adapted|decrease", "label": "…", "ref": "…"}]}`
with `status ∈ {"ok","unknown","calibrating"}` and `source ∈ {"camera","simulation"}`.

## Engine rule (single place that decides adaptation)

```
input   : confusion proxy p ∈ [0,1] per observation (camera or labelled simulation)
unknown : no face | >1 face | small face | head turned | too dark/bright | bad frame
          | calibrating | camera off/paused | vision socket closed | gap > max_gap_s
          → smoothed = null, hold timer reset (never "neutral", never "confused")
smooth  : EMA, time-based: a = 1 − (1 − α)^(Δt·reference_fps)   (α = 0.2 @ 10 fps)
trigger : smoothed > threshold continuously for ≥ hold_s (wall-clock seconds)
          and not in cooldown and armed → ONE `possible_confusion` event, cooldown
          starts, hold accumulation paused during cooldown
episode : after an event the engine is disarmed until smoothed < rearm_threshold (0.55)
          or a new answer is committed — a face that just stays tense is not nagged
relief  : after an adapted answer, smoothed < relief_threshold for ≥ relief_hold_s
          (status ok) within relief_window_s → one informational `signal_decreased`
```
