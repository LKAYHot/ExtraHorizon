// VoiceController with stubbed browser APIs: the live socket protocol → UI state + player.
import { describe, expect, it } from 'vitest'

const store = new Map()
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) }
globalThis.location = { protocol: 'http:', host: '127.0.0.1:8765', hostname: '127.0.0.1' }
globalThis.performance ??= { now: () => Date.now() }

class FakeCtx {
  constructor() { this.currentTime = 0; this.state = 'running'; this.destination = {} }
  createGain() { return { gain: { value: 1 }, connect() { return this } } }
  createBuffer(_c, n, sr) { const d = new Float32Array(n); return { duration: n / sr, getChannelData: () => d } }
  createBufferSource() { return { connect() {}, disconnect() {}, start() {}, stop() {}, onended: null } }
  resume() { return Promise.resolve() }
  close() { return Promise.resolve() }
}
globalThis.AudioContext = FakeCtx

const sockets = []
class FakeWS {
  constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this) }
  send(d) { this.sent.push(d) }
  close() { this.readyState = 3 }
  open() { this.readyState = 1; this.onopen?.() }
  msg(obj) { this.onmessage?.({ data: JSON.stringify(obj) }) }
  bin(turn, samples = 441) {
    const buf = new ArrayBuffer(4 + samples * 2)
    new DataView(buf).setUint32(0, turn)
    this.onmessage?.({ data: buf })
  }
  json() { return this.sent.filter((d) => typeof d === 'string').map((d) => JSON.parse(d)) }
}
globalThis.WebSocket = FakeWS

const { VoiceController } = await import('./voice.svelte.js')
const settle = (ms) => new Promise((r) => setTimeout(r, ms))

function setup() {
  store.clear()
  const turns = []
  const app = {
    sessionId: '00000000-0000-4000-8000-000000000000', bootId: null, busy: false, lost: 0,
    onVoiceTurn: (m) => turns.push(m), onAssistantInterrupted() {}, toast() {},
    onVoiceSocketLost() { this.lost++ },
  }
  const v = new VoiceController(app)
  v.start()
  const ws = sockets.at(-1)
  ws.open()
  ws.msg({ type: 'hello', boot_id: 'b', persona: 'Rika', config: {}, tts: { state: 'ok' }, stt: {}, fillers: 'ready' })
  return { v, ws, turns, app }
}

describe('VoiceController', () => {
  it('tells the backend whether to speak answers as soon as the socket opens', () => {
    const { v, ws } = setup()
    expect(ws.json()[0]).toEqual({ type: 'voice_out', on: true })
    v.setSpeaker(false)
    expect(ws.json().at(-1)).toEqual({ type: 'voice_out', on: false })
    v.stop()
  })

  it('lets the learner turn interruptions off: sent on connect and on change, remembered, and said when held', () => {
    const { v, ws } = setup()
    expect(ws.json()[1]).toEqual({ type: 'interruptions', on: true }) // the default: talking over her stops her
    expect(v.canInterrupt).toBe(true)
    v.setInterruptions(false)
    expect(ws.json().at(-1)).toEqual({ type: 'interruptions', on: false })
    expect(store.get('eh.interruptions')).toBe('false') // remembered for the next visit
    expect(v.canInterrupt).toBe(false)
    ws.msg({ type: 'held' }) // someone spoke during her answer: she goes on
    expect(v.notice.kind).toBe('held')
    expect(v.notice.text).toContain('Rika finishes first')
    v.stop()
    // a server with EH_BARGE_IN=false never allows it
    const again = setup()
    again.v.setInterruptions(true)
    again.ws.msg({ type: 'hello', boot_id: 'b', persona: 'Rika', config: { barge_in: false }, tts: {}, stt: {}, fillers: 'ready' })
    expect(again.v.canInterrupt).toBe(false)
    again.v.stop()
  })

  it('shows the live transcript, joining a sentence the learner paused in', () => {
    const { v, ws } = setup()
    ws.msg({ type: 'vad', speaking: true, utt: 1, continues: null, barge: false })
    expect(v.hearing).toBe(true)
    ws.msg({ type: 'stt', utt: 1, text: 'Explain recursion to me', final: false })
    expect(v.caption).toEqual({ text: 'Explain recursion to me', final: false })
    ws.msg({ type: 'vad', speaking: false, utt: 1, turn_no: 1 })
    expect(v.hearing).toBe(false)
    ws.msg({ type: 'vad', speaking: true, utt: 2, continues: 1, barge: false })
    ws.msg({ type: 'stt', utt: 2, text: 'and give an example', final: false })
    expect(v.caption.text).toBe('Explain recursion to me and give an example')
    ws.msg({ type: 'heard', utt: 2, turn_no: 2, text: 'Explain recursion to me and give an example.' })
    expect(v.caption).toEqual({ text: 'Explain recursion to me and give an example.', final: true })
    v.stop()
  })

  it('plays her voice, reports playback, and stops at once on barge-in', async () => {
    const { v, ws } = setup()
    ws.msg({ type: 'audio_begin', turn_no: 3, kind: 'answer', sample_rate: 44100 })
    ws.bin(3)
    expect(v.playing).toBe(true)
    expect(ws.json().some((m) => m.type === 'playback' && m.playing === true)).toBe(true)
    ws.msg({ type: 'barge_in', by: 'voice' })
    expect(v.playing).toBe(false)
    await settle(300) // a short gap is not "stopped"; after the debounce it is
    expect(ws.json().at(-1)).toEqual({ type: 'playback', playing: false })
    v.stop()
  })

  it('ignores voice audio when answers are muted', () => {
    const { v, ws } = setup()
    v.setSpeaker(false)
    ws.msg({ type: 'audio_begin', turn_no: 4, kind: 'answer', sample_rate: 44100 })
    ws.bin(4)
    expect(v.playing).toBe(false)
    v.stop()
  })

  it('shows fillers while she thinks and notices like "you stopped her"', () => {
    const { v, ws } = setup()
    ws.msg({ type: 'filler', turn_no: 5, text: 'Hmm...' })
    expect(v.filler).toBe('Hmm...')
    ws.msg({ type: 'audio_begin', turn_no: 5, kind: 'answer', sample_rate: 44100 })
    expect(v.filler).toBe('')
    ws.msg({ type: 'stt_ignored', utt: 9, turn_no: 6, reason: 'stop', text: 'Wait, stop.' })
    expect(v.notice.text).toMatch(/stopped Rika/)
    v.stop()
  })

  it('forwards turn events to the chat and clears the caption when the answer starts', () => {
    const { v, ws, turns } = setup()
    ws.msg({ type: 'heard', utt: 1, turn_no: 1, text: 'Hi' })
    ws.msg({ type: 'turn', event: 'meta', turn_no: 1, data: { user_message: { id: 'u', text: 'Hi' } } })
    expect(turns[0].event).toBe('meta')
    expect(v.caption.text).toBe('')
    v.interrupt()
    expect(ws.json().at(-1)).toEqual({ type: 'interrupt' })
    v.stop()
  })

  it('a new connection resets turn numbering, so answers of a fresh server session still play', () => {
    const { v, ws } = setup()
    ws.msg({ type: 'audio_begin', turn_no: 9, kind: 'answer', sample_rate: 44100 })
    ws.bin(9)
    ws.msg({ type: 'hello', boot_id: 'b2', persona: 'Rika', config: {}, tts: {}, stt: {} })
    ws.msg({ type: 'audio_begin', turn_no: 1, kind: 'answer', sample_rate: 44100 })
    ws.bin(1)
    expect(v.playing).toBe(true)
    expect(v.playingTurn).toBe(1)
    v.stop()
  })

  it('a dropped socket ends the spoken turn in the chat and a superseded one turns the mic off', () => {
    const { v, ws, app } = setup()
    v.mic = 'on'
    ws.readyState = 3
    ws.onclose?.({ code: 4001 })
    expect(app.lost).toBe(1)
    expect(v.socket).toBe('superseded')
    expect(v.mic).toBe('off')
    v.stop()
  })

  it('lists microphones, remembers the choice and uses it', async () => {
    const devices = [
      { kind: 'audioinput', deviceId: 'default', label: 'Default' },
      { kind: 'audioinput', deviceId: 'communications', label: 'Communications' },
      { kind: 'audioinput', deviceId: 'dev-1', label: '' },
      { kind: 'audioinput', deviceId: 'dev-2', label: 'USB Headset' },
      { kind: 'videoinput', deviceId: 'cam', label: 'Camera' },
    ]
    Object.defineProperty(globalThis, 'navigator', {
      value: { mediaDevices: { enumerateDevices: async () => devices, addEventListener() {}, removeEventListener() {} } },
      configurable: true,
    })
    const { v } = setup()
    await v.refreshDevices()
    expect(v.devices).toEqual([{ deviceId: 'dev-1', label: 'Microphone 1' }, { deviceId: 'dev-2', label: 'USB Headset' }])
    await v.setDevice('dev-2')
    expect(v.deviceId).toBe('dev-2')
    expect(store.get('eh.micDevice')).toBe('"dev-2"')
    v.stop()
  })
})

describe('MicCapture device choice', () => {
  it('asks for the chosen microphone and falls back to the default one if it is gone', async () => {
    const { MicCapture } = await import('./audio.js')
    expect(MicCapture.constraints('dev-2').audio.deviceId).toEqual({ exact: 'dev-2' })
    expect(MicCapture.constraints('').audio.deviceId).toBeUndefined()
    const asked = []
    const track = { label: 'Built-in microphone', addEventListener() {}, stop() {} }
    Object.defineProperty(globalThis, 'navigator', {
      value: {
        mediaDevices: {
          getUserMedia: async (c) => {
            asked.push(c.audio.deviceId ?? null)
            if (c.audio.deviceId) throw Object.assign(new Error('gone'), { name: 'OverconstrainedError' })
            return { getAudioTracks: () => [track], getTracks: () => [track] }
          },
        },
      },
      configurable: true,
    })
    globalThis.window = { isSecureContext: true }
    globalThis.AudioWorkletNode = class { constructor() { this.port = {} } connect(x) { return x } }
    const proto = globalThis.AudioContext.prototype
    proto.createMediaStreamSource = () => ({ connect() {} })
    Object.defineProperty(proto, 'audioWorklet', { value: { addModule: async () => {} }, configurable: true })
    const cap = new MicCapture({ deviceId: 'dev-9' })
    await cap.start()
    expect(asked).toEqual([{ exact: 'dev-9' }, null])
    expect(cap.fellBack).toBe(true)
    expect(cap.label).toBe('Built-in microphone')
    cap.stop()
  })
})
