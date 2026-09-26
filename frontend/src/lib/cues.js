// Fish Audio voice cues written by the tutor: "[huffy and flustered] Hmph." — performed by
// the text-to-speech, never read aloud. The chat shows them as small stage directions.

const CUE = /\[([^[\]\n]{1,90})\]/g
const TIMING = new Set(['break', 'long-break', 'long break', 'emphasis', 'pause', 'short pause'])
// a sound effect names the sound as its first word ("sighing", "laughs softly", "clear throat");
// "huffy and flustered" is a delivery, not the sound "huffs"
const SOUND_WORD = /^(laugh(s|ing)?|sigh(s|ing)?|gasp(s|ing)?|groan(s|ing)?|chuckl(e|es|ing)|giggl(e|es|ing)|sob(s|bing)?|cry(ing)?|pant(s|ing)?|yawn(s|ing)?|snor(e|es|ing)|sniff(s|ing)?|huffs|huffing|scoff(s|ing)?|clears?|clearing)$/

export function cueKind(cue) {
  const c = cue.trim().toLowerCase()
  if (TIMING.has(c)) return 'timing'
  if (SOUND_WORD.test(c.split(/[\s,]+/)[0] ?? '')) return 'sound'
  return 'mood'
}

/** Text without cues (captions, previews, copy). */
export function stripCues(text) {
  return (text ?? '')
    .replace(CUE, ' ')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/ +([,.!?;:])/g, '$1')
    .trim()
}

/** While a reply streams, hide a cue that has started but not closed yet ("[huffy an"). */
export function hideOpenCue(text) {
  return (text ?? '').replace(/\[[^\]\n]{0,90}$/, '')
}

/** The cues of a text in order (for the "how she said it" summary). */
export function listCues(text) {
  return [...(text ?? '').matchAll(CUE)].map((m) => m[1].trim()).filter((c) => cueKind(c) !== 'timing')
}

/** markdown-it plugin: [cue] (not a [link](url)) → <span class="cue …">. */
export function cuePlugin(md) {
  md.inline.ruler.before('link', 'eh_cue', (state, silent) => {
    if (state.src.charCodeAt(state.pos) !== 0x5b /* [ */) return false
    const m = /^\[([^[\]\n]{1,90})\](?![([])/.exec(state.src.slice(state.pos))
    if (!m) return false
    if (!silent) {
      const t = state.push('eh_cue', 'span', 0)
      t.content = m[1].trim()
    }
    state.pos += m[0].length
    return true
  })
  md.renderer.rules.eh_cue = (tokens, idx) => {
    const cue = tokens[idx].content
    const kind = cueKind(cue)
    if (kind === 'timing') return '<span class="cue timing" aria-hidden="true"></span>'
    return `<span class="cue ${kind}" title="Voice cue — performed by the voice, not read aloud">${md.utils.escapeHtml(cue)}</span>`
  }
}
