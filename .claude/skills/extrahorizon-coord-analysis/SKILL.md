---
name: extrahorizon-coord-analysis
description: The utility-coordination analysis in ExtraHorizon — reading Miami-Dade County's public Utility Coordination open data (Esri ArcGIS Online), verifying every record, flagging where two utilities' future construction projects are physically close or scheduled around the same time, the cross-check with the county's own conflict list, Rika's grounded report (fact sheet + grounding check) and the analysis panel (Leaflet map, findings, schedules, sources & checks). Use this whenever the work touches utilities, construction plans, overlaps, coordination, the map, findings F1…, backend/extrahorizon/coord/ or the Coord*/AnalysisPanel components — when she states a wrong number about the analysis, a layer "could not be read", the county's numbers look different, a re-check says "changed", the map is blank, when changing the rules (distance, window, area), the report wording or the fixtures, or when adding a data source or another county — even if the user only says "анализ", "пересечения", "почему F1?", "карта пустая" or "коммунальные службы".
---

# Utility-coordination analysis

What it does and why each rule exists: **`docs/ANALYSIS.md`** (sources, verification, method, cross-check,
grounding, limitations). Every message and field: **`docs/CONTRACT.md`** (`/api/coord/*`, the `analysis` event,
`meta.analysis` / `done.analysis`). Read the relevant part before changing behaviour.

## Where things live

| Concern | File |
|---|---|
| The county's layers, the conflict list, region, agency aliases, links by project ID | `backend/extrahorizon/coord/catalog.py` |
| ArcGIS REST client (paging, footprints by object IDs, a project's records by project ID) · fixture client | `coord/arcgis.py` |
| A record → `Project` (dates, agency canonicalisation, plan label) | `coord/model.py` |
| Dataset checks + record checks (exclusion reasons, notes) | `coord/verify.py` |
| Overlaps: local metric plane, STR-tree, categories, score, stable F-numbering, suggested actions | `coord/overlap.py` |
| The county cross-check in both directions | `coord/crosscheck.py` |
| Fact sheet (what she may say), grounding check, pairs, highlights | `coord/report.py` |
| Reading + cache (memory 6 h, last copy on disk, failed reads retried after 60 s), verify, assemble, live re-check | `coord/service.py` |
| "Is this question about the analysis?" (EN + RU) · refresh words | `coord/intent.py` |
| Report rules in her prompt · persona exception | `context.py` (`ANALYSIS_REPLY_NOTE`, `ANALYSIS_FOLLOWUP_NOTE`) |
| Analysis turns (run / context), progress events, 3,000-token budget, grounding stored with the answer | `sessions.py` (`plan_chat`, `analysis_messages`), `turns.py` (`_run_analysis`) |
| REST routes | `app.py` (`/api/coord/*`) |
| Panel, map, findings, schedules, sources · state · colours/format | `frontend/src/lib/components/AnalysisPanel.svelte`, `Coord*.svelte` · `app.svelte.js` (`runAnalysis`, `choosePair`, `selectFinding`, …) · `coord.js` |
| Synthetic TEST fixtures + their expected result | `backend/tests/fixtures/make_coord_fixtures.py` → `fixtures/coord/*.geojson`, `_meta.json` |

## Look at it

```powershell
cd backend
uv run python scripts/coord_report.py              # live county data: totals, every layer's checks, pairs
uv run python scripts/coord_report.py --sheet      # + the fact sheet exactly as her prompt gets it
uv run python scripts/coord_report.py --finding F1 # + one finding in full + a live re-check
uv run python scripts/coord_report.py --offline    # the TEST fixtures (what the tests expect)
```

In the app: **Coordination** in the chat header, or ask *"Where do the utilities' construction plans overlap?"*.
In the in-app browser pane, **mute the speaker toggle first** (her voice would play on the user's speakers). The
panel opens on the strongest finding and its pair; *Sources & checks* shows every layer's verification.

## Invariants (each is covered by `backend/tests/test_coord.py` or the e2e — keep them green)

1. **Nothing unverified**: every record passes the record checks or is excluded with a counted reason (statuses as
   whole values: "Incomplete" and "Design Complete" are not finished; "Dropped/Transferred" is stopped); "inside the
   county" is the county's own boundary polygon (the bounding box only as a labelled fallback); datasets carry their
   checks; a layer that cannot be read is *named as unreadable* (never "empty"); no readable layer → the analysis fails
   plainly; days count inclusively.
2. **She states only the fact sheet**: numbers, dates and IDs copied exactly, no arithmetic; every analysis answer gets
   the grounding check (numbers ≥ 10, ISO dates, F-IDs). If she needs a number, **add it to the sheet** (`report.py`)
   — never loosen the check. No contact e-mails / phone numbers in the sheet.
3. **Failures are said, never guessed**: a failed analysis → the FAILED sheet; a layer from the saved copy is labelled
   with its read time everywhere (panel, report, sheet).
4. **Test data is labelled**: fixtures show *TEST FIXTURE* in the panel, the chat card and the sheet; their publisher
   check fails on purpose; offline reads are never cached; tests never contact the county (`make_settings` sets
   `coord_offline_dir`; Playwright's server gets `EH_COORD_OFFLINE_DIR` and blocks map tiles).
5. **Project IDs, not object IDs**: the county republishes its layers (seen: new object IDs at 15:50 UTC on
   2026-09-26). Links, the county-list link, the live re-check and the F-numbering tie-breaks use plan + project ID.
6. **Two different plans only**; the same project in two layers is skipped; the suggested actions are general practice
   and worded as such.
6b. **It never takes over tutoring**: it runs only when asked (buttons, or a message naming the utilities and asking
   where they overlap — `intent.py`, strict on purpose); with an analysis open only messages *about* it are answered
   from it ("again / обнови" re-runs); ✕ closes it on the server. A turn that ends early sends `analysis: cancelled`;
   after the spoken summary, "okay" does not cut the written report and a real question keeps what was written.
6c. **Stays responsive**: the CPU part runs in a worker thread; a slow county read sends a heartbeat every 5 s; the
   camera frames resume when the camera panel comes back.
7. **Honest data-flow wording** in the privacy card, the Sources tab, README and `EXTERNAL_DEPENDENCIES.md`: ArcGIS
   (queries only), OpenAI (public facts), OpenStreetMap tiles (the viewer's browser, IP address).
8. **Colours**: the utility network blue `#3987e5`, the road work orange `#d95926` (`orderPair`), overlaps near-white,
   other plans gray, basemap gray — validated with the dataviz skill's `validate_palette.js`; re-validate if changed.

## Debugging recipes

- **"not in the verified data: 2426"** under her answer → `coord_report.py --sheet`: is the number derivable from the
  sheet (a sum/difference)? Add the total to the sheet and keep the rule "no new numbers". Is it a real invention?
  Tighten `ANALYSIS_REPLY_NOTE`, then re-run live and read the grounding tag.
- **A layer "could not be read"** → open `https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services/<Layer>_gdb/FeatureServer/0?f=json`;
  the copy in `backend/cache/coord/` covers it (labelled); failed reads retry after 60 s; **Read the county's data
  again** forces it.
- **Numbers differ from yesterday / F1 moved** → the county edits and republishes; check each layer's `fresh` check
  and `editingInfo`; the findings order is stable for the same data.
- **Re-check says "changed"** → the county changed that project (status / dates) or it no longer passes the checks —
  that is the point of the button; the fact sheet of the current report is still the one she uses.
- **Map without streets** → the browser cannot reach `tile.openstreetmap.org` (network requests in the pane); data
  layers still draw. **Map framed wrongly** → `fit()` in `CoordMap.svelte` (selected finding → its two projects; else
  the pair's projects; refit when the container size changes).
- **Panel empty after a reload** → `GET /api/coord/report` 404 = the session has no analysis (backend restarted →
  new `boot_id`).

## Changing things

- **Rules**: `EH_COORD_DISTANCE_M` / `_WINDOW_DAYS` / `_AREA_M` or the panel's Rules form; update the numbers in
  `docs/ANALYSIS.md` if the defaults change.
- **Report wording**: `context.py` notes + `report.py` sheet; keep `test_coord.py` green, then one live run and read
  the answer and its grounding tag.
- **A new source or county**: `catalog.py` (Source, required fields, aliases, region bbox), fixtures + expected result,
  `test_coord.py`, e2e expectations, `docs/ANALYSIS.md`, `EXTERNAL_DEPENDENCIES.md` (who serves it, terms, what it sees).
- **Fixtures**: edit `make_coord_fixtures.py`, run it (`uv run python tests/fixtures/make_coord_fixtures.py`), update
  `test_coord.py` and `frontend/e2e/analysis.spec.js`; keep `_as_of`.

## Tests

`cd backend && uv run pytest tests/test_coord.py` (verification, overlaps, cross-check, sheet + grounding, intent,
analysis turns, REST, failures, copies, republished layers, cut report, voiced summary) ·
`cd frontend && npx vitest run src/lib/coord.test.js` · `npx playwright test --project=analysis` (needs a fresh
`npm run build`). Then the full `.\scripts\test.ps1 -E2E`.
