import { describe, expect, it } from 'vitest'
import { createSSEParser } from './sse.js'

describe('createSSEParser', () => {
  it('parses events split at arbitrary chunk boundaries', () => {
    const wire =
      'event: meta\ndata: {"a":1}\n\n' +
      'event: delta\ndata: {"text":"Rec"}\n\n' +
      'event: delta\ndata: {"text":"ursion\\n\\nis"}\n\n' +
      'event: done\ndata: {"ok":true}\n\n'
    for (const size of [1, 2, 3, 7, 16, wire.length]) {
      const p = createSSEParser()
      const events = []
      for (let i = 0; i < wire.length; i += size) events.push(...p.push(wire.slice(i, i + size)))
      expect(events.map((e) => e.event)).toEqual(['meta', 'delta', 'delta', 'done'])
      expect(JSON.parse(events[2].data).text).toBe('ursion\n\nis')
      expect(p.pending).toBe('')
    }
  })

  it('accepts CRLF, comments and multi-line data', () => {
    const p = createSSEParser()
    const events = p.push(': keep-alive\r\n\r\nevent: error\r\ndata: line1\r\ndata: line2\r\n\r\n')
    expect(events).toEqual([{ event: 'error', data: 'line1\nline2' }])
  })

  it('keeps an incomplete event until its terminator arrives', () => {
    const p = createSSEParser()
    expect(p.push('event: delta\ndata: {"text":"x"}\n')).toEqual([])
    expect(p.push('\n')).toEqual([{ event: 'delta', data: '{"text":"x"}' }])
  })
})
