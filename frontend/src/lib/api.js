import { createSSEParser } from './sse.js'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function jsonOrThrow(res) {
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(body.message || `HTTP ${res.status}`)
    err.code = body.code || `http_${res.status}`
    err.status = res.status
    throw err
  }
  return body
}

export async function getHealth(deep = false, signal) {
  const res = await fetch(`/api/health${deep ? '?deep=1' : ''}`, { cache: 'no-store', signal })
  return jsonOrThrow(res)
}

export async function getState(sessionId) {
  const res = await fetch(`/api/session/${sessionId}/state`, { cache: 'no-store' })
  return jsonOrThrow(res)
}

export async function interruptSession(sessionId) {
  const res = await fetch('/api/session/interrupt', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ session_id: sessionId }),
  })
  return jsonOrThrow(res)
}

export async function resetSession(sessionId) {
  const res = await fetch('/api/session/reset', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ session_id: sessionId }),
  })
  return jsonOrThrow(res)
}

/**
 * POST /api/chat and consume the SSE stream.
 * Guarantees exactly one terminal callback (onDone, onInterrupted or onError): network failures,
 * HTTP errors, a missing terminal event and a silent connection (idle watchdog)
 * all become onError — the UI can never stay in "thinking".
 */
export async function streamChat(body, { onMeta, onDelta, onDone, onInterrupted, onError, signal, idleMs = 25000 } = {}) {
  let finished = false
  const finish = (fn, arg) => {
    if (finished) return
    finished = true
    fn?.(arg)
  }
  const ctrl = new AbortController()
  const abortFromCaller = () => ctrl.abort(signal.reason ?? 'aborted')
  signal?.addEventListener('abort', abortFromCaller, { once: true })
  let idleTimer = null
  let idleFired = false
  const armIdle = () => {
    clearTimeout(idleTimer)
    idleTimer = setTimeout(() => {
      idleFired = true
      ctrl.abort('idle')
    }, idleMs)
  }

  try {
    armIdle()
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
      signal: ctrl.signal,
    })
    if (!res.ok || !res.body) {
      const info = await res.json().catch(() => ({}))
      finish(onError, {
        code: info.code || `http_${res.status}`,
        message: info.message || `The backend answered HTTP ${res.status}.`,
        retryable: res.status >= 500 || res.status === 429,
        status: res.status,
      })
      return
    }
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
    const parser = createSSEParser()
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      armIdle()
      for (const ev of parser.push(value)) {
        let data
        try {
          data = JSON.parse(ev.data)
        } catch {
          continue
        }
        if (ev.event === 'meta') onMeta?.(data)
        else if (ev.event === 'delta') onDelta?.(data.text ?? '')
        else if (ev.event === 'done') finish(onDone, data)
        else if (ev.event === 'interrupted') finish(onInterrupted ?? onDone, data)
        else if (ev.event === 'error') finish(onError, data)
      }
    }
    finish(onError, { code: 'incomplete', message: 'The answer stream ended unexpectedly.', retryable: true })
  } catch (e) {
    if (idleFired) {
      finish(onError, { code: 'client_timeout', message: 'No response from the backend for too long.', retryable: true })
    } else if (signal?.aborted) {
      finish(onError, { code: 'stopped', message: 'Stopped.', retryable: true })
    } else {
      finish(onError, {
        code: 'network',
        message: 'Cannot reach the ExtraHorizon backend. Is it running?',
        retryable: true,
      })
    }
  } finally {
    clearTimeout(idleTimer)
    signal?.removeEventListener('abort', abortFromCaller)
  }
}
