import * as api from './api.js'
import { currentOffer, isLoopbackHost } from './format.js'
import { claimSessionId, getSessionId, readPref, writePref } from './session.js'
import { VisionController } from './vision.svelte.js'

const WINDOW_MS = 180_000
const HEALTH_EVERY_MS = 4000
let tmpCounter = 0
const tmpId = (p) => `tmp_${p}_${++tmpCounter}`

function findLast(arr, pred) {
  for (let i = arr.length - 1; i >= 0; i--) if (pred(arr[i])) return arr[i]
  return null
}

/**
 * All UI state. Everything the signal panel, the timeline and the "Why it adapted"
 * card show comes from the backend state engine (ticks, events, markers, chat meta) —
 * the browser never computes or invents a signal value.
 */
class AppState {
  sessionId = getSessionId()
  bootId = $state(null)
  health = $state.raw(null)
  backendUp = $state(null)
  subject = $state(readPref('subject', 'General'))
  autoAdapt = $state(readPref('autoAdapt', false))

  messages = $state([])
  busy = $state(false)
  events = $state([])
  engine = $state.raw(null)
  visionTick = $state.raw(null)
  sim = $state({ enabled: false, value: 0.1 })
  toasts = $state([])
  lastEventAt = $state(0)
  resetting = $state(false)

  // high-frequency data: plain arrays + a version counter (cheap to append at 12 Hz)
  timeline = { samples: [], markers: [] }
  timelineVersion = $state(0)

  vision = new VisionController(this)

  offer = $derived(currentOffer(this.messages, this.events, this.busy))
  // "local" wording anywhere in the UI requires BOTH a loopback page and the backend
  // confirming it sees us on loopback (same rule as the privacy card)
  local = $derived(typeof location !== 'undefined' && isLoopbackHost(location.hostname) && this.vision.clientIsLoopback === true)
  latestConfusion = $derived(findLast(this.events, (e) => e.kind === 'possible_confusion'))

  #abort = null
  #healthTimer = null
  #started = false
  #ready = null // resolves once the tab owns its session id and restored its state

  // ------------------------------------------------------------------ lifecycle
  start() {
    if (this.#started) return this.#ready
    this.#started = true
    this.#ready = (async () => {
      this.sessionId = await claimSessionId()
      await this.#restore()
      this.#pollHealth(true)
      this.#healthTimer = setInterval(() => this.#pollHealth(false), HEALTH_EVERY_MS)
      this.vision.start()
    })()
    return this.#ready
  }

  /** Chat actions wait for start-up, so an early click can't race the state restore. */
  async #whenReady() {
    if (this.#ready) await this.#ready
  }

  shutdown() {
    clearInterval(this.#healthTimer)
    this.vision.stop()
    this.#started = false
  }

  async #restore() {
    try {
      const st = await api.getState(this.sessionId)
      this.bootId = st.boot_id
      if (this.messages.length || this.busy) return // never clobber a conversation already under way
      if (st.subject && st.messages.length) this.subject = st.subject
      this.messages = st.messages.map((m) => ({ ...m, key: m.id, status: 'done' }))
      this.events = st.events
      this.timeline = { samples: st.timeline.samples, markers: st.timeline.markers }
      this.timelineVersion++
    } catch {
      /* backend not up yet — health polling + the socket will catch up */
    }
  }

  async #pollHealth(deep) {
    try {
      const h = await api.getHealth(deep)
      if (this.bootId && h.boot_id !== this.bootId) this.#backendRestarted()
      this.bootId = h.boot_id
      // keep the last known "reachable" (only deep checks measure it)
      if (!deep && this.health?.llm && h.llm.reachable == null) h.llm.reachable = this.health.llm.reachable
      this.health = h
      if (this.backendUp === false) this.toast('ok', 'Backend is back online.')
      this.backendUp = true
    } catch {
      if (this.backendUp !== false) this.backendUp = false
    }
  }

  recheckLLM() {
    return this.#pollHealth(true)
  }

  #backendRestarted() {
    this.#clearLocal()
    this.toast('warn', 'The backend restarted — the session was cleared.')
  }

  #clearLocal() {
    this.#abort?.abort('reset')
    this.messages = []
    this.events = []
    this.engine = null
    this.timeline = { samples: [], markers: [] }
    this.timelineVersion++
  }

  // ------------------------------------------------------------------ vision socket callbacks
  onHello(m) {
    if (this.bootId && m.boot_id !== this.bootId) this.#backendRestarted()
    this.bootId = m.boot_id
  }

  onSnapshot(m) {
    this.events = m.events
    this.timeline = { samples: m.timeline.samples, markers: m.timeline.markers }
    this.engine = m.engine
    this.timelineVersion++
  }

  onTick(m) {
    if (m.vision) this.visionTick = m.vision
    const e = m.engine
    if (!e) return
    this.engine = e
    const s = this.timeline.samples
    s.push([m.t, e.raw, e.smoothed, e.status, e.source])
    const cutoff = m.t - WINDOW_MS
    let drop = 0
    while (drop < s.length && s[drop][0] < cutoff) drop++
    if (drop > 64) s.splice(0, drop)
    this.timelineVersion++
  }

  onEvent(ev) {
    const i = this.events.findIndex((x) => x.id === ev.id)
    if (i === -1) {
      this.events.push(ev)
      if (ev.kind === 'possible_confusion') this.lastEventAt = Date.now()
    } else {
      this.events[i] = ev
    }
  }

  onMarker(mk) {
    this.timeline.markers.push(mk)
    this.timelineVersion++
  }

  onServerReset() {
    this.#clearLocal()
  }

  onSocketClosed() {
    this.engine = null // nothing is measured while disconnected — never show a frozen value
  }

  // ------------------------------------------------------------------ chat
  async send(text) {
    text = (text ?? '').trim()
    if (!text || this.busy) return false
    await this.#whenReady()
    if (this.busy) return false
    const id = tmpId('u')
    this.messages.push({ id, key: id, role: 'user', text, mode: 'normal', status: 'done', created: Date.now() })
    this.#run({ mode: 'normal', message: text, subject: this.subject })
    return true
  }

  async explainDifferently(eventId) {
    if (this.busy || !eventId) return
    await this.#whenReady()
    if (this.busy) return
    const id = tmpId('u')
    this.messages.push({
      id, key: id, role: 'user', text: 'Explain differently', mode: 'explain_differently', status: 'done', created: Date.now(),
    })
    this.#run({ mode: 'explain_differently', event_id: eventId })
  }

  async retry(assistantId) {
    if (this.busy) return
    const i = this.messages.findIndex((m) => m.id === assistantId)
    // only the latest answer can be retried: re-running an older one would reorder history
    if (i === -1 || i !== this.messages.length - 1) return
    const failed = this.messages[i]
    this.messages.splice(i, 1)
    this.#run(failed.request)
  }

  stopAnswer() {
    this.#abort?.abort('stopped')
  }

  async #run(request) {
    this.busy = true
    const aid = tmpId('a')
    this.messages.push({
      id: aid, key: aid, role: 'assistant', text: '', status: 'pending', mode: request.mode,
      adaptation: null, error: null, model: null, created: Date.now(), request,
    })
    const msg = this.messages[this.messages.length - 1]
    const userMsg = findLast(this.messages, (m) => m.role === 'user')
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
          msg.model = meta.model
          msg.adaptation = meta.adaptation
          msg.status = 'streaming'
          if (userMsg && userMsg.id.startsWith('tmp_')) userMsg.id = meta.user_message.id
        },
        onDelta: (t) => {
          pending += t
          schedule()
        },
        onDone: (d) => {
          flush()
          msg.status = 'done'
          msg.model = d.model
          msg.ttft_ms = d.ttft_ms
          msg.elapsed_ms = d.elapsed_ms
          msg.finish_reason = d.finish_reason
        },
        onError: (err) => {
          flush()
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
    try {
      await api.resetSession(this.sessionId)
      this.#clearLocal()
      if (this.sim.enabled) this.sim.value = 0.1
      this.toast('ok', 'Demo reset — chat, signal state, cooldown and timeline cleared.')
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

  setAutoAdapt(on) {
    this.autoAdapt = on
    writePref('autoAdapt', on)
  }

  setSimulation(enabled) {
    this.sim.enabled = enabled
    if (enabled) this.sim.value = 0.1
    this.vision.setSimulation(enabled)
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
