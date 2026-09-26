// Browser audio for the voice conversation: microphone capture (PCM16 24 kHz frames for
// the backend's voice detection + speech-to-text) and gapless playback of the tutor's
// streamed voice (PCM16 44.1 kHz chunks from Fish Audio, relayed by the backend).

export const MIC_RATE = 24000
export const MIC_FRAME = 960 // 40 ms per WebSocket message

// AudioWorklet: float → int16 frames (+ RMS for the level meter). Resamples by linear
// interpolation (after a light low-pass) only when the browser could not give us a
// 24 kHz context — Chrome/Edge resample natively.
const WORKLET = `
class EhMic extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const o = (options && options.processorOptions) || {}
    this.frame = o.frame || 960
    this.ratio = sampleRate / (o.target || 24000)
    this.alpha = this.ratio > 1.05 ? 1 - Math.exp((-2 * Math.PI * 10000) / sampleRate) : 1
    this.lp = 0
    this.pos = 0
    this.prev = 0
    this.out = new Int16Array(this.frame)
    this.n = 0
    this.sum = 0
  }
  push(s) {
    s = s < -1 ? -1 : s > 1 ? 1 : s
    this.out[this.n++] = s < 0 ? s * 32768 : s * 32767
    this.sum += s * s
    if (this.n === this.frame) {
      this.port.postMessage({ pcm: this.out.buffer, rms: Math.sqrt(this.sum / this.frame) }, [this.out.buffer])
      this.out = new Int16Array(this.frame)
      this.n = 0
      this.sum = 0
    }
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (!ch || !ch.length) return true
    if (this.ratio === 1) {
      for (let i = 0; i < ch.length; i++) this.push(ch[i])
      return true
    }
    const x = new Float32Array(ch.length)
    for (let i = 0; i < ch.length; i++) x[i] = this.lp += this.alpha * (ch[i] - this.lp)
    let p = this.pos
    const last = x.length - 1
    while (p < last) {
      const i = Math.floor(p)
      const f = p - i
      const a = i < 0 ? this.prev : x[i]
      this.push(a + (x[i + 1] - a) * f)
      p += this.ratio
    }
    this.pos = p - x.length
    this.prev = x[last]
    return true
  }
}
registerProcessor('eh-mic', EhMic)
`

let workletUrl = null
function workletModuleUrl() {
  workletUrl ??= URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' }))
  return workletUrl
}

export class MicError extends Error {
  constructor(kind, message) {
    super(message)
    this.kind = kind // denied | unavailable | unsupported
  }
}

const GUM_ERRORS = {
  NotAllowedError: ['denied', 'Microphone permission was denied. Allow it in the address bar, then retry.'],
  SecurityError: ['denied', 'The browser blocked microphone access for this page.'],
  NotFoundError: ['unavailable', 'No microphone was found on this device.'],
  NotReadableError: ['unavailable', 'The microphone is busy (used by another app?).'],
  OverconstrainedError: ['unavailable', 'No microphone matches the requested settings.'],
  AbortError: ['unavailable', 'The microphone could not start.'],
}

/** Microphone → 40 ms PCM16 frames at 24 kHz. Browser echo cancellation, noise suppression
 *  and auto gain stay on (the backend adds voice detection; OpenAI adds noise reduction). */
export class MicCapture {
  constructor({ onFrame, onLevel, onEnded, deviceId = '' } = {}) {
    this.onFrame = onFrame
    this.onLevel = onLevel
    this.onEnded = onEnded
    this.deviceId = deviceId // '' = the system default microphone
    this.fellBack = false // the chosen device was gone → the default was used
    this.label = ''
    this.stream = null
    this.ctx = null
    this.node = null
  }

  static constraints(deviceId) {
    const audio = { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    if (deviceId) audio.deviceId = { exact: deviceId }
    return { audio, video: false }
  }

  async start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new MicError('unsupported', window.isSecureContext ? 'This browser has no microphone API.' : 'Microphone access needs localhost or HTTPS.')
    }
    let stream
    try {
      try {
        stream = await navigator.mediaDevices.getUserMedia(MicCapture.constraints(this.deviceId))
      } catch (e) {
        // the chosen microphone was unplugged / renamed: use the default instead of failing
        if (!this.deviceId || !['OverconstrainedError', 'NotFoundError'].includes(e?.name)) throw e
        this.fellBack = true
        stream = await navigator.mediaDevices.getUserMedia(MicCapture.constraints(''))
      }
    } catch (e) {
      const [kind, msg] = GUM_ERRORS[e?.name] ?? ['unavailable', `The microphone could not start (${e?.name || e}).`]
      throw new MicError(kind, msg)
    }
    this.stream = stream
    this.label = stream.getAudioTracks()[0]?.label ?? ''
    let ctx = null
    let src = null
    try {
      ctx = new AudioContext({ sampleRate: MIC_RATE, latencyHint: 'interactive' })
      src = ctx.createMediaStreamSource(stream)
    } catch {
      // e.g. Firefox cannot mix a device stream into a context of another rate
      await ctx?.close().catch(() => {})
      ctx = new AudioContext({ latencyHint: 'interactive' })
      src = ctx.createMediaStreamSource(stream)
    }
    this.ctx = ctx
    await ctx.audioWorklet.addModule(workletModuleUrl())
    const node = new AudioWorkletNode(ctx, 'eh-mic', { processorOptions: { target: MIC_RATE, frame: MIC_FRAME } })
    node.port.onmessage = (e) => {
      this.onFrame?.(e.data.pcm)
      this.onLevel?.(e.data.rms)
    }
    src.connect(node)
    const mute = ctx.createGain() // the worklet must be pulled by the graph; nothing is heard
    mute.gain.value = 0
    node.connect(mute).connect(ctx.destination)
    this.node = node
    if (ctx.state === 'suspended') await ctx.resume().catch(() => {})
    stream.getAudioTracks()[0]?.addEventListener('ended', () => {
      if (this.stream === stream) this.onEnded?.()
    })
  }

  stop() {
    this.stream?.getTracks().forEach((t) => t.stop())
    this.stream = null
    if (this.node) this.node.port.onmessage = null
    this.node = null
    this.ctx?.close().catch(() => {})
    this.ctx = null
  }
}

/** Decode one binary voice frame from the backend: 4-byte big-endian turn number + PCM16LE. */
export function parseVoiceFrame(buf) {
  if (!(buf instanceof ArrayBuffer) || buf.byteLength < 6) return null
  const turn = new DataView(buf).getUint32(0)
  const samples = (buf.byteLength - 4) >> 1
  return { turn, pcm: new Int16Array(buf, 4, samples) }
}

const PREBUFFER_S = 0.09 // jitter cushion at the start of a burst (Fish streams in chunks)

/**
 * Gapless streaming player. Chunks of the same turn are scheduled back to back; a newer
 * turn cuts the older one; ``stop(turn)`` / ``stopAll()`` silence instantly (barge-in).
 * ``onState({playing, turn, kind})`` fires when playback starts or ends.
 */
export class TtsPlayer {
  constructor({ onState } = {}) {
    this.onState = onState
    this.ctx = null
    this.out = null
    this.sampleRate = 44100
    this.nextTime = 0
    this.current = 0
    this.kind = null
    this.stopped = new Set()
    this.sources = new Set()
    this.playing = false
    this.volume = 1
    this.timer = null
  }

  /** Create/resume the output context (call from a user gesture when possible). */
  unlock() {
    if (!this.ctx) {
      this.ctx = new AudioContext({ latencyHint: 'interactive' })
      this.out = this.ctx.createGain()
      this.out.gain.value = this.volume
      this.out.connect(this.ctx.destination)
    }
    if (this.ctx.state === 'suspended') this.ctx.resume().catch(() => {})
    return this.ctx
  }

  begin(turn, kind, sampleRate) {
    if (sampleRate) this.sampleRate = sampleRate
    if (this.stopped.has(turn) || turn < this.current) return
    if (turn > this.current) this.#cut(turn)
    this.kind = kind
    this.#emit()
  }

  push(turn, pcm) {
    if (this.stopped.has(turn) || turn < this.current || !pcm?.length) return
    if (turn > this.current) this.#cut(turn)
    const ctx = this.unlock()
    const buf = ctx.createBuffer(1, pcm.length, this.sampleRate)
    const ch = buf.getChannelData(0)
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.connect(this.out)
    const now = ctx.currentTime
    if (this.nextTime < now + 0.01) this.nextTime = now + PREBUFFER_S
    src.start(this.nextTime)
    this.nextTime += buf.duration
    const entry = { src, turn }
    this.sources.add(entry)
    src.onended = () => {
      this.sources.delete(entry)
      this.#check()
    }
    this.#check()
  }

  stop(turn) {
    this.stopped.add(turn)
    for (const e of [...this.sources]) if (e.turn === turn) this.#kill(e)
    if (turn === this.current) this.nextTime = 0
    this.#check()
  }

  stopAll() {
    if (this.current) this.stopped.add(this.current)
    for (const e of [...this.sources]) this.#kill(e)
    this.nextTime = 0
    this.#check()
  }

  /** Forget turn numbering (a new server session numbers its turns from 1 again). */
  reset() {
    for (const e of [...this.sources]) this.#kill(e)
    this.stopped.clear()
    this.current = 0
    this.nextTime = 0
    this.kind = null
    this.#check()
  }

  setVolume(v) {
    this.volume = v
    if (this.out) this.out.gain.value = v
  }

  get remaining() {
    return this.ctx ? Math.max(0, this.nextTime - this.ctx.currentTime) : 0
  }

  close() {
    this.stopAll()
    clearTimeout(this.timer)
    this.ctx?.close().catch(() => {})
    this.ctx = null
  }

  #cut(turn) {
    for (const e of [...this.sources]) this.#kill(e)
    this.nextTime = 0
    this.current = turn
  }

  #kill(e) {
    this.sources.delete(e)
    e.src.onended = null
    try {
      e.src.stop()
    } catch {
      /* not started yet / already stopped */
    }
    e.src.disconnect()
  }

  #check() {
    const playing = this.sources.size > 0
    if (playing !== this.playing) {
      this.playing = playing
      this.#emit()
    }
  }

  #emit() {
    this.onState?.({ playing: this.playing, turn: this.current, kind: this.kind })
  }
}
