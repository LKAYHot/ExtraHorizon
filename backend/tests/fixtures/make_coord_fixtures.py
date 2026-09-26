"""Writes the synthetic utility-coordination fixtures (tests/fixtures/coord/*.geojson).

Clearly TEST data — invented projects around one Miami intersection, built so that the
expected result is known exactly:

* W1 (WASD water) × S1 (WASD sewer) cross, scheduled together        → "both"
* W1 × R1 (FDOT roadway 30 m north, 2028), S1 × R1, W5 × R1          → "near"
* W1 × R2 (DTPW roadway 800 m east, same months), S1 × R2, W5 × S1   → "same_time"
* W1 × W5 (the same plan), W4 × S3 (one joint project in two layers) → skipped
* W4 is published as two records (two parts of project TJ-500)          → one project, parts merged
* W2 finished, W3 ended, S2 placeholder date 1899-12-31, R3 in the Florida Keys → excluded
* R4 on Key Largo: inside the county's bounding box but outside its boundary polygon → excluded
  (MiamiDadeBoundary.geojson is a TEST stand-in for the county's boundary layer)
* the county's list confirms W1 × S1, pairs W2 (excluded) × R1, and W4 × S3 (same project)

The data is valid as of 2026-09-26 ("_as_of" in _meta.json): offline, the analysis uses that date as
"today", so the expected result never drifts with the calendar.

Run: ``uv run python tests/fixtures/make_coord_fixtures.py``
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

OUT = Path(__file__).parent / "coord"
EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
WASD, DTPW, FDOT = ("Miami-Dade Water and Sewer Department",
                    "Miami-Dade County Department of Transportation and Public Works", "FDOT")


def ms(d: str) -> int:
    return int((dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc) - EPOCH).total_seconds() * 1000)


def strip_ew(lat: float, lon0: float, lon1: float, half: float = 0.00005) -> dict:
    return {"type": "Polygon", "coordinates": [[[lon0, lat - half], [lon1, lat - half], [lon1, lat + half],
                                                [lon0, lat + half], [lon0, lat - half]]]}


def strip_ns(lon: float, lat0: float, lat1: float, half: float = 0.00005) -> dict:
    return {"type": "Polygon", "coordinates": [[[lon - half, lat0], [lon + half, lat0], [lon + half, lat1],
                                                [lon - half, lat1], [lon - half, lat0]]]}


def feature(oid: int, pid: str, name: str, agency: str, fac: str, status: str, start: str, end: str, geom: dict,
            agency_status: str | None = None) -> dict:
    return {"type": "Feature", "geometry": geom, "properties": {
        "OBJECTID": oid, "PRJNAME": name, "PROJECTID": pid, "PRJSCOPE": f"TEST fixture — {name}",
        "AGCYNAME": agency, "FACTYPE": fac, "GENPRJSTAT": status, "AGYPRJSTAT": agency_status or status,
        "STARTDATE": ms(start), "ENDDATE": ms(end), "GENCONTEMAIL": "test@example.org", "GENCONTNUM": "0000000000",
        "UPDATDATE": ms("2026-09-01")}}


def write(name: str, feats: list[dict]) -> None:
    (OUT / f"{name}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, indent=1),
                                         encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lat = 25.7700
    write("UtilCoordWater", [
        feature(1, "TW-100", "TEST W1 water main replacement", WASD, "Water", "Design", "2026-10-01", "2027-06-30",
                strip_ew(lat, -80.2500, -80.2400)),
        feature(2, "TW-101", "TEST W2 finished water main", WASD, "Water", "Complete", "2024-01-01", "2027-01-01",
                strip_ew(lat + 0.001, -80.2500, -80.2400), "Completed"),
        feature(3, "TW-102", "TEST W3 ended water main", WASD, "Water", "Construction", "2023-01-01", "2025-01-01",
                strip_ew(lat - 0.001, -80.2500, -80.2400)),
        feature(4, "TJ-500", "TEST W4 joint water part", WASD, "Water", "Planning", "2027-01-01", "2028-01-01",
                strip_ew(25.6000, -80.4050, -80.3950)),
        feature(5, "TW-103", "TEST W5 water main west", WASD, "Water", "Design", "2026-10-01", "2027-06-30",
                strip_ew(lat, -80.2600, -80.2502)),
        feature(6, "TJ-500", "TEST W4 joint water part", WASD, "Water", "Planning", "2027-01-01", "2028-01-01",
                strip_ew(25.6000, -80.3950, -80.3850)),
    ])
    write("UtilCoordSewer", [
        feature(1, "TS-200", "TEST S1 sewer force main", WASD, "Sewer", "Design", "2026-11-01", "2027-03-01",
                strip_ns(-80.2450, lat - 0.0050, lat + 0.0050)),
        feature(2, "TS-201", "TEST S2 placeholder dates", WASD, "Sewer", "Planning", "1899-12-31", "2027-01-01",
                strip_ns(-80.2440, lat - 0.0050, lat + 0.0050)),
        feature(3, "TJ-500", "TEST S3 joint sewer part", WASD, "Sewer", "Planning", "2027-01-01", "2028-01-01",
                strip_ns(-80.4000, 25.5950, 25.6050)),
    ])
    write("UtilCoordRoadway", [
        feature(1, "TR-300", "TEST R1 state road rebuild", FDOT, "Roadway", "Pre-Engineering", "2028-01-01",
                "2029-06-30", strip_ew(lat + 0.00027, -80.2500, -80.2400, 0.00008)),
        feature(2, "TR-301", "TEST R2 county road resurfacing", DTPW, "Roadway", "Construction", "2026-10-15",
                "2027-01-15", strip_ns(-80.2320, lat - 0.0020, lat + 0.0020)),
        feature(3, "TR-302", "TEST R3 Keys highway", FDOT, "Roadway", "Pre-Engineering", "2026-10-01", "2028-01-01",
                strip_ew(24.7000, -81.1100, -81.1000)),
        feature(4, "TR-303", "TEST R4 Key Largo overpass", FDOT, "Roadway", "Design", "2026-10-01", "2028-01-01",
                strip_ew(25.1430, -80.4000, -80.3960)),
    ])
    write("MiamiDadeBoundary", [{"type": "Feature", "properties": {"OBJECTID": 1}, "geometry": {
        "type": "Polygon", "coordinates": [[[-80.87, 25.25], [-80.05, 25.25], [-80.05, 25.98], [-80.87, 25.98],
                                            [-80.87, 25.25]]]}}])
    write("PotentialConflictProject", [
        {"type": "Feature", "geometry": None, "properties": {
            "OBJECTID": 1, "FACTYPE1": "UtilCoordWater", "AGCYNAME1": WASD, "CONFLTID1": "TW-100",
            "FACTYPE2": "UtilCoordSewer", "AGCYNAME2": WASD, "CONFLTID2": "TS-200",
            "STARTDATE": ms("2026-11-01"), "ENDDATE": ms("2027-03-01"), "MODIDATE": ms("2026-09-25")}},
        {"type": "Feature", "geometry": None, "properties": {
            "OBJECTID": 2, "FACTYPE1": "UtilCoordRoadway", "AGCYNAME1": FDOT, "CONFLTID1": "TR-300",
            "FACTYPE2": "UtilCoordWater", "AGCYNAME2": WASD, "CONFLTID2": "TW-101",
            "STARTDATE": ms("2028-01-01"), "ENDDATE": ms("2029-06-30"), "MODIDATE": ms("2026-09-25")}},
        {"type": "Feature", "geometry": None, "properties": {
            "OBJECTID": 3, "FACTYPE1": "UtilCoordWater", "AGCYNAME1": WASD, "CONFLTID1": "TJ-500",
            "FACTYPE2": "UtilCoordSewer", "AGCYNAME2": WASD, "CONFLTID2": "TJ-500",
            "STARTDATE": ms("2027-01-01"), "ENDDATE": ms("2028-01-01"), "MODIDATE": ms("2026-09-25")}},
    ])
    meta: dict = {"_as_of": "2026-09-26"}
    meta.update({k: {"layer": {"editingInfo": {"lastEditDate": ms("2026-09-25")}}}
                 for k in ("UtilCoordWater", "UtilCoordSewer", "UtilCoordRoadway", "PotentialConflictProject")})
    meta["MiamiDadeBoundary"] = {"layer": {"editingInfo": {"lastEditDate": ms("2018-11-13")}}}  # a static layer
    (OUT / "_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
