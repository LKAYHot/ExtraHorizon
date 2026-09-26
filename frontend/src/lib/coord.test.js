import { describe, expect, it } from 'vitest'
import { ALL_PAIRS, fmtDistance, fmtTiming, findingsOfPair, orderPair, pairKey, shownFindings, sideOf, yearTicks } from './coord.js'

describe('coordination helpers', () => {
  it('formats distances and timing in words a planner reads', () => {
    expect(fmtDistance(0)).toBe('intersect')
    expect(fmtDistance(38.4)).toBe('38 m')
    expect(fmtDistance(1234)).toBe('1.2 km')
    expect(fmtTiming({ overlap_days: 120, gap_days: 0 })).toBe('together 120 days')
    expect(fmtTiming({ overlap_days: 1, gap_days: 0 })).toBe('together 1 day')
    expect(fmtTiming({ overlap_days: -185, gap_days: 185 })).toBe('185 days apart')
    expect(fmtTiming({ overlap_days: -1, gap_days: 1 })).toBe('1 day apart')
    expect(fmtTiming({ overlap_days: 0, gap_days: 0 })).toBe('back to back')
  })

  it('filters findings by the chosen pair of plans (in either order)', () => {
    const report = {
      findings: [
        { id: 'F1', plans: ['WASD · Water', 'FDOT · Roadway'] },
        { id: 'F2', plans: ['FDOT · Roadway', 'WASD · Water'] },
        { id: 'F3', plans: ['WASD · Sewer', 'FDOT · Roadway'] },
      ],
    }
    const key = pairKey(['FDOT · Roadway', 'WASD · Water'])
    expect(findingsOfPair(report, key).map((f) => f.id)).toEqual(['F1', 'F2'])
    expect(findingsOfPair(report, null)).toHaveLength(3)
    expect(sideOf('FDOT · Roadway', key)).toBe('a')
    expect(sideOf('WASD · Water', key)).toBe('b')
    expect(sideOf('DTPW · Paving', key)).toBe(null)
  })

  it('puts the utility network first (blue) and the road work second (orange)', () => {
    const report = { plans: [
      { label: 'FDOT · Roadway', utility: false }, { label: 'WASD · Water', utility: true },
      { label: 'WASD · Sewer', utility: true }, { label: 'DTPW · Paving', utility: false },
    ] }
    expect(orderPair(['FDOT · Roadway', 'WASD · Water'], report)).toEqual(['WASD · Water', 'FDOT · Roadway'])
    expect(orderPair(['WASD · Water', 'FDOT · Roadway'], report)).toEqual(['WASD · Water', 'FDOT · Roadway'])
    // two utilities or two road plans keep the report's order
    expect(orderPair(['WASD · Sewer', 'WASD · Water'], report)).toEqual(['WASD · Sewer', 'WASD · Water'])
    expect(orderPair(['FDOT · Roadway', 'DTPW · Paving'], report)).toEqual(['FDOT · Roadway', 'DTPW · Paving'])
    expect(orderPair(['A', 'B'], null)).toEqual(['A', 'B'])
  })

  it('year ticks cover the whole range, every second year on long ranges', () => {
    expect(yearTicks('2026-03-01', '2028-06-30')).toEqual([2026, 2027, 2028, 2029])
    expect(yearTicks('2014-07-01', '2040-06-30')[1] - yearTicks('2014-07-01', '2040-06-30')[0]).toBe(2)
  })

  it('the spotlight (what she looked up) and "all pairs" colour by network vs road work', () => {
    const report = {
      plans: [{ label: 'WASD · Water', utility: true }, { label: 'FDOT · Roadway', utility: false }],
      findings: [{ id: 'F1', plans: ['WASD · Water', 'FDOT · Roadway'] }, { id: 'F2', plans: ['WASD · Water', 'FDOT · Roadway'] }],
    }
    expect(findingsOfPair(report, ALL_PAIRS)).toHaveLength(2)
    expect(shownFindings(report, 'WASD · Water ↔ FDOT · Roadway', { ids: ['F2'] }).map((f) => f.id)).toEqual(['F2'])
    expect(shownFindings(report, ALL_PAIRS, null)).toHaveLength(2)
    expect(sideOf('WASD · Water', ALL_PAIRS, report)).toBe('a')
    expect(sideOf('FDOT · Roadway', ALL_PAIRS, report)).toBe('b')
  })
})
