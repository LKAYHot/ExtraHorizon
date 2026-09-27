import { describe, expect, it } from 'vitest'
import { addMonths, combine, shiftMonth, dayAllowed, deadlineProblem, formatDeadline, fromNow, isoDay, monthGrid, stepMinutes,
  suggestDeadline, to12, to24 } from './datetime.js'

describe('the deadline picker', () => {
  it('lays a month out in six Sunday-first weeks', () => {
    const g = monthGrid(2026, 8) // September 2026 starts on a Tuesday
    expect(g).toHaveLength(42)
    expect(isoDay(g[0].date)).toBe('2026-08-30') // the Sunday before
    expect(g[0].inMonth).toBe(false)
    expect(isoDay(g[2].date)).toBe('2026-09-01')
    expect(g.filter((c) => c.inMonth)).toHaveLength(30)
    expect(isoDay(addMonths(new Date(2026, 11, 31), 1))).toBe('2027-01-01')
    expect(isoDay(shiftMonth(new Date(2026, 0, 31), 1))).toBe('2026-02-28') // PageDown from the 31st
    expect(isoDay(shiftMonth(new Date(2026, 9, 15), -1))).toBe('2026-09-15')
  })

  it('converts a 12-hour clock both ways', () => {
    expect(to12(0)).toEqual({ hour: 12, pm: false })
    expect(to12(12)).toEqual({ hour: 12, pm: true })
    expect(to12(18)).toEqual({ hour: 6, pm: true })
    expect(to24(12, false)).toBe(0)
    expect(to24(12, true)).toBe(12)
    expect(to24(6, true)).toBe(18)
    const d = combine(new Date(2026, 8, 27), 6, 30, true)
    expect([d.getHours(), d.getMinutes()]).toEqual([18, 30])
  })

  it('allows today to thirty days ahead, and only future moments', () => {
    const now = new Date(2026, 8, 26, 18, 10)
    expect(dayAllowed(new Date(2026, 8, 26), now, 30)).toBe(true)
    expect(dayAllowed(new Date(2026, 8, 25), now, 30)).toBe(false)
    expect(dayAllowed(new Date(2026, 9, 26), now, 30)).toBe(true)
    expect(dayAllowed(new Date(2026, 9, 27), now, 30)).toBe(false)
    expect(deadlineProblem(new Date(2026, 8, 26, 17, 0), now, 30)).toBe('Pick a time in the future')
    expect(deadlineProblem(new Date(2026, 9, 30), now, 30)).toBe('Pick a time within 30 days')
    expect(deadlineProblem(new Date(2026, 8, 27, 10, 0), now, 30)).toBe('')
    expect(deadlineProblem(null, now, 30)).toBe('Pick a day and a time')
  })

  it('suggests a round time and says it plainly', () => {
    const now = new Date(2026, 8, 26, 18, 10)
    const s = suggestDeadline(now)
    expect(isoDay(s)).toBe('2026-09-27')
    expect([s.getHours(), s.getMinutes()]).toEqual([18, 0])
    expect(stepMinutes(58)).toBe(55)
    expect(formatDeadline(new Date(2026, 8, 27, 18, 0))).toBe('Sun, Sep 27 · 6:00 PM')
    expect(fromNow(new Date(2026, 8, 27, 17, 50), now)).toBe('in 23 h 40 min')
    expect(fromNow(new Date(2026, 8, 29, 21, 10), now)).toBe('in 3 days 3 h')
    expect(fromNow(new Date(2026, 8, 26, 18, 40), now)).toBe('in 30 min')
  })
})
