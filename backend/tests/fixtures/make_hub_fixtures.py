"""Writes the hackathon hub's synthetic TEST fixtures (tests and the offline e2e never go online).

Everything here is invented and labelled: titles start with "TEST —", every link points to example.org, and no
real person's name or account appears. Each item also includes some that the hub must leave out (off-topic,
unanswered, archived, stale), so the audits are exercised.

    uv run python tests/fixtures/make_hub_fixtures.py
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

OUT = Path(__file__).parent / "hub"
AS_OF = "2026-09-20"
X = "https://example.org/test-fixture"


def ts(day: str) -> int:
    return int(dt.datetime.fromisoformat(day + "T12:00:00+00:00").timestamp())


def owner(n: int) -> dict:
    return {"display_name": f"Test Answerer {n}", "link": f"{X}/users/{n}", "user_type": "registered", "reputation": 1000 * n}


QUESTIONS = [
    {"_keys": ["access-control-allow-origin", "cors"], "question_id": 900001,
     "title": "TEST — FastAPI: No &#39;Access-Control-Allow-Origin&#39; header from the Svelte dev server",
     "link": f"{X}/so/900001", "score": 41, "answer_count": 3, "is_answered": True, "accepted_answer_id": 910001,
     "tags": ["python", "fastapi", "cors"], "creation_date": ts("2023-03-02"), "owner": owner(9),
     "body": "<p>My Svelte app on the Vite dev server calls my FastAPI backend and the browser says: blocked by CORS "
             "policy: No 'Access-Control-Allow-Origin' header is present on the requested resource.</p>"},
    {"_keys": ["access-control-allow-origin", "cors"], "question_id": 900002,
     "title": "TEST — CORS policy error when the request sends credentials to a wildcard origin",
     "link": f"{X}/so/900002", "score": 12, "answer_count": 1, "is_answered": True, "accepted_answer_id": None,
     "tags": ["javascript", "cors"], "creation_date": ts("2018-06-10"), "owner": owner(8),
     "body": "<p>Blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present on the requested "
             "resource, but only when I use credentials: 'include'.</p>"},
    {"_keys": ["access-control-allow-origin", "cors"], "question_id": 900003, "title": "TEST — How do I center a div?",
     "link": f"{X}/so/900003", "score": 3, "answer_count": 2, "is_answered": True, "accepted_answer_id": 910003,
     "tags": ["css"], "creation_date": ts("2020-01-01"), "owner": owner(7), "body": "<p>Flexbox or grid?</p>"},
    {"_keys": ["access-control-allow-origin"], "question_id": 900004,
     "title": "TEST — CORS header missing on requested resource when FastAPI returns 500",
     "link": f"{X}/so/900004", "score": 2, "answer_count": 1, "is_answered": False, "accepted_answer_id": None,
     "tags": ["fastapi", "cors"], "creation_date": ts("2024-05-05"), "owner": owner(6),
     "body": "<p>No 'Access-Control-Allow-Origin' header is present on the requested resource, only on errors. "
             "The CORS policy blocked it.</p>"},
    {"_keys": ["cv2", "modulenotfounderror"], "question_id": 900011,
     "title": "TEST — ModuleNotFoundError: No module named &#39;cv2&#39; after pip install",
     "link": f"{X}/so/900011", "score": 120, "answer_count": 6, "is_answered": True, "accepted_answer_id": 910011,
     "tags": ["python", "opencv"], "creation_date": ts("2021-04-01"), "owner": owner(5),
     "body": "<p>I ran pip install cv2 and import cv2 still fails: ModuleNotFoundError: No module named 'cv2'.</p>"},
    {"_keys": ["cv2"], "question_id": 900012, "title": "TEST — No module named cv2 in Jupyter, but it works in the terminal",
     "link": f"{X}/so/900012", "score": 35, "answer_count": 2, "is_answered": True, "accepted_answer_id": 910012,
     "tags": ["python", "opencv", "jupyter-notebook"], "creation_date": ts("2022-09-10"), "owner": owner(4),
     "body": "<p>ModuleNotFoundError: No module named 'cv2' only inside the notebook.</p>"},
    {"_keys": ["eresolve"], "question_id": 900021,
     "title": "TEST — npm ERESOLVE unable to resolve dependency tree after upgrading React",
     "link": f"{X}/so/900021", "score": 88, "answer_count": 4, "is_answered": True, "accepted_answer_id": 910021,
     "tags": ["npm", "reactjs"], "creation_date": ts("2025-02-02"), "owner": owner(3),
     "body": "<p>npm ERR! code ERESOLVE, unable to resolve dependency tree: a package wants the old React as a peer "
             "dependency.</p>"},
]
ANSWERS = [
    {"answer_id": 910001, "question_id": 900001, "score": 57, "is_accepted": True, "creation_date": ts("2023-03-02"),
     "content_license": "CC BY-SA 4.0", "owner": owner(1),
     "body": "<p>Add FastAPI&#39;s CORSMiddleware and list the dev server&#39;s exact origin. A wildcard origin cannot "
             "be combined with credentials.</p><pre><code>from fastapi.middleware.cors import CORSMiddleware\n\n"
             "app.add_middleware(\n    CORSMiddleware,\n    allow_origins=[\"http://localhost:5173\"],\n"
             "    allow_methods=[\"*\"],\n    allow_headers=[\"*\"],\n)\n</code></pre>"},
    {"answer_id": 910002, "question_id": 900002, "score": 9, "is_accepted": False, "creation_date": ts("2018-06-11"),
     "content_license": "CC BY-SA 4.0", "owner": owner(2),
     "body": "<p>With credentials the server must answer with the exact origin, never *, and also send "
             "Access-Control-Allow-Credentials: true.</p>"},
    {"answer_id": 910003, "question_id": 900003, "score": 30, "is_accepted": True, "creation_date": ts("2020-01-02"),
     "content_license": "CC BY-SA 4.0", "owner": owner(3), "body": "<p>Use display: grid; place-items: center.</p>"},
    {"answer_id": 910004, "question_id": 900004, "score": 1, "is_accepted": False, "creation_date": ts("2024-05-06"),
     "content_license": "CC BY-SA 4.0", "owner": owner(4), "body": "<p>Maybe restart the server?</p>"},
    {"answer_id": 910011, "question_id": 900011, "score": 150, "is_accepted": True, "creation_date": ts("2021-04-02"),
     "content_license": "CC BY-SA 4.0", "owner": owner(5),
     "body": "<p>There is no package called cv2 — the import name cv2 comes from the opencv-python package. Install "
             "it into the interpreter you run:</p><pre><code>python -m pip install opencv-python</code></pre>"},
    {"answer_id": 910012, "question_id": 900012, "score": 40, "is_accepted": True, "creation_date": ts("2022-09-11"),
     "content_license": "CC BY-SA 4.0", "owner": owner(6),
     "body": "<p>The notebook runs another interpreter. Install it into that kernel from a cell:</p>"
             "<pre><code>%pip install opencv-python</code></pre>"},
    {"answer_id": 910021, "question_id": 900021, "score": 95, "is_accepted": True, "creation_date": ts("2025-02-03"),
     "content_license": "CC BY-SA 4.0", "owner": owner(7),
     "body": "<p>Upgrade the package that pins the old peer dependency; only as a last resort install with "
             "--legacy-peer-deps.</p><pre><code>npm install --legacy-peer-deps</code></pre>"},
]
TOP = {
    "fastapi": [
        {"question_id": 900101, "title": "TEST — How do I use WebSockets in FastAPI?", "link": f"{X}/so/900101",
         "score": 310, "answer_count": 5, "accepted_answer_id": 910101, "tags": ["fastapi", "websocket"],
         "creation_date": ts("2021-08-10")},
        {"question_id": 900102, "title": "TEST — FastAPI vs Flask", "link": f"{X}/so/900102", "score": 12,
         "answer_count": 3, "accepted_answer_id": None, "tags": ["fastapi", "flask"], "creation_date": ts("2020-03-01")},
    ],
}
ISSUES = [
    {"_keys": ["cors", "access-control-allow-origin"], "id": 7001, "number": 101,
     "title": "TEST — CORS headers are missing when the app raises an exception",
     "state": "closed", "state_reason": "completed", "comments": 14, "reactions": {"total_count": 23},
     "repository_url": "https://api.github.com/repos/fastapi/fastapi", "html_url": f"{X}/gh/101",
     "created_at": "2024-02-01T10:00:00Z", "closed_at": "2024-03-15T10:00:00Z", "user": {"login": "test-user-1", "html_url": f"{X}/u/1"},
     "body": "The CORS middleware headers are missing (No 'Access-Control-Allow-Origin' header is present on the "
             "requested resource) when an unhandled exception returns a 500. Blocked by CORS policy."},
    {"_keys": ["cors"], "id": 7002, "number": 5, "title": "TEST — cors not working", "state": "open",
     "state_reason": None, "comments": 0, "reactions": {"total_count": 0},
     "repository_url": "https://api.github.com/repos/test-org/some-app", "html_url": f"{X}/gh/5",
     "created_at": "2026-01-01T10:00:00Z", "closed_at": None, "user": {"login": "test-user-2", "html_url": f"{X}/u/2"},
     "body": "Access-Control-Allow-Origin header is present on the requested resource? blocked by CORS policy"},
    {"_keys": ["cv2", "modulenotfounderror"], "id": 7011, "number": 55,
     "title": "TEST — ModuleNotFoundError: No module named 'cv2' in a fresh virtual environment",
     "state": "closed", "state_reason": "completed", "comments": 9, "reactions": {"total_count": 12},
     "repository_url": "https://api.github.com/repos/opencv/opencv-python", "html_url": f"{X}/gh/55",
     "created_at": "2025-03-01T10:00:00Z", "closed_at": "2025-03-04T10:00:00Z", "user": {"login": "test-user-3", "html_url": f"{X}/u/3"},
     "body": "import cv2 → ModuleNotFoundError: No module named 'cv2'. Installing opencv-python into the venv fixed it."},
]
REPOS = [
    {"_keys": ["websockets", "websocket"], "id": 8001, "full_name": "test-org/fastapi-websocket-chat-starter",
     "html_url": f"{X}/repo/8001", "description": "TEST — Starter: real-time chat with FastAPI WebSockets and a Svelte client",
     "stargazers_count": 640, "pushed_at": "2026-07-01T00:00:00Z", "archived": False, "is_template": True,
     "license": {"spdx_id": "MIT"}, "language": "Python", "topics": ["fastapi", "websockets", "svelte"]},
    {"_keys": ["websockets"], "id": 8002, "full_name": "test-org/old-socket-demo", "html_url": f"{X}/repo/8002",
     "description": "TEST — WebSockets with FastAPI demo", "stargazers_count": 90, "pushed_at": "2021-01-01T00:00:00Z",
     "archived": False, "is_template": False, "license": {"spdx_id": "MIT"}, "language": "Python", "topics": []},
    {"_keys": ["websockets"], "id": 8003, "full_name": "test-org/websocket-archive", "html_url": f"{X}/repo/8003",
     "description": "TEST — archived FastAPI websockets sample", "stargazers_count": 400, "pushed_at": "2026-01-01T00:00:00Z",
     "archived": True, "is_template": False, "license": None, "language": "Python", "topics": []},
    {"_keys": ["websockets", "fastapi"], "id": 8004, "full_name": "test-org/realtime-dashboard-fastapi",
     "html_url": f"{X}/repo/8004", "description": "TEST — Live dashboard over WebSockets with FastAPI",
     "stargazers_count": 210, "pushed_at": "2026-05-10T00:00:00Z", "archived": False, "is_template": False,
     "license": {"spdx_id": "Apache-2.0"}, "language": "Python", "topics": ["fastapi", "websockets", "dashboard"]},
]
USERS = {
    "octo-test": {
        "user": {"login": "octo-test", "type": "User", "public_repos": 4, "html_url": f"{X}/octo-test"},
        "repos": [
            {"name": "svelte-habit-tracker", "language": "Svelte", "fork": False, "topics": ["svelte"],
             "pushed_at": "2026-08-30T00:00:00Z", "description": "TEST"},
            {"name": "fastapi-notes", "language": "Python", "fork": False, "topics": ["fastapi"],
             "pushed_at": "2026-06-01T00:00:00Z", "description": "TEST"},
            {"name": "ml-playground", "language": "Jupyter Notebook", "fork": False,
             "topics": ["machine-learning", "pytorch"], "pushed_at": "2025-12-01T00:00:00Z", "description": "TEST"},
            {"name": "forked-react-lib", "language": "TypeScript", "fork": True, "topics": ["react"],
             "pushed_at": "2026-09-01T00:00:00Z", "description": "TEST"},
        ],
    },
}


def person(login: str, name: str, location: str, bio: str, repos: list[tuple[str, str, list[str], str, bool]],
           kind: str = "User", hireable: bool | None = None, followers: int = 10, since: str = "2021") -> dict:
    """A synthetic public GitHub profile (TEST). The e-mail, blog, company and social fields are filled on purpose:
    the hub must never read, keep or show them."""
    return {
        "user": {"login": login, "type": kind, "name": name, "location": location, "bio": bio, "hireable": hireable,
                 "public_repos": len(repos) + 3, "followers": followers, "created_at": f"{since}-03-01T00:00:00Z",
                 "html_url": f"{X}/gh/{login}", "email": f"{login}-never-shown@example.org",
                 "blog": f"{X}/blog/{login}-never-shown", "twitter_username": f"{login}_never_shown",
                 "company": "@never-shown-company"},
        "repos": [{"name": n, "language": lang, "fork": fork, "topics": topics, "pushed_at": f"{pushed}T00:00:00Z",
                   "description": "TEST"} for n, lang, topics, pushed, fork in repos],
    }


PEOPLE = {
    "test-ana-svelte": person("test-ana-svelte", "TEST Ana Fixture", "Miami, FL (TEST)",
                              "TEST — CS student at a university who loves hackathons; open to collaborate",
                              [("svelte-kanban", "Svelte", ["svelte"], "2026-09-12", False),
                               ("svelte-weather", "Svelte", [], "2026-07-01", False),
                               ("ts-utils", "TypeScript", [], "2026-05-20", False),
                               ("forked-thing", "Rust", [], "2026-09-15", True)], since="2022"),
    "test-ben-react": person("test-ben-react", "TEST Ben Fixture", "Miami Beach (TEST)", "TEST — frontend developer",
                             [("react-dashboard", "TypeScript", ["react"], "2026-08-30", False),
                              ("next-blog", "TypeScript", ["nextjs"], "2026-06-10", False)],
                             hireable=True, followers=40, since="2019"),
    "test-dan-python": person("test-dan-python", "TEST Dan Fixture", "Miami (TEST)", "TEST — data engineer",
                              [("fastapi-orders", "Python", ["fastapi"], "2026-09-01", False),
                               ("pandas-notes", "Jupyter Notebook", ["pandas"], "2026-04-01", False)], since="2020"),
    "test-cleo-stale": person("test-cleo-stale", "TEST Cleo Fixture", "Miami (TEST)", "TEST",
                              [("old-svelte-app", "Svelte", ["svelte"], "2024-03-01", False)]),
    "test-deploy-bot": person("test-deploy-bot", "TEST deploy bot", "", "TEST",
                              [("bot-config", "TypeScript", [], "2026-09-10", False)]),
    "test-lab-org": person("test-lab-org", "TEST Lab (an organisation)", "Miami (TEST)", "TEST",
                           [("lab-site", "TypeScript", [], "2026-09-10", False)], kind="Organization"),
}
# GitHub's user search: which logins a query returns, in its order (matched by the query's language)
USER_SEARCH = [
    {"_keys": ["typescript", "javascript"], "login": "test-ben-react", "type": "User", "html_url": f"{X}/gh/test-ben-react"},
    {"_keys": ["svelte", "typescript"], "login": "test-ana-svelte", "type": "User", "html_url": f"{X}/gh/test-ana-svelte"},
    {"_keys": ["typescript", "svelte", "python"], "login": "test-lab-org", "type": "Organization", "html_url": f"{X}/gh/test-lab-org"},
    {"_keys": ["typescript"], "login": "test-deploy-bot", "type": "User", "html_url": f"{X}/gh/test-deploy-bot"},
    {"_keys": ["svelte"], "login": "test-cleo-stale", "type": "User", "html_url": f"{X}/gh/test-cleo-stale"},
    {"_keys": ["python"], "login": "test-dan-python", "type": "User", "html_url": f"{X}/gh/test-dan-python"},
]


def expert(n: int, name: str, answers: int, score: int, kind: str = "registered") -> dict:
    return {"user": {"user_id": 7000 + n, "display_name": name, "link": f"{X}/so-users/{7000 + n}",
                     "user_type": kind, "reputation": 1000 * n + 7},
            "post_count": answers, "score": score}


TOP_ANSWERERS = {
    "pytorch": {"all_time": [expert(1, "TEST Expert Uma", 120, 900), expert(2, "TEST Expert Vik", 45, 300),
                             expert(3, "TEST Newcomer", 4, 20), expert(4, "TEST Gone", 60, 400, "does_not_exist")],
                "month": [expert(2, "TEST Expert Vik", 2, 3)]},
    "fastapi": {"all_time": [expert(5, "TEST Expert Wen", 210, 1500), expert(6, "TEST Expert Xan", 30, 150)],
                "month": [expert(6, "TEST Expert Xan", 1, 1)]},
}


def open_q(qid: int, title: str, tags: list[str], day: str, score: int = 0, answers: int = 0, closed: bool = False,
           solved: bool = False) -> dict:
    q = {"question_id": qid, "title": title, "link": f"{X}/so/{qid}", "tags": tags, "creation_date": ts(day),
         "score": score, "answer_count": answers, "view_count": 30 + qid % 50, "is_answered": solved,
         "owner": {"display_name": f"Test Asker {qid % 7}"}}
    if closed:
        q["closed_date"] = ts(day)
        q["closed_reason"] = "duplicate"
    return q


OPEN_QUESTIONS = {
    "fastapi": [open_q(950001, "TEST — FastAPI background task never runs after the response", ["python", "fastapi"], "2026-09-18"),
                open_q(950002, "TEST — FastAPI &quot;Depends&quot; with a class and a default", ["fastapi"], "2026-09-12"),
                open_q(950003, "TEST — an old FastAPI question", ["fastapi"], "2026-01-15"),
                open_q(950006, "TEST — solved meanwhile (an upvoted answer)", ["fastapi"], "2026-09-14", answers=1, solved=True),
                open_q(950004, "TEST — a closed duplicate", ["fastapi"], "2026-09-15", closed=True),
                open_q(950005, "TEST — a voted-down question", ["fastapi"], "2026-09-16", score=-2)],
    "python": [open_q(950011, "TEST — Python dataclass default list shared between instances", ["python"], "2026-09-19"),
               open_q(950001, "TEST — FastAPI background task never runs after the response", ["python", "fastapi"], "2026-09-18")],
    "svelte": [open_q(950021, "TEST — Svelte 5 $derived does not update inside an each block", ["svelte"], "2026-09-17")],
}

REGISTRIES = {
    "pypi": {
        "opencv-python": {"info": {"name": "opencv-python", "version": "4.12.0.88", "requires_python": ">=3.7",
                                   "summary": "TEST — Wrapper package for OpenCV python bindings.",
                                   "package_url": f"{X}/pypi/opencv-python",
                                   "project_urls": {"Documentation": f"{X}/docs/opencv"}, "yanked": False},
                          "latest_upload": "2025-07-07"},
        "markupsafe": {"info": {"name": "MarkupSafe", "version": "3.0.2", "requires_python": ">=3.9",
                                "summary": "TEST — Safely add untrusted strings to HTML/XML markup.",
                                "package_url": f"{X}/pypi/markupsafe", "project_urls": {}, "yanked": False},
                       "latest_upload": "2024-10-18"},
    },
    "npm": {
        "vite": {"name": "vite", "version": "8.3.1", "engines": {"node": "^20.19.0 || >=22.12.0"},
                 "description": "TEST — Native-ESM powered web dev build tool", "homepage": f"{X}/vite"},
        "request": {"name": "request", "version": "2.88.2", "deprecated": "TEST — request has been deprecated",
                    "description": "TEST — Simplified HTTP request client.", "homepage": f"{X}/request"},
        "react-leaflet": {"name": "react-leaflet", "version": "5.0.0", "description": "TEST — React components for Leaflet maps",
                          "peerDependencies": {"leaflet": "^1.9.0", "react": "^19.0.0", "react-dom": "^19.0.0"},
                          "homepage": f"{X}/react-leaflet"},
    },
}
DEVTO = {
    "fastapi": [
        {"title": "TEST — WebSockets in FastAPI, step by step", "url": f"{X}/devto/1",
         "description": "TEST — A chat room in 40 lines.", "public_reactions_count": 57, "reading_time_minutes": 6,
         "published_at": "2026-04-22T00:00:00Z", "tag_list": ["fastapi", "websockets", "python"],
         "user": {"name": "Test Writer"}},
        {"title": "TEST — FastAPI websockets in 2019", "url": f"{X}/devto/2", "description": "TEST",
         "public_reactions_count": 80, "reading_time_minutes": 4, "published_at": "2019-01-01T00:00:00Z",
         "tag_list": ["fastapi", "websockets"], "user": {"name": "Test Writer"}},
        {"title": "TEST — Hello FastAPI websockets", "url": f"{X}/devto/3", "description": "TEST",
         "public_reactions_count": 1, "reading_time_minutes": 2, "published_at": "2026-05-01T00:00:00Z",
         "tag_list": ["fastapi"], "user": {"name": "Test Writer"}},
    ],
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    note = "Synthetic TEST data for the hackathon hub — invented; links point to example.org."
    files = {
        "stackoverflow.json": {"_note": note, "_as_of": AS_OF, "questions": QUESTIONS, "answers": ANSWERS, "top": TOP,
                               "top_answerers": TOP_ANSWERERS, "open_questions": OPEN_QUESTIONS},
        "github.json": {"_note": note, "issues": ISSUES, "repos": REPOS, "users": {**USERS, **PEOPLE},
                        "user_search": USER_SEARCH},
        "registries.json": {"_note": note, **REGISTRIES},
        "devto.json": {"_note": note, **DEVTO},
    }
    for name, data in files.items():
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", ", ".join(files))


if __name__ == "__main__":
    main()
