# Test matrix

Status as of 2026-09-26 on the development machine (Windows 11, Python 3.14.7, Node 24,
Edge for the browser tests, OpenAI `gpt-6-luna`). "Agent" = checked by the coding agent
(Claude Code); items that need a person in front of a physical webcam are marked
**not tested** — they are the agenda of the final rehearsal (docs/PITCH.md).

## Automated tests

| Suite | Command | Result |
|---|---|---|
| Backend unit + integration (engine, context, API with fake LLM, vision incl. real MediaPipe on a portrait, secrets) | `cd backend && uv run pytest` | **72 passed** |
| Frontend unit (SSE parser, offer logic, loopback check, markdown XSS/remote-image safety, camera/socket controller races) | `cd frontend && npx vitest run` | **16 passed** |
| Svelte type/a11y check | `npx svelte-check --threshold warning` | **0 errors, 0 warnings** |
| Browser e2e — 4 virtual camera setups (face / two faces / no face / permission denied), consent gate, refresh, duplicated tab, optional auto-adapt; mock LLM, production build | `cd frontend && npm run e2e` | **9 passed** |
| Browser e2e — full demo scenario repeated | `npx playwright test --project face -g "question → answer" --repeat-each 10` | **10/10 passed** (≈13 s each) |
| Live chain against the running app + real OpenAI (answer → labelled simulated signal → exactly one event → adapted answer → reset) | `cd backend && uv run python scripts/demo_check.py --runs 10` | **10/10 passed** (final run) — median TTFT 0.64 s (adapted 0.65 s), event 2.14 s after the signal rose, 1 event per run, 0 % verbatim overlap, no camera/feelings mentions |

What the automated tests prove: the engine rules (spikes, sustained, time-based, cooldown,
reset on dip/unknown/gap/multi-face, isolation), the context builder (no note before an
event, strategy + previous answer after, no numbers/images/landmarks in the payload), the
chat failure paths (error, mid-stream failure, first-token hang, stall, missing key → clear
error, retry works, nothing half-committed), vision failures not breaking chat, reset, the
real browser camera path through MediaPipe (virtual camera showing a real face), the
camera-consent gate, refresh restore.

What they do **not** prove: that a real person's spontaneous (or deliberate) frown in venue
lighting crosses the threshold reliably. The confusion rise in the automated chains is the
labelled simulation input.

## Manual matrix

| # | Scenario | How it was checked | Result |
|---|---|---|---|
| 1 | Camera allowed | e2e with a virtual camera (Edge fake device playing a real face clip): Active → 1 face → calibrating → tracking, 11 fps, 68 ms round trip | **pass** (virtual device) |
| 1b | Camera allowed — physical webcam (Logi C270), live person | needs a person | **not tested** |
| 2 | Camera permission denied | browser pane (blocks camera) + e2e `denied`: status "Permission denied", banner "Vision unavailable — chat still works", chat answers | **pass** |
| 3 | No face | e2e `no-face` (synthetic pattern): "No face in view — signal unknown", meter "—", chat works | **pass** |
| 4 | Several faces | e2e `two-faces` + backend test: "2 faces — ambiguous, signal not used", engine unknown | **pass** |
| 5 | Camera switched off mid-session | e2e: Turn off → status off, engine "Camera is off" (a frame in flight no longer overwrites it — bug found and fixed), turn on again | **pass** |
| 5b | Camera physically unplugged mid-session | `track.ended` handler → status "Disconnected"; needs hardware | **not tested** |
| 6 | WebSocket dropped | backend killed with the UI open: banner "Backend offline — reconnecting…", socket reconnects with backoff after restart | **pass** |
| 7 | Backend restarted | UI detected the new `boot_id`, cleared the stale view, reconnected; chat sent while down showed "Cannot reach the backend… Retry" (no spinner) | **pass** |
| 8 | Missing API key | instance with empty key: health `configured: false`, chat → `llm_not_configured` in 67 ms, UI error card with the fix + Retry | **pass** |
| 9 | LLM timeout | instance with `EH_LLM_FIRST_TOKEN_TIMEOUT_S=0.05`: `llm_timeout` (retryable) in 136 ms, nothing committed; stall/hang variants covered by tests | **pass** |
| 10 | Page refresh | e2e: conversation of the tab restored from the server session | **pass** |
| 11 | Repeated reset | API test (reset twice) + UI | **pass** |
| 12 | 10 consecutive full runs | `demo_check.py --runs 10` (real OpenAI) and Playwright ×10 | **pass** (10/10 each) |
| 13 | Live frown → event → adapted answer with a real person | needs a person + webcam | **not tested** |
| 14 | Proxy calibration in venue light (`vision_probe.py`) | needs a person + webcam | **not tested** |

## Network / privacy checks

| Check | Result |
|---|---|
| Idle backend makes no outbound connections | **pass** (none observed after start-up) |
| OpenAI payload contains no image data, landmarks, blendshapes or signal numbers | **pass** (test + payload inspection) |
| MediaPipe native library contacts Google | **observed**: HTTPS to 172.217.115.4:443 ≈60 s into a landmarker session and on close. Disclosed in the consent card, privacy card, README and EXTERNAL_DEPENDENCIES.md; camera starts only after consent; no MediaPipe session at server start |
| Cross-site requests / foreign Host header | **pass** (403 / 400) |
| Key never committed | **pass** (`.gitignore`, pre-commit + pre-push hooks tested with a fake key, `test_secrets.py`) |

## Bugs found by testing and fixed

1. Windows cp1251 console crashed the server banner / `--help` output (`UnicodeEncodeError`) → UTF-8 reconfigure at every entry point.
2. Session TTL check mixed an injected clock with `time.monotonic()` → one injectable session clock.
3. Adaptation note contained digits ("3 steps", "150 words") → rewritten in words; test now asserts no digits.
4. A frame in flight when the camera was turned off overwrote the "camera off" state → frames are only ingested while the camera is active.
5. Switch control: decorative spans intercepted clicks on the checkbox → `pointer-events: none`.
6. Harmless Windows Proactor `WinError 10022/10054` tracebacks on disconnect → filtered precisely.
7. Server start created a MediaPipe session (which reports usage metrics) before any consent → removed; consent gate added.
8. Consent text overflowed the 4:3 camera frame on narrow panels; sticky Vision header let content show through → layout fixes.

## Independent code review (Claude sub-agent, read-only) — all findings fixed

| # | Severity | Finding | Fix | Regression test |
|---|---|---|---|---|
| 1 | medium | Camera ready before the server `hello` (e.g. refresh with remembered consent) → frame loop never started, no event could fire | frame loop (re)starts on `hello` | `vision.test.js` (both orders + reconnect after a vision error), e2e reload asserts "1 face" |
| 2 | low (privacy) | Camera toggled while permission pending → first stream kept capturing after "Turn off" | request token; stale streams stopped; older stream released | `vision.test.js` |
| 3 | low | Broken OpenCV import took the whole backend (chat) down | `FrameResult` moved to `vision/types.py`; OpenCV/NumPy/MediaPipe load lazily per camera session | `test_broken_opencv_disables_vision_but_never_the_chat` |
| 4 | low | Retry on an older failed answer reordered history | Retry only on the latest message (UI + store guard) | — (UI rule) |
| 5 | low | "local" wording shown without the loopback check | one `app.local` flag (page host + backend's view) gates every such string | — (UI rule) |
| 6 | low | Signal froze on its last value when the socket closed | server records `unknown` (`vision_disconnected`), client clears the value | `test_closing_the_vision_socket_turns_the_signal_unknown` |
| 7 | low | Duplicated tab shared the session (history, reset) | BroadcastChannel claim → fresh id if another live tab owns it | e2e "a duplicated tab gets its own session" |
| 8 | low (privacy) | Markdown images in answers loaded third-party URLs | `md.disable('image')` | `markdown.test.js` |
| 9 | low (security) | `0.0.0.0` bind accepted any Host → DNS rebinding could drive the API/camera socket | explicit `EH_ALLOWED_HOSTS` only, never `*` | `test_wildcard_bind_never_accepts_arbitrary_hosts` |

Also from the review: a signal that stays high used to re-fire every 17 s (cooldown + hold).
The engine now fires **one event per episode** — re-armed only when the smoothed value drops
below 0.55 or a new answer arrives (`test_one_event_per_episode…`, `test_a_real_drop_ends_the_episode…`,
`test_a_new_answer_rearms…`). While fixing these, a start-up race (a message sent in the first
~150 ms could be wiped by the state restore) was found by the e2e suite and fixed: chat actions
wait for start-up and the restore never overwrites a conversation in progress.
