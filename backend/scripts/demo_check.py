"""End-to-end rehearsal of the demo chain against a RUNNING backend (real providers).

Drives the chain exactly as the browser does:
health → vision socket (labelled Demo simulation: a chosen expression drives the same
emotion engine) → the live prompt note → "Explain recursion to me." over SSE with the
voice socket open → the note reached the prompt (meta.emotion_context) → her voice for
that turn streams back (Fish Audio) → optionally a spoken question from a WAV file over
the microphone path (Silero VAD → OpenAI transcription → filler → answer voice) → reset.

The expression comes from the simulation because a script has no face in front of a
camera: this proves emotion engine → prompt → LLM → voice, not camera → model — the live
camera must be rehearsed by a person (see docs/TEST_MATRIX.md).

    cd backend
    uv run python scripts/demo_check.py --runs 3
    uv run python scripts/demo_check.py --speech ../frontend/e2e/.cache/question.wav
    # the remote demo, through the tunnel (logs in with EH_ACCESS_KEY from .env, never prints it):
    uv run python scripts/demo_check.py --base https://demo.example.com --access-key-env
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import statistics
import struct
import sys
import time
import uuid
import wave
from pathlib import Path

import httpx
import numpy as np
from websockets.asyncio.client import connect


class LiveSocket:
    """The browser's /api/live connection: collects events and voice frames per turn."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.events: list[tuple[float, dict]] = []
        self.first_audio: dict[int, float] = {}
        self.audio_bytes: dict[int, int] = {}
        self._task = asyncio.create_task(self._read())

    async def _read(self) -> None:
        async for raw in self.ws:
            now = time.perf_counter()
            if isinstance(raw, bytes):
                turn = struct.unpack(">I", raw[:4])[0]
                self.first_audio.setdefault(turn, now)
                self.audio_bytes[turn] = self.audio_bytes.get(turn, 0) + len(raw) - 4
            else:
                self.events.append((now, json.loads(raw)))

    def find(self, pred) -> tuple[float, dict] | None:
        return next(((t, m) for t, m in self.events if pred(m)), None)

    async def wait(self, pred, timeout: float = 30.0) -> tuple[float, dict]:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            hit = self.find(pred)
            if hit:
                return hit
            await asyncio.sleep(0.02)
        raise TimeoutError("expected message did not arrive")

    async def close(self) -> None:
        self._task.cancel()
        await self.ws.close()


class VisionSim:
    """Keeps the vision socket open (closing it = no camera = no note) and drives the
    labelled simulation at 10 Hz in the background."""

    def __init__(self, base_ws: str, sid: str, emotion: str, headers: dict | None = None) -> None:
        self.url = f"{base_ws}/api/vision?session_id={sid}"
        self.emotion = emotion
        self.headers = headers or {}
        self.note: dict | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self.ws = await connect(self.url, additional_headers=self.headers)
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        async def reader() -> None:
            async for raw in self.ws:
                m = json.loads(raw)
                if m.get("type") == "emotion_note":
                    self.note = m["context"]

        rt = asyncio.create_task(reader())
        try:
            while True:
                await self.ws.send(json.dumps({"type": "sim", "enabled": True, "emotion": self.emotion, "intensity": 0.85}))
                await asyncio.sleep(0.1)
        finally:
            rt.cancel()

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
        await self.ws.close()


def load_speech(path: str) -> bytes:
    with wave.open(path) as w:
        rate, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    y = np.interp(np.arange(0, len(x), rate / 24000), np.arange(len(x)), x)
    return y.astype("<i2").tobytes()


def access_key_from_env() -> str:
    """EH_ACCESS_KEY from the environment or the repo's .env (never printed)."""
    if os.environ.get("EH_ACCESS_KEY"):
        return os.environ["EH_ACCESS_KEY"].strip()
    env = Path(__file__).resolve().parents[2] / ".env"
    for line in env.read_text(encoding="utf-8").splitlines() if env.exists() else []:
        if line.strip().startswith("EH_ACCESS_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("no EH_ACCESS_KEY in the environment or .env")


def pin_dns(spec: str) -> None:
    """--resolve host:ip — connect to ip for host (TLS name and Host header unchanged)."""
    host, ip = spec.rsplit(":", 1)
    original = socket.getaddrinfo

    def patched(h, *args, **kwargs):
        name = h.decode("idna") if isinstance(h, bytes) else h  # anyio passes IDNA bytes
        return original(ip if name == host else h, *args, **kwargs)

    socket.getaddrinfo = patched


async def login(client: httpx.AsyncClient, base: str, key: str | None) -> dict:
    """The remote demo's access gate: returns the cookie header for the WebSockets."""
    access = await client.get(f"{base}/api/access")
    if access.status_code == 404 or not access.json().get("required"):
        return {}
    if not key:
        raise SystemExit(f"{base} asks for the access key — add --access-key-env")
    r = await client.post(f"{base}/api/access", json={"key": key})
    if r.status_code != 200:
        raise SystemExit(f"access key refused: {r.json().get('code')}")
    return {"Cookie": f"eh_access={client.cookies.get('eh_access')}"}


async def one_run(base: str, question: str, speech: bytes | None, key: str | None = None) -> dict:
    base_ws = base.replace("http", "ws", 1)
    sid = str(uuid.uuid4())
    out: dict = {}
    async with httpx.AsyncClient(timeout=90) as client:
        headers = await login(client, base, key)
        health = (await client.get(f"{base}/api/health?deep=1")).json()
        out["health"] = {k: health[k] for k in ("llm", "tts", "stt", "vision", "fillers")}
        out["transport"] = (health.get("client") or {}).get("transport")
        live = LiveSocket(await connect(f"{base_ws}/api/live?session_id={sid}", max_size=2**24,
                                        additional_headers=headers))
        await live.wait(lambda m: m["type"] == "hello")
        await live.ws.send(json.dumps({"type": "voice_out", "on": True}))
        # the expression (labelled simulation) → the note that will be added to the prompt
        sim = VisionSim(base_ws, sid, "happiness", headers)
        await sim.start()
        await asyncio.sleep(2.5)
        out["note"] = (sim.note or {}).get("note")
        # a typed question: text over SSE, voice over the live socket
        t0 = time.perf_counter()
        meta = done = None
        ttft = None
        async with client.stream("POST", f"{base}/api/chat", json={"session_id": sid, "message": question}) as r:
            event = None
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:])
                    if event == "meta":
                        meta = data
                    elif event == "delta" and ttft is None:
                        ttft = time.perf_counter() - t0
                    elif event in ("done", "error", "interrupted"):
                        done = (event, data)
        out["ttft_s"] = ttft
        out["result"] = done[0] if done else "no terminal event"
        ctx = (meta or {}).get("emotion_context") or {}
        out["note_in_prompt"] = bool(ctx.get("available")) and ctx.get("dominant") == "happiness"
        turn = (meta or {}).get("turn_no")
        try:
            await live.wait(lambda m: m["type"] == "audio_end" and m["turn_no"] == turn, 40)
            out["first_audio_s"] = live.first_audio[turn] - t0
            out["voice_s"] = live.audio_bytes[turn] / 2 / 44100
        except (TimeoutError, KeyError):
            out["first_audio_s"] = None
        if speech is not None:
            await live.ws.send(json.dumps({"type": "mic", "on": True}))
            await asyncio.sleep(0.5)
            start = time.perf_counter()
            for i in range(0, len(speech), 1920):  # real time, like a microphone
                await asyncio.sleep(max(0.0, start + i / 48000 - time.perf_counter()))
                await live.ws.send(speech[i : i + 1920])
            t_end, end = await live.wait(lambda m: m["type"] == "vad" and m["speaking"] is False, 10)
            spoken_turn = end["turn_no"]
            _, heard = await live.wait(lambda m: m["type"] in ("heard", "stt_ignored"), 10)
            out["heard"] = heard.get("text")
            t_answer, _ = await live.wait(
                lambda m: m["type"] == "audio_begin" and m["kind"] == "answer" and m["turn_no"] == spoken_turn, 20)
            filler = live.find(lambda m: m["type"] == "filler" and m["turn_no"] == spoken_turn)
            out["filler"] = filler[1]["text"] if filler else None
            out["speech_end_to_filler_s"] = (live.first_audio[spoken_turn] - t_end) if filler else None
            out["speech_end_to_answer_voice_s"] = t_answer - t_end
        await client.post(f"{base}/api/session/reset", json={"session_id": sid})
        await sim.close()
        await live.close()
    return out


def _quiet_windows_socket_teardown() -> None:
    """Windows' Proactor loop reports sockets reset while closing (WinError 10022/10053/10054) as
    unhandled errors — harmless at the end of a run; everything else is still reported."""
    loop = asyncio.get_running_loop()

    def handler(lp, context):
        exc = context.get("exception")
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10022, 10053, 10054):
            return
        lp.default_exception_handler(context)

    loop.set_exception_handler(handler)


async def main() -> int:
    _quiet_windows_socket_teardown()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--question", default="Explain recursion to me.")
    ap.add_argument("--speech", help="optional WAV with a spoken question (mic path)")
    ap.add_argument("--access-key-env", action="store_true",
                    help="remote demo: log in with EH_ACCESS_KEY from the environment or .env (never printed)")
    ap.add_argument("--resolve", help="host:ip — use this address for host (e.g. when this PC's DNS is stale)")
    a = ap.parse_args()
    if a.resolve:
        pin_dns(a.resolve)
    key = access_key_from_env() if a.access_key_env else None
    speech = load_speech(a.speech) if a.speech else None
    results = []
    for i in range(a.runs):
        r = await one_run(a.base.rstrip("/"), a.question, speech, key)
        results.append(r)
        print(f"run {i + 1}: {json.dumps({k: v for k, v in r.items() if k != 'health'}, ensure_ascii=False)}")
    h = results[0]["health"]
    print("\nhealth:", {k: (v.get("state") or v.get("available") or v.get("configured")) if isinstance(v, dict) else v for k, v in h.items()})
    ok = all(r["result"] == "done" and r["note_in_prompt"] and r.get("first_audio_s") for r in results)
    ttfts = [r["ttft_s"] for r in results if r["ttft_s"]]
    firsts = [r["first_audio_s"] for r in results if r.get("first_audio_s")]
    if ttfts:
        print(f"first token: median {statistics.median(ttfts):.2f} s · first voice: median {statistics.median(firsts):.2f} s" if firsts else "")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
