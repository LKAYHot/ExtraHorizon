"""The hackathon hub's people are real: this event's board, public GitHub profiles in the event's city, Stack
Overflow's top answerers — and real open questions on the help board. No sample entries anywhere.

Offline TEST fixtures only (synthetic profiles and experts, labelled, links to example.org); tests never go online.
"""

from __future__ import annotations

import asyncio
import json

from starlette.testclient import TestClient

from extrahorizon.app import create_app
from extrahorizon.hub.board import Board
from extrahorizon.hub.people import languages_for, location_in, so_tags_for
from extrahorizon.hub.report import hub_grounding, hub_sheet
from extrahorizon.hub.service import HubService
from extrahorizon.hub.sources import FixtureSources, SourceError

from .conftest import FakeLLM, FakeVision, make_settings, new_sid, parse_sse

NEVER = ("never-shown", "never_shown", "@never")  # the fixtures' e-mail, blog, social and company fields


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def chat(c, sid, message, **extra):
    return parse_sse(c.post("/api/chat", json={"session_id": sid, "message": message, **extra}).text)


# ---------------------------------------------------------------------- teammates: the board, then public profiles
def test_teammates_are_real_public_profiles_verified_and_nothing_private_is_read():
    svc = HubService(make_settings())
    steps: list[dict] = []
    r = run(svc.people("Find me a teammate who knows Svelte", None, "team", progress=steps.append))
    assert [(s["step"], s["state"]) for s in steps] == [("board", "done"), ("github", "reading"), ("github", "done")]
    # GitHub's own user search, by the language and the event's city — nothing else about the learner
    searched = [q for s, q in svc.sources.calls if q.startswith("users ")]
    assert searched == ['users type:user language:"Svelte" repos:>=3 location:"Miami"']
    p1 = r["items"][0]
    assert p1["ref"] == "P1" and p1["source"] == "github" and p1["login"] == "test-ana-svelte"
    assert p1["covers"] == ["svelte"] and p1["evidence"][0].startswith("svelte in 2 public GitHub repos")
    assert p1["signals"] == ["hackathons", "a student", "a university", "open to collaborating"]  # words, not the bio
    assert p1["location"] == "Miami, FL (TEST)" and p1["last_push"] == "2026-09-12"
    audit = next(a for a in r["audit"] if a["source"] == "github_people")
    assert audit["excluded"] == {"an organisation, not a person": 1, "no public activity for a year": 1}
    blob = json.dumps(r) + hub_sheet(r)
    assert not any(w in blob for w in NEVER), "an e-mail, blog, social or company field was read"
    assert "bio" not in p1 and "loves hackathons" not in blob  # the bio itself is never kept


def test_the_board_comes_first_and_public_people_are_leads_not_participants():
    svc = HubService(make_settings())
    b = svc.board
    run(b.save_profile(b.new_token(), {"name": "Test Rae", "skills": "react, typescript"}))
    r = run(svc.people("Find me a teammate who knows React", None, "team"))
    assert [(x["ref"], x["source"]) for x in r["items"]] == [("P1", "board"), ("P2", "github")]
    sheet = hub_sheet(r)
    assert sheet.startswith("[Who fits what the learner asked") and "NOT at this event" in sheet
    assert "P1 — Test Rae — on this event's board" in sheet
    assert ("P2 — TEST Ben Fixture — public GitHub profile @test-ben-react; location on their profile: Miami Beach "
            "(TEST)") in sheet
    assert "has not said they are looking for a team" in sheet and "marked available for hire on GitHub" in sheet
    assert "GitHub profiles searched: public repositories in TypeScript or JavaScript, location Miami." in sheet
    ok = hub_grounding("[calm] P2 has 2 public repositories of their own, last push 2026-08-30, since 2019.", sheet, "")
    assert ok["ok"] is True, ok
    bad = hub_grounding("[calm] P2 has 12 repositories and joined in 2015.", sheet, "")
    assert bad["ok"] is False
    # found live: "last pushed on August 30" (no year) is the sheet's 2026-08-30 — another day is not
    assert hub_grounding("[calm] P2 last pushed on August 30 and 30 Aug is fine.", sheet, "")["ok"] is True
    assert hub_grounding("[calm] P2 last pushed on August 31.", sheet, "")["unknown"] == ["August 31"]
    # found live: the model writes dates with non-breaking hyphens (2026‑08‑30) and thousands with narrow spaces
    assert hub_grounding("[calm] P2 last pushed 2026\u201108\u201130.", sheet, "")["ok"] is True
    assert hub_grounding("[calm] P2 last pushed 2026\u201108\u201131.", sheet, "")["ok"] is False
    # found live: a login's digits (github.com/Xivaldivia26) are part of a name, not a figure; units still count
    assert hub_grounding("[calm] P2 is @TestUser26 — https://github.com/TestUser26 has it.", sheet, "")["ok"] is True
    from extrahorizon.coord.report import grounding_check
    assert grounding_check("It is 12km away.", "It is 5 km away.")["unknown"] == ["12"]  # a glued unit is a figure


def test_where_to_look_comes_from_the_question_or_the_event():
    assert location_in("Find me a React dev in Orlando", "Miami") == "Orlando"
    assert location_in("someone near Fort Lauderdale who knows Svelte", "Miami") == "Fort Lauderdale"
    assert location_in("In Tampa, who knows Flutter?", "Miami") == "Tampa"
    assert location_in("a teammate who is good in React and in TypeScript", "Miami") == "Miami"  # skills are not places
    assert location_in("a remote teammate who knows Rust", "Miami") is None
    assert location_in("anyone who knows Go", "") is None
    svc = HubService(make_settings(hub_event_location=""))
    run(svc.people("Find me a Python dev anywhere", None, "team"))
    assert [q for s, q in svc.sources.calls if q.startswith("users ")] == ['users type:user language:"Python" repos:>=3']


def test_roles_github_cannot_show_are_said_plainly():
    assert languages_for(["design", "pitch"]) == [] and languages_for(["frontend", "ml"]) == ["TypeScript", "Python"]
    assert languages_for(["react", "svelte"]) == ["TypeScript", "Svelte"]  # found live: Svelte was never searched
    svc = HubService(make_settings())
    r = run(svc.people("We need a designer", None, "team"))
    assert not any(q.startswith("users ") for _s, q in svc.sources.calls)  # nothing to search on GitHub
    assert r["hints"][0].startswith("design: their work rarely shows on GitHub")
    assert "Note: design: their work rarely shows on GitHub" in hub_sheet(r)
    r = run(svc.people("Find me teammates", None, "team"))
    assert any("No skill or role was named" in h for h in r["hints"])


def test_githubs_limit_is_said_and_nothing_is_made_up():
    class Limited(FixtureSources):
        async def gh_user(self, login):
            raise SourceError("github", "GitHub's limit without a token is reached (60 profile reads an hour)")

    s = make_settings()
    svc = HubService(s, sources=Limited(s.hub_offline_dir), board=Board(None))
    r = run(svc.people("Find me a teammate who knows Svelte", None, "team"))
    assert r["items"] == [] and r["errors"] == [{"source": "GitHub", "message": "GitHub's limit without a token is "
                                                                                 "reached (60 profile reads an hour)"}]
    sheet = hub_sheet(r)
    assert "Could not read: GitHub" in sheet and "Do not guess" in sheet


# ---------------------------------------------------------------------- mentors: the board, then public experts
def test_mentors_are_board_mentors_then_stack_overflows_top_answerers():
    assert so_tags_for(["pytorch"], "Is there a mentor who knows PyTorch?") == ["pytorch"]
    assert so_tags_for(["frontend"], "a frontend mentor") == ["reactjs", "javascript"]
    svc = HubService(make_settings())
    b = svc.board
    run(b.save_profile(b.new_token(), {"kind": "mentor", "name": "Test Mentor Lia", "skills": "pytorch, python",
                                       "availability": "available now"}))
    r = run(svc.people("Is there a mentor who knows PyTorch?", None, "mentors"))
    got = [(m["ref"], m["source"], m["name"]) for m in r["mentors"]]
    assert got == [("M1", "board", "Test Mentor Lia"), ("M2", "stackoverflow", "TEST Expert Vik"),
                   ("M3", "stackoverflow", "TEST Expert Uma")]  # the one answering this month first
    vik = r["mentors"][1]
    assert vik["active_this_month"] and vik["month_answers"] == 2 and vik["answers"] == 45
    audit = next(a for a in r["audit"] if a["source"] == "stackoverflow_experts")
    assert audit["excluded"] == {"fewer than 10 answers on the tag": 1, "not a registered account": 1}
    sheet = hub_sheet(r)
    assert "M2 — TEST Expert Vik — Stack Overflow top answerer for [pytorch]: 45 answers on the tag" in sheet
    assert "not a mentor at this event" in sheet and "Stack Overflow has no private messages" in sheet


# ---------------------------------------------------------------------- the help board: real open questions
def test_the_help_board_lists_real_questions_nobody_has_answered():
    app = create_app(make_settings(), vision=FakeVision())
    with TestClient(app) as c:
        sid = new_sid()
        empty = c.get(f"/api/hub/questions?session_id={sid}").json()
        assert empty["tags"] == [] and empty["items"] == [] and empty["why"] is None  # no card, no search yet
        c.post("/api/hub/profile", json={"session_id": sid, "name": "Mia", "skills": "python, fastapi"})
        q = c.get(f"/api/hub/questions?session_id={sid}").json()
        assert q["tags"] == ["fastapi", "python"] and q["why"] == "the skills on your card"
        assert [x["id"] for x in q["items"]] == [950001, 950011, 950002]  # the tags in turn, newest first, each once
        assert q["items"][2]["title"] == 'TEST — FastAPI "Depends" with a class and a default'  # entities decoded
        # found live: [python]'s daily questions crowded out [fastapi]'s — each tag gets its turn
        assert q["audit"][0]["excluded"] == {"already answered": 1, "voted down": 1, "closed": 1,
                                             "asked more than 180 days ago": 1}
        assert q["items"][0]["license"] == "CC BY-SA 4.0" and q["items"][0]["author"]
        # without a card: the stack of their last search
        other = new_sid()
        chat(c, other, "ModuleNotFoundError: No module named 'svelte' in my svelte app")
        q2 = c.get(f"/api/hub/questions?session_id={other}").json()
        assert "svelte" in q2["tags"] and q2["why"] == "the stack of your last search"
    # a quiet tag gets its language's questions too (found live: [fastapi]'s newest unsolved one was 101 days old)
    svc = HubService(make_settings())
    assert run(svc.open_questions(["svelte"]))["tags"] == ["svelte", "javascript"]
    assert run(svc.open_questions(["fastapi"]))["tags"] == ["fastapi", "python"]
    assert run(svc.open_questions(["python"]))["tags"] == ["python"]


# ---------------------------------------------------------------------- no samples anywhere
def test_there_are_no_sample_entries_anywhere():
    svc = HubService(make_settings())
    assert svc.board.profiles == {} and svc.board.requests == {} and svc.board.cards == {}
    assert "samples" not in svc.board.public()
    r = run(svc.people("Find me a teammate who knows React", None, "team"))
    assert "sample" not in json.dumps(r).lower() and "sample" not in hub_sheet(r).lower()


def test_find_people_in_a_follow_up_searches_public_sources_too():
    llm = FakeLLM(script=["[calm] Here you go.",
                          'tools:[{"name": "find_people", "arguments": {"skills": "pytorch", "kind": "mentor"}}]',
                          "[calm] M1 answers PyTorch questions on Stack Overflow."])
    app = create_app(make_settings(), llm=llm, vision=FakeVision())
    with TestClient(app) as c:
        sid = new_sid()
        chat(c, sid, "Find me a teammate who knows Svelte")
        ev = chat(c, sid, "and who could help us with P1's PyTorch model?")
        report = c.get(f"/api/hub/report?session_id={sid}").json()
        assert report["kind"] == "mentors" and report["mentors"][0]["source"] == "stackoverflow"
        done = next(d for n, d in ev if n == "done")
        assert done["hub"]["report_id"] == report["id"]
