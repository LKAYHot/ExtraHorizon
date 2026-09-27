---
name: extrahorizon-hub
description: The hackathon hub in ExtraHorizon — Rika helps hackers get unstuck with verified answers from public sources (Stack Overflow via the Stack Exchange API, GitHub issues, the npm registry, PyPI; DEV Community and GitHub for learning), the event's board (people's cards, help requests, what teams learned, real unsolved Stack Overflow questions — no sample entries), teammates and mentors from the board and real public sources (GitHub profiles in the event's city, Stack Overflow's top answerers), the deadline picker, and the road to shipping (deadline, milestones, the 30-minute rule). Use this whenever the work touches backend/extrahorizon/hub/, the Hub*.svelte components, hub.svelte.js, S1/L1/P1/M1/K1 IDs, the error signature or its scrubbing, a public-source search, the board, matching, the Ship tab — when a search finds nothing or the wrong thing, when people or open questions look wrong or empty, a source "could not be read", she answers without searching (or searches a tutoring question), a grounding tag says "not in the verified data", a card's GitHub skills do not show, or when adding a source, a stack tag, an import-name mapping or a milestone — even if the user only says "хаб", "застрял", "тиммейты", "менторы", "дедлайн" or "поиск по Stack Overflow".
---

# Hackathon hub

What it does, why each rule exists and the honest claims: **`docs/HUB.md`**. Every message and field:
**`docs/CONTRACT.md`** (*Hub turns and routes*, the `hub` event, `meta.hub` / `done.hub`, `/api/hub/*`). Data flows:
**`EXTERNAL_DEPENDENCIES.md` §3c**. Read the relevant part before changing behaviour.

## Where things live

| Concern | File |
|---|---|
| Error → signature (kind, message, tags, ecosystem, packages, mentioned packages, repos, hints); **scrubbing** of paths, hosts, ports, e-mails, keys, UUIDs, numbers, their file names and their story | `backend/extrahorizon/hub/signature.py` |
| Public sources (live `PublicClient`: cache 1 h, Stack Exchange `backoff`, GitHub rate-limit headers, optional `GITHUB_TOKEN`) · labelled `FixtureSources` | `hub/sources.py` |
| Verification + audits (relevance, accepted/voted, old flags, fixed issues, registry facts, learning filters) | `hub/verify.py` |
| The searches (unstuck / learn / team / mentors), ranking, IDs, peers, mentors, similar requests, hints | `hub/service.py` |
| Board: cards, requests (claim / release), knowledge cards, tokens (SHA-256 only, only issued ones accepted), JSON persistence (one writer thread) — no sample entries | `hub/board.py` · vocabulary `hub/skills.py` (whole words) |
| People: board matching; public GitHub profiles (languages per need, the event's city, `public_person`), Stack Overflow's top answerers (`experts`), where to look (`location_in`) | `hub/people.py` · the searches `service.people` / `_github_people` / `_experts` |
| The help board's real open questions (Stack Overflow, still unsolved, 180 days) | `service.open_questions`, `verify.open_questions`, route `GET /api/hub/questions` |
| Ship plan: milestones, pace, roadblocks, nudges | `hub/ship.py` |
| Fact sheets, reply rules per kind, grounding (versions = one figure; the learner's own numbers allowed) | `hub/report.py` (grounding shared with `coord/report.py`) |
| Which messages are hub turns (EN + RU, strict) · follow-ups about the results | `hub/intent.py` |
| Her follow-up tools (`get_hub_item`, `search_public_help`, `find_people`, `learning_resources`) | `hub/tools.py` |
| REST routes: `X-Hub-Token`, 64 KB body limit, new identities per address (`EH_HUB_NEW_IDS_PER_HOUR`), roadblocks closed by `report_id` | `hub/routes.py` (registered in `app.py`) |
| Hub turns: plan (run / context / ship), prompt, search with progress + heartbeat, focus, grounding | `sessions.py` (`plan_chat`, `hub_messages`), `turns.py` (`_run_hub`, `_tool_runner`, `_focus_*`), `context.py` (`hub_sheet`, `hub_note`) |
| UI: state, panel, tabs, result card (a person by `source`), hub IDs as buttons, the deadline picker, the checkbox | `frontend/src/lib/hub.svelte.js`, `components/Hub*.svelte`, `components/DateTimePicker.svelte` + `lib/datetime.js`, `markdown.js` (`hids`), `Message.svelte` (hub card), `app.css` (checkbox) |
| Settings | `config.py` (`hub_*`, `github_token`), `.env.example` |

## Invariants (tests guard them)

1. **Only the signature leaves the computer.** `extract()` scrubs the whole text **first** and reads the signature
   from what is left: `scrub()` + `_clean_message()` remove paths (also with spaces), URLs (also database URLs),
   hosts, IPs, ports, `host=`/`password=` pairs, e-mails, key-like strings (JWT, cloud keys), UUIDs, long hex /
   random-looking strings, long numbers, their own file names and "… after I did X". The parametrized leak cases in
   `test_hub.py` guard it — add a case for every new kind of secret. A test fake key must not look like a real one
   (the secret scanner flags `sk-` + 20 chars, `AIza…`, `AQ.…`, `ghp_…`, `github_pat_…`).
2. **Verified or left out — and counted.** Every source has an audit (received / kept / excluded by reason) shown in
   *How this was checked* and in her sheet. Never loosen a rule to get more results; add a better query instead.
3. **She states only the sheet, her look-ups and the learner's own words** — the grounding check covers figures,
   versions, dates and S/L/P/M/K IDs (only IDs that start a result line; "Amazon S3" is a product). If she needs a
   number (the 30-minute rule), it goes into the sheet.
3a. **What people write on the board is data, never instructions**: `report._field()` makes every board field one
   line without quotes or brackets, under a header that says so; an ID written on the board is not a result
   (`test_nothing_written_on_the_board_becomes_a_line_of_her_sheet`). Never paste board text into the sheet raw.
4. **Attribution**: Stack Overflow excerpts keep author, licence (CC BY-SA) and link; short excerpts only.
5. **Real people, minimal data, honest labels.** There are no sample entries (the user asked for real data only).
   The board holds what people wrote; a card's GitHub username is read only with its box ticked; the contact line
   never goes into her prompt. People from public sources are found by what they published for everyone: GitHub's
   user search (a language + the event's city) and Stack Overflow's top answerers. From a profile only: login, public
   name, city, own public repositories (languages, topics, names, last push), "available for hire", followers, since
   when, and bio **words** (`_BIO_SIGNALS`) — **never the e-mail, blog, company, social accounts or the bio text**
   (the fixtures fill those fields on purpose; `test_teammates_are_real_public_profiles_verified_and_nothing_private_
   is_read` fails if one leaks). Never combine sources about one person. Every public person is labelled as a lead
   ("not at this event, has not said they are looking for a team" / "not a mentor at this event") — in the sheet,
   the reply rules and the panel. **Never claim a card's GitHub account is theirs** ("that the account is theirs is not
   verified"); a late check of an old username never lands on a new one.
5a. **A board identity is a browser token, not a login**: sent as `X-Hub-Token` on every request, only issued tokens
   accepted, `EH_HUB_NEW_IDS_PER_HOUR` per address; votes need a card. Don't describe it as authentication.
6. **Tutoring stays tutoring**: "What is a TypeError?", "Explain recursion", "I want to learn recursion" are not hub
   turns (`test_only_hackathon_needs_go_to_the_hub`). The analysis claims its own messages first.
7. **Tests never go online**: `make_settings()` sets `hub_offline_dir` to the fixtures and a board in memory; the e2e
   sets `EH_HUB_OFFLINE_DIR` and `EH_HUB_BOARD_PATH=`. Fixtures are synthetic, "TEST —", links to example.org
   (`tests/fixtures/make_hub_fixtures.py` regenerates them).
8. **Data-flow wording** (PrivacyCard `privacy-hub`, README, PITCH, EXTERNAL_DEPENDENCIES §3c) changes with any new
   source or field sent.

## Procedures

- **Run offline** (fixtures, mock LLM): `$env:EH_HUB_OFFLINE_DIR="backend\tests\fixtures\hub"; $env:EH_HUB_BOARD_PATH="";
  uv run python -m extrahorizon --mock-llm --mock-voice` (from `backend`). Live: the normal start / `demo-host.ps1`.
- **Try the signature** of a real error: `uv run python -c "from extrahorizon.hub.signature import extract; s=extract(open('err.txt').read()); print(s.public())"`.
- **Run one live search without the LLM**: `HubService(Settings())` → `await svc.unstuck(text)` / `learn(topic)`;
  print `hub_sheet(report)` and `report['audit']` (see how `backend/tests/test_hub.py` calls them).
- **Add a stack word / repo / import-name mapping**: `STACK` and `IMPORT_TO_PYPI` in `signature.py` (+ a
  parametrized case in `test_hub.py`). A repo that moved is harmless (422 → search everywhere) but fix the name.
- **Add a source**: a method on `Sources` (+ `FixtureSources`, a fixture file), a `verify.*` function with an audit, a
  job in `service.py`, a line kind in `report.source_line`, a label in `Hub*.svelte`, then EXTERNAL_DEPENDENCIES §3c,
  the privacy texts and docs/HUB.md.

## Debugging recipes

- **Nothing found for an obvious error** → print the signature: is the message clean (no "npm ERR!", no "after I…",
  no paths)? Is the query too long? `relevance()` too strict for this wording? Check the audit: "not about this error"
  vs "no accepted or well-voted answer".
- **A source "could not be read"** → the report's `errors`: `HTTP 403` from DEV (its firewall dislikes some
  User-Agents — keep `UA` as it is), GitHub rate limit (10 searches/min without a token; set `GITHUB_TOKEN`), Stack
  Exchange `backoff`/quota (`status()` shows `stackexchange_remaining`), `HTTP 422` from GitHub (a moved repo — the
  search falls back).
- **She answered without searching** → `hub_intent(text)` is None: add the phrasing to `intent.py` with a test (both
  directions — a false trigger is worse).
- **"not in the verified data: 30 / 64"** → a number that is not in the sheet: either add the fact to the sheet (if it
  is ours, like the 30-minute rule) or it is an invention the check caught.
- **Learning results are popular products** → the two searches must stay `<topic> example` / `<topic> tutorial`;
  `verify.repos` keeps a non-learning repo only with ≥ 100 stars, flagged "a project to read".
- **Few or no public teammates** → the audit (panel "GitHub profiles: N read, K kept (left out …)"): "not read
  (GitHub's rate limit …)" → set `GITHUB_TOKEN` (5 → 11 profiles read); "none of the skills asked for" → the need's
  language (`_LANG`) is too broad (a framework needs its own GitHub language if it has one — Svelte, Vue, Dart);
  "no public activity for a year" is intended. Designers, pitch and product people are not on GitHub by design.
- **No open questions on the help board** → Stack Overflow is quiet for niche tags (found live: [fastapi]'s newest
  unsolved question was 101 days old): the window is 180 days and a single tag gets its language's tag; check `why`
  (card skills vs last search) and `audit` in `GET /api/hub/questions`.
- **A card's GitHub skills do not show** → consent ticked? `verify_later` runs in the background (the panel
  refreshes after ~2.5 s); a 404 shows "GitHub has no public account called …"; GitHub unreachable shows "could not
  be checked right now (…)" (`verified.found == null`).
- **"Too many new board identities" (429) at an event** → everyone on the venue's Wi-Fi shares one address: raise
  `EH_HUB_NEW_IDS_PER_HOUR` in `.env` and restart.
- **A profile / request is refused with 422** → the list limits (skills 20, looking for / interests 12, tags 8, links
  5) apply to lists only; the form sends the typed text ("python, fastapi"), which `norm_list` splits and caps.
- **The ship plan or "mine" vanished after a restart** → the browser sends its token (`X-Hub-Token`) and its plan
  (`hello`); a 401 `no_token` makes the UI say hello and retry once. Check localStorage `eh.hub.token` / the ship key.
