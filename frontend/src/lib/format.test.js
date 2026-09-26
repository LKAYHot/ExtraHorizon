import { describe, expect, it } from 'vitest'
import { TALK_LABEL, isLoopbackHost, pct, reasonText, signed } from './format.js'

describe('isLoopbackHost', () => {
  it('only treats loopback names as local', () => {
    for (const h of ['localhost', '127.0.0.1', '127.1.2.3', '[::1]', 'app.localhost']) expect(isLoopbackHost(h)).toBe(true)
    for (const h of ['192.168.1.5', 'extrahorizon.example', '10.0.0.2']) expect(isLoopbackHost(h)).toBe(false)
  })
})

describe('reasonText', () => {
  it('explains unknown states in plain words', () => {
    expect(reasonText('multiple_faces')).toMatch(/ambiguous/)
    expect(reasonText('head_turned')).toMatch(/turned/)
    expect(reasonText(null)).toBe('No reading')
    expect(reasonText('some_new_reason')).toBe('some new reason')
  })
})

describe('number formatting', () => {
  it('formats percentages and signed values, unknown as a dash', () => {
    expect(pct(0.625)).toBe('63%')
    expect(pct(null)).toBe('—')
    expect(signed(0.4)).toBe('+0.40')
    expect(signed(-0.25)).toBe('-0.25')
    expect(signed(undefined)).toBe('—')
  })
  it('has a label for every conversational state', () => {
    for (const s of ['idle', 'listening', 'hearing', 'thinking', 'speaking']) expect(TALK_LABEL[s]).toBeTruthy()
  })
})
