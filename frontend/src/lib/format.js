export const REASONS = {
  no_face: 'No face in view',
  multiple_faces: 'Several faces — ambiguous, not used',
  face_too_small: 'Face too far away',
  head_turned: 'Head turned away',
  too_dark: 'Too dark',
  overexposed: 'Too bright',
  bad_frame: 'Unreadable frame',
  analysis_failed: 'Analysis failed on this frame',
  calibrating: 'Calibrating neutral baseline',
  camera_off: 'Camera is off',
  camera_denied: 'Camera permission denied',
  camera_unavailable: 'Camera unavailable',
  camera_ended: 'Camera disconnected',
  camera_paused: 'Paused (tab in background)',
  camera_disconnected: 'Vision connection closed',
  vision_disconnected: 'Vision connection closed',
  camera_initializing: 'Camera starting…',
  camera_vision_unavailable: 'Vision processing unavailable',
  source_switched: 'Signal source switched',
  no_value: 'No reading',
}

export function reasonText(reason) {
  if (!reason) return 'No reading'
  return REASONS[reason] ?? reason.replaceAll('_', ' ')
}

export function fmt2(x) {
  return x == null || Number.isNaN(x) ? '—' : x.toFixed(2)
}

export function clock(ms) {
  if (!ms) return ''
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function ago(ms, now = Date.now()) {
  const s = Math.max(0, Math.round((now - ms) / 1000))
  if (s < 2) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.round(s / 60)
  return `${m} min ago`
}

export function isLoopbackHost(hostname) {
  return hostname === 'localhost' || hostname === '::1' || hostname === '[::1]' || /^127\./.test(hostname) || hostname.endsWith('.localhost')
}

/** The offer shown under the latest answer — derived only from backend state. */
export function currentOffer(messages, events, busy) {
  if (busy) return null
  let last = null
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'assistant') {
      last = messages[i]
      break
    }
  }
  if (!last || last.status !== 'done') return null
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (e.kind === 'possible_confusion' && e.status === 'offered' && e.answer_id === last.id) return { event: e, answerId: last.id }
  }
  return null
}
