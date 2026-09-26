"""One planned project, normalized from the county's schema (dates as calendar days)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from .catalog import AGENCY_ALIASES, AGENCY_SHORT, BY_KEY

EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def epoch_ms_to_date(v: Any) -> dt.date | None:
    """ArcGIS date (epoch milliseconds, UTC; may be negative for dates before 1970)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return (EPOCH + dt.timedelta(milliseconds=float(v))).date()
    except (TypeError, ValueError, OverflowError):
        return None


def clean(v: Any) -> str:
    return " ".join(str(v).split()) if v is not None else ""


def canonical_agency(name: str) -> tuple[str, bool]:
    """(canonical name, whether an alias was merged)."""
    n = clean(name)
    return AGENCY_ALIASES.get(n, n), n in AGENCY_ALIASES


def short_agency(name: str) -> str:
    return AGENCY_SHORT.get(name, name.replace("City of Miami - ", "Miami "))


@dataclass
class Project:
    uid: str  # "<source key>:<OBJECTID>"
    source: str
    object_id: int
    project_id: str
    name: str
    scope: str
    agency: str
    facility: str
    status: str
    agency_status: str
    start: dt.date | None
    end: dt.date | None
    updated: dt.date | None
    contact: str
    record_url: str
    geometry: dict[str, Any] | None = None  # GeoJSON, WGS84
    notes: list[str] = field(default_factory=list)  # non-fatal verification notes (codes)
    parts: int = 1  # features merged into this project (same layer + project ID)

    @property
    def plan(self) -> str:
        return f"{self.agency} · {self.facility}"

    @property
    def plan_short(self) -> str:
        return f"{short_agency(self.agency)} · {self.facility}"

    @property
    def kind(self) -> str:
        src = BY_KEY.get(self.source)
        return src.kind if src else self.facility.lower()

    def public(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "source": self.source,
            "object_id": self.object_id,
            "project_id": self.project_id,
            "name": self.name,
            "scope": self.scope[:400],
            "agency": self.agency,
            "agency_short": short_agency(self.agency),
            "facility": self.facility,
            "kind": self.kind,
            "plan": self.plan,
            "plan_short": self.plan_short,
            "status": self.status,
            "agency_status": self.agency_status,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "record_url": self.record_url,
            "notes": list(self.notes),
            "parts": self.parts,
        }


def from_row(source_key: str, row: dict[str, Any], record_url: str) -> Project:
    agency, _ = canonical_agency(row.get("AGCYNAME") or "")
    return Project(
        uid=f"{source_key}:{int(row['OBJECTID'])}",
        source=source_key,
        object_id=int(row["OBJECTID"]),
        project_id=clean(row.get("PROJECTID")),
        name=clean(row.get("PRJNAME")),
        scope=clean(row.get("PRJSCOPE")),
        agency=agency,
        facility=clean(row.get("FACTYPE")),
        status=clean(row.get("GENPRJSTAT")),
        agency_status=clean(row.get("AGYPRJSTAT")),
        start=epoch_ms_to_date(row.get("STARTDATE")),
        end=epoch_ms_to_date(row.get("ENDDATE")),
        updated=epoch_ms_to_date(row.get("UPDATDATE")),
        contact=clean(row.get("GENCONTEMAIL")),
        record_url=record_url,
    )
