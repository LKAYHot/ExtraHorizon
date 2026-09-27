"""The hackathon board: people (hackers and mentors) who put a card here, help requests, and what teams learned.

It is shared by everyone using this server (at an event: the presenter's laptop and the laptops that reach it
through the tunnel), kept in a git-ignored JSON file, and every entry belongs to the browser that wrote it (a
random token in that browser; the server keeps only its SHA-256). Everything on it was written by a real person
using the app — there are no sample entries; a board card's GitHub username is read only with its box ticked.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .skills import norm_list

log = logging.getLogger("extrahorizon.hub")

MAX_PROFILES = 400
MAX_REQUESTS = 800
MAX_CARDS = 800
TEAM_MAX = 4  # ShellHacks teams: up to four people


class BoardError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _now_ms() -> int:
    return int(time.time() * 1000)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u2028\u2029]")


def _line(v: Any, limit: int) -> str:
    """A one-line field (a name, a title, availability): every line break and control character collapses — nothing
    anyone writes on the board can start a new line in her fact sheet."""
    return re.sub(r"\s+", " ", _CONTROL.sub(" ", str(v or ""))).strip()[:limit]


def _text(v: Any, limit: int) -> str:
    """A multi-line field (a problem, what fixed it): line breaks stay for the panel (the sheet quotes it on one line)."""
    t = _CONTROL.sub(" ", str(v or "").replace("\r\n", "\n"))
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()[:limit]


def _url_list(v: Any, limit: int = 5) -> list[str]:
    out: list[str] = []
    for u in list(v or [])[:limit * 2]:
        u = str(u).strip()
        if re.fullmatch(r"https?://[^\s<>\"']{4,300}", u) and u not in out:
            out.append(u)
    return out[:limit]


def _signature(v: Any) -> dict[str, str] | None:
    if not isinstance(v, dict):
        return None
    return {"kind": _line(v.get("kind"), 60), "message": _line(v.get("message"), 240)}


def _sid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class Board:
    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path else None
        self._lock = asyncio.Lock()
        self.profiles: dict[str, dict[str, Any]] = {}
        self.requests: dict[str, dict[str, Any]] = {}
        self.cards: dict[str, dict[str, Any]] = {}
        self.issued: set[str] = set()  # hashes of the tokens this server gave out (only those are accepted back)
        self._io = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hub-board")
        self._last_write: Future[None] | None = None
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            # (an entry marked "sample" was demo data of an older version — never real, never shown)
            self.profiles = {p["id"]: p for p in data.get("profiles", []) if not p.get("sample")}
            self.requests = {r["id"]: r for r in data.get("requests", []) if not r.get("sample")}
            self.cards = {c["id"]: c for c in data.get("cards", []) if not c.get("sample")}
            self.issued = set(data.get("issued") or []) | {x["owner"] for x in (*self.profiles.values(),
                                                                                 *self.requests.values(),
                                                                                 *self.cards.values()) if x.get("owner")}
        except (ValueError, KeyError, OSError) as e:
            log.warning("hub board could not be read (%s) — starting empty", type(e).__name__)

    def _snapshot(self) -> str:
        return json.dumps({"version": 1, "issued": sorted(self.issued), "profiles": list(self.profiles.values()),
                           "requests": list(self.requests.values()), "cards": list(self.cards.values())},
                          ensure_ascii=False, indent=1)

    def _write(self, text: str) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        for attempt in range(3):  # Windows: a reader (an editor, an antivirus) may hold the file for a moment
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                if attempt == 2:
                    log.warning("hub board could not be saved (the file is locked) — kept in memory")
                    return
                time.sleep(0.05)

    def _save(self) -> None:
        """Called under the lock: the snapshot is taken now, the file is written off the event loop, one write after
        the other (a single writer thread — two writes never interleave)."""
        if self.path:
            self._last_write = self._io.submit(self._write, self._snapshot())

    def flush(self) -> None:
        """Wait for the last write (shutdown, tests)."""
        f = self._last_write
        if f is not None:
            f.result(timeout=10)

    # ------------------------------------------------------------------ who is asking
    def new_token(self) -> str:
        token = secrets.token_urlsafe(24)
        self.issued.add(_hash(token))
        return token

    def known(self, token: str | None) -> bool:
        """A token this server gave out (a made-up one is never accepted — no fresh identities for free votes)."""
        return bool(token) and _hash(token) in self.issued

    @staticmethod
    def owner_of(token: str | None) -> str | None:
        return _hash(token) if token else None

    def mine(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        h = _hash(token)
        return next((p for p in self.profiles.values() if p.get("owner") == h), None)

    def _owner(self, token: str | None) -> str:
        if not token or len(token) < 16:
            raise BoardError(401, "no_token", "This browser has no hub token yet — create your card first.")
        return _hash(token)

    # ------------------------------------------------------------------ people
    async def save_profile(self, token: str, data: dict[str, Any]) -> dict[str, Any]:
        owner = self._owner(token)
        async with self._lock:
            me = next((p for p in self.profiles.values() if p.get("owner") == owner), None)
            if me is None and len(self.profiles) >= MAX_PROFILES:
                raise BoardError(409, "board_full", "The board is full.")
            name = _line(data.get("name"), 40)
            if not name:
                raise BoardError(422, "no_name", "A name (or a nickname) is needed.")
            kind = "mentor" if data.get("kind") == "mentor" else "hacker"
            github = _line(data.get("github"), 39).lstrip("@")
            if github and not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", github):
                raise BoardError(422, "bad_github", "That is not a GitHub username.")
            team = data.get("team") or {}
            size = max(1, min(TEAM_MAX + 2, int(team.get("size") or 1)))
            p = me or {"id": _sid("u"), "created": _now_ms(), "owner": owner, "verified": None}
            old_github = p.get("github")
            p.update({
                "kind": kind, "name": name, "contact": _line(data.get("contact"), 80),
                "skills": norm_list(data.get("skills")), "looking_for": norm_list(data.get("looking_for"), 8),
                "interests": norm_list(data.get("interests"), 8), "idea": _line(data.get("idea"), 240),
                "availability": _line(data.get("availability"), 40),
                "team": {"name": _line(team.get("name"), 40), "size": size},
                "github": github, "github_consent": bool(data.get("github_consent")) and bool(github),
                "updated": _now_ms(),
            })
            if old_github != github or not p["github_consent"]:
                p["verified"] = None  # a new username (or no consent) — nothing from GitHub is kept
            self.profiles[p["id"]] = p
            self._save()
            return p

    async def set_verified(self, profile_id: str, verified: dict[str, Any] | None, login: str = "") -> None:
        """Store a GitHub check — only if the card still names that account and still has the box ticked (a slow
        check of an old username must not land on the new one)."""
        async with self._lock:
            p = self.profiles.get(profile_id)
            if p is None or not p.get("github_consent"):
                return
            if login and str(p.get("github") or "").lower() != login.lower():
                return
            p["verified"] = verified
            self._save()

    async def delete_profile(self, token: str) -> bool:
        owner = self._owner(token)
        async with self._lock:
            gone = [k for k, p in self.profiles.items() if p.get("owner") == owner]
            for k in gone:
                del self.profiles[k]
            if gone:
                self._save()
            return bool(gone)

    # ------------------------------------------------------------------ help requests
    async def post_request(self, token: str, data: dict[str, Any]) -> dict[str, Any]:
        owner = self._owner(token)
        async with self._lock:
            if len(self.requests) >= MAX_REQUESTS:
                raise BoardError(409, "board_full", "The help board is full.")
            title = _line(data.get("title"), 120)
            if not title:
                raise BoardError(422, "no_title", "A short title is needed.")
            me = next((p for p in self.profiles.values() if p.get("owner") == owner), None)
            r = {"id": _sid("h"), "title": title, "problem": _text(data.get("problem"), 1500),
                 "tags": norm_list(data.get("tags"), 6), "signature": _signature(data.get("signature")),
                 "author": me["name"] if me else _line(data.get("author"), 40) or "a hacker",
                 "author_profile": me["id"] if me else None, "status": "open", "claimed_by": None,
                 "tried": _url_list(data.get("tried")), "created": _now_ms(), "updated": _now_ms(),
                 "solved_note": None, "owner": owner}
            self.requests[r["id"]] = r
            self._save()
            return r

    async def claim(self, token: str, request_id: str) -> dict[str, Any]:
        owner = self._owner(token)
        async with self._lock:
            r = self.requests.get(request_id)
            if r is None:
                raise BoardError(404, "no_request", "No such help request.")
            me = next((p for p in self.profiles.values() if p.get("owner") == owner), None)
            if me is None:
                raise BoardError(409, "no_profile", "Create your card first, so they know who is coming.")
            if r.get("owner") == owner:
                raise BoardError(409, "own_request", "That is your own request.")
            if r["status"] != "open":
                raise BoardError(409, "taken", "Someone is already on it.")
            r.update({"status": "claimed", "claimed_by": {"id": me["id"], "name": me["name"]}, "updated": _now_ms()})
            self._save()
            return r

    async def release(self, token: str, request_id: str) -> dict[str, Any]:
        """The helper (or the team that asked) gives a claim back: the request is open again."""
        owner = self._owner(token)
        async with self._lock:
            r = self.requests.get(request_id)
            if r is None:
                raise BoardError(404, "no_request", "No such help request.")
            me = next((p for p in self.profiles.values() if p.get("owner") == owner), None)
            claimer = (r.get("claimed_by") or {}).get("id")
            if r["status"] != "claimed" or not (r.get("owner") == owner or (me and me["id"] == claimer)):
                raise BoardError(403, "not_yours", "Only the helper or the team that asked can release it.")
            r.update({"status": "open", "claimed_by": None, "updated": _now_ms()})
            self._save()
            return r

    async def resolve(self, token: str, request_id: str, note: str = "") -> dict[str, Any]:
        owner = self._owner(token)
        async with self._lock:
            r = self.requests.get(request_id)
            if r is None:
                raise BoardError(404, "no_request", "No such help request.")
            if r.get("owner") != owner:
                raise BoardError(403, "not_yours", "Only the team that asked can mark it solved.")
            r.update({"status": "solved", "solved_note": _line(note, 400) or None, "updated": _now_ms()})
            self._save()
            return r

    async def withdraw(self, token: str, request_id: str) -> bool:
        owner = self._owner(token)
        async with self._lock:
            r = self.requests.get(request_id)
            if r is None or r.get("owner") != owner:
                return False
            del self.requests[request_id]
            self._save()
            return True

    # ------------------------------------------------------------------ what teams learned
    async def add_card(self, token: str, data: dict[str, Any]) -> dict[str, Any]:
        owner = self._owner(token)
        async with self._lock:
            if len(self.cards) >= MAX_CARDS:
                raise BoardError(409, "board_full", "The knowledge board is full.")
            title, fix = _line(data.get("title"), 120), _text(data.get("fix"), 800)
            if not title or not fix:
                raise BoardError(422, "no_fix", "A title and what fixed it are needed.")
            me = next((p for p in self.profiles.values() if p.get("owner") == owner), None)
            c = {"id": _sid("k"), "title": title, "problem": _text(data.get("problem"), 300), "fix": fix,
                 "tags": norm_list(data.get("tags"), 6), "links": _url_list(data.get("links")),
                 "author": me["name"] if me else _line(data.get("author"), 40) or "a team here",
                 "created": _now_ms(), "helpful": 0, "voters": [], "owner": owner}
            self.cards[c["id"]] = c
            self._save()
            return c

    async def helpful(self, token: str, card_id: str) -> dict[str, Any]:
        owner = self._owner(token)
        async with self._lock:
            c = self.cards.get(card_id)
            if c is None:
                raise BoardError(404, "no_card", "No such card.")
            if not any(p.get("owner") == owner for p in self.profiles.values()):
                raise BoardError(409, "no_profile", "Create your card first — then you can vote.")
            if owner not in c["voters"] and c.get("owner") != owner:
                c["voters"].append(owner)
                c["helpful"] = int(c.get("helpful") or 0) + 1
                self._save()
            return c

    async def delete_card(self, token: str, card_id: str) -> bool:
        owner = self._owner(token)
        async with self._lock:
            c = self.cards.get(card_id)
            if c is None or c.get("owner") != owner:
                return False
            del self.cards[card_id]
            self._save()
            return True

    # ------------------------------------------------------------------ what the browser sees
    def public(self, token: str | None = None) -> dict[str, Any]:
        h = _hash(token) if token else None

        def strip(x: dict[str, Any]) -> dict[str, Any]:
            out = {k: v for k, v in x.items() if k not in ("owner", "voters")}
            out["mine"] = bool(h) and x.get("owner") == h
            return out
        people = sorted(self.profiles.values(), key=lambda p: -p.get("updated", 0))
        reqs = sorted(self.requests.values(), key=lambda r: ({"open": 0, "claimed": 1, "solved": 2}[r["status"]],
                                                             -r.get("created", 0)))
        cards = sorted(self.cards.values(), key=lambda c: (-int(c.get("helpful") or 0), -c.get("created", 0)))
        return {"profiles": [strip(p) for p in people], "requests": [strip(r) for r in reqs],
                "cards": [strip(c) for c in cards]}
