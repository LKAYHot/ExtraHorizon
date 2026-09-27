# Hackathon hub — help from public sources, teammates and mentors, shared knowledge, shipping on time

The second ShellHacks challenge built into ExtraHorizon:

> *Create a solution that helps students find teammates, learn from one another, share knowledge, ask for help,
> receive mentorship, overcome roadblocks, and stay engaged until they ship.*

Rika is the interface: say or type what is blocking you, and she searches **public sources**, keeps only what can be
verified, and explains it in her own voice — citing every result by an ID you can click. The **Hub** panel (header
button *Hub*) shows the verified results, the people on this event's board, the help board and the road to shipping.

## 1. The pain points it solves (from hackathons we have been to)

| Pain point | What the hub does |
|---|---|
| **Silent stuck.** Beginners stay stuck for hours on a cryptic error, afraid to ask, and don't know how to phrase it. | Paste the error (or just say it). She searches Stack Overflow, GitHub issues and the npm / PyPI registries, keeps only verified answers and explains the likely fix with the exact command. *Still stuck?* turns the search into a well-formed help request ("Error … Stack … Already tried: S1, S2 …"). |
| **The same question, twelve times.** Mentors answer the same CORS / `cv2` / `ERESOLVE` question for team after team. | When a fix works, one click shares it as a card; the next team stuck on the same error sees it in her answer ("From teams here", K1) — peers learn from one another. The help board shows who else is stuck on it, so a mentor can help them together. |
| **Team formation chaos.** The first hours are spent wandering; skills on a badge are unverifiable. | People put a card on the board (skills, what they are looking for, interests, availability, team size). Matching covers the roles asked for, keeps teams within four, and shows which skills were **seen in their public GitHub repos** (only if they ticked the box). Nobody on the board yet? She searches **real public GitHub profiles in the event's city** whose repositories use what the team needs — each skill backed by their repositories, labelled as a lead ("not at this event"). |
| **Where do I even start?** Learning a new stack at 2 am. | "Where can I learn WebSockets with FastAPI?" → current tutorials and examples on GitHub, DEV Community articles and top Stack Overflow questions — stale, archived and unpopular material left out. |
| **Mentors are few and busy.** | Mentors on the board are matched to the stack ("covers fastapi, cors — available now"); help requests are claimed ("I can help") so nobody gets three mentors and nobody none. Beyond the event: **Stack Overflow's top answerers** for the stack — real experts, those who answered this month first — reached by asking with that tag. And the help board lists **real open questions** in your stack, so a team can learn by helping. |
| **Not shipping.** Teams build too much and miss the submission. | The Ship tab: a deadline and countdown, the seven milestones every hackathon project passes (pace: on track / behind), how long each roadblock has blocked them, and plain nudges — **the 30-minute rule** (stuck that long → ask a person), *cut scope*, *record the demo video now*, *submit a draft*. She answers "how are we doing?" from it. |

## 2. How a roadblock is searched

1. **The signature** (`hub/signature.py`): the error's type (`ModuleNotFoundError`, `CORS`, `ERESOLVE`, `HTTP 422`,
   `git` …), its core message, the stack (Stack Overflow tags, ecosystem, the project's GitHub repository), the
   packages it names (Python import names mapped to PyPI names: `cv2` → `opencv-python`) and hints from the error
   itself (a local import that did not resolve, a Node built-in in a browser bundle). **The text is scrubbed before
   anything is read from it**: file paths (also Windows paths with spaces), URLs (also database URLs), hosts, IP
   addresses and ports, `host=` / `password=` pairs, e-mail addresses, key-like strings (API keys, JWTs, cloud keys),
   UUIDs, long hex or random-looking strings and long numbers, their own file names and what they said around the
   error ("… after I added react-leaflet to my app") are gone; the signature is taken from what is left. Only the
   signature leaves the computer.
2. **The sources, in parallel** (`hub/sources.py`), each with progress on screen:
   * **Stack Overflow** (Stack Exchange API 2.3, no key, 300 requests/day per IP): `search/advanced` for questions
     with answers, then the **accepted answers by their own IDs** (`answers/{ids}` — a popular question's accepted
     answer is not always among its top-voted ones) and the other answers of the candidates that match.
   * **GitHub issues** (REST search, 10 searches/min without a token): first the stack's own tracker (a repository
     that moved answers 422 — then everywhere), then everywhere.
   * **npm registry / PyPI**: does the package exist, its latest version, what it needs (Node / Python versions, peer
     dependencies), deprecations.
   * **This event's board**: what teams here learned (cards), mentors who cover the stack, open requests about the same.
3. **Verification** (`hub/verify.py`) — every source is audited: how many results arrived, how many were kept, how
   many were left out and why (shown under *How this was checked*):
   * a Stack Overflow answer is kept only if its question **matches the error** (the signature's words, the error
     type counting double; for an HTTP error its status code must be there — "returns 500" does not match any
     question about HTTP) and it is **accepted** or has **≥ 3 votes**; voted-down questions are left out; answers
     older than five years are kept but **flagged** ("check it against today's versions"); every excerpt keeps its
     **author and licence (CC BY-SA)** and links to the answer; the code shown is the answer's block about this
     error — not the first one (often the asker's setup) and not the command that already failed for them ("npm
     install fails" → not a block that only says `npm install`);
   * a GitHub issue is kept if it matches and is **closed as fixed** or actively discussed (≥ 3 comments or ≥ 5
     reactions); pull requests and spam are left out; an issue from **another project's tracker** ranks lower and is
     labelled "a lead, not a command to copy";
   * the registries' own data is a fact; a package *named by the error* that does not exist is reported ("PyPI has no
     package named cv2"); a name the learner only mentioned is never reported as missing.
4. **Ranking**: a registry fact that settles it comes first (the import name ≠ the package name; a deprecated
   package; the peer dependencies behind an `ERESOLVE`), then accepted answers with code, then fixed issues. At most
   eight results, **S1 … S8**; peers **K1 …**, mentors **M1 …**. Commands in her answer come only from accepted
   answers or the registries. **Their own open request** is never shown as "another team stuck on this".

**Learning** (`learn`) searches GitHub for `<topic> example` and `<topic> tutorial` (tutorials, examples and
starters first; archived or untouched for three years left out, older than two flagged; a popular project that
merely uses the words is kept only with ≥ 100 stars and flagged "a project to read"), DEV Community by tag (published
within three years, ≥ 3 reactions) and Stack Overflow's top questions for the topic's tags (≥ 25 votes, accepted
answer) — **L1 …**.

## 3. The board (people, help requests, what teams learned)

* Shared by everyone using this server (at an event: the presenter's laptop and the laptops that reach it through
  the tunnel), kept in `backend/data/hub_board.json` (**git-ignored**; `EH_HUB_BOARD_PATH=` keeps it in memory).
* **Every entry belongs to the browser that wrote it**: the first write creates a random token, returned once and kept
  in that browser (localStorage) and sent back with every hub request (`X-Hub-Token`), so a server that lost the
  session (a restart, a sweep) still knows whose entries they are; the server stores only its SHA-256 and accepts back
  **only tokens it issued**. A client address gets **30 new identities an hour** (`EH_HUB_NEW_IDS_PER_HOUR`; a venue's
  Wi-Fi puts everyone behind one address — raise it there). Only the owner can edit or delete their card, resolve or
  withdraw their request, delete their card of knowledge. Claiming a request needs a card ("who is coming?"); your
  own request cannot be claimed by you; the helper or the team that asked can **give a claim back** (the request is
  open again). *Helped us* needs your own card on the board (one vote per identity, none for your own card of knowledge).
* **What people write stays data.** Board text reaches her sheet as one line per field (line breaks, quotes and
  brackets removed) under a header that says it is data, never instructions; an ID someone writes on the board
  ("S9 — …") is not a result, and her answer citing it is flagged. Links are plain web links (`http(s)` only,
  duplicates dropped; the panel shows nothing else); a request body over 64 KB is refused.
* **GitHub**: a username is read only if whoever typed it **ticked the box**; the hub reads `GET /users/<name>` and
  its public, non-fork repositories (languages, topics, names). **The hub cannot check that the account belongs to
  the person who typed it** — the form, the panel and her sheet say "that the account is theirs is not verified".
  "Seen in public GitHub repos" means exactly that — never a rating of skill. A new username or an unticked box drops
  what was read (a slow check of the old username never lands on the new one); if GitHub cannot be reached the card
  says so.
* **No sample entries**: everything on the board was written by a real person using the app. An empty board says so
  ("nobody has put a card here yet") — the public sources below still answer.
* Matching on the board (`hub/people.py`): the roles and skills asked for (in the question or on the asker's card: "a
  frontend dev and a designer" → frontend, design) must be covered (a role through its skills); a skill seen on GitHub
  counts 1.0, one written on the card 0.6; new skills the team lacks and shared interests add; teams together stay
  **within four**. Mentors are matched to the stack, "available now" first.
* **Open questions you could answer** (help board): real Stack Overflow questions that are still unsolved (no accepted,
  no upvoted answer), asked in the last six months, open, not voted down — for the skills on your card or the stack of
  your last search; a quiet tag gets its language's questions too ([fastapi] → [python]: found live, [fastapi]'s
  newest unsolved question was 101 days old); the tags take turns, newest first in each (a busy [python] must not
  crowd out [fastapi]). Titles link to Stack Overflow (CC BY-SA, asker named).

## 3b. People from public sources (`hub/people.py`, `service.people`)

Teammates and mentors come from **this event's board first**, then from real public sources — found live, verified,
labelled as leads:

* **Public GitHub profiles** (teammates): GitHub's own user search — `type:user language:"<Lang>" repos:>=3
  location:"<city>"` — for at most two languages, each need's own first ("react or svelte" → TypeScript and Svelte),
  in the event's city (`EH_HUB_EVENT_LOCATION`, Miami for ShellHacks; a place in the question wins — "… in Orlando" —
  and "remote" / "anywhere" searches everywhere). The first few profiles (from both searches in turn) are read:
  their public name, the city they wrote, their own public repositories (languages, topics, names, last push),
  "available for hire", and a few words their bio uses ("hackathons", "a student", "a university", "open to
  collaborating") — **never their e-mail, links, company, social accounts or the bio itself**. Kept: people (not
  organisations or bots) with public activity in the last year whose repositories use a skill asked for; ranked by what
  they cover, the bio's words, recency. Each is labelled: *not on this board, has not said they are looking for a team
  — one polite message through their GitHub profile at most.* Roles GitHub cannot show (design, pitch, product) are
  said plainly ("the board and a help request are the places to find them").
* **Stack Overflow's top answerers** (mentors): the stack's tags (the question's, else the role's usual ones), all
  time and this month; kept: registered accounts with at least ten answers on the tag; those who answered this month
  first. Labelled: *a public expert, not a mentor at this event — ask on Stack Overflow with the tag.* The panel links
  "Ask a [tag] question".
* Nothing is combined across sources (a GitHub profile and a Stack Overflow account are separate results); every
  source is audited (read / kept / left out and why) in the panel and her sheet.
* Limits: without a token GitHub allows 60 profile reads an hour — a search reads the first five profiles (two reads
  each) and says when more were found; a `GITHUB_TOKEN` in `.env` reads eleven. Stack Exchange: four requests per
  mentor search.

## 4. The road to shipping (`hub/ship.py`)

Per session (the browser keeps a copy in case the server restarts): a deadline (a preset — in 6 / 12 / 24 / 36 h — or
the app's own date-and-time picker: a month calendar from today to 30 days ahead, hour and minute columns, AM/PM,
keyboard-friendly), the milestones *Team and idea
locked → A hello-world running end to end → The core feature works → The demo path works every time → README with
screenshots → Demo video recorded → Submitted on Devpost*, each due at a share of the time (10 % … 97 %), and the
roadblocks she searched (open → solved / asked — closed by the search they came from: a card shared from it →
solved, a help request posted from it → asked). A server that lost the plan gets it back from the browser's copy; an
empty plan from the server never erases the browser's. The pace compares milestones done with the ones due. Nudges are
plain rules, not predictions: the **30-minute rule**, *cut scope* (behind by two at half time), *record the video*
(≤ 3 h left), *submit now* (≤ 1 h left), *no milestone for three hours*.

## 5. Rika and the hub

* **When a message is for the hub** (`hub/intent.py`, strict so tutoring stays tutoring): an error with a failure
  ("I get TypeError …", "the build fails with …", a pasted traceback or npm log, "у меня CORS ошибка") → get unstuck;
  teammates / a role / *тиммейт* → people; *mentor* → mentors; where to learn / tutorials / starters → learn; the
  deadline / time left / submission → ship. "What is a TypeError?", "Explain recursion", "I want to learn recursion",
  "What does ERESOLVE mean?" stay ordinary tutoring. Roles and skills are whole words ("we use npm and linux" asks
  for no one). The panel's own form and buttons send the same turns.
* **A search turn** runs first (progress events per source, a heartbeat while a source is slow, stopped by Stop /
  a newer question, a spoken question searched only once the final transcript confirms it); then her prompt holds
  the **hub fact sheet** — every result with its ID, figures, dates, flags, excerpts with attribution, the board's
  entries, the audit, sources that could not be read ("do not guess what they would have said"),
  the hub's 30-minute rule and the ship status — and **reply rules** per kind (a spoken summary first, then written
  help: *Try this first / If that does not fix it / Get a human / Sources*; *Start here / Go deeper*; *On this event's
  board / Public GitHub profiles / How to say hi*; *At this event / Public experts / How to ask well*; *Where you are /
  Next steps / Cut or keep*). People from public sources are never called available, looking for a team or willing to
  mentor. Only the first paragraph is spoken.
* **Grounding**: every figure, **version** (one figure: `4.12.0.88`, also at the end of a sentence), date and ID in
  her answer must be in the sheet (also inside its code — a date without its year, "last push on August 30", only if
  the sheet has that day), in her look-ups or in the learner's own message (their port
  5173 or "100 % of my requests" are theirs to mention); a whole number rounded from one in the sheet ("about 5 hours
  left") is fine; products named like IDs ("Amazon S3", "an M2 Mac", "the L2 cache") are not results. Otherwise the
  answer is marked *not in the verified data: …* (found live: it caught an invented "64-bit").
* **Follow-ups** ("what does S2 say exactly?", "who else can help?") are answered from the results on screen with
  tools: `get_hub_item`, `search_public_help`, `find_people`, `learning_resources`; the panel follows the ID in the
  question and the first result she names; IDs in her answers are buttons while the panel shows that search. A
  follow-up that runs a new search replaces the results, and her answer's IDs are about the new ones.
* **Language**: English even to Russian questions (unless Russian is asked for), as in the analysis.

## 6. Honest claims

* The hub reads public data and this event's board; it does not know about private Discords, Devpost teams or
  anything not on those sources. People from public sources are real people found by what they published for
  everyone (a GitHub profile and its repositories, Stack Overflow answers) — only the fields listed in §3b, never
  combined across sources, never called participants, available or looking for a team.
* There are no accounts: a board identity is a browser's token. It keeps honest people's entries theirs; it is not
  authentication (clearing the browser gives a new identity, within the per-address limit), and GitHub usernames on
  cards are not proven to be their owners'. The board is not moderated beyond these rules.
* "Verified" means *checked against these rules* (matching, accepted or voted, fixed, the registry's own data) — not
  that the fix is right for their code. Old answers and projects to read are flagged.
* Stack Overflow content is **CC BY-SA 4.0**: excerpts are short, with author, licence and link.
* There are no sample entries. The TEST fixtures (tests and the offline e2e) are invented, labelled (TEST people,
  TEST experts, TEST questions) and link to example.org.
* Limits: Stack Exchange 300 requests/day per IP (a search uses 2–4), GitHub 10 searches/min and 60 profile reads an
  hour without a token (an optional `GITHUB_TOKEN` in .env raises both — a people search then reads more profiles);
  responses are cached for an hour; a source that cannot be read is named and the others still answer.

## 7. Where things are

| What | Where |
|---|---|
| Signature, scrubbing, stack tags, import names | `backend/extrahorizon/hub/signature.py` |
| Public sources (live + labelled fixtures), caching, limits | `backend/extrahorizon/hub/sources.py` |
| Verification rules and audits | `backend/extrahorizon/hub/verify.py` |
| Searches (unstuck / learn / people) and report IDs | `backend/extrahorizon/hub/service.py` |
| Board, tokens, persistence | `backend/extrahorizon/hub/board.py`, vocabulary `hub/skills.py` |
| Matching; public GitHub profiles and Stack Overflow experts; where to look | `backend/extrahorizon/hub/people.py` (searches in `service.people`) |
| Road to shipping | `backend/extrahorizon/hub/ship.py` |
| Fact sheets, reply rules, grounding | `backend/extrahorizon/hub/report.py` (grounding shared with `coord/report.py`) |
| Intents, tools, REST routes | `hub/intent.py`, `hub/tools.py`, `hub/routes.py`; turns in `turns.py` (`_run_hub`) |
| UI | `frontend/src/lib/hub.svelte.js`, `components/Hub*.svelte`, hub IDs as buttons in `markdown.js`; the deadline picker `components/DateTimePicker.svelte` + `lib/datetime.js` |
| Tests | `backend/tests/test_hub.py`, `test_hub_people.py` (real people, open questions, no samples), `test_hub_review.py` (what the independent review found — `docs/TEST_MATRIX.md`), fixtures `tests/fixtures/make_hub_fixtures.py`, `frontend/src/lib/datetime.test.js`, `frontend/e2e/hub.spec.js` |
