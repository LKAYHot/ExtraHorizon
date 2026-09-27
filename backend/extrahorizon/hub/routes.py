"""REST routes of the hackathon hub (the searches themselves run as chat turns — she explains every result).

Every hub request carries this browser's board token in the ``X-Hub-Token`` header (kept in localStorage): the first
write creates it and returns it once. Only tokens this server issued are accepted back, and a client address gets a
handful of new ones an hour — a made-up or freshly minted identity buys no extra votes.
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

from ..sessions import ApiError
from .board import BoardError
from .ship import MILESTONES, ShipPlan

SESSION_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{20,80}$")
MAX_BODY = 64 * 1024  # a card, a request or a ship change is small
Tag = Annotated[str, StringConstraints(max_length=40)]
Link = Annotated[str, StringConstraints(max_length=300)]
Text = Annotated[str, StringConstraints(max_length=400)]  # "python, fastapi" as typed
# (the item limit belongs to the list alone: on the union it would also cap the typed text's length)
Skills = Annotated[list[Tag], Field(max_length=20)] | Text
Few = Annotated[list[Tag], Field(max_length=12)] | Text


class SignatureBody(BaseModel):
    kind: str = Field(default="", max_length=60)
    message: str = Field(default="", max_length=240)


class HubHello(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    token: str | None = Field(default=None, max_length=80)
    ship: dict[str, Any] | None = None  # the plan this browser kept, if the server lost it (a restart, a sweep)


class SessionOnly(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)


class TeamBody(BaseModel):
    name: str = Field(default="", max_length=40)
    size: int = Field(default=1, ge=1, le=6)


class ProfileBody(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    kind: Literal["hacker", "mentor"] = "hacker"
    name: str = Field(min_length=1, max_length=40)
    contact: str = Field(default="", max_length=80)
    skills: Skills = Field(default_factory=list)
    looking_for: Few = Field(default_factory=list)
    interests: Few = Field(default_factory=list)
    idea: str = Field(default="", max_length=240)
    availability: str = Field(default="", max_length=40)
    team: TeamBody = Field(default_factory=TeamBody)
    github: str = Field(default="", max_length=40)
    github_consent: bool = False


class RequestBody(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    problem: str = Field(default="", max_length=1500)
    tags: list[Tag] = Field(default_factory=list, max_length=8)
    signature: SignatureBody | None = None
    tried: list[Link] = Field(default_factory=list, max_length=8)
    report_id: str | None = Field(default=None, max_length=40)  # the search it comes from (its roadblock is "asked")


class ResolveBody(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    note: str = Field(default="", max_length=400)
    share: bool = False  # also post what fixed it as a card for everyone
    fix: str = Field(default="", max_length=800)
    links: list[Link] = Field(default_factory=list, max_length=5)


class CardBody(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    problem: str = Field(default="", max_length=300)
    fix: str = Field(min_length=1, max_length=800)
    tags: list[Tag] = Field(default_factory=list, max_length=8)
    links: list[Link] = Field(default_factory=list, max_length=5)
    report_id: str | None = Field(default=None, max_length=40)  # the search it comes from (its roadblock is solved)


class ShipBody(BaseModel):
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    deadline: float | None = None  # epoch seconds (explicit null clears it)
    milestone: str | None = Field(default=None, max_length=20)
    done: bool | None = None
    roadblock: str | None = Field(default=None, max_length=12)
    status: Literal["solved", "asked", "dropped"] | None = None


def register(app: FastAPI, store: Any, services: Any) -> None:
    minted: dict[str, deque[float]] = {}

    @app.middleware("http")
    async def hub_body_limit(request: Request, call_next):
        if request.url.path.startswith("/api/hub/"):
            try:
                size = int(request.headers.get("content-length") or 0)
            except ValueError:
                size = MAX_BODY + 1
            if size > MAX_BODY:
                return JSONResponse({"code": "too_large", "message": "That is too long for the hub."}, 413)
        return await call_next(request)

    def hub():
        if services.hub is None:
            raise ApiError(404, "hub_disabled", "The hackathon hub is turned off (EH_HUB_ENABLED).")
        return services.hub

    def session_of(sid: str, request: Request | None = None):
        if not re.match(SESSION_ID_PATTERN, sid or ""):
            raise ApiError(422, "bad_session_id", "Invalid session id.")
        session = store.get_or_create(sid)
        header = request.headers.get("x-hub-token") if request is not None else None
        if header and _TOKEN_RE.match(header) and services.hub is not None and services.hub.board.known(header):
            session.hub_token = header  # the browser's own token wins over whatever the session had (or lost)
        return session

    def token_for(session: Any, request: Request) -> tuple[str, bool]:
        board = hub().board
        if session.hub_token and board.known(session.hub_token):
            return session.hub_token, False
        ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
        recent = minted.setdefault(ip, deque())
        now = time.monotonic()
        while recent and now - recent[0] > 3600:
            recent.popleft()
        if len(recent) >= services.settings.hub_new_ids_per_hour:
            raise ApiError(429, "too_many_identities", "Too many new board identities from this address — try later.")
        recent.append(now)
        session.hub_token = board.new_token()
        return session.hub_token, True

    def close_roadblocks(session: Any, report_id: str | None, status: str) -> None:
        for rb in session.ship.roadblocks:
            if rb["status"] == "open" and report_id and rb.get("report_id") == report_id:
                session.ship.close_roadblock(rb["id"], status)

    async def board_call(coro):
        try:
            return await coro
        except BoardError as e:
            raise ApiError(e.status, e.code, e.message) from e

    def board_view(session: Any) -> dict[str, Any]:
        b = hub().board
        me = b.mine(session.hub_token)
        return {**b.public(session.hub_token), "me": me["id"] if me else None}

    def with_token(out: dict[str, Any], token: str, created: bool) -> dict[str, Any]:
        return {**out, "token": token} if created else out

    # ------------------------------------------------------------------ session
    @app.post("/api/hub/hello")
    async def hub_hello(req: HubHello, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(req.session_id, request)
        if req.token and _TOKEN_RE.match(req.token) and h.board.known(req.token):
            session.hub_token = req.token
        if req.ship and session.ship.deadline is None and not session.ship.done and not session.ship.roadblocks:
            session.ship = ShipPlan.from_json(req.ship)  # the server lost it (a restart, a sweep): the browser kept it
        report = session.hub_report
        return {"board": board_view(session), "ship": session.ship.public(), "ship_state": session.ship.to_json(),
                "report_id": report["id"] if report and not report.get("error") else None,
                "offline": h.offline, "event_location": getattr(services.settings, "hub_event_location", "") or None,
                "milestones": [{"key": k, "title": t} for k, t, _f in MILESTONES]}

    @app.get("/api/hub/report")
    async def hub_report(session_id: str, request: Request) -> dict[str, Any]:
        hub()
        session = session_of(session_id, request)
        if not session.hub_report or session.hub_report.get("error"):
            raise ApiError(404, "no_hub_report", "No hub search in this session yet.")
        return session.hub_report

    @app.delete("/api/hub/report")
    async def hub_close(session_id: str) -> dict[str, Any]:
        session_of(session_id).hub_report = None
        return {"ok": True}

    # ------------------------------------------------------------------ questions someone here could answer
    @app.get("/api/hub/questions")
    async def hub_questions(session_id: str, request: Request) -> dict[str, Any]:
        """Real Stack Overflow questions nobody has answered yet, for the skills on this browser's card and the stack
        of its last search (at most two tags)."""
        h = hub()
        session = session_of(session_id, request)
        me = h.board.mine(session.hub_token)
        from .signature import _tags_of

        skills = list((me or {}).get("skills") or [])
        tags = _tags_of(" ".join(skills))[0] if skills else []
        why = "the skills on your card" if tags else None
        rep = session.hub_report or {}
        q = rep.get("query") or {}
        last = list((q.get("signature") or {}).get("tags") or q.get("tags") or [])
        generic = {"python", "javascript", "node.js", "npm", "typescript", "cors", "git", "github", "docker"}
        for t in [t for t in last if t not in generic] + [t for t in last if t in generic]:
            if t not in tags:
                tags.append(t)
                why = why or "the stack of your last search"
        specific = [t for t in tags if t not in generic] + [t for t in tags if t in generic]
        return {**(await h.open_questions(specific[:2])), "why": why}

    # ------------------------------------------------------------------ the board
    @app.get("/api/hub/board")
    async def hub_board(session_id: str, request: Request) -> dict[str, Any]:
        return board_view(session_of(session_id, request))

    @app.post("/api/hub/profile")
    async def hub_profile(req: ProfileBody, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(req.session_id, request)
        token, created = token_for(session, request)
        p = await board_call(h.board.save_profile(token, req.model_dump(exclude={"session_id"})))
        h.verify_later(p)
        return with_token({"profile": {k: v for k, v in p.items() if k != "owner"}, "board": board_view(session)},
                          token, created)

    @app.delete("/api/hub/profile")
    async def hub_profile_delete(session_id: str, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(session_id, request)
        gone = await board_call(h.board.delete_profile(session.hub_token or ""))
        return {"ok": gone, "board": board_view(session)}

    @app.post("/api/hub/requests")
    async def hub_request(req: RequestBody, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(req.session_id, request)
        token, created = token_for(session, request)
        r = await board_call(h.board.post_request(token, req.model_dump(exclude={"session_id", "report_id"})))
        close_roadblocks(session, req.report_id, "asked")  # the roadblock she searched is now asked about
        return with_token({"request": {k: v for k, v in r.items() if k != "owner"}, "board": board_view(session)},
                          token, created)

    @app.post("/api/hub/requests/{rid}/claim")
    async def hub_claim(rid: str, req: SessionOnly, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(req.session_id, request)
        await board_call(h.board.claim(session.hub_token or "", rid))
        return {"board": board_view(session)}

    @app.post("/api/hub/requests/{rid}/release")
    async def hub_release(rid: str, req: SessionOnly, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(req.session_id, request)
        await board_call(h.board.release(session.hub_token or "", rid))
        return {"board": board_view(session)}

    @app.post("/api/hub/requests/{rid}/resolve")
    async def hub_resolve(rid: str, req: ResolveBody, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(req.session_id, request)
        r = await board_call(h.board.resolve(session.hub_token or "", rid, req.note))
        card = None
        if req.share and req.fix.strip():
            card = await board_call(h.board.add_card(session.hub_token or "", {
                "title": r["title"], "problem": (r.get("problem") or "")[:300], "fix": req.fix, "tags": r.get("tags"),
                "links": req.links}))
        return {"board": board_view(session), "card_id": card["id"] if card else None}

    @app.delete("/api/hub/requests/{rid}")
    async def hub_withdraw(rid: str, session_id: str, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(session_id, request)
        ok = await board_call(h.board.withdraw(session.hub_token or "", rid))
        return {"ok": ok, "board": board_view(session)}

    @app.post("/api/hub/cards")
    async def hub_card(req: CardBody, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(req.session_id, request)
        token, created = token_for(session, request)
        c = await board_call(h.board.add_card(token, req.model_dump(exclude={"session_id", "report_id"})))
        close_roadblocks(session, req.report_id, "solved")  # sharing what fixed it: that roadblock is solved
        return with_token({"card": {k: v for k, v in c.items() if k not in ("owner", "voters")},
                           "board": board_view(session)}, token, created)

    @app.post("/api/hub/cards/{cid}/helpful")
    async def hub_helpful(cid: str, req: SessionOnly, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(req.session_id, request)
        await board_call(h.board.helpful(session.hub_token or "", cid))  # a vote needs a card (and so a token)
        return {"board": board_view(session)}

    @app.delete("/api/hub/cards/{cid}")
    async def hub_card_delete(cid: str, session_id: str, request: Request) -> dict[str, Any]:
        h = hub()
        session = session_of(session_id, request)
        ok = await board_call(h.board.delete_card(session.hub_token or "", cid))
        return {"ok": ok, "board": board_view(session)}

    # ------------------------------------------------------------------ the road to shipping
    @app.get("/api/hub/ship")
    async def hub_ship(session_id: str, request: Request) -> dict[str, Any]:
        session = session_of(session_id, request)
        return {"ship": session.ship.public(), "ship_state": session.ship.to_json()}

    @app.post("/api/hub/ship")
    async def hub_ship_update(req: ShipBody, request: Request) -> dict[str, Any]:
        session = session_of(req.session_id, request)
        plan = session.ship
        if "deadline" in req.model_fields_set:
            if req.deadline is not None and not (time.time() - 7 * 86400 < req.deadline < time.time() + 30 * 86400):
                raise ApiError(422, "bad_deadline", "The deadline must be within the next 30 days.")
            plan.set_deadline(req.deadline)
        if req.milestone is not None:
            try:
                plan.toggle(req.milestone, bool(req.done))
            except KeyError as e:
                raise ApiError(422, "bad_milestone", "No such milestone.") from e
        if req.roadblock is not None:
            try:
                plan.close_roadblock(req.roadblock, req.status or "solved")
            except KeyError as e:
                raise ApiError(404, "no_roadblock", "No such roadblock.") from e
        return {"ship": plan.public(), "ship_state": plan.to_json()}
