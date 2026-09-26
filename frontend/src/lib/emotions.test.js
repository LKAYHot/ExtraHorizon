import { describe, expect, it } from 'vitest'
import { COLOR, EMOTIONS, LABEL, ROWS, SIM_PRESETS, STACK, arousalWord, probsArray, strengthWord, valenceWord } from './emotions.js'

// the documented dark categorical steps (dataviz reference palette) — no eyeballed colours
const DOCUMENTED_DARK = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767']

describe('emotion palette and orders', () => {
  it('covers exactly the eight model classes everywhere', () => {
    for (const list of [STACK, ROWS, SIM_PRESETS]) expect([...list].sort()).toEqual([...EMOTIONS].sort())
    expect(Object.keys(LABEL).sort()).toEqual([...EMOTIONS].sort())
  })
  it('uses each documented colour once (colour follows the emotion)', () => {
    expect(Object.values(COLOR).sort()).toEqual([...DOCUMENTED_DARK].sort())
  })
  it('keeps the validated stack order (checked with validate_palette.js, dark, adjacent)', () => {
    expect(STACK).toEqual(['neutral', 'surprise', 'sadness', 'happiness', 'contempt', 'disgust', 'fear', 'anger'])
  })
})

describe('helpers', () => {
  it('orders tick probabilities like the backend samples', () => {
    const probs = Object.fromEntries(EMOTIONS.map((k, i) => [k, i / 10]))
    expect(probsArray(probs)).toEqual(EMOTIONS.map((_, i) => i / 10))
    expect(probsArray(null)).toBeNull()
  })
  it('describes strength and mood in words, like the prompt note', () => {
    expect(strengthWord(0.7)).toBe('clearly')
    expect(strengthWord(0.45)).toBe('mostly')
    expect(strengthWord(0.3)).toBe('somewhat')
    expect(valenceWord(0.5)).toBe('positive')
    expect(valenceWord(-0.5)).toBe('negative')
    expect(arousalWord(0.5)).toBe('high energy')
    expect(arousalWord(-0.5)).toBe('low energy')
    expect(valenceWord(null)).toBeNull()
  })
})
