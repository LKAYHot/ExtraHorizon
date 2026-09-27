import { MicCapture, TtsPlayer, parseVoiceFrame } from './audio.js'
import { readPref, writePref } from './session.js'

/**
 * The voice conversation: the /api/live WebSocket, the microphone and the tutor's voice.
 *
 * Mic (hands-free): 40 ms PCM16 frames stream to the LOCAL backend, which detects speech
 * (Silero VAD) and forwards only speech to OpenAI's realtime transcription. The backend
 * decides turn-taking (fillers, barge-in, "wait, stop", continued sentences) and streams
 * the tutor's Fish Audio voice back as binary frames tagged with the turn number.
 *
 * The socket is open whenever the page is — typed questions are spoken through it too.
 */
export class VoiceController {
  socket = $state('closed') // connecting | open | closed | superseded
  info = $state.raw(null) // hello: {config, tts, stt, vad, fillers, persona}
  speaker = $state(readPref('speaker', true)) // speak answers aloud
  interruptions = $state(readPref('interruptions', true)) // talking over her stops her (off: she always finishes)
  consented = $state(readPref('micConsent', false))
  mic = $state('off') // off | starting | on | denied | unavailable | error
  micMessage = $state('')
  level = $state(0) // mic loudness 0..1 (meter)
  hearing = $state(false) // the backend hears the learner speaking
  caption = $state({ text: '', final: false }) // live transcript of the current question
  filler = $state('') // "Hmm..." while it plays
  playing = $state(false)
  playingTurn = $state(0)
  playingKind = $state(null) // filler | answer
  notice = $state(null) // {kind, text} — "You stopped Rika", "Ignored echo"
  lastLatencyMs = $state(null) // end of speech → first answer audio (last voice turn)
  devices = $state.raw([]) // microphones: [{deviceId, label}]
  deviceId = $state(readPref('micDevice', '')) // '' = the system default
  deviceLabel = $state('') // the microphone actually in use

  #app
  #ws = null
  #capture = null
  #player
  #stopped = false
  #reconnectTimer = null
  #reconnectDelay = 500
  #pingTimer = null
  #playbackTimer = null
  #reportedPlaying = false
  #utt = null
  #prefix = '' // text of the earlier part of a sentence the learner paused in
  #speechEndAt = 0
  #measureTurn = 0
  #noticeTimer = null
  #errorShownAt = 0

  constructor(app) {
    this.#app = app
    this.#player = new TtsPlayer({ onState: (s) => this.#onPlayerState(s) })
  }

  // ------------------------------------------------------------------ lifecycle
  start() {
    this.#stopped = false
    this.connect()
    this.#pingTimer = setInterval(() => this.#send({ type: 'ping', t: Date.now() }), 15000)
    navigator.mediaDevices?.addEventListener?.('devicechange', this.#onDeviceChange)
    this.refreshDevices()
  }

  stop() {
    this.#stopped = true
    clearInterval(this.#pingTimer)
    clearTimeout(this.#reconnectTimer)
    navigator.mediaDevices?.removeEventListener?.('devicechange', this.#onDeviceChange)
    this.#stopMic()
    this.#player.close()
    this.#ws?.close()
  }

  // ------------------------------------------------------------------ microphone choice
  /** List the microphones (names appear once the browser has microphone permission). */
  async refreshDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) return
    try {
      const all = await navigator.mediaDevices.enumerateDevices()
      const inputs = all.filter((d) => d.kind === 'audioinput' && d.deviceId && d.deviceId !== 'default' && d.deviceId !== 'communications')
      this.devices = inputs.map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Microphone ${i + 1}` }))
    } catch {
      /* no permission yet / not supported — the default microphone still works */
    }
  }

  #onDeviceChange = () => {
    this.refreshDevices()
  }

  /** Use another microphone (''= system default); switches live if the mic is on. */
  async setDevice(id) {
    this.deviceId = id
    writePref('micDevice', id)
    if (this.mic !== 'on') return
    const old = this.#capture
    this.#capture = null
    old?.stop()
    await this.#startCapture()
  }

  connect() {
    clearTimeout(this.#reconnectTimer)
    if (this.#ws && this.#ws.readyState <= 1) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/api/live?session_id=${this.#app.sessionId}`)
    ws.binaryType = 'arraybuffer'
    this.#ws = ws
    this.socket = 'connecting'
    ws.onopen = () => {
      if (this.#ws !== ws) return
      this.socket = 'open'
      this.#reconnectDelay = 500
      this.#send({ type: 'voice_out', on: this.speaker })
      this.#send({ type: 'interruptions', on: this.interruptions })
      if (this.mic === 'on') this.#send({ type: 'mic', on: true })
      this.#reportedPlaying = false
    }
    ws.onmessage = (e) => (typeof e.data === 'string' ? this.#onText(e.data) : this.#onAudio(e.data))
    ws.onclose = (e) => {
      if (this.#ws !== ws) return
      this.#ws = null
      this.hearing = false
      // the server cancels a spoken turn whose socket is gone: never leave it "thinking"
      this.#player.stopAll()
      this.filler = ''
      this.#app.onVoiceSocketLost?.()
      if (e.code === 4001 || this.socket === 'superseded') {
        this.socket = 'superseded'
        this.stopMic()
        return
      }
      this.socket = 'closed'
      if (!this.#stopped) {
        this.#reconnectTimer = setTimeout(() => this.connect(), this.#reconnectDelay)
        this.#reconnectDelay = Math.min(5000, this.#reconnectDelay * 2)
      }
    }
  }

  reconnectNow() {
    this.#reconnectDelay = 500
    if (this.socket === 'superseded') this.socket = 'closed'
    this.connect()
  }

  #send(obj) {
    if (this.#ws?.readyState === 1) this.#ws.send(JSON.stringify(obj))
  }

  // ------------------------------------------------------------------ controls
  /** Call from a user gesture (send button, mic button): browsers only allow audio after one. */
  unlockAudio() {
    if (this.speaker) this.#player.unlock()
  }

  /** May talking over her interrupt her? (The server's EH_BARGE_IN=false turns it off for everyone.) */
  get canInterrupt() {
    return this.interruptions && this.info?.config?.barge_in !== false
  }

  setInterruptions(on) {
    this.interruptions = on
    writePref('interruptions', on)
    this.#send({ type: 'interruptions', on })
  }

  /** She keeps her turn (interruptions are off): say so where the voice notices appear. */
  flashHeld() {
    this.#flash('held', `${this.info?.persona ?? 'She'} finishes first — interruptions are off (Stop or Esc cuts her off).`)
  }

  setSpeaker(on) {
    this.speaker = on
    writePref('speaker', on)
    if (on) this.#player.unlock()
    else this.#player.stopAll()
    this.#send({ type: 'voice_out', on })
  }

  /** First explicit opt-in (after reading the microphone disclosure). */
  consent() {
    this.consented = true
    writePref('micConsent', true)
    return this.startMic()
  }

  toggleMic() {
    if (this.mic === 'on' || this.mic === 'starting') this.stopMic()
    else return this.startMic()
  }

  async startMic() {
    if (!this.consented || this.mic === 'on' || this.mic === 'starting') return
    this.unlockAudio()
    this.mic = 'starting'
    this.micMessage = ''
    if (await this.#startCapture()) this.#send({ type: 'mic', on: true })
  }

  /** Open the chosen microphone and stream it; the server's listening session is untouched. */
  async #startCapture() {
    const cap = new MicCapture({
      deviceId: this.deviceId,
      onFrame: (pcm) => {
        if (this.#capture === cap && this.#ws?.readyState === 1) this.#ws.send(pcm)
      },
      onLevel: (rms) => {
        // fast attack, slow release; ~ -50 dBFS → 0, -10 dBFS → 1
        const db = 20 * Math.log10(Math.max(rms, 1e-5))
        const v = Math.min(1, Math.max(0, (db + 50) / 40))
        this.level = v > this.level ? v : this.level * 0.8 + v * 0.2
      },
      onEnded: () => {
        this.#stopMic()
        this.mic = 'unavailable'
        this.micMessage = 'The microphone was disconnected or access was revoked.'
      },
    })
    this.#capture = cap
    try {
      await cap.start()
    } catch (e) {
      if (this.#capture !== cap) return false
      this.#capture = null
      cap.stop()
      this.#stopMicOnServer()
      this.mic = e.kind === 'denied' ? 'denied' : 'unavailable'
      this.micMessage = e.message
      return false
    }
    if (this.#capture !== cap) {
      cap.stop() // turned off (or switched again) while the permission prompt was open
      return false
    }
    this.mic = 'on'
    this.deviceLabel = cap.label
    if (cap.fellBack) {
      this.deviceId = ''
      writePref('micDevice', '')
      this.#app.toast?.('warn', 'The chosen microphone is not available — using the default one.')
    }
    this.refreshDevices() // names are visible now that the browser has permission
    return true
  }

  #stopMicOnServer() {
    if (this.mic === 'on') this.#send({ type: 'mic', on: false })
  }

  stopMic() {
    this.#stopMic()
    this.mic = 'off'
    this.micMessage = ''
  }

  #stopMic() {
    const cap = this.#capture
    this.#capture = null
    cap?.stop()
    this.level = 0
    this.hearing = false
    if (this.mic === 'on' || this.mic === 'starting') this.#send({ type: 'mic', on: false })
    if (!this.#app.busy) this.caption = { text: '', final: false }
  }

  /** Stop button / Esc: silence her now and cancel what she is saying or thinking. */
  interrupt() {
    this.#player.stopAll()
    this.filler = ''
    this.#send({ type: 'interrupt' })
  }

  /** Local cleanup after a reset (the server also sends a reset). */
  reset() {
    this.#player.reset()
    this.caption = { text: '', final: false }
    this.filler = ''
    this.notice = null
    this.#prefix = ''
  }

  // ------------------------------------------------------------------ inbound
  #onAudio(buf) {
    const f = parseVoiceFrame(buf)
    if (!f || !this.speaker) return
    if (f.turn === this.#measureTurn && this.#speechEndAt && this.playingKind === 'answer') {
      this.lastLatencyMs = Math.round(performance.now() - this.#speechEndAt)
      this.#speechEndAt = 0
    }
    this.#player.push(f.turn, f.pcm)
  }

  #onText(raw) {
    let m
    try {
      m = JSON.parse(raw)
    } catch {
      return
    }
    const app = this.#app
    switch (m.type) {
      case 'hello':
        this.info = m
        // a new connection may belong to a fresh server session whose turns start at 1 again
        this.#player.reset()
        app.onHello?.(m) // a new boot_id → the tab clears its view (once, whichever socket sees it first)
        break
      case 'vad':
        if (m.speaking) {
          this.hearing = true
          if (m.continues != null && this.caption.text) this.#prefix = this.caption.text
          else this.#prefix = ''
          this.#utt = m.utt
          this.caption = { text: this.#prefix, final: false }
          if (m.barge) this.#player.stopAll()
        } else {
          this.hearing = false
          this.#speechEndAt = performance.now()
          this.#measureTurn = m.turn_no
        }
        break
      case 'stt':
        if (m.utt === this.#utt) {
          const text = [this.#prefix, m.text].filter(Boolean).join(' ')
          this.caption = { text, final: false }
        }
        break
      case 'heard':
        this.caption = { text: m.text, final: true }
        this.#prefix = ''
        break
      case 'stt_ignored':
        if (m.reason === 'stop') this.#flash('stop', `You stopped ${this.info?.persona ?? 'the tutor'}.`)
        else if (m.reason === 'echo') this.#flash('echo', 'Ignored: that sounded like the tutor’s own voice.')
        if (m.utt === this.#utt || m.reason !== 'empty') this.caption = { text: '', final: false }
        break
      case 'filler':
        this.filler = m.text
        break
      case 'audio_begin':
        if (m.kind === 'answer') this.filler = ''
        this.#player.begin(m.turn_no, m.kind, m.sample_rate)
        this.playingKind = m.kind
        this.playingTurn = m.turn_no
        break
      case 'audio_end':
        break
      case 'audio_stop':
        this.#player.stop(m.turn_no)
        if (m.turn_no === this.playingTurn) this.filler = ''
        break
      case 'barge_in':
        this.#player.stopAll()
        this.filler = ''
        break
      case 'held':
        this.flashHeld()
        break
      case 'turn':
        if (m.event === 'meta') this.caption = { text: '', final: false }
        app.onVoiceTurn(m)
        break
      case 'assistant_interrupted':
        app.onAssistantInterrupted(m.message_id)
        break
      case 'reset':
        this.reset()
        break
      case 'superseded':
        this.socket = 'superseded'
        break
      case 'tts_error':
        this.#rateLimitedToast('warn', `Voice output problem: ${m.message}`)
        break
      case 'stt_error':
        this.#rateLimitedToast('warn', `Speech recognition problem: ${m.message}`)
        break
      case 'error':
        if (m.code === 'vad_unavailable' || m.code === 'stt_unavailable') {
          this.#stopMic()
          this.mic = 'error'
          this.micMessage = m.message
        } else {
          console.warn('[live]', m.code, m.message)
        }
        break
    }
  }

  #onPlayerState({ playing, turn, kind }) {
    this.playing = playing
    this.playingTurn = turn
    this.playingKind = kind
    if (!playing && kind === 'filler') this.filler = ''
    // tell the backend (barge-in rules apply while her voice is audible); a short gap
    // between two chunks is not "stopped"
    clearTimeout(this.#playbackTimer)
    if (playing && !this.#reportedPlaying) {
      this.#reportedPlaying = true
      this.#send({ type: 'playback', playing: true })
    } else if (!playing && this.#reportedPlaying) {
      this.#playbackTimer = setTimeout(() => {
        if (this.playing) return
        this.#reportedPlaying = false
        this.#send({ type: 'playback', playing: false })
      }, 250)
    }
  }

  #flash(kind, text) {
    clearTimeout(this.#noticeTimer)
    this.notice = { kind, text }
    this.#noticeTimer = setTimeout(() => (this.notice = null), 4000)
  }

  #rateLimitedToast(kind, text) {
    const now = Date.now()
    if (now - this.#errorShownAt < 8000) return
    this.#errorShownAt = now
    this.#app.toast(kind, text)
  }
}
