import { describe, expect, it } from 'vitest'
import { cueKind, hideOpenCue, listCues, stripCues } from './cues.js'

describe('Fish voice cues', () => {
  it('classifies cues', () => {
    expect(cueKind('huffy and flustered')).toBe('mood')
    expect(cueKind('sighing softly')).toBe('sound')
    expect(cueKind('clear throat')).toBe('sound')
    expect(cueKind('sighing')).toBe('sound')
    expect(cueKind('Laughing')).toBe('sound')
    expect(cueKind('break')).toBe('timing')
    expect(cueKind('long-break')).toBe('timing')
  })
  it('strips cues for captions and tidies spaces/punctuation', () => {
    expect(stripCues('[smug] Heh. [chuckling] You got it , baka.')).toBe('Heh. You got it, baka.')
    expect(stripCues('')).toBe('')
  })
  it('hides a cue that is still being streamed', () => {
    expect(hideOpenCue('Hmph. [huffy an')).toBe('Hmph. ')
    expect(hideOpenCue('Hmph. [huffy] Fine')).toBe('Hmph. [huffy] Fine')
  })
  it('lists the performed cues (not the pauses)', () => {
    expect(listCues('[proud] Right. [break] [soft] Good job.')).toEqual(['proud', 'soft'])
  })
})
