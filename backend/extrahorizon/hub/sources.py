"""The public sources the hub reads — all without keys, all read-only:

* Stack Exchange API 2.3 (Stack Overflow questions and answers; its top answerers per tag; questions nobody has
  answered yet; 300 requests a day per IP without a key; content is CC BY-SA, so every excerpt keeps its author and
  licence),
* GitHub REST API (issue, repository and user search — 10 searches a minute without a token; the public profile and
  repositories of a person found by skill and city, or named on a board card with its box ticked — 60 reads an hour
  without a token; an optional ``GITHUB_TOKEN`` in .env raises both limits and is never logged),
* the npm registry and PyPI (does a package exist, its latest version, what it needs, deprecations),
* DEV Community (articles by tag, for learning).

Only the searched words leave the computer (a signature scrubbed of paths, hosts and numbers — signature.py; for
people: skills, a GitHub language and the event's city). ``FixtureSources`` serves labelled synthetic TEST data
instead (tests and the offline e2e never go online).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx

log = logging.getLogger("extrahorizon.hub")

UA = "ExtraHorizon-hackathon-hub/1.0 (student project; +https://github.com)"
SE_API = "https://api.stackexchange.com/2.3"
GH_API = "https://api.github.com"
NPM = "https://registry.npmjs.org"
PYPI = "https://pypi.org/pypi"
DEVTO = "https://dev.to/api"

SOURCE_LABELS = {"stackoverflow": "Stack Overflow", "github": "GitHub", "npm": "npm registry", "pypi": "PyPI",
                 "devto": "DEV Community"}


class SourceError(Exception):
    def __init__(self, source: str, message: str) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source
        self.message = message


class Sources(Protocol):
    offline: bool

    async def so_search(self, q: str, tagged: str = "") -> list[dict[str, Any]]: ...
    async def so_answers(self, question_ids: list[int]) -> list[dict[str, Any]]: ...
    async def so_answers_by_id(self, answer_ids: list[int]) -> list[dict[str, Any]]: ...
    async def so_top(self, tag: str) -> list[dict[str, Any]]: ...
    async def gh_issues(self, q: str) -> list[dict[str, Any]]: ...
    async def gh_repos(self, q: str) -> list[dict[str, Any]]: ...
    async def gh_user(self, login: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]: ...
    async def gh_search_users(self, q: str) -> list[dict[str, Any]]: ...
    async def so_top_answerers(self, tag: str, period: str) -> list[dict[str, Any]]: ...
    async def so_open_questions(self, tag: str) -> list[dict[str, Any]]: ...
    async def npm(self, name: str) -> dict[str, Any] | None: ...
    async def pypi(self, name: str) -> dict[str, Any] | None: ...
    async def devto(self, tag: str) -> list[dict[str, Any]]: ...
    def status(self) -> dict[str, Any]: ...
    async def aclose(self) -> None: ...


def devto_tag(tag: str) -> str:
    """DEV Community tags are plain words: node.js → node, next.js → nextjs, tailwind-css → tailwindcss."""
    special = {"node.js": "node", "vue.js": "vue", "nuxt.js": "nuxt", "c++": "cpp", "amazon-web-services": "aws",
               "unity-game-engine": "unity3d", "google-cloud-platform": "googlecloud", "openai-api": "openai",
               "raspberry-pi": "raspberrypi", "stripe-payments": "stripe", "oauth-2.0": "oauth"}
    return special.get(tag, re.sub(r"[^a-z0-9]", "", tag.lower()))


class PublicClient:
    """Live reads with a response cache (the same search within the TTL costs no quota) and the sources' own
    limits respected: Stack Exchange's ``backoff``, GitHub's rate-limit headers."""

    offline = False

    def __init__(self, timeout_s: float = 12.0, cache_ttl_s: float = 3600.0, github_token: str | None = None,
                 client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_s, follow_redirects=True,
                                                   headers={"User-Agent": UA})
        self._ttl = cache_ttl_s
        self._cache: dict[str, tuple[float, Any]] = {}  # bounded (a long event must not grow it forever)
        self._gh_token = github_token or None
        self._blocked: dict[str, tuple[float, str]] = {}  # source → (until, why)
        self._quota: dict[str, Any] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    def status(self) -> dict[str, Any]:
        now = time.time()
        return {"offline": False, "github_token": bool(self._gh_token), "quota": dict(self._quota),
                "blocked": {k: {"until": round(u), "why": w} for k, (u, w) in self._blocked.items() if u > now}}

    def _gate(self, source: str) -> None:
        until, why = self._blocked.get(source, (0.0, ""))
        if until > time.time():
            raise SourceError(source, f"{why} — try again after {time.strftime('%H:%M', time.localtime(until))}")

    async def _get(self, source: str, url: str, params: dict[str, Any] | None = None,
                   headers: dict[str, str] | None = None, allow_404: bool = False) -> Any:
        key = url + "?" + json.dumps(params or {}, sort_keys=True)
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        self._gate(source)
        try:
            r = await self._client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as e:
            raise SourceError(source, "did not answer in time") from e
        except httpx.HTTPError as e:
            raise SourceError(source, "could not be reached") from e
        if source.startswith("github"):
            self._github_limits(source, r)
        if r.status_code == 404 and allow_404:
            self._remember(key, None)
            return None
        if r.status_code in (403, 429) and source.startswith("github"):
            if self._gh_token:
                raise SourceError(source, "GitHub's rate limit is reached — try again in a minute")
            what = "10 searches a minute" if source == "github_search" else "60 profile reads an hour"
            raise SourceError(source, f"GitHub's limit without a token is reached ({what}) — a GITHUB_TOKEN in .env "
                                      "raises it")
        if r.status_code >= 400:
            detail = ""
            try:
                j = r.json()
                detail = str(j.get("error_message") or j.get("message") or "")[:120]
                if source == "stackoverflow" and j.get("error_id") == 502:  # throttle violation
                    self._blocked[source] = (time.time() + 60, "Stack Exchange asked us to slow down")
            except ValueError:
                pass
            raise SourceError(source, f"returned HTTP {r.status_code}{': ' + detail if detail else ''}")
        try:
            data = r.json()
        except ValueError as e:
            raise SourceError(source, "returned something that is not JSON") from e
        if source == "stackoverflow" and isinstance(data, dict):
            self._quota["stackexchange_remaining"] = data.get("quota_remaining")
            if data.get("backoff"):
                self._blocked[source] = (time.time() + float(data["backoff"]), "Stack Exchange asked us to wait")
        self._remember(key, data)
        return data

    def _remember(self, key: str, data: Any) -> None:
        if len(self._cache) >= 400:
            now = time.monotonic()
            for k in [k for k, (until, _d) in self._cache.items() if until <= now] or list(self._cache)[:100]:
                self._cache.pop(k, None)
        self._cache[key] = (time.monotonic() + self._ttl, data)

    def _github_limits(self, source: str, r: httpx.Response) -> None:
        rem, reset, res = (r.headers.get("x-ratelimit-remaining"), r.headers.get("x-ratelimit-reset"),
                           r.headers.get("x-ratelimit-resource") or source)
        if rem is None:
            return
        self._quota[f"github_{res}_remaining"] = int(rem)
        if int(rem) <= 0 and reset:
            name = "github_search" if res == "search" else "github"
            self._blocked[name] = (float(reset), "GitHub's rate limit is reached")

    def _gh_headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._gh_token:
            h["Authorization"] = f"Bearer {self._gh_token}"
        return h

    # ------------------------------------------------------------------ Stack Overflow
    async def so_search(self, q: str, tagged: str = "") -> list[dict[str, Any]]:
        params = {"q": q, "site": "stackoverflow", "order": "desc", "sort": "relevance", "answers": 1,
                  "pagesize": 20, "filter": "withbody"}
        if tagged:
            params["tagged"] = tagged
        data = await self._get("stackoverflow", f"{SE_API}/search/advanced", params)
        return list(data.get("items") or [])

    async def so_answers(self, question_ids: list[int]) -> list[dict[str, Any]]:
        if not question_ids:
            return []
        ids = ";".join(str(i) for i in question_ids[:30])
        data = await self._get("stackoverflow", f"{SE_API}/questions/{ids}/answers",
                               {"site": "stackoverflow", "order": "desc", "sort": "votes", "pagesize": 60,
                                "filter": "withbody"})
        return list(data.get("items") or [])

    async def so_answers_by_id(self, answer_ids: list[int]) -> list[dict[str, Any]]:
        """The accepted answers themselves (a popular question's 60 other answers must not crowd them out)."""
        if not answer_ids:
            return []
        ids = ";".join(str(i) for i in answer_ids[:30])
        data = await self._get("stackoverflow", f"{SE_API}/answers/{ids}",
                               {"site": "stackoverflow", "order": "desc", "sort": "votes", "pagesize": 30,
                                "filter": "withbody"})
        return list(data.get("items") or [])

    async def so_top(self, tag: str) -> list[dict[str, Any]]:
        data = await self._get("stackoverflow", f"{SE_API}/questions",
                               {"tagged": tag, "site": "stackoverflow", "order": "desc", "sort": "votes",
                                "pagesize": 10})
        return list(data.get("items") or [])

    async def so_top_answerers(self, tag: str, period: str) -> list[dict[str, Any]]:
        """The tag's top answerers (``period``: "all_time" or "month") — public experts, with their answer counts."""
        data = await self._get("stackoverflow", f"{SE_API}/tags/{quote(tag, safe='')}/top-answerers/{period}",
                               {"site": "stackoverflow", "pagesize": 20})
        return list(data.get("items") or [])

    async def so_open_questions(self, tag: str) -> list[dict[str, Any]]:
        """The newest questions with the tag that are still unsolved — no accepted and no upvoted answer (someone
        here could answer them)."""
        data = await self._get("stackoverflow", f"{SE_API}/questions/unanswered",
                               {"tagged": tag, "site": "stackoverflow", "sort": "creation", "order": "desc",
                                "pagesize": 15})
        return list(data.get("items") or [])

    # ------------------------------------------------------------------ GitHub
    async def gh_issues(self, q: str) -> list[dict[str, Any]]:
        data = await self._get("github_search", f"{GH_API}/search/issues", {"q": q, "per_page": 15},
                               self._gh_headers())
        return list(data.get("items") or [])

    async def gh_repos(self, q: str) -> list[dict[str, Any]]:
        data = await self._get("github_search", f"{GH_API}/search/repositories",
                               {"q": q, "sort": "stars", "order": "desc", "per_page": 12}, self._gh_headers())
        return list(data.get("items") or [])

    async def gh_user(self, login: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        user = await self._get("github", f"{GH_API}/users/{quote(login)}", None, self._gh_headers(), allow_404=True)
        if not user:
            return None, []
        repos = await self._get("github", f"{GH_API}/users/{quote(login)}/repos",
                                {"per_page": 100, "sort": "pushed", "type": "owner"}, self._gh_headers())
        return user, list(repos or [])

    async def gh_search_users(self, q: str) -> list[dict[str, Any]]:
        """GitHub's own user search (``type:user language:"Svelte" location:"Miami"``): logins, in its order."""
        data = await self._get("github_search", f"{GH_API}/search/users", {"q": q, "per_page": 20}, self._gh_headers())
        return list(data.get("items") or [])

    # ------------------------------------------------------------------ registries
    async def npm(self, name: str) -> dict[str, Any] | None:
        path = quote(name, safe="@") if not name.startswith("@") else "@" + quote(name[1:], safe="")
        return await self._get("npm", f"{NPM}/{path}/latest", allow_404=True)

    async def pypi(self, name: str) -> dict[str, Any] | None:
        data = await self._get("pypi", f"{PYPI}/{quote(name)}/json", allow_404=True)
        if data is None:
            return None
        return {"info": data.get("info") or {}, "latest_upload": _latest_upload(data)}

    # ------------------------------------------------------------------ DEV Community
    async def devto(self, tag: str) -> list[dict[str, Any]]:
        data = await self._get("devto", f"{DEVTO}/articles", {"tag": devto_tag(tag), "top": 365, "per_page": 12})
        return list(data or [])


def _latest_upload(data: dict[str, Any]) -> str | None:
    """When the latest version was uploaded (PyPI's ``urls`` are the latest release's files)."""
    times = [u.get("upload_time_iso_8601") or u.get("upload_time") for u in data.get("urls") or []]
    times = [t for t in times if t]
    return min(times)[:10] if times else None


class FixtureSources:
    """Labelled synthetic TEST data (``EH_HUB_OFFLINE_DIR``): the same shapes as the real APIs, filtered by the
    keywords each fixture item lists under ``_keys`` — so different questions still get different answers."""

    offline = True

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self._data: dict[str, Any] = {}
        for name in ("stackoverflow", "github", "registries", "devto"):
            f = self.folder / f"{name}.json"
            self._data[name] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        self.as_of = self._data["stackoverflow"].get("_as_of")  # the "today" the fixtures were written for
        self.calls: list[tuple[str, str]] = []  # what was asked (tests check that no private bits left)
        self.delay_s = 0.0

    async def aclose(self) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return {"offline": True, "github_token": False, "quota": {}, "blocked": {}}

    async def _pause(self) -> None:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)

    @staticmethod
    def _match(items: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
        words = set(re.findall(r"[a-z0-9+#.\-]+", text.lower()))
        return [dict(i) for i in items if any(k.lower() in words or k.lower() in text.lower() for k in i.get("_keys", []))]

    async def so_search(self, q: str, tagged: str = "") -> list[dict[str, Any]]:
        self.calls.append(("stackoverflow", f"{q} [{tagged}]"))
        await self._pause()
        return self._match(self._data["stackoverflow"].get("questions", []), f"{q} {tagged}")

    async def so_answers(self, question_ids: list[int]) -> list[dict[str, Any]]:
        self.calls.append(("stackoverflow", "answers " + ",".join(map(str, question_ids))))
        ids = set(question_ids)
        return [dict(a) for a in self._data["stackoverflow"].get("answers", []) if a.get("question_id") in ids]

    async def so_answers_by_id(self, answer_ids: list[int]) -> list[dict[str, Any]]:
        self.calls.append(("stackoverflow", "answers by id " + ",".join(map(str, answer_ids))))
        ids = set(answer_ids)
        return [dict(a) for a in self._data["stackoverflow"].get("answers", []) if a.get("answer_id") in ids]

    async def so_top(self, tag: str) -> list[dict[str, Any]]:
        self.calls.append(("stackoverflow", f"top {tag}"))
        return [dict(x) for x in (self._data["stackoverflow"].get("top") or {}).get(tag, [])]

    async def gh_issues(self, q: str) -> list[dict[str, Any]]:
        self.calls.append(("github", q))
        await self._pause()
        return self._match(self._data["github"].get("issues", []), q)

    async def gh_repos(self, q: str) -> list[dict[str, Any]]:
        self.calls.append(("github", q))
        return self._match(self._data["github"].get("repos", []), q)

    async def gh_user(self, login: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        self.calls.append(("github", f"user {login}"))
        u = (self._data["github"].get("users") or {}).get(login.lower())
        return (dict(u["user"]), [dict(r) for r in u.get("repos", [])]) if u else (None, [])

    async def gh_search_users(self, q: str) -> list[dict[str, Any]]:
        self.calls.append(("github", f"users {q}"))
        await self._pause()
        return self._match(self._data["github"].get("user_search", []), q)

    async def so_top_answerers(self, tag: str, period: str) -> list[dict[str, Any]]:
        self.calls.append(("stackoverflow", f"top answerers {tag} {period}"))
        per_tag = (self._data["stackoverflow"].get("top_answerers") or {}).get(tag) or {}
        return [dict(x) for x in per_tag.get(period, [])]

    async def so_open_questions(self, tag: str) -> list[dict[str, Any]]:
        self.calls.append(("stackoverflow", f"open questions {tag}"))
        return [dict(x) for x in (self._data["stackoverflow"].get("open_questions") or {}).get(tag, [])]

    async def npm(self, name: str) -> dict[str, Any] | None:
        self.calls.append(("npm", name))
        return (self._data["registries"].get("npm") or {}).get(name)

    async def pypi(self, name: str) -> dict[str, Any] | None:
        self.calls.append(("pypi", name))
        for k, v in (self._data["registries"].get("pypi") or {}).items():
            if k.lower() == name.lower():
                return v
        return None

    async def devto(self, tag: str) -> list[dict[str, Any]]:
        self.calls.append(("devto", tag))
        return [dict(x) for x in self._data["devto"].get(devto_tag(tag), [])]


def create_sources(settings: Any) -> Sources:
    if settings.hub_offline_dir:
        return FixtureSources(Path(settings.hub_offline_dir))
    token = settings.github_token.get_secret_value().strip() if settings.github_token else ""
    return PublicClient(settings.hub_http_timeout_s, settings.hub_cache_ttl_s, token or None)
