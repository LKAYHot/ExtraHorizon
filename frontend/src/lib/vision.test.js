// VisionController regression tests with stubbed browser APIs (node environment).
// Adapted from the independent review's harness: both orders of "camera ready" vs
// "server hello" must lead to frames being sent, and a camera toggled while a
// permission request is pending must never keep capturing.
import { afterEach, describe, expect, it } from 'vitest'

const store = new Map([['eh.cameraConsent', 'true'], ['eh.camera', 'true']])
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) }
globalThis.location = { protocol: 'http:', host: '127.0.0.1:8765', hostname: '127.0.0.1' }
globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} }
globalThis.window = { isSecureContext: true }

const sockets = []
class FakeWS {
  constructor(url) {
    this.url = url
    this.readyState = 0
    this.sent = []
    sockets.push(this)
  }
  send(d) {
    this.sent.push(d)
  }
  close() {
    this.readyState = 3
  }
  open() {
    this.readyState = 1
    this.onopen?.()
  }
  msg(obj) {
    this.onmessage?.({ data: JSON.stringify(obj) })
  }
  drop() {
    this.readyState = 3
    this.onclose?.({ code: 1006 })
  }
  frames() {
    return this.sent.filter((d) => typeof d !== 'string')
  }
}
globalThis.WebSocket = FakeWS

const pending = [] // resolvers of getUserMedia calls, in call order
function makeStream(name) {
  const track = { name, stopped: false, addEventListener() {}, stop() { this.stopped = true } }
  return { track, getTracks: () => [track], getVideoTracks: () => [track] }
}
Object.defineProperty(globalThis, 'navigator', {
  value: { mediaDevices: { getUserMedia: () => new Promise((resolve) => pending.push(resolve)) } },
  configurable: true,
})
globalThis.OffscreenCanvas = class {
  constructor(w, h) {
    this.width = w
    this.height = h
  }
  getContext() {
    return { drawImage() {} }
  }
  async convertToBlob() {
    return new Blob([new Uint8Array(64)])
  }
}

const video = () => ({ readyState: 4, videoWidth: 640, videoHeight: 480, srcObject: null, play: () => Promise.resolve() })
const hello = {
  type: 'hello', session_id: 's', boot_id: 'b', client_is_loopback: true,
  vision: { available: true, reason: null }, config: { max_fps: 12 },
}
const makeApp = () => ({
  sessionId: '00000000-0000-4000-8000-000000000000', sim: { enabled: false, value: 0.1 },
  onHello() {}, onSnapshot() {}, onTick() {}, onEvent() {}, onMarker() {}, onServerReset() {}, onSocketClosed() {}, toast() {},
})
const settle = (ms = 350) => new Promise((r) => setTimeout(r, ms))

const { VisionController } = await import('./vision.svelte.js')

describe('VisionController', () => {
  afterEach(() => {
    sockets.length = 0
    pending.length = 0
  })

  it('sends frames when hello arrives before the camera is ready', async () => {
    const v = new VisionController(makeApp())
    v.attachVideo(video())
    v.start()
    const ws = sockets.at(-1)
    ws.open()
    ws.msg(hello)
    pending.shift()(makeStream('cam'))
    await settle()
    expect(v.camera).toBe('active')
    expect(ws.frames().length).toBeGreaterThan(0)
    v.stop()
  })

  it('sends frames when the camera is ready before the socket opens (refresh with remembered consent)', async () => {
    const v = new VisionController(makeApp())
    v.attachVideo(video())
    v.start()
    const ws = sockets.at(-1)
    pending.shift()(makeStream('cam')) // camera first …
    await settle()
    expect(ws.frames().length).toBe(0) // nothing can be sent yet
    ws.open() // … backend accepts late …
    ws.msg(hello) // … and says vision is available
    await settle()
    expect(ws.frames().length).toBeGreaterThan(0)
    v.stop()
  })

  it('resumes frames after a vision error followed by a reconnect', async () => {
    const v = new VisionController(makeApp())
    v.attachVideo(video())
    v.start()
    let ws = sockets.at(-1)
    ws.open()
    ws.msg(hello)
    pending.shift()(makeStream('cam'))
    await settle()
    ws.msg({ type: 'error', code: 'vision_busy', message: 'busy' })
    expect(v.backend.available).toBe(false)
    ws.drop()
    await settle(700) // reconnect back-off
    ws = sockets.at(-1)
    ws.open()
    ws.msg(hello)
    await settle()
    expect(ws.frames().length).toBeGreaterThan(0)
    v.stop()
  })

  it('never keeps capturing when the camera is toggled while permission is pending', async () => {
    const v = new VisionController(makeApp())
    v.attachVideo(video())
    v.startCamera() // request #1 pending
    v.stopCamera()
    v.startCamera() // request #2 pending
    const first = makeStream('first')
    const second = makeStream('second')
    pending[0](first)
    pending[1](second)
    await settle(50)
    expect(first.track.stopped).toBe(true) // the stale stream is released immediately
    v.stopCamera()
    expect(second.track.stopped).toBe(true)
    expect(v.camera).toBe('off')
  })
})
