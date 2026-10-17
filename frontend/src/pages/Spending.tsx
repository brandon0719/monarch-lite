import { useState, type CSSProperties } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import BreakdownCard from '../components/BreakdownCard'
import CategoryBudgetsCard from '../components/CategoryBudgetsCard'
import { api, type Budget, type BudgetMonth, type CashflowMonth } from '../api'
import { currentMonth, formatCents, formatPct, monthLabel } from '../format'

type BucketKey = 'needs' | 'wants' | 'savings'
const BUCKETS: { key: BucketKey; label: string }[] = [
  { key: 'needs', label: 'Needs' },
  { key: 'wants', label: 'Wants' },
  { key: 'savings', label: 'Savings' },
]
const RANGES = [3, 6, 12]

const clamp01 = (n: number) => Math.min(Math.max(n, 0), 1)
/** Below this income a savings rate is noise ($4 of income and $40 spent reads as -900%). */
const MIN_RATE_INCOME_CENTS = 1000

/** Savings rate for display: "—" with no income, "n/m" when it means nothing, else a capped whole percent.
 *  The exact figure rides along in title/aria-label so "n/m" never hides data. */
function Rate({ rate, income }: { rate: number | null; income: number }) {
  if (rate === null) return <>—</>
  const exact = `${(rate * 100).toFixed(1)}%`
  if (income < MIN_RATE_INCOME_CENTS || rate < -1) {
    return <span role="img" aria-label={`${exact}, not meaningful`} title={`${exact} (not meaningful)`}>n/m</span>
  }
  return <>{formatPct(Math.round(rate * 100))}</>
}

/** Rows come newest first. Drop the leading (oldest) run where every value is zero. */
function trimEmptyOldest<T extends { month: string }>(rows: T[], isEmpty: (row: T) => boolean) {
  let last = rows.length - 1
  while (last >= 0 && isEmpty(rows[last]!)) last--
  const shown = rows.slice(0, last + 1)
  return { shown, quietBefore: shown.length > 0 && shown.length < rows.length ? shown[shown.length - 1]!.month : null }
}
const QuietLine = ({ before }: { before: string | null }) =>
  before ? <p className="muted sp-quiet">No activity before {monthLabel(before)}</p> : null

function Meter({ bucket, label, actual, target }: { bucket: BucketKey; label: string; actual: number; target: number | null }) {
  const hasTarget = target !== null
  const ratio = hasTarget ? (target > 0 ? actual / target : actual > 0 ? 2 : 0) : 0
  const pct = hasTarget && target > 0 ? formatPct(Math.round(ratio * 100)) : null
  const over = bucket !== 'savings' && hasTarget && ratio > 1
  const met = bucket === 'savings' && hasTarget && actual >= target && actual > 0
  const value = formatCents(actual)
  const summary = [
    `${label}: ${value}`,
    hasTarget ? ` of ${formatCents(target)}` : '',
    pct !== null ? `, ${pct}` : '',
    over ? ', over target' : '',
    met ? ', target met' : '',
  ].join('')
  return (
    <div className={`meter${over ? ' over' : ''}`} role="img" aria-label={summary} title={summary} style={{ '--b': `var(--b-${bucket})` } as CSSProperties}>
      <span className="m-name" aria-hidden="true">
        <i className="sw" />{label}{hasTarget ? ` · target ${formatCents(target)}` : ''}
      </span>
      <span className="m-text" aria-hidden="true">
        <span className="m-val">{value}</span>
        {pct !== null && <span className="m-pct"> · {pct}</span>}
        {met && <span className="m-ok"> ✓</span>}
      </span>
      {hasTarget && (
        <span className="trk" aria-hidden="true"><span style={{ width: `${clamp01(ratio) * 100}%` }} /></span>
      )}
    </div>
  )
}

function MeterRow({ m, targets }: { m: BudgetMonth; targets: Budget['targets'] }) {
  const amounts: Record<BucketKey, number> = { needs: m.needs_cents, wants: m.wants_cents, savings: m.savings_cents }
  return (
    <li className="m-row">
      <span className="m-month">{monthLabel(m.month)}{m.is_current && <span className="muted"> · so far</span>}</span>
      {BUCKETS.map((b) => (
        <Meter key={b.key} bucket={b.key} label={b.label} actual={amounts[b.key]} target={targets ? targets[b.key] : null} />
      ))}
    </li>
  )
}

function BudgetCard() {
  const [months, setMonths] = useState(3)
  const budget = useQuery({ queryKey: ['budget', months], queryFn: () => api.budget(months), placeholderData: keepPreviousData })
  const b = budget.data
  const { shown, quietBefore } = trimEmptyOldest(
    b?.months ?? [],
    (m) => m.needs_cents === 0 && m.wants_cents === 0 && m.savings_cents === 0,
  )

  return (
    <section className="card" aria-labelledby="sp-budget">
      <div className="card-head">
        <h2 className="card-title" id="sp-budget">50/30/20</h2>
        <label className="pill-field">Show last
          <select className="pill" value={months} onChange={(e) => setMonths(Number(e.target.value))}>
            {RANGES.map((n) => <option key={n} value={n}>{n} months</option>)}
          </select>
        </label>
      </div>
      {budget.isPending && <p className="muted" role="status">Loading…</p>}
      {budget.isError && <p className="error" role="alert">{budget.error.message}</p>}
      {b && (
        <>
          {b.configured && b.base_cents !== null ? (
            <p className="sp-base">
              Base <strong>{formatCents(b.base_cents)}</strong>
              <span className="muted"> take-home · rent counts in Needs</span>
            </p>
          ) : (
            <p className="muted sp-base">
              Set your take-home in <Link to="/settings">Settings</Link> to see targets
            </p>
          )}
          {shown.length === 0 ? (
            <p className="muted">No spending or savings recorded in the last {months} months.</p>
          ) : (
            <>
              <div className="m-head" aria-hidden="true">
                <span />
                {BUCKETS.map((x) => (
                  <span key={x.key} className="m-head-cell" style={{ '--b': `var(--b-${x.key})` } as CSSProperties}>
                    <i className="sw" />
                    <b>{x.label}</b>
                    {b.targets && <span className="muted"> {b[`${x.key}_pct`]}% · {formatCents(b.targets[x.key])}</span>}
                  </span>
                ))}
              </div>
              <ul className="m-list">
                {shown.map((m) => (
                  <MeterRow key={m.month} m={m} targets={b.targets} />
                ))}
              </ul>
              <QuietLine before={quietBefore} />
            </>
          )}
        </>
      )}
    </section>
  )
}

function CashRow({ m, max, now }: { m: CashflowMonth; max: number; now: string }) {
  const net = m.saved_cents
  const title = `${monthLabel(m.month)}: income ${formatCents(m.income_cents)}, spent ${formatCents(m.spent_cents)}`
  return (
    <li className="cf-row" title={title}>
      <span className="cf-month">{monthLabel(m.month)}{m.month === now && <span className="muted"> · so far</span>}</span>
      <span className="cf-bars" aria-hidden="true">
        <span className="cf-bar income"><span style={{ width: `${clamp01(m.income_cents / max) * 100}%` }} /></span>
        <span className="cf-bar spent"><span style={{ width: `${clamp01(m.spent_cents / max) * 100}%` }} /></span>
      </span>
      <span className={`cf-num cf-income${m.income_cents === 0 ? ' dim' : ''}`}><span className="cf-k">Income </span>{formatCents(m.income_cents)}</span>
      <span className={`cf-num cf-spent${m.spent_cents === 0 ? ' dim' : ''}`}><span className="cf-k">Spent </span>{formatCents(m.spent_cents)}</span>
      <span className={`cf-num cf-net${net > 0 ? ' pos' : net < 0 ? ' error' : ' dim'}`}><span className="cf-k">Net saved </span>{formatCents(net)}</span>
      <span className="cf-num cf-rate"><span className="cf-k">Rate </span><Rate rate={m.savings_rate} income={m.income_cents} /></span>
    </li>
  )
}

function CashflowCard() {
  const cashflow = useQuery({ queryKey: ['cashflow', 12], queryFn: () => api.cashflow(12) })
  const c = cashflow.data
  const { shown, quietBefore } = trimEmptyOldest(c?.months ?? [], (m) => m.income_cents === 0 && m.spent_cents === 0)
  const max = Math.max(1, ...shown.map((m) => Math.max(m.income_cents, m.spent_cents)))
  // Same weighting as the server's average (months with income), so the same "n/m" rule applies to the total.
  const incomeTotal = (c?.months ?? []).reduce((sum, m) => sum + Math.max(m.income_cents, 0), 0)
  const now = currentMonth()

  return (
    <section className="card" aria-labelledby="sp-cashflow">
      <h2 className="card-title" id="sp-cashflow">Cash flow</h2>
      {cashflow.isPending && <p className="muted" role="status">Loading…</p>}
      {cashflow.isError && <p className="error" role="alert">{cashflow.error.message}</p>}
      {c && shown.length === 0 && <p className="muted">No income or spending recorded in the last 12 months.</p>}
      {c && shown.length > 0 && (
        <>
          <p className="sp-base">
            Average savings rate{' '}
            <strong><Rate rate={c.average_savings_rate} income={incomeTotal} /></strong>
            <span className="muted"> over months with income</span>
          </p>
          <div className="cf-legend muted" aria-hidden="true">
            <span><i className="sw cf-income-sw" />Income</span>
            <span><i className="sw cf-spent-sw" />Spent</span>
          </div>
          <div className="cf-head" aria-hidden="true">
            <span>Month</span><span /><span>Income</span><span>Spent</span><span>Net saved</span><span>Rate</span>
          </div>
          <ul className="cf-list">
            {shown.map((m) => <CashRow key={m.month} m={m} max={max} now={now} />)}
          </ul>
          <QuietLine before={quietBefore} />
          <p className="muted sp-note">Net saved = income − spent. The 50/30/20 Savings meter counts only money you moved to savings.</p>
        </>
      )}
    </section>
  )
}

export default function Spending() {
  return (
    <>
      <header className="page-head">
        <h1>Spending</h1>
      </header>
      <BudgetCard />
      <CategoryBudgetsCard />
      <CashflowCard />
      <BreakdownCard />
    </>
  )
}
