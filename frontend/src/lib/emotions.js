// The eight expression classes of the on-device emotion model (AffectNet order, as sent
// by the backend in timeline samples) and how the UI shows them.
export const EMOTIONS = ['anger', 'contempt', 'disgust', 'fear', 'happiness', 'neutral', 'sadness', 'surprise']

export const LABEL = {
  anger: 'Angry',
  contempt: 'Unimpressed',
  disgust: 'Disgusted',
  fear: 'Anxious',
  happiness: 'Happy',
  neutral: 'Neutral',
  sadness: 'Sad',
  surprise: 'Surprised',
}

export const NOUN = {
  anger: 'anger',
  contempt: 'contempt',
  disgust: 'disgust',
  fear: 'anxiety',
  happiness: 'happiness',
  neutral: 'calm',
  sadness: 'sadness',
  surprise: 'surprise',
}

// Colours: the documented dark categorical steps of the dataviz reference palette, each
// following its emotion everywhere (bars, stack, circumplex dot, legend). The STACK order
// (bottom → top) was chosen by enumerating orderings and validating them with the skill's
// validate_palette.js on this app's chart surface #0e1629, dark mode, adjacent pairs:
// lightness band, chroma floor, contrast ≥ 3:1 all PASS; worst adjacent CVD ΔE 9.4 (≥ 8
// target), normal-vision ΔE 19.3 (≥ 15 floor).
export const COLOR = {
  neutral: '#199e70',
  surprise: '#d95926',
  sadness: '#3987e5',
  happiness: '#c98500',
  contempt: '#d55181',
  disgust: '#008300',
  fear: '#9085e9',
  anger: '#e66767',
}
export const STACK = ['neutral', 'surprise', 'sadness', 'happiness', 'contempt', 'disgust', 'fear', 'anger']
// the bar list reads from pleasant to unpleasant (fixed order: rows never jump around)
export const ROWS = ['happiness', 'surprise', 'neutral', 'sadness', 'fear', 'anger', 'disgust', 'contempt']

export const SIM_PRESETS = ['happiness', 'surprise', 'neutral', 'sadness', 'fear', 'anger', 'disgust', 'contempt']

/** probs as sent in ticks ({anger: .1, …}) → array in EMOTIONS order (or null). */
export function probsArray(probs) {
  if (!probs) return null
  return EMOTIONS.map((e) => probs[e] ?? 0)
}

export function strengthWord(p) {
  if (p == null) return ''
  return p >= 0.6 ? 'clearly' : p >= 0.4 ? 'mostly' : 'somewhat'
}

export function valenceWord(v) {
  if (v == null) return null
  return v > 0.25 ? 'positive' : v < -0.25 ? 'negative' : 'neutral'
}

export function arousalWord(a) {
  if (a == null) return null
  return a > 0.35 ? 'high energy' : a < -0.15 ? 'low energy' : 'moderate energy'
}

export function seconds(s) {
  if (s == null) return ''
  if (s < 1) return 'just now'
  if (s < 60) return `${Math.round(s)} s`
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`
}
