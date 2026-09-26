"""Independent cross-check against the county's own conflict list.

Miami-Dade's coordination system regenerates "Potential Collaboration Project" — pairs of
projects whose footprints overlap — and publishes them (FACTYPE1/CONFLTID1 ↔ FACTYPE2/CONFLTID2,
where FACTYPE is the layer name and CONFLTID the project ID). Each finding is marked with
whether the county lists the same pair; the county pairs we do not flag are explained (one
project excluded as finished/ended, or the footprints we received do not overlap).
"""

from __future__ import annotations

from typing import Any

from .catalog import query_page, sql_str
from .model import clean, epoch_ms_to_date
from .overlap import Finding

Key = tuple[str, str]  # (layer key, project ID)


def county_pairs(rows: list[dict[str, Any]]) -> dict[frozenset[Key], dict[str, Any]]:
    out: dict[frozenset[Key], dict[str, Any]] = {}
    for r in rows:
        a = (clean(r.get("FACTYPE1")), clean(r.get("CONFLTID1")))
        b = (clean(r.get("FACTYPE2")), clean(r.get("CONFLTID2")))
        if not a[0] or not a[1] or not b[0] or not b[1] or a == b:
            continue
        start, end = epoch_ms_to_date(r.get("STARTDATE")), epoch_ms_to_date(r.get("ENDDATE"))
        out[frozenset((a, b))] = {
            "object_id": r.get("OBJECTID"),
            "agencies": [clean(r.get("AGCYNAME1")), clean(r.get("AGCYNAME2"))],
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        }
    return out


def cross_check(findings: list[Finding], pairs: dict[frozenset[Key], dict[str, Any]],
                verified: set[Key], excluded: dict[Key, str], conflicts_url: str) -> dict[str, Any]:
    """Mark every finding and summarize the agreement in both directions."""
    ours: set[frozenset[Key]] = set()
    for f in findings:
        key = frozenset(((f.a.source, f.a.project_id), (f.b.source, f.b.project_id)))
        ours.add(key)
        hit = pairs.get(key)
        a, b = sql_str(f.a.project_id), sql_str(f.b.project_id)
        f.county = {"listed": bool(hit), "object_id": hit["object_id"] if hit else None,
                    "record_url": query_page(conflicts_url, f"(CONFLTID1={a} AND CONFLTID2={b}) OR "
                                                            f"(CONFLTID1={b} AND CONFLTID2={a})") if hit else None}
    intersecting = [f for f in findings if f.distance_m <= 0.0]
    confirmed = sum(1 for f in intersecting if f.county.get("listed"))
    both_ours = [k for k in pairs if all(p in verified for p in k)]
    missed = [k for k in both_ours if k not in ours]
    # the county also pairs one project with itself when it is listed in two layers (e.g. a joint
    # water + sewer contract under one project ID) — one project, not two utilities to coordinate
    same_project = [k for k in missed if len({pid for _layer, pid in k}) == 1]
    other = [k for k in missed if k not in same_project]
    outside: dict[str, int] = {}
    with_excluded = 0  # each pair once (by reason, a pair with two excluded projects counts twice)
    for k in pairs:
        if all(p in verified for p in k):
            continue
        with_excluded += 1
        reasons = sorted({excluded.get(p, "not in the layers read") for p in k if p not in verified})
        for r in reasons:
            outside[r] = outside.get(r, 0) + 1
    return {
        "county_pairs": len(pairs),
        "our_intersecting": len(intersecting),
        "our_intersecting_confirmed": confirmed,
        "county_pairs_between_verified_projects": len(both_ours),
        "county_pairs_we_also_flag": len(both_ours) - len(missed),
        "county_pairs_same_project": len(same_project),
        "county_pairs_we_do_not_flag": [sorted(list(k)) for k in other][:20],
        "county_pairs_we_do_not_flag_count": len(other),
        "our_intersecting_not_listed": len(intersecting) - confirmed,
        "county_pairs_with_excluded_project": outside,
        "county_pairs_with_excluded_project_total": with_excluded,
    }
