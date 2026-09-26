import { beforeEach, describe, expect, it } from 'vitest'

class FakeCtx {
  constructor() {
    this.currentTime = 0
    this.state = 'running'
    this.destination = {}
    this.started = []
  }
  createGain() {
    return { gain: { value: 1 }, connect() { return this } }
  }
  createBuffer(_ch, n, sr) {
    const data = new Float32Array(n)
    return { duration: n / sr, getChannelData: () => data }
  }
  createBufferSource() {
    const src = {
      buffer: null, onended: null, stopped: false,
      connect() {}, disconnect() {},
      start: (t) => { src.at = t; this.started.push(src) },
      stop() { src.stopped = true },
    }
    return src
  }
  resume() { return Promise.resolve() }
  close() { return Promise.resolve() }
}
globalThis.AudioContext = FakeCtx

const { parseVoiceFrame, TtsPlayer } = await import('./audio.js')

function frame(turn, samples) {
  const buf = new ArrayBuffer(4 + samples * 2)
  new DataView(buf).setUint32(0, turn)
  return buf
}
const pcm = (n) => new Int16Array(n).fill(1000)

describe('parseVoiceFrame', () => {
  it('reads the big-endian turn number and the PCM16 samples', () => {
    const f = parseVoiceFrame(frame(258, 3))
    expect(f.turn).toBe(258)
    expect(f.pcm.length).toBe(3)
  })
  it('rejects frames without audio', () => {
    expect(parseVoiceFrame(new ArrayBuffer(4))).toBeNull()
    expect(parseVoiceFrame('text')).toBeNull()
  })
})

describe('TtsPlayer', () => {
  let states
  let p
  beforeEach(() => {
    states = []
    p = new TtsPlayer({ onState: (s) => states.push(s) })
  })

  it('schedules the chunks of one turn back to back (gapless)', () => {
    p.begin(1, 'answer', 44100)
    p.push(1, pcm(4410))
    p.push(1, pcm(4410))
    const [a, b] = p.ctx.started
    expect(b.at).toBeCloseTo(a.at + 0.1, 6)
    expect(states.at(-1)).toMatchObject({ playing: true, turn: 1, kind: 'answer' })
  })

  it('a newer turn cuts the older one; late chunks of the old turn are dropped', () => {
    p.push(1, pcm(100))
    const first = p.ctx.started[0]
    p.push(2, pcm(100))
    expect(first.stopped).toBe(true)
    p.push(1, pcm(100))
    expect(p.ctx.started.length).toBe(2)
  })

  it('stop(turn) silences it at once and ignores what still arrives for it', () => {
    p.push(3, pcm(100))
    p.stop(3)
    expect(p.ctx.started[0].stopped).toBe(true)
    p.push(3, pcm(100))
    expect(p.ctx.started.length).toBe(1)
    expect(states.at(-1).playing).toBe(false)
  })

  it('reports the end of playback when the last chunk has played', () => {
    p.push(4, pcm(100))
    p.push(4, pcm(100))
    for (const s of p.ctx.started) s.onended?.()
    expect(states.at(-1).playing).toBe(false)
  })

  it('stopAll silences everything (barge-in)', () => {
    p.push(5, pcm(100))
    p.push(5, pcm(100))
    p.stopAll()
    expect(p.ctx.started.every((s) => s.stopped)).toBe(true)
    p.push(5, pcm(100))
    expect(p.ctx.started.length).toBe(2)
  })
})

describe('TtsPlayer.reset', () => {
  it('accepts turn 1 again after a reset (a fresh server session numbers turns from 1)', () => {
    const p = new TtsPlayer()
    p.push(12, pcm(100))
    p.stop(12)
    p.reset()
    p.push(1, pcm(100))
    expect(p.ctx.started.length).toBe(2)
    expect(p.playing).toBe(true)
  })
})
