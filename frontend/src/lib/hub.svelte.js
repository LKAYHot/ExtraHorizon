import * as api from './api.js'

/**
 * The hackathon hub's state (docs/HUB.md): the search results on screen (get unstuck, learn, teammates and
 * mentors — this event's board and real people from public sources), the event's board (people, help requests,
 * what teams learned, real open questions from Stack Overflow) and the road to shipping. Nothing on it is a sample.
 * The searches run as chat turns — Rika explains every result — so this state mostly follows server events.
 */

const TOKEN_KEY = 'eh.hub.token' // this browser's board token: whose card, requests and cards are its own
const SHIP_KEY = 'eh.hub.ship' // the ship plan, kept in case the server restarts
const store = {
  get(k) {
    try {
      return localStorage.getItem(k)
    } catch {
      return null
    }
  },
  set(k, v) {
    try {
      if (v == null) localStorage.removeItem(k)
      else localStorage.setItem(k, v)
    } catch {
      /* private mode: the board still works for this session */
    }
  },
}

export const HUB_TABS = [
  { key: 'help', label: 'Get unstuck' },
  { key: 'people', label: 'People' },
  { key: 'board', label: 'Help board' },
  { key: 'ship', label: 'Ship' },
]
export const SOURCE_KIND = {
  stackoverflow: 'Stack Overflow', github_issue: 'GitHub issue', package: 'Package registry', repo: 'GitHub repo',
  article: 'DEV Community', so_question: 'Stack Overflow',
}
const PEOPLE_KINDS = new Set(['team', 'mentors'])
/** Roles to search for in one click (the board, then public GitHub profiles in the event's city). */
export const ROLE_CHIPS = [
  { key: 'frontend', label: 'Frontend' }, { key: 'backend', label: 'Backend' }, { key: 'ml', label: 'ML / AI' },
  { key: 'mobile', label: 'Mobile' }, { key: 'hardware', label: 'Hardware' }, { key: 'design', label: 'Design' },
]
/** Where a person comes from: this event's board, a public GitHub profile, a Stack Overflow top answerer. */
export const PERSON_SOURCE = {
  board: 'On this board', github: 'GitHub profile', stackoverflow: 'Stack Overflow expert',
}
const QUESTIONS_EVERY_MS = 10 * 60_000 // open questions change slowly; the server caches them too

/** The refs of a report's results in the order the panel lists them. */
export function refsOf(report) {
  if (!report) return []
  return ['items', 'peers', 'mentors'].flatMap((g) => (report[g] ?? []).map((x) => x.ref)).filter(Boolean)
}

export function itemOf(report, ref) {
  if (!report || !ref) return null
  for (const g of ['items', 'peers', 'mentors']) {
    const x = (report[g] ?? []).find((y) => y.ref === ref)
    if (x) return x
  }
  return null
}

/** Links from public APIs and the board are shown only if they are plain web links (never javascript: or data:). */
export function safeUrl(u) {
  return typeof u === 'string' && /^https?:\/\/[^\s<>"']+$/i.test(u) ? u : null
}

/** "12 min", "1 h 05 min" */
export function minutes(n) {
  if (n == null) return ''
  if (n < 60) return `${n} min`
  return `${Math.floor(n / 60)} h ${String(n % 60).padStart(2, '0')} min`
}

export class HubState {
  report = $state.raw(null) // the results on screen: {kind: unstuck | learn | team | mentors, items, peers, mentors, …}
  run = $state({ state: 'idle', kind: null, steps: [], error: '' }) // a search in flight (server events)
  tab = $state('help')
  selected = $state(null) // a result's ref (S2, P1, M1, K1) — its card is highlighted
  board = $state.raw(null) // {profiles, requests, cards, me}
  questions = $state.raw(null) // real open questions for the help board: {tags, why, items, errors, as_of}
  #questionsAt = 0
  ship = $state.raw(null) // the ship status (computed by the server)
  milestones = $state.raw([])
  offline = $state(false)
  busy = $state(false)
  #gen = 0 // bumped by "New session" / closing: late answers are dropped
  #pendingFocus = null

  constructor(app) {
    this.app = app
  }

  get enabled() {
    return this.app.health?.hub?.enabled !== false
  }

  get token() {
    return store.get(TOKEN_KEY)
  }

  get me() {
    const b = this.board
    return b?.me ? (b.profiles ?? []).find((p) => p.id === b.me) ?? null : null
  }

  // ------------------------------------------------------------------ a session starts
  async hello() {
    let kept = null
    try {
      kept = JSON.parse(store.get(SHIP_KEY) || 'null')
    } catch {
      kept = null
    }
    try {
      const r = await api.hubHello(this.app.sessionId, this.token, kept)
      this.board = r.board
      this.milestones = r.milestones ?? []
      this.offline = !!r.offline
      this.#setShip(r)
      if (r.report_id) await this.loadReport()
    } catch {
      /* the hub is off or the backend is not up yet */
    }
  }

  #setShip(r) {
    if (!r?.ship) return
    const s = r.ship_state
    const empty = s && !s.deadline && !Object.keys(s.done ?? {}).length && !(s.roadblocks ?? []).length
    let kept = null
    try {
      kept = JSON.parse(store.get(SHIP_KEY) || 'null')
    } catch {
      kept = null
    }
    const keptHasData = kept && (kept.deadline || Object.keys(kept.done ?? {}).length || (kept.roadblocks ?? []).length)
    if (empty && keptHasData) {
      // the server lost the plan (a restart, a swept session): restore it from this browser, never erase it
      this.hello()
      return
    }
    this.ship = r.ship
    if (s) store.set(SHIP_KEY, JSON.stringify(s))
  }

  #took(r) {
    if (r?.token) store.set(TOKEN_KEY, r.token)
    if (r?.board) {
      const skills = (this.me?.skills ?? []).join(',')
      this.board = r.board
      if ((this.me?.skills ?? []).join(',') !== skills) this.#questionsAt = 0 // new skills: new open questions
    }
    return r
  }

  // ------------------------------------------------------------------ a search as a chat turn
  /** Ask Rika: she runs the search, the panel shows the verified results, she explains them. */
  search(kind, text) {
    const t = (text ?? '').trim()
    if (!t) return false
    this.app.view = 'hub'
    this.tab = PEOPLE_KINDS.has(kind) ? 'people' : kind === 'ship' ? 'ship' : 'help'
    return this.app.send(t, { hub: kind })
  }

  findTeammates() {
    const me = this.me
    const want = me?.looking_for?.length ? `who can cover ${me.looking_for.join(', ')}` : 'who complements my skills'
    return this.search('team', `Find me teammates ${want}.`)
  }

  findRole(role) {
    return this.search('team', `Find me a teammate for ${role}.`)
  }

  findMentor() {
    const me = this.me
    const topic = me?.looking_for?.length ? me.looking_for.join(' or ') : (me?.skills ?? []).slice(0, 2).join(' or ')
    return this.search('mentors', topic ? `Is there a mentor who knows ${topic}?` : 'Which mentors could help us right now?')
  }

  /** Real Stack Overflow questions nobody has answered yet, for my card's skills or my last search (help board). */
  async loadQuestions(force = false) {
    if (!force && this.questions && Date.now() - this.#questionsAt < QUESTIONS_EVERY_MS) return
    this.#questionsAt = Date.now()
    try {
      this.questions = await api.hubQuestions(this.app.sessionId)
    } catch (e) {
      this.questions = { tags: [], items: [], errors: [{ source: 'Stack Overflow', message: e.message || 'could not be read' }] }
    }
  }

  askShip() {
    return this.search('ship', 'How are we doing with the deadline, and what should we do next?')
  }

  /** Server events of a hub turn: running → progress… → ready | error | cancelled. */
  onEvent(d) {
    const run = this.run
    if (d.state === 'running') {
      run.state = 'running'
      run.kind = d.kind
      run.steps = []
      run.error = ''
      this.app.view = 'hub'
      this.tab = PEOPLE_KINDS.has(d.kind) ? 'people' : 'help'
    } else if (d.state === 'progress') {
      run.steps = [...run.steps, d].slice(-30)
    } else if (d.state === 'ready') {
      if (d.kind === 'ship') {
        this.app.view = 'hub'
        this.tab = 'ship'
        this.refreshShip()
        return
      }
      this.loadReport()
    } else if (d.state === 'error') {
      run.state = 'error'
      run.error = d.message || 'The search failed.'
    } else if (d.state === 'cancelled') {
      run.state = this.report ? 'ready' : 'idle'
      run.steps = []
    }
  }

  /** A turn that was searching ended early (Stop, a newer question, an error): nothing keeps spinning. */
  turnEnded(msg) {
    const st = msg?.hub?.live?.state
    if (msg?.hub?.mode === 'run' && msg.hub.kind !== 'ship' && (!st || st === 'running' || st === 'progress')) {
      msg.hub = { ...msg.hub, live: { state: 'cancelled', kind: msg.hub.kind } }
      if (this.run.state === 'running') this.onEvent({ state: 'cancelled' })
    }
  }

  async loadReport() {
    const gen = this.#gen
    try {
      const r = await api.hubReport(this.app.sessionId)
      if (gen !== this.#gen) return
      this.#setReport(r)
    } catch (e) {
      if (gen !== this.#gen) return
      if (e.status === 404) {
        if (this.run.state === 'running') this.run.state = 'idle'
      } else {
        this.run.state = 'error'
        this.run.error = e.message
      }
    }
    this.refreshBoard()
    this.refreshShip()
  }

  #setReport(r) {
    this.report = r
    if (r.kind === 'unstuck' || r.kind === 'learn') this.#questionsAt = 0 // a new stack: new open questions
    this.run.state = 'ready'
    this.run.kind = r.kind
    this.selected = refsOf(r)[0] ?? null
    this.tab = PEOPLE_KINDS.has(r.kind) ? 'people' : 'help'
    if (this.#pendingFocus) {
      const d = this.#pendingFocus
      this.#pendingFocus = null
      if (!d.report_id || d.report_id === r.id) this.onFocus(d)
    }
  }

  /** She named or looked up a result ("S2 is the one"): show its card. */
  onFocus(d) {
    if (!d?.ids?.length) return
    if (!this.report || (d.report_id && d.report_id !== this.report.id)) {
      this.#pendingFocus = d
      return
    }
    this.select(d.ids[0])
  }

  select(ref) {
    if (!itemOf(this.report, ref)) return false
    this.selected = ref
    this.tab = PEOPLE_KINDS.has(this.report.kind) ? 'people' : 'help'
    this.app.view = 'hub'
    return true
  }

  async close() {
    this.#gen++
    this.#pendingFocus = null
    this.report = null
    this.selected = null
    this.run.state = 'idle'
    this.run.steps = []
    try {
      await api.hubClose(this.app.sessionId)
    } catch {
      /* closed locally anyway */
    }
  }

  reset() {
    this.#gen++
    this.#pendingFocus = null
    this.questions = null
    this.#questionsAt = 0
    this.report = null
    this.selected = null
    this.run.state = 'idle'
    this.run.steps = []
    this.run.error = ''
  }

  // ------------------------------------------------------------------ the board
  async #do(fn, ok) {
    this.busy = true
    try {
      let r
      try {
        r = await fn()
      } catch (e) {
        if (e.status !== 401 || e.code !== 'no_token' || !this.token) throw e
        await this.hello() // the server lost this session: tell it who we are, then try once more
        r = await fn()
      }
      this.#took(r)
      if (ok) this.app.toast('ok', ok)
      return r
    } catch (e) {
      this.app.toast('error', e.message || 'That did not work.')
      return null
    } finally {
      this.busy = false
    }
  }

  async refreshBoard() {
    try {
      this.board = await api.hubBoard(this.app.sessionId)
    } catch {
      /* keep what is shown */
    }
  }

  saveProfile(profile) {
    return this.#do(() => api.hubSaveProfile(this.app.sessionId, profile), 'Your card is on the board.')
  }

  deleteProfile() {
    return this.#do(() => api.hubDeleteProfile(this.app.sessionId), 'Your card was removed from the board.')
  }

  postRequest(req) {
    return this.#do(() => api.hubPostRequest(this.app.sessionId, req), 'Posted on the help board — mentors and peers can see it.')
      .then((r) => { this.refreshShip(); return r })
  }

  claim(rid) {
    return this.#do(() => api.hubClaim(this.app.sessionId, rid), "You're on it — they can see who is coming.")
  }

  release(rid) {
    return this.#do(() => api.hubRelease(this.app.sessionId, rid), 'Given back — the request is open again.')
  }

  resolve(rid, body) {
    return this.#do(() => api.hubResolve(this.app.sessionId, rid, body), body?.share ? 'Solved — and shared for the next team.' : 'Marked solved.')
  }

  withdraw(rid) {
    return this.#do(() => api.hubWithdraw(this.app.sessionId, rid))
  }

  addCard(card) {
    return this.#do(() => api.hubAddCard(this.app.sessionId, card), 'Shared — the next team stuck on this will find it.')
      .then((r) => { this.refreshShip(); return r })
  }

  helpful(cid) {
    return this.#do(() => api.hubHelpful(this.app.sessionId, cid))
  }

  deleteCard(cid) {
    return this.#do(() => api.hubDeleteCard(this.app.sessionId, cid))
  }

  /** A help request written from the search on screen: the error, and what was already tried. */
  draftRequest() {
    const r = this.report
    if (!r || r.kind !== 'unstuck') return { title: '', problem: '', tags: [], tried: [] }
    const sig = r.query?.signature ?? {}
    const tried = (r.items ?? []).filter((x) => x.url).slice(0, 3)
    const lines = [`Error: ${r.query?.text ?? ''}`]
    if (sig.tags?.length) lines.push(`Stack: ${sig.tags.join(', ')}`)
    if (tried.length) lines.push(`Already tried: ${tried.map((x) => `${x.ref} ${x.title}`).join('; ')}`)
    lines.push('Expected: …', 'What happens instead: …')
    return { title: (r.query?.text ?? '').slice(0, 120), problem: lines.join('\n'), tags: (sig.tags ?? []).slice(0, 6),
             signature: { kind: sig.kind ?? '', message: (sig.message ?? '').slice(0, 240) },
             tried: tried.map((x) => safeUrl(x.url)).filter(Boolean), report_id: r.id }
  }

  /** A card for the next team, written from the result that fixed it. */
  draftCard(ref) {
    const r = this.report
    const x = itemOf(r, ref)
    let fix = x?.excerpt?.text || (x?.facts ?? []).join('; ') || x?.fix || ''
    if (x?.type === 'stackoverflow' && x.attribution?.author) {
      // a Stack Overflow answer is CC BY-SA: whoever reads the card later still sees whose answer it was
      fix = `${fix}\n(from an answer by ${x.attribution.author} on Stack Overflow, ${x.attribution.license})`
    }
    return { title: (r?.query?.text ?? '').slice(0, 120), problem: (r?.query?.text ?? '').slice(0, 300),
             fix: fix.slice(0, 800), tags: (r?.query?.signature?.tags ?? []).slice(0, 6),
             links: [safeUrl(x?.answer_url || x?.url)].filter(Boolean), report_id: r?.id ?? null }
  }

  // ------------------------------------------------------------------ the road to shipping
  async refreshShip() {
    try {
      this.#setShip(await api.hubShip(this.app.sessionId, {}))
    } catch {
      /* keep what is shown */
    }
  }

  async #ship(change) {
    try {
      this.#setShip(await api.hubShip(this.app.sessionId, change))
    } catch (e) {
      this.app.toast('error', e.message || 'That did not work.')
    }
  }

  setDeadline(epochSeconds) {
    return this.#ship({ deadline: epochSeconds })
  }

  toggleMilestone(key, done) {
    return this.#ship({ milestone: key, done })
  }

  closeRoadblock(id, status) {
    return this.#ship({ roadblock: id, status })
  }
}
