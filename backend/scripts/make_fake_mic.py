"""Build a .wav "virtual microphone" clip for browser tests (Chromium's
--use-file-for-fake-audio-capture). An offline system voice (Windows SAPI — no network,
no API key) says a question, padded with silence. It lets the e2e test drive the REAL
voice path (mic capture → AudioWorklet PCM16 → WebSocket → Silero VAD → speech-to-text →
turn → voice playback) without anyone speaking into a microphone.

    uv run python scripts/make_fake_mic.py --out ../frontend/e2e/.cache/question.wav
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np


def sapi(text: str, out: Path) -> None:
    safe = text.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{out}'); $s.Speak('{safe}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True, capture_output=True, timeout=90)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--text", default="Explain recursion to me, please.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lead", type=float, default=1.5, help="seconds of silence before the speech")
    ap.add_argument("--tail", type=float, default=6.0, help="seconds of silence after it")
    a = ap.parse_args()
    if sys.platform != "win32":
        print("make_fake_mic: needs Windows SAPI (System.Speech)", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        raw = Path(d) / "speech.wav"
        sapi(a.text, raw)
        with wave.open(str(raw)) as w:
            rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            data = w.readframes(w.getnframes())
    if width != 2:
        print(f"unexpected sample width {width}", file=sys.stderr)
        return 1
    x = np.frombuffer(data, dtype="<i2").astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    peak = float(np.abs(x).max()) or 1.0
    x = x * (0.6 * 32767 / peak)  # a normal speaking level
    pad = lambda s: np.zeros(int(s * rate), np.float32)  # noqa: E731
    y = np.concatenate([pad(a.lead), x, pad(a.tail)]).astype("<i2")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(y.tobytes())
    print(f"wrote {out} ({len(y) / rate:.1f} s at {rate} Hz, speech {len(x) / rate:.1f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
