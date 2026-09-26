"""End-to-end rehearsal of the demo chain against a RUNNING backend.

Drives the whole chain exactly as the UI does:
health → vision socket → "Explain recursion to me." (streamed) → sustained signal
→ exactly ONE possible_confusion event (cooldown holds) → "Explain differently"
(adapted answer + strategy metadata) → reset clears everything.

The signal comes from the **labelled Demo simulation input** (the same state engine,
tagged ``source: simulation``) because a script has no face in front of a camera.
It proves the engine → context → LLM part, not the camera → proxy part — the live
camera must be rehearsed by a person (see docs/TEST_MATRIX.md).

    cd backend
    uv run python scripts/demo_check.py --runs 10
    uv run python scripts/demo_check.py --base http://127.0.0.1:8765 --question "Explain recursion to me."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
import uuid

import httpx
from websockets.asyncio.client import connect


def shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(words[i : i + n]) for i in range(max(0, len(words) - n + 1))}


def verbatim_overlap(original: str, adapted: str) -> float:
    """Share of 5-word sequences of the adapted answer copied from the original."""
    a, b = shingles(original), shingles(adapted)
    return len(a & b) / len(b) if b else 0.0


async def sse_chat(client: httpx.AsyncClient, base: str, body: dict) -> dict:
    out: dict = {"meta": None, "text": "", "done": None, "error": None, "ttft": None}
    t0 = time.perf_counter()
    parts: list[str] = []
    async with client.stream("POST", f"{base}/api/chat", json=body, timeout=90) as r:
        if r.status_code != 200:
            out["error"] = {"http": r.status_code, "body": (await r.aread()).decode(errors="replace")[:300]}
            return out
        event = None
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
                if event == "meta":
                    out["meta"] = data
                elif event == "delta":
                    if out["ttft"] is None:
                        out["ttft"] = time.perf_counter() - t0
                    parts.append(data["text"])
                elif event == "done":
                    out["done"] = data
                elif event == "error":
                    out["error"] = data
    out["text"] = "".join(parts)
    out["total"] = time.perf_counter() - t0
    return out


async def run_once(base: str, question: str, idx: int) -> dict:
    sid = str(uuid.uuid4())
    ws_url = base.replace("http", "ws", 1) + f"/api/vision?session_id={sid}"
    res: dict = {"run": idx, "ok": False}
    async with httpx.AsyncClient() as client, connect(ws_url, max_size=2**22) as ws:
        hello = json.loads(await ws.recv())
        assert hello["type"] == "hello", hello
        events: list[dict] = []

        async def reader() -> None:
            async for raw in ws:
                m = json.loads(raw)
                if m["type"] == "event":
                    events.append(m["event"])

        reader_task = asyncio.create_task(reader())
        try:
            # 1) normal streamed answer
            r1 = await sse_chat(client, base, {"session_id": sid, "message": question})
            if not r1["done"]:
                res["fail"] = f"normal answer failed: {r1['error']}"
                return res
            res["ttft_normal"] = r1["ttft"]
            res["total_normal"] = r1["total"]
            if r1["meta"]["adaptation"] is not None:
                res["fail"] = "normal answer carried an adaptation"
                return res

            # 2) sustained signal (labelled simulation) → exactly one event
            t_sig = time.perf_counter()
            while time.perf_counter() - t_sig < 4.0:
                await ws.send(json.dumps({"type": "sim", "enabled": True, "value": 0.9}))
                await asyncio.sleep(0.1)
                if any(e["kind"] == "possible_confusion" for e in events):
                    break
            conf = [e for e in events if e["kind"] == "possible_confusion"]
            if not conf:
                res["fail"] = "no possible_confusion event within 4 s"
                return res
            res["detect_s"] = time.perf_counter() - t_sig
            for _ in range(10):  # keep the signal high: cooldown must suppress repeats
                await ws.send(json.dumps({"type": "sim", "enabled": True, "value": 0.9}))
                await asyncio.sleep(0.1)
            res["events"] = sum(1 for e in events if e["kind"] == "possible_confusion")
            ev = conf[0]
            if ev["answer_id"] != r1["done"]["assistant_message_id"] or ev["status"] != "offered":
                res["fail"] = f"event not attached/offered: {ev}"
                return res
            await ws.send(json.dumps({"type": "sim", "enabled": True, "value": 0.1}))

            # 3) explain differently
            r2 = await sse_chat(client, base, {"session_id": sid, "mode": "explain_differently", "event_id": ev["id"]})
            if not r2["done"]:
                res["fail"] = f"adapted answer failed: {r2['error']}"
                return res
            adapt = r2["meta"]["adaptation"]
            res["ttft_adapted"] = r2["ttft"]
            res["strategy"] = adapt["strategy"]["id"]
            res["overlap"] = verbatim_overlap(r1["text"], r2["text"])
            instr = adapt["instruction"]
            if re.search(r"\d", instr) or "%" in instr:
                res["fail"] = "instruction contains numbers"
                return res
            leaks = [w for w in ("camera", "webcam", "facial", "detected your", "you look", "you seem") if w in r2["text"].lower()]
            res["leaks"] = leaks

            # 4) reset clears everything
            rr = (await client.post(f"{base}/api/session/reset", json={"session_id": sid})).json()
            st = (await client.get(f"{base}/api/session/{sid}/state")).json()
            if not rr.get("ok") or st["messages"] or st["events"] or st["timeline"]["samples"] or st["timeline"]["markers"]:
                res["fail"] = "reset left state behind"
                return res
            res["ok"] = res["events"] == 1 and not leaks
            if res["events"] != 1:
                res["fail"] = f"expected 1 event, got {res['events']}"
            elif leaks:
                res["fail"] = f"adapted answer mentions: {leaks}"
            return res
        finally:
            reader_task.cancel()


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]  # cp1251 consoles
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--question", default="Explain recursion to me.")
    args = ap.parse_args()

    async with httpx.AsyncClient() as c:
        h = (await c.get(f"{args.base}/api/health", params={"deep": 1}, timeout=15)).json()
    print(f"backend {h['version']} boot={h['boot_id']}  LLM {h['llm']['provider']}/{h['llm']['model']} "
          f"reachable={h['llm']['reachable']}  vision={h['vision']['available']}")
    results = []
    for i in range(1, args.runs + 1):
        try:
            r = await run_once(args.base, args.question, i)
        except Exception as e:  # noqa: BLE001
            r = {"run": i, "ok": False, "fail": f"{type(e).__name__}: {e}"}
        results.append(r)
        if r["ok"]:
            print(
                f"run {i:2d} PASS  ttft {r['ttft_normal']:.2f}s/{r['ttft_adapted']:.2f}s  "
                f"event after {r['detect_s']:.2f}s  events={r['events']}  strategy={r['strategy']}  "
                f"verbatim overlap {r['overlap']:.0%}"
            )
        else:
            print(f"run {i:2d} FAIL  {r.get('fail')}")
    ok = [r for r in results if r["ok"]]
    print(f"\n{len(ok)}/{len(results)} runs passed")
    if ok:
        med = lambda k: statistics.median(r[k] for r in ok)  # noqa: E731
        print(f"median TTFT normal {med('ttft_normal'):.2f}s, adapted {med('ttft_adapted'):.2f}s, "
              f"event latency {med('detect_s'):.2f}s, verbatim overlap {med('overlap'):.0%}")
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
