# ExtraHorizon — architecture

```
┌──────────────────────── Browser tab (SvelteKit SPA, Svelte 5) ────────────────────────┐
│ Sidebar: brand · New session/Reset · Adaptive Tutor · subject · status                 │
│ Chat: fetch POST /api/chat → SSE (meta/delta/done/error) · idle watchdog · Retry/Stop   │
│       "Explain differently" (only when the engine offered an event) · Why it adapted   │
│ Vision panel: camera preview (mirrored) + face box · signal meter · event · timeline   │
│       · Demo simulation mode (labelled) · signal details · privacy card                │
│ getUserMedia → OffscreenCanvas 480 px → JPEG → [seq|jpeg] binary WS message            │
└────────────────────────────┬──────────────────────────────▲─────────────────────────────┘
          localhost only     │ WS /api/vision               │ tick / event / marker / snapshot
                             ▼                              │
┌────────────────────────── Python process (FastAPI + uvicorn) ───────────────────────────┐
│ OriginGuard + TrustedHost (no cross-site driving of the tutor / camera socket)          │
│ VisionConnection: receiver (latest-frame-wins) → processor → sender (single writer)     │
│   └ FaceAnalyzer (MediaPipe, thread pool) → assess_quality → ConfusionProxy ─┐           │
│ SessionStore (per tab, in memory, TTL/LRU)                                  ▼           │
│   Session: StateEngine (EMA · hold · cooldown · relief) · events/offers · timeline      │
│            chat history · plan_chat → context.build_messages → commit on done           │
│ POST /api/chat → _chat_stream: first-token/idle/total timeouts, cancel on disconnect,   │
│                  supersede/reset, commit only after `done`                              │
│ Serves frontend/build (demo mode) · GET /api/health · POST /api/session/reset           │
└───────────────────────────────────────┬─────────────────────────────────────────────────┘
                                        │ HTTPS: chat text + abstract adaptation note only
                                        ▼
                         OpenAI Chat Completions (streaming) — gpt-6-luna (fallback gpt-5.5)
```

## Data flow of the key chain

1. **Camera → local signal.** The browser keeps one frame in flight; the backend analyses
   it in a worker thread (≈7 ms), gates quality, updates the per-session proxy and engine,
   and answers with a `tick` (vision section + engine section). The next frame is sent
   after that ack (≤ 12 fps). Frames are never queued, stored or forwarded.
2. **Stable event.** The engine fires `possible_confusion` after 2 s above 0.65 (time-based),
   attaches it to the latest answer (`answer_id`) and starts a 15 s cooldown. The event and
   a timeline marker go to the socket.
3. **Context.** "Explain differently" posts `{mode: explain_differently, event_id}`. The
   session validates the event (same session, still offered, belongs to the latest answer,
   not expired), picks the next strategy for that answer chain and builds the messages:
   system prompt · history · **adaptation note** (no numbers) · "Can you explain that differently?".
4. **Visibly different answer.** Streamed back via SSE; on `done` the exchange is committed,
   the event is marked used, an `adapted` marker is added and a 60 s "decrease" watch starts.
5. **Why it adapted.** The `meta` event carries the real signal values, the rule, the
   strategy and the exact note — the UI renders them; the numbers never go to the LLM.

## Failure handling

| Failure | Behaviour |
|---|---|
| Camera denied / missing / busy / unplugged | camera status in UI, banner "Vision unavailable — chat still works", engine `unknown` |
| No / several faces, bad light, head turned | `unknown` with reason, hold reset, gaps in the timeline |
| Vision model missing / MediaPipe broken | `/api/health` vision unavailable; socket says so; chat unaffected |
| Tab hidden | frames paused (`camera: paused`), engine unknown |
| WebSocket drop | engine marks `unknown` (`vision_disconnected`), UI shows "—" instead of a frozen value; exponential reconnect (0.5 → 5 s); state restored from `snapshot` |
| Camera ready before the server's `hello` (refresh with remembered consent) | the frame loop (re)starts on `hello` |
| Camera toggled while permission is pending | stale `getUserMedia` results are stopped immediately (request token) |
| OpenCV / NumPy / MediaPipe broken on the machine | chat unaffected — the analyzer module is imported lazily only for a camera session |
| Duplicated tab | detects the live owner of its session id (BroadcastChannel) and takes a new session |
| Backend restart | new `boot_id` → tab clears its view with a toast; sessions start fresh |
| Missing key / 401 / 404 / 429 / 5xx / network | SSE `error` with code + message; UI error card with Retry |
| LLM too slow / stalls | first-token 15 s, idle 20 s, total 60 s → `llm_timeout`; client watchdog 25 s |
| Client disconnects mid-answer | server cancels the upstream stream; nothing committed |
| Second tab with the same session | newer socket supersedes the older ("Use here" button) |

## Why no Go service

The spec (§3) keeps a Go service out of the critical path. The reference project
(AzIAIBetter) contributed its **design language** (matte material, depth, sheen, grain,
motion rules); its Go UI server was not needed because FastAPI serves the built UI in the
same process — one process, one port, fewer moving parts on demo day.
