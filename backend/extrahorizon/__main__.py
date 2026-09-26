"""``uv run extrahorizon`` / ``uv run python -m extrahorizon`` — start the demo server."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import webbrowser


def _utf8_console() -> None:
    # Windows consoles often use a legacy code page (e.g. cp1251); never crash on output
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(prog="extrahorizon", description="ExtraHorizon emotion-aware voice tutor (backend + built UI)")
    parser.add_argument("--host", help="bind address (default 127.0.0.1 — keep it local for the privacy claim)")
    parser.add_argument("--port", type=int, help="port (default 8765)")
    parser.add_argument("--mock-llm", action="store_true", help="use the labelled offline mock tutor instead of OpenAI")
    parser.add_argument("--mock-voice", action="store_true",
                        help="offline voice doubles: a tone instead of Fish Audio, a scripted transcript instead of OpenAI STT")
    parser.add_argument("--no-vision", action="store_true", help="disable the local vision pipeline")
    parser.add_argument("--open", action="store_true", help="open the browser when ready")
    args = parser.parse_args(argv)

    if args.host:
        os.environ["EH_HOST"] = args.host
    if args.port:
        os.environ["EH_PORT"] = str(args.port)
    if args.mock_llm:
        os.environ["EH_LLM_PROVIDER"] = "mock"
    if args.mock_voice:
        os.environ["EH_TTS_PROVIDER"] = "mock"
        os.environ["EH_STT_PROVIDER"] = "mock"
    if args.no_vision:
        os.environ["EH_VISION_ENABLED"] = "false"

    import uvicorn

    from .app import create_app
    from .config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # MediaPipe/absl are chatty on stderr at start-up; keep our own log readable
    os.environ.setdefault("GLOG_minloglevel", "2")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

    url = f"http://{'127.0.0.1' if settings.host in ('0.0.0.0', '::') else settings.host}:{settings.port}"
    print(f"\n  ExtraHorizon -> {url}\n", flush=True)
    if settings.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "  WARNING: bound to a non-loopback address. Camera frames from other machines would travel\n"
            "  over the network; the UI then hides the 'video stays on this device' claim.\n"
            "  Other machines are accepted only via EH_ALLOWED_HOSTS + EH_ALLOWED_ORIGINS (explicit names).\n",
            file=sys.stderr,
            flush=True,
        )
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    class _NoHealthPolls(logging.Filter):  # every open tab polls /api/health every 4 s
        def filter(self, record: logging.LogRecord) -> bool:
            return "/api/health" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(_NoHealthPolls())
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        ws_max_size=settings.max_frame_bytes + 1024,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
