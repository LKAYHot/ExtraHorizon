"""Run the utility-coordination analysis from the command line and show what Rika is told.

Reads Miami-Dade County's public Utility Coordination data (or the synthetic TEST fixtures),
verifies it, finds the overlaps and prints the summary, every layer's checks, the county
cross-check and — on request — the exact fact sheet her prompt gets or one finding in full
with a live re-check against the county's service. No keys needed; nothing is sent to an LLM.

    cd backend
    uv run python scripts/coord_report.py                  # live county data
    uv run python scripts/coord_report.py --offline        # the synthetic TEST fixtures
    uv run python scripts/coord_report.py --sheet          # + the fact sheet, word for word
    uv run python scripts/coord_report.py --finding F12    # + one finding in full (+ live re-check)
    uv run python scripts/coord_report.py --distance 100 --window 30 --area 1000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from extrahorizon.config import Settings
from extrahorizon.coord.report import fact_sheet
from extrahorizon.coord.service import CoordService

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "coord"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="read the synthetic TEST fixtures instead of the county")
    ap.add_argument("--sheet", action="store_true", help="print the fact sheet exactly as her prompt gets it")
    ap.add_argument("--finding", help="print one finding in full, e.g. F12 (live: re-checked at the source)")
    ap.add_argument("--distance", type=float, help="'close' in metres (default EH_COORD_DISTANCE_M)")
    ap.add_argument("--window", type=int, help="'same time' in days (default EH_COORD_WINDOW_DAYS)")
    ap.add_argument("--area", type=float, help="'same time' alone within metres (default EH_COORD_AREA_M)")
    ap.add_argument("--json", action="store_true", help="dump the whole report as JSON instead")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    overrides = {"coord_offline_dir": FIXTURES} if a.offline else {}
    svc = CoordService(Settings(**overrides))
    try:
        steps: list[str] = []
        report = await svc.analyze(
            svc.params({"distance_m": a.distance, "window_days": a.window, "area_m": a.area}),
            progress=lambda m: steps.append(m.get("source") or m.get("step") or "") if m.get("state") == "error" else None)
        if a.json:
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return 0
        s, x = report["summary"], report["crosscheck"]
        print(f"{report['publisher']} — read {report['generated_at_local']}"
              + ("  [OFFLINE TEST FIXTURE]" if report["offline"] else ""))
        if report.get("stale_note"):
            print(f"NOTE: {report['stale_note']}")
        print(f"records {s['records_received']:,}/{s['records_reported']:,} · excluded {s['records_excluded']:,} · "
              f"passed {s['records_passed']:,} → {s['projects_verified']:,} projects (merged parts {s['records_merged']})")
        print(f"rules {report['params']} → findings {s['findings']:,} {s['by_category']}")
        print(f"county list: {x['our_intersecting_confirmed']}/{x['our_intersecting']} of our intersecting pairs; "
              f"we flag {x['county_pairs_we_also_flag']}/{x['county_pairs_between_verified_projects']} of theirs\n")
        for src in report["sources"]:
            bad = [c["code"] for c in src["checks"] if not c["ok"]]
            ex = ", ".join(f"{e['code']} {e['count']}" for e in src["excluded"]) or "—"
            print(f"  {src['key']:<24} {src['received']:>5}/{src['reported']:<5} verified {src['verified']:>4}  "
                  f"excluded: {ex}" + (f"  FAILED CHECKS: {bad}" if bad else "")
                  + (f"  ERROR: {src['error']}" if src.get("error") else ""))
        print("\npairs of plans:")
        for p in report["pairs"][:12]:
            print(f"  {p['plans'][0]} ↔ {p['plans'][1]}: {p['total']} (close + same time {p['both']})")
        if a.sheet:
            print("\n----- fact sheet -----\n" + fact_sheet(report))
        if a.finding:
            f = next((y for y in report["findings"] if y["id"] == a.finding.upper()), None)
            if f is None:
                print(f"\n{a.finding}: no such finding in this report")
                return 1
            idx = {p["uid"]: p for p in report["projects_index"]}
            print(f"\n----- {f['id']} ({f['category']}) -----")
            for uid in (f["a"], f["b"]):
                p = idx[uid]
                print(f"  {p['plan_short']} · {p['name']} · project {p['project_id']} · {p['status']} · "
                      f"{p['start']} → {p['end']}\n    {p['record_url']}")
            print(f"  distance {f['distance_m']} m · shared {f['shared_area_m2']} m² · overlap days "
                  f"{f['overlap_days']} · county list {f['county']['listed']}")
            for r in f["reasons"] + f["actions"]:
                print(f"  - {r}")
            if not report["offline"]:
                print("  live re-check: " + json.dumps(await svc.recheck(report, f["id"]), ensure_ascii=False))
        return 0
    finally:
        await svc.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
