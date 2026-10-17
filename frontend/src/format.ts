const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export const formatCents = (cents: number) => usd.format(cents / 100)

/** Whole percent for display. Past 999% either way it caps ("> 999%") so a tiny base can't print absurd numbers. */
export const formatPct = (pct: number) => (Math.abs(pct) > 999 ? `${pct < 0 ? '< -' : '> '}999%` : `${pct}%`)

/** Local current month as 'YYYY-MM'. */
export const currentMonth = () => isoDate(new Date()).slice(0, 7)

/** Backend datetimes are naive UTC. */
export const formatDateTime = (iso: string) => new Date(`${iso}Z`).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

export const formatDate = (isoDate: string) =>
  new Date(`${isoDate}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

/** "12.3" -> 1230, "-$1,234" -> -123400; blank or invalid -> null. String math, no float rounding. */
export function dollarsToCents(text: string): number | null {
  const m = text.replace(/[$,\s]/g, '').match(/^(-?)(\d*)(?:\.(\d{0,2}))?$/)
  if (!m || (m[2] === '' && !m[3])) return null
  const cents = Number(m[2] || '0') * 100 + Number((m[3] ?? '').padEnd(2, '0'))
  return m[1] ? -cents : cents
}

export type DatePreset = 'last30' | 'last90' | 'thisMonth' | 'lastMonth' | 'thisYear' | 'all' | 'custom'
export const DATE_PRESETS: [DatePreset, string][] = [
  ['last30', 'Last 30 days'], ['last90', 'Last 90 days'], ['thisMonth', 'This month'],
  ['lastMonth', 'Last month'], ['thisYear', 'This year'], ['all', 'All time'], ['custom', 'Custom…'],
]

const pad = (n: number) => String(n).padStart(2, '0')
/** Local calendar date as YYYY-MM-DD. */
export const isoDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

/** '2026-01', -1 -> '2025-12'. */
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y!, m! - 1 + delta, 1)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
}

export function presetRange(preset: DatePreset, today = new Date()): { start?: string; end?: string } {
  const y = today.getFullYear()
  const m = today.getMonth()
  const daysAgo = (n: number) => { const d = new Date(today); d.setDate(d.getDate() - n); return isoDate(d) }
  switch (preset) {
    case 'last30': return { start: daysAgo(30) }
    case 'last90': return { start: daysAgo(90) }
    case 'thisMonth': return { start: isoDate(new Date(y, m, 1)) }
    case 'lastMonth': return { start: isoDate(new Date(y, m - 1, 1)), end: isoDate(new Date(y, m, 0)) }
    case 'thisYear': return { start: isoDate(new Date(y, 0, 1)) }
    default: return {}
  }
}

/** Consecutive rows (already newest-first) bucketed by posted_date, order preserved. */
export function groupByDay<T extends { posted_date: string }>(rows: T[]): { day: string; items: T[] }[] {
  const groups: { day: string; items: T[] }[] = []
  for (const row of rows) {
    const last = groups[groups.length - 1]
    if (last && last.day === row.posted_date) last.items.push(row)
    else groups.push({ day: row.posted_date, items: [row] })
  }
  return groups
}

export const formatDayHeading = (isoDay: string) => {
  const d = new Date(`${isoDay}T00:00:00`)
  return d.toLocaleDateString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric',
    ...(d.getFullYear() !== new Date().getFullYear() && { year: 'numeric' as const }),
  })
}

/** '2026-10' -> 'October'; a month outside the current year gets its year: 'October 2025'. */
export const monthLabel = (month: string) => {
  const d = new Date(`${month}-01T00:00:00`)
  return d.toLocaleDateString(undefined, { month: 'long', ...(d.getFullYear() !== new Date().getFullYear() && { year: 'numeric' as const }) })
}
