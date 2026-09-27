"""The road to shipping: a deadline, the milestones every hackathon project passes, the roadblocks on the way —
and plain rules that keep a team moving (the 30-minute rule: stuck that long, ask a person)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# (key, title, when it should be done — share of the time between the plan's start and the deadline)
MILESTONES: list[tuple[str, str, float]] = [
    ("team", "Team and idea locked", 0.10),
    ("skeleton", "A hello-world running end to end", 0.25),
    ("core", "The core feature works", 0.55),
    ("demo", "The demo path works every time", 0.75),
    ("readme", "README with screenshots", 0.85),
    ("video", "Demo video recorded", 0.92),
    ("submitted", "Submitted on Devpost", 0.97),
]
STUCK_ASK_MIN = 30  # the 30-minute rule
QUIET_HOURS = 3.0  # no milestone for this long → a nudge


@dataclass
class ShipPlan:
    start: float = field(default_factory=time.time)
    deadline: float | None = None
    done: dict[str, float] = field(default_factory=dict)
    roadblocks: list[dict[str, Any]] = field(default_factory=list)

    def set_deadline(self, when: float | None) -> None:
        self.deadline = when

    def toggle(self, key: str, done: bool, now: float | None = None) -> None:
        if key not in {k for k, _t, _f in MILESTONES}:
            raise KeyError(key)
        if done:
            self.done.setdefault(key, now or time.time())
        else:
            self.done.pop(key, None)

    def open_roadblock(self, title: str, report_id: str | None, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        for r in self.roadblocks:  # the same roadblock searched again is the same roadblock
            if r["status"] == "open" and r["title"].lower() == title.lower():
                r["report_id"] = report_id or r.get("report_id")
                return r
        r = {"id": f"rb{uuid.uuid4().hex[:8]}", "title": title[:140], "report_id": report_id,
             "started": now, "status": "open", "ended": None}
        self.roadblocks.append(r)
        del self.roadblocks[:-20]
        return r

    def close_roadblock(self, rid: str, status: str = "solved", now: float | None = None) -> dict[str, Any]:
        r = next((x for x in self.roadblocks if x["id"] == rid), None)
        if r is None:
            raise KeyError(rid)
        r.update({"status": status if status in ("solved", "asked", "dropped") else "solved", "ended": now or time.time()})
        return r

    def status(self, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        span = (self.deadline - self.start) if self.deadline else None
        frac = max(0.0, min(1.0, (now - self.start) / span)) if span and span > 0 else None
        left_h = (self.deadline - now) / 3600 if self.deadline else None
        ms = [{"key": k, "title": t, "due_at": (self.start + f * span) if span else None,
               "done": k in self.done, "done_at": self.done.get(k)} for k, t, f in MILESTONES]
        done_n = sum(1 for m in ms if m["done"])
        expected = sum(1 for _k, _t, f in MILESTONES if frac is not None and f <= frac)
        nxt = next((m for m in ms if not m["done"]), None)
        stuck = []
        for r in self.roadblocks:
            if r["status"] == "open":
                mins = int((now - r["started"]) // 60)
                stuck.append({**r, "minutes": mins, "ask_now": mins >= STUCK_ASK_MIN})
        last = max([self.start, *self.done.values(), *[r["ended"] or 0 for r in self.roadblocks if r["status"] == "solved"]])
        quiet_h = (now - last) / 3600
        pace = None
        if frac is not None:
            gap = expected - done_n
            pace = "on track" if gap <= 0 else f"behind by {gap} milestone{'s' if gap != 1 else ''}"
        nudges: list[str] = []
        for r in stuck:
            if r["ask_now"]:
                nudges.append(f"30-minute rule: \"{r['title']}\" has blocked you for {r['minutes']} minutes — "
                              "ask a mentor or a peer on the help board.")
        if left_h is not None and left_h <= 0 and "submitted" not in self.done:
            nudges.append("The deadline has passed — check whether late submissions are allowed.")
        elif left_h is not None and left_h <= 1 and "submitted" not in self.done:
            nudges.append("Less than an hour left: submit on Devpost now; improve it afterwards only if the rules allow.")
        elif left_h is not None and left_h <= 3 and "video" not in self.done:
            nudges.append("Three hours or less left: record the demo video now — it always takes longer than planned.")
        if frac is not None and frac >= 0.5 and expected - done_n >= 2:
            nudges.append("Behind schedule: cut scope — make the one demo path work before adding anything.")
        if quiet_h >= QUIET_HOURS and done_n < len(MILESTONES) and self.deadline:
            nudges.append(f"No milestone for {int(quiet_h)} hours — what is the smallest next step?")
        if done_n == len(MILESTONES):
            nudges.append("Everything is shipped. Celebrate — then sleep.")
        return {"start": self.start, "deadline": self.deadline, "now": now,
                "hours_left": None if left_h is None else round(left_h, 1),
                "elapsed": None if frac is None else round(frac, 3), "milestones": ms, "done": done_n,
                "total": len(MILESTONES), "expected": expected, "pace": pace,
                "next": nxt["title"] if nxt else None, "roadblocks": [dict(r) for r in self.roadblocks[-8:]],
                "stuck": stuck, "quiet_hours": round(quiet_h, 1), "nudges": nudges}

    def public(self, now: float | None = None) -> dict[str, Any]:
        return self.status(now)

    def to_json(self) -> dict[str, Any]:
        return {"start": self.start, "deadline": self.deadline, "done": dict(self.done),
                "roadblocks": [dict(r) for r in self.roadblocks]}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> ShipPlan:
        """A plan the browser kept (after a server restart) — anything malformed is dropped, never trusted."""
        def num(v: Any) -> float | None:
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            return f if 1e9 < f < 1e10 else None  # epoch seconds, 2001–2286

        now = time.time()
        p = cls(start=num(d.get("start")) or now)
        p.deadline = num(d.get("deadline"))
        keys = {k for k, _t, _f in MILESTONES}
        p.done = {k: t for k, v in (d.get("done") or {}).items() if k in keys and (t := num(v))} \
            if isinstance(d.get("done"), dict) else {}
        rbs = []
        for r in (d.get("roadblocks") or [])[-20:] if isinstance(d.get("roadblocks"), list) else []:
            if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not num(r.get("started")):
                continue
            rbs.append({"id": r["id"][:12], "title": str(r.get("title") or "")[:140],
                        "report_id": r["report_id"][:40] if isinstance(r.get("report_id"), str) else None,
                        "started": num(r["started"]), "ended": num(r.get("ended")),
                        "status": r.get("status") if r.get("status") in ("open", "solved", "asked", "dropped") else "open"})
        p.roadblocks = rbs
        return p


def ship_lines(st: dict[str, Any]) -> list[str]:
    """The ship status in her fact sheet (numbers she may say)."""
    if not st:
        return []
    lines = []
    if st.get("hours_left") is not None:
        lines.append(f"Time left until the deadline: {st['hours_left']} hours"
                     + (f" ({st['pace']})" if st.get("pace") else "") + ".")
    else:
        lines.append("No deadline is set in the Ship tab yet.")
    lines.append(f"Milestones done: {st['done']} of {st['total']}" + (f"; next: {st['next']}." if st.get("next") else "."))
    for r in st.get("stuck") or []:
        lines.append(f"Open roadblock: \"{r['title']}\" for {r['minutes']} minutes"
                     + (" — past the 30-minute rule." if r["ask_now"] else "."))
    for n in st.get("nudges") or []:
        lines.append(f"Nudge: {n}")
    return lines
