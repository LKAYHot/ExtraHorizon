"""What the hub keeps from the public sources, and why the rest is left out.

Every source is audited like the county's records: how many results arrived, how many were kept, and how many
were excluded for which reason. A kept result carries what makes it trustworthy (an accepted answer and its votes,
an issue closed as fixed, a registry's own data) and the flags that make it weaker (an old answer, an open issue).
"""

from __future__ import annotations

import datetime as dt
import html
import math
import re
from collections import Counter
from html.parser import HTMLParser
from typing import Any

from .signature import IMPORT_TO_PYPI, Signature, relevance

OLD_YEARS = 5  # an answer older than this is flagged: check it against today's versions
MIN_RELEVANCE = 0.5
MIN_VOTES_UNACCEPTED = 3  # an answer that was not accepted needs at least this many votes
STALE_REPO_DAYS = 3 * 365  # a learning repo untouched this long is left out; older than two years is flagged
_LEARNING = re.compile(r"tutorial|example|starter|template|boilerplate|demo|guide|course|learn|sample|workshop|"
                       r"playground|cookbook|how-?to|\b101\b", re.I)
MAX_EXCERPT_TEXT = 320
MAX_EXCERPT_CODE = 600


class _Body(HTMLParser):
    """Stack Exchange bodies (HTML) → paragraphs and code blocks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paras: list[str] = []
        self.codes: list[str] = []
        self._buf: list[str] = []
        self._pre = 0
        self._in_block = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "pre":
            self._flush()
            self._pre += 1
        elif tag in ("p", "li", "blockquote", "h1", "h2", "h3") and not self._pre:
            self._flush()
            self._in_block = True
        elif tag == "br" and not self._pre:
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre" and self._pre:
            self._pre -= 1
            code = "".join(self._buf).strip("\n")
            if code.strip():
                self.codes.append(code)
            self._buf = []
        elif tag in ("p", "li", "blockquote", "h1", "h2", "h3") and not self._pre:
            self._flush()

    def handle_data(self, data: str) -> None:
        self._buf.append(data)

    def _flush(self) -> None:
        if not self._pre:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if text:
                self.paras.append(text)
            self._buf = []


def body_parts(body: str) -> tuple[list[str], list[str]]:
    p = _Body()
    try:
        p.feed(body or "")
        p.close()
    except Exception:  # noqa: BLE001 — a malformed body gives what could be read
        pass
    p._flush()
    return p.paras, p.codes


def plain(body: str, limit: int = 4000) -> str:
    paras, codes = body_parts(body)
    return (" ".join(paras) + " " + " ".join(codes))[:limit]


def _clip(text: str, n: int) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _as_command(code: str) -> str:
    lines = [re.sub(r"^\s*[$>#]\s+", "", line) for line in code.strip().splitlines() if line.strip()]
    return " ".join(" ".join(lines).lower().split())


def _best_code(sig: Signature, codes: list[str]) -> str:
    """The answer's code block that is about this error (the fix), not the first one (often their setup code) and not
    the command that already failed for them ("npm install fails" → not a block that says only `npm install`)."""
    keys = {w.lower() for w in sig.words} | {t.lower() for t in sig.tags} | {p.lower() for p in sig.packages + sig.mentioned}
    keys |= {k.replace(".", "") for k in keys}
    ran = set(sig.ran)

    def score(code: str) -> int:
        if _as_command(code) in ran:
            return -1
        low = code.lower()
        return sum(1 for k in keys if len(k) > 2 and k in low)
    best = max(range(len(codes)), key=lambda i: (score(codes[i]), -i))
    return codes[best]


def _clip_code(code: str) -> str:
    lines = code.strip("\n").splitlines()[:14]
    out = "\n".join(line.rstrip() for line in lines)
    return out[:MAX_EXCERPT_CODE] + ("\n…" if len(out) > MAX_EXCERPT_CODE or len(code.splitlines()) > 14 else "")


def _day(ts: int | float | None) -> str | None:
    if not ts:
        return None
    return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).date().isoformat()


def _years(day: str | None, today: dt.date) -> float:
    if not day:
        return 0.0
    return (today - dt.date.fromisoformat(day[:10])).days / 365.25


def _matched(sig: Signature, text: str) -> list[str]:
    low = text.lower()
    have = set(re.findall(r"[a-z][a-z0-9+#.\-]*[a-z0-9+#]|[a-z]", low))
    return [w for w in sig.words if w in have or (len(w) > 4 and w in low)][:8]


def _audit(source: str, received: int) -> dict[str, Any]:
    return {"source": source, "received": received, "kept": 0, "excluded": Counter(), "error": None}


def _finish(audit: dict[str, Any]) -> dict[str, Any]:
    audit["excluded"] = dict(audit["excluded"].most_common())
    return audit


# ---------------------------------------------------------------------- Stack Overflow
def stackoverflow(sig: Signature, questions: list[dict[str, Any]], answers: list[dict[str, Any]],
                  today: dt.date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit = _audit("stackoverflow", len(questions))
    by_q: dict[int, list[dict[str, Any]]] = {}
    for a in answers:
        by_q.setdefault(int(a.get("question_id", 0)), []).append(a)
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for q in questions:
        qid = int(q.get("question_id", 0))
        if qid in seen:
            continue
        seen.add(qid)
        title = html.unescape(q.get("title") or "")
        if (q.get("score") or 0) < 0:
            audit["excluded"]["the question is voted down"] += 1
            continue
        text = f"{title} {' '.join(q.get('tags') or [])} {plain(q.get('body') or '', 3000)}"
        rel = relevance(sig, text)
        if rel < MIN_RELEVANCE:
            audit["excluded"]["not about this error"] += 1
            continue
        ans = by_q.get(qid, [])
        accepted = next((a for a in ans if a.get("is_accepted")), None)
        best = accepted or max(ans, key=lambda a: a.get("score") or 0, default=None)
        if best is None:
            audit["excluded"]["its answers could not be read" if (q.get("answer_count") or 0) else "no answer yet"] += 1
            continue
        votes = int(best.get("score") or 0)
        if accepted is None and votes < MIN_VOTES_UNACCEPTED:
            audit["excluded"]["no accepted or well-voted answer"] += 1
            continue
        paras, codes = body_parts(best.get("body") or "")
        day = _day(best.get("creation_date"))
        old = _years(day, today) > OLD_YEARS
        owner = best.get("owner") or {}
        out.append({
            "type": "stackoverflow",
            "source": "Stack Overflow",
            "title": title,
            "url": q.get("link") or f"https://stackoverflow.com/q/{qid}",
            "answer_url": f"https://stackoverflow.com/a/{best.get('answer_id')}",
            "question_id": qid,
            "accepted": accepted is not None,
            "votes": votes,
            "answers": int(q.get("answer_count") or len(ans)),
            "date": day,
            "tags": list(q.get("tags") or [])[:6],
            "relevance": rel,
            "matched": _matched(sig, text),
            "excerpt": {"text": _clip(html.unescape(paras[0]), MAX_EXCERPT_TEXT) if paras else "",
                        "code": _clip_code(html.unescape(_best_code(sig, codes))) if codes else ""},
            "attribution": {"author": html.unescape(str(owner.get("display_name") or "a Stack Overflow user")),
                            "author_url": owner.get("link"),
                            "license": best.get("content_license") or "CC BY-SA"},
            "flags": (["accepted answer"] if accepted is not None else ["top-voted answer"])
                     + ([f"answer from {day[:4]} — check it against today's versions"] if old and day else []),
            "rank": round(3 * rel + math.log10(max(votes, 0) + 1) + (1.2 if accepted else 0.0) + (0.5 if codes else 0.0)
                          - (0.6 if old else 0.0), 3),
        })
    audit["kept"] = len(out)
    return out, _finish(audit)


# ---------------------------------------------------------------------- GitHub issues
def github_issues(sig: Signature, issues: list[dict[str, Any]], today: dt.date
                  ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit = _audit("github", len(issues))
    out: list[dict[str, Any]] = []
    for it in issues:
        if it.get("pull_request"):
            audit["excluded"]["a pull request, not an issue"] += 1
            continue
        if it.get("active_lock_reason") in ("spam", "too heated", "off-topic"):
            audit["excluded"]["locked as spam or off-topic"] += 1
            continue
        title = it.get("title") or ""
        body = re.sub(r"\s+", " ", it.get("body") or "")
        rel = relevance(sig, f"{title} {body[:3000]}")
        if rel < MIN_RELEVANCE:
            audit["excluded"]["not about this error"] += 1
            continue
        repo = (it.get("repository_url") or "").split("/repos/")[-1]
        reactions = int((it.get("reactions") or {}).get("total_count") or 0)
        comments = int(it.get("comments") or 0)
        fixed = it.get("state") == "closed" and it.get("state_reason") in ("completed", None)
        if not fixed and comments < 3 and reactions < 5:
            audit["excluded"]["open, and nobody has answered it yet"] += 1
            continue
        closed = (it.get("closed_at") or "")[:10] or None
        official = repo in sig.repos
        flags = []
        if fixed:
            flags.append("closed as fixed")
        elif it.get("state") == "closed":
            flags.append("closed without a fix")
        else:
            flags.append("still open")
        if official:
            flags.append("the project's own tracker")
        else:
            flags.append("another project's tracker — a lead, not a command to copy")
        out.append({
            "type": "github_issue",
            "source": f"GitHub · {repo}",
            "title": title,
            "url": it.get("html_url"),
            "repo": repo,
            "number": it.get("number"),
            "state": it.get("state"),
            "comments": comments,
            "reactions": reactions,
            "date": closed or (it.get("created_at") or "")[:10] or None,
            "opened": (it.get("created_at") or "")[:10] or None,
            "closed": closed,
            "relevance": rel,
            "matched": _matched(sig, f"{title} {body}"),
            "excerpt": {"text": _clip(re.sub(r"[#*`>]+", " ", body), 220), "code": ""},
            "attribution": {"author": (it.get("user") or {}).get("login"), "author_url": (it.get("user") or {}).get("html_url"),
                            "license": ""},
            "flags": flags,
            "rank": round(3 * rel + (1.0 if fixed else 0.0) + (0.5 if official else -0.5)
                          + 0.7 * math.log10(comments + reactions + 1), 3),
        })
    audit["kept"] = len(out)
    return out, _finish(audit)


# ---------------------------------------------------------------------- the registries
def packages(sig: Signature, found: dict[str, tuple[str, dict[str, Any] | None]],
             soft: set[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """``found``: the name the signature named → (registry, what the registry returned or None). A ``soft`` name
    (one they mentioned, not one the error names) that the registry does not know is left out quietly."""
    audit = _audit("registries", len(found))
    out: list[dict[str, Any]] = []
    for named, (registry, data) in found.items():
        if data is None and named in (soft or set()):
            audit["excluded"]["a mentioned name that is not a package"] += 1
            continue
        if registry == "pypi":
            real = IMPORT_TO_PYPI.get(named)
            if data is None:
                audit["excluded"]["not on PyPI"] += 1
                out.append({"type": "package", "source": "PyPI", "registry": "pypi", "name": real or named,
                            "exists": False, "title": f"No PyPI package is named {real or named}",
                            "url": f"https://pypi.org/project/{real or named}/", "date": None,
                            "facts": [f"PyPI has no package named {real or named}"], "flags": ["not found"],
                            "rank": 5.0})
                continue
            info = data.get("info") or {}
            facts = [f"latest version {info.get('version')}"]
            if info.get("requires_python"):
                facts.append(f"requires Python {info['requires_python']}")
            if real:
                facts.insert(0, f"the import name {named} comes from the PyPI package {info.get('name') or real}")
                facts.append(f"install it with: pip install {info.get('name') or real}")
            if info.get("yanked"):
                facts.append("the latest release was yanked")
            docs = (info.get("project_urls") or {}).get("Documentation") or info.get("home_page") or info.get("package_url")
            out.append({"type": "package", "source": "PyPI", "registry": "pypi", "name": info.get("name") or real or named,
                        "exists": True, "title": f"{info.get('name') or real or named} on PyPI",
                        "url": info.get("package_url") or f"https://pypi.org/project/{real or named}/",
                        "docs": docs, "version": info.get("version"), "summary": _clip(info.get("summary") or "", 160),
                        "date": data.get("latest_upload"), "facts": facts,
                        "flags": ["import name ≠ package name"] if real else [], "rank": 9.0 if real else 2.2})
        else:
            if data is None:
                audit["excluded"]["not on npm"] += 1
                out.append({"type": "package", "source": "npm registry", "registry": "npm", "name": named, "exists": False,
                            "title": f"No npm package is named {named}", "url": f"https://www.npmjs.com/package/{named}",
                            "date": None, "facts": [f"the npm registry has no package named {named}"],
                            "flags": ["not found"], "rank": 5.0})
                continue
            facts = [f"latest version {data.get('version')}"]
            node = (data.get("engines") or {}).get("node")
            if node:
                facts.append(f"needs Node {node}")
            peers = data.get("peerDependencies") or {}
            if peers:
                facts.append("peer dependencies: " + ", ".join(f"{k} {v}" for k, v in list(peers.items())[:4]))
            if data.get("deprecated"):
                facts.append(f"deprecated: {_clip(str(data['deprecated']), 140)}")
            out.append({"type": "package", "source": "npm registry", "registry": "npm", "name": data.get("name") or named,
                        "exists": True, "title": f"{data.get('name') or named} on npm",
                        "url": f"https://www.npmjs.com/package/{data.get('name') or named}",
                        "docs": data.get("homepage"), "version": data.get("version"), "date": None,
                        "summary": _clip(str(data.get("description") or ""), 160), "facts": facts,
                        "flags": (["deprecated"] if data.get("deprecated") else [])
                                 + (["its peer dependencies"] if peers and sig.kind == "ERESOLVE" else []),
                        # a peer-dependency conflict is settled by what the package itself asks for
                        "rank": 7.0 if data.get("deprecated") else 8.0 if peers and sig.kind == "ERESOLVE" else 2.0})
    audit["kept"] = sum(1 for o in out if o.get("exists"))
    return out, _finish(audit)


# ---------------------------------------------------------------------- learning
def _topic_rel(words: list[str], text: str) -> float:
    if not words:
        return 0.0
    low = text.lower()
    return round(sum(1 for w in words if w in low) / len(words), 3)


def repos(words: list[str], items: list[dict[str, Any]], today: dt.date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit = _audit("github", len(items))
    out = []
    for r in items:
        if r.get("archived"):
            audit["excluded"]["archived"] += 1
            continue
        pushed = (r.get("pushed_at") or "")[:10]
        if pushed and (today - dt.date.fromisoformat(pushed)).days > STALE_REPO_DAYS:
            audit["excluded"]["no push in three years"] += 1
            continue
        text = f"{r.get('full_name')} {r.get('description') or ''} {' '.join(r.get('topics') or [])}"
        rel = _topic_rel(words, text)
        if rel < (1.0 if len(words) <= 3 else 0.75):
            audit["excluded"]["not about this topic"] += 1
            continue
        stars = int(r.get("stargazers_count") or 0)
        lic = ((r.get("license") or {}).get("spdx_id") or "")
        learning = bool(r.get("is_template")) or bool(_LEARNING.search(f"{r.get('name') or r.get('full_name')} {r.get('description') or ''}"))
        if not learning and stars < 100:
            audit["excluded"]["a project, not a tutorial or example"] += 1
            continue
        old = bool(pushed) and (today - dt.date.fromisoformat(pushed)).days > 730
        out.append({"type": "repo", "source": "GitHub", "title": r.get("full_name"), "url": r.get("html_url"),
                    "summary": _clip(r.get("description") or "", 200), "stars": stars, "date": pushed or None,
                    "license": lic if lic and lic != "NOASSERTION" else "", "language": r.get("language"),
                    "flags": (["tutorial / example"] if learning else ["a project to read, not a tutorial"])
                             + ([f"last push {pushed[:4]} — check it against today's versions"] if old else [])
                             + ([] if lic and lic != "NOASSERTION" else ["no licence"]),
                    "relevance": rel,
                    "rank": round(2 * rel + 0.5 * math.log10(stars + 1) + (2.0 if learning else 0.0) - (0.5 if old else 0.0), 3)})
    audit["kept"] = len(out)
    return out, _finish(audit)


def articles(words: list[str], items: list[dict[str, Any]], today: dt.date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit = _audit("devto", len(items))
    out = []
    for a in items:
        day = (a.get("published_at") or "")[:10]
        if day and (today - dt.date.fromisoformat(day)).days > 3 * 365:
            audit["excluded"]["older than three years"] += 1
            continue
        reactions = int(a.get("public_reactions_count") or a.get("positive_reactions_count") or 0)
        if reactions < 3:
            audit["excluded"]["fewer than 3 reactions"] += 1
            continue
        tags = a.get("tag_list") if isinstance(a.get("tag_list"), list) else re.split(r",\s*", a.get("tags") or "")
        text = f"{a.get('title')} {a.get('description') or ''} {' '.join(tags)}"
        rel = _topic_rel(words, text)
        if rel < MIN_RELEVANCE:
            audit["excluded"]["not about this topic"] += 1
            continue
        out.append({"type": "article", "source": "DEV Community", "title": a.get("title"), "url": a.get("url"),
                    "summary": _clip(a.get("description") or "", 200), "reactions": reactions,
                    "minutes": a.get("reading_time_minutes"), "date": day or None,
                    "attribution": {"author": (a.get("user") or {}).get("name"), "license": ""},
                    "flags": [], "relevance": rel,
                    "rank": round(2 * rel + math.log10(reactions + 1), 3)})
    audit["kept"] = len(out)
    return out, _finish(audit)


def top_questions(words: list[str], items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit = _audit("stackoverflow", len(items))
    out = []
    for q in items:
        if int(q.get("score") or 0) < 25 or not q.get("accepted_answer_id"):
            audit["excluded"]["fewer than 25 votes or no accepted answer"] += 1
            continue
        title = html.unescape(q.get("title") or "")
        if len(words) >= 2 and _topic_rel(words, f"{title} {' '.join(q.get('tags') or [])}") < 0.75:
            audit["excluded"]["not about this topic"] += 1
            continue
        out.append({"type": "so_question", "source": "Stack Overflow", "title": title, "url": q.get("link"),
                    "votes": int(q.get("score") or 0), "answers": int(q.get("answer_count") or 0),
                    "date": _day(q.get("creation_date")), "tags": list(q.get("tags") or [])[:5], "flags": ["accepted answer"],
                    "relevance": _topic_rel(words, title), "rank": round(math.log10(int(q.get('score') or 0) + 1), 3)})
    audit["kept"] = len(out)
    return out, _finish(audit)


# ---------------------------------------------------------------------- questions someone here could answer
OPEN_QUESTION_DAYS = 180  # Stack Overflow is quieter than it was: a niche tag's newest unsolved question can be months old
MAX_OPEN_QUESTIONS = 6


def open_questions(items: list[dict[str, Any]], today: dt.date,
                   limit: int | None = MAX_OPEN_QUESTIONS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Stack Overflow questions that are still unsolved (no accepted, no upvoted answer): asked in the last six
    months, open, not voted down — real people stuck, for the help board ("learn by helping"). Their age is shown."""
    audit = _audit("stackoverflow_open", len(items))
    out, seen = [], set()
    for q in sorted(items, key=lambda q: -int(q.get("creation_date") or 0)):
        qid = q.get("question_id")
        if qid in seen:
            continue
        seen.add(qid)
        asked = _day(q.get("creation_date"))
        if q.get("closed_date") or q.get("closed_reason"):
            audit["excluded"]["closed"] += 1
        elif q.get("is_answered") or q.get("accepted_answer_id"):
            audit["excluded"]["already answered"] += 1
        elif int(q.get("score") or 0) < 0:
            audit["excluded"]["voted down"] += 1
        elif not asked or (today - dt.date.fromisoformat(asked)).days > OPEN_QUESTION_DAYS:
            audit["excluded"][f"asked more than {OPEN_QUESTION_DAYS} days ago"] += 1
        else:
            owner = q.get("owner") or {}
            out.append({"id": qid, "title": html.unescape(q.get("title") or ""), "url": q.get("link"),
                        "tags": list(q.get("tags") or [])[:5], "asked": asked, "views": int(q.get("view_count") or 0),
                        "answers": int(q.get("answer_count") or 0),
                        "score": int(q.get("score") or 0), "author": html.unescape(owner.get("display_name") or ""),
                        "license": "CC BY-SA 4.0"})
    if limit is None:  # the caller picks (and counts) what is shown
        audit["kept"] = len(out)
        return out, audit
    audit["kept"] = min(len(out), limit)
    if len(out) > limit:
        audit["excluded"]["more than the six shown"] += len(out) - limit
    return out[:limit], _finish(audit)
