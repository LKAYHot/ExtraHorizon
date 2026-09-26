# Test matrix

Status as of 2026-09-26 on the development machine (Windows 11, Python 3.14.7, Node 24, Edge for the browser
tests; OpenAI `gpt-6-luna` + `gpt-live-transcribe`, Fish Audio `drama-3-preview`). "Agent" = checked by the coding
agent (Claude Code); items that need a person in front of a physical webcam/microphone are marked **not tested** —
they are the agenda of the final rehearsal (docs/PITCH.md).

## Automated tests

| Suite | Command | Result |
|---|---|---|
| Backend unit + integration — remote access (transport detection incl. the tunnel's 127.0.0.1 requests, access key + cookie flags, brute-force brake, guarded WebSockets, remote camera profile), per-person calibration modelled on a real learner's measured frames (relaxed stern face → neutral, snarl → angry not disgusted, pressed lips → angry, stern smile → happy, pose, talking, adaptation, sensitivity), emotion engine, quality gates, real MediaPipe + expression model on a portrait (calibrated over the vision socket), persona/context, cues/splitter/silence/fillers, Fish protocol (fake server), realtime STT (fake server), VAD segmentation + Silero, the voice socket end to end (fake LLM, mock TTS/STT, energy VAD), API/SSE/sockets, guards, secret scan | `cd backend && uv run pytest` | **143 passed** |
| Frontend unit — remote access API (key sent once as JSON, refusals mapped), markdown safety + cue rendering, cue helpers, emotion palette/orders, audio frame parsing + gapless player, voice controller protocol + microphone list/choice/fallback, camera controller races + recalibrate/sensitivity, formatting | `cd frontend && npx vitest run` | **51 passed** |
| Svelte type/a11y check | `npx svelte-check --threshold warning` | **0 errors, 0 warnings** |
| Browser e2e (production build, mock LLM + mock voice, Edge): **remote browser** (sends Cloudflare's headers: access-key gate, wrong/right key, tunnel wording, camera ≤ 8 fps, chat, remembered after reload), demo scenario with the real models on a virtual camera (calibration → "tracking (calibrated to you)" → Neutral → Recalibrate), consent remembered, refresh, duplicated tab, two faces, no face, camera off, camera + microphone denied, **voice with a virtual microphone** (real Silero VAD in the loop) | `cd frontend && npm run e2e` | **11 passed** |
| Live chain against the running app + real providers (health → simulated expression → note → typed question → note in the prompt → Fish voice for the turn → spoken question from a WAV over the mic path → filler → answer voice) | `cd backend && uv run python scripts/demo_check.py --runs 2 --speech ../frontend/e2e/.cache/question.wav` | **PASS 2/2** — first token 0.63–0.89 s, first voice 1.5–1.9 s (typed); end of speech → filler ≈0 s, → answer voice 1.66–1.99 s |
| Live voice probe (browser-like client, recorded speech in real time, real providers): noisy question (SNR ≈5 dB), barge-in, "wait, stop", a sentence with a 1.1 s pause | development probe | **pass** — transcripts exact, filler at end of speech, barge-in stops her ≈0.7 s after onset, "wait, stop" starts no answer, the paused sentence is joined |
| Calibration on the user's own frames (five screenshots of the camera panel, local models only, production Calibrator + engine at 10 fps with logit noise) | development scripts | **pass** — relaxed faces → **Neutral 0.79–0.93**; snarl → **Angry 0.89–0.96** ("baring teeth"); lips pressed → **Angry 0.72–0.83** (was Neutral 0.41–0.70 / Disgusted with the first calibration); 5 min of a relaxed face drifting (10° pitch, noise σ ≤ 0.7): **0 %** false expressions in every preset; Angry after 1.3–1.5 s, Neutral again after 1.3–1.4 s (Balanced) |
| **Remote demo through the real Cloudflare Tunnel** (the PC serving `demo-host.ps1` on 127.0.0.1:8080, test clients on the same PC going out to Cloudflare's edge and back; virtual camera + microphone; real providers) | `remote_e2e` browser script + `demo_check.py --access-key-env` | **pass** — `/api/access` sees `cloudflare`; API without key 401, cross-origin login 403; gate → wrong key rejected → key accepted → app; tunnel wording in the privacy card and sidebar; camera 8 fps, 73 ms round trip, calibrated → Neutral; typed question first text 2.2 s; reload keeps access; voice chain 2/2: first token 0.59–0.99 s, first voice 1.5–2.0 s, spoken question transcribed exactly, filler at end of speech, answer voice 2.3–2.4 s after it |
| Styled select boxes (Subject, microphone ×2) | screenshots + keyboard script (virtual devices) | **pass** — dark list with check mark and hover row, not clipped by the scrolling sidebar, compact list near the composer; ↓ / typing "p" / Enter selects Physics |
| Persona with the real LLM (`gpt-6-luna`, prompt builder, no camera) | development probe | **pass** — "Can you see me?" → "Yeah, I can see you — you look pretty relaxed"; "hey" → "Hey. So, what are we working on today?"; a cut-off sentence → "The thing with the… what?"; "I'm not angry" → "Hmph, fine — concentration face, then"; an unchanged frown is not mentioned again; with no camera she says she can't see them; no assistant phrases |

What the automated tests prove: the calibration rules (a biased resting face reads neutral, a small brow shift or a
lowered head does not become an expression, a real expression still shows, talking frames are skipped, adaptation
never absorbs a smile, sensitivity presets are ordered), the emotion rules (time-based smoothing, stable dominant,
unknown never neutral, words-only note phrased as her view, "unchanged" marking), that the note reaches the prompt only with a clear face, the voice turn logic (filler, speculation
confirmed/replaced without losing audio or leaving history traces, barge-in, stop commands, continued sentences,
echo, stop button, text-only mode, mic off), provider protocols against fake servers, chat failure paths, the real
browser camera path through MediaPipe + the expression model (virtual camera with a real face), the real browser
microphone path through the AudioWorklet and Silero VAD (virtual microphone with an offline system voice), consent
gates, refresh restore.

What they do **not** prove: accuracy of the calibrated expression estimate on a real person moving in front of a
real webcam in venue light (checked only on two still frames); transcription of a real person's accent through a real
microphone; echo behaviour with the demo laptop's speakers; switching between two physical microphones.

## Manual matrix

| # | Scenario | How it was checked | Result |
|---|---|---|---|
| 1 | Camera allowed (virtual device, real face clip) | e2e: Active → 1 face · tracking → expression estimate + face label → note | **pass** |
| 1b | Camera allowed — physical webcam, live person | needs a person | **not tested** |
| 1c | Calibration: relaxed face → Neutral; small brow movements / slightly lowered head stay Neutral; a clear snarl / pressed lips → Angry, a smile → Happy | virtual camera (e2e) + the user's five still frames (offline, production pipeline) + `test_calibration.py`; live person still needed | **pass** (stills) / **not tested** (live) |
| 1d | Recalibrate + Calm/Balanced/Expressive | e2e (Recalibrate → Calibrating… → Neutral), API test over the vision socket, `vision.test.js` | **pass** |
| 2 | Camera permission denied | e2e `denied` + browser pane: status, banner "chat and voice still work", chat answers | **pass** |
| 3 | No face | e2e `no-face`: "No face in view — expression unknown", nothing sent about a face | **pass** |
| 4 | Several faces | e2e `two-faces` + API test: ambiguous, no estimate, no note | **pass** |
| 5 | Camera switched off mid-session | e2e: Turn off → "Camera is off" → on again | **pass** |
| 5b | Camera physically unplugged | `track.ended` handler; needs hardware | **not tested** |
| 6 | Microphone allowed (virtual device, system voice) | e2e `voice`: hearing → spoken question → answer → speaking → Stop | **pass** |
| 6b | Microphone — live person, laptop speakers (echo) and headphones | needs a person | **not tested** |
| 7 | Microphone permission denied | e2e `denied`: clear message, mic off, typing works | **pass** |
| 7b | Microphone choice (list, remembered, live switch, unplugged → default) | `voice.test.js` (listing, persistence, `OverconstrainedError`/`NotFoundError` fallback); two physical mics need hardware | **pass** (unit) / **not tested** (hardware) |
| 8 | Noisy speech (SNR ≈5 dB, EN + RU) | development probe with recorded speech + noise | **pass** (exact transcripts) |
| 9 | Barge-in / "wait, stop" / paused sentence (real providers) | live probe + `test_live.py` | **pass** |
| 10 | Russian question → English answer | live check: "Объясни, что такое хеш-таблица." → English, 3 sentences | **pass** |
| 11 | Fish Audio errors / quota | fake-server tests (error event, unreachable → breaker) | **pass** (simulated) |
| 12 | Missing keys | tests: `llm_not_configured`; health shows voice/STT unconfigured | **pass** |
| 13 | LLM timeout / stall | tests (0.4 s timeouts) | **pass** |
| 14 | Page refresh | e2e: conversation restored | **pass** |
| 15 | Repeated reset | API test + e2e | **pass** |
| 16 | Expression accuracy in venue light (`vision_probe.py`, now calibrated) | needs a person + webcam | **not tested** |
| 17 | "Can you see me?" / small talk / garbled speech / "I'm not angry" | real-LLM persona probe (text) | **pass** |

## Network / privacy checks

| Check | Result |
|---|---|
| Microphone audio reaches the transcription service only inside VAD utterances | **pass** (`test_live.py`: mic off → nothing; silence → no utterance; `test_vad.py`) |
| OpenAI chat payload has no image data, landmarks, probabilities or numbers | **pass** (tests + payload inspection) |
| MediaPipe contacts Google | **observed** (usage metrics, see EXTERNAL_DEPENDENCIES.md); disclosed; camera only after consent |
| Cross-site requests / WebSockets, foreign Host header | **pass** (403 / refused / 400) |
| Remote access needs the key (tunnel requests arrive from 127.0.0.1 — told apart by Cloudflare's headers); cookie holds no key; brute-force brake | **pass** (`test_remote.py`, e2e `remote`, live through the tunnel) |
| Remote wording: camera/mic traffic goes through Cloudflare (never "stays on this device") | **pass** (e2e `remote` + live tunnel: privacy card, consent texts, status line) |
| Keys never committed | **pass** (`.gitignore`, pre-commit + pre-push hooks, `test_secrets.py` also checks the literal `.env` values) |

## Bugs found by testing and fixed (voice/emotion version)

1. A speculative turn discarded after a different final transcript sent `audio_stop` for the shared turn number, silencing the filler **and** the replacement answer → only audio that was actually released is stopped (regression test).
2. A fast speculative answer could be committed to the history before the final transcript confirmed it (and its task never ended) → commit waits for confirmation (regression test).
3. The later of two cancel reasons won (e.g. `superseded` hid `interrupted`, losing the partial answer) → the first reason wins.
4. "Before that they looked …" skipped the segment that had just ended → fixed (test).
5. The TTS splitter sent a whole burst of text as one huge first chunk → earliest clause for the first chunk, bounded later chunks.
6. LaTeX in answers would be read aloud ("backslash parenthesis") → the persona forbids it and `speakable()` turns maths into words (test).
7. "huffy and flustered" was shown as a sound effect (prefix match on "huff") → whole-word sound detection (test).
8. Answers were too long for a conversation (~75 words, ~30 s of voice) → per-turn reply rules (now 48–63 words).
9. Speculative LLM calls on transcripts that were just her own echo → skipped.
10. Test fixtures with key-like strings were (correctly) flagged by the secret scan → neutral fake keys.
11. With a fast LLM the first half of a paused sentence was already answered (in text, not yet heard) when the learner went on → the unheard answer is taken back and the halves are joined (live-verified 2/2, regression test).

## Reported by the owner and fixed (calibration version)

1. A relaxed face read **Angry 78–94 %**; small brow movements or a slightly lowered head switched to Angry / Unimpressed → per-person calibration (bias correction in logit space + facial-action evidence + pose weighting + a "clearly there" floor), face alignment and mirror averaging; sensitivity presets; Recalibrate (`test_calibration.py`, API + e2e tests).
2. She kept saying *"I can't see you directly, but the estimate suggests…"* → the note is phrased as her own view on the call and the persona treats it as her eyes (never "estimates"); she says she can't see only when there is no face (`test_context.py`, real-LLM probe).
3. Service phrases like *"Tell me what you were asking, and I'll answer directly"* → a stronger character (reacts like a person first, banned assistant phrases, garbled input handled in character, "unchanged" faces not commented on again) (`test_context.py`, probe).
4. No way to choose the microphone → a microphone list (sidebar, microphone card, under the chat while talking), remembered, switched live, falling back to the default when unplugged (`voice.test.js`).
5. Found while fixing: the calibration never finished while the learner smiled or talked (smiles now allowed, talking skipped with an 8 s fallback); the frame completing calibration still said "calibrating"; the UI showed "Calibrating…" without a face; the browser did not send the default sensitivity, so a server default other than *balanced* could override the learner's choice (all with tests).
6. Found on UI screenshots (virtual camera, 1440×900 / 1366×768 / 1024×768): the new microphone list made the sidebar taller than the window and squashed the *New session* button → the sidebar scrolls instead and nothing shrinks; on narrow windows the list sits in the top bar row; "for just now" → "just now" and the missing space before "·" in the expression subtitle.

## Reported by the owner and fixed (calibration, second round)

1. After the first calibration a clear angry face read **Neutral 49 % / Disgusted 30 %** (another time Disgusted 69 %) and lips pressed together **Neutral 70 % / Disgusted 29 %** → reproduced exactly offline on the same frames. Cause: the learner's resting face already reads anger 0.95 and their angry face 0.98 — only *neutral* drops; the correction shifted every class toward a reference, which erased anger, and the blendshape "evidence" gate demanded brow-down, which MediaPipe does not see on that face (0.4 at rest, ~0 in a snarl), moving the rest into Neutral / Disgusted. New method: neutral vs. expression relative to the relaxed face (intensity = the gains of what the face shows now), which expression from how the face reads now (classes that gained on neutral), hallmark facial actions only between expressions; square crop over the whole face (pressed lips: raw anger 0.55 → 0.76); Balanced hold 1.2 → 1.0 s. Now: snarl → Angry 0.89–0.96, pressed lips → Angry 0.72–0.83, relaxed → Neutral; 0 % false expressions over 5 min of a drifting relaxed face (`test_calibration.py` with the measured logits, stress + latency scripts).
2. The note could name a snarl's stretched lips as "smiling" → the note names only facial actions that fit the reported expression ("baring teeth").
3. The panel said "relaxed · negative · high energy" (the mood was right, the dominant wrongly Neutral) → dominant and mood now agree: the relaxed face's valence/arousal bias is removed in proportion to how relaxed the face reads (relaxed → neutral mood; angry → negative, high energy).
4. Also checked: the stern face that smiles reads Happy (the first version of the new method missed it — the neutral share hardly moves when happiness replaces anger; fixed by measuring the gains per class, test).
5. Independent review of the new calibration (Claude sub-agent, read-only; crop verified at all roll angles, 50 001 fuzzed frames sum to 1 with no NaN) found, and we fixed with regression tests: slow adaptation could absorb a slowly creeping expression (a snarl read neutral 0.89 after 10 min of drift) → adaptation only while the classifier reads the relaxed face, bounded drift; the head-pose neutral bonus was uncapped (a snarl at 25° pitch read neutral 0.62) → capped at 1, the frame weight does the rest; speech produced "baring teeth / lips pressed together" in the note → no mouth words while talking; non-finite model output → "no estimate" (unknown), never a poisoned baseline, overflow-free sigmoid; a frame without a pose assumed pitch 0 → the calibration pose; a test assertion that could not fail.

## Independent code review (Claude sub-agent, read-only) — findings and fixes

| # | Severity | Finding | Fix | Regression test |
|---|---|---|---|---|
| 1 | high | After a backend restart (or a swept session) turn numbers restart at 1 and the browser player dropped them as "older" → silent answers | `TtsPlayer.reset()` on every live `hello` and on reset | `audio.test.js`, `voice.test.js` |
| 2 | high | Stop pressed before the final transcript committed a phantom exchange and still answered when the transcript arrived | an unconfirmed turn is dropped, never committed; pending questions are cancelled by Stop/barge-in | `test_stop_while_she_is_still_thinking…` |
| 3 | medium | A dropped voice socket left the turn "thinking" forever | the client ends pending spoken turns on close (partial kept as interrupted) | `voice.test.js` |
| 4 | medium | The echo check matched shared words ("What is a base case?") and swallowed real follow-ups | echo = a contiguous repeat of her phrasing (word trigrams) | `test_echo_needs_her_phrasing…` |
| 5 | medium | An unreachable transcription service stalled the live socket (inline 8 s re-dials); a dropped connection could shift transcripts | background reconnect with back-off, audio dropped while down; pending utterances finished with their live text; item mapping cleared | `test_an_unreachable_service…`, `test_a_dropped_connection…` |
| 6 | medium (plausible) | A cancelled turn's slow voice dial could register late and silence the newer answer | the speaker registers only if its turn is still current | — (timing) |
| 7 | low-medium | A superseded socket's teardown cancelled the new socket's turn | only turns this connection started, and only if not superseded | — |
| 8 | low-medium (plausible) | "Superseded" left the mic showing on | mic set off | `voice.test.js` |
| 9 | low | Simulated history leaked into camera notes; the note called a simulation a camera estimate | segments carry their source; the note says "labelled demo simulation" | `test_simulated_history_never_leaks…`, `test_a_simulated_note_says_so` |
| 10 | low | Reset did not forget utterances being transcribed; consent texts claimed "this computer" on LAN setups | `on_reset()` cancels them; consent wording follows the loopback check | `test_a_new_session_drops_a_question…` |

Checked and fine (per the review): no key reaches logs or the client; `/api/live` is covered by the origin/host guards; audio framing and worklet resampling are correct; audio reaches OpenAI only inside VAD utterances; memory growth is bounded.
