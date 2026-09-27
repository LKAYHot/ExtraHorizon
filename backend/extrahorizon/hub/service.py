"""The hub's searches: get unstuck (public fixes for an error), learn (where to start with a topic) and find people
(teammates and mentors: this event's board, public GitHub profiles in the event's city, Stack Overflow's top
answerers). Each run reads its sources in parallel, reports progress per source, verifies what came back (verify.py,
people.py) and returns a report with short IDs she cites: S (sources), L (learning), P (people), M (mentors),
K (what peers here learned). The help board also lists real Stack Overflow questions nobody has answered yet."""

from __future__ import annotations

import asyncio
import datetime as dt
import itertools
import logging
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import verify
from .board import Board
from .people import (MAX_PUBLIC_PEOPLE, NOT_ON_GITHUB, experts, github_evidence, github_user_query, languages_for,
                     location_in, match_mentors, match_people, needs_of, public_person, so_tags_for)
from .signature import _GENERIC_TAGS, _STOP, _tags_of, IMPORT_TO_PYPI, Signature, extract, relevance, scrub
from .skills import norm, norm_list
from .sources import SOURCE_LABELS, SourceError, create_sources

log = logging.getLogger("extrahorizon.hub")

MAX_SOURCES = 8
# a registry name (npm: optionally scoped; PyPI: letters, digits, . _ -) — nothing else is sent to a registry
_PACKAGE_NAME = re.compile(r"^(?:@[a-z0-9~][\w.~-]{0,100}/)?[A-Za-z0-9][\w.~-]{0,100}$")
MAX_LEARN = 9
Progress = Callable[[dict[str, Any]], None]
_LEARN_NOISE = {"learn", "learning", "tutorial", "tutorials", "course", "courses", "resources", "resource", "guide",
                "guides", "start", "started", "getting", "beginner", "beginners", "basics", "example", "examples",
                "docs", "documentation", "fast", "quickly", "quick", "best", "good", "way", "ways", "where", "find",
                "want", "need", "know", "understand", "teach", "show", "recommend", "hackathon", "weekend", "tonight"}


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return f"hub_{uuid.uuid4().hex[:8]}"


class HubService:
    def __init__(self, settings: Any, sources: Any = None, board: Board | None = None) -> None:
        self.s = settings
        self.sources = sources if sources is not None else create_sources(settings)
        self.board = board if board is not None else Board(settings.hub_board_path)
        self._bg: set[asyncio.Task[Any]] = set()

    @property
    def offline(self) -> bool:
        return bool(getattr(self.sources, "offline", False))

    def today(self) -> dt.date:
        as_of = getattr(self.sources, "as_of", None)
        return dt.date.fromisoformat(as_of) if as_of else dt.date.today()

    async def aclose(self) -> None:
        for t in list(self._bg):
            t.cancel()
        self.board.flush()
        await self.sources.aclose()

    def status(self) -> dict[str, Any]:
        return {"offline": self.offline, **self.sources.status()}

    # ------------------------------------------------------------------ the board around a search
    def _peers(self, sig_words: list[str], tags: list[str], text: str) -> list[dict[str, Any]]:
        tags_n = set(norm_list(tags, 10))
        probe = Signature(kind="", message=text, words=sig_words)
        out = []
        for c in self.board.cards.values():
            shared = tags_n & set(c.get("tags") or [])
            body = f"{c['title']} {c.get('problem', '')} {c.get('fix', '')}"
            rel = relevance(probe, body) if sig_words else 0.0
            hits = sum(1 for w in sig_words if w in body.lower())
            if hits < min(2, len(sig_words)) and len(shared) < 2:
                continue  # one shared word ("fastapi") is not the same problem
            if len(shared) >= 2 or rel >= 0.5 or (shared and rel >= 0.3):
                out.append((rel + 0.2 * len(shared) + 0.05 * int(c.get("helpful") or 0), c))
        out.sort(key=lambda x: -x[0])
        return [{k: v for k, v in c.items() if k not in ("owner", "voters")} for _s, c in out[:3]]

    def _similar(self, sig: Signature, owner: str | None = None) -> list[dict[str, Any]]:
        tags_n = set(norm_list(sig.tags, 10))
        out = []
        for r in self.board.requests.values():
            if r["status"] == "solved" or (owner and r.get("owner") == owner):
                continue  # their own request is not "another team stuck on this"
            rel = relevance(sig, f"{r['title']} {r.get('problem', '')}")
            if rel >= 0.5 or len(tags_n & set(r.get("tags") or [])) >= 2:
                out.append({k: r[k] for k in ("id", "title", "status", "author", "created")})
        return out[:4]

    # ------------------------------------------------------------------ get unstuck
    async def unstuck(self, problem: str, progress: Progress | None = None, owner: str | None = None) -> dict[str, Any]:
        emit = progress or (lambda _m: None)
        sig = extract(problem)
        if not sig.words and not sig.kind:
            return {"error": "there was nothing to search for — describe the error or paste it"}
        today = self.today()
        emit({"step": "signature", "state": "done", "query": sig.query, "tags": sig.tags})
        tag = next((t for t in sig.tags if t not in _GENERIC_TAGS), sig.tags[0] if sig.tags else "")
        errors: list[dict[str, str]] = []

        async def so() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            emit({"step": "stackoverflow", "state": "reading"})
            qs = await self.sources.so_search(sig.query, tag)
            if len(qs) < 3 and tag:
                more = await self.sources.so_search(sig.query, "")
                have = {q.get("question_id") for q in qs}
                qs += [q for q in more if q.get("question_id") not in have]
            cand = [q for q in qs if (q.get("score") or 0) >= 0 and relevance(
                sig, f"{q.get('title', '')} {' '.join(q.get('tags') or [])} {verify.plain(q.get('body') or '', 3000)}")
                >= verify.MIN_RELEVANCE][:15]
            # the accepted answers by their own IDs; the others' top answers (a popular question has dozens)
            accepted = [int(q["accepted_answer_id"]) for q in cand if q.get("accepted_answer_id")]
            others = [int(q["question_id"]) for q in cand if not q.get("accepted_answer_id")]
            answers = (await self.sources.so_answers_by_id(accepted) if accepted else []) + (
                await self.sources.so_answers(others) if others else [])
            ev, audit = verify.stackoverflow(sig, qs, answers, today)
            emit({"step": "stackoverflow", "state": "done", "received": audit["received"], "kept": audit["kept"]})
            return ev, audit

        async def gh() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            emit({"step": "github", "state": "reading"})
            words = " ".join(w.replace("-", " ") for w in sig.words[:4])
            items: list[dict[str, Any]] = []
            if sig.repos:
                try:  # the project's own tracker first (a repository that moved answers 422: search everywhere)
                    items = await self.sources.gh_issues(f"{words} is:issue repo:{sig.repos[0]}")
                except SourceError as e:
                    if "HTTP 422" not in e.message:
                        raise
            if len(items) < 2:
                have = {i.get("id") for i in items}
                items += [i for i in await self.sources.gh_issues(f"{words} is:issue") if i.get("id") not in have]
            ev, audit = verify.github_issues(sig, items, today)
            emit({"step": "github", "state": "done", "received": audit["received"], "kept": audit["kept"]})
            return ev, audit

        async def reg() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            emit({"step": "registries", "state": "reading"})
            found: dict[str, tuple[str, dict[str, Any] | None]] = {}
            for name in sig.packages + sig.mentioned:
                if not _PACKAGE_NAME.match(name):
                    continue  # "a/../../simple", "git+https": not a package name — nothing is looked up
                if sig.ecosystem == "pypi":
                    found[name] = ("pypi", await self.sources.pypi(IMPORT_TO_PYPI.get(name, name)))
                elif sig.ecosystem == "npm":
                    found[name] = ("npm", await self.sources.npm(name))
            ev, audit = verify.packages(sig, found, soft=set(sig.mentioned))
            emit({"step": "registries", "state": "done", "received": audit["received"], "kept": audit["kept"]})
            return ev, audit

        jobs = [("stackoverflow", so()), ("github", gh())] + (
            [("registries", reg())] if sig.packages or sig.mentioned else [])
        results = await asyncio.gather(*(j for _n, j in jobs), return_exceptions=True)
        evidence: list[dict[str, Any]] = []
        audits: list[dict[str, Any]] = []
        for (name, _j), res in zip(jobs, results):
            if isinstance(res, SourceError):
                errors.append({"source": SOURCE_LABELS.get(res.source.split("_")[0], res.source), "message": res.message})
                emit({"step": name, "state": "failed", "message": res.message})
                audits.append({"source": name, "received": 0, "kept": 0, "excluded": {}, "error": res.message})
                continue
            if isinstance(res, BaseException):
                log.warning("hub source %s failed: %r", name, res)
                errors.append({"source": name, "message": f"failed on the server ({type(res).__name__})"})
                emit({"step": name, "state": "failed", "message": "failed on the server"})
                audits.append({"source": name, "received": 0, "kept": 0, "excluded": {}, "error": "failed on the server"})
                continue
            ev, audit = res
            evidence += ev
            audits.append(audit)
        # what she cites first: a package fact that settles it, then the strongest answers; a few of each kind
        evidence.sort(key=lambda e: -e.get("rank", 0))
        caps = {"stackoverflow": 5, "github_issue": 3, "package": 3}
        items: list[dict[str, Any]] = []
        for e in evidence:
            if sum(1 for x in items if x["type"] == e["type"]) < caps.get(e["type"], 3):
                items.append(e)
        items = items[:MAX_SOURCES]
        for i, e in enumerate(items, 1):
            e["ref"] = f"S{i}"
        needs = [norm(t) for t in sig.tags]
        peers = self._peers(sig.words, sig.tags, sig.title)
        mentors = match_mentors(list(self.board.profiles.values()), needs)
        for i, k in enumerate(peers, 1):
            k["ref"] = f"K{i}"
        for i, m in enumerate(mentors, 1):
            m["ref"] = f"M{i}"
        hints = []
        if sig.local_import:
            hints.append(f"The import of your own file {sig.local_import} did not resolve — check its path and the "
                         "letter case of the file name (this comes from the error itself, not from a web source).")
        if sig.node_builtin:
            hints.append(f"'{sig.node_builtin}' is a Node.js built-in module; code that runs in the browser cannot "
                         "import it (this comes from the error itself, not from a web source).")
        emit({"step": "board", "state": "done", "peers": len(peers), "mentors": len(mentors)})
        return {"id": _new_id(), "kind": "unstuck", "created": _now_iso(), "offline": self.offline,
                "query": {"text": sig.title, "signature": sig.public()}, "items": items, "peers": peers,
                "mentors": mentors, "similar": self._similar(sig, owner), "hints": hints, "audit": audits,
                "errors": errors, "sources": [a["source"] for a in audits if not a.get("error")]}

    # ------------------------------------------------------------------ learn
    async def learn(self, topic: str, progress: Progress | None = None) -> dict[str, Any]:
        emit = progress or (lambda _m: None)
        topic = scrub(topic or "")  # the same rule as a roadblock: no e-mail, host, path or key leaves with a topic
        words = [w for w in re.findall(r"[a-z][a-z0-9+#.\-]*[a-z0-9+#]|[a-z]", topic.lower())
                 if w not in _STOP and w not in _LEARN_NOISE and len(w) > 1][:6]
        if not words:
            return {"error": "there was no topic to look for — say what you want to learn"}
        tags, _eco, _repos = _tags_of(topic)
        tag = tags[0] if tags else words[0]
        today = self.today()
        emit({"step": "topic", "state": "done", "query": " ".join(words), "tags": tags})
        errors: list[dict[str, str]] = []

        async def repos() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            emit({"step": "github", "state": "reading"})
            # two searches that look for lessons, not for popular products that merely use the words
            found = await asyncio.gather(*(self.sources.gh_repos(
                f"{' '.join(words[:4])} {kind} in:name,description,topics archived:false") for kind in ("example", "tutorial")))
            items, seen = [], set()
            for r in (x for batch in found for x in batch):
                if r.get("id") not in seen:
                    seen.add(r.get("id"))
                    items.append(r)
            ev, audit = verify.repos(words, items, today)
            emit({"step": "github", "state": "done", "received": audit["received"], "kept": audit["kept"]})
            return ev, audit

        async def devto() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            emit({"step": "devto", "state": "reading"})
            items = await self.sources.devto(tag)
            ev, audit = verify.articles(words, items, today)
            emit({"step": "devto", "state": "done", "received": audit["received"], "kept": audit["kept"]})
            return ev, audit

        async def so() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            emit({"step": "stackoverflow", "state": "reading"})
            items = await self.sources.so_top(";".join(tags[:2])) if len(tags) >= 2 else []  # both tags: on topic
            if len(items) < 3 and tags:
                seen = {q.get("question_id") for q in items}
                items += [q for q in await self.sources.so_top(tag) if q.get("question_id") not in seen]
            ev, audit = verify.top_questions(words, items)
            emit({"step": "stackoverflow", "state": "done", "received": audit["received"], "kept": audit["kept"]})
            return ev, audit

        jobs = [("github", repos()), ("devto", devto()), ("stackoverflow", so())]
        results = await asyncio.gather(*(j for _n, j in jobs), return_exceptions=True)
        by_type: dict[str, list[dict[str, Any]]] = {}
        audits = []
        for (name, _j), res in zip(jobs, results):
            if isinstance(res, BaseException):
                msg = res.message if isinstance(res, SourceError) else f"failed on the server ({type(res).__name__})"
                errors.append({"source": SOURCE_LABELS.get(name, name), "message": msg})
                emit({"step": name, "state": "failed", "message": msg})
                audits.append({"source": name, "received": 0, "kept": 0, "excluded": {}, "error": msg})
                continue
            ev, audit = res
            audits.append(audit)
            for e in ev:
                by_type.setdefault(e["type"], []).append(e)
        items: list[dict[str, Any]] = []
        for kind, cap in (("repo", 4), ("article", 3), ("so_question", 3)):
            items += sorted(by_type.get(kind, []), key=lambda e: -e.get("rank", 0))[:cap]
        items = items[:MAX_LEARN]
        for i, e in enumerate(items, 1):
            e["ref"] = f"L{i}"
        peers = self._peers(words, tags, topic)
        mentors = match_mentors(list(self.board.profiles.values()), [norm(t) for t in tags] or [norm(w) for w in words[:3]])
        for i, k in enumerate(peers, 1):
            k["ref"] = f"K{i}"
        for i, m in enumerate(mentors, 1):
            m["ref"] = f"M{i}"
        emit({"step": "board", "state": "done", "peers": len(peers), "mentors": len(mentors)})
        return {"id": _new_id(), "kind": "learn", "created": _now_iso(), "offline": self.offline,
                "query": {"text": " ".join(words), "tags": tags}, "items": items, "peers": peers, "mentors": mentors,
                "similar": [], "hints": [], "audit": audits, "errors": errors,
                "sources": [a["source"] for a in audits if not a.get("error")]}

    # ------------------------------------------------------------------ people
    async def people(self, text: str, me: dict[str, Any] | None, kind: str = "team",
                     progress: Progress | None = None) -> dict[str, Any]:
        """Teammates (``kind`` "team") or mentors ("mentors"): this event's board first, then real people from public
        sources — GitHub profiles in the event's city whose public repositories use what is asked for, and Stack
        Overflow's top answerers for the stack. Public people are leads, not people at this event."""
        emit = progress or (lambda _m: None)
        mentors_only = kind == "mentors"
        text = (text or "")[:600]
        profiles = list(self.board.profiles.values())
        if mentors_only:
            needs = needs_of(text, None)
            board_people, board_audit = [], {"source": "board", "received": 0, "kept": 0, "excluded": {}, "error": None}
        else:
            board_people, board_audit, needs = match_people(profiles, me, text)
        board_mentors = match_mentors(profiles, needs)
        board_audit = {**board_audit, "received": board_audit["received"] + sum(1 for p in profiles if p.get("kind") == "mentor"),
                       "kept": board_audit["kept"] + len(board_mentors)}
        emit({"step": "board", "state": "done", "people": len(board_people), "mentors": len(board_mentors)})
        location = location_in(text, getattr(self.s, "hub_event_location", "") or None)
        audits: list[dict[str, Any]] = [board_audit]
        errors: list[dict[str, str]] = []
        found_people: list[dict[str, Any]] = []
        found_experts: list[dict[str, Any]] = []
        languages = languages_for(needs)
        tags = so_tags_for(needs, text) if mentors_only else []
        jobs: list[tuple[str, Any]] = []
        if getattr(self.s, "hub_public_people", True):
            if not mentors_only and languages:
                jobs.append(("github", self._github_people(needs, languages, location, me, emit)))
            if mentors_only and tags:
                jobs.append(("stackoverflow", self._experts(tags, emit)))
        results = await asyncio.gather(*(j for _n, j in jobs), return_exceptions=True)
        for (name, _j), res in zip(jobs, results):
            if isinstance(res, BaseException):
                msg = res.message if isinstance(res, SourceError) else f"failed on the server ({type(res).__name__})"
                label = "GitHub" if name == "github" else "Stack Overflow"
                errors.append({"source": label, "message": msg})
                emit({"step": name, "state": "failed", "message": msg})
                audits.append({"source": "github_people" if name == "github" else "stackoverflow_experts",
                               "received": 0, "kept": 0, "excluded": {}, "error": msg})
                continue
            found, audit = res
            audits.append(audit)
            (found_people if name == "github" else found_experts).extend(found)
        items = board_people + found_people
        mentors = board_mentors + found_experts
        hints: list[str] = []
        for i, x in enumerate(items, 1):
            x["ref"] = f"P{i}"
        for i, m in enumerate(mentors, 1):
            m["ref"] = f"M{i}"
        capped = next((a["excluded"].get(k) for a in audits if a["source"] == "github_people"
                       for k in a.get("excluded") or {} if k.startswith("not read")), None)
        if capped and not self.status().get("github_token"):
            hints.append(f"Only the first few public profiles were read ({capped} more were found): without a token "
                         "GitHub allows 60 profile reads an hour — a GITHUB_TOKEN in .env reads more.")
        not_on_github = [n for n in needs if n in NOT_ON_GITHUB]
        if not mentors_only and not_on_github:
            hints.append(f"{', '.join(not_on_github)}: their work rarely shows on GitHub — this event's board and a "
                         "help request are the places to find them.")
        if not needs:
            hints.append("No skill or role was named — say what the team needs (e.g. frontend, design, ML) to search "
                         "public profiles too.")
        return {"id": _new_id(), "kind": "mentors" if mentors_only else "team", "created": _now_iso(),
                "offline": self.offline,
                "query": {"text": text[:300], "needs": needs, "location": location, "languages": languages,
                          "tags": tags,
                          "me": {k: (me or {}).get(k) for k in ("name", "skills", "looking_for", "interests", "team")}
                          if me else None},
                "items": items, "peers": [], "mentors": mentors, "similar": [], "hints": hints, "audit": audits,
                "errors": errors, "sources": [a["source"] for a in audits if not a.get("error")]}

    async def _github_people(self, needs: list[str], languages: list[str], location: str | None,
                             me: dict[str, Any] | None, emit: Progress) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        emit({"step": "github", "state": "reading"})
        batches = await asyncio.gather(*(self.sources.gh_search_users(github_user_query(lang, location))
                                         for lang in languages))
        mine = str((me or {}).get("github") or "").lower()
        cands, seen = [], set()
        # one from each search in turn: the few profiles GitHub lets us read are shared between the languages
        for u in (x for row in itertools.zip_longest(*batches) for x in row if x is not None):
            login = str(u.get("login") or "")
            if login and login.lower() not in seen and login.lower() != mine:
                seen.add(login.lower())
                cands.append(u)
        # each profile costs two reads (the profile, its repositories): 60 an hour without a token
        read = cands[:(MAX_PUBLIC_PEOPLE + 6) if self.status().get("github_token") else (MAX_PUBLIC_PEOPLE + 1)]
        audit = {"source": "github_people", "received": len(cands), "kept": 0, "excluded": {}, "error": None}
        ex: dict[str, int] = {}
        if len(cands) > len(read):
            ex["not read (GitHub's rate limit: only the first few profiles are read)"] = len(cands) - len(read)
        details = await asyncio.gather(*(self.sources.gh_user(u["login"]) for u in read), return_exceptions=True)
        today = self.today()
        out: list[dict[str, Any]] = []
        failed: SourceError | None = None
        for u, d in zip(read, details):
            if isinstance(d, BaseException):
                failed = d if isinstance(d, SourceError) else failed
                ex["could not be read"] = ex.get("could not be read", 0) + 1
                continue
            user, repos = d
            person, why = public_person(user, repos, needs, today)
            if person is None:
                ex[why or "left out"] = ex.get(why or "left out", 0) + 1
                continue
            out.append(person)
        if failed is not None and not out:
            raise failed  # nothing could be read: say why (usually GitHub's limit)
        out.sort(key=lambda x: -x["score"])
        if len(out) > MAX_PUBLIC_PEOPLE:
            ex["more than the four shown"] = len(out) - MAX_PUBLIC_PEOPLE
        audit["kept"] = min(len(out), MAX_PUBLIC_PEOPLE)
        audit["excluded"] = dict(sorted(ex.items(), key=lambda kv: -kv[1]))
        emit({"step": "github", "state": "done", "received": audit["received"], "kept": audit["kept"]})
        return out[:MAX_PUBLIC_PEOPLE], audit

    async def _experts(self, tags: list[str], emit: Progress) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        emit({"step": "stackoverflow", "state": "reading"})
        jobs = [(tag, period) for tag in tags for period in ("all_time", "month")]
        res = await asyncio.gather(*(self.sources.so_top_answerers(tag, period) for tag, period in jobs))
        found: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for (tag, period), items in zip(jobs, res):
            found.setdefault(tag, {})[period] = items
        out, audit = experts(found)
        emit({"step": "stackoverflow", "state": "done", "received": audit["received"], "kept": audit["kept"]})
        return out, audit

    # ------------------------------------------------------------------ questions someone here could answer
    async def open_questions(self, tags: list[str]) -> dict[str, Any]:
        """Real Stack Overflow questions with these tags that are still unsolved (the newest first). A narrow tag
        with few new questions gets its language's tag as the second one ([fastapi] → [python])."""
        tags = [t for t in dict.fromkeys(tags) if t][:2]
        if len(tags) == 1:
            _t, eco, _r = _tags_of(tags[0])
            lang = {"pypi": "python", "npm": "javascript"}.get(eco)
            if lang and lang != tags[0]:
                tags.append(lang)
        if not tags:
            return {"tags": [], "items": [], "audit": [], "errors": [], "offline": self.offline, "as_of": _now_iso()}
        res = await asyncio.gather(*(self.sources.so_open_questions(t) for t in tags), return_exceptions=True)
        items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for t, r in zip(tags, res):
            if isinstance(r, BaseException):
                msg = r.message if isinstance(r, SourceError) else f"failed on the server ({type(r).__name__})"
                errors.append({"source": "Stack Overflow", "message": msg})
            else:
                items += r
        found, audit = verify.open_questions(items, self.today(), limit=None)
        # the tags in turn, newest first in each: a busy language tag must not crowd out the stack's own
        by_tag = [[x for x in found if t in x["tags"]] for t in tags]
        kept: list[dict[str, Any]] = []
        seen: set[Any] = set()
        for x in (x for row in itertools.zip_longest(*by_tag) for x in row if x is not None):
            if x["id"] not in seen:
                seen.add(x["id"])
                kept.append(x)
        shown = kept[:verify.MAX_OPEN_QUESTIONS]
        audit["kept"] = len(shown)
        if len(found) > len(shown):
            audit["excluded"]["more than the six shown"] += len(found) - len(shown)
        audit["excluded"] = dict(audit["excluded"].most_common())
        return {"tags": tags, "items": shown, "audit": [audit], "errors": errors, "offline": self.offline,
                "as_of": _now_iso()}

    # ------------------------------------------------------------------ GitHub, for someone who asked for it
    def verify_later(self, profile: dict[str, Any]) -> None:
        if not profile.get("github") or not profile.get("github_consent"):
            return

        async def run() -> None:
            try:
                ev = await github_evidence(self.sources, profile["github"], self.today())
            except SourceError as e:
                ev = {"login": profile["github"], "found": None, "error": e.message, "checked_at": _now_iso(), "skills": {}}
            except Exception as e:  # noqa: BLE001
                log.warning("github check failed: %r", e)
                ev = {"login": profile["github"], "found": None, "error": "failed on the server",
                      "checked_at": _now_iso(), "skills": {}}
            await self.board.set_verified(profile["id"], ev, login=profile["github"])

        task = asyncio.ensure_future(run())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)


def item_by_ref(report: dict[str, Any], ref: str) -> dict[str, Any] | None:
    ref = ref.upper()
    return next((x for g in ("items", "peers", "mentors") for x in report.get(g) or [] if x.get("ref") == ref), None)


def refs_of(report: dict[str, Any]) -> list[str]:
    return [x["ref"] for g in ("items", "peers", "mentors") for x in report.get(g) or [] if x.get("ref")]


def default_board_path(settings: Any) -> Path:
    return Path(settings.hub_board_path)
