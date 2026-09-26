"""One tutor turn: LLM stream → text deltas → TTS chunks → voice audio.

``TurnRunner.events()`` is consumed by the SSE chat route (typed questions) and by the
live voice socket (spoken questions). The LLM is read by a background producer so that:

* a *speculative* turn (started on the live transcript the moment the learner stops
  talking) keeps generating text and voice while its outputs are held behind
  ``plan.gate``; the final transcript either confirms it (outputs released — saves the
  ~0.4 s transcription wait) or discards it silently;
* every chunk the splitter releases goes to Fish immediately (first audio after the first
  clause, not after the whole answer); the audio keeps playing after the text is done;
* barge-in / stop / a newer question / reset cancel the turn: the voice stops at once and
  an interrupted answer is committed with what was generated so far (marked interrupted).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any, Protocol

import anyio

from .context import after_tools_note
from .coord.refs import finding_ids, project_refs
from .coord.report import grounding_check
from .coord.tools import TOOL_SPECS, ToolRunner
from .llm import BaseLLM, LLMError, StreamInfo, ToolCalls, map_openai_error
from .sessions import ChatCancelled, ChatPlan, Session
from .voice.fish import TtsEngine, TtsError
from .voice.splitter import TtsSplitter

HEARTBEAT_S = 5.0  # an analysis waiting on the county's services still sends progress this often
MAX_TOOL_ROUNDS = 3  # look-ups per answer (then she answers with what she has)
TOOL_TIMEOUT_S = 20.0  # one look-up at most (a live re-check reads the county's service)
ANALYSIS_KEYS = ("mode", "report_id", "check", "live", "tools")  # what an answer keeps about its analysis
_FID_TEXT = re.compile(r"\bF\d{1,6}\b")
REPORT_CUT_NOTE = ("\n\n*(The written report stops here: it reached its length limit. The map and the "
                   "Findings tab list every finding.)*")

log = logging.getLogger("extrahorizon.turns")


class AudioSink(Protocol):
    voice_out: bool

    def audio_begin(self, turn_no: int, kind: str) -> None: ...
    def send_audio(self, turn_no: int, pcm: bytes) -> None: ...
    def audio_end(self, turn_no: int, failed: str = "") -> None: ...
    def audio_stop(self, turn_no: int) -> None: ...
    def send(self, msg: dict[str, Any]) -> None: ...


async def _next_or_cancel(agen: AsyncIterator[Any], timeout: float, cancel: asyncio.Event) -> tuple[str, Any]:
    """Next chunk, or 'end' / 'cancel' / 'timeout' — whichever comes first."""
    if cancel.is_set():
        return "cancel", None
    nxt = asyncio.ensure_future(agen.__anext__())
    stop = asyncio.ensure_future(cancel.wait())
    try:
        done, _ = await asyncio.wait({nxt, stop}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    except BaseException:
        nxt.cancel()
        stop.cancel()
        raise
    stop.cancel()
    if nxt in done:
        try:
            return "chunk", nxt.result()
        except StopAsyncIteration:
            return "end", None
    nxt.cancel()
    with contextlib.suppress(BaseException):
        await nxt
    return ("cancel", None) if stop in done else ("timeout", None)


class Speaker:
    """Streams one reply to Fish and its audio to the learner's browser."""

    def __init__(self, tts: TtsEngine, sink: AudioSink, plan: ChatPlan, settings: Any, session: Session,
                 first_paragraph_only: bool = False) -> None:
        self.tts = tts
        self.sink = sink
        self.plan = plan
        self.s = settings
        self.session = session
        self.splitter = TtsSplitter(settings.tts_first_chunk_chars, settings.tts_chunk_chars)
        self.tts_session = None
        self._pump: asyncio.Task | None = None
        self.aborted = False
        self.ok = False
        self.began = False  # answer audio has been sent to the browser
        self.first_audio_ms: int | None = None
        self._t0 = time.monotonic()
        # analysis reports: only the spoken summary (the first paragraph) is voiced
        self.first_paragraph_only = first_paragraph_only
        self._said = ""
        self._closed = False

    async def start(self) -> bool:
        try:
            self.tts_session = await self.tts.open_session()
            await self.tts_session.begin()  # voice loads while the LLM writes its first words
        except (TtsError, Exception) as e:  # noqa: BLE001 — voice failure never breaks the chat
            msg = e.message if isinstance(e, TtsError) else f"voice error ({type(e).__name__})"
            log.warning("tts unavailable for turn %s: %s", self.plan.turn_no, msg)
            self.sink.send({"type": "tts_error", "turn_no": self.plan.turn_no, "message": msg})
            return False
        if self.plan.cancel.is_set() or not self.session.is_current(self.plan):
            # cancelled while the voice was connecting (a slow dial): registering now would
            # silence the newer turn's voice
            await self.tts_session.abort()
            return False
        self.ok = True
        self.session.set_speaker(self)
        self._pump = asyncio.create_task(self._pump_audio())
        return True

    async def feed(self, delta: str) -> None:
        if not self.ok or self.aborted or self._closed:
            return
        if self.first_paragraph_only:
            text = self._said + delta
            cut = text.find("\n", 12)  # any new line (a heading, a list, a table) ends the spoken summary
            if cut >= 0:  # the written report starts here: say the summary and stop
                delta = text[len(self._said):cut]
                self._said = text[:cut]
                for chunk in self.splitter.feed(delta):
                    await self.tts_session.send(chunk)  # type: ignore[union-attr]
                await self._close_voice()
                return
            self._said = text
        for chunk in self.splitter.feed(delta):
            await self.tts_session.send(chunk)  # type: ignore[union-attr]

    async def _close_voice(self) -> None:
        self._closed = True
        if self.first_paragraph_only:
            self.plan.voice_done = True  # the rest of the report is written silently
        for chunk in self.splitter.flush():
            await self.tts_session.send(chunk)  # type: ignore[union-attr]
        await self.tts_session.finish()  # type: ignore[union-attr]

    async def finish(self) -> None:
        if self.ok and not self.aborted and not self._closed:
            await self._close_voice()

    async def _pump_audio(self) -> None:
        try:
            async for pcm in self.tts_session.audio():  # type: ignore[union-attr]
                if self.aborted:
                    break
                if not self.plan.gate.is_set():
                    await self.plan.gate.wait()  # speculative: hold the voice until confirmed
                if self.aborted:
                    break
                if not self.began:
                    self.began = True
                    self.first_audio_ms = int((time.monotonic() - self._t0) * 1000)
                    self.sink.audio_begin(self.plan.turn_no, "answer")
                self.sink.send_audio(self.plan.turn_no, pcm)
        except asyncio.CancelledError:
            pass
        finally:
            if not self.aborted and self.began:
                failed = getattr(self.tts_session, "failed", "") or ""
                self.sink.audio_end(self.plan.turn_no, failed)
            elif not self.aborted:
                failed = getattr(self.tts_session, "failed", "") or ""
                if failed:
                    self.sink.send({"type": "tts_error", "turn_no": self.plan.turn_no, "message": failed})
            self.session.clear_speaker(self)

    def abort_nowait(self) -> None:
        """Stop talking now (called from sync code: barge-in, supersede, reset)."""
        if self.aborted:
            return
        self.aborted = True
        if self.began:
            # only audio that reached the browser needs stopping; a speculative voice that
            # was never released must not silence the filler / the replacement answer that
            # share its turn number
            self.sink.audio_stop(self.plan.turn_no)
        if self._pump is not None:
            self._pump.cancel()
        if self.tts_session is not None:
            asyncio.get_running_loop().create_task(self.tts_session.abort())


class TurnRunner:
    def __init__(self, session: Session, plan: ChatPlan, llm: BaseLLM, settings: Any,
                 tts: TtsEngine | None = None, sink: AudioSink | None = None, coord: Any = None) -> None:
        self.session = session
        self.coord = coord  # the utility-coordination analysis service (coord/service.py)
        self.plan = plan
        self.llm = llm
        self.s = settings
        self.tts = tts
        self.sink = sink
        self._q: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
        self.speaker: Speaker | None = None
        self.tools: ToolRunner | None = None
        self._focused = False  # the map already follows this turn (question, a look-up or her answer)
        self._picked = False  # her answer has moved the map (once per question / look-up)
        self._answer_from = 0  # her answer after the last look-up starts at this part

    @property
    def voice(self) -> bool:
        return bool(self.tts is not None and getattr(self.tts, "configured", False)
                     and self.sink is not None and getattr(self.sink, "voice_out", False))

    async def events(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        plan = self.plan
        producer = asyncio.create_task(self._produce())
        try:
            if not plan.gate.is_set():
                gate = asyncio.ensure_future(plan.gate.wait())
                cancel = asyncio.ensure_future(plan.cancel.wait())
                try:  # (an error before confirmation is shown once confirmed — or vanishes with the plan)
                    await asyncio.wait({gate, cancel}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    gate.cancel()
                    cancel.cancel()
                if not plan.gate.is_set():
                    # the final transcript contradicted the speculative one: vanish quietly
                    with contextlib.suppress(BaseException):
                        await producer
                    yield "discarded", {"turn_no": plan.turn_no}
                    return
            yield "meta", plan.meta(self.llm.model, self.voice)
            while True:
                ev = await self._q.get()
                if ev is None:
                    return
                yield ev
        finally:
            if not producer.done():
                producer.cancel()
                with anyio.CancelScope(shield=True):
                    with contextlib.suppress(BaseException):
                        await producer

    async def _await_release(self, timeout: float) -> None:
        plan = self.plan
        gate = asyncio.ensure_future(plan.gate.wait())
        cancel = asyncio.ensure_future(plan.cancel.wait())
        try:
            await asyncio.wait({gate, cancel}, timeout=max(0.1, timeout), return_when=asyncio.FIRST_COMPLETED)
        finally:
            gate.cancel()
            cancel.cancel()
        if plan.cancel.is_set():
            raise ChatCancelled(plan.cancel_reason[0] if plan.cancel_reason else "discarded")
        if not plan.gate.is_set():  # never confirmed (the transcript was lost): drop the plan
            self.session.discard_plan(plan)
            raise ChatCancelled("discarded")

    async def _run_analysis(self) -> None:
        """An analysis turn: read → verify → compare the utilities' plans, then answer from it."""
        plan, session = self.plan, self.session
        put = self._q.put_nowait
        an = plan.analysis if plan.analysis is not None else {}
        if not plan.gate.is_set():
            # asked out loud: run it only once the final transcript confirms the question — a discarded guess
            # must neither read the county's data nor leave an analysis behind
            await self._await_release(self.s.stt_final_timeout_s + 5.0)
        put(("analysis", {"state": "running"}))
        an["started"] = True
        report: dict[str, Any]
        if self.coord is None:
            report = {"error": "the analysis is not enabled on this server"}
        else:
            from .coord.arcgis import SourceError

            params = self.coord.params(session.coord_params)
            task = asyncio.ensure_future(self.coord.analyze(
                params, progress=lambda m: put(("analysis", {**m, "state": "progress", "phase": m.get("state")})),
                refresh=bool(an.get("refresh"))))
            stop = asyncio.ensure_future(plan.cancel.wait())
            try:
                while not task.done() and not stop.done():
                    await asyncio.wait({task, stop}, timeout=HEARTBEAT_S, return_when=asyncio.FIRST_COMPLETED)
                    if not task.done() and not stop.done():  # a slow county service: keep the stream alive
                        put(("analysis", {"state": "progress", "phase": "waiting", "step": "wait"}))
            finally:
                stop.cancel()
            if not task.done():
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
                raise ChatCancelled(plan.cancel_reason[0] if plan.cancel_reason else "superseded")
            try:
                report = task.result()
            except SourceError as e:
                report = {"error": f"the county's data could not be read: {e.message}"}
            except Exception as e:  # noqa: BLE001 — say it failed; never make up results
                log.exception("analysis failed")
                report = {"error": f"the analysis failed on the server ({type(e).__name__})"}
        if report.get("error"):
            an["live"] = {"state": "error", "message": report["error"]}
        else:
            if session.is_current(plan):
                session.analysis = report
            an["report_id"] = report["id"]
            s = report["summary"]
            an["live"] = {"state": "ready", "report_id": report["id"], "findings": s["findings"],
                          "by_category": s["by_category"], "projects": s["projects_verified"],
                          "plans": s["plans"], "offline": report.get("offline", False)}
        put(("analysis", an["live"]))
        plan.llm_messages = session.analysis_messages(plan, report)

    # ------------------------------------------------------------------ tools and the map
    def _tool_runner(self) -> ToolRunner | None:
        """Her look-ups for an analysis answer (the whole analysis on screen, not only the fact sheet)."""
        report = self.session.analysis
        if not self.plan.analysis or self.coord is None or not report or report.get("error"):
            return None

        def emit(event: str, data: dict[str, Any]) -> None:
            plan = self.plan
            if plan.cancel.is_set() or not self.session.is_current(plan):
                return  # a stopped or replaced turn moves nothing any more
            if event == "focus":
                self._focused = True
                if data.get("source") == "tool":
                    self._picked = False  # a new look-up: what she says next may pick one of its findings
            self._q.put_nowait((event, data))

        return ToolRunner(report, self.coord, emit)

    def _facts(self) -> str:
        """What she may state: the fact sheet and everything her tools returned."""
        extra = "\n".join(self.tools.facts) if self.tools is not None else ""
        return f"{self.plan.analysis_sheet or ''}\n{extra}"

    def _focus_question(self) -> None:
        """The map follows the question at once: "what about F146?" (also spoken), a project ID."""
        t = self.tools
        if t is None:
            return
        q = self.plan.user_msg["text"]
        ids = [i for i in finding_ids(q) if i in t.by_id]
        if ids:
            t.focus(ids, ", ".join(ids), source="question")
            return
        pids = project_refs(q, t.report)
        p = next((x for x in t.projects.values() if pids and str(x.get("project_id")) == pids[0]), None)
        if p is not None:
            t.focus([f["id"] for f in t.all if p["uid"] in (f["a"], f["b"])], p["name"], project=p["uid"],
                    source="question")

    def _focus_answer(self, parts: list[str]) -> None:
        """…and her answer: the first finding she names. When the question or a look-up already put findings on
        the map, the first of THOSE she names is picked out of them (the spotlight stays): "the closest is F138"
        selects F138 among the 35 she looked up; a finding she only mentions in passing moves nothing."""
        t = self.tools
        if t is None or self._picked or (self._focused and not t.spot):
            return
        text = "".join(parts[max(self._answer_from, len(parts) - 40):])
        for x in _FID_TEXT.finditer(text):
            fid = x.group(0)
            # an ID at the very end may still be growing ("F114" + "6" = F1146): only one followed by something counts
            if x.end() >= len(text) or fid not in t.by_id or (self._focused and fid not in t.spot):
                continue
            self._picked = True
            if not self._focused:
                t.focus([fid], fid, source="answer")
            elif len(t.spot) > 1:
                t.focus([fid], fid, source="answer", within=True)
            return

    async def _tool(self, call: dict[str, str], budget: float) -> str:
        """One look-up, stopped by Stop / a newer question and by the answer's time budget; while it runs (a live
        re-check reads the county's service) the stream keeps sending, so no watchdog gives up on it."""
        plan = self.plan
        task = asyncio.ensure_future(self.tools.run(call["name"], call["arguments"]))  # type: ignore[union-attr]
        stop = asyncio.ensure_future(plan.cancel.wait())
        deadline = time.monotonic() + max(1.0, min(budget, TOOL_TIMEOUT_S))
        try:
            while not task.done() and not stop.done():
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                await asyncio.wait({task, stop}, timeout=min(HEARTBEAT_S, left), return_when=asyncio.FIRST_COMPLETED)
                if not task.done() and not stop.done():
                    self._q.put_nowait(("working", {"what": "look-up", "name": call["name"]}))
        finally:
            stop.cancel()
        if task.done():
            return task.result()
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
        if plan.cancel.is_set():
            raise ChatCancelled(plan.cancel_reason[0] if plan.cancel_reason else "superseded")
        return f"error: {call['name']} took too long — answer without it"

    def _analysis_ended(self) -> None:
        """A turn that started the analysis ends early (stop, a newer question, an error): tell the browser the
        analysis is not coming, so nothing keeps spinning."""
        an = self.plan.analysis
        if an and an.get("started") and not an.get("live"):
            an["live"] = {"state": "cancelled"}
            self._q.put_nowait(("analysis", an["live"]))

    async def _produce(self) -> None:
        plan, session, llm, s = self.plan, self.session, self.llm, self.s
        put = self._q.put_nowait
        t0 = time.monotonic()
        committed = False
        parts: list[str] = []
        ttft: float | None = None
        info = StreamInfo(model=llm.model)
        agen = None
        try:
            if not llm.configured:
                raise LLMError("llm_not_configured", "OPENAI_API_KEY is not set on the server. Put it in .env and restart.", False)
            if plan.analysis and plan.analysis.get("mode") == "run":
                await self._run_analysis()
            t_llm = time.monotonic()  # the LLM's time budget (and its first-token time) starts after the analysis
            total_s = s.coord_llm_total_timeout_s if plan.analysis else s.llm_total_timeout_s
            if self.voice:
                self.speaker = Speaker(self.tts, self.sink, plan, s, session,  # type: ignore[arg-type]
                                       first_paragraph_only=bool(plan.analysis))
                if not await self.speaker.start():
                    self.speaker = None
            self.tools = self._tool_runner()
            self._focus_question()
            messages = list(plan.llm_messages)
            rounds = 0
            # her tools serve follow-ups: the first report is written from the fact sheet, which already holds
            # everything it covers (look-ups there only made it slower and longer); the map follows it anyway
            offer = self.tools is not None and (plan.analysis or {}).get("mode") == "context"
            while True:  # one LLM call per round; a round that asks for tools gets their results and goes on
                # after the last look-up round the tools stay declared (the history has tool calls) but are off
                tools = TOOL_SPECS if offer else None
                choice = "auto" if rounds < MAX_TOOL_ROUNDS else "none"
                agen = llm.stream(messages, max_tokens=s.coord_max_output_tokens if plan.analysis else None,
                                  **({"tools": tools, "tool_choice": choice} if tools else {}))
                calls: tuple[dict[str, str], ...] = ()
                said: list[str] = []
                while True:
                    budget = t_llm + total_s - time.monotonic()
                    step = s.llm_first_token_timeout_s if ttft is None else s.llm_idle_timeout_s
                    timeout = min(step, budget)
                    if timeout <= 0:
                        raise LLMError("llm_timeout", "The answer took too long. Retry.", True)
                    kind, chunk = await _next_or_cancel(agen, timeout, plan.cancel)
                    if kind == "end":
                        break
                    if kind == "cancel":  # the first reason is the cause (later ones are follow-ups)
                        raise ChatCancelled(plan.cancel_reason[0] if plan.cancel_reason else "superseded")
                    if kind == "timeout":
                        raise LLMError("llm_timeout", "The model did not start answering in time. Retry."
                                       if ttft is None else "The answer stalled. Retry.", True)
                    if isinstance(chunk, StreamInfo):
                        info = chunk
                        continue
                    if isinstance(chunk, ToolCalls):
                        calls = chunk.calls
                        continue
                    if chunk:
                        if ttft is None:
                            ttft = time.monotonic() - t_llm
                        if not said and parts and not parts[-1].endswith((" ", "\n")) and not chunk[:1].isspace():
                            chunk = " " + chunk  # the answer goes on after a look-up
                        said.append(chunk)
                        parts.append(chunk)
                        plan.text_so_far.append(chunk)
                        put(("delta", {"text": chunk}))
                        if self.speaker is not None:
                            await self.speaker.feed(chunk)
                        self._focus_answer(parts)
                with anyio.CancelScope(shield=True):
                    with contextlib.suppress(BaseException):
                        await agen.aclose()  # type: ignore[attr-defined]
                agen = None
                if not calls or self.tools is None or choice == "none":  # (no look-ups after the last round)
                    break
                rounds += 1
                ids = [c.get("id") or f"call_{rounds}_{i}" for i, c in enumerate(calls)]
                messages.append({"role": "assistant", "content": "".join(said) or None, "tool_calls": [
                    {"id": cid, "type": "function", "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                    for cid, c in zip(ids, calls)]})
                if not plan.gate.is_set():
                    # a spoken question: nothing reads the county's service for a guess the transcript may discard
                    await self._await_release(s.stt_final_timeout_s + 5.0)
                for cid, c in zip(ids, calls):
                    before = len(self.tools.used)
                    result = await self._tool(c, t_llm + total_s - time.monotonic())
                    log.info("turn %s tool %s(%s) → %d chars", plan.turn_no, c["name"], (c["arguments"] or "")[:120],
                             len(result))
                    messages.append({"role": "tool", "tool_call_id": cid, "content": result})
                    if len(self.tools.used) > before:
                        put(("tool", dict(self.tools.used[-1])))
                messages.append({"role": "system", "content": after_tools_note(plan.user_msg["text"])})
                self._answer_from = len(parts)  # what she names from here on is about these look-ups
            if plan.analysis and info.finish_reason == "length" and parts:
                # the written report hit its token budget: say so rather than stop mid-sentence
                put(("delta", {"text": REPORT_CUT_NOTE}))
                parts.append(REPORT_CUT_NOTE)
                plan.text_so_far.append(REPORT_CUT_NOTE)
            text = "".join(parts).strip()
            if not text:
                raise LLMError("llm_empty", "The model returned an empty answer. Retry.", True)
            if plan.analysis and plan.analysis_sheet:
                # every number, date and finding ID she wrote must come from the fact sheet or her look-ups
                plan.analysis["check"] = grounding_check(text, self._facts())
            if self.tools is not None and self.tools.used:
                plan.analysis["tools"] = self.tools.used  # type: ignore[index]
            if self.speaker is not None:
                await self.speaker.finish()
            if not plan.gate.is_set():
                # speculative and already complete: it may be committed only once the final
                # transcript has confirmed it (a mismatch must leave no trace in the history)
                await self._await_release(t0 + s.llm_total_timeout_s + s.stt_final_timeout_s - time.monotonic())
            done = session.commit_chat(
                plan, text, model=info.model, ttft_ms=None if ttft is None else int(ttft * 1000),
                elapsed_ms=int((time.monotonic() - t0) * 1000), finish_reason=info.finish_reason,
            )
            committed = True
            llm.note_ok()
            log.info("turn %s done (%s) ttft=%sms", plan.turn_no, plan.source, done["ttft_ms"])
            if plan.analysis:
                done["analysis"] = {k: v for k, v in plan.analysis.items() if k in ANALYSIS_KEYS}
            put(("done", done))
        except ChatCancelled as c:
            if self.speaker is not None:
                self.speaker.abort_nowait()
            if c.code not in ("discarded", "merged"):
                self._analysis_ended()
            if c.code == "interrupted" and not plan.gate.is_set():
                # stopped before the question was even confirmed: the learner never saw it
                put(("dropped", {"reason": "stopped"}))
            elif c.code == "interrupted" and session.is_current(plan):
                partial = "".join(parts).strip()
                if partial:
                    if plan.analysis and plan.analysis_sheet:
                        plan.analysis["check"] = grounding_check(partial, self._facts())
                    if plan.analysis and self.tools is not None and self.tools.used:
                        plan.analysis["tools"] = self.tools.used
                    done = session.commit_chat(plan, partial, model=info.model,
                                               ttft_ms=None if ttft is None else int(ttft * 1000),
                                               elapsed_ms=int((time.monotonic() - t0) * 1000), interrupted=True)
                    committed = True
                    if plan.analysis:
                        done["analysis"] = {k: v for k, v in plan.analysis.items() if k in ANALYSIS_KEYS}
                    put(("interrupted", done))
                else:
                    put(("error", {"code": "interrupted", "message": "Interrupted.", "retryable": True}))
            elif c.code in ("discarded", "merged"):
                # nothing is committed; if the turn was already visible the client removes it
                put(("dropped", {"reason": c.code}))
            else:
                msg = "The session was reset." if c.code == "reset" else "A newer request replaced this one."
                put(("error", {"code": c.code, "message": msg, "retryable": c.code != "reset"}))
        except asyncio.CancelledError:
            if self.speaker is not None:
                self.speaker.abort_nowait()
            raise
        except Exception as e:  # noqa: BLE001 — every failure ends the turn with a clear error
            if self.speaker is not None:
                self.speaker.abort_nowait()
            self._analysis_ended()
            err = e if isinstance(e, LLMError) else map_openai_error(e)
            llm.note_error(err)
            log.warning("turn %s failed: %s", plan.turn_no, err.code)
            put(("error", err.public()))
        finally:
            if not committed:
                session.abort_chat(plan)
            if agen is not None:
                with anyio.CancelScope(shield=True):
                    with contextlib.suppress(BaseException):
                        await agen.aclose()  # type: ignore[attr-defined]
            plan.settled.set()
            put(None)
