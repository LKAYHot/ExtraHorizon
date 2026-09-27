"""Her look-ups in follow-up answers about the hub (OpenAI function tools, like the analysis tools): every detail
of a result on screen, a new search for a different roadblock, people on the board, places to learn. What a tool
returns is verified data (it enters the grounding check); a new search replaces the results on screen."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from .report import hub_sheet, peer_line, person_line, source_line
from .service import item_by_ref, refs_of

log = logging.getLogger("extrahorizon.hub")

HUB_TOOL_SPECS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "get_hub_item",
        "description": "Every detail of one result of the hub search on screen, by its ID (S1, L2, P1, M1, K1): the "
                       "full excerpt and code, links, flags, attribution, availability.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    {"type": "function", "function": {
        "name": "search_public_help",
        "description": "Search Stack Overflow, GitHub issues, npm/PyPI and this event's board for a NEW error or "
                       "roadblock the learner describes (the results on screen are replaced). Pass the error text or "
                       "a short description of the problem.",
        "parameters": {"type": "object", "properties": {"problem": {"type": "string"}}, "required": ["problem"]}}},
    {"type": "function", "function": {
        "name": "find_people",
        "description": "Find teammates (kind 'hacker') or mentors (kind 'mentor') who cover the given skills or "
                       "roles: this event's board first, then real public GitHub profiles in the event's city "
                       "(teammates) or Stack Overflow's top answerers for the stack (mentors). The results on screen "
                       "are replaced.",
        "parameters": {"type": "object", "properties": {
            "skills": {"type": "string", "description": "skills or roles, e.g. 'react, design'"},
            "kind": {"type": "string", "enum": ["hacker", "mentor"]}}, "required": ["skills"]}}},
    {"type": "function", "function": {
        "name": "learning_resources",
        "description": "Verified places to learn a topic: GitHub starters and examples, DEV Community articles, "
                       "top Stack Overflow questions.",
        "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}}},
]
_ARGS = {"get_hub_item": {"id"}, "search_public_help": {"problem"}, "find_people": {"skills", "kind"},
         "learning_resources": {"topic"}}


class HubToolRunner:
    """The hub tools of one turn; ``emit(event, data)`` reaches the browser (the same interface as the analysis
    tools, so the turn's look-up loop runs either)."""

    def __init__(self, report: dict[str, Any], service: Any, session: Any, emit: Callable[[str, dict[str, Any]], None],
                 on_report: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.service = service
        self.session = session
        self.emit = emit
        self.on_report = on_report  # the turn follows a new search (her answer's IDs, the Ship tab's roadblock)
        self.used: list[dict[str, str]] = []
        self.facts: list[str] = []
        self.spot: set[str] = set()
        self._set(report)

    def _set(self, report: dict[str, Any]) -> None:
        self.report = report
        self.by_id = {r: item_by_ref(report, r) for r in refs_of(report)}

    def _note(self, name: str, summary: str) -> None:
        tag = {"name": name, "summary": summary}
        if tag not in self.used:
            self.used.append(tag)

    def focus(self, ids: list[str], label: str, project: str | None = None, source: str = "tool",
              within: bool = False) -> None:
        found = [i for i in ids if i in self.by_id]
        if not found:
            return
        if not within:
            self.spot = set(found)
        data = {"kind": "hub", "ids": found[:10], "total": len(found), "label": label, "project": None,
                "source": source, "report_id": self.report.get("id"), "findings": []}
        if within:
            data["within"] = True
        self.emit("focus", data)

    async def run(self, name: str, raw_args: str) -> str:
        try:
            args = json.loads(raw_args or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            return "error: the arguments were not valid JSON"
        fn = {"get_hub_item": self._item, "search_public_help": self._search, "find_people": self._people,
              "learning_resources": self._learn}.get(name)
        if fn is None:
            return f"error: there is no tool named {name}"
        try:
            return await fn(**{k: v for k, v in args.items() if k in _ARGS[name]})
        except Exception:  # noqa: BLE001 — a tool failure is told to the model, never raised into the turn
            log.exception("hub tool %s failed", name)
            return f"error: {name} failed on the server"

    # ------------------------------------------------------------------ tools
    async def _item(self, id: Any = "") -> str:  # noqa: A002 — the tool's parameter name
        ref = str(id or "").strip().upper()
        x = self.by_id.get(ref)
        if x is None:
            self._note("get_hub_item", f"{ref or '?'}: not on screen")
            have = ", ".join(self.by_id) or "none"
            return f"No result {ref or '(no ID)'} on screen (the IDs are: {have})."
        if ref[0] in "SL":
            text = source_line(x)
            ex = x.get("excerpt") or {}
            links = [u for u in (x.get("url"), x.get("answer_url"), x.get("docs")) if u]
            text += ("\nFlags: " + ", ".join(x.get("flags") or [])) if x.get("flags") else ""
            text += ("\nFull excerpt: \"" + ex["text"] + "\"") if ex.get("text") else ""
            text += ("\nLinks: " + " ; ".join(links)) if links else ""
        elif ref[0] == "K":
            text = peer_line(x) + ("\nLinks: " + " ; ".join(x.get("links") or []) if x.get("links") else "")
        else:
            text = person_line(x, mentor=ref[0] == "M")
        self._note("get_hub_item", ref)
        self.focus([ref], ref)
        self.facts.append(text)
        return text

    def _replace(self, report: dict[str, Any], what: str) -> str:
        if report.get("error"):
            self._note(what, "failed")
            return f"The search failed: {report['error']}."
        self.session.hub_report = report
        self._set(report)
        if self.on_report is not None:
            self.on_report(report)
        self.emit("hub", {"state": "ready", "report_id": report["id"], "kind": report["kind"],
                          "items": len(report.get("items") or []), "offline": report.get("offline", False)})
        sheet = hub_sheet(report)
        self.facts.append(sheet)
        refs = refs_of(report)
        if refs:
            self.focus(refs[:1] if report["kind"] == "unstuck" else refs, report["kind"])
        return sheet

    async def _search(self, problem: Any = "") -> str:
        text = str(problem or "").strip()[:1500]
        if not text:
            return "error: describe the problem to search for"
        report = await self.service.unstuck(text, owner=self.service.board.owner_of(getattr(self.session, "hub_token", None)))
        out = self._replace(report, "search_public_help")
        if not report.get("error"):
            self._note("search_public_help", (report.get("query") or {}).get("text", "")[:80])
        return out

    async def _people(self, skills: Any = "", kind: Any = "hacker") -> str:
        me = self.service.board.mine(getattr(self.session, "hub_token", None))
        report = await self.service.people(str(skills or "")[:300], me, "mentors" if str(kind) == "mentor" else "team")
        out = self._replace(report, "find_people")
        self._note("find_people", f"{'mentors' if str(kind) == 'mentor' else 'teammates'}: {str(skills)[:60]}")
        return out

    async def _learn(self, topic: Any = "") -> str:
        text = str(topic or "").strip()[:200]
        if not text:
            return "error: say what topic to look for"
        report = await self.service.learn(text)
        out = self._replace(report, "learning_resources")
        if not report.get("error"):
            self._note("learning_resources", text[:80])
        return out
