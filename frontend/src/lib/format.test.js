import { describe, expect, it } from 'vitest'
import { currentOffer, isLoopbackHost, reasonText } from './format.js'

const done = (id) => ({ id, role: 'assistant', status: 'done' })
const ev = (id, answer_id, status = 'offered', kind = 'possible_confusion') => ({ id, answer_id, status, kind })

describe('currentOffer', () => {
  it('offers only for the latest finished answer with an offered event', () => {
    const msgs = [{ id: 'u1', role: 'user' }, done('a1')]
    expect(currentOffer(msgs, [ev('e1', 'a1')], false)?.event.id).toBe('e1')
  })
  it('does not offer before an event, for used/expired events or other answers', () => {
    const msgs = [done('a1'), { id: 'u2', role: 'user' }, done('a2')]
    expect(currentOffer(msgs, [], false)).toBeNull()
    expect(currentOffer(msgs, [ev('e1', 'a1')], false)).toBeNull()
    expect(currentOffer(msgs, [ev('e2', 'a2', 'used')], false)).toBeNull()
    expect(currentOffer(msgs, [ev('e3', 'a2', 'offered', 'signal_decreased')], false)).toBeNull()
  })
  it('does not offer while an answer is streaming or after a failed answer', () => {
    expect(currentOffer([done('a1')], [ev('e1', 'a1')], true)).toBeNull()
    expect(currentOffer([{ id: 'a1', role: 'assistant', status: 'error' }], [ev('e1', 'a1')], false)).toBeNull()
  })
})

describe('isLoopbackHost', () => {
  it('only treats loopback names as local', () => {
    for (const h of ['localhost', '127.0.0.1', '127.1.2.3', '[::1]', 'app.localhost']) expect(isLoopbackHost(h)).toBe(true)
    for (const h of ['192.168.1.5', 'extrahorizon.example', '10.0.0.2']) expect(isLoopbackHost(h)).toBe(false)
  })
})

describe('reasonText', () => {
  it('explains unknown states in plain words', () => {
    expect(reasonText('multiple_faces')).toMatch(/ambiguous/)
    expect(reasonText(null)).toBe('No reading')
  })
})
