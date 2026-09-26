"""Tools Rika can call while she talks about the analysis — so she can know ALL of it, not only the fact sheet.

* ``find_findings`` — any finding of the analysis (all of them, also those the panel does not list): by ID, by a
  project's ID, name, street or place, by plan or agency, by kind, by the county's list — with exact counts.
* ``get_project`` — a project and every finding it is part of.
* ``show_on_map`` — the learner's map shows findings or one project.
* ``recheck_finding`` — read both projects of a finding again from the county's service and verify them again.

What a tool returns is plain text in the fact sheet's own format. Only the parts built from the data count as
verified facts for the grounding check (finding and project lines, counts, a re-check's values) — never an echo of
the model's own arguments, a label or an error text, so a look-up cannot launder an invented number.
Looking things up also moves the map (``focus`` events), so the learner sees what she talks about.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from .report import finding_line, fmt_project

log = logging.getLogger("extrahorizon.coord")

MAX_SHOWN = 15  # findings described in one answer
MAX_SPOT = 50  # findings highlighted on the map at once

TOOL_SPECS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "find_findings",
        "description": (
            "Look up findings of the analysis on screen — ANY of them, not only those in the fact sheet: by ID "
            "(F146), by a project's ID, name, street or place (\"Biscayne Blvd\", \"SR 826\", \"68 Street\"), by plan "
            "or agency (\"WASD Sewer\", \"FDOT\"), by kind or by the county's list. Returns how many match (exact) and "
            "the details of the best ones, and shows them on the learner's map."),
        "parameters": {"type": "object", "properties": {
            "ids": {"type": "array", "items": {"type": "string"}, "description": "finding IDs such as F146"},
            "text": {"type": "string", "description": "words from a project name, street or place, or a project ID "
                                                      "(in English, as written in the data)"},
            "plans": {"type": "array", "items": {"type": "string"},
                      "description": "every plan the finding must involve, e.g. [\"WASD Sewer\", \"FDOT\"]"},
            "category": {"type": "string", "enum": ["both", "near", "same_time"],
                         "description": "both = close and at the same time; near = close only; same_time = same "
                                        "time nearby"},
            "county_listed": {"type": "boolean",
                              "description": "only pairs that are (true) or are not (false) on the county's list"},
            "sort": {"type": "string", "enum": ["strongest", "closest", "most_days_together", "largest_shared_area"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SHOWN},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_project",
        "description": "Projects of the analysis by project ID or words of the name / street: plan, status, dates "
                       "and every finding they are part of.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 8},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "show_on_map",
        "description": "Show several findings, or one project, on the learner's map now. (The map already follows "
                       "the finding a question names and the first finding you name.)",
        "parameters": {"type": "object", "properties": {
            "ids": {"type": "array", "items": {"type": "string"}, "description": "finding IDs such as F146"},
            "project_id": {"type": "string"},
        }},
    }},
    {"type": "function", "function": {
        "name": "recheck_finding",
        "description": "Read both projects of a finding again from the county's service now and verify them again "
                       "(status, dates, footprints, distance). Use it when the learner asks whether something is "
                       "still true, current or verified.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    }},
]
_ARGS = {"find_findings": {"ids", "text", "plans", "category", "county_listed", "sort", "limit"},
         "get_project": {"query", "limit"}, "show_on_map": {"ids", "project_id"}, "recheck_finding": {"id"}}

_STOP = set("""a an the of in on at to for and or with without what which where who whose is are was were be been
does do did how many much any all some there their them it its this that these those me my our tell show list find
give about near close nearby around along between from into by than then please overlap overlaps overlapping
finding findings project projects work works plan plans utility utilities county""".split())
_SYN = {"street": "st", "avenue": "ave", "av": "ave", "boulevard": "blvd", "road": "rd", "drive": "dr",
        "expressway": "expy", "expwy": "expy", "expw": "expy", "xway": "expy", "exwy": "expy", "place": "pl",
        "court": "ct", "terrace": "ter", "lane": "ln", "highway": "hwy", "parkway": "pkwy", "northwest": "nw",
        "southwest": "sw", "northeast": "ne", "southeast": "se", "north": "n", "south": "s", "east": "e", "west": "w"}
# words that say what kind of street or which side — alone they match hundreds of names, so they only rank
_GENERIC = {"st", "ave", "blvd", "rd", "dr", "expy", "pl", "ct", "ter", "ln", "hwy", "pkwy", "nw", "sw", "ne", "se",
            "n", "s", "e", "w", "sr", "us", "cr", "i", "fm", "wm", "from", "to", "phase", "improvements", "improvement",
            "replacement", "installation", "project", "main", "mains", "line", "lines"}


def _tokens(text: str) -> list[str]:
    out = []
    for t in re.findall(r"[a-z0-9][a-z0-9.\-]*", (text or "").lower()):
        t = t.strip(".-")
        t = re.sub(r"^(\d+)(st|nd|rd|th)$", r"\1", t)  # 68th → 68
        t = _SYN.get(t, t)
        if t and t not in _STOP:
            out.append(t)
    return out


def _words(text: str) -> set[str]:
    return set(_tokens(text)) | set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _match(query: list[str], words: set[str]) -> int:
    """How well words match a query: -1 = not at all. Every distinctive query word (a name, a number) must be
    there; street-type and direction words only rank. "Zzqx Ave" matches nothing, "Biscayne Blvd" matches
    Biscayne."""
    distinctive = [t for t in query if t not in _GENERIC]
    must = distinctive or query
    if not must or any(t not in words for t in must):
        return -1
    return sum(1 for t in query if t in words)


class ToolRunner:
    """Runs the tools of one turn against the analysis on screen; ``emit(event, data)`` reaches the browser."""

    def __init__(self, report: dict[str, Any], service: Any, emit: Callable[[str, dict[str, Any]], None]) -> None:
        self.report = report
        self.service = service
        self.emit = emit
        self.all: list[dict[str, Any]] = report.get("_all_findings") or report["findings"]
        self.by_id = {f["id"]: f for f in self.all}
        self.rank = {f["id"]: n for n, f in enumerate(self.all)}
        self.projects = {p["uid"]: p for p in report["projects_index"]}
        self.listed = {f["id"] for f in report["findings"]}
        self._pwords = {uid: _words(" ".join(str(p.get(k) or "") for k in (
            "name", "project_id", "plan_short", "agency_short", "facility", "status"))) for uid, p in self.projects.items()}
        self._plan_words = {uid: _words(" ".join(str(p.get(k) or "") for k in ("plan_short", "agency_short",
                                                                              "facility")))
                            for uid, p in self.projects.items()}
        self.used: list[dict[str, str]] = []  # what she looked up (shown under her answer)
        self.facts: list[str] = []  # data the tools returned (verified facts for the grounding check)
        self._last: tuple[str, set[str]] = ("", set())  # the last look-up: its caption and its findings
        self.spot: set[str] = set()  # what the map shows now (her answer may pick one finding out of it)

    # ------------------------------------------------------------------ dispatch
    async def run(self, name: str, raw_args: str) -> str:
        try:
            args = json.loads(raw_args or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            return "error: the arguments were not valid JSON"
        fn = {"find_findings": self._find, "get_project": self._project, "show_on_map": self._show,
              "recheck_finding": self._recheck}.get(name)
        if fn is None:
            return f"error: there is no tool named {name}"
        try:
            return await fn(**{k: v for k, v in args.items() if k in _ARGS[name]})
        except Exception:  # noqa: BLE001 — a tool failure is told to the model, never raised into the turn
            log.exception("tool %s failed", name)
            return f"error: {name} failed on the server"

    # ------------------------------------------------------------------ helpers
    def focus(self, ids: list[str], label: str, project: str | None = None, source: str = "tool",
              within: bool = False) -> None:
        """Move the learner's map; ``within`` picks one finding out of what it shows (the spotlight stays)."""
        found = [i for i in ids if i in self.by_id]
        if not found and not project:
            return
        shown = found[:MAX_SPOT]
        if not within:
            self.spot = set(found)
        data = {"ids": shown, "total": len(found), "label": label, "project": project, "source": source,
                "report_id": self.report.get("id"),
                # findings the panel does not list travel with the event, so the map can draw them
                "findings": [self.by_id[i] for i in shown if i not in self.listed]}
        if within:
            data["within"] = True
        self.emit("focus", data)

    def _note(self, name: str, summary: str) -> None:
        """What she looked up, shown under her answer (the same look-up twice is one tag)."""
        tag = {"name": name, "summary": summary}
        if tag not in self.used:
            self.used.append(tag)

    def _norm_ids(self, ids: Any) -> list[str]:
        from .refs import finding_ids

        out: list[str] = []
        for x in ids if isinstance(ids, list) else [ids]:
            s = str(x).strip().upper().replace(" ", "")
            got = [s] if re.fullmatch(r"F\d{1,6}", s) else finding_ids(str(x))
            out += [g for g in got if g not in out]
        return out

    def _limit(self, value: Any, default: int, top: int) -> int:
        try:
            return max(1, min(int(value), top))
        except (TypeError, ValueError):
            return default

    def _plan_side(self, uid: str, term: str) -> bool:
        toks = _tokens(term)
        return bool(toks) and set(toks) <= self._plan_words[uid]

    def _plan_named(self, text: Any) -> str | None:
        """The plan a text names exactly (its words are the plan's own: "DTPW Paving", "WASD · Sewer")."""
        toks = set(_tokens(str(text or "")))
        if not toks:
            return None
        for p in self.projects.values():
            if toks == set(_tokens(p["plan_short"])):
                return p["plan_short"]
        return None

    def _missing(self, ids: list[str]) -> str:
        gone = [i for i in ids if i not in self.by_id]
        if not gone:
            return ""
        return f"\nNo such finding in this analysis: {', '.join(gone)} (it has F1–F{len(self.all)})."

    # ------------------------------------------------------------------ tools
    async def _find(self, ids: Any = None, text: Any = None, plans: Any = None, category: Any = None,
                    county_listed: Any = None, sort: Any = None, limit: Any = None) -> str:
        pool = list(self.all)
        what: list[str] = []
        wanted: list[str] = []
        if ids:
            wanted = self._norm_ids(ids)
            pool = [f for f in pool if f["id"] in wanted]
            what.append(", ".join(wanted) or "those IDs")
        if plans:
            terms = [str(t) for t in (plans if isinstance(plans, list) else [plans]) if str(t).strip()]
            unknown = [t for t in terms if not any(self._plan_side(uid, t) for uid in self.projects)]
            if unknown:
                names = "; ".join(sorted({p["plan_short"] for p in self.projects.values()}))
                self._note("find_findings", "unknown plan")
                return f"No plan of this analysis is called {', '.join(repr(t) for t in unknown)}. The plans are: {names}."
            pool = [f for f in pool if all(self._plan_side(f["a"], t) or self._plan_side(f["b"], t) for t in terms)]
            what.append(" & ".join(terms))
        if category in ("both", "near", "same_time"):
            pool = [f for f in pool if f["category"] == category]
            what.append({"both": "close and at the same time", "near": "close only",
                         "same_time": "same time nearby"}[category])
        if isinstance(county_listed, bool):
            pool = [f for f in pool if bool(f["county"].get("listed")) == county_listed]
            what.append("on the county's list" if county_listed else "not on the county's list")
        plan_named = self._plan_named(text)
        if plan_named:
            # "DTPW Paving" / "WASD · Sewer" is a plan, not words to find in project names ("Paving Marking …")
            pool = [f for f in pool if self._plan_side(f["a"], plan_named) or self._plan_side(f["b"], plan_named)]
            if not any(plan_named.lower() in w.lower() for w in what):
                what.append(plan_named)
            text = None
        if text and str(text).strip():
            q = _tokens(str(text))
            scored = [(_match(q, self._pwords[f["a"]] | self._pwords[f["b"]]), f) for f in pool] if q else []
            best = max((sc for sc, _ in scored), default=-1)
            pool = [f for sc, f in scored if best >= 0 and sc == best]
            what.append(f'"{str(text).strip()}"')
        key = {"closest": lambda f: (f["distance_m"], self.rank[f["id"]]),
               "most_days_together": lambda f: (-max(f["overlap_days"], 0), self.rank[f["id"]]),
               "largest_shared_area": lambda f: (-f["shared_area_m2"], self.rank[f["id"]])}.get(
            str(sort or ""), lambda f: self.rank[f["id"]])
        pool.sort(key=key)
        n = self._limit(limit, 8, MAX_SHOWN)
        label = " · ".join(what) or "all findings"
        order = {"closest": "closest first", "most_days_together": "most days together first",
                 "largest_shared_area": "largest shared area first"}.get(str(sort or ""))
        caption = f"{label} · {order}" if order else label  # the tag and the spotlight say how they are ordered
        self._note("find_findings", caption)
        if not pool:
            return f"No findings match {label}." + self._missing(wanted)
        shown = pool[:n]
        self._last = (caption, {f["id"] for f in pool})
        self.focus([f["id"] for f in pool], caption)
        rows = [finding_line(f, self.projects) + " Suggested: " + " ".join(f["actions"]) for f in shown]
        count = f"{len(pool):,} finding{'' if len(pool) == 1 else 's'}"
        self.facts.append(count + "\n" + "\n".join(rows))
        return (f"{count} match {label} (showing {len(shown)}, {str(sort or 'strongest').replace('_', ' ')} first; "
                f"the learner's map shows them):\n" + "\n".join(rows) + self._missing(wanted))

    async def _project(self, query: Any = "", limit: Any = None) -> str:
        q = str(query or "").strip()
        exact = [p for p in self.projects.values() if str(p.get("project_id")) == q]
        if exact:
            hits = exact
        else:
            toks = _tokens(q)
            scored = [(_match(toks, self._pwords[uid]), p) for uid, p in self.projects.items()] if toks else []
            best = max((sc for sc, _ in scored), default=-1)
            hits = [p for sc, p in scored if best >= 0 and sc == best]
        hits = hits[:self._limit(limit, 5, 8)]
        self._note("get_project", q)
        if not hits:
            return f'No project of the analysis matches "{q}".'
        lines = []
        for p in hits:
            fs = [f for f in self.all if p["uid"] in (f["a"], f["b"])]
            lines.append(fmt_project(p) + f"; agency status {p.get('agency_status') or 'n/a'}"
                         + (f"; published as {p['parts']} records" if p.get("parts", 1) > 1 else "")
                         + f"; findings: {len(fs):,}"
                         + (" — " + "; ".join(
                             f"{f['id']} with {self.projects[f['b'] if f['a'] == p['uid'] else f['a']]['plan_short']} "
                             f"({f['category_label'].lower()})" for f in fs[:10]) if fs else ""))
        first = hits[0]
        ids = [f["id"] for f in self.all if first["uid"] in (f["a"], f["b"])]
        self._last = (first["name"], set(ids))
        self.focus(ids, first["name"], project=first["uid"])
        self.facts.append("\n".join(lines))
        return "\n".join(lines)

    async def _show(self, ids: Any = None, project_id: Any = None) -> str:
        wanted = self._norm_ids(ids) if ids else []
        project = None
        if project_id:
            project = next((p for p in self.projects.values() if str(p.get("project_id")) == str(project_id).strip()),
                           None)
        found = [i for i in wanted if i in self.by_id]
        if not found and not project:
            return "Nothing to show: " + (self._missing(wanted).strip() or "no finding or project given.")
        # a caption a learner can read: what she looked up, not a list of fifteen IDs
        if found and len(found) > 1 and set(found) <= self._last[1] and self._last[0]:
            label = self._last[0]
        elif len(found) > 3:
            label = f"{len(found)} findings she named"
        else:
            label = ", ".join(found) if found else project["name"]
        extra = ""
        if project and not found:
            found = [f["id"] for f in self.all if project["uid"] in (f["a"], f["b"])]
            if not found:
                extra = " It is on the map; it has no findings under these rules."
        self._note("show_on_map", label)
        self.focus(found, label, project=project["uid"] if project else None)
        return f"Shown on the learner's map: {label}.{extra}" + self._missing(wanted)

    async def _recheck(self, id: Any = "") -> str:  # noqa: A002 — the tool's parameter name
        fid = (self._norm_ids(id) or [""])[0]
        if fid not in self.by_id:
            self._note("recheck_finding", f"{fid or id}: not found")
            return f"No such finding in this analysis: {fid or id}."
        r = await self.service.recheck(self.report, fid)
        self.emit("recheck", {"id": fid, "result": r, "report_id": self.report.get("id")})
        self.focus([fid], fid)
        f = self.by_id[fid]
        parts = []
        for rec in r["records"]:
            p = self.projects[rec["uid"]]
            if not rec["found"]:
                parts.append(f"{p['plan_short']} project {p['project_id']}: {rec.get('error')}")
            elif rec.get("changed"):
                parts.append(f"{p['plan_short']} project {p['project_id']} changed: " + ", ".join(rec["changed"])
                             + f" (now {rec['live'].get('status')}, {rec['live'].get('start')} → {rec['live'].get('end')})")
            else:
                parts.append(f"{p['plan_short']} project {p['project_id']} unchanged")
        dist = r.get("distance_m_live")
        if dist is not None:
            parts.append(f"distance now {'intersecting' if dist <= 0 else f'{round(dist):,} m'}"
                         + ("" if r.get("distance_matches", True) else f" (was {round(f['distance_m']):,} m)"))
        verdict = "still holds" if r.get("ok") else "does not hold as published before"
        self._note("recheck_finding", f"{fid}: {'unchanged' if r.get('ok') else 'changed'}")
        out = (f"{fid} re-checked at the county's service just now ({r['checked_at'][11:16]} UTC): the finding "
               f"{verdict}. " + "; ".join(parts) + ".")
        self.facts.append(out)
        return out
