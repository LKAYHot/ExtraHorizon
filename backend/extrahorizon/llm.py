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

    def stream(self, messages: list[dict[str, str]], max_tokens: int | None = None) -> AsyncIterator[str | StreamInfo]:
        """Yields text chunks, then exactly one ``StreamInfo`` (``max_tokens``: a longer answer, e.g. a report)."""
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

    def build_request(self, messages: list[dict[str, str]], model: str, max_tokens: int | None = None) -> dict[str, Any]:
        req: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_completion_tokens": max_tokens or self.settings.llm_max_output_tokens,
        }
        if self._effort and self._effort_ok.get(model, True):
            req["reasoning_effort"] = self._effort
        return req

    async def _open(self, messages: list[dict[str, str]], max_tokens: int | None = None):
        import openai

        if self._client is None:
            raise LLMError("llm_not_configured", "OPENAI_API_KEY is not set on the server (.env).", False)
        candidates = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            candidates.append(self.fallback_model)
        for model in candidates:
            for _ in range(2):  # 2nd try: without reasoning_effort if the model rejects it
                try:
                    stream = await self._client.chat.completions.create(**self.build_request(messages, model, max_tokens))
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

    async def stream(self, messages: list[dict[str, str]], max_tokens: int | None = None) -> AsyncIterator[str | StreamInfo]:
        import openai

        stream, model = await self._open(messages, max_tokens)
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

_MOCK_RECURSION = (
    "[huffy and flustered] Hmph. It's not like I wanted to explain this to you or anything. "
    "[smug, teasing] Recursion is when a function solves a problem by calling itself on a smaller piece of it. "
    "[confident] Every recursive function needs a base case that stops it, and a step that shrinks the problem. "
    "[soft, a little embarrassed] Like counting down from three: say three, then count down from two, until you hit zero. "
    "[chuckling] Even you can follow that, right?"
)
_MOCK_GENERIC = (
    "[exasperated] Ugh, fine. [calm] This is the offline mock tutor, so I only know the recursion demo. "
    "[proud] Ask me about recursion instead!"
)


class MockLLM(BaseLLM):
    """Labelled offline scripted tutor (``EH_LLM_PROVIDER=mock``): no network, no key.
    The UI shows a "Mock LLM" badge; every answer is the same script."""

    provider = "mock"
    model = "mock-tutor (offline)"

    def __init__(self, delay_s: float = 0.03) -> None:
        super().__init__()
        self.delay_s = delay_s

    async def stream(self, messages: list[dict[str, str]], max_tokens: int | None = None) -> AsyncIterator[str | StreamInfo]:
        question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        sheet = next((m["content"] for m in messages if m["role"] == "system"
                      and m["content"].startswith("[Verified utility-coordination analysis")), None)
        if sheet:
            body = _mock_analysis(sheet)
        else:
            body = _MOCK_RECURSION if ("recurs" in question.lower() or "рекурс" in question.lower()) else _MOCK_GENERIC
        for piece in re.findall(r"\S+\s*|\s+", body):
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield piece
        yield StreamInfo(model=self.model, finish_reason="stop")


def _mock_analysis(sheet: str) -> str:
    """The offline tutor's analysis answer: lines of the fact sheet, verbatim (labelled mock)."""
    lines = sheet.splitlines()
    pick = lambda prefix: next((ln for ln in lines if ln.startswith(prefix)), "")  # noqa: E731
    findings = [ln for ln in lines if ln[:1] == "F" and " — " in ln][:3]
    body = ["[confident] I compared the utilities' public construction plans. "
            "[calm] This is the offline mock tutor, so the report below repeats the verified facts word for word.", "",
            "### What overlaps", *(f"- {ln}" for ln in findings), "", "### Where the data comes from",
            f"- {pick('Data:')}", f"- {pick('Records received:')}", f"- {pick('County cross-check')}"]
    return "\n".join(body)


def create_llm(settings: Any) -> BaseLLM:
    if settings.llm_provider == "mock":
        return MockLLM(settings.mock_llm_delay_s)
    return OpenAIChat(settings)
