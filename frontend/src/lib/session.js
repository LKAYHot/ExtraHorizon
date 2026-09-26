// One session per browser tab: sessionStorage survives a refresh of the tab but a
// new tab gets a new id, so tabs never share engine state, history or cooldowns.
const KEY = 'eh.session'

function uuid() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID()
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

export function getSessionId() {
  try {
    const existing = sessionStorage.getItem(KEY)
    if (existing && /^[0-9a-f-]{36}$/.test(existing)) return existing
    const id = uuid()
    sessionStorage.setItem(KEY, id)
    return id
  } catch {
    return uuid() // storage blocked: still works, just not across refreshes
  }
}

/**
 * "Duplicate tab" copies sessionStorage, so two tabs could share one session (history,
 * engine, reset). Before using the id, ask other tabs over a BroadcastChannel whether one
 * of them already owns it; if so, this tab takes a fresh id. Keeps answering for its id.
 */
export async function claimSessionId(timeoutMs = 150) {
  let id = getSessionId()
  if (typeof BroadcastChannel === 'undefined') return id
  const ch = new BroadcastChannel('eh.sessions')
  const taken = await new Promise((resolve) => {
    const onMsg = (e) => {
      if (e.data?.type === 'mine' && e.data.id === id) resolve(true)
    }
    ch.addEventListener('message', onMsg)
    ch.postMessage({ type: 'who', id })
    setTimeout(() => {
      ch.removeEventListener('message', onMsg)
      resolve(false)
    }, timeoutMs)
  })
  if (taken) {
    id = uuid()
    try {
      sessionStorage.setItem(KEY, id)
    } catch {
      /* storage blocked — the in-memory id is still unique */
    }
  }
  ch.addEventListener('message', (e) => {
    if (e.data?.type === 'who' && e.data.id === id) ch.postMessage({ type: 'mine', id })
  })
  return id
}

export function readPref(key, fallback) {
  try {
    const v = localStorage.getItem(`eh.${key}`)
    return v === null ? fallback : JSON.parse(v)
  } catch {
    return fallback
  }
}

export function writePref(key, value) {
  try {
    localStorage.setItem(`eh.${key}`, JSON.stringify(value))
  } catch {
    /* private mode — preference just isn't remembered */
  }
}
