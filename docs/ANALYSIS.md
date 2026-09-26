# Utility-coordination analysis

ExtraHorizon can compare the **public future construction plans of the utilities and road agencies in
Miami-Dade County, Florida** and flag where their planned work overlaps — because two projects are
**physically close**, because they are **scheduled around the same time**, or both. When utilities
coordinate nearby projects they can share labour, equipment, one excavation, detours and surface
restoration instead of digging up the same street twice.

Ask Rika in the chat or by voice (*"Where do the utilities' construction plans overlap?"*, *"Сравни планы
строительства коммунальных служб"*), click the example button, or open **Coordination** and press
**Compare the utilities' plans**. The analysis runs on the server, then she explains it — the first
paragraph out loud, a detailed written report below — and the panel shows the map, the findings, the
schedules and every source with its checks.

Everything below is implemented in `backend/extrahorizon/coord/` and `frontend/src/lib/components/Coord*.svelte`;
the HTTP/SSE contract is in `docs/CONTRACT.md`. `backend/scripts/coord_report.py` prints any of it from the
command line.

---

## 1. Where the data comes from

**Miami-Dade County's Utility Coordination open data** — ArcGIS Online organisation `8Pc9XBTAsYuxx9Ny`,
published by the county's account **MDPublisher**, read live from
`https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services/…/FeatureServer/0`:

| Layer | Plan (agency · facility) in today's data | Utility network? |
|---|---|---|
| UtilCoordWater, UtilCoordSewer, UtilCoordReclaimed | WASD (Water and Sewer Department) · Water / Sewer / Reclaimed | yes |
| UtilCoordStormwater | DTPW (Transportation and Public Works) · Stormwater | yes |
| UtilCoordPower, UtilCoordGas, UtilCoordCable | power, gas, telecom | yes — **published but empty** today |
| UtilCoordRoadway, UtilCoordPaving | FDOT · Roadway, DTPW · Roadway / Paving, cities | right-of-way work |
| UtilCoordBridge, UtilCoordTransit, UtilCoordCanal, UtilCoordMiscellaneous, UtilCoordMoratorium | bridges, transit, canals, other, moratoria | right-of-way work (several empty today) |
| **PotentialConflictProject** ("Potential Collaboration Project") | the county's own list of project pairs its coordination system found overlapping | used only to cross-check (§4) |
| **MiamiDadeBoundary** ("Miami-Dade Boundary") | the county's own boundary polygon | used only for "inside the county" (§2) |

All project layers share one schema (`PRJNAME`, `PROJECTID`, `PRJSCOPE`, `AGCYNAME`, `FACTYPE`, `GENPRJSTAT`,
`AGYPRJSTAT`, `STARTDATE`, `ENDDATE`, `UPDATDATE`, contact fields). Each layer's ArcGIS item metadata
(owner, access, modified) comes from `https://www.arcgis.com/sharing/rest/content/items/<id>`.

**How it is read** (`coord/arcgis.py`): layer info, item metadata and the record count; all attributes
(pages of 1,000); then footprints in WGS84 (`outSR=4326`, 6 decimals) only for records that pass the
record checks (POST by object IDs, 100 at a time); the boundary polygon generalised to ≈30 m. The result is
kept in memory for 6 hours (`EH_COORD_CACHE_TTL_S`); a read where some layer failed is tried again after a
minute; "Read the county's data again" forces a fresh read. The last good copy of each layer is saved to
`backend/cache/coord/` (git-ignored) and used **only** when a live read fails — the report then says which
layer came from the copy and when it was read. A layer that cannot be read and has no copy is named as
unreadable (never "empty"); if no project layer can be read, the analysis fails plainly. The CPU part
(verify, compare, cross-check) runs off the server's event loop, so voice and camera keep flowing meanwhile.

**Today's live result** (2026-09-26 12:52, after the county republished its layers at 11:50): 2,815 records in 14
layers, all received; **386 verified future or ongoing projects in 7 plans** — FDOT · Roadway 299, WASD · Water 48,
WASD · Sewer 23, DTPW · Roadway 7, DTPW · Paving 6, DTPW · Stormwater 2, WASD · Reclaimed 1. Power, Gas, Cable,
Bridge, Transit and Moratorium were published but had no records. So the utilities actually compared are WASD's
water, sewer and reclaimed-water networks and DTPW's stormwater, against each other and against FDOT's and DTPW's
road work.

## 2. Verification — every dataset, every record

Nothing enters the analysis unchecked (`coord/verify.py`); everything excluded is counted by reason and
shown per layer in **Sources & checks**.

**Dataset checks** (per layer, the conflict list and the boundary too): `publisher` — the ArcGIS item's owner is
MDPublisher and it is public; `https` — read over HTTPS from the county's service; `schema` — the expected fields
exist; `complete` — records received = the count the service reports; `fresh` — the layer was edited in the last
30 days (the boundary is a static `reference` layer, last edited 2018-11-13).

**Record checks** — a record becomes a project only if it has:

| Check | Excluded as | Today |
|---|---|---|
| a project ID | no project ID | 0 |
| both dates | start or end date missing | 0 |
| start ≤ end | start date after the end date | 0 |
| plausible years (1990–2060) | placeholder or impossible dates (e.g. 1899-12-31) | 161 |
| a status that is not finished — whole values after the agency's step number: Complete(d), Const.Complete, "08- Final Completion", "10- Administrative C", Closed, "6-Close-Out", Line Item Completed (never "Incomplete" or "Design Complete") | status says the work is finished | 647 |
| a status that is not stopped: Dropped/Transferred, Inactive, Cancelled | status says the work was dropped, transferred or is inactive | 4 |
| an end date not in the past | end date already passed | 1,563 |
| a footprint that exists and can be repaired if self-intersecting (`make_valid`) | no footprint / cannot be repaired | 0 |
| a footprint that reaches into the county's **own boundary polygon** (≈100 m tolerance) — not just its bounding box: FDOT's Key Largo work lies inside the box, 10 km outside the county | outside the county (e.g. FDOT work in the Florida Keys) | 41 |

2,416 records are excluded; the other **399 pass every check and form 386 projects** — 13 records are
further parts of a project published as several features (the same agency and project ID in one layer),
merged into one project (union of the footprints, earliest start, latest end). Non-fatal notes are kept
too: agency names spelled two ways ("City of Miami - RPW") are merged with their department; a "finished"
status with an end date still ahead is excluded *to be safe*; records not updated for a year are marked. If
the boundary layer cannot be read, the bounding box is used instead and every report says so.

## 3. How overlaps are found

`coord/overlap.py` — deterministic and exact:

* Footprints are projected to a local metric plane at 25.76° N (WGS84 ellipsoid radii; < 0.5 % scale error
  across the county) and indexed with an STR-tree; every candidate pair is measured with GEOS (shapely).
* Only pairs from **two different plans** (agency · facility) count. Two WASD water projects are one
  utility's own business; the same project listed in two layers (same agency and project ID) is skipped.
* **Close** — footprints within `EH_COORD_DISTANCE_M` (150 m); 0 m = they intersect, and the shared area is
  measured. **Same time** — the schedules overlap or are at most `EH_COORD_WINDOW_DAYS` (60) days apart. Days
  count **inclusively** (an end date is a working day): two schedules that share one date are "together 1 day";
  projects that follow each other without a free day are "back to back".
* **Close + same time** (`both`) — the strongest case for coordinating now. **Close** (`near`) — at different
  times: sequence the work so the later project does not redo the earlier one. **Same time** (`same_time`) —
  flagged only within `EH_COORD_AREA_M` (1,500 m, a shared crew or staging-yard radius; at least 1 m); county-wide
  "same time" would flag everything.
* Findings are ranked (category first, then closeness, days together, and a penalty for long gaps), ties broken
  by plan and project ID, and numbered F1, F2, … Each carries the overlap geometry (shared area or the shortest
  line between the two), the days together or the days between them, and **suggested coordination** by
  combination — e.g. water/sewer pipes with road or paving work: *"Put the pipe work before the road or paving
  work: one excavation, no cutting of new pavement."* These suggestions are general practice, never facts from
  the data, and are worded that way.
* The panel lists the 300 strongest findings plus the 25 best of every pair of plans and every finding her fact
  sheet highlights (today 384 of 583), and says so; no pair in the pair picker is empty.

The rules can be changed in **Sources & checks → Rules**; the analysis is recomputed on the same verified data
(rules are remembered for the session only once they produced an analysis).

Today: **583 findings** — 144 close + same time, 2 close, 437 same time nearby. Most are between FDOT's road
corridors and WASD's water (325) and sewer (158) plans; WASD's own water ↔ sewer plans overlap 16 times.

## 4. Cross-check with the county's own list

The county publishes the pairs of projects its coordination system found overlapping (194 pairs today).
`coord/crosscheck.py` compares in both directions:

* Of our pairs with **intersecting** footprints, **64 of 80** are on the county's list; the other 16 are
  marked *"not in county list"* in the findings so a coordinator can look at them.
* Of the county's pairs between two projects we verified, we flag **64 of 66**; the other 2 pair one project
  with itself across two layers (which we skip by design). County pairs we would not flag under the current
  rules are counted and named as such — never explained away.
* **128** county pairs involve a project we excluded; by reason (a pair with two excluded projects counts under
  both): finished 61, ended 80 — the county's list still contains finished and past work.

## 5. Live re-check of one finding

**Re-check live** on a finding (`POST /api/coord/recheck`) reads both projects again from the county's service
**by project ID**, verifies the live records exactly like the analysis did (parts merged, the county's boundary),
compares status and dates and recomputes the distance: *"unchanged at the source · intersect"*, what changed,
*"no longer passes the checks: status says the work is finished"*, or — if the service does not answer — *"could
not re-check now"* (never "changed").

Why by project ID: the county **republishes its layers** — on 2026-09-26 at 15:50 UTC every layer's data and schema
were rewritten and the records got new object IDs. So nothing in ExtraHorizon depends on object IDs across reads:
record links are query pages by project ID, the county-list link queries the pair of project IDs, and findings are
numbered in a stable order (score, distance, then plan and project ID — never the service's row order or object IDs),
so the same data always gives the same F1, F2, …

## 6. In the dialogue — grounded answers

* **When it runs** (`coord/intent.py`, strict on purpose): the buttons, or a message that names the utilities
  (their networks, agencies or the county) *and* asks where they overlap or to compare/find/flag their plans —
  in English or Russian. Ordinary tutoring questions never start it ("compare the construction of a heap with
  sorting", "a utility function", "infrastructure as code", "как работает канализация?").
* **While an analysis is open**, a message about it (a finding ID like F12 — not the "F1 score" —, a project ID,
  the utilities, overlaps, the map, the county…) is answered from it without a new run; asking for it *again*
  ("compare them again", "обнови анализ") re-runs it; anything else is ordinary tutoring. **✕** in the panel
  closes the analysis; the header's *Coordination* button only switches panels.
* The analysis runs first (`analysis` events: running → progress, with a heartbeat every 5 s while the county's
  service is slow → ready | error | cancelled), then her answer streams. A spoken question runs it only after the
  final transcript confirms the question. If the turn is stopped or replaced meanwhile, the card and the panel
  say the analysis was stopped — nothing keeps spinning; the result card is stored with the answer, so it
  survives a page reload.
* She is given a **fact sheet** (`coord/report.py`) as a system message — the only facts she may state:
  the source and read time, record totals and exclusions by reason, empty or unreadable layers, the plans, the
  rules, finding counts, the county cross-check, findings per pair of plans, and the highlighted findings (the
  best of each pair of plans; plus any finding or project ID the question names — or a line saying there is no
  such finding) with plan, name, project ID, status, dates, distance or shared area, days together and
  county-list status. The reply rules ask for a short spoken summary and then a report in Markdown (*What
  overlaps · Which plans overlap most · Where the data comes from · Caveats*), copying numbers, dates and IDs
  exactly and never calculating new ones.
* **Grounding check** on every analysis answer (also a stopped one): numbers ≥ 10 — also with a unit ("90m",
  "2,426m²") and small numbers with a unit ("3 km", "5 days") —, dates in any common form ("2026-11-04",
  "2026-11-04T00:00", "March 5, 2027", "May 2029"), percentages (the sheet has none: she must not compute them)
  and finding IDs in any case must appear in the fact sheet. A number that is part of a project's name or ID
  counts only in that context ("SR 826", "48-inch", "project 20018") — "F26 is 62 m apart" is not grounded just
  because a street is called "NW 62 Ave". The answer shows *"N figures match the verified data"* or lists what is
  not in the data. During testing it caught a real slip: she computed "2,815 − 389 = 2,426 excluded", while 2,413
  records were excluded and 13 were merged parts — the sheet now states those totals and the rules forbid
  arithmetic.
* Only the first paragraph is voiced (Fish Audio) — the voice stops at the first line break. The written report
  can be up to 3,000 tokens (`EH_COORD_MAX_OUTPUT_TOKENS`, 150 s budget) and says so visibly if it is ever cut.
  While the rest is still being written, the learner's voice is not an interruption: *"okay"*, *"угу"* are
  ignored, and a real question keeps the report so far (marked interrupted, grounding-checked) and is answered.
* If the county's data cannot be read, the sheet says the analysis FAILED and she says so plainly; a server-side
  failure is said as one — she never guesses.

### She knows the whole analysis — not only the sheet (`coord/refs.py`, `coord/tools.py`)

Found live: asked out loud *"что пересекается на F сто сорок шесть?"*, she said F146 was "not in the summary" while
the panel listed it — speech-to-text had written the number as words, and she could see only the dozen findings of
her fact sheet. Now:

* **Finding numbers are read however they arrive** — "F146", "f-146", "F 146", "F сто сорок шесть", "эф сто
  тридцать пять", "F one forty-six", "finding one hundred and three", "находка 12" (English and Russian number
  words up to 9,999, digit by digit or in groups; "the F1 score" is not a finding). The finding's full details go
  into her fact sheet and the ID is written out in her prompt ("… F сто сорок шесть? [F146]").
* **Tools** (OpenAI function calling, in follow-up answers — the first report is written from the sheet, which
  already holds everything it covers): `find_findings` (any of the 583 findings — also those the panel does not
  list — by ID, by a project's ID, name, street or place, by plan or agency, by kind, by the county's list, with
  exact counts; sorted strongest / closest / most days together / largest shared area), `get_project` (a project
  and every finding it is part of), `recheck_finding` (reads both projects from the county's service now and
  verifies them again) and `show_on_map`. Up to three look-up rounds per answer; everything a tool returns counts as
  verified data for the grounding check; under her answer small tags say what she looked up ("looked up "Biscayne
  Blvd"", "looked up DTPW · Paving · closest first", "re-checked live F135: unchanged", "showed on the map …"; the
  same look-up twice is one tag). A search needs every distinctive word ("Zzqx Ave" finds nothing, not every
  avenue), and a plan named in the search text is that plan: "DTPW Paving" gives the plan's 35 findings, not the
  48 whose project names contain "Paving".
* **The map follows the conversation** (`focus` events): the finding a question names moves the map before she
  says a word (also spoken: "F сто сорок шесть"); what she looks up is spotlighted — the map frames those overlaps,
  the list shows just them, the pair picker switches to *All pairs of plans* if they span several (blue = utility
  networks, orange = road work), and a banner says what is shown with *Show all*. Her answer moves it too: with
  nothing on the map yet, the first finding she names is selected; after a look-up, the first of *its* findings she
  names is picked out of the spotlight, which stays ("the closest is F138" selects F138 among the 35 she looked up —
  live it had kept the strongest one selected); a finding she mentions only in passing, or anything after the
  learner asked about one finding, moves nothing. The map stays in view: the plan picker, her spotlight banner and
  the map stay at the top of the panel while the list scrolls under them, and the selected card comes in just below
  the map (live, a selection had scrolled the map out of sight). The selected card is always on the list (a
  *Sources* tab switches to *Findings*). A finding ID in her answer is a button — a click shows it (also one the panel does not list: it is
  fetched from the server).
* **She answers in English**, also to Russian questions — the rule opens her analysis rules, a question in Russian
  gets it once more as the last message after it, and it is repeated right after her look-ups (live, Russian
  questions had drawn Russian answers now and then, with and without a look-up). A message that asks
  for Russian ("Ответь по-русски", "на русском", "in Russian") gets Russian, with IDs, names and figures as written
  (her voice cues may then be Russian too; nothing inside a cue is spoken).
* Live check with the real model (2026-09-26): "Хорошо, что пересекается на F сто сорок шесть?" → F146 on the map
  and in the list before her answer, the answer in English with 4 figures, all grounded; "Is F135 still true right
  now?" → `recheck_finding` → "F135 still holds … unchanged, 37 m", the card shows the re-check; "What overlaps along
  Biscayne Blvd?" → `find_findings("Biscayne Blvd")`: 40 findings spotlighted, F18 (the one she describes) selected,
  11 figures grounded; "How many findings involve DTPW Paving, and which one is the closest?" → one look-up
  (*DTPW · Paving · closest first*): exactly 35, the closest F138 (72 m), F138 selected; "If F = 20 N and m = 4 kg…"
  → ordinary physics, the map stays. Five more questions in Russian (F146, DTPW Paving, Biscayne Blvd, "почему F135
  важна?", "какие планы пересекаются чаще всего?"), run twice → 10 of 10 answered in English, with and without
  look-ups; "Ответь по-русски, пожалуйста: что с F146?" → in Russian (2 of 2).

### The analysis is built on screen

While it runs, the panel shows the build step by step from the server's progress events — the county's 16 layers
arriving one by one with their record counts, then *Verifying every record*, *Comparing the utilities' plans*,
*Cross-checking with the county's own list*, each with a counter. When it is ready the numbers count up and the
map builds itself: the county first, then the projects are drawn along their outlines in a west-to-east sweep
(context, road work, utility networks), the overlaps light up, and the camera flies in to the finding she talks
about, where a ring pulses. Later changes only restyle or fly; with *reduce motion* set in the system, none of it
animates.

## 7. What leaves the computer

* **Server → Esri ArcGIS Online** (the county's services): only the queries; nothing about the learner.
* **Server → OpenAI:** the fact sheet and, in follow-ups, the results of her look-ups — public county records
  (project names, IDs, agencies, statuses, dates, measurements, counts) and the tool definitions. Contact e-mails
  and phone numbers in the records are never included (not even sent to the browser); the full list of findings
  stays on the server (`public_report`).
* **Browser → OpenStreetMap's tile servers** (`tile.openstreetmap.org`): map tiles for the visible area; the
  tile servers see the viewer's IP address and the page address (Referer). Map data © OpenStreetMap
  contributors (ODbL), shown on the map.

## 8. Limitations (said honestly)

* Dates and statuses are the agencies' plans as published; they change. Each layer's last edit is shown and
  checked; a finding can be re-checked live.
* Footprints are drawn by the agencies: FDOT's state-road corridors are long, so many "same time nearby"
  findings involve them. The distance and window are rules of thumb, adjustable in the panel.
* "Inside the county" uses the county's boundary generalised to ≈30 m with ≈100 m tolerance; a footprint that
  reaches into the county counts even if part of it lies outside.
* Six layers (power, gas, telecom, bridges, transit, moratoria) are empty today, so private utilities are not
  in the comparison until the county publishes them.
* Pairs inside one plan are skipped by design; the suggested actions are general practice, not the agencies'
  decisions.
* One county only (the data model is the county's). Everything else is out of scope.

## 9. Tests and offline mode

`EH_COORD_OFFLINE_DIR` points the service at local GeoJSON fixtures instead of the county: the synthetic
**TEST** data in `backend/tests/fixtures/coord/` (`make_coord_fixtures.py` documents the exact expected result:
7 projects, 7 findings — 1 close + same time, 3 close, 3 same time — plus every exclusion reason, a project inside
the bounding box but outside the (test) boundary, a merged multi-part project and the county cross-check), dated
as of 2026-09-26 so the result never drifts. Offline results are labelled *TEST FIXTURE* in the panel, the chat
card and the fact sheet, the publisher check fails on purpose, and nothing is cached. Tests:
`backend/tests/test_coord.py`, `backend/tests/test_coord_tools.py` (spoken IDs, the tools, the map following the
conversation, the offline tutor using the same tool, the OpenAI stream's tool calls), the voice-socket cases in
`backend/tests/test_live.py`, `frontend/src/lib/coord.test.js` + `markdown.test.js`, `frontend/e2e/analysis.spec.js`
(the e2e server always runs on the fixtures and blocks map tiles; it checks a spoken "F пять", a click on an ID in
her answer and a look-up spotlighted on the map).

## 10. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `EH_COORD_ENABLED` | `true` | the analysis routes, buttons and intent (off: the buttons are hidden and a request is answered with "not enabled") |
| `EH_COORD_OFFLINE_DIR` | — | read fixtures from this folder instead of the county (tests) |
| `EH_COORD_CACHE_TTL_S` | `21600` | keep the county's data in memory this long (a read with a failed layer: 60 s) |
| `EH_COORD_HTTP_TIMEOUT_S` | `30` | per request to the county's services |
| `EH_COORD_DISTANCE_M` | `150` | "close" |
| `EH_COORD_WINDOW_DAYS` | `60` | "same time" |
| `EH_COORD_AREA_M` | `1500` | "same time" alone is flagged within this distance (at least 1 m) |
| `EH_COORD_MAX_OUTPUT_TOKENS` | `3000` | the written report's length limit |
| `EH_COORD_LLM_TOTAL_TIMEOUT_S` | `150` | the written report's time limit (a spoken answer: `EH_LLM_TOTAL_TIMEOUT_S`) |
