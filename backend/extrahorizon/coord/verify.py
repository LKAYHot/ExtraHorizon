"""Verification of every source and every record — nothing enters the analysis unchecked.

Dataset checks: published by the county's account and public, served over HTTPS, the
expected schema, every record received (count = what the service reports), how recently the
layer was edited. Record checks decide whether a record is a *future or ongoing* planned
project: an ID, both dates, start ≤ end, plausible years, not finished (status or end date),
a valid footprint inside the county. Everything excluded is counted by reason.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

import shapely
from shapely import make_valid
from shapely.geometry import shape

from .catalog import PUBLISHER_OWNER, REGION, REQUIRED_FIELDS, Source

# statuses that mean the work is finished or stopped — whole values after the agency's step number
# ("08- Final Completion", "6-Close-Out"), so "Incomplete" or "Design Complete" never match
_STEP = re.compile(r"^\s*\d+\s*-\s*")
FINISHED = re.compile(r"^(?:complete|completed|const\.?\s?complete|final completion|administrative c\w*|closed|"
                      r"close-?out|line item completed)$")
STOPPED = re.compile(r"^(?:dropped(?:/transferred)?|transferred|inactive|cancell?ed)$")


def status_class(value: Any) -> str | None:
    """'finished' | 'stopped' | None for one status value of a record."""
    s = _STEP.sub("", str(value or "").strip().lower())
    if FINISHED.match(s):
        return "finished"
    if STOPPED.match(s):
        return "stopped"
    return None


EXCLUDE_REASONS = {
    "missing_id": "no project ID",
    "missing_dates": "start or end date missing",
    "bad_dates": "start date after the end date",
    "implausible_dates": "placeholder or impossible dates (e.g. 1899-12-31)",
    "finished_status": "status says the work is finished",
    "stopped_status": "status says the work was dropped, transferred or is inactive",
    "ended": "end date already passed",
    "no_geometry": "no footprint",
    "invalid_geometry": "footprint cannot be repaired",
    "outside_region": "footprint outside Miami-Dade County (e.g. FDOT work in the Florida Keys)",
}
NOTES = {
    "agency_alias": "agency name spelled differently in the data — merged with its department",
    "geometry_repaired": "footprint was self-intersecting — repaired (make_valid)",
    "parts_merged": "the same project appears as several features — merged",
    "finished_status_future_end": "agency status says finished but the end date is still ahead — excluded to be safe",
    "stale_record": "record not updated for more than a year",
}


@dataclass
class DatasetCheck:
    code: str
    ok: bool
    detail: str

    def public(self) -> dict[str, Any]:
        return {"code": self.code, "ok": self.ok, "detail": self.detail}


@dataclass
class SourceAudit:
    """What was received from one layer and what verification did with it."""

    key: str
    title: str
    kind: str
    url: str
    item_url: str
    utility: bool
    reported: int = 0
    received: int = 0
    candidates: int = 0
    verified: int = 0  # future/ongoing projects that passed every check (after merging parts)
    excluded: dict[str, int] = field(default_factory=dict)
    notes: dict[str, int] = field(default_factory=dict)
    checks: list[DatasetCheck] = field(default_factory=list)
    last_edit: str | None = None
    fetched_at: str | None = None
    error: str | None = None

    def exclude(self, reason: str) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + 1

    def note(self, code: str) -> None:
        self.notes[code] = self.notes.get(code, 0) + 1

    def public(self) -> dict[str, Any]:
        return {
            "key": self.key, "title": self.title, "kind": self.kind, "url": self.url, "item_url": self.item_url,
            "utility": self.utility, "reported": self.reported, "received": self.received,
            "candidates": self.candidates, "verified": self.verified,
            "excluded": [{"code": k, "count": v, "label": EXCLUDE_REASONS.get(k, k)} for k, v in
                         sorted(self.excluded.items(), key=lambda kv: -kv[1])],
            "notes": [{"code": k, "count": v, "label": NOTES.get(k, k)} for k, v in sorted(self.notes.items())],
            "checks": [c.public() for c in self.checks], "last_edit": self.last_edit,
            "fetched_at": self.fetched_at, "error": self.error,
        }


def dataset_checks(src: Source, item: dict[str, Any], layer: dict[str, Any], reported: int, received: int,
                   today: dt.date, offline: bool = False, static: bool = False) -> list[DatasetCheck]:
    """``static``: a reference layer (the county's boundary) — how long ago it was edited does not matter."""
    checks: list[DatasetCheck] = []
    owner, access = item.get("owner"), item.get("access")
    if offline:
        checks.append(DatasetCheck("publisher", False, "offline test fixture — not the county's data"))
    else:
        checks.append(DatasetCheck("publisher", owner == PUBLISHER_OWNER and access == "public",
                                   f"ArcGIS item owner '{owner}', access '{access}'"))
        checks.append(DatasetCheck("https", src.url.startswith("https://"), "read over HTTPS from the county's service"))
    names = {f.get("name") for f in layer.get("fields", [])}
    missing = [f for f in REQUIRED_FIELDS if f not in names]
    if src.key == "PotentialConflictProject":
        missing = [f for f in ("FACTYPE1", "CONFLTID1", "FACTYPE2", "CONFLTID2") if f not in names]
    elif static:
        missing = [f for f in ("OBJECTID",) if f not in names]
    checks.append(DatasetCheck("schema", not missing, "expected fields present" if not missing
                               else f"missing fields: {', '.join(missing)}"))
    checks.append(DatasetCheck("complete", reported == received,
                               f"received {received} of {reported} records the service reports"))
    edit = (layer.get("editingInfo") or {}).get("lastEditDate")
    if edit:
        d = (dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(milliseconds=edit)).date()
        age = (today - d).days
        if static:
            checks.append(DatasetCheck("reference", True, f"reference layer, last edited {d.isoformat()}"))
        else:
            checks.append(DatasetCheck("fresh", age <= 30, f"layer last edited {d.isoformat()} ({age} days ago)"))
    return checks


def record_verdict(row: dict[str, Any], today: dt.date, start: dt.date | None, end: dt.date | None,
                   updated: dt.date | None) -> tuple[str | None, list[str]]:
    """(exclusion reason or None, non-fatal notes) — geometry is checked separately."""
    notes: list[str] = []
    if not str(row.get("PROJECTID") or "").strip():
        return "missing_id", notes
    if start is None or end is None:
        return "missing_dates", notes
    if start > end:
        return "bad_dates", notes
    if start.year < 1990 or end.year > 2060:
        return "implausible_dates", notes
    classes = {status_class(row.get("GENPRJSTAT")), status_class(row.get("AGYPRJSTAT"))}
    if "finished" in classes:
        if end >= today:
            notes.append("finished_status_future_end")
        return "finished_status", notes
    if "stopped" in classes:
        return "stopped_status", notes
    if end < today:
        return "ended", notes
    if updated is not None and (today - updated).days > 365:
        notes.append("stale_record")
    return None, notes


def county_region(geojson: dict[str, Any] | None) -> Any | None:
    """The county's boundary as a prepared polygon, widened by ≈100 m for the ≈30 m generalisation (None: the
    boundary could not be read — the bounding box is used instead)."""
    if not geojson:
        return None
    try:
        g = shape(geojson)
        g = g if g.is_valid else make_valid(g)
    except Exception:  # noqa: BLE001 — malformed boundary: fall back to the bounding box
        return None
    if g.is_empty:
        return None
    region = g.buffer(0.001)
    shapely.prepare(region)
    return region


def check_geometry(geojson: dict[str, Any] | None, region: Any | None = None) -> tuple[Any | None, str | None, list[str]]:
    """(shapely geometry in lon/lat, exclusion reason, notes). ``region``: the county's own boundary — a footprint
    entirely outside it is excluded (FDOT's Keys work); without it, the county's bounding box."""
    if not geojson:
        return None, "no_geometry", []
    try:
        g = shape(geojson)
    except Exception:  # noqa: BLE001 — malformed coordinates
        return None, "invalid_geometry", []
    notes: list[str] = []
    if g.is_empty:
        return None, "no_geometry", notes
    if not g.is_valid:
        g = make_valid(g)
        if g.is_empty:
            return None, "invalid_geometry", notes
        notes.append("geometry_repaired")
    if region is not None:
        return (g, None, notes) if region.intersects(g) else (None, "outside_region", notes)
    x0, y0, x1, y1 = REGION["bbox"]
    bx0, by0, bx1, by1 = g.bounds
    if bx0 < x0 or bx1 > x1 or by0 < y0 or by1 > y1:
        return None, "outside_region", notes
    return g, None, notes
