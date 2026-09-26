"""The single LLM integration (OpenAI Chat Completions, streaming) + an offline mock.

* ``OpenAIChat`` — the real provider. The API key stays in this process (env /
  .env); it is never logged or returned to the browser.
* ``MockLLM`` — explicitly labelled offline scripted tutor (``EH_LLM_PROVIDER=mock``)
  for tests, CI and rehearsals without internet. Every mock answer says so, and the
  UI shows a "Mock LLM" badge. It is not a second LLM integration.

Timeouts (first token / idle / total) are enforced by the chat route, which also
closes the upstream stream on cancel so no tokens are generated for nobody.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from .context import ADAPTATION_MARKER

log = logging.getLogger("extrahorizon.llm")

_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-*]{6,}")


@dataclass(frozen=True)
class StreamInfo:
    """Yielded once, after the last text chunk: which model answered and why it stopped.
    (Per-stream, so concurrent sessions never read each other's values.)"""

    model: str
    finish_reason: str | None = None


class LLMError(Exception):
    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def public(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


def _clean(text: str, limit: int = 220) -> str:
    text = _KEY_RE.sub("sk-…", str(text)).replace("\n", " ").strip()
    return text[:limit]


def map_openai_error(e: BaseException) -> LLMError:
    import openai

    if isinstance(e, LLMError):
        return e
    if isinstance(e, openai.AuthenticationError):
        return LLMError("llm_auth", "OpenAI rejected the API key (401). Check OPENAI_API_KEY in .env.", False)
    if isinstance(e, openai.PermissionDeniedError):
        return LLMError("llm_forbidden", "This API key is not allowed to use the configured model (403).", False)
    if isinstance(e, openai.NotFoundError):
        return LLMError("llm_model", "The configured model is not available for this API key (404).", False)
    if isinstance(e, openai.RateLimitError):
        return LLMError("llm_rate_limited", "OpenAI rate limit or quota reached (429). Wait a moment, then retry.", True)
    if isinstance(e, openai.APITimeoutError):
        return LLMError("llm_timeout", "OpenAI did not respond in time. Retry.", True)
    if isinstance(e, openai.APIConnectionError):
        return LLMError("llm_unreachable", "Could not reach OpenAI — check the internet connection, then retry.", True)
    if isinstance(e, openai.InternalServerError):
        return LLMError("llm_upstream", "OpenAI returned a server error. Retry in a moment.", True)
    if isinstance(e, openai.BadRequestError):
        return LLMError("llm_bad_request", f"OpenAI rejected the request: {_clean(getattr(e, 'message', e))}", False)
    if isinstance(e, openai.APIStatusError):
        code = getattr(e, "status_code", 0) or 0
        return LLMError("llm_upstream", f"OpenAI returned HTTP {code}.", code >= 500 or code == 0)
    if isinstance(e, (TimeoutError, asyncio.TimeoutError)):
        return LLMError("llm_timeout", "The model did not respond in time. Retry.", True)
    return LLMError("llm_error", f"LLM error ({type(e).__name__}). Retry.", True)


class BaseLLM:
    provider: str = "base"
    model: str = ""

    def __init__(self) -> None:
        self.last_error: dict[str, Any] | None = None
        self.last_ok_at: float | None = None

    @property
    def configured(self) -> bool:
        return True

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "configured": self.configured,
            "reachable": None,
            "last_error": self.last_error,
        }

    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str | StreamInfo]:
        """Yields text chunks, then exactly one ``StreamInfo``."""
        raise NotImplementedError

    async def ping(self) -> bool:
        return self.configured

    async def aclose(self) -> None:
        return None

    def note_ok(self) -> None:
        self.last_ok_at = time.time()
        self.last_error = None

    def note_error(self, err: LLMError) -> None:
        self.last_error = {"code": err.code, "message": err.message, "at": time.time()}


class OpenAIChat(BaseLLM):
    provider = "openai"

    def __init__(self, settings: Any) -> None:
        super().__init__()
        self.settings = settings
        self.model = settings.llm_model
        self.fallback_model = settings.llm_fallback_model or None
        self._effort = (settings.llm_reasoning_effort or "").strip() or None
        self._effort_ok: dict[str, bool] = {}
        self._client = None
        key = settings.openai_api_key.get_secret_value().strip() if settings.openai_api_key else ""
        self._configured = bool(key)
        if self._configured:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=key,
                base_url=settings.openai_base_url or None,
                max_retries=0,  # the UI offers Retry; hidden retries would blow the latency budget
                timeout=max(settings.llm_idle_timeout_s, settings.llm_first_token_timeout_s) + 5.0,
            )

    @property
    def configured(self) -> bool:
        return self._configured

    def build_request(self, messages: list[dict[str, str]], model: str) -> dict[str, Any]:
        req: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_completion_tokens": self.settings.llm_max_output_tokens,
        }
        if self._effort and self._effort_ok.get(model, True):
            req["reasoning_effort"] = self._effort
        return req

    async def _open(self, messages: list[dict[str, str]]):
        import openai

        if self._client is None:
            raise LLMError("llm_not_configured", "OPENAI_API_KEY is not set on the server (.env).", False)
        candidates = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            candidates.append(self.fallback_model)
        for model in candidates:
            for _ in range(2):  # 2nd try: without reasoning_effort if the model rejects it
                try:
                    stream = await self._client.chat.completions.create(**self.build_request(messages, model))
                    return stream, model
                except openai.BadRequestError as e:
                    if "reasoning" in str(e).lower() and self._effort_ok.get(model, True) and self._effort:
                        log.info("model %s rejected reasoning_effort — retrying without it", model)
                        self._effort_ok[model] = False
                        continue
                    raise map_openai_error(e) from e
                except openai.NotFoundError:
                    log.warning("model %s not available for this key", model)
                    break  # → fallback model
                except openai.OpenAIError as e:
                    raise map_openai_error(e) from e
        raise LLMError("llm_model", f"Model '{self.model}' is not available for this API key.", False)

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str | StreamInfo]:
        import openai

        stream, model = await self._open(messages)
        finish: str | None = None
        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish = getattr(choice, "finish_reason", None) or finish
                delta = choice.delta
                text = getattr(delta, "content", None) if delta is not None else None
                if text:
                    yield text
            yield StreamInfo(model=getattr(stream, "model", None) or model, finish_reason=finish)
        except openai.OpenAIError as e:
            raise map_openai_error(e) from e
        finally:
            try:
                await stream.close()
            except Exception:  # noqa: BLE001
                pass

    async def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            await asyncio.wait_for(self._client.models.retrieve(self.model), 5.0)
            return True
        except Exception as e:  # noqa: BLE001
            if self.fallback_model:
                try:
                    await asyncio.wait_for(self._client.models.retrieve(self.fallback_model), 5.0)
                    return True
                except Exception:  # noqa: BLE001
                    pass
            self.note_error(map_openai_error(e))
            return False

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------- offline mock

_MOCK_NOTE = "_Offline mock tutor — scripted answer, no LLM was called._\n\n"

_MOCK_RECURSION = (
    "**Recursion** is when a function solves a problem by calling *itself* on a smaller version "
    "of the same problem.\n\nEvery recursive function needs two parts:\n\n"
    "1. **Base case** — when to stop.\n2. **Recursive case** — shrink the problem and call again.\n\n"
    "```python\ndef factorial(n):\n    if n == 0:        # base case\n        return 1\n"
    "    return n * factorial(n - 1)  # recursive case\n```\n\n"
    "`factorial(3)` → `3 * factorial(2)` → `3 * 2 * factorial(1)` → `3 * 2 * 1 * 1` = **6**."
)

_MOCK_ADAPTED = {
    "analogy": (
        "Think of **Russian nesting dolls**. To reach the smallest doll you open one doll, then do the "
        "*exact same thing* to the doll inside — until a doll doesn't open. That last doll is the stop.\n\n"
        "**Example:** counting down from 3 — say 3, then *count down from 2*; say 2, then *count down from 1*; "
        "say 1, then stop at 0.\n\n1. Do one small piece of work.\n2. Hand the smaller rest to the same process.\n"
        "3. Stop at the simplest case."
    ),
    "trace": (
        "Let's trace `sum_to(3)`, where `sum_to(n) = n + sum_to(n - 1)` and `sum_to(0) = 0`:\n\n"
        "| call | waits for | returns |\n|---|---|---|\n| sum_to(3) | 3 + sum_to(2) | 6 |\n"
        "| sum_to(2) | 2 + sum_to(1) | 3 |\n| sum_to(1) | 1 + sum_to(0) | 1 |\n| sum_to(0) | — | 0 |\n\n"
        "**Core idea:** each call waits for a smaller call, and answers flow back up once the base case returns."
    ),
    "plain": (
        "Imagine you're at the back of a long line and want to know your place. You ask the person ahead "
        "\"what's your number?\" They ask the person ahead of them, and so on. The first person just says "
        "\"1\". Then everyone adds 1 on the way back.\n\n**Takeaway:** a big question gets answered by asking "
        "the same, smaller question until it's easy."
    ),
}


class MockLLM(BaseLLM):
    provider = "mock"
    model = "mock-tutor (offline)"

    def __init__(self, delay_s: float = 0.03) -> None:
        super().__init__()
        self.delay_s = delay_s

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str | StreamInfo]:
        note = next(
            (m["content"] for m in messages[1:] if m["role"] == "system" and m["content"].startswith(ADAPTATION_MARKER)),
            None,
        )
        question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if note is not None:
            low = note.lower()
            key = "trace" if "step at a time" in low else "plain" if "twelve-year-old" in low else "analogy"
            body = _MOCK_ADAPTED[key]
        elif "recurs" in question.lower():
            body = _MOCK_RECURSION
        else:
            body = (
                f"You asked: *{question[:160]}*\n\nIn live mode the OpenAI model answers here. "
                "The offline mock only knows the recursion demo script."
            )
        for piece in re.findall(r"\S+\s*|\s+", _MOCK_NOTE + body):
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield piece
        yield StreamInfo(model=self.model, finish_reason="stop")


def create_llm(settings: Any) -> BaseLLM:
    if settings.llm_provider == "mock":
        return MockLLM(settings.mock_llm_delay_s)
    return OpenAIChat(settings)
