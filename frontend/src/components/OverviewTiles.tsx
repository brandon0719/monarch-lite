import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type Budget, type BudgetMonth } from '../api'
import UnvestedLine from './UnvestedLine'
import { formatCents, formatDateTime, formatPct, monthLabel } from '../format'

type BucketKey = 'needs' | 'wants' | 'savings'
const BUCKETS: [BucketKey, string][] = [['needs', 'Needs'], ['wants', 'Wants'], ['savings', 'Savings']]

const signed = (cents: number) => `${cents > 0 ? '+' : ''}${formatCents(cents)}`

export function NetWorthTile() {
  const overview = useQuery({ queryKey: ['overview'], queryFn: () => api.overview() })
  const change = useQuery({ queryKey: ['networth', '1M'], queryFn: () => api.networth('1M') })
  const o = overview.data
  return (
    <div className="tile">
      <div className="tile-label">Net worth</div>
      {overview.isPending && <p className="muted" role="status">Loading…</p>}
      {overview.isError && <p className="error" role="alert">{overview.error.message}</p>}
      {o && <div className="tile-value">{formatCents(o.net_worth_cents)}</div>}
      {change.data && (
        <div className="tile-sub">
          <span className={change.data.change_cents > 0 ? 'pos' : undefined}>{signed(change.data.change_cents)}</span> in 30 days
        </div>
      )}
      {change.isError && <div className="tile-sub">30-day change unavailable</div>}
      <UnvestedLine />
      {o && <div className="tile-sub">{o.last_synced_at ? `as of ${formatDateTime(o.last_synced_at)}` : 'Not synced yet'}</div>}
      <Link className="tile-link" to="/networth">See history →</Link>
    </div>
  )
}

export function MonthTile() {
  const cash = useQuery({ queryKey: ['cashflow', 1], queryFn: () => api.cashflow(1) })
  const m = cash.data?.months[0]
  return (
    <div className="tile">
      <div className="tile-label">This month{m && ` · ${monthLabel(m.month)}`}</div>
      {cash.isPending && <p className="muted" role="status">Loading…</p>}
      {cash.isError && <p className="error" role="alert">{cash.error.message}</p>}
      {cash.data && !m && <p className="muted">No data yet.</p>}
      {m && (
        <dl className="balances tile-rows">
          <div className="balance-row"><dt>Income</dt><dd>{formatCents(m.income_cents)}</dd></div>
          <div className="balance-row"><dt>Spent</dt><dd>{formatCents(m.spent_cents)}</dd></div>
          <div className="balance-row"><dt>Net</dt><dd>{signed(m.saved_cents)}</dd></div>
        </dl>
      )}
      <Link className="tile-link" to="/spending">See spending →</Link>
    </div>
  )
}

function MiniMeter({ bucket, label, actual, target }: { bucket: BucketKey; label: string; actual: number; target: number }) {
  const ratio = target > 0 ? actual / target : actual > 0 ? 2 : 0
  const pct = target > 0 ? formatPct(Math.round(ratio * 100)) : null
  const over = bucket !== 'savings' && ratio > 1
  const summary = `${label}: ${formatCents(actual)} of ${formatCents(target)}${pct ? `, ${pct}` : ''}${over ? ', over target' : ''}`
  return (
    <div className={`meter ov-meter${over ? ' over' : ''}`} role="img" aria-label={summary} title={summary} style={{ '--b': `var(--b-${bucket})` } as CSSProperties}>
      <span className="ov-meter-text" aria-hidden="true">
        <span>{label}</span>
        <span><span className="m-val">{formatCents(actual)}</span> of {formatCents(target)}{pct && <span className="m-pct"> · {pct}</span>}{over && <span className="m-pct"> · over</span>}</span>
      </span>
      <span className="trk" aria-hidden="true"><span style={{ width: `${Math.min(Math.max(ratio, 0), 1) * 100}%` }} /></span>
    </div>
  )
}

export function BudgetTile() {
  const budget = useQuery({ queryKey: ['budget', 1], queryFn: () => api.budget(1) })
  const b: Budget | undefined = budget.data
  const m: BudgetMonth | undefined = b?.months[0]
  const amounts = m ? { needs: m.needs_cents, wants: m.wants_cents, savings: m.savings_cents } : null
  return (
    <div className="tile">
      <div className="tile-label">50/30/20</div>
      {budget.isPending && <p className="muted" role="status">Loading…</p>}
      {budget.isError && <p className="error" role="alert">{budget.error.message}</p>}
      {b && (b.targets && amounts ? (
        <div className="ov-meters">
          {BUCKETS.map(([key, label]) => <MiniMeter key={key} bucket={key} label={label} actual={amounts[key]} target={b.targets![key]} />)}
        </div>
      ) : (
        <p className="muted">Set targets in <Link to="/settings">Settings</Link>.</p>
      ))}
      <Link className="tile-link" to="/spending">See budget →</Link>
    </div>
  )
}
