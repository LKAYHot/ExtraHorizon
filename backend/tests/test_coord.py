"""Utility-coordination analysis: verification, overlap detection, the county cross-check, the
fact sheet + grounding check, and how it reaches the dialogue — on synthetic TEST fixtures
(tests/fixtures/make_coord_fixtures.py documents the expected result)."""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from extrahorizon.app import create_app
from extrahorizon.coord.intent import wants_analysis, wants_refresh
from extrahorizon.coord.overlap import Params
from extrahorizon.coord.report import fact_sheet, grounding_check
from extrahorizon.coord.service import CoordService
from extrahorizon.llm import MockLLM

from .conftest import FakeLLM, FakeVision, make_settings, new_sid, parse_sse

TODAY = dt.date(2026, 9, 26)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def report():
    svc = CoordService(make_settings())
    return run(svc.analyze(Params(today=TODAY)))


def by_projects(rep, a_pid: str, b_pid: str):
    idx = {p["uid"]: p for p in rep["projects_index"]}
    for f in rep["findings"]:
        pids = {idx[f["a"]]["project_id"], idx[f["b"]]["project_id"]}
        if pids == {a_pid, b_pid}:
            return f
    return None


def test_every_record_is_verified_and_exclusions_are_counted_by_reason(report):
    src = {s["key"]: s for s in report["sources"]}
    ex = lambda k: {e["code"]: e["count"] for e in src[k]["excluded"]}  # noqa: E731
    assert ex("UtilCoordWater") == {"finished_status": 1, "ended": 1}
    assert ex("UtilCoordSewer") == {"implausible_dates": 1}
    assert ex("UtilCoordRoadway") == {"outside_region": 2}  # the Keys, and Key Largo (inside the box, not the county)
    notes = {n["code"] for n in src["UtilCoordWater"]["notes"]}
    assert "finished_status_future_end" in notes  # "Complete" with an end date still ahead → excluded to be safe
    assert src["UtilCoordGas"]["reported"] == 0 and src["UtilCoordPower"]["reported"] == 0  # published but empty
    checks = {c["code"]: c for c in src["UtilCoordWater"]["checks"]}
    assert checks["complete"]["ok"] and checks["schema"]["ok"]
    assert checks["publisher"]["ok"] is False and "fixture" in checks["publisher"]["detail"]  # never passed off as real
    assert report["offline"] is True
    s = report["summary"]
    assert s["projects_verified"] == 7  # W1 W4 W5 · S1 S3 · R1 R2
    # 13 records: 5 excluded, 8 kept — W4's two records are one project (its parts merged)
    assert (s["records_received"], s["records_excluded"], s["records_passed"], s["records_merged"]) == (13, 5, 8, 1)
    w4 = next(p for p in report["projects_index"] if p["project_id"] == "TJ-500" and p["source"] == "UtilCoordWater")
    assert w4["parts"] == 2 and "parts_merged" in w4["notes"]


def test_overlaps_close_in_space_or_time_between_different_plans(report):
    cats = report["summary"]["by_category"]
    assert cats == {"both": 1, "near": 3, "same_time": 3} and report["summary"]["findings"] == 7
    f = by_projects(report, "TW-100", "TS-200")  # the water and sewer mains cross, scheduled together
    assert f["category"] == "both" and f["distance_m"] == 0 and f["shared_area_m2"] > 50
    assert f["overlap_days"] == 121 and f["window"] == ["2026-11-01", "2027-03-01"]  # both end dates count
    assert f["id"] == "F1" and f["county"]["listed"] is True and f["county"]["record_url"]
    near = by_projects(report, "TW-100", "TR-300")  # the road 30 m north, but in 2028
    assert near["category"] == "near" and 10 < near["distance_m"] < 20 and near["gap_days"] > 60
    assert any("days between the two schedules" in r and "starts 2028-01-01" in r for r in near["reasons"])
    same = by_projects(report, "TW-100", "TR-301")  # 800 m apart, the same months
    assert same["category"] == "same_time" and 700 < same["distance_m"] < 900 and same["overlap_days"] > 0
    assert by_projects(report, "TW-100", "TW-103") is None  # the same plan (WASD · Water): not two utilities
    assert by_projects(report, "TJ-500", "TJ-500") is None  # one joint project listed in two layers
    for f in report["findings"]:
        assert f["actions"] and f["geometry"]["type"] in ("Polygon", "MultiPolygon", "LineString", "GeometryCollection")


def test_the_county_cross_check_explains_both_directions(report):
    x = report["crosscheck"]
    assert x["county_pairs"] == 3
    assert x["our_intersecting"] == 2 and x["our_intersecting_confirmed"] == 1 and x["our_intersecting_not_listed"] == 1
    assert x["county_pairs_between_verified_projects"] == 2 and x["county_pairs_we_also_flag"] == 1
    assert x["county_pairs_same_project"] == 1 and x["county_pairs_we_do_not_flag"] == []
    assert x["county_pairs_with_excluded_project"] == {"status says the work is finished": 1}


def test_the_fact_sheet_holds_every_fact_and_the_grounding_check_catches_inventions(report):
    sheet = fact_sheet(report)
    assert sheet.startswith("[Verified utility-coordination analysis")
    assert "OFFLINE TEST FIXTURE" in sheet and "F1 —" in sheet and "TW-100" in sheet and "2026-11-01" in sheet
    assert "Published but empty right now" in sheet and "Gas Projects" in sheet
    # the totals are written out, so the answer never has to compute them
    assert "Records excluded: 5 — " in sheet and "Records that passed every check: 8, forming 7" in sheet
    assert "1 of those records is a further part of a project" in sheet
    assert "test@example.org" not in sheet  # no personal contact data goes to the model
    good = ("[confident] Two plans overlap. \n\n### What overlaps\n- F1: water TW-100 and sewer TS-200 intersect, "
            "together for 121 days (2026-11-01 → 2027-03-01).")
    assert grounding_check(good, sheet) == {"ok": True, "checked": grounding_check(good, sheet)["checked"], "unknown": []}
    bad = "F1 overlaps for 145 days from 2026-12-02, and F99 is also close."
    chk = grounding_check(bad, sheet)
    assert chk["ok"] is False and {"145", "2026-12-02", "F99"} <= set(chk["unknown"])
    assert "F7 —" in fact_sheet(report, top=1, mention="what about F7?")  # asked-about findings are added


def test_intent_in_english_and_russian():
    assert wants_analysis("Compare the utilities' construction plans and flag overlaps")
    assert wants_analysis("Where do the water main and FDOT roadway projects overlap?")
    assert wants_analysis("Сравни планы строительства коммунальных служб и найди пересечения")
    assert not wants_analysis("Explain recursion to me.")
    assert not wants_analysis("What is a hash table?")
    assert wants_refresh("re-run the analysis with fresh data") and not wants_refresh("compare the plans")


def test_the_mock_tutor_answers_from_the_sheet_word_for_word(report):
    sheet = fact_sheet(report)
    msgs = [{"role": "system", "content": "persona"}, {"role": "system", "content": sheet},
            {"role": "user", "content": "compare"}]

    async def collect():
        return "".join([c async for c in MockLLM(0).stream(msgs) if isinstance(c, str)])

    text = run(collect())
    assert "### What overlaps" in text and "F1 —" in text
    assert grounding_check(text, sheet)["ok"]


def client() -> TestClient:
    return TestClient(create_app(make_settings(), llm=FakeLLM(
        text="[confident] F1 is the big one. \n\n### What overlaps\n- F1: TW-100 and TS-200, together for 121 days."),
        vision=FakeVision()))


def test_a_chat_question_runs_the_analysis_and_answers_from_the_fact_sheet():
    with client() as c:
        sid = new_sid()
        r = c.post("/api/chat", json={"session_id": sid, "message": "Compare the utilities' construction plans and flag overlaps"})
        events = parse_sse(r.text)
        names = [n for n, _ in events]
        states = [d["state"] for n, d in events if n == "analysis"]
        assert states[0] == "running" and "progress" in states and states[-1] == "ready"
        assert names.index("analysis") < names.index("delta")  # the analysis comes before her answer
        ready = next(d for n, d in events if n == "analysis" and d["state"] == "ready")
        assert ready["findings"] == 7 and ready["offline"] is True
        meta = next(d for n, d in events if n == "meta")
        assert meta["analysis"]["mode"] == "run"
        done = next(d for n, d in events if n == "done")
        assert done["analysis"]["check"]["ok"] is True and done["analysis"]["report_id"] == ready["report_id"]
        llm = c.app.state.services.llm
        prompt = llm.requests[-1]
        assert any(m["role"] == "system" and m["content"].startswith("[Verified utility-coordination") for m in prompt)
        assert "Reply rules for this answer" in prompt[-2]["content"] and llm.max_tokens[-1] == 3000
        # a follow-up uses the analysis on screen — no new run
        r2 = c.post("/api/chat", json={"session_id": sid, "message": "Why does F1 matter?"})
        ev2 = parse_sse(r2.text)
        assert not [d for n, d in ev2 if n == "analysis"]
        assert next(d for n, d in ev2 if n == "meta")["analysis"]["mode"] == "context"
        assert "the learner asks about the utility-coordination analysis" in llm.requests[-1][-2]["content"]
        state = c.get(f"/api/session/{sid}/state").json()
        assert state["messages"][1]["analysis"]["check"]["ok"] is True  # kept with the answer
        # an ordinary question after closing the analysis is an ordinary answer again
        assert c.delete(f"/api/coord/report?session_id={sid}").json() == {"ok": True}
        c.post("/api/chat", json={"session_id": sid, "message": "Explain recursion to me."})
        assert not any(m["content"].startswith("[Verified utility-coordination") for m in llm.requests[-1])
        assert "Reply rules:" in llm.requests[-1][-2]["content"] and llm.max_tokens[-1] is None


def test_a_report_cut_at_the_length_limit_says_so():
    with client() as c:
        c.app.state.services.llm.script = ["length"]
        r = c.post("/api/chat", json={"session_id": new_sid(), "message": "x", "analysis": True})
        events = parse_sse(r.text)
        done = next(d for n, d in events if n == "done")
        text = "".join(d["text"] for n, d in events if n == "delta")
        assert done["finish_reason"] == "length" and "reached its length limit" in text
        assert done["analysis"]["check"]["ok"] is True  # the note adds no figures


def test_the_rest_api_catalog_analyze_report_recheck():
    with client() as c:
        sid = new_sid()
        cat = c.get("/api/coord/catalog").json()
        assert cat["region"].startswith("Miami-Dade") and len(cat["sources"]) == 14 and cat["status"]["offline"]
        assert c.get(f"/api/coord/report?session_id={sid}").status_code == 404
        rep = c.post("/api/coord/analyze", json={"session_id": sid, "distance_m": 10}).json()
        assert rep["params"]["distance_m"] == 10 and rep["summary"]["by_category"].get("near", 0) == 1  # only S1×R1 now
        assert c.get(f"/api/coord/report?session_id={sid}").json()["id"] == rep["id"]
        chk = c.post("/api/coord/recheck", json={"session_id": sid, "finding_id": "F1"}).json()
        assert chk["ok"] is True and all(r["found"] and r["changed"] == [] for r in chk["records"])
        assert c.post("/api/coord/recheck", json={"session_id": sid, "finding_id": "F999"}).status_code == 404
        assert c.post("/api/coord/analyze", json={"session_id": sid, "distance_m": -5}).status_code == 422


def test_a_failed_analysis_is_said_plainly_never_guessed():
    class Broken(CoordService):
        async def analyze(self, *a, **k):  # noqa: ANN002, ANN003
            raise RuntimeError("county service down")

    s = make_settings()
    llm = FakeLLM()
    app = create_app(s, llm=llm, vision=FakeVision(), coord=Broken(s))
    with TestClient(app) as c:
        r = c.post("/api/chat", json={"session_id": new_sid(), "message": "", "analysis": True})
        assert r.status_code == 422  # still needs a message
        r = c.post("/api/chat", json={"session_id": new_sid(), "message": "Run it", "analysis": True})
        events = parse_sse(r.text)
        err = [d for n, d in events if n == "analysis" and d["state"] == "error"]
        # not a county read failure: said as what it is
        assert err and err[0]["message"] == "the analysis failed on the server (RuntimeError)"
        assert any(m["content"].startswith("[Utility-coordination analysis — FAILED]") for m in llm.requests[-1])


def test_a_layer_that_cannot_be_read_falls_back_to_its_last_copy_and_says_so(tmp_path):
    from extrahorizon.coord.arcgis import FixtureClient, SourceError

    folder = Path(__file__).parent / "fixtures" / "coord"

    class Online(FixtureClient):  # the fixtures served like the live service, so good reads are saved
        offline = False

    class WaterDown(Online):
        async def attributes(self, src, *args):  # noqa: ANN001, ANN002
            if src.key == "UtilCoordWater":
                raise SourceError(src.key, "HTTP 503")
            return await super().attributes(src, *args)

    s = make_settings(cache_dir=tmp_path, coord_offline_dir=None)
    first = run(CoordService(s, client=Online(folder)).analyze())
    assert (tmp_path / "coord" / "UtilCoordWater.json").exists() and first["stale_note"] is None
    again = run(CoordService(s, client=WaterDown(folder)).analyze())
    assert again["summary"]["findings"] == first["summary"]["findings"] == 7  # the same verified data
    water = next(x for x in again["sources"] if x["key"] == "UtilCoordWater")
    assert "live read failed (HTTP 503); using the copy read at" in water["error"]
    assert "UtilCoordWater: live read failed" in again["stale_note"]
    assert "Note: UtilCoordWater: live read failed" in fact_sheet(again)  # she is told, and says so
    # without a copy the layer is reported as unreadable — never silently empty
    lost = run(CoordService(make_settings(cache_dir=tmp_path / "none", coord_offline_dir=None),
                            client=WaterDown(folder)).analyze())
    assert next(x for x in lost["sources"] if x["key"] == "UtilCoordWater")["error"] == "HTTP 503"
    assert lost["summary"]["projects_verified"] == 4  # S1 S3 · R1 R2
    sheet = fact_sheet(lost)
    assert "Could not be read now, so left out of this analysis: Water Projects (HTTP 503)." in sheet
    assert "Water Projects" not in sheet.split("Published but empty right now")[1].split("\n")[0]


def test_nothing_readable_is_a_failed_analysis_and_a_failed_read_is_retried_soon(tmp_path):
    from extrahorizon.coord.arcgis import FixtureClient, SourceError

    folder = Path(__file__).parent / "fixtures" / "coord"
    calls = {"water": 0}

    class Flaky(FixtureClient):
        offline = False
        down = {"UtilCoordWater"}

        async def attributes(self, src, *args):  # noqa: ANN001, ANN002
            if src.key == "UtilCoordWater":
                calls["water"] += 1
            if src.key in self.down or "*" in self.down:
                raise SourceError(src.key, "HTTP 503")
            return await super().attributes(src, *args)

    s = make_settings(cache_dir=tmp_path / "empty", coord_offline_dir=None)
    client = Flaky(folder)
    svc = CoordService(s, client=client)
    run(svc.analyze())
    run(svc.analyze())
    assert calls["water"] == 1  # within the minute: the same read
    svc._loaded_at -= dt.timedelta(seconds=61)
    client.down = set()
    rep = run(svc.analyze())
    assert calls["water"] == 2 and rep["summary"]["projects_verified"] == 7  # retried, recovered
    # the good read was saved: with every layer down the copies are used (and said to be copies)
    client.down = {"*"}
    assert "live read failed" in run(svc.analyze(refresh=True))["stale_note"]
    # every layer down and no saved copy: a failed analysis, never "0 projects"
    s = make_settings(cache_dir=tmp_path / "none", coord_offline_dir=None)
    svc = CoordService(s, client=client)
    with pytest.raises(SourceError, match="none of the county's layers could be read"):
        run(svc.analyze())
    app = create_app(s, llm=FakeLLM(), vision=FakeVision(), coord=svc)
    with TestClient(app) as c:
        sid = new_sid()
        assert c.post("/api/coord/analyze", json={"session_id": sid, "refresh": True}).status_code == 502
        events = parse_sse(c.post("/api/chat", json={"session_id": sid, "message": "Run it", "analysis": True}).text)
        err = next(d for n, d in events if n == "analysis" and d["state"] == "error")
        assert "none of the county's layers could be read (HTTP 503)" in err["message"]


def test_the_county_republishing_its_layers_changes_nothing(report):
    """The county rewrites its layers (seen live: new object IDs at 15:50 UTC). Finding IDs, links and the
    live re-check go by project ID, so a republished layer gives the same answer."""
    import copy

    from extrahorizon.coord.arcgis import FixtureClient

    folder = Path(__file__).parent / "fixtures" / "coord"

    class Republished(FixtureClient):  # other object IDs, other row order, same projects
        edits: dict[str, dict] = {}

        def _features(self, src):  # noqa: ANN001, ANN202
            feats = copy.deepcopy(super()._features(src))[::-1]
            for f in feats:
                f["properties"]["OBJECTID"] += 1000
                f["properties"].update(self.edits.get(f["properties"].get("PROJECTID"), {}))
            return feats

    svc = CoordService(make_settings(), client=Republished(folder))
    again = run(svc.analyze(Params(today=TODAY)))

    def pairs(rep):
        idx = {p["uid"]: p["project_id"] for p in rep["projects_index"]}
        return {f["id"]: (idx[f["a"]], idx[f["b"]]) for f in rep["findings"]}

    assert pairs(again) == pairs(report)  # the same finding IDs for the same pairs of projects
    w1 = next(p for p in report["projects_index"] if p["project_id"] == "TW-100")
    assert "PROJECTID%3D%27TW-100%27" in w1["record_url"] and "OBJECTID" not in w1["record_url"]
    f1 = next(f for f in report["findings"] if f["id"] == "F1")
    assert "CONFLTID1%3D%27TW-100%27" in f1["county"]["record_url"]
    # the re-check of the earlier report finds both projects in the republished layers, unchanged
    chk = run(svc.recheck(report, "F1"))
    assert chk["ok"] is True and all(r["found"] and r["changed"] == [] for r in chk["records"])
    assert chk["distance_m_live"] == 0.0
    # … and says so when a project no longer passes the checks
    Republished.edits = {"TW-100": {"GENPRJSTAT": "Complete"}}
    chk = run(svc.recheck(report, "F1"))
    assert chk["ok"] is False
    assert "no longer passes the checks: status says the work is finished" in chk["records"][0]["changed"]
    Republished.edits = {}


def test_inside_the_county_is_checked_against_its_own_boundary():
    from extrahorizon.coord.arcgis import FixtureClient, SourceError

    rep = run(CoordService(make_settings()).analyze(Params(today=TODAY)))
    assert rep["region"]["check"] == "the county's boundary" and not rep["stale_note"]
    assert {c["code"] for c in rep["boundary_source"]["checks"]} >= {"schema", "complete", "reference"}
    assert "TR-303" not in {p["project_id"] for p in rep["projects_index"]}  # Key Largo: in the box, not the county

    class NoBoundary(FixtureClient):
        async def boundary(self, src):  # noqa: ANN001, ANN201
            raise SourceError(src.key, "HTTP 503")

    fb = run(CoordService(make_settings(), client=NoBoundary(Path(__file__).parent / "fixtures" / "coord"))
             .analyze(Params(today=TODAY)))
    assert fb["region"]["check"] == "a bounding box" and "bounding box" in fb["stale_note"]
    assert "TR-303" in {p["project_id"] for p in fb["projects_index"]}  # said, not hidden
    assert "checked against a bounding box" in fact_sheet(fb)


def test_with_the_analysis_turned_off_a_request_is_answered_plainly():
    app = create_app(make_settings(coord_enabled=False), llm=FakeLLM(), vision=FakeVision())
    with TestClient(app) as c:
        assert c.get("/api/health").json()["coord"] == {"enabled": False, "offline": False}  # the UI hides its buttons
        assert c.get("/api/coord/catalog").status_code == 404
        events = parse_sse(c.post("/api/chat", json={"session_id": new_sid(), "message": "Where do the utilities' "
                                                      "construction plans overlap?"}).text)
        err = next(d for n, d in events if n == "analysis" and d["state"] == "error")
        assert err["message"] == "the analysis is not enabled on this server"
        assert any(m["content"].startswith("[Utility-coordination analysis — FAILED]")
                   for m in c.app.state.services.llm.requests[-1])


def test_only_questions_about_the_utilities_start_the_analysis():
    from extrahorizon.coord.intent import about_analysis, wants_rerun

    for q in ["Where do the utilities' construction plans overlap?", "Which utilities overlap the most?",
              "Compare the public construction plans of WASD and FDOT", "Сравни планы строительства коммунальных служб",
              "Где пересекаются работы водопровода и дорожные работы?"]:
        assert wants_analysis(q), q
    # ordinary tutoring questions never start it (found in review)
    for q in ["Compare the construction of a binary heap with sorting", "What is a utility function? Compare two plans",
              "Explain infrastructure as code and plan a deployment", "k-d tree construction for nearest neighbor",
              "Analyze the time complexity of this construction", "Сравни строительство кучи и сортировку",
              "How do sewers work?", "Как работает канализация?"]:
        assert not wants_analysis(q), q
    assert about_analysis("Why does F1 matter?") and about_analysis("what about the county list")
    assert not about_analysis("What is the F1 score in machine learning?")
    assert not about_analysis("Explain recursion to me.")
    assert wants_rerun("Compare them again") and wants_rerun("обнови анализ") and not wants_rerun("Why F1?")


def test_an_open_analysis_does_not_take_over_ordinary_questions():
    with client() as c:
        sid = new_sid()
        c.post("/api/chat", json={"session_id": sid, "message": "", "analysis": True})
        parse_sse(c.post("/api/chat", json={"session_id": sid, "message": "Compare the utilities' plans",
                                             "analysis": True}).text)
        mode = lambda text: next(d for n, d in parse_sse(c.post(  # noqa: E731
            "/api/chat", json={"session_id": sid, "message": text}).text) if n == "meta")["analysis"]
        assert mode("Explain recursion to me.") is None  # tutoring as usual, analysis still on screen
        assert mode("Why does F1 matter?")["mode"] == "context"
        assert mode("Which utilities overlap the most?")["mode"] == "context"  # answered, not re-run
        assert mode("Compare the utilities' plans again")["mode"] == "run"
        # the stored answer keeps the result card's summary (restored after a reload)
        msgs = c.get(f"/api/session/{sid}/state").json()["messages"]
        assert msgs[1]["analysis"]["live"]["state"] == "ready" and msgs[1]["analysis"]["live"]["findings"] == 7


def test_rules_are_validated_and_kept_only_when_they_worked():
    with client() as c:
        sid = new_sid()
        assert c.post("/api/coord/analyze", json={"session_id": sid, "area_m": 0}).status_code == 422
        assert c.post("/api/coord/analyze", json={"session_id": sid, "distance_m": 10}).status_code == 200
        svc = c.app.state.services.coord
        real = svc.analyze

        async def broken(*a, **k):  # noqa: ANN002, ANN003
            from extrahorizon.coord.arcgis import SourceError
            raise SourceError("all", "down")

        svc.analyze = broken
        try:
            assert c.post("/api/coord/analyze", json={"session_id": sid, "distance_m": 999}).status_code == 502
        finally:
            svc.analyze = real
        rep = c.post("/api/coord/analyze", json={"session_id": sid}).json()
        assert rep["params"]["distance_m"] == 10  # the failed run did not change the session's rules
    # a zero area from the environment is clamped, never a crash
    rep = run(CoordService(make_settings(coord_area_m=0)).analyze())
    assert rep["params"]["area_m"] == 1.0


def test_the_panel_lists_every_pair_and_every_highlighted_finding(monkeypatch):
    import extrahorizon.coord.service as service

    monkeypatch.setattr(service, "MAX_FINDINGS", 1)
    monkeypatch.setattr(service, "PER_PAIR_FINDINGS", 1)
    rep = run(CoordService(make_settings()).analyze(Params(today=TODAY)))
    listed = {f["id"] for f in rep["findings"]}
    assert rep["findings_total"] == 7 and set(rep["highlights"]) <= listed
    for pair in rep["pairs"]:  # no pair in the picker is empty
        assert any(sorted(f["plans"]) == pair["plans"] for f in rep["findings"])
    sheet = fact_sheet(rep, mention="and F99? and F7?")
    assert f"Listed in the panel: the {len(listed)} strongest of the 7 findings" in sheet
    assert "Asked about F99: there is no F99 in this analysis (F1–F7)." in sheet


def test_grounding_catches_units_written_dates_percentages_and_names_numbers():
    sheet = ('Rules: close = footprints within 150 m (0 m = they intersect). Findings: 586 in total.\n'
             'F26 — DTPW · Stormwater "NW 62 Ave From NW 7 St" (project 20250158-1-73118, Construction, 2026-07-01 → '
             '2027-03-01) ↔ FDOT · Roadway "SR 826/PALMETTO XWAY" (project 455134.3, Pre-Engineering, 2026-07-01 → '
             '2030-06-30): 110 m apart; Scheduled together for 244 days (2026-07-01 → 2027-03-01).\n'
             'F3 — WASD · Sewer "20068 - 48-inch Force Main" (project 20068, Design, 2024-02-05 → 2027-05-20)')
    good = ("F26: the NW 62 Ave project and SR 826 are 110 m apart, together 244 days (2026-07-01 → 2027-03-01); "
            "project 20068 is a 48-inch main; 586 findings; it starts July 1, 2026.")
    assert grounding_check(good, sheet)["ok"] is True
    for bad, flagged in [("F26 is 62 m apart", "62"), ("90m apart", "90"), ("shared 2,426m²", "2,426"),
                         ("3km away", "3"), ("on March 5, 2027", "March 5, 2027"), ("by May 2029", "May 2029"),
                         ("from 2026-11-04T00:00", "2026-11-04"), ("see f999", "F999"), ("80% of them", "80%")]:
        chk = grounding_check(bad, sheet)
        assert chk["ok"] is False and flagged in chk["unknown"], (bad, chk)
    assert grounding_check("2 findings, list item 3", sheet)["checked"] == 0  # small counts are not figures


def test_finished_and_stopped_statuses_are_read_exactly():
    from extrahorizon.coord.verify import record_verdict, status_class

    for v in ["Completed", "Const.Complete", "08- Final Completion", "10- Administrative C", "11- Closed",
              "Line Item Completed", "6-Complete", "6-Close-Out", "Complete"]:
        assert status_class(v) == "finished", v
    assert status_class("Dropped/Transferred") == status_class("Inactive") == "stopped"
    for v in ["Incomplete", "Design Complete", "07- Construction", "7-On-Hold", "Under Construction", ""]:
        assert status_class(v) is None, v
    d = dt.date
    row = {"PROJECTID": "X1", "GENPRJSTAT": "Pre-Engineering", "AGYPRJSTAT": "Dropped/Transferred"}
    assert record_verdict(row, TODAY, d(2026, 1, 1), d(2030, 1, 1), None)[0] == "stopped_status"
    row["AGYPRJSTAT"] = "Incomplete"
    assert record_verdict(row, TODAY, d(2026, 1, 1), d(2030, 1, 1), None)[0] is None


def test_a_county_pair_with_two_excluded_projects_is_counted_once():
    from extrahorizon.coord.crosscheck import cross_check

    pairs = {frozenset({("UtilCoordWater", "A"), ("UtilCoordRoadway", "B")}): {"object_id": 1}}
    excluded = {("UtilCoordWater", "A"): "status says the work is finished",
                ("UtilCoordRoadway", "B"): "end date already passed"}
    x = cross_check([], pairs, set(), excluded, "https://example.org/layer")
    assert x["county_pairs_with_excluded_project_total"] == 1
    assert sum(x["county_pairs_with_excluded_project"].values()) == 2


def test_schedule_days_count_both_end_dates():
    from types import SimpleNamespace

    from extrahorizon.coord.overlap import temporal

    d = dt.date
    p = lambda a, b: SimpleNamespace(start=a, end=b)  # noqa: E731
    assert temporal(p(d(2026, 9, 1), d(2026, 9, 30)), p(d(2026, 9, 30), d(2026, 12, 1)))[0] == 1  # one shared day
    assert temporal(p(d(2026, 9, 24), d(2026, 9, 30)), p(d(2026, 9, 1), d(2027, 1, 1)))[0] == 7
    assert temporal(p(d(2026, 9, 1), d(2026, 9, 30)), p(d(2026, 10, 1), d(2026, 12, 1)))[0] == 0  # back to back
    assert temporal(p(d(2026, 9, 1), d(2026, 9, 30)), p(d(2026, 10, 3), d(2026, 12, 1)))[0] == -2  # 2 days between


def test_a_stopped_analysis_turn_says_the_analysis_is_not_coming():
    """Found in review: Stop / a newer question during the analysis left the panel "running" forever."""

    class Slow(CoordService):
        async def analyze(self, *a, **k):  # noqa: ANN002, ANN003
            await asyncio.sleep(0.6)
            return await super().analyze(*a, **k)

    s = make_settings()
    app = create_app(s, llm=FakeLLM(), vision=FakeVision(), coord=Slow(s))
    with TestClient(app) as c:
        sid = new_sid()
        import concurrent.futures as cf

        with cf.ThreadPoolExecutor(1) as pool:
            fut = pool.submit(lambda: c.post("/api/chat", json={"session_id": sid, "message": "x", "analysis": True}))
            import time as _time

            _time.sleep(0.25)
            assert c.post("/api/session/interrupt", json={"session_id": sid}).json()["stopped"] is True
            events = parse_sse(fut.result(timeout=10).text)
        states = [d["state"] for n, d in events if n == "analysis"]
        assert states[0] == "running" and states[-1] == "cancelled"
        assert c.get(f"/api/coord/report?session_id={sid}").status_code == 404  # nothing half-done was kept


def test_only_the_spoken_summary_of_a_report_is_voiced():
    from extrahorizon.turns import Speaker

    sent: list[str] = []

    class TtsSession:
        async def send(self, text):
            sent.append(text)

        async def finish(self):
            sent.append("<finish>")

    class Plan:
        turn_no = 1

    sp = Speaker.__new__(Speaker)
    Speaker.__init__(sp, None, None, Plan(), make_settings(), None, first_paragraph_only=True)
    sp.ok, sp.tts_session = True, TtsSession()

    async def go():
        for piece in ["[confident] Two plans overlap. ", "[smug] Details below.", "\n\n### What", " overlaps\n- F1 …"]:
            await sp.feed(piece)
        await sp.finish()

    run(go())
    spoken = "".join(x for x in sent if x != "<finish>")
    assert "Two plans overlap" in spoken and "Details below" in spoken and "###" not in spoken and "F1" not in spoken
    assert sent.count("<finish>") == 1
