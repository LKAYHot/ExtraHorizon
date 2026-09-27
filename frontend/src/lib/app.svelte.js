import * as api from './api.js'
import { probsArray } from './emotions.js'
import { ALL_PAIRS, orderPair } from './coord.js'
import { isLoopbackHost } from './format.js'
import { claimSessionId, getSessionId, readPref, writePref } from './session.js'
import { VisionController } from './vision.svelte.js'
import { VoiceController } from './voice.svelte.js'
import { HubState } from './hub.svelte.js'

const WINDOW_MS = 180_000
const HEALTH_EVERY_MS = 4000
let tmpCounter = 0
const tmpId = (p) => `tmp_${p}_${++tmpCounter}`

/**
 * All UI state. Everything the emotion panel shows comes from the backend (ticks, notes,
 * markers, chat meta) — the browser never computes or invents an emotion value.
 */
class AppState {
  sessionId = getSessionId()
  bootId = $state(null)
  health = $state.raw(null)
  backendUp = $state(null)
  subject = $state(readPref('subject', 'General'))
  showCues = $state(readPref('showCues', true))

  messages = $state([])
  busy = $state(false) // a typed answer is streaming over SSE
  emotion = $state.raw(null) // latest smoothed estimate (public engine state)
  context = $state.raw(null) // what the tutor would be told right now ({available, text, note, …})
  visionTick = $state.raw(null)
  sim = $state({ enabled: false, emotion: 'happiness', intensity: 0.8 })
  toasts = $state([])
  resetting = $state(false)

  // high-frequency data: plain arrays + a version counter (cheap to append at 12 Hz)
  timeline = { samples: [], markers: [] }
  timelineVersion = $state(0)

  vision = new VisionController(this)
  voice = new VoiceController(this)

  // utility-coordination analysis (coord/) or the hackathon hub (hub/): the right panel shows it instead of the camera
  view = $state('tutor') // tutor | analysis | hub
  // spot: what she just looked up or named ({ids, label, project}) — the panel and the map follow it
  coord = $state({ state: 'idle', error: '', steps: [], selected: null, pair: null, rechecks: {}, busy: false, spot: null,
                   tab: 'findings' })
  coordReport = $state.raw(null) // the verified report (projects, findings, sources) — large, not deep-reactive
  // hackathon hub: help from public sources, teammates and mentors, the board, the road to shipping
  hub = new HubState(this)

  // remote access (e.g. the presenter's PC behind Cloudflare Tunnel): the app starts only once
  // /api/access says this browser may use it — checking | ok | needed | disabled | offline
  access = $state.raw(null)
  accessState = $state('checking')
  /** local | cloudflare | proxy | network — how this browser reaches the server (for honest wording). */
  transport = $derived(this.access?.transport ?? this.vision.transport ?? null)
  viaTunnel = $derived(this.transport === 'cloudflare')

  // "local" wording anywhere in the UI requires BOTH a loopback page and the backend
  // confirming it sees us on loopback (same rule as the privacy card)
  local = $derived(typeof location !== 'undefined' && isLoopbackHost(location.hostname) && this.vision.clientIsLoopback === true)
  persona = $derived(this.health?.persona ?? this.voice.info?.persona ?? 'Rika')
  coordEnabled = $derived(this.health?.coord?.enabled !== false) // EH_COORD_ENABLED (on until health says otherwise)
  hubEnabled = $derived(this.health?.hub?.enabled !== false) // EH_HUB_ENABLED
  #coordGen = 0 // bumped by "New session" / closing: late answers of older requests are dropped
  #pendingFocus = null // a focus that arrived before its report was loaded
  /** Voice turn in flight (spoken question being answered), newest first. */
  voiceTurnActive = $derived(this.messages.some((m) => m.role === 'assistant' && m.source === 'voice' && (m.status === 'pending' || m.status === 'streaming')))
  /** idle | listening | hearing | thinking | speaking — the tutor's conversational state. */
  talkState = $derived.by(() => {
    const v = this.voice
    if (v.playing && v.playingKind === 'answer') return 'speaking'
    if (v.hearing) return 'hearing'
    if (this.busy || this.voiceTurnActive || (v.playing && v.playingKind === 'filler')) return 'thinking'
    if (v.mic === 'on') return 'listening'
    return 'idle'
  })

  #abort = null
  #healthTimer = null
  #started = false
  #booting = false
  #ready = null // resolves once the tab owns its session id and restored its state

  // ------------------------------------------------------------------ access
  /** First call: ask whether this browser needs the access key, then start (or show the gate). */
  async boot() {
    this.#booting = true
    while (this.#booting) {
      try {
        const a = await api.getAccess()
        this.access = a
        if (!a.required || a.ok) {
          this.accessState = 'ok'
          return this.start()
        }
        this.accessState = a.configured ? 'needed' : 'disabled'
        return
      } catch (e) {
        if (e.status === 404) { // a backend without remote access support: nothing to unlock
          this.accessState = 'ok'
          return this.start()
        }
        this.accessState = 'offline' // server or tunnel not reachable yet — keep trying
        await new Promise((r) => setTimeout(r, 2500))
      }
    }
  }

  /** Submit the access key (throws {code: wrong_key | too_many_attempts | remote_disabled, …}). */
  async unlock(key) {
    const a = await api.login(key)
    this.access = { ...a, ok: true }
    this.accessState = 'ok'
    return this.start()
  }

  /** The API said the access cookie is gone (expired, key changed): back to the gate. */
  lockOut() {
    if (this.accessState !== 'ok' || !this.access?.required) return
    this.shutdown()
    this.access = { ...this.access, ok: false }
    this.accessState = 'needed'
    this.toast('warn', 'Access expired — enter the key again.')
  }

  // ------------------------------------------------------------------ lifecycle
  start() {
    if (this.#started) return this.#ready
    this.#started = true
    this.#ready = (async () => {
      this.sessionId = await claimSessionId()
      await this.#restore()
      this.#restoreAnalysis()
      this.hub.hello()
      this.#pollHealth(true)
      this.#healthTimer = setInterval(() => this.#pollHealth(false), HEALTH_EVERY_MS)
      this.vision.start()
      this.voice.start()
    })()
    return this.#ready
  }

  /** Chat actions wait for start-up, so an early click can't race the state restore. */
  async #whenReady() {
    if (this.#ready) await this.#ready
  }

  shutdown() {
    this.#booting = false
    clearInterval(this.#healthTimer)
    this.vision.stop()
    this.voice.stop()
    this.#started = false
  }

  async #restore() {
    try {
      const st = await api.getState(this.sessionId)
      this.bootId = st.boot_id
      if (this.messages.length || this.busy) return // never clobber a conversation already under way
      if (st.subject && st.messages.length) this.subject = st.subject
      this.messages = st.messages.map((m) => ({ ...m, key: m.id, status: 'done' }))
      this.timeline = { samples: st.timeline.samples, markers: st.timeline.markers }
      this.emotion = st.emotion
      this.timelineVersion++
    } catch {
      /* backend not up yet — health polling + the sockets will catch up */
    }
  }

  async #pollHealth(deep) {
    try {
      const h = await api.getHealth(deep)
      if (this.bootId && h.boot_id !== this.bootId) this.onBackendRestart()
      this.bootId = h.boot_id
      // keep the last known "reachable" (only deep checks measure it)
      if (!deep && this.health?.llm && h.llm.reachable == null) h.llm.reachable = this.health.llm.reachable
      this.health = h
      if (this.backendUp === false) this.toast('ok', 'Backend is back online.')
      this.backendUp = true
    } catch (e) {
      if (e?.status === 401 || e?.code === 'remote_disabled') return this.lockOut()
      if (this.backendUp !== false) this.backendUp = false
    }
  }

  recheckLLM() {
    return this.#pollHealth(true)
  }

  onBackendRestart() {
    this.#clearLocal()
    this.toast('warn', 'The backend restarted — the session was cleared.')
  }

  #clearLocal() {
    this.#abort?.abort('reset')
    this.messages = []
    this.emotion = null
    this.context = null
    this.timeline = { samples: [], markers: [] }
    this.timelineVersion++
    this.voice.reset()
    this.#coordGen++
    this.#pendingFocus = null
    this.coordReport = null
    this.coord.state = 'idle'
    this.coord.steps = []
    this.coord.rechecks = {}
    this.coord.selected = null
    this.coord.spot = null
    this.hub.reset()
    this.hub.hello() // the board token and the ship plan are this browser's: tell the (new) server again
    this.view = 'tutor'
  }

  // ------------------------------------------------------------------ vision socket callbacks
  onHello(m) {
    if (this.bootId && m.boot_id !== this.bootId) this.onBackendRestart()
    this.bootId = m.boot_id
  }

  onSnapshot(m) {
    this.timeline = { samples: m.timeline.samples, markers: m.timeline.markers }
    this.emotion = m.emotion
    if (m.context) this.context = m.context
    this.timelineVersion++
  }

  onTick(m) {
    // simulation ticks carry no vision section: keep the last analysed frame (no box flicker)
    if (m.vision) this.visionTick = m.vision
    else if (m.seq != null) this.visionTick = null // an acknowledged frame that was not analysed
    const e = m.emotion
    if (!e) return
    this.emotion = e
    const s = this.timeline.samples
    s.push([m.t, e.status, e.source, e.dominant, probsArray(e.probs), e.valence, e.arousal])
    const cutoff = m.t - WINDOW_MS
    let drop = 0
    while (drop < s.length && s[drop][0] < cutoff) drop++
    if (drop > 64) s.splice(0, drop)
    this.timelineVersion++
  }

  onEmotionNote(ctx) {
    this.context = ctx
  }

  onMarker(mk) {
    this.timeline.markers.push(mk)
    this.timelineVersion++
  }

  onServerReset() {
    this.#clearLocal()
  }

  onSocketClosed() {
    this.emotion = null // nothing is measured while disconnected — never show a frozen value
    this.visionTick = null
  }

  onAssistantInterrupted(id) {
    const m = this.messages.find((x) => x.id === id)
    if (m) m.interrupted = true
  }

  /** The voice socket closed: its spoken turn in flight was cancelled by the server. */
  onVoiceSocketLost() {
    this.#flushNow()
    for (let i = this.messages.length - 1; i >= 0; i--) {
      const m = this.messages[i]
      if (m.role !== 'assistant' || m.source !== 'voice' || (m.status !== 'pending' && m.status !== 'streaming')) continue
      if (m.text) {
        m.status = 'done'
        m.interrupted = true
      } else {
        m.status = 'error'
        m.error = { code: 'connection_lost', message: 'The voice connection dropped — ask again.', retryable: false }
      }
    }
  }

  // ------------------------------------------------------------------ voice turns (live socket)
  #pendingText = new Map() // turn_no → buffered delta text (flushed once per frame)
  #flushScheduled = false

  onVoiceTurn({ event, turn_no: turn, data }) {
    if (event === 'meta') {
      const u = data.user_message
      this.messages.push({ ...u, key: u.id, status: 'done' })
      this.messages.push({
        id: data.assistant_message_id, key: data.assistant_message_id, role: 'assistant', text: '', status: 'streaming',
        source: 'voice', turn_no: turn, model: data.model, emotion_context: data.emotion_context, voice: data.voice,
        analysis: data.analysis ?? null, hub: data.hub ?? null, created: Date.now(),
      })
      return
    }
    if (event === 'focus') return data?.kind === 'hub' ? this.hub.onFocus(data) : this.onFocus(data)
    if (event === 'recheck') return this.onRecheckEvent(data)
    const msg = this.#assistantOfTurn(turn)
    if (!msg) return
    if (event === 'analysis') {
      msg.analysis = { ...(msg.analysis ?? {}), live: data }
      this.onAnalysisEvent(data)
      return
    }
    if (event === 'hub') {
      msg.hub = { ...(msg.hub ?? {}), live: data }
      this.hub.onEvent(data)
      return
    }
    if (event === 'tool') {
      this.#onTool(msg, data)
      return
    }
    if (event === 'delta') {
      this.#pendingText.set(turn, (this.#pendingText.get(turn) ?? '') + (data.text ?? ''))
      this.#scheduleFlush()
      return
    }
    this.#flushNow()
    if (event === 'done' || event === 'interrupted') {
      msg.status = 'done'
      if (data.analysis) msg.analysis = { ...(msg.analysis ?? {}), ...data.analysis }
      if (data.hub) msg.hub = { ...(msg.hub ?? {}), ...data.hub }
      msg.model = data.model
      msg.ttft_ms = data.ttft_ms
      msg.elapsed_ms = data.elapsed_ms
      msg.interrupted = !!data.interrupted
      if (event === 'interrupted') this.#analysisTurnEnded(msg)
    } else if (event === 'error') {
      msg.status = 'error'
      msg.error = data
      this.#analysisTurnEnded(msg)
    } else if (event === 'dropped') {
      this.#analysisTurnEnded(msg)
      // the learner went on talking: this turn never happened (the next one answers both)
      const i = this.messages.indexOf(msg)
      const start = i > 0 && this.messages[i - 1].role === 'user' ? i - 1 : i
      this.messages.splice(start, i - start + 1)
    }
  }

  #assistantOfTurn(turn) {
    for (let i = this.messages.length - 1; i >= 0; i--) {
      const m = this.messages[i]
      if (m.role === 'assistant' && m.turn_no === turn) return m
    }
    return null
  }

  #scheduleFlush() {
    if (this.#flushScheduled) return
    this.#flushScheduled = true
    if (document.hidden) setTimeout(() => this.#flushNow(), 50)
    else requestAnimationFrame(() => this.#flushNow())
  }

  #flushNow() {
    this.#flushScheduled = false
    for (const [turn, text] of this.#pendingText) {
      const msg = this.#assistantOfTurn(turn)
      if (msg && text) msg.text += text
    }
    this.#pendingText.clear()
  }

  // ------------------------------------------------------------------ typed chat (SSE)
  async send(text, { analysis = false, hub = null } = {}) {
    text = (text ?? '').trim()
    if (!text || this.busy) return false
    this.voice.unlockAudio() // the click/Enter is the user gesture browsers require for audio
    await this.#whenReady()
    if (this.busy) return false
    const id = tmpId('u')
    this.messages.push({ id, key: id, role: 'user', text, source: 'text', status: 'done', created: Date.now() })
    this.#run({ message: text, subject: this.subject, ...(analysis ? { analysis: true } : {}), ...(hub ? { hub } : {}) })
    return true
  }

  // ------------------------------------------------------------------ utility-coordination analysis
  /** Ask Rika to run the analysis (she explains it in the chat; the panel shows it). */
  runAnalysis() {
    this.view = 'analysis'
    return this.send('Compare the public construction plans of the utilities in Miami-Dade County and flag where their planned work overlaps.', { analysis: true })
  }

  /** Server events of an analysis turn: running → progress… → ready | error | cancelled. */
  onAnalysisEvent(d) {
    const c = this.coord
    if (d.state === 'running') {
      c.state = 'running'
      c.error = ''
      c.steps = []
      this.view = 'analysis'
    } else if (d.state === 'progress') {
      c.steps = [...c.steps, d].slice(-60)
    } else if (d.state === 'ready') {
      this.#loadReport('ready')
    } else if (d.state === 'error') {
      c.state = 'error'
      c.error = d.message || 'The analysis failed.'
    } else if (d.state === 'cancelled') {
      c.state = this.coordReport ? 'ready' : 'idle' // stopped: the panel shows what it had (or the intro)
      c.steps = []
    }
  }

  /** A turn that was running the analysis ended early (Stop, a newer question, an error, a dropped
   *  voice turn): the card and the panel must not keep spinning. */
  #analysisTurnEnded(msg) {
    this.hub.turnEnded(msg)
    const st = msg?.analysis?.live?.state
    if (msg?.analysis?.mode === 'run' && (!st || st === 'running' || st === 'progress')) {
      msg.analysis = { ...msg.analysis, live: { state: 'cancelled' } }
      if (this.coord.state === 'running') this.onAnalysisEvent({ state: 'cancelled' })
    }
  }

  async #loadReport(state) {
    const gen = this.#coordGen
    try {
      const report = await api.coordReport(this.sessionId)
      if (gen !== this.#coordGen) return // "New session" / closed meanwhile
      this.#setReport(report)
      this.coord.state = state
    } catch (e) {
      if (gen !== this.#coordGen) return
      if (e.status === 404) {
        if (this.coord.state === 'running') this.coord.state = 'idle'
      } else {
        this.coord.state = 'error'
        this.coord.error = e.message
      }
    }
  }

  /** A new report opens on its strongest finding (the one she names first) and that finding's pair;
   *  a re-run with other rules keeps the chosen pair (finding IDs are renumbered). */
  #setReport(report, keepPair = false) {
    this.coordReport = report
    this.coord.rechecks = {}
    const pairs = (report?.pairs ?? []).map((p) => orderPair(p.plans, report).join(' ↔ '))
    const first = keepPair ? null : (report?.highlights?.[0] ?? report?.findings?.[0]?.id ?? null)
    this.coord.selected = first
    const own = first ? this.#pairOf(first) : null
    this.coord.spot = null
    if (own) this.coord.pair = own
    else if (!pairs.includes(this.coord.pair)) this.coord.pair = pairs[0] ?? null
    if (this.#pendingFocus) {
      const d = this.#pendingFocus
      this.#pendingFocus = null
      if (!d.report_id || d.report_id === report?.id) this.onFocus(d) // a stale one (older report) is dropped
    }
  }

  /** The pair key (as the pair picker spells it) of a finding. */
  #pairOf(fid) {
    const report = this.coordReport
    const f = report?.findings?.find((x) => x.id === fid)
    if (!f) return null
    const want = [...f.plans].sort().join(' ↔ ')
    const p = report.pairs.find((x) => [...x.plans].sort().join(' ↔ ') === want)
    return p ? orderPair(p.plans, report).join(' ↔ ') : null
  }

  choosePair(key) {
    this.coord.spot = null // the learner browses again
    this.coord.pair = key
    if (key !== ALL_PAIRS && this.coord.selected && this.#pairOf(this.coord.selected) !== key) this.coord.selected = null
  }

  // ------------------------------------------------------------------ the map follows the conversation
  /** A finding or place she looked up or named, or the question pointed at ("what about F146?"). */
  onFocus(d) {
    if (!d) return
    if (!this.coordReport || (d.report_id && d.report_id !== this.coordReport.id)) {
      // the report is still loading (an analysis that just finished) — or it is a newer one than the panel's
      if (d.within && this.#pendingFocus) return // a pick never replaces the spotlight it picks from
      this.#pendingFocus = d
      return
    }
    this.#mergeFindings(d.findings)
    const have = new Set(this.coordReport.findings.map((f) => f.id))
    const ids = (d.ids ?? []).filter((id) => have.has(id))
    if (!ids.length && !d.project) return
    if (d.within && this.coord.spot && ids.length === 1) {
      // her answer names one of the findings she is showing ("the closest is F138"): select it, keep the rest
      const s = this.coord.spot
      if (!s.ids.includes(ids[0])) this.coord.spot = { ...s, ids: [...s.ids, ids[0]] }
      this.#select(ids[0])
      return
    }
    this.view = 'analysis'
    if (ids.length === 1 && !d.project) {
      this.coord.spot = null
      this.#select(ids[0])
      return
    }
    if (!ids.length) {
      // a project with no findings: the map shows the project itself
      this.coord.spot = { ids: [], total: 0, label: d.label ?? '', project: d.project }
      this.coord.selected = null
      if (this.coord.tab === 'sources') this.coord.tab = 'findings'
      return
    }
    this.coord.spot = { ids, total: d.total ?? ids.length, label: d.label ?? '', project: d.project ?? null }
    if (this.coord.tab === 'sources') this.coord.tab = 'findings'
    const pairs = new Set(ids.map((id) => this.#pairOf(id)))
    this.coord.pair = pairs.size === 1 ? [...pairs][0] : ALL_PAIRS
    this.coord.selected = ids[0]
  }

  clearSpot() {
    this.coord.spot = null
  }

  onRecheckEvent(d) {
    if (!d?.id || !d.result || (d.report_id && d.report_id !== this.coordReport?.id)) return
    this.coord.rechecks = { ...this.coord.rechecks, [d.id]: recheckState(d.result) }
  }

  #onTool(msg, d) {
    if (!msg || !d?.name) return
    const key = msg.hub ? 'hub' : 'analysis' // the look-ups of a hub answer or of an analysis answer
    msg[key] = { ...(msg[key] ?? {}), tools: [...(msg[key]?.tools ?? []), d] }
  }

  /** Findings the panel does not list arrive with a focus (or on a click): the map can draw them. */
  #mergeFindings(list) {
    if (!list?.length || !this.coordReport) return
    const have = new Set(this.coordReport.findings.map((f) => f.id))
    const add = list.filter((f) => f?.id && !have.has(f.id))
    if (add.length) this.coordReport = { ...this.coordReport, findings: [...this.coordReport.findings, ...add] }
  }

  async #restoreAnalysis() {
    await this.#loadReport('ready')
  }

  openAnalysis() {
    this.view = 'analysis'
  }

  closeAnalysisView() {
    this.view = 'tutor'
  }

  /** Re-run with other thresholds (no chat turn — ask Rika about it afterwards). */
  async applyCoordParams(params, refresh = false) {
    const gen = this.#coordGen
    this.coord.busy = true
    try {
      const report = await api.coordAnalyze(this.sessionId, { ...params, refresh })
      if (gen !== this.#coordGen) return
      this.#setReport(report, true)
      this.coord.state = 'ready'
      this.toast('ok', `Analysis updated: ${report.summary.findings.toLocaleString('en-US')} findings. Ask ${this.persona} about them.`)
    } catch (e) {
      if (gen === this.#coordGen) this.toast('error', e.message || 'The analysis could not be updated.')
    } finally {
      this.coord.busy = false
    }
  }

  async recheckFinding(fid) {
    const reportId = this.coordReport?.id
    this.coord.rechecks = { ...this.coord.rechecks, [fid]: { state: 'checking' } }
    let result
    try {
      const r = await api.coordRecheck(this.sessionId, fid)
      result = recheckState(r)
    } catch (e) {
      result = { state: 'unreachable', message: e.message }
    }
    // "Apply" renumbers the findings: an answer for the old F12 must not land on the new one
    if (this.coordReport?.id === reportId) this.coord.rechecks = { ...this.coord.rechecks, [fid]: result }
  }

  /** Show a finding on the map — also one the panel does not list (a click on "F450" in her answer). */
  async selectFinding(fid) {
    if (!this.coordReport) return
    if (!this.coordReport.findings.some((f) => f.id === fid)) {
      const gen = this.#coordGen
      try {
        const f = await api.coordFinding(this.sessionId, fid)
        if (gen !== this.#coordGen) return
        this.#mergeFindings([f])
      } catch {
        this.toast('warn', `${fid} is not in this analysis.`)
        return
      }
    }
    if (this.coord.spot && !this.coord.spot.ids.includes(fid)) this.coord.spot = null
    this.#select(fid)
  }

  #select(fid) {
    if (this.coord.tab === 'sources') this.coord.tab = 'findings' // show the finding's card
    const own = this.#pairOf(fid)
    if (!this.coord.spot && this.coord.pair !== ALL_PAIRS && own && own !== this.coord.pair) this.coord.pair = own
    this.coord.selected = fid
    this.view = 'analysis'
  }

  /** Close the analysis: the server forgets it (her answers are ordinary tutoring again), the camera
   *  panel comes back. (The header toggle only switches panels and keeps the analysis.) */
  async closeAnalysis() {
    this.#coordGen++
    this.#pendingFocus = null
    this.coord.spot = null
    this.coordReport = null
    this.coord.state = 'idle'
    this.coord.steps = []
    this.coord.rechecks = {}
    this.coord.selected = null
    this.view = 'tutor'
    try {
      await api.coordClose(this.sessionId)
    } catch {
      /* the local view is closed anyway */
    }
  }

  async retry(assistantId) {
    if (this.busy) return
    const i = this.messages.findIndex((m) => m.id === assistantId)
    // only the latest answer can be retried: re-running an older one would reorder history
    if (i === -1 || i !== this.messages.length - 1) return
    const failed = this.messages[i]
    if (!failed.request) return
    this.messages.splice(i, 1)
    this.#run(failed.request)
  }

  /** Stop button / Esc: silence her and stop the answer in flight (typed or spoken). The
   *  server keeps what was said so far (marked interrupted) and ends the stream cleanly. */
  stopAnswer() {
    const live = this.voice.socket === 'open'
    this.voice.interrupt()
    if (!live) api.interruptSession(this.sessionId).catch(() => {})
    const ctrl = this.#abort
    if (ctrl) setTimeout(() => this.#abort === ctrl && ctrl.abort('stopped'), 2500) // backend unreachable
  }

  async #run(request) {
    this.busy = true
    const aid = tmpId('a')
    this.messages.push({
      id: aid, key: aid, role: 'assistant', text: '', status: 'pending', source: 'text',
      error: null, model: null, created: Date.now(), request,
    })
    const msg = this.messages[this.messages.length - 1]
    let userMsg = null
    for (let i = this.messages.length - 2; i >= 0; i--) if (this.messages[i].role === 'user') { userMsg = this.messages[i]; break }
    const ctrl = new AbortController()
    this.#abort = ctrl

    let pending = ''
    let scheduled = false
    const flush = () => {
      scheduled = false
      if (pending) {
        msg.text += pending
        pending = ''
      }
    }
    const schedule = () => {
      if (scheduled) return
      scheduled = true
      if (document.hidden) setTimeout(flush, 50)
      else requestAnimationFrame(flush)
    }

    await api.streamChat(
      { ...request, session_id: this.sessionId },
      {
        signal: ctrl.signal,
        onMeta: (meta) => {
          msg.id = meta.assistant_message_id
          msg.analysis = meta.analysis ?? null
          msg.hub = meta.hub ?? null
          msg.model = meta.model
          msg.turn_no = meta.turn_no
          msg.voice = meta.voice
          msg.emotion_context = meta.emotion_context
          msg.status = 'streaming'
          if (userMsg && userMsg.id.startsWith('tmp_')) userMsg.id = meta.user_message.id
        },
        onDelta: (t) => {
          pending += t
          schedule()
        },
        onAnalysis: (d) => {
          msg.analysis = { ...(msg.analysis ?? {}), live: d }
          this.onAnalysisEvent(d)
        },
        onHub: (d) => {
          msg.hub = { ...(msg.hub ?? {}), live: d }
          this.hub.onEvent(d)
        },
        onFocus: (d) => (d?.kind === 'hub' ? this.hub.onFocus(d) : this.onFocus(d)),
        onTool: (d) => this.#onTool(msg, d),
        onRecheck: (d) => this.onRecheckEvent(d),
        onDone: (d) => {
          flush()
          msg.status = 'done'
          if (d.analysis) msg.analysis = { ...(msg.analysis ?? {}), ...d.analysis }
          if (d.hub) msg.hub = { ...(msg.hub ?? {}), ...d.hub }
          msg.model = d.model
          msg.ttft_ms = d.ttft_ms
          msg.elapsed_ms = d.elapsed_ms
          msg.finish_reason = d.finish_reason
        },
        onInterrupted: (d) => {
          flush()
          msg.status = 'done'
          msg.interrupted = true
          msg.model = d.model
          msg.ttft_ms = d.ttft_ms
          if (d.analysis) msg.analysis = { ...(msg.analysis ?? {}), ...d.analysis }
          if (d.hub) msg.hub = { ...(msg.hub ?? {}), ...d.hub }
          this.#analysisTurnEnded(msg)
        },
        onError: (err) => {
          flush()
          this.#analysisTurnEnded(msg)
          if (err.code === 'stopped' && msg.text) {
            msg.status = 'done'
            msg.interrupted = true
            return
          }
          msg.status = 'error'
          msg.error = err
        },
      },
    )
    if (this.#abort === ctrl) this.#abort = null
    this.busy = false
  }

  // ------------------------------------------------------------------ controls
  async reset() {
    if (this.resetting) return
    this.resetting = true
    this.#abort?.abort('reset')
    this.voice.interrupt()
    try {
      await api.resetSession(this.sessionId)
      this.#clearLocal()
      this.toast('ok', 'New session — chat, emotion history and timeline cleared.')
    } catch {
      this.#clearLocal()
      this.toast('error', 'Backend unreachable — cleared the local view only.')
    } finally {
      this.resetting = false
    }
  }

  setSubject(s) {
    this.subject = s
    writePref('subject', s)
  }

  setShowCues(on) {
    this.showCues = on
    writePref('showCues', on)
  }

  setSimulation(enabled) {
    this.sim.enabled = enabled
    this.vision.setSimulation(enabled)
  }

  setSimEmotion(emotion) {
    this.sim.emotion = emotion
  }

  toast(kind, text) {
    const id = tmpId('t')
    this.toasts.push({ id, kind, text })
    setTimeout(() => {
      const i = this.toasts.findIndex((t) => t.id === id)
      if (i !== -1) this.toasts.splice(i, 1)
    }, 4200)
  }
}

export const app = new AppState()

/** A re-check's state for the finding card: a record the county's service did not answer for is
 *  "could not re-check", never "changed". */
export function recheckState(r) {
  const unreachable = (r.records ?? []).filter((x) => !x.found && x.error !== 'record no longer published')
  return { ...r, state: r.ok ? 'ok' : unreachable.length ? 'unreachable' : 'changed' }
}
