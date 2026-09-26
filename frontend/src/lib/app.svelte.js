import * as api from './api.js'
import { probsArray } from './emotions.js'
import { isLoopbackHost } from './format.js'
import { claimSessionId, getSessionId, readPref, writePref } from './session.js'
import { VisionController } from './vision.svelte.js'
import { VoiceController } from './voice.svelte.js'

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
        created: Date.now(),
      })
      return
    }
    const msg = this.#assistantOfTurn(turn)
    if (!msg) return
    if (event === 'delta') {
      this.#pendingText.set(turn, (this.#pendingText.get(turn) ?? '') + (data.text ?? ''))
      this.#scheduleFlush()
      return
    }
    this.#flushNow()
    if (event === 'done' || event === 'interrupted') {
      msg.status = 'done'
      msg.model = data.model
      msg.ttft_ms = data.ttft_ms
      msg.elapsed_ms = data.elapsed_ms
      msg.interrupted = !!data.interrupted
    } else if (event === 'error') {
      msg.status = 'error'
      msg.error = data
    } else if (event === 'dropped') {
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
  async send(text) {
    text = (text ?? '').trim()
    if (!text || this.busy) return false
    this.voice.unlockAudio() // the click/Enter is the user gesture browsers require for audio
    await this.#whenReady()
    if (this.busy) return false
    const id = tmpId('u')
    this.messages.push({ id, key: id, role: 'user', text, source: 'text', status: 'done', created: Date.now() })
    this.#run({ message: text, subject: this.subject })
    return true
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
        onDone: (d) => {
          flush()
          msg.status = 'done'
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
        },
        onError: (err) => {
          flush()
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
