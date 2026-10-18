import type { Goal } from './api'
import { formatCents, monthLabel } from './format'

function reachedBy(reachBy: string): string {
  const label = monthLabel(reachBy.slice(0, 7))
  // monthLabel only adds the year outside the current year; the status text always names it.
  return /\d{4}$/.test(label) ? label : `${label} ${reachBy.slice(0, 4)}`
}

export function statusLine(g: Goal): { text: string; behind?: boolean } {
  const rate = g.rate_cents === null ? null : formatCents(g.rate_cents)
  const unknown = { text: `Saving rate available after 2 weeks of history (${g.history_days ?? 0} days so far)` }
  switch (g.status) {
    case 'done': return { text: 'Done' }
    case 'unknown': return unknown
    case 'on_track': return { text: `Needed ${formatCents(g.needed_cents ?? 0)}/mo · saving ${rate ?? formatCents(0)}/mo · On track` }
    case 'behind': return { text: `Needed ${formatCents(g.needed_cents ?? 0)}/mo · saving ${rate ?? formatCents(0)}/mo · `, behind: true }
    default:
      if (rate === null) return unknown
      return { text: g.reach_by ? `Saving ${rate}/mo · at this rate, reached by ${reachedBy(g.reach_by)}` : `Saving ${rate}/mo` }
  }
}
