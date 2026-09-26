import { writePref, readPref } from './session.js'

const CAMERA_ERRORS = {
  NotAllowedError: ['denied', 'Camera permission was denied. Allow it in the address bar, then retry.'],
  SecurityError: ['denied', 'The browser blocked camera access for this page.'],
  NotFoundError: ['unavailable', 'No camera was found on this device.'],
  OverconstrainedError: ['unavailable', 'No camera matches the requested settings.'],
  NotReadableError: ['unavailable', 'The camera is busy (used by another app?).'],
  AbortError: ['unavailable', 'The camera could not start.'],
}

/**
 * Camera capture + the /api/vision WebSocket.
 *
 * Frames: the browser downsizes the live video to `frame_width` px, encodes JPEG and
 * sends it to the LOCAL backend. Exactly one frame is in flight: the next one is sent
 * after the backend acknowledges the previous one (a `tick` with the same seq) or after
 * a 1.5 s timeout, capped at `max_fps` — the pipeline adapts to the machine's speed and
 * never builds a backlog. Nothing is recorded or stored in the browser.
 */
export class VisionController {
  camera = $state('off') // off | initializing | active | denied | unavailable | ended
  cameraMessage = $state('')
  socket = $state('closed') // connecting | open | closed | superseded
  backend = $state.raw({ available: null, reason: null })
  clientIsLoopback = $state(null)
  config = $state.raw({
    max_fps: 12, frame_width: 480, jpeg_quality: 0.75, alpha: 0.2, reference_fps: 10,
    threshold: 0.65, hold_s: 2, cooldown_s: 15, calibration_s: 2.5, relief_threshold: 0.45,
  })
  fps = $state(0)
  latencyMs = $state(null)
  // informed consent (shown in the camera card) is required once before the camera ever starts;
  // after that the camera follows the user's last on/off choice
  consented = $state(readPref('cameraConsent', false))
  wanted = $state(readPref('camera', true))

  #app
  #ws = null
  #stream = null
  #video = null
  #canvas = null
  #ctx = null
  #seq = 0
  #inflight = null
  #inflightAt = 0
  #lastSend = 0
  #frameTimer = null
  #watchdog = null
  #simTimer = null
  #reconnectTimer = null
  #reconnectDelay = 500
  #stopped = false
  #acks = []
  #gumToken = 0

  constructor(app) {
    this.#app = app
  }

  // ------------------------------------------------------------------ lifecycle
  start() {
    this.#stopped = false
    this.connect()
    if (this.consented && this.wanted) this.startCamera()
    document.addEventListener('visibilitychange', this.#onVisibility)
    this.#watchdog = setInterval(() => {
      if (this.#inflight !== null && performance.now() - this.#inflightAt > 1500) {
        this.#inflight = null // lost ack — never stall the stream
        this.#scheduleFrame()
      }
    }, 500)
  }

  stop() {
    this.#stopped = true
    document.removeEventListener('visibilitychange', this.#onVisibility)
    clearInterval(this.#watchdog)
    clearTimeout(this.#frameTimer)
    clearTimeout(this.#reconnectTimer)
    this.#stopSim()
    this.#releaseStream()
    this.#ws?.close()
  }

  // ------------------------------------------------------------------ socket
  connect() {
    clearTimeout(this.#reconnectTimer)
    if (this.#ws && this.#ws.readyState <= 1) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/api/vision?session_id=${this.#app.sessionId}`)
    ws.binaryType = 'arraybuffer'
    this.#ws = ws
    this.socket = 'connecting'
    ws.onopen = () => {
      if (this.#ws !== ws) return
      this.socket = 'open'
      this.#reconnectDelay = 500
      this.#inflight = null
      this.#sendJSON({ type: 'camera', status: this.camera === 'active' && document.hidden ? 'paused' : this.camera })
      this.#syncSim()
      this.#scheduleFrame()
    }
    ws.onmessage = (e) => this.#onMessage(e.data)
    ws.onclose = (e) => {
      if (this.#ws !== ws) return
      this.#ws = null
      this.#inflight = null
      this.#stopSim()
      this.#app.onSocketClosed()
      if (e.code === 4001 || this.socket === 'superseded') {
        this.socket = 'superseded' // this session was opened in another tab
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

  #sendJSON(obj) {
    if (this.#ws?.readyState === 1) this.#ws.send(JSON.stringify(obj))
  }

  #onMessage(raw) {
    let m
    try {
      m = JSON.parse(raw)
    } catch {
      return
    }
    const app = this.#app
    switch (m.type) {
      case 'hello':
        this.backend = m.vision
        this.clientIsLoopback = m.client_is_loopback
        this.config = { ...this.config, ...m.config }
        app.onHello(m)
        // the camera may have become active before the server said vision is available
        // (refresh with remembered consent, dev server, reconnect) — start the frame loop now
        this.#scheduleFrame()
        if (!m.vision?.available && this.camera === 'active') {
          app.toast('warn', 'Vision processing is unavailable — chat still works.')
        }
        break
      case 'snapshot':
        app.onSnapshot(m)
        break
      case 'tick':
        this.#onTick(m)
        app.onTick(m)
        break
      case 'event':
      case 'event_update':
        app.onEvent(m.event)
        break
      case 'marker':
        app.onMarker(m.marker)
        break
      case 'reset':
        app.onServerReset(m)
        break
      case 'superseded':
        this.socket = 'superseded'
        break
      case 'error':
        if (m.code === 'vision_unavailable' || m.code === 'vision_busy') this.backend = { available: false, reason: m.message }
        else console.warn('[vision]', m.code, m.message)
        break
    }
  }

  // ------------------------------------------------------------------ camera
  attachVideo(el) {
    this.#video = el
    if (el && this.#stream) {
      el.srcObject = this.#stream
      el.play().catch(() => {})
    }
  }

  /** First explicit opt-in from the camera card (after reading the disclosure). */
  enableCamera() {
    this.consented = true
    writePref('cameraConsent', true)
    return this.startCamera()
  }

  async startCamera() {
    if (!this.consented) return
    this.wanted = true
    writePref('camera', true)
    if (this.camera === 'active' || this.camera === 'initializing') return
    if (!navigator.mediaDevices?.getUserMedia) {
      this.#setCamera(
        'unavailable',
        window.isSecureContext ? 'This browser has no camera API.' : 'Camera access needs localhost or HTTPS.',
      )
      return
    }
    this.#setCamera('initializing', '')
    const token = ++this.#gumToken
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30, max: 30 }, facingMode: 'user' },
        audio: false,
      })
      if (token !== this.#gumToken || !this.wanted || this.#stopped) {
        stream.getTracks().forEach((t) => t.stop()) // a stale request (turned off / re-requested meanwhile)
        return
      }
      this.#releaseStream() // never leave an older stream running
      this.#stream = stream
      stream.getVideoTracks()[0]?.addEventListener('ended', () => {
        if (this.#stream !== stream) return
        this.#stream = null
        this.#setCamera('ended', 'The camera was disconnected or access was revoked.')
      })
      if (this.#video) {
        this.#video.srcObject = stream
        await this.#video.play().catch(() => {})
      }
      this.#setCamera('active', '')
      this.#scheduleFrame()
    } catch (e) {
      if (token !== this.#gumToken) return // superseded by a newer request
      const [status, msg] = CAMERA_ERRORS[e?.name] ?? ['unavailable', `The camera could not start (${e?.name || e}).`]
      this.#setCamera(status, msg)
    }
  }

  stopCamera() {
    this.wanted = false
    this.#gumToken++ // any pending getUserMedia result is now stale
    writePref('camera', false)
    this.#releaseStream()
    this.#setCamera('off', '')
  }

  recalibrate() {
    this.#sendJSON({ type: 'calibrate' })
  }

  #releaseStream() {
    this.#stream?.getTracks().forEach((t) => t.stop())
    this.#stream = null
    if (this.#video) this.#video.srcObject = null
  }

  #setCamera(status, message) {
    this.camera = status
    this.cameraMessage = message
    if (status !== 'active') {
      this.#inflight = null
      this.fps = 0
    }
    this.#sendJSON({ type: 'camera', status })
  }

  #onVisibility = () => {
    if (this.camera !== 'active') return
    this.#sendJSON({ type: 'camera', status: document.hidden ? 'paused' : 'active' })
    if (!document.hidden) this.#scheduleFrame()
  }

  // ------------------------------------------------------------------ frames
  #canSend() {
    return (
      this.camera === 'active' &&
      this.socket === 'open' &&
      this.backend.available === true &&
      !document.hidden &&
      !!this.#video
    )
  }

  #scheduleFrame() {
    clearTimeout(this.#frameTimer)
    if (!this.#canSend() || this.#inflight !== null) return
    const minInterval = 1000 / Math.max(1, this.config.max_fps || 12)
    const wait = Math.max(0, this.#lastSend + minInterval - performance.now())
    this.#frameTimer = setTimeout(() => this.#captureAndSend(), wait)
  }

  async #captureAndSend() {
    if (!this.#canSend() || this.#inflight !== null) return
    const v = this.#video
    if (v.readyState < 2 || !v.videoWidth) {
      this.#frameTimer = setTimeout(() => this.#scheduleFrame(), 120)
      return
    }
    const w = this.config.frame_width || 480
    const h = Math.round((w * v.videoHeight) / v.videoWidth)
    if (!this.#canvas) {
      this.#canvas = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(w, h) : document.createElement('canvas')
      this.#ctx = this.#canvas.getContext('2d', { alpha: false, desynchronized: true })
    }
    if (this.#canvas.width !== w || this.#canvas.height !== h) {
      this.#canvas.width = w
      this.#canvas.height = h
    }
    this.#ctx.drawImage(v, 0, 0, w, h)
    const quality = this.config.jpeg_quality || 0.75
    const seq = (this.#seq = (this.#seq + 1) >>> 0)
    this.#inflight = seq
    this.#inflightAt = performance.now()
    this.#lastSend = this.#inflightAt
    try {
      const blob = this.#canvas.convertToBlob
        ? await this.#canvas.convertToBlob({ type: 'image/jpeg', quality })
        : await new Promise((res) => this.#canvas.toBlob(res, 'image/jpeg', quality))
      const header = new Uint8Array(4)
      new DataView(header.buffer).setUint32(0, seq)
      const payload = await new Blob([header, blob]).arrayBuffer()
      if (this.#ws?.readyState === 1 && this.#inflight === seq) this.#ws.send(payload)
      else this.#inflight = null
    } catch {
      this.#inflight = null
      this.#frameTimer = setTimeout(() => this.#scheduleFrame(), 250)
    }
  }

  #onTick(m) {
    if (m.seq == null || this.#inflight === null || m.seq < this.#inflight) return
    const now = performance.now()
    this.latencyMs = Math.round(now - this.#inflightAt)
    this.#inflight = null
    this.#acks.push(now)
    while (this.#acks.length && now - this.#acks[0] > 2000) this.#acks.shift()
    this.fps = Math.round((this.#acks.length / 2) * 10) / 10
    this.#scheduleFrame()
  }

  // ------------------------------------------------------------------ labelled Demo simulation mode
  #syncSim() {
    const sim = this.#app.sim
    this.#stopSim()
    if (!sim.enabled) return
    const tick = () => this.#sendJSON({ type: 'sim', enabled: true, value: this.#app.sim.value })
    tick()
    this.#simTimer = setInterval(tick, 100)
  }

  #stopSim() {
    clearInterval(this.#simTimer)
    this.#simTimer = null
  }

  setSimulation(enabled) {
    if (!enabled) {
      this.#stopSim()
      this.#sendJSON({ type: 'sim', enabled: false })
      this.#scheduleFrame()
      return
    }
    this.#syncSim()
  }
}
