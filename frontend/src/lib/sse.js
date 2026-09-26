/**
 * Incremental Server-Sent-Events parser for a fetch() body stream.
 * Handles events split across network chunks, CRLF line endings and
 * multi-line `data:` fields. Returns completed events; keeps the tail.
 */
export function createSSEParser() {
  let buffer = ''
  return {
    /** @param {string} chunk @returns {{event: string, data: string}[]} */
    push(chunk) {
      buffer += chunk.replace(/\r\n?/g, '\n')
      const out = []
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        let event = 'message'
        const data = []
        for (const line of block.split('\n')) {
          if (!line || line.startsWith(':')) continue
          const colon = line.indexOf(':')
          const field = colon === -1 ? line : line.slice(0, colon)
          let value = colon === -1 ? '' : line.slice(colon + 1)
          if (value.startsWith(' ')) value = value.slice(1)
          if (field === 'event') event = value
          else if (field === 'data') data.push(value)
        }
        if (data.length) out.push({ event, data: data.join('\n') })
      }
      return out
    },
    get pending() {
      return buffer
    },
  }
}
