"""Where two plans overlap — in space, in time, or both. Deterministic and exact.

Footprints (lon/lat) are projected to a local metric plane around the county (WGS84
ellipsoid radii at the reference latitude; < 0.5 % scale error across the county), indexed
with an STR-tree, and every candidate pair from two *different plans* (agency · facility) is
measured exactly with GEOS:

* **near** — the footprints are within ``distance_m`` of each other (0 m = they intersect;
  the shared area is measured);
* **same time** — the schedules overlap, or the gap between them is at most ``window_days``;
  on its own this is flagged only for projects within ``area_m`` (a shared crew / yard
  radius) — county-wide "same time" would flag everything;
* **both** — near *and* at the same time: the strongest case for coordinating now.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import shapely
from shapely.geometry import mapping
from shapely.strtree import STRtree

from .model import Project

A_WGS84 = 6378137.0
E2_WGS84 = 0.00669437999014
CATEGORY_WEIGHT = {"both": 3.0, "near": 2.0, "same_time": 1.0}
CATEGORY_LABEL = {"both": "Close by and at the same time", "near": "Physically close",
                  "same_time": "Same time, nearby area"}


@dataclass(frozen=True)
class Params:
    distance_m: float = 150.0
    window_days: int = 60
    area_m: float = 1500.0
    today: dt.date = field(default_factory=dt.date.today)
    lat0: float = 25.76
    lon0: float = -80.30

    def public(self) -> dict[str, Any]:
        return {"distance_m": self.distance_m, "window_days": self.window_days, "area_m": self.area_m,
                "today": self.today.isoformat()}


class LocalProjection:
    """lon/lat ⇄ metres on a tangent plane at (lat0, lon0)."""

    def __init__(self, lat0: float, lon0: float) -> None:
        phi = math.radians(lat0)
        s2 = math.sin(phi) ** 2
        self.m_per_deg_lat = math.radians(1) * A_WGS84 * (1 - E2_WGS84) / (1 - E2_WGS84 * s2) ** 1.5
        self.m_per_deg_lon = math.radians(1) * A_WGS84 / math.sqrt(1 - E2_WGS84 * s2) * math.cos(phi)
        self.lat0, self.lon0 = lat0, lon0

    def forward(self, g: Any) -> Any:
        return shapely.transform(g, lambda c: np.column_stack(((c[:, 0] - self.lon0) * self.m_per_deg_lon,
                                                                (c[:, 1] - self.lat0) * self.m_per_deg_lat)))

    def inverse(self, g: Any) -> Any:
        return shapely.transform(g, lambda c: np.column_stack((c[:, 0] / self.m_per_deg_lon + self.lon0,
                                                                c[:, 1] / self.m_per_deg_lat + self.lat0)))


@dataclass
class Finding:
    a: Project
    b: Project
    category: str
    distance_m: float
    shared_area_m2: float
    overlap_days: int  # > 0: days both are scheduled (end dates count); ≤ 0: −(days between them)
    window_start: dt.date | None
    window_end: dt.date | None
    geometry: dict[str, Any] | None  # the shared area, or the shortest line between the footprints
    score: float = 0.0
    id: str = ""
    county: dict[str, Any] = field(default_factory=dict)

    @property
    def gap_days(self) -> int:
        return max(0, -self.overlap_days)

    def reasons(self) -> list[str]:
        out = []
        if self.distance_m <= 0.0:
            out.append(f"Footprints intersect ({round(self.shared_area_m2):,} m² shared)"
                       if self.shared_area_m2 >= 1 else "Footprints touch")
        else:
            out.append(f"{round(self.distance_m):,} m apart")
        if self.overlap_days > 0:
            n = self.overlap_days
            out.append(f"Scheduled together for {n:,} day{'' if n == 1 else 's'} "
                       f"({self.window_start.isoformat()} → {self.window_end.isoformat()})")
        else:
            first, second = (self.a, self.b) if (self.a.end or dt.date.max) <= (self.b.end or dt.date.max) else (self.b, self.a)
            when = (f"{first.plan_short} ends {first.end.isoformat()}, {second.plan_short} starts "
                    f"{second.start.isoformat()}") if first.end and second.start else ""
            gap = self.gap_days
            out.append((f"Back to back ({when})" if gap == 0 else
                        f"{gap:,} day{'' if gap == 1 else 's'} between the two schedules ({when})"))
        return out

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "category_label": CATEGORY_LABEL[self.category],
            "a": self.a.uid,
            "b": self.b.uid,
            "plans": [self.a.plan_short, self.b.plan_short],
            "distance_m": round(self.distance_m, 1),
            "shared_area_m2": round(self.shared_area_m2, 1),
            "overlap_days": self.overlap_days,
            "gap_days": self.gap_days,
            "window": [self.window_start.isoformat() if self.window_start else None,
                       self.window_end.isoformat() if self.window_end else None],
            "reasons": self.reasons(),
            "actions": actions_for(self),
            "county": self.county,
            "score": round(self.score, 3),
            "geometry": self.geometry,
        }


PIPES = {"water", "sewer", "reclaimed", "stormwater", "gas", "power", "cable"}
SURFACE = {"roadway", "paving", "bridge", "transit", "canal", "misc", "moratorium"}


def actions_for(f: Finding) -> list[str]:
    """Why coordinating helps — general practice for this combination (a recommendation, not data)."""
    kinds = {f.a.kind, f.b.kind}
    out: list[str] = []
    if kinds & PIPES and kinds & SURFACE:
        out.append("Put the pipe work before the road or paving work: one excavation, no cutting of new pavement.")
        out.append("Share maintenance-of-traffic, detours and surface restoration.")
    elif len(kinds & PIPES) == 2:
        out.append("Open one trench window for both networks: shared excavation, dewatering and restoration.")
    elif kinds & PIPES:
        out.append("Coordinate the excavation and restoration of the right-of-way.")
    else:
        out.append("Share maintenance-of-traffic and detours; align lane closures.")
    if f.category in ("both", "same_time"):
        out.append("Share crews, equipment and a staging yard while both are active.")
    if f.category == "near":
        out.append("Sequence the work so the later project does not redo the earlier one.")
    return out


def temporal(a: Project, b: Project) -> tuple[int, dt.date | None, dt.date | None]:
    """(days both are scheduled — an end date is a working day, so one shared date counts as 1 — or,
    when they do not overlap, −(days between them; 0 = back to back), overlap start, overlap end)."""
    assert a.start and a.end and b.start and b.end
    lo, hi = max(a.start, b.start), min(a.end, b.end)
    if hi >= lo:
        return (hi - lo).days + 1, lo, hi
    return -((lo - hi).days - 1), None, None


def find_overlaps(projects: list[Project], geoms_lonlat: list[Any], params: Params) -> list[Finding]:
    """Every flagged pair between two different plans, best first, with IDs F1, F2, …"""
    if len(projects) < 2:
        return []
    proj = LocalProjection(params.lat0, params.lon0)
    geoms = [proj.forward(g) for g in geoms_lonlat]
    tree = STRtree(geoms)
    left, right = tree.query(geoms, predicate="dwithin", distance=max(params.distance_m, params.area_m))
    findings: list[Finding] = []
    for i, j in zip(left.tolist(), right.tolist()):
        if i >= j:
            continue
        a, b = projects[i], projects[j]
        if a.plan == b.plan:
            continue  # the same plan: not a coordination between two utilities
        if a.agency == b.agency and a.project_id == b.project_id:
            continue  # one project listed in two layers
        ga, gb = geoms[i], geoms[j]
        d = float(ga.distance(gb))
        days, w0, w1 = temporal(a, b)
        near = d <= params.distance_m
        same_time = days > 0 or -days <= params.window_days
        if near and same_time:
            cat = "both"
        elif near:
            cat = "near"
        elif same_time and d <= params.area_m:
            cat = "same_time"
        else:
            continue
        shared = 0.0
        geom = None
        if d <= 0.0:
            inter = ga.intersection(gb)
            shared = float(inter.area)
            if not inter.is_empty:
                reduced = shapely.set_precision(inter, 0.5)
                # a sliver of a square metre can vanish at 0.5 m precision: then its point, never an empty polygon
                geom = mapping(proj.inverse(reduced if not reduced.is_empty else inter.representative_point()))
        if geom is None:
            geom = mapping(proj.inverse(shapely.shortest_line(ga, gb)))
        area = max(params.area_m, 1.0)
        closeness = 1.0 - min(d, area) / area
        together = min(max(days, 0), 365) / 365
        apart = min(max(-days, 0), 3650) / 3650
        score = CATEGORY_WEIGHT[cat] + 0.5 * closeness + 0.4 * together - 0.3 * apart
        findings.append(Finding(a, b, cat, d, shared, days, w0, w1, geom, score))
    # ties broken by what the projects are, never by object IDs (the county republishes its layers)
    findings.sort(key=lambda f: (-f.score, f.distance_m, f.a.plan, f.a.project_id, f.b.plan, f.b.project_id))
    for n, f in enumerate(findings, 1):
        f.id = f"F{n}"
    return findings
