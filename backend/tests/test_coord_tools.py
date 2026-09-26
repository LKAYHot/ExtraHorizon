"""She knows the whole analysis: spoken finding IDs, her look-up tools, the map following the conversation.

Found live: asked out loud "что пересекается на F сто сорок шесть?", she said F146 was "not in the summary"
while the panel listed it — speech-to-text had written the number as words, and she had no way to look it up.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from extrahorizon.app import create_app
from extrahorizon.context import ANALYSIS_AFTER_TOOLS_NOTE, ANALYSIS_LANGUAGE_NOTE
from extrahorizon.coord.overlap import Params
from extrahorizon.coord.refs import finding_ids, project_refs, with_ids
from extrahorizon.coord.report import fact_sheet
from extrahorizon.coord.service import CoordService
from extrahorizon.coord.tools import TOOL_SPECS, ToolRunner

from .conftest import FakeLLM, FakeVision, make_settings, new_sid, parse_sse

TODAY = dt.date(2026, 9, 26)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def report():
    return run(CoordService(make_settings()).analyze(Params(today=TODAY)))


def pid_finding(rep, a_pid: str, b_pid: str) -> dict:
    idx = {p["uid"]: p["project_id"] for p in rep["projects_index"]}
    return next(f for f in rep["findings"] if {idx[f["a"]], idx[f["b"]]} == {a_pid, b_pid})


# ---------------------------------------------------------------------- what a question points at
@pytest.mark.parametrize("text, ids", [
    ("Хорошо, что пересекается на F сто сорок шесть?", ["F146"]),
    ("Хорошо, F сто тридцать пять.", ["F135"]),
    ("эф сто тридцать пять", ["F135"]),
    ("F one forty-six please", ["F146"]),
    ("F one four six", ["F146"]),
    ("finding one hundred and three", ["F103"]),
    ("находка номер 12", ["F12"]),
    ("what about F146 and f-12", ["F146", "F12"]),
    ("F 7 and F 8", ["F7", "F8"]),
    ("What is the F1 score?", []),
    ("the effect of F on the result", []),
    # found in review: ordinary maths / physics / life must never point at a finding
    ("If F = 20 N and m = 4 kg, what is a?", []),
    ("What is f(2) if f(x) = x^2?", []),
    ("I got an F two times", []),
    ("the F-16 fighter jet", []),
    ("70 F 20 C", []),
    ("70°F outside", []),
    # …and a number that cannot be read completely gives no ID, not a different one
    ("на F сто сорок шестой", []),
    ("F сто сорока", []),
    ("F forty-sixth", []),
    ("F one and two", ["F1"]),
    ("F ten five", []),
    ("F 146, F 12", ["F146", "F12"]),
    ("F one oh five", ["F105"]),
])
def test_finding_ids_typed_or_spoken(text, ids):
    assert finding_ids(text) == ids


def test_the_prompt_gets_the_ids_written_out(report):
    assert with_ids("что на F сто сорок шесть?") == "что на F сто сорок шесть? [F146]"
    assert with_ids("what about F7?") == "what about F7?"  # already typed
    assert project_refs("and project TW-100?", report) == ["TW-100"]


def test_a_spoken_id_puts_that_finding_in_her_fact_sheet(report):
    last = f"F{report['findings_total']}"
    words = {"F7": "F семь"}[last]
    sheet = fact_sheet(report, top=1, mention=f"а что на {words}?")
    assert "Asked about in this question:" in sheet and f"\n{last} — " in sheet
    assert "there is no F99 in this analysis" in fact_sheet(report, mention="and F ninety nine?")


# ---------------------------------------------------------------------- the tools themselves
def tools(report):
    events: list[tuple[str, dict]] = []
    svc = CoordService(make_settings())
    return ToolRunner(report, svc, lambda e, d: events.append((e, d))), events


def test_tool_specs_are_valid_openai_function_tools():
    names = {t["function"]["name"] for t in TOOL_SPECS}
    assert names == {"find_findings", "get_project", "show_on_map", "recheck_finding"}
    for t in TOOL_SPECS:
        assert t["type"] == "function" and t["function"]["parameters"]["type"] == "object"
        json.dumps(t)


def test_find_findings_by_id_text_plan_and_kind(report):
    t, events = tools(report)
    out = run(t.run("find_findings", json.dumps({"ids": ["F2", "f 999"]})))
    assert out.startswith("1 finding match F2") and "\nF2 — " in out and "No such finding in this analysis: F999" in out
    assert events[-1][0] == "focus" and events[-1][1]["ids"] == ["F2"]
    out = run(t.run("find_findings", json.dumps({"text": "county road resurfacing"})))
    assert "TR-301" in out and "match \"county road resurfacing\"" in out  # R2 by the words of its name
    out = run(t.run("find_findings", json.dumps({"plans": ["WASD Water", "FDOT"], "category": "near"})))
    assert out.startswith("2 findings match WASD Water & FDOT · close only")
    out = run(t.run("find_findings", json.dumps({"county_listed": True})))
    assert out.startswith("1 finding match on the county's list") and "TW-100" in out
    assert run(t.run("find_findings", json.dumps({"text": "no such street anywhere"}))).startswith("No findings match")
    assert run(t.run("find_findings", "not json")) == "error: the arguments were not valid JSON"
    assert [u["name"] for u in t.used].count("find_findings") == 5
    assert all(f in "\n".join(t.facts) for f in ("F2 — ", "TR-301"))  # facts for the grounding check


def test_get_project_show_on_map_and_recheck(report):
    t, events = tools(report)
    out = run(t.run("get_project", json.dumps({"query": "TW-100"})))
    assert '"TEST W1 water main replacement" (project TW-100' in out and "findings: 3" in out  # × S1, R1, R2
    focus = events[-1][1]
    assert focus["project"] and len(focus["ids"]) == 3
    assert run(t.run("show_on_map", json.dumps({"ids": ["F1"]}))) == "Shown on the learner's map: F1."
    out = run(t.run("recheck_finding", json.dumps({"id": "F1"})))
    assert out.startswith("F1 re-checked at the county's service just now") and "the finding still holds" in out
    assert ("recheck", "F1") in [(e, d.get("id")) for e, d in events]
    assert run(t.run("recheck_finding", json.dumps({"id": "F99"}))) == "No such finding in this analysis: F99."


def test_focus_carries_findings_the_panel_does_not_list(report, monkeypatch):
    import extrahorizon.coord.service as service

    monkeypatch.setattr(service, "MAX_FINDINGS", 1)
    monkeypatch.setattr(service, "PER_PAIR_FINDINGS", 0)
    rep = run(CoordService(make_settings()).analyze(Params(today=TODAY)))
    hidden = next(f["id"] for f in rep["_all_findings"] if f["id"] not in {x["id"] for x in rep["findings"]})
    t, events = tools(rep)
    run(t.run("show_on_map", json.dumps({"ids": [hidden]})))
    data = events[-1][1]
    assert data["ids"] == [hidden] and [f["id"] for f in data["findings"]] == [hidden]  # the map can draw it


# ---------------------------------------------------------------------- in a conversation
def chat(c, sid, message, **extra):
    return parse_sse(c.post("/api/chat", json={"session_id": sid, "message": message, **extra}).text)


def test_she_looks_things_up_and_the_map_follows():
    llm = FakeLLM(script=["ok", 'tools:[{"name": "find_findings", "arguments": {"text": "county road resurfacing"}}]',
                          "ok"], text="[calm] Found it: F6 is the county road resurfacing, TR-301.")
    app = create_app(make_settings(), llm=llm, vision=FakeVision())
    with TestClient(app) as c:
        sid = new_sid()
        chat(c, sid, "Compare the utilities' plans", analysis=True)
        ev = chat(c, sid, "Which overlaps involve the county road resurfacing?")
        names = [n for n, _ in ev]
        assert names.index("tool") < names.index("delta") and "focus" in names
        focus = next(d for n, d in ev if n == "focus")
        assert focus["source"] == "tool" and focus["ids"]
        done = next(d for n, d in ev if n == "done")
        assert done["analysis"]["tools"][0]["name"] == "find_findings"
        assert done["analysis"]["check"]["ok"] is True  # "TR-301" and "F6" come from her look-up
        assert llm.tools[-1] and llm.requests[-1][-2]["role"] == "tool"  # the second call saw the result
        assert "TR-301" in llm.requests[-1][-2]["content"]
        assert llm.requests[-1][-1] == {"role": "system", "content": ANALYSIS_AFTER_TOOLS_NOTE}  # …and the language
        # a spoken finding number moves the map before she says a word, and reaches her prompt as an ID
        ev = chat(c, sid, "а что на F семь?")
        first = next(d for n, d in ev if n == "focus")
        assert first == {**first, "ids": ["F7"], "source": "question"}
        assert [m["content"] for m in llm.requests[-1] if m["role"] == "user"][-1] == "а что на F семь? [F7]"
        assert llm.requests[-1][-1] == {"role": "system", "content": ANALYSIS_LANGUAGE_NOTE}  # asked in Russian
        sheet = next(m["content"] for m in llm.requests[-1] if m["content"] and m["content"].startswith("[Verified"))
        assert "\nF7 — " in sheet  # its details are in her fact sheet
        # the finding endpoint serves any finding (a click on an ID in her answer)
        assert c.get(f"/api/coord/finding?session_id={sid}&id=F7").json()["id"] == "F7"
        assert c.get(f"/api/coord/finding?session_id={sid}&id=F99").status_code == 404
        assert "_all_findings" not in c.get(f"/api/coord/report?session_id={sid}").json()


def test_the_map_follows_the_first_finding_she_names():
    llm = FakeLLM(text="[calm] F3 is the one to watch.")
    app = create_app(make_settings(), llm=llm, vision=FakeVision())
    with TestClient(app) as c:
        sid = new_sid()
        chat(c, sid, "Compare the utilities' plans", analysis=True)
        ev = chat(c, sid, "Which overlap matters most?")
        focus = next(d for n, d in ev if n == "focus")
        assert {k: focus[k] for k in ("ids", "label", "project", "source", "findings", "total")} == {
            "ids": ["F3"], "label": "F3", "project": None, "source": "answer", "findings": [], "total": 1}
        assert focus["report_id"]  # the browser drops a focus for a report it no longer shows


def test_her_answer_picks_a_finding_out_of_her_look_up():
    """Live: she looked up DTPW Paving (35 findings, the strongest first) and said "the closest is F138" while the
    map kept the strongest one selected. The finding she names is picked out of the spotlight, which stays."""
    look = 'tools:[{"name": "find_findings", "arguments": {"plans": ["DTPW Roadway"]}}]'
    llm = FakeLLM(script=["ok", look, "ok", look, "ok"])
    app = create_app(make_settings(), llm=llm, vision=FakeVision())
    with TestClient(app) as c:
        sid = new_sid()
        chat(c, sid, "Compare the utilities' plans", analysis=True)
        spot = next(d for n, d in chat(c, sid, "Which overlaps involve DTPW Roadway?") if n == "focus")
        assert spot["source"] == "tool" and len(spot["ids"]) >= 2
        other, second = next(i for i in ("F1", "F2", "F3", "F4") if i not in spot["ids"]), spot["ids"][1]
        llm.text = f"[calm] Unlike {other}, the closest one is {second}. [smug] Obviously."
        focus = [d for n, d in chat(c, sid, "Which DTPW Roadway overlap is the closest?") if n == "focus"]
        assert [(f["source"], f.get("within", False)) for f in focus] == [("tool", False), ("answer", True)]
        assert focus[1]["ids"] == [second]  # not the one she mentions in passing
        # a finding the learner asked about stays on the map, whatever else she names first
        llm.text = f"[calm] Unlike {other}, F7 is close."
        assert [d["ids"] for n, d in chat(c, sid, "а что на F семь?") if n == "focus"] == [["F7"]]


def test_she_answers_in_english_unless_asked_for_russian():
    # live: a Russian question followed by a look-up was answered in Russian; "Ответь по-русски" got English
    look = 'tools:[{"name": "find_findings", "arguments": {"ids": ["F7"]}}]'
    llm = FakeLLM(script=["ok", look, "ok", look, "ok"])
    app = create_app(make_settings(), llm=llm, vision=FakeVision())
    with TestClient(app) as c:
        sid = new_sid()
        chat(c, sid, "Compare the utilities' plans", analysis=True)
        chat(c, sid, "Хорошо, что пересекается на F семь?")
        assert llm.requests[-1][-1]["content"].startswith("[Your look-ups are above. Answer in English")
        assert "Answer in English" in next(m["content"] for m in llm.requests[-1] if "Reply rules" in str(m["content"]))
        chat(c, sid, "Ответь по-русски, пожалуйста: что с F семь?")
        assert "answer in Russian this time" in llm.requests[-1][-1]["content"]
        assert ANALYSIS_LANGUAGE_NOTE not in [m["content"] for m in llm.requests[-1]]  # no "answer in English" after it
        rules = next(m["content"] for m in llm.requests[-1] if "Reply rules" in str(m["content"]))
        assert "answer in Russian this time" in rules and "Answer in English" not in rules


def test_after_three_look_up_rounds_she_answers():
    look = 'tools:[{"name": "find_findings", "arguments": {"ids": ["F7"]}}]'
    llm = FakeLLM(script=["ok", look, look, look, look, "ok"], text="[calm] F7 it is.")
    app = create_app(make_settings(), llm=llm, vision=FakeVision())
    with TestClient(app) as c:
        sid = new_sid()
        chat(c, sid, "Compare the utilities' plans", analysis=True)
        ev = chat(c, sid, "Which overlap is F7?")
        # the fourth call keeps the tools declared (the history holds tool calls) but off — and a provider that
        # asks for more anyway ends the look-ups there
        assert llm.tools[-4:] == [TOOL_SPECS, TOOL_SPECS, TOOL_SPECS, None]
        assert sum(1 for m in llm.requests[-1] if m.get("tool_calls")) == 3
        assert [n for n, _ in ev][-1] == "error"  # it had asked for a look-up instead of answering
        llm.script = ["ok", look, look, look, "ok"][1:]
        ev = chat(c, sid, "Which overlap is F7?")
        assert [n for n, _ in ev][-1] == "done" and llm.tools[-1] is None


def test_the_same_look_up_twice_is_one_tag(report):
    t, _ = tools(report)
    for args in ({"plans": ["DTPW Roadway"]}, {"plans": ["DTPW Roadway"]}, {"plans": ["DTPW Roadway"], "sort": "closest"}):
        run(t.run("find_findings", json.dumps(args)))
    assert [u["summary"] for u in t.used] == ["DTPW Roadway", "DTPW Roadway · closest first"]


def test_the_offline_tutor_uses_the_same_tools():
    app = create_app(make_settings(), vision=FakeVision())  # the labelled mock LLM
    with TestClient(app) as c:
        sid = new_sid()
        chat(c, sid, "Compare the utilities' plans", analysis=True)
        ev = chat(c, sid, "What overlaps with the county road resurfacing?")
        assert ("tool", "find_findings") in [(n, d.get("name")) for n, d in ev]
        text = "".join(d["text"] for n, d in ev if n == "delta")
        assert "TR-301" in text and next(d for n, d in ev if n == "done")["analysis"]["check"]["ok"] is True


# ---------------------------------------------------------------------- the OpenAI stream
def test_openai_tool_calls_are_assembled_from_the_stream():
    from extrahorizon.llm import OpenAIChat, StreamInfo, ToolCalls

    def chunk(content=None, calls=None, finish=None):
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=calls),
                                                        finish_reason=finish)])

    def call(i, cid=None, name=None, args=""):
        return SimpleNamespace(index=i, id=cid, function=SimpleNamespace(name=name, arguments=args))

    chunks = [chunk("Let me check."), chunk(calls=[call(0, "c1", "find_findings", '{"ids": ["F1')]),
              chunk(calls=[call(0, args='46"]}')]), chunk(calls=[call(1, "c2", "show_on_map", '{"ids":["F146"]}')]),
              chunk(finish="tool_calls")]

    class Stream:
        model = "gpt-test"

        def __aiter__(self):
            async def gen():
                for c in chunks:
                    yield c
            return gen()

        async def close(self):
            return None

    sent = {}

    class Completions:
        async def create(self, **req):
            sent.update(req)
            return Stream()

    llm = OpenAIChat(make_settings())
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))

    async def collect():
        return [x async for x in llm.stream([{"role": "user", "content": "x"}], tools=TOOL_SPECS)]

    out = run(collect())
    assert out[0] == "Let me check." and isinstance(out[1], ToolCalls) and isinstance(out[2], StreamInfo)
    assert out[1].calls == ({"id": "c1", "name": "find_findings", "arguments": '{"ids": ["F146"]}'},
                            {"id": "c2", "name": "show_on_map", "arguments": '{"ids":["F146"]}'})
    assert out[2].finish_reason == "tool_calls" and sent["tools"] == TOOL_SPECS and sent["tool_choice"] == "auto"


# ---------------------------------------------------------------------- found in the second review
def test_a_look_up_cannot_launder_invented_figures(report):
    from extrahorizon.coord.report import grounding_check

    t, _ = tools(report)
    answer = "F999 has 2426 records, starting 2027-03-15."
    sheet = fact_sheet(report)
    assert grounding_check(answer, sheet)["ok"] is False
    run(t.run("find_findings", json.dumps({"ids": ["F999"], "text": "2426 records 2027-03-15"})))
    run(t.run("show_on_map", json.dumps({"ids": ["F999"]})))
    chk = grounding_check(answer, sheet + "\n" + "\n".join(t.facts))
    assert chk["ok"] is False and {"F999", "2426", "2027-03-15"} <= set(chk["unknown"])


def test_text_search_needs_the_distinctive_words(report):
    t, _ = tools(report)
    for q in ("Nonexistentname Blvd", "Zzqx Ave", "Zzqx Road"):
        assert run(t.run("find_findings", json.dumps({"text": q}))).startswith("No findings match"), q
    assert run(t.run("get_project", json.dumps({"query": "Zzqx Road"}))) == 'No project of the analysis matches "Zzqx Road".'
    assert "TW-100" in run(t.run("find_findings", json.dumps({"text": "water main replacement"})))
    out = run(t.run("find_findings", json.dumps({"plans": ["Utility"]})))
    assert out.startswith("No plan of this analysis is called 'Utility'. The plans are: ")
    # a plan named in the text is the plan, not words in project names
    by_text = run(t.run("find_findings", json.dumps({"text": "DTPW Roadway"})))
    by_plan = run(t.run("find_findings", json.dumps({"plans": ["DTPW Roadway"]})))
    assert by_text.split(" match ")[0] == by_plan.split(" match ")[0] == "2 findings"
    assert by_text.startswith("2 findings match DTPW · Roadway (")  # the plan, not the words "DTPW Roadway"


def test_showing_a_project_without_findings_says_so(report):
    t, events = tools(report)
    out = run(t.run("show_on_map", json.dumps({"project_id": "TJ-500"})))  # the joint project far away
    assert out.endswith("It is on the map; it has no findings under these rules.")
    assert events[-1][1]["project"] and events[-1][1]["ids"] == []


def test_a_sliver_of_an_intersection_is_never_an_empty_geometry():
    from extrahorizon.coord.model import Project
    from extrahorizon.coord.overlap import find_overlaps
    from shapely.geometry import box

    d = dt.date
    mk = lambda uid, fac: Project(uid, "UtilCoordWater" if fac == "Water" else "UtilCoordRoadway", 1, uid, uid, "", "A",
                                  fac, "Design", "Design", d(2026, 10, 1), d(2027, 1, 1), None, "", "")  # noqa: E731
    lat, lon = 25.76, -80.30
    a = box(lon, lat, lon + 0.001, lat + 0.001)
    kinds = set()
    for width in (1e-8, 1e-7, 5e-7, 1e-6, 3e-6):  # overlaps from millimetres to ≈0.3 m
        b = box(lon + 0.001 - width, lat, lon + 0.002, lat + 0.001)
        f = find_overlaps([mk("A1", "Water"), mk("B1", "Roadway")], [a, b], Params(today=TODAY))[0]
        assert f.distance_m == 0 and f.geometry["coordinates"], width  # found live: F11 / F13 had []
        kinds.add(f.geometry["type"])
    assert "Point" in kinds  # the narrowest vanish at 0.5 m precision and become their point


def test_the_prompt_rules_match_what_each_turn_gets():
    from extrahorizon.context import ANALYSIS_FOLLOWUP_NOTE, ANALYSIS_REPLY_NOTE

    assert "find_findings" not in ANALYSIS_REPLY_NOTE and "find_findings" in ANALYSIS_FOLLOWUP_NOTE
    assert "Answer in English" in ANALYSIS_REPLY_NOTE and "Answer in English" in ANALYSIS_FOLLOWUP_NOTE


def test_a_confirmed_spoken_question_keeps_the_written_out_id():
    from extrahorizon.sessions import Session

    rep = run(CoordService(make_settings()).analyze(Params(today=TODAY)))

    async def go():
        s = Session("sid", make_settings())
        s.analysis = rep
        plan = s.plan_chat(message="а что на F семь", subject=None, source="voice", speculative=True)
        s.confirm_plan(plan, "А что на F семь?")
        return plan

    plan = asyncio.new_event_loop().run_until_complete(go())
    question = [m["content"] for m in plan.llm_messages if m["role"] == "user"][-1]
    assert plan.analysis["mode"] == "context" and question == "А что на F семь? [F7]"


def test_a_slow_look_up_is_stopped_with_the_turn_and_moves_nothing_after():
    import concurrent.futures as cf
    import time as _time

    class Slow(CoordService):
        async def recheck(self, report, finding_id):  # noqa: ANN001, ANN201
            await asyncio.sleep(3)
            return await super().recheck(report, finding_id)

    s = make_settings()
    llm = FakeLLM(script=["ok", 'tools:[{"name": "recheck_finding", "arguments": {"id": "F1"}}]', "ok"])
    app = create_app(s, llm=llm, vision=FakeVision(), coord=Slow(s))
    with TestClient(app) as c:
        sid = new_sid()
        chat(c, sid, "Compare the utilities' plans", analysis=True)
        with cf.ThreadPoolExecutor(1) as pool:
            fut = pool.submit(lambda: chat(c, sid, "Is F1 still true? Re-check it."))
            _time.sleep(0.4)
            t0 = _time.monotonic()
            c.post("/api/session/interrupt", json={"session_id": sid})
            ev = fut.result(timeout=10)
            assert _time.monotonic() - t0 < 2.0  # not after the 3 s look-up
        names = [n for n, _ in ev]
        assert "recheck" not in names and names[-1] in ("interrupted", "error")


def test_a_failed_tool_call_adds_no_tag():
    llm = FakeLLM(script=["ok", 'tools:[{"name": "find_findings", "arguments": "not json"}]', "ok"])
    app = create_app(make_settings(), llm=llm, vision=FakeVision())
    with TestClient(app) as c:
        sid = new_sid()
        chat(c, sid, "Compare the utilities' plans", analysis=True)
        ev = chat(c, sid, "Which overlaps involve the county road resurfacing?")
        assert "tool" not in [n for n, _ in ev]
        assert llm.requests[-1][-2]["content"] == "error: the arguments were not valid JSON"

