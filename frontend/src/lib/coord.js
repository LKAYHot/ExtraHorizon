// Utility-coordination analysis (backend coord/): colours, labels and formatting.
//
// Colours: two plans are compared at a time, so the map and the timeline need exactly two
// categorical hues that stay apart for every reader. Blue #3987e5 (plan A) and orange #d95926
// (plan B) are steps of the dataviz reference palette; validated with validate_palette.js
// --pairs all on the dark map surface #1b1c1e: lightness band, chroma floor, contrast ≥ 3:1
// PASS; CVD ΔE 26.8, normal-vision ΔE 31.8. Other plans are recessive gray context; overlaps are
// drawn in near-white (luminance, not hue) so they read on top of both.
export const PLAN_A = '#3987e5'
export const PLAN_B = '#d95926'
export const OTHER = '#6b7597'
export const OVERLAP = '#eef2ff'

export const CATEGORY = {
  both: { label: 'Close by and at the same time', short: 'Close + same time', rank: 0 },
  near: { label: 'Physically close', short: 'Close', rank: 1 },
  same_time: { label: 'Same time, nearby area', short: 'Same time', rank: 2 },
}

export const pairKey = (plans) => plans.join(' ↔ ')

const nf = new Intl.NumberFormat('en-US')
export const fmtNum = (n) => (n == null ? '—' : nf.format(Math.round(n)))

/** 0 → "intersect", 38 → "38 m", 1234 → "1.2 km". */
export function fmtDistance(m) {
  if (m == null) return '—'
  if (m <= 0) return 'intersect'
  if (m < 1000) return `${Math.round(m)} m`
  return `${(m / 1000).toFixed(1)} km`
}

/** Both scheduled → "together 121 days" (end dates count); apart → "184 days apart" or "back to back". */
export function fmtTiming(f) {
  if (f.overlap_days > 0) return `together ${fmtNum(f.overlap_days)} day${f.overlap_days === 1 ? '' : 's'}`
  if (!f.gap_days) return 'back to back'
  return `${fmtNum(f.gap_days)} day${f.gap_days === 1 ? '' : 's'} apart`
}

export function fmtDate(iso) {
  if (!iso) return '—'
  const d = new Date(`${iso}T00:00:00Z`)
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' })
}

/** The pair picker's "all pairs of plans". */
export const ALL_PAIRS = '*'

/** Findings between the two plans of a pair, in either order (all findings without a pair). */
export function findingsOfPair(report, key) {
  if (!report) return []
  if (!key || key === ALL_PAIRS) return report.findings
  const want = key.split(' ↔ ').sort().join(' ↔ ')
  return report.findings.filter((f) => [...f.plans].sort().join(' ↔ ') === want)
}

/** What the panel shows: the spotlight (what she just looked up or named), else the chosen pair. */
export function shownFindings(report, key, spot) {
  if (!report) return []
  if (spot?.ids?.length) {
    const want = new Set(spot.ids)
    return report.findings.filter((f) => want.has(f.id))
  }
  return findingsOfPair(report, key)
}

/** A pair of plans with the utility network first (blue) and the road/other work second
 *  (orange) — e.g. "WASD · Water ↔ FDOT · Roadway". */
export function orderPair(plans, report) {
  const utility = (label) => report?.plans?.find((p) => p.label === label)?.utility ?? false
  const [a, b] = plans
  return utility(b) && !utility(a) ? [b, a] : [a, b]
}

/** Which plan of the pair is "A" (blue) — the pair key's first plan. For all pairs: utility networks are
 *  blue and road / other work orange. */
export function sideOf(plan, key, report = null) {
  if (!key || !plan) return null
  if (key === ALL_PAIRS) {
    const p = report?.plans?.find((x) => x.label === plan)
    return p ? (p.utility ? 'a' : 'b') : null
  }
  const [a, b] = key.split(' ↔ ')
  return plan === a ? 'a' : plan === b ? 'b' : null
}

/** Years between two ISO dates (for the timeline scale). */
export function yearTicks(fromIso, toIso) {
  const y0 = Number(fromIso.slice(0, 4))
  const y1 = Number(toIso.slice(0, 4)) + 1
  const step = y1 - y0 > 12 ? 2 : 1
  const out = []
  for (let y = y0; y <= y1; y += step) out.push(y)
  return out
}
