import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useId, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { categoryColor, NEUTRAL } from '../colors'
import { formatCents, isoDate } from '../format'

type Range = 'thisMonth' | 'lastMonth' | 'last3' | 'ytd' | 'custom'
const RANGES: [Range, string][] = [
  ['thisMonth', 'This month'], ['lastMonth', 'Last month'], ['last3', 'Last 3 months'], ['ytd', 'Year to date'], ['custom', 'Custom…'],
]

/** Inclusive local-date range for a preset; "Last 3 months" is this month plus the two before it. */
function rangeFor(r: Range, today = new Date()): { start: string; end: string } {
  const y = today.getFullYear()
  const m = today.getMonth()
  const t = isoDate(today)
  switch (r) {
    case 'lastMonth': return { start: isoDate(new Date(y, m - 1, 1)), end: isoDate(new Date(y, m, 0)) }
    case 'last3': return { start: isoDate(new Date(y, m - 2, 1)), end: t }
    case 'ytd': return { start: isoDate(new Date(y, 0, 1)), end: t }
    default: return { start: isoDate(new Date(y, m, 1)), end: t }
  }
}

function BarRow({ to, label, note, cents, max, color }: { to: string; label: string; note?: string; cents: number; max: number; color: string }) {
  return (
    <li>
      <Link className="bar-row bd-link" to={to} aria-label={`${label}: ${formatCents(cents)}${note ? `, ${note}` : ''}. Show transactions`}>
        <span className="bar-name">{label}{note && <span className="muted"> · {note}</span>}</span>
        <span className="bar" aria-hidden="true"><span style={{ '--bar': color, width: `${(cents / max) * 100}%` } as CSSProperties} /></span>
        <span className="amount">{formatCents(cents)}</span>
      </Link>
    </li>
  )
}

export default function BreakdownCard() {
  const rangeError = useId()
  const [range, setRange] = useState<Range>('thisMonth')
  const [custom, setCustom] = useState(() => rangeFor('thisMonth'))
  const { start, end } = range === 'custom' ? custom : rangeFor(range)
  const valid = start !== '' && end !== '' && start <= end
  const q = useQuery({ queryKey: ['breakdown', start, end], queryFn: async () => ({ ...(await api.breakdown(start, end)), start, end }), enabled: valid, placeholderData: keepPreviousData })
  const d = q.data
  // While a new range loads, the rows on screen still belong to the previous one; link with the range they were fetched for.
  const stale = q.isPlaceholderData
  const link = (extra: Record<string, string>) => `/transactions?${new URLSearchParams({ start: d?.start ?? start, end: d?.end ?? end, ...extra })}`
  const catMax = Math.max(1, ...(d?.categories.map((c) => c.cents) ?? []))
  const merMax = Math.max(1, ...(d?.merchants.map((m) => m.cents) ?? []))

  return (
    <section className="card" aria-labelledby="sp-breakdown">
      <div className="card-head">
        <h2 className="card-title" id="sp-breakdown">Breakdown</h2>
        <div className="pills">
          <select className="pill" aria-label="Breakdown range" value={range} onChange={(e) => {
            const next = e.target.value as Range
            if (next === 'custom') setCustom({ start, end })
            setRange(next)
          }}>
            {RANGES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          {range === 'custom' && (
            <>
              <label className="pill-field">From
                <input className="pill" type="date" value={custom.start} max={custom.end} aria-invalid={!valid} aria-describedby={valid ? undefined : rangeError} onChange={(e) => setCustom({ ...custom, start: e.target.value })} />
              </label>
              <label className="pill-field">To
                <input className="pill" type="date" value={custom.end} min={custom.start} aria-invalid={!valid} aria-describedby={valid ? undefined : rangeError} onChange={(e) => setCustom({ ...custom, end: e.target.value })} />
              </label>
            </>
          )}
        </div>
      </div>
      {!valid && <p className="error" role="alert" id={rangeError}>Pick a start date on or before the end date.</p>}
      {valid && q.isPending && <p className="muted" role="status">Loading…</p>}
      {valid && q.isError && <p className="error" role="alert">{q.error.message}</p>}
      {valid && d && (d.categories.length === 0 ? (
        <p className="muted">No spending in this range.</p>
      ) : (
        <>
          <p className={`sp-base${stale ? ' stale' : ''}`}>Spent <strong>{formatCents(d.total_cents)}</strong></p>
          <div className={`bd-grid${stale ? ' stale' : ''}`} aria-busy={stale}>
            <div>
              <h3 className="set-sub">Categories</h3>
              <ul className="bar-list">
                {d.categories.map((c) => (
                  <BarRow
                    key={c.category_id ?? 'none'} label={c.name} cents={c.cents} max={catMax}
                    color={c.category_id === null || c.bucket === null ? NEUTRAL : categoryColor({ id: c.category_id, bucket: c.bucket })}
                    to={link(c.category_id === null ? { uncategorized: '1' } : { category_id: String(c.category_id) })}
                  />
                ))}
              </ul>
            </div>
            <div>
              <h3 className="set-sub">Top merchants</h3>
              {d.merchants.length === 0 && <p className="muted">No merchants in this range.</p>}
              <ul className="bar-list">
                {d.merchants.map((m) => (
                  <BarRow
                    key={m.merchant} label={m.merchant} note={`${m.count} ${m.count === 1 ? 'transaction' : 'transactions'}`}
                    cents={m.cents} max={merMax} color={NEUTRAL} to={link({ merchant: m.merchant })}
                  />
                ))}
              </ul>
            </div>
          </div>
        </>
      ))}
    </section>
  )
}
