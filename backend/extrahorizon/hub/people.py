"""Who to team up with and who can help: matching on this event's board, and real people from public sources.

* **The board** — people who put a card here (their own words). A skill on a card is theirs to claim; "seen on GitHub"
  only says the public, non-fork repositories of the username on their card use it (a language GitHub reports, a
  topic, a framework in a repository's name) — never that they are good at it.
* **Public GitHub profiles** — developers in the event's city whose public repositories use the languages asked for
  (GitHub's own user search). Read: their public name, the city they wrote, their public repositories (languages,
  topics, names, last push), whether they marked themselves available for hire, and a few words their bio uses
  ("student", "hackathon" …) — never their e-mail, links, company or bio text. They are not at this event unless they
  are on the board, and have not said they are looking for a team: a lead for one polite public message.
* **Stack Overflow's top answerers** for the stack's tags (all time and this month) — public experts, not mentors at
  this event: they answer questions asked with that tag.

Nothing is combined across sources: a person from GitHub and one from Stack Overflow are separate results.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from typing import Any

from .board import TEAM_MAX
from .skills import GITHUB_LANGUAGES, ROLES, covers, norm, roles_in, skills_in

MAX_PEOPLE = 6
MAX_MENTORS = 3
MAX_PUBLIC_PEOPLE = 4  # public profiles shown
MAX_EXPERTS = 4
ACTIVE_DAYS = 365  # a profile with no public push for a year is not a lead for tonight
MIN_EXPERT_ANSWERS = 10  # all-time answers on the tag

# what GitHub's user search can look for: a skill or a role → the languages its public repositories are written in
_LANG = {
    "python": ["Python"], "fastapi": ["Python"], "flask": ["Python"], "django": ["Python"], "pandas": ["Python"],
    "numpy": ["Python"], "machine learning": ["Python"], "deep learning": ["Python"], "pytorch": ["Python"],
    "tensorflow": ["Python"], "scikit-learn": ["Python"], "computer vision": ["Python"], "opencv": ["Python"],
    "nlp": ["Python"], "llms": ["Python"], "mediapipe": ["Python"], "data visualization": ["Python"],
    "raspberry pi": ["Python"], "javascript": ["JavaScript"], "typescript": ["TypeScript"],
    "react": ["TypeScript", "JavaScript"], "next.js": ["TypeScript"], "node.js": ["JavaScript", "TypeScript"],
    "express": ["JavaScript"], "angular": ["TypeScript"], "react native": ["TypeScript"], "tailwind": ["TypeScript"],
    "svelte": ["Svelte"], "vue": ["Vue"], "html": ["HTML"], "css": ["CSS"], "flutter": ["Dart"], "dart": ["Dart"],
    "swift": ["Swift"], "ios": ["Swift"], "kotlin": ["Kotlin"], "android": ["Kotlin", "Java"], "arduino": ["C++"],
    "esp32": ["C++"], "c++": ["C++"], "c": ["C"], "iot": ["C++"], "go": ["Go"], "rust": ["Rust"], "java": ["Java"],
    "spring-boot": ["Java"], "c#": ["C#"], "unity": ["C#"], "godot": ["GDScript"], "solidity": ["Solidity"],
    "r": ["R"], "php": ["PHP"], "ruby": ["Ruby"],
    # roles
    "frontend": ["TypeScript", "JavaScript"], "backend": ["Python", "Go"], "fullstack": ["TypeScript", "Python"],
    "ml": ["Python"], "data": ["Python"], "mobile": ["Swift", "Kotlin"], "hardware": ["C++"], "game": ["C#"],
}
# roles GitHub cannot show (their work is not code): the board is the place for them
NOT_ON_GITHUB = {"design", "pitch", "product", "devops"}

# Stack Overflow tags for a role, when the question names no stack
_ROLE_TAGS = {
    "frontend": ["reactjs", "javascript"], "backend": ["fastapi", "node.js"], "fullstack": ["reactjs", "node.js"],
    "ml": ["pytorch", "machine-learning"], "data": ["pandas", "sql"], "mobile": ["flutter", "android"],
    "hardware": ["arduino", "esp32"], "devops": ["docker", "kubernetes"], "game": ["unity-game-engine", "godot"],
}
_SKILL_TAGS = {"react": "reactjs", "vue": "vue.js", "machine learning": "machine-learning", "deep learning": "deep-learning",
               "computer vision": "computer-vision", "unity": "unity-game-engine", "raspberry pi": "raspberry-pi",
               "tailwind": "tailwind-css", "c#": "c#", "react native": "react-native", "data visualization": "d3.js",
               "llms": "large-language-model", "spring-boot": "spring-boot", "go": "go"}

# a few words a public bio uses — only these flags are kept, never the bio itself
_BIO_SIGNALS = (
    ("hackathons", re.compile(r"hackath|devpost|\bmlh\b", re.I)),
    ("a student", re.compile(r"\bstudent\b|\bundergrad|\bcs major\b|\bclass of 20\d\d\b|\bfreshman\b|\bsophomore\b", re.I)),
    ("a university", re.compile(r"universit|\bcollege\b|\bfiu\b|institute of technology", re.I)),
    ("open to collaborating", re.compile(r"open to (?:collab\w*|new projects|opportunit\w*)|looking for (?:a )?(?:team\w*|"
                                         r"collab\w*)|let'?s (?:build|collaborate|connect)", re.I)),
)
_REMOTE = re.compile(r"\b(?:remote(?:ly)?|anywhere|online|worldwide|any city|any location)\b", re.I)
_PLACE = re.compile(r"\b(?i:in|near|around|from|based in|located in)\s+((?:[A-Z][\w'.-]+)(?:,?\s+[A-Z][\w'.-]+){0,2})")
_NOT_PLACES = {"english", "russian", "spanish", "the", "a", "my", "our", "this", "that", "person", "team", "discord",
               "github", "slack", "devpost", "hackathon", "shellhacks", "english,", "general"}


def _clip(text: Any, limit: int) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t[:limit] + ("…" if len(t) > limit else "")


# ---------------------------------------------------------------------- what public repositories show
def repo_skills(repos: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int, str]:
    """Skills seen in someone's own public repositories: {skill: {repos, last_push}}, how many are their own, the last
    push to any of them."""
    own = [r for r in repos if not r.get("fork")]
    skills: dict[str, dict[str, Any]] = {}
    for r in own:
        found: set[str] = set()
        lang = r.get("language")
        if lang in GITHUB_LANGUAGES:
            found.add(GITHUB_LANGUAGES[lang])
        for t in r.get("topics") or []:
            found.update(skills_in(str(t).replace("-", " ")) or [])
        found.update(skills_in(f"{str(r.get('name') or '').replace('-', ' ').replace('_', ' ')} {r.get('description') or ''}"))
        pushed = (r.get("pushed_at") or "")[:10]
        for s in found:
            e = skills.setdefault(s, {"repos": 0, "last_push": ""})
            e["repos"] += 1
            e["last_push"] = max(e["last_push"], pushed)
    top = dict(sorted(skills.items(), key=lambda kv: (-kv[1]["repos"], kv[0]))[:16])
    last = max(((r.get("pushed_at") or "")[:10] for r in own), default="")
    return top, len(own), last


async def github_evidence(sources: Any, login: str, today: dt.date | None = None) -> dict[str, Any]:
    """What a public GitHub account shows (for a board card whose author typed the username and ticked the box)."""
    user, repos = await sources.gh_user(login)
    checked = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if not user:
        return {"login": login, "found": False, "checked_at": checked, "skills": {}}
    skills, own, _last = repo_skills(repos)
    return {"login": user.get("login") or login, "found": True, "type": user.get("type"),
            "public_repos": user.get("public_repos"), "own_repos": own, "checked_at": checked,
            "profile_url": user.get("html_url") or f"https://github.com/{login}", "skills": skills}


def evidence_line(skill: str, verified: dict[str, Any] | None) -> str | None:
    e = ((verified or {}).get("skills") or {}).get(skill)
    if not e:
        return None
    n = e["repos"]
    return f"{skill} in {n} public GitHub repo{'s' if n != 1 else ''}" + (f" (last push {e['last_push']})" if e.get("last_push") else "")


# ---------------------------------------------------------------------- the board
def _verified_set(p: dict[str, Any]) -> set[str]:
    v = p.get("verified") or {}
    return set((v.get("skills") or {}).keys()) if v.get("found") else set()


def _night(a: str) -> bool:
    a = (a or "").lower()
    return "night" in a or "2 am" in a or "late" in a


def needs_of(text: str, me: dict[str, Any] | None) -> list[str]:
    needs: list[str] = []
    for n in roles_in(text) + skills_in(text) + list((me or {}).get("looking_for") or []):
        n = norm(n)
        if n and n not in needs:
            needs.append(n)
    return needs[:8]


def match_people(profiles: list[dict[str, Any]], me: dict[str, Any] | None, text: str,
                 limit: int = MAX_PEOPLE) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Hackers on the board who fit: they cover what is asked for (verified skills count more), bring skills the
    asker's team lacks, share interests, and the teams together stay within four people."""
    needs = needs_of(text, me)
    mine = set((me or {}).get("skills") or [])
    my_int = set((me or {}).get("interests") or [])
    my_size = int(((me or {}).get("team") or {}).get("size") or 1)
    audit = {"source": "board", "received": 0, "kept": 0, "excluded": {}, "error": None}
    ex: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for p in profiles:
        if p.get("kind") != "hacker" or (me and p.get("id") == me.get("id")):
            continue
        audit["received"] += 1
        size = int((p.get("team") or {}).get("size") or 1)
        if my_size + size > TEAM_MAX:
            ex["together the team would be larger than four"] = ex.get("together the team would be larger than four", 0) + 1
            continue
        skills = set(p.get("skills") or [])
        seen = _verified_set(p)
        covered = [n for n in needs if covers(skills, n)]
        if needs and not covered:
            ex["has none of the skills asked for"] = ex.get("has none of the skills asked for", 0) + 1
            continue
        new = sorted(skills - mine)
        shared = sorted(my_int & set(p.get("interests") or []))
        score = sum(1.0 if covers(seen, n) else 0.6 for n in covered) + 0.12 * len(new) + 0.3 * len(shared)
        if me and _night(me.get("availability", "")) and _night(p.get("availability", "")):
            score += 0.15
        if not needs:
            score += 0.2 * len(new)
        proof = [line for s in sorted(skills) if (line := evidence_line(s, p.get("verified")))]
        out.append({**{k: v for k, v in p.items() if k not in ("owner",)}, "source": "board",
                    "covers": covered, "new_skills": new[:6], "shared_interests": shared,
                    "evidence": proof[:4], "score": round(score, 3)})
    out.sort(key=lambda x: (-x["score"], -int(x.get("updated") or 0)))
    audit["kept"] = min(len(out), limit)
    audit["excluded"] = dict(sorted(ex.items(), key=lambda kv: -kv[1]))
    return out[:limit], audit, needs


def match_mentors(profiles: list[dict[str, Any]], needs: list[str], limit: int = MAX_MENTORS) -> list[dict[str, Any]]:
    out = []
    for p in profiles:
        if p.get("kind") != "mentor":
            continue
        skills = set(p.get("skills") or [])
        covered = [n for n in needs if covers(skills, n)]
        if needs and not covered:
            continue
        now = "now" in (p.get("availability") or "").lower()
        out.append({**{k: v for k, v in p.items() if k not in ("owner",)}, "source": "board", "covers": covered,
                    "evidence": [line for s in sorted(skills) if (line := evidence_line(s, p.get("verified")))][:3],
                    "score": round(len(covered) + (0.5 if now else 0.0), 3)})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


# ---------------------------------------------------------------------- public GitHub profiles
def location_in(text: str, default: str | None) -> str | None:
    """Where to look: a place the question names ("… in Orlando"), nowhere in particular ("remote", "anywhere"), or
    the event's city."""
    t = text or ""
    if _REMOTE.search(t):
        return None
    for m in _PLACE.finditer(t):
        place = m.group(1).strip(" ,.")
        first = place.split()[0].lower().strip(",")
        if first in _NOT_PLACES or norm(place) in _LANG or norm(first) in _LANG or roles_in(place) or skills_in(place):
            continue
        return place[:40]
    return (default or "").strip()[:40] or None


def languages_for(needs: list[str]) -> list[str]:
    """GitHub languages for what is asked (at most two searches): each need's own language first ("react or svelte"
    → TypeScript and Svelte, not TypeScript and JavaScript), then their second choices."""
    firsts = [_LANG[n][0] for n in needs if _LANG.get(n)]
    seconds = [lang for n in needs for lang in _LANG.get(n, [])[1:]]
    out: list[str] = []
    for lang in firsts + seconds:
        if lang not in out:
            out.append(lang)
    return out[:2]


def github_user_query(language: str, location: str | None) -> str:
    q = f'type:user language:"{language}" repos:>=3'
    return q + (f' location:"{location}"' if location else "")


def public_person(user: dict[str, Any] | None, repos: list[dict[str, Any]], needs: list[str],
                  today: dt.date) -> tuple[dict[str, Any] | None, str | None]:
    """A public GitHub profile as a teammate lead, or why it is left out."""
    if not user:
        return None, "the profile could not be read"
    if user.get("type") != "User":
        return None, "an organisation, not a person"
    login = str(user.get("login") or "")
    if login.lower().endswith("[bot]") or re.search(r"(?:^|[-_])bot$", login.lower()):
        return None, "a bot account"
    skills, own, last = repo_skills(repos)
    if not own:
        return None, "no public repositories of their own"
    if not last or (today - dt.date.fromisoformat(last)).days > ACTIVE_DAYS:
        return None, "no public activity for a year"
    seen = set(skills)
    covered = [n for n in needs if covers(seen, n)]
    if needs and not covered:
        return None, "none of the skills asked for in their public repos"
    bio = str(user.get("bio") or "")
    signals = [name for name, rx in _BIO_SIGNALS if rx.search(bio)]  # the words only; the bio is not kept
    days = (today - dt.date.fromisoformat(last)).days
    score = (len(covered) + 0.5 * ("hackathons" in signals) + 0.3 * ("a student" in signals)
             + 0.2 * ("a university" in signals) + 0.2 * ("open to collaborating" in signals)
             + 0.2 * bool(user.get("hireable")) + (0.3 if days <= 30 else 0.15 if days <= 90 else 0.0))
    shown = [s for s in needs if s in skills] + [s for s in skills if s not in needs]
    return {
        "source": "github", "login": login, "name": _clip(user.get("name") or login, 40),
        "location": _clip(user.get("location"), 40) or None,
        "profile_url": user.get("html_url") or f"https://github.com/{login}",
        "covers": covered, "skills": [s for s in shown][:8],
        "evidence": [line for s in shown[:4] if (line := evidence_line(s, {"skills": skills}))],
        "last_push": last, "public_repos": user.get("public_repos"), "own_repos": own,
        "followers": user.get("followers"), "since": str(user.get("created_at") or "")[:4] or None,
        "signals": signals, "hireable": bool(user.get("hireable")), "score": round(score, 3),
    }, None


# ---------------------------------------------------------------------- Stack Overflow's top answerers
def so_tags_for(needs: list[str], text: str) -> list[str]:
    """Stack Overflow tags for a mentor search: the stack the question names, else the roles' usual tags."""
    from .signature import _tags_of

    tags, _eco, _repos = _tags_of(" ".join([text or "", *needs]))
    for n in needs:
        t = _SKILL_TAGS.get(n) or (n if n in _LANG and n not in ROLES else None)
        if t and t not in tags:
            tags.append(t)
    for n in needs:
        for t in _ROLE_TAGS.get(n, []):
            if t not in tags:
                tags.append(t)
    generic = {"python", "javascript", "node.js", "typescript", "java", "cors", "git", "github", "docker", "npm"}
    specific = [t for t in tags if t not in generic]
    return (specific + [t for t in tags if t in generic])[:2]


def experts(found: dict[str, dict[str, list[dict[str, Any]]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Stack Overflow's top answerers per tag (``{tag: {"all_time": [...], "month": [...]}}``): registered accounts
    with at least ten answers on the tag, those who answered this month first."""
    audit = {"source": "stackoverflow_experts", "received": 0, "kept": 0, "excluded": {}, "error": None}
    ex: dict[str, int] = {}
    month: dict[int, int] = {}
    for tag, lists in found.items():
        for it in lists.get("month") or []:
            uid = (it.get("user") or {}).get("user_id")
            if uid is not None:
                month[uid] = month.get(uid, 0) + int(it.get("post_count") or 0)
    best: dict[int, dict[str, Any]] = {}
    for tag, lists in found.items():
        for it in lists.get("all_time") or []:
            audit["received"] += 1
            u = it.get("user") or {}
            uid = u.get("user_id")
            if u.get("user_type") != "registered" or uid is None:
                ex["not a registered account"] = ex.get("not a registered account", 0) + 1
                continue
            answers = int(it.get("post_count") or 0)
            if answers < MIN_EXPERT_ANSWERS:
                ex[f"fewer than {MIN_EXPERT_ANSWERS} answers on the tag"] = ex.get(f"fewer than {MIN_EXPERT_ANSWERS} answers on the tag", 0) + 1
                continue
            e = {"source": "stackoverflow", "user_id": uid, "name": _clip(html.unescape(u.get("display_name") or ""), 40),
                 "profile_url": u.get("link"), "tag": tag, "answers": answers, "score": int(it.get("score") or 0),
                 "reputation": int(u.get("reputation") or 0), "month_answers": month.get(uid, 0),
                 "active_this_month": uid in month}
            if uid not in best or e["score"] > best[uid]["score"]:
                best[uid] = e
    out = sorted(best.values(), key=lambda e: (not e["active_this_month"], -e["score"]))
    audit["kept"] = min(len(out), MAX_EXPERTS)
    if len(out) > MAX_EXPERTS:
        ex["more than the four shown"] = len(out) - MAX_EXPERTS
    audit["excluded"] = dict(sorted(ex.items(), key=lambda kv: -kv[1]))
    return out[:MAX_EXPERTS], audit
