---
name: extrahorizon-remote-demo
description: Run, check, secure and troubleshoot ExtraHorizon's remote demo — the presenter's PC at home runs the server (127.0.0.1:8080) behind Cloudflare Tunnel, and a laptop on any network opens the public HTTPS URL, enters the access key and gets the full app while the PC does the heavy work. Use this whenever the user mentions Cloudflare, cloudflared, the tunnel, the public/demo URL, "показать с ноутбука", "зайти с другой сети", "сервер дома", the access key / "ключ доступа", 502/530/1033 errors, a laptop that cannot reach or log into the demo, autostart of the demo host, or wants to change remote access rules — even if they don't say "remote".
---

# Remote demo (home PC + Cloudflare Tunnel)

Guide for humans: `docs/REMOTE_DEMO.md`. Code: `backend/extrahorizon/access.py` (transport + key +
cookie + brute-force brake + `AccessGuard`), `/api/access` in `app.py`, `frontend/src/lib/components/AccessGate.svelte`,
`app.boot()/unlock()/lockOut()` in `app.svelte.js`, runner `scripts/demo-host.ps1`.

```
laptop ─HTTPS─▶ Cloudflare edge ═ tunnel ═▶ cloudflared (Windows service) ─▶ http://127.0.0.1:8080 (demo-host.ps1)
```

## Run and check (on the PC)

```powershell
.\scripts\demo-host.ps1 -PublicUrl https://<public-host>   # first time: saves EH_PUBLIC_URL, creates EH_ACCESS_KEY in .env
.\scripts\demo-host.ps1                                    # later: serve + auto-restart + keep the PC awake
.\scripts\demo-host.ps1 -Check                             # server · cloudflared service · public URL via Cloudflare · key · sleep
cd backend; uv run python scripts/demo_check.py --base https://<public-host> --access-key-env --speech ..\frontend\e2e\.cache\question.wav
```

- The tunnel's public hostname must point to `http://127.0.0.1:<port>` (8080 by default).
- If this PC's DNS cache is stale, `-Check` says so. For scripted checks add
  `--resolve <host>:<Cloudflare IP>` (demo_check) or `--host-resolver-rules="MAP <host> <ip>"` (Chromium).
  Never "fix" this by editing the hosts file.
- `-Install` / `-Uninstall` add or remove the logon autostart task. That is a persistent change to the
  user's system: let the user run it, or ask first.
- The same applies to `powercfg` changes: suggest them, don't apply them.

## Secrets

- `EH_ACCESS_KEY` lives only in the git-ignored `.env`. Never print, log or echo it.
- Only the user may display it (`-ShowKey` in their own terminal).
- Scripts read it themselves (`demo_check.py --access-key-env`, a Playwright script reading `.env`) and
  must never output it.
- Rotate the key with `-NewKey`; that logs every browser out.
- Whoever has the key spends the owner's OpenAI and Fish Audio credits.

## Invariants (tests: `backend/tests/test_remote.py`, Playwright project `remote`)

- **Server binding.** The server binds to loopback only; remote traffic arrives only through the tunnel.
  Never bind to 0.0.0.0 for the demo.
- **Local detection.** "Local" means loopback peer **and** no proxy header **and** loopback Host.
  Tunnel requests come from 127.0.0.1 with `CF-Connecting-IP`, so they are always remote.
  Never trust the peer address alone.
- **What the key protects.** Every remote `/api/*` request and both WebSockets need the cookie.
  - Static UI files stay public, so the gate can render.
  - `/api/access` is the only open API route.
  - Without a configured key, remote access is refused (`remote_disabled`).
- **Cookie.** `HttpOnly; Secure` (https); `SameSite=Strict`. It holds a signed timestamp, never the key.
  Changing the key invalidates every cookie.
- **Honest wording.** For a Cloudflare transport the UI says frames and audio go through Cloudflare to the
  presenter's computer. The "stays on this device" claim is never shown remotely.
  Keep README, PITCH and EXTERNAL_DEPENDENCIES §3a in line.
- **Remote camera profile.** A remote browser gets `EH_REMOTE_MAX_FPS` (8) and `EH_REMOTE_JPEG_QUALITY` (0.7).
- **Keepalive.** Both sockets ping (vision every 20 s, voice every 15 s), because Cloudflare closes
  silent WebSockets after about 100 s.

## Symptom → cause

| Symptom | Look at |
|---|---|
| `ERR_SSL_VERSION_OR_CIPHER_MISMATCH` in a browser | that device's DNS (ISP resolver / browser VPN) still returns the domain's OLD host (registrar parking) which refuses TLS — compare `Resolve-DnsName <host>` with `-Server 1.1.1.1`; fix: Secure DNS (DoH) in the browser / DNS 1.1.1.1 / wait for the cached NS to expire; never touch the server |
| 502 from Cloudflare | demo host not running / tunnel service URL wrong (`-Check`) |
| 530 / 1033 | `cloudflared` not connected (`Get-Service cloudflared`) |
| Gate says "not reachable — retrying" | server down or tunnel down |
| Gate says "Remote access is off" | no `EH_ACCESS_KEY` in the server's environment |
| "Too many wrong keys" | 8 wrong tries per client per 10 min → wait |
| Voice stutters remotely | laptop upload → lower `EH_REMOTE_MAX_FPS`, headphones |
| A local tab suddenly asks for a key | it is being opened through the public name or a proxy — expected |
