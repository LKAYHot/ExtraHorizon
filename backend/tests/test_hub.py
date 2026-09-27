"""Hackathon hub: help from public sources, teammates and mentors, shared knowledge, the road to shipping.

Everything runs on the synthetic TEST fixtures (tests/fixtures/hub) — tests never contact Stack Overflow, GitHub,
npm, PyPI or DEV Community.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from extrahorizon.app import create_app
from extrahorizon.hub.board import Board, BoardError
from extrahorizon.hub.intent import about_hub, hub_intent
from extrahorizon.hub.people import github_evidence, match_people
from extrahorizon.hub.report import HUB_IDS, hub_grounding, hub_sheet
from extrahorizon.hub.service import HubService, item_by_ref, refs_of
from extrahorizon.hub.ship import STUCK_ASK_MIN, ShipPlan
from extrahorizon.hub.signature import extract, scrub
from extrahorizon.hub.sources import FixtureSources

from .conftest import FakeLLM, FakeVision, make_settings, new_sid, parse_sse

FIXTURES = Path(__file__).parent / "fixtures" / "hub"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def service(**kw) -> HubService:
    return HubService(make_settings(**kw))


def seeded(**kw) -> HubService:
    """A service whose board holds what teams here wrote — through the board's own API, in the test (the hub has no
    sample entries): three fixes teams shared, two hackers, and a mentor."""
    svc = service(**kw)
    b = svc.board
    chen, nova, ava, gus, kai = (b.new_token() for _ in range(5))
    run(b.save_profile(chen, {"name": "Test Chen", "skills": "python, pytorch, opencv", "looking_for": "frontend"}))
    run(b.save_profile(nova, {"name": "Test Nova", "skills": "svelte, typescript, figma", "team": {"name": "Nova", "size": 2}}))
    run(b.save_profile(ava, {"name": "Test Ava", "skills": "design, figma, pitch", "availability": "all night"}))
    run(b.save_profile(gus, {"name": "Test Gus", "skills": "react, node.js, express", "availability": "all night"}))
    run(b.save_profile(kai, {"kind": "mentor", "name": "Test Mentor Kai", "availability": "available now",
                             "skills": "machine learning, pytorch, opencv, mediapipe, python"}))
    run(b.add_card(chen, {"title": "import cv2 fails inside a virtual environment",
                          "problem": "ModuleNotFoundError: No module named 'cv2'", "tags": ["python", "opencv"],
                          "fix": "The import name cv2 belongs to the opencv-python package: install it into the same "
                                 "environment that runs the script (python -m pip install opencv-python).",
                          "links": ["https://example.org/test-fixture/pypi/opencv-python"]}))
    run(b.add_card(nova, {"title": "CORS between the Vite dev server and FastAPI", "tags": ["cors", "fastapi", "vite"],
                          "problem": "No 'Access-Control-Allow-Origin' header on requests from localhost:5173",
                          "fix": "Add FastAPI's CORSMiddleware with the dev server's exact origin."}))
    run(b.post_request(nova, {"title": "CORS error between our Svelte app and FastAPI", "tags": ["cors", "fastapi", "svelte"],
                              "problem": "Fetching from the Vite dev server fails: No 'Access-Control-Allow-Origin' header.",
                              "signature": {"kind": "CORS", "message": "No 'Access-Control-Allow-Origin' header"}}))
    return svc


# ---------------------------------------------------------------------- the signature of a roadblock
@pytest.mark.parametrize("text, kind, words_in, tags_in", [
    ('Traceback (most recent call last):\n  File "C:\\Users\\dmitr\\proj\\main.py", line 3, in <module>\n    import cv2\n'
     "ModuleNotFoundError: No module named 'cv2'", "ModuleNotFoundError", ["cv2"], ["opencv", "python"]),
    ("Access to fetch at 'http://localhost:8000/api' from origin 'http://localhost:5173' has been blocked by CORS policy: "
     "No 'Access-Control-Allow-Origin' header is present on the requested resource. svelte + fastapi", "CORS",
     ["access-control-allow-origin"], ["fastapi", "svelte", "cors"]),
    ("Uncaught TypeError: Cannot read properties of undefined (reading 'map') at App (App.jsx:12:15)", "TypeError",
     ["undefined", "map"], ["reactjs"]),
    ("npm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve dependency tree", "ERESOLVE", ["dependency"], ["npm"]),
    ("fatal: refusing to merge unrelated histories", "git", ["unrelated", "histories"], ["git"]),
    ("FastAPI returns 422 Unprocessable Entity when I post JSON", "HTTP 422", ["unprocessable"], ["fastapi"]),
    ("pydantic_core._pydantic_core.ValidationError: 1 validation error for Item\nprice\n  Field required "
     "[type=missing, input_value={'name': 'x'}, input_type=dict]", "ValidationError", ["field", "required"], ["pydantic"]),
    ("openai.RateLimitError: Error code: 429 - {'error': {'message': 'You exceeded your current quota'}}",
     "RateLimitError", ["quota"], ["openai-api"]),
])
def test_the_signature_is_the_error_not_the_learners_setup(text, kind, words_in, tags_in):
    sig = extract(text)
    assert sig.kind == kind
    assert all(w in sig.words for w in words_in), sig.words
    assert all(t in sig.tags for t in tags_in), sig.tags


def test_their_paths_hosts_ports_emails_and_keys_never_leave():
    text = ("Error at C:\\Users\\dmitr\\secret-project\\app.py and /home/dan/work/app/main.py calling "
            "http://192.168.1.20:8000/api?token=abc from http://localhost:5173 — mail me at dan@example.com, key "
            "sk-notarealkey12, uuid 123e4567-e89b-12d3-a456-426614174000, id 88442211\n"
            "ModuleNotFoundError: No module named 'cv2'")
    q = extract(text).query
    for secret in ("dmitr", "secret-project", "/home/dan", "192.168", "5173", "8000", "dan@example.com",
                   "sk-notarealkey12", "123e4567", "88442211", "token=abc"):
        assert secret not in q, secret
    clean = scrub(text)
    assert "sk-notarealkey12" not in clean and "dan@example.com" not in clean and "C:\\Users" not in clean


# found in review: what still reached a search (IP, host names, host:port, key=value, JWT, AWS, hf_, spaces in paths)
@pytest.mark.parametrize("text, private", [
    ("requests.exceptions.ConnectionError: HTTPConnectionPool(host='192.168.1.50', port=8000): Max retries exceeded",
     ["192.168", "8000"]),
    ("psycopg2.OperationalError: connection to server at 'db.qwertyuiop.supabase.co' (34.120.5.77), port 5432 failed",
     ["qwertyuiop", "supabase.co", "34.120", "5432"]),
    ("pymongo.errors.ServerSelectionTimeoutError: dmitr-cluster.ab1cd.mongodb.net:27017: timed out",
     ["dmitr", "ab1cd", "mongodb.net", "27017"]),
    ("Error: connect ECONNREFUSED 10.0.0.12:3000", ["10.0.0", "3000"]),
    ("Error: getaddrinfo ENOTFOUND my-secret-startup-api.internal", ["my-secret", "internal"]),
    ("401 invalid token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiJ9.abcdefghijklmnop", ["eyJ"]),
    ("botocore ClientError AKIAIOSFODNN7EXAMPLE secret wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY", ["AKIA", "wJalr"]),
    ("HfHubHTTPError 401 hf_abcdefghijklmnopqrstuvwxyz123456", ["hf_"]),
    ("FileNotFoundError: No such file: C:\\Users\\John Smith\\Desktop\\hack\\data.csv", ["John", "Smith", "Desktop", "data.csv"]),
    ("FileNotFoundError: No such file: /home/John Smith/Desktop/hack/data.csv", ["John", "Smith", "Desktop"]),
    ("fetch failed from my-api:8000 in docker compose", ["my-api", "8000"]),
    ("IPv6 connect fe80::1ff:fe23:4567:890a failed", ["fe80", "890a"]),
])
def test_what_is_theirs_never_reaches_a_search(text, private):
    sig = extract(text)
    sent = f"{sig.query} {' '.join(sig.words)} {' '.join(sig.packages + sig.mentioned)}"
    for p in private:
        assert p not in sent, (p, sent)


def test_a_learning_topic_is_scrubbed_too():
    svc = service()
    run(svc.learn("Where can I learn Flask with WebSockets? mail me at dmitriy.dodo@gmail.com from 10.1.2.3"))
    asked = " ".join(q for _s, q in svc.sources.calls)
    assert "dmitriy" not in asked and "gmail" not in asked and "10.1.2.3" not in asked


def test_a_local_import_and_a_node_builtin_are_hints_not_packages():
    sig = extract('[vite] Internal server error: Failed to resolve import "./Foo.svelte" from "src/routes/+page.svelte".')
    assert sig.local_import == "Foo.svelte" and not sig.packages and "src/routes" not in sig.query
    sig = extract("Module not found: Can't resolve 'fs' in '/home/dan/proj/node_modules/pg/lib' next.js")
    assert sig.node_builtin == "fs" and not sig.packages


# ---------------------------------------------------------------------- which messages are for the hub
@pytest.mark.parametrize("text, want", [
    ("I get TypeError: Cannot read properties of undefined (reading 'map') in my React app", "unstuck"),
    ("My FastAPI app returns 422 when I post JSON", "unstuck"),
    ("у меня CORS ошибка между svelte и fastapi", "unstuck"),
    ("npm install keeps failing with ERESOLVE", "unstuck"),
    # found live: a pasted npm log, "fails with …" — roadblocks even without "I" or "my"
    ("npm install fails: npm ERR! code ERESOLVE npm ERR! ERESOLVE unable to resolve dependency tree", "unstuck"),
    ("the build fails with TypeError: x is not a function", "unstuck"),
    ("npm ERR! code ELIFECYCLE", "unstuck"),
    ("What does ERESOLVE mean?", None),
    # found in review: tutoring that went to the hub, roadblocks that did not
    ("ModuleNotFoundError: No module named 'cv2'", "unstuck"), ("504 Deadline Exceeded", "unstuck"),
    ("DEADLINE_EXCEEDED", "unstuck"), ("vite build fails: Could not resolve './teammates.js'", "unstuck"),
    ("I'm getting a CORS error from FastAPI", "unstuck"), ("my flask app returns 500", "unstuck"),
    ("у меня не работает fastapi, пишет ошибку CORS", "unstuck"),
    ("How does form submission work in React?", None), ("How much time does quicksort take on sorted input?", None),
    ("How do I submit the form with fetch?", None), ("Сколько времени занимает сортировка слиянием?", None),
    ("I have a question about Python decorators", None), ("I want to see how React hooks work", None),
    ("Can I get an example of a JavaScript closure?", None), ("How do I find the dev tools in Chrome?", None),
    ("How does the OS allocate resources for processes?", None), ("Что значит ошибка CORS?", None),
    ("Explain how an API_KEY is used in requests", None), ("Explain recursion", None),
    ("We're looking for a frontend developer", "team"), ("When is the Devpost deadline?", "ship"),
    ("Find me a teammate who knows React", "team"),
    ("ищу команду, я бэкендер на python", "team"),
    ("Is there a mentor who knows PyTorch?", "mentors"),
    ("Where can I learn WebSockets fast?", "learn"),
    ("где можно изучить fastapi за вечер", "learn"),
    ("How much time do we have left before the deadline?", "ship"),
    ("сколько у нас осталось времени до дедлайна?", "ship"),
    # tutoring stays tutoring
    ("What is a TypeError in Python?", None), ("Explain recursion to me please.", None), ("What does 404 mean?", None),
    ("I want to learn recursion", None), ("Compare the utilities' plans", None), ("hey", None),
    ("what is the difference between let and const in javascript", None), ("My code doesn't work", None),
])
def test_only_hackathon_needs_go_to_the_hub(text, want):
    assert hub_intent(text) == want


# ---------------------------------------------------------------------- searches on the fixtures
def test_get_unstuck_verifies_and_ranks_what_the_sources_say():
    svc = seeded()
    steps: list[dict] = []
    r = run(svc.unstuck("Traceback (most recent call last):\n  File \"app.py\", line 1\n"
                        "ModuleNotFoundError: No module named 'cv2'", progress=steps.append))
    assert svc.offline and r["offline"] is True
    assert [x["ref"] for x in r["items"]] == ["S1", "S2", "S3", "S4"]
    s1 = r["items"][0]  # the registry fact that settles it comes first
    assert s1["type"] == "package" and s1["name"] == "opencv-python" and "import name ≠ package name" in s1["flags"]
    so = [x for x in r["items"] if x["type"] == "stackoverflow"]
    assert all(x["accepted"] for x in so) and all(x["attribution"]["license"] == "CC BY-SA 4.0" for x in so)
    assert any("check it against today's versions" in f for x in so for f in x["flags"])  # the 2021 answer
    assert r["peers"][0]["ref"] == "K1" and r["peers"][0]["author"] == "Test Chen"  # what a team here shared
    assert r["mentors"][0]["name"] == "Test Mentor Kai" and r["mentors"][0]["source"] == "board"
    assert {s["step"] for s in steps} >= {"signature", "stackoverflow", "github", "registries", "board"}


def test_the_audit_says_what_was_left_out_and_why():
    r = run(seeded().unstuck("blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present on the "
                              "requested resource — svelte calls fastapi"))
    audits = {a["source"]: a for a in r["audit"]}
    assert audits["stackoverflow"]["received"] == 4 and audits["stackoverflow"]["kept"] == 2
    assert audits["stackoverflow"]["excluded"] == {"not about this error": 1, "no accepted or well-voted answer": 1}
    assert audits["github"]["excluded"] == {"open, and nobody has answered it yet": 1}
    assert r["items"][0]["type"] == "stackoverflow" and r["items"][0]["accepted"]  # the accepted answer with code
    assert "allow_origins" in r["items"][0]["excerpt"]["code"]
    assert [s["title"] for s in r["similar"]] == ["CORS error between our Svelte app and FastAPI"]


def test_the_code_shown_is_the_fix_not_their_setup():
    """Found live: an accepted CORS answer showed its first code block (database setup), not the middleware fix."""
    from extrahorizon.hub.verify import _best_code

    sig = extract("blocked by CORS policy: No 'Access-Control-Allow-Origin' header — svelte calls fastapi")
    setup = "SessionLocal = sessionmaker(autocommit=False, bind=engine)"
    fix = 'app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"])'
    assert _best_code(sig, [setup, fix]) == fix
    assert _best_code(sig, ["print(1)", "print(2)"]) == "print(1)"  # nothing about it: the first one


def test_learning_resources_are_current_and_popular():
    r = run(seeded().learn("Where can I learn WebSockets with FastAPI fast?"))
    kinds = [x["type"] for x in r["items"]]
    assert kinds == ["repo", "repo", "article", "so_question"]
    assert r["items"][0]["title"] == "test-org/fastapi-websocket-chat-starter" and "tutorial / example" in r["items"][0]["flags"]
    assert "a project to read, not a tutorial" in r["items"][1]["flags"]  # a popular project using the words
    audits = {a["source"]: a["excluded"] for a in r["audit"]}
    assert audits["github"] == {"no push in three years": 1, "archived": 1}
    assert audits["devto"] == {"older than three years": 1, "fewer than 3 reactions": 1}
    assert not r["peers"]  # a card that only shares the word "fastapi" is not about WebSockets


def test_their_story_is_not_the_error_and_a_moved_repository_is_not_a_failure():
    """Found live: "npm install fails: npm ERR! code ERESOLVE … after I added react-leaflet to my React 19 app" searched
    for "npm ERR! … after I added …" (nothing found), looked up a package called "fails", and GitHub answered 422
    for a project repository that had moved."""
    sig = extract("npm install fails: npm ERR! code ERESOLVE npm ERR! ERESOLVE unable to resolve dependency tree after "
                  "I added react-leaflet to my React 19 app")
    assert sig.query == "ERESOLVE unable to resolve dependency tree" and not sig.packages
    assert sig.mentioned == ["react-leaflet"] and sig.ecosystem == "npm"
    assert extract("I added a button and now TypeError: x is not a function").mentioned == []

    class Moved(FixtureSources):
        async def gh_issues(self, q):
            if "repo:" in q:
                from extrahorizon.hub.sources import SourceError
                raise SourceError("github_search", "returned HTTP 422: Validation Failed")
            return await super().gh_issues(q)

    svc = HubService(make_settings(), sources=Moved(FIXTURES))
    r = run(svc.unstuck("npm install fails: npm ERR! code ERESOLVE npm ERR! ERESOLVE unable to resolve dependency tree "
                        "after I added react-leaflet to my React 19 app"))
    assert not r["errors"]  # the scoped search failed, the search everywhere ran
    pkg = r["items"][0]  # what the package itself asks for settles a peer-dependency conflict
    assert pkg["name"] == "react-leaflet" and "peer dependencies: leaflet ^1.9.0, react ^19.0.0, react-dom ^19.0.0" in pkg["facts"]
    assert any(x["type"] == "stackoverflow" and "ERESOLVE" in x["title"] for x in r["items"])
    # a mentioned name the registry does not know is not reported as "no package named …"
    r = run(svc.unstuck("npm ERR! code ERESOLVE unable to resolve dependency tree after I upgraded my-own-thing"))
    assert not any(x["type"] == "package" for x in r["items"])


def test_nothing_to_search_is_said_plainly():
    assert "error" in run(service().unstuck("  "))
    assert "error" in run(service().learn("where can I learn"))


# ---------------------------------------------------------------------- people
def test_teammates_cover_what_is_asked_and_teams_stay_within_four():
    board = seeded().board
    people, audit, needs = match_people(list(board.profiles.values()), None, "Find me a teammate who knows React or a designer")
    assert needs == ["design", "react"]
    assert {p["name"] for p in people} == {"Test Gus", "Test Ava", "Test Nova"}  # react; design (figma counts)
    assert all(p["source"] == "board" for p in people)
    me = {"id": "me", "skills": ["python"], "looking_for": ["frontend"], "interests": ["health"], "team": {"size": 3}}
    people, audit, _ = match_people(list(board.profiles.values()), me, "")
    assert all(int((p.get("team") or {}).get("size") or 1) == 1 for p in people)  # 3 + 2 would be five
    assert audit["excluded"]["together the team would be larger than four"] == 1  # team Nova (2)


def test_a_skill_seen_on_github_counts_more_than_a_claim():
    svc = service()
    board = svc.board
    token_a, token_b = board.new_token(), board.new_token()
    a = run(board.save_profile(token_a, {"name": "Claims", "skills": "react", "github": "", "github_consent": False}))
    b = run(board.save_profile(token_b, {"name": "Shows", "skills": "svelte, react", "github": "octo-test",
                                          "github_consent": True}))
    ev = run(github_evidence(svc.sources, "octo-test", dt.date(2026, 9, 20)))
    assert ev["found"] and ev["own_repos"] == 3 and "svelte" in ev["skills"] and "typescript" not in ev["skills"]
    run(board.set_verified(b["id"], ev))
    people, _audit, _needs = match_people(list(board.profiles.values()), None, "someone who knows svelte")
    assert people[0]["name"] == "Shows" and people[0]["evidence"][0].startswith("svelte in 1 public GitHub repo")
    assert a["verified"] is None


def test_github_is_never_read_without_consent():
    svc = service()
    p = run(svc.board.save_profile(svc.board.new_token(), {"name": "No", "github": "octo-test", "github_consent": False}))
    svc.verify_later(p)
    assert ("github", "user octo-test") not in svc.sources.calls and p["github_consent"] is False


# ---------------------------------------------------------------------- the board
def test_the_board_belongs_to_whoever_wrote_it(tmp_path):
    board = Board(tmp_path / "board.json")
    assert not board.profiles and not board.requests and not board.cards  # only what real people write
    alice, bob = board.new_token(), board.new_token()
    with pytest.raises(BoardError):
        run(board.post_request("", {"title": "x"}))  # no token, no writes
    req = run(board.post_request(alice, {"title": "Vite build fails", "problem": "ERESOLVE", "tags": ["npm"]}))
    with pytest.raises(BoardError) as e:
        run(board.claim(bob, req["id"]))
    assert e.value.code == "no_profile"  # who is coming?
    run(board.save_profile(bob, {"name": "Bob", "skills": "npm"}))
    run(board.claim(bob, req["id"]))
    with pytest.raises(BoardError) as e:
        run(board.resolve(bob, req["id"]))
    assert e.value.code == "not_yours"
    run(board.resolve(alice, req["id"], "pinned the peer dependency"))
    card = run(board.add_card(alice, {"title": "ERESOLVE after a React upgrade", "fix": "Upgrade the plugin first.",
                                     "links": ["https://example.org/x", "javascript:alert(1)"]}))
    assert card["links"] == ["https://example.org/x"]
    run(board.helpful(bob, card["id"]))
    run(board.helpful(bob, card["id"]))
    assert board.cards[card["id"]]["helpful"] == 1  # once per browser
    # saved — without the tokens themselves
    board.flush()
    assert alice not in (tmp_path / "board.json").read_text(encoding="utf-8")
    again = Board(tmp_path / "board.json")
    assert again.requests[req["id"]]["status"] == "solved" and again.mine(bob)["name"] == "Bob"
    pub = board.public(alice)
    assert all("owner" not in x for x in pub["profiles"] + pub["requests"] + pub["cards"])
    assert next(r for r in pub["requests"] if r["id"] == req["id"])["mine"] is True


# ---------------------------------------------------------------------- the road to shipping
def test_the_ship_plan_nudges_at_the_right_moments():
    now = time.time()
    plan = ShipPlan(start=now - 20 * 3600)
    plan.set_deadline(now + 2 * 3600)  # 90 % of the time is gone
    st = plan.status(now)
    assert st["hours_left"] == 2.0 and st["pace"] == "behind by 5 milestones"
    assert any("record the demo video now" in n for n in st["nudges"])
    assert any("cut scope" in n for n in st["nudges"])
    rb = plan.open_roadblock("CORS error", "hub_x", now=now - (STUCK_ASK_MIN + 5) * 60)
    assert plan.open_roadblock("cors error", "hub_y", now=now)["id"] == rb["id"]  # the same roadblock
    assert any(n.startswith("30-minute rule") for n in plan.status(now)["nudges"])
    plan.close_roadblock(rb["id"], "solved", now)
    for k in ("team", "skeleton", "core", "demo", "readme", "video", "submitted"):
        plan.toggle(k, True, now)
    st = plan.status(now)
    assert st["done"] == 7 and st["pace"] == "on track" and st["nudges"][-1].startswith("Everything is shipped")
    back = ShipPlan.from_json(json.loads(json.dumps(plan.to_json())))
    assert back.status(now)["done"] == 7 and back.deadline == plan.deadline
    # a plan kept by the browser is not trusted: anything malformed is dropped
    junk = ShipPlan.from_json({"start": "yesterday", "deadline": 5, "done": {"team": "x", "video": now, "nope": now},
                               "roadblocks": [{"id": 3}, {"id": "rb1", "started": "soon"}, "x",
                                              {"id": "rb2", "title": "A" * 500, "started": now - 60, "status": "hacked"}]})
    st = junk.status(now)
    assert junk.deadline is None and set(junk.done) == {"video"} and [r["id"] for r in st["roadblocks"]] == ["rb2"]
    assert st["roadblocks"][0]["status"] == "open" and len(st["roadblocks"][0]["title"]) == 140


# ---------------------------------------------------------------------- what she may say
def test_the_sheet_labels_test_data_and_keeps_attribution():
    svc = seeded()
    r = run(svc.unstuck("ModuleNotFoundError: No module named 'cv2'"))
    sheet = hub_sheet(r, ShipPlan().status())
    assert "These are TEST fixtures" in sheet and "sample" not in sheet.lower()
    assert "K1 — shared on this event's board by Test Chen" in sheet
    assert "answer by Test Answerer 5, licence CC BY-SA 4.0" in sheet
    assert "S1 — PyPI: opencv-python — the import name cv2 comes from the PyPI package opencv-python" in sheet
    assert "No deadline is set in the Ship tab yet." in sheet
    assert "stuck on one roadblock for 30 minutes" in sheet  # her 30-minute rule is grounded (found live)
    assert set(HUB_IDS.findall(sheet)) >= {"S1", "S2", "S3", "S4", "K1", "M1"}


def test_the_grounding_check_knows_hub_ids_versions_and_the_learners_own_numbers():
    r = run(seeded().unstuck("ModuleNotFoundError: No module named 'cv2'"))
    sheet = hub_sheet(r)
    q = "my app on port 5173 says No module named 'cv2'"
    ok = hub_grounding("[calm] S1: install opencv-python 4.12.0.88 (Python >=3.7) — your port 5173 is fine; K1 agrees.",
                       sheet, q)
    assert ok["ok"] is True, ok
    bad = hub_grounding("[calm] Install opencv-python 5.1.2, see S9 and ask M4.", sheet, q)
    assert bad["ok"] is False and {"S9", "M4"} <= set(bad["unknown"])


def test_refs_and_follow_ups():
    r = run(seeded().unstuck("ModuleNotFoundError: No module named 'cv2'"))
    assert refs_of(r)[:4] == ["S1", "S2", "S3", "S4"] and item_by_ref(r, "k1")["ref"] == "K1"
    assert about_hub("what does S2 say?", r) and about_hub("is that answer old?", r)
    assert not about_hub("what about S9?", r) and not about_hub("Explain recursion", r)
    # found in review: products that look like result IDs are not follow-ups
    assert not about_hub("How do I upload to S3 with boto3?", r) and not about_hub("my M1 Mac is slow", r)


# ---------------------------------------------------------------------- in a conversation
def chat(c, sid, message, **extra):
    return parse_sse(c.post("/api/chat", json={"session_id": sid, "message": message, **extra}).text)


def test_a_roadblock_in_the_chat_runs_the_search_and_she_answers_from_it():
    app = create_app(make_settings(), vision=FakeVision())  # the labelled offline mock tutor
    with TestClient(app) as c:
        sid = new_sid()
        ev = chat(c, sid, "I keep getting ModuleNotFoundError: No module named 'cv2' in C:\\Users\\dan\\proj")
        names = [n for n, _ in ev]
        meta = next(d for n, d in ev if n == "meta")
        assert meta["hub"] == {"mode": "run", "kind": "unstuck", "report_id": None}
        assert names.index("hub") < names.index("delta")
        hub = [d for n, d in ev if n == "hub"]
        assert hub[0] == {"state": "running", "kind": "unstuck"} and hub[-1]["state"] == "ready"
        assert any(d.get("step") == "stackoverflow" for d in hub)
        done = next(d for n, d in ev if n == "done")
        assert done["hub"]["kind"] == "unstuck" and done["hub"]["check"]["ok"] is True
        rid = done["hub"]["report_id"]
        report = c.get(f"/api/hub/report?session_id={sid}").json()
        assert report["id"] == rid and report["items"][0]["ref"] == "S1"
        # the Ship tab counts this roadblock
        ship = c.get(f"/api/hub/ship?session_id={sid}").json()["ship"]
        assert ship["stuck"][0]["title"].startswith("ModuleNotFoundError")
        # a follow-up about the results: she looks S2 up and the panel follows
        ev = chat(c, sid, "What does S2 say exactly?")
        meta = next(d for n, d in ev if n == "meta")
        assert meta["hub"]["mode"] == "context"
        focus = [d for n, d in ev if n == "focus"]
        assert focus[0]["kind"] == "hub" and focus[0]["ids"] == ["S2"] and focus[0]["source"] == "question"
        assert [d for n, d in ev if n == "tool"][0] == {"name": "get_hub_item", "summary": "S2"}
        assert next(d for n, d in ev if n == "done")["hub"]["check"]["ok"] is True
        # ordinary tutoring stays ordinary
        ev = chat(c, sid, "Explain recursion to me please.")
        assert next(d for n, d in ev if n == "meta")["hub"] is None


def test_the_searched_words_never_include_their_paths():
    app = create_app(make_settings(), vision=FakeVision())
    with TestClient(app) as c:
        chat(c, new_sid(), "I get ModuleNotFoundError: No module named 'cv2' in C:\\Users\\dan\\secret\\main.py "
                           "running on http://localhost:5173")
        calls = " ".join(q for _s, q in app.state.services.hub.sources.calls)
        assert "cv2" in calls
        for private in ("Users", "dan", "secret", "main.py", "localhost", "5173"):
            assert private not in calls, private


def test_team_mentor_learn_and_ship_turns():
    llm = FakeLLM(text="[calm] P1 fits. \n\n### Best matches\n- P1")
    app = create_app(make_settings(), llm=llm, vision=FakeVision())
    with TestClient(app) as c:
        sid = new_sid()
        ev = chat(c, sid, "Find me a teammate who knows React")
        hub = [d for n, d in ev if n == "hub"]
        ready = hub[-1]
        assert ready["state"] == "ready" and ready["kind"] == "team" and ready["items"] >= 1
        assert [d["step"] for d in hub if d.get("state") == "progress"][:2] == ["board", "github"]  # searched live
        sheet = next(m["content"] for m in llm.requests[-1] if str(m["content"]).startswith("[Who fits what the learner asked"))
        assert "P1 — TEST Ben Fixture — public GitHub profile @test-ben-react" in sheet
        assert "has not said they are looking for a team" in sheet and "sample" not in sheet.lower()
        ev = chat(c, sid, "Is there a mentor who knows PyTorch?")
        assert [d for n, d in ev if n == "hub"][-1]["kind"] == "mentors"
        sheet = next(m["content"] for m in llm.requests[-1] if str(m["content"]).startswith("[Who fits what the learner asked"))
        assert "M1 — TEST Expert Vik — Stack Overflow top answerer for [pytorch]" in sheet
        ev = chat(c, sid, "Where can I learn WebSockets with FastAPI fast?")
        assert [d for n, d in ev if n == "hub"][-1]["kind"] == "learn"
        # the deadline: no search, her sheet is the Ship tab
        c.post("/api/hub/ship", json={"session_id": sid, "deadline": time.time() + 5 * 3600})
        c.post("/api/hub/ship", json={"session_id": sid, "milestone": "team", "done": True})
        ev = chat(c, sid, "How much time do we have left before the deadline?")
        assert [d for n, d in ev if n == "hub"] == [{"state": "ready", "kind": "ship", "report_id": None}]
        sheet = next(m["content"] for m in llm.requests[-1] if str(m["content"]).startswith("[The learner's ship status"))
        assert "Milestones done: 1 of 7" in sheet and "Time left until the deadline: 5.0 hours" in sheet


def test_board_routes_with_a_browser_token():
    app = create_app(make_settings(), vision=FakeVision())
    with TestClient(app) as c:
        sid, other = new_sid(), new_sid()
        r = c.post("/api/hub/profile", json={"session_id": sid, "name": "Mia", "skills": ["svelte", "figma"],
                                            "looking_for": "backend", "github": "octo-test", "github_consent": True})
        assert r.status_code == 200
        token = r.json()["token"]  # created once, given back once
        assert "token" not in c.post("/api/hub/profile", json={"session_id": sid, "name": "Mia R."}).json()
        # another session of the same browser sends its token back
        hello = c.post("/api/hub/hello", json={"session_id": other, "token": token}).json()
        assert hello["board"]["me"] and hello["offline"] is True and len(hello["milestones"]) == 7
        req = c.post("/api/hub/requests", json={"session_id": other, "title": "CORS again", "tags": ["cors"]}).json()
        rid = req["request"]["id"]
        assert c.post(f"/api/hub/requests/{rid}/claim", json={"session_id": sid}).status_code == 409  # own request
        stranger = new_sid()
        assert c.post(f"/api/hub/requests/{rid}/claim", json={"session_id": stranger}).status_code == 401
        res = c.post(f"/api/hub/requests/{rid}/resolve", json={"session_id": sid, "share": True,
                                                                 "fix": "Exact origin in allow_origins."}).json()
        assert res["card_id"] and any(x["id"] == res["card_id"] for x in res["board"]["cards"])
        board = c.get(f"/api/hub/board?session_id={sid}").json()
        assert all("owner" not in p for p in board["profiles"])
        assert c.delete(f"/api/hub/profile?session_id={sid}").json()["ok"] is True
        assert c.post("/api/hub/ship", json={"session_id": sid, "deadline": time.time() + 90 * 86400}).status_code == 422
        assert c.post("/api/hub/ship", json={"session_id": sid, "milestone": "nope", "done": True}).status_code == 422
        health = c.get("/api/health").json()["hub"]
        assert health == {"enabled": True, "offline": True, "public_people": True, "event_location": "Miami",
                          "github_token": False}
        assert "samples" not in c.post("/api/hub/hello", json={"session_id": new_sid()}).json()


def test_the_hub_can_be_turned_off():
    app = create_app(make_settings(hub_enabled=False), vision=FakeVision())
    with TestClient(app) as c:
        ev = chat(c, new_sid(), "I get ModuleNotFoundError: No module named 'cv2'")
        assert next(d for n, d in ev if n == "meta")["hub"] is None
        assert c.get(f"/api/hub/board?session_id={new_sid()}").status_code == 404


def test_fixture_sources_record_what_was_asked():
    src = FixtureSources(FIXTURES)
    run(src.so_search("ModuleNotFoundError No module named 'cv2'", "opencv"))
    assert src.calls == [("stackoverflow", "ModuleNotFoundError No module named 'cv2' [opencv]")]
    assert src.as_of == "2026-09-20"
