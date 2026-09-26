# Remote demo — the presenter's PC at home, the laptop anywhere

The PC does all the heavy work (face landmarks + expression model on its CPU, speech detection, every
call to OpenAI and Fish Audio). The laptop's browser only captures the camera and the microphone and
plays her voice — so a weak laptop can show the full demo from any network.

```
laptop browser ──HTTPS──▶ Cloudflare edge ══ Cloudflare Tunnel (outbound from the PC) ══▶ cloudflared (Windows service)
                                                                                           │
                                                          http://127.0.0.1:8080 ◀──────────┘
                                                          ExtraHorizon (scripts/demo-host.ps1)
                                                           ├─ MediaPipe + expression model, Silero VAD (local CPU)
                                                           └─▶ OpenAI (chat, transcription) · Fish Audio (voice)
```

No router ports are opened: `cloudflared` connects *out* to Cloudflare, and the server listens on
127.0.0.1 only, so nothing else on the network can reach it.

## One-time setup

**Cloudflare** (dashboard, your account)

1. The domain uses Cloudflare's nameservers (public DNS answers with Cloudflare addresses).
2. Zero Trust → Networks → Tunnels → your tunnel (`cloudflared` installed as a Windows service on the PC)
   → Public hostname, e.g. `demo.example.com` → Service **`http://127.0.0.1:8080`** (prefer 127.0.0.1 to
   `localhost`: Windows tries `::1` first; the server listens on IPv4 loopback).
3. Optional, recommended for a public event: Zero Trust → Access → Applications → Self-hosted → the same
   hostname, policy "emails: yours" (one-time PIN). Then strangers never even see the key prompt.

**The PC**

1. As for local use: `.\scripts\setup.ps1`, API keys in `.env`.
2. `.\scripts\demo-host.ps1 -PublicUrl https://demo.example.com` — remembers the URL in `.env`, creates the
   access key (`EH_ACCESS_KEY`, 24 random characters) if there is none, rebuilds the UI when the sources
   changed, serves on `127.0.0.1:8080`, restarts the server if it ever stops, and keeps Windows awake while
   it runs. Later starts: just `.\scripts\demo-host.ps1`.
3. `.\scripts\demo-host.ps1 -ShowKey` prints the key in *your* terminal — type it on the laptop once.
   `-NewKey` replaces it (every browser has to enter the new one).
4. `.\scripts\demo-host.ps1 -Check` — the server answers, the `cloudflared` service runs, the public URL
   answers **through Cloudflare** and asks for the key, the key exists, sleep settings, autostart.
5. Leaving it unattended: `.\scripts\demo-host.ps1 -Install` registers a scheduled task that starts the demo
   host hidden when you log on (output in `logs\`); `-Uninstall` removes it. Stay logged in (lock the screen
   with Win+L), let Windows never sleep on AC power (`powercfg /change standby-timeout-ac 0`), and keep the
   `cloudflared` service on *Automatic*.

**The laptop**

Open the public URL → enter the key (remembered for 14 days in a secure cookie) → **Turn on camera** →
3 s relaxed face (calibration) → microphone, **with headphones** (her voice must not reach the laptop's mic).

## Security model

* **Who counts as "this PC"**: a loopback peer, *no* proxy header and a loopback `Host`. Tunnel requests also
  come from 127.0.0.1, but Cloudflare always adds `CF-Connecting-IP` / `CF-Ray` — so they are always remote.
* **Every remote request needs the key** — the whole `/api/*` (including the docs) and both WebSockets. The UI
  shell itself is public (it has no data) so it can show the prompt. Without `EH_ACCESS_KEY` remote requests
  are refused (`403 remote_disabled`); the same applies to LAN access via `EH_ALLOWED_HOSTS`.
* **The key** lives only in the git-ignored `.env` (the pre-commit/pre-push hooks and `test_secrets.py` block
  its value from git). The browser posts it once to `/api/access` and receives a cookie holding a signed
  timestamp (HMAC-SHA256 keyed by a hash of the key) — never the key: `HttpOnly`, `Secure`, `SameSite=Strict`,
  14 days. Changing the key logs every browser out.
* **Brute-force brake**: 8 wrong keys per client (by `CF-Connecting-IP`) and 60 overall per 10 minutes → `429`;
  the key has ~139 bits, the brake is hygiene.
* **Same site only**: cross-site requests and WebSockets are refused (Origin check); the Host allow-list is
  loopback + the public name.
* **Costs**: whoever has the key uses *your* OpenAI and Fish Audio keys — give it only to the demo laptop and
  rotate it (`-NewKey`) after the event.

## Privacy — what changes compared with a local run (the UI says the same)

* Camera frames and microphone audio travel from the laptop over **HTTPS to Cloudflare, which decrypts and
  re-encrypts them into the tunnel** to the PC — Cloudflare can technically see this traffic in transit. On the
  PC they are analysed in memory and discarded, as locally; nothing is stored.
* The privacy card, the camera and microphone consent texts and the status line switch to this wording as soon
  as the server reports the Cloudflare transport; the "video stays on this device" claim is never shown remotely.
* OpenAI, Fish Audio and Google (MediaPipe usage metrics) receive exactly what they receive locally — from the PC.

## Performance

* The laptop: camera capture + 480 px JPEG, microphone PCM16 24 kHz (≈ 384 kbit/s up), her voice PCM16
  44.1 kHz (≈ 706 kbit/s down), the UI.
* Remote camera profile: **8 fps, JPEG quality 0.7** (≈ 1–1.5 Mbit/s up; `EH_REMOTE_MAX_FPS`,
  `EH_REMOTE_JPEG_QUALITY`) — local browsers keep 12 fps. One frame in flight, so the rate adapts to latency.
* Keepalive: Cloudflare closes WebSockets that stay silent for ~100 s; the vision socket pings every 20 s, the
  voice socket every 15 s.
* Measured through the real tunnel (2026-09-26, the test client on the PC's own connection going out to
  Cloudflare and back): camera 8 fps, 73 ms round trip; typed question — first token 0.59–0.99 s, first voice
  1.5–2.0 s; spoken question — exact transcript, filler at the end of speech, answer voice 2.3–2.4 s after it.
  From another network add the laptop ↔ Cloudflare latency.

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| Cloudflare "502 Bad Gateway" | the tunnel works but nothing answers on its service → start `demo-host.ps1`; the tunnel must point to `http://127.0.0.1:8080` (or your `-Port`) |
| Cloudflare 530 / 1033 | `cloudflared` is not connected → `Start-Service cloudflared` (administrator), check the tunnel in the dashboard |
| "Remote access is off" | the server has no `EH_ACCESS_KEY` → start it via `demo-host.ps1` (creates one) |
| "Too many wrong keys" | wait 10 minutes (per client) |
| `ERR_SSL_VERSION_OR_CIPHER_MISMATCH` (or the registrar's parking page) | the DNS server this device uses still has the domain's **old** records (e.g. the registrar's parking host) — normal for minutes to hours after moving the domain to Cloudflare; the old host refuses the TLS handshake. `-Check` shows it on the PC. Fix on that device: turn on **Secure DNS** (DNS-over-HTTPS → Cloudflare 1.1.1.1) in the browser, or set the network DNS to 1.1.1.1 / 1.0.0.1, or wait until that cache expires. A browser VPN/proxy resolves names itself — switch it off (it also adds latency). Only if the stale entry is in the Windows cache does `ipconfig /flushdns` help |
| `port 8080 is already in use` | another server runs there → stop it, or `-Port 8090` and point the tunnel there |
| Camera / microphone blocked on the laptop | allow them in the address bar (the page is HTTPS through Cloudflare, so browsers allow them) |
| Her voice stutters, answers feel slow | the laptop's upload is saturated → headphones, `EH_REMOTE_MAX_FPS=6`, `EH_REMOTE_JPEG_QUALITY=0.6` in `.env`, restart |
| Logged out after a restart | the key changed (`-NewKey`) or 14 days passed → enter it again |

## Verify before the show

```powershell
.\scripts\demo-host.ps1 -Check
cd backend; uv run python scripts/demo_check.py --base https://demo.example.com --access-key-env --speech ..\frontend\e2e\.cache\question.wav
```

The second command runs the whole chain through the tunnel with the real providers (logs in with the key from
`.env`, never prints it); if the PC's own DNS is stale add `--resolve demo.example.com:<a Cloudflare IP>`.
Automated: `backend/tests/test_remote.py` (access rules) and the `remote` Playwright project (the key gate, the
camera and chat as a browser behind Cloudflare, see `frontend/e2e/remote.spec.js`).
