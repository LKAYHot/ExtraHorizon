// The deadline picker's date arithmetic (pure — tested in datetime.test.js). Weeks start on Sunday and times use a
// 12-hour clock (en-US), like every other date in the UI.

export const WEEKDAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
export const WEEKDAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December']
export const HOURS = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
export const MINUTES = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]

export function startOfDay(d) {
  const x = new Date(d)
  x.setHours(0, 0, 0, 0)
  return x
}

export function addDays(d, n) {
  const x = new Date(d)
  x.setDate(x.getDate() + n) // (calendar days: a daylight-saving change does not shift the date)
  return x
}

/** The first day of the month ``n`` months after the one ``d`` is in. */
export function addMonths(d, n) {
  return new Date(d.getFullYear(), d.getMonth() + n, 1)
}

/** The same day of the month ``n`` months later (the 31st becomes the month's last day). */
export function shiftMonth(d, n) {
  const last = new Date(d.getFullYear(), d.getMonth() + n + 1, 0).getDate()
  return new Date(d.getFullYear(), d.getMonth() + n, Math.min(d.getDate(), last))
}

export function sameDay(a, b) {
  return !!a && !!b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/** "2026-09-27" in local time (a stable key for a day cell). */
export function isoDay(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Six weeks of seven days that cover the month (Sunday first): ``[{date, inMonth}]`` × 42. */
export function monthGrid(year, month) {
  const first = new Date(year, month, 1)
  const start = addDays(first, -first.getDay())
  return Array.from({ length: 42 }, (_, i) => {
    const date = addDays(start, i)
    return { date, inMonth: date.getMonth() === month }
  })
}

export function to12(h24) {
  return { hour: h24 % 12 || 12, pm: h24 >= 12 }
}

export function to24(hour12, pm) {
  return (hour12 % 12) + (pm ? 12 : 0)
}

/** The moment chosen: a day, an hour on a 12-hour clock, minutes, AM or PM. */
export function combine(day, hour12, minute, pm) {
  const d = new Date(day)
  d.setHours(to24(hour12, pm), minute, 0, 0)
  return d
}

/** A day can be picked from today to ``maxDays`` days ahead. */
export function dayAllowed(day, now, maxDays) {
  const d = startOfDay(day)
  const t = startOfDay(now)
  return d >= t && d <= addDays(t, maxDays)
}

/** Why a moment cannot be the deadline ('' when it can). */
export function deadlineProblem(when, now, maxDays) {
  if (!(when instanceof Date) || Number.isNaN(when.getTime())) return 'Pick a day and a time'
  if (when.getTime() <= now.getTime() + 60_000) return 'Pick a time in the future'
  if (when.getTime() > now.getTime() + maxDays * 86_400_000) return `Pick a time within ${maxDays} days`
  return ''
}

/** A sensible first suggestion: 24 hours from now, on the hour. */
export function suggestDeadline(now) {
  const d = new Date(now.getTime() + 24 * 3_600_000)
  d.setMinutes(0, 0, 0)
  return d
}

/** Minutes rounded to the picker's five-minute steps (down). */
export function stepMinutes(m) {
  return Math.floor(m / 5) * 5
}

/** "Sun, Sep 27 · 6:00 PM" */
export function formatDeadline(d) {
  if (!d) return ''
  const day = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  return `${day} · ${time}`
}

/** "in 23 h 40 min", "in 2 days 3 h" */
export function fromNow(d, now) {
  const m = Math.round((d.getTime() - now.getTime()) / 60_000)
  if (m <= 0) return 'in the past'
  if (m < 60) return `in ${m} min`
  const h = Math.floor(m / 60)
  if (h < 48) return `in ${h} h${m % 60 ? ` ${m % 60} min` : ''}`
  const days = Math.floor(h / 24)
  return `in ${days} days${h % 24 ? ` ${h % 24} h` : ''}`
}
