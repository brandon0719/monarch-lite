import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type Category, type SpendingRow } from '../api'
import CategoryChip from '../components/CategoryChip'
import { categoryColor, NEUTRAL } from '../colors'
import { formatCents, formatDate, formatDateTime, monthLabel } from '../format'

const TOP_N = 6

function greeting(hour: number) {
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

/** Top rows by spend, the remainder folded into one "Other" row. */
function topWithOther(rows: SpendingRow[]): SpendingRow[] {
  const sorted = [...rows].sort((a, b) => b.cents - a.cents)
  if (sorted.length <= TOP_N) return sorted
  const rest = sorted.slice(TOP_N).reduce((sum, r) => sum + r.cents, 0)
  return [...sorted.slice(0, TOP_N), { category_id: null, name: 'Other', cents: rest }]
}

function UpcomingCard() {
  const up = useQuery({ queryKey: ['recurring', 'upcoming', 30], queryFn: () => api.upcoming(30) })
  const rec = useQuery({ queryKey: ['recurring'], queryFn: api.recurring })
  const alerts = rec.data?.alerts.length ?? 0
  return (
    <section className="card" aria-labelledby="ov-upcoming">
      <h2 className="card-title" id="ov-upcoming">Upcoming</h2>
      {up.isPending && <p className="muted" role="status">Loading…</p>}
      {up.isError && <p className="error" role="alert">{up.error.message}</p>}
      {up.data && (up.data.rows.length === 0 ? (
        <p className="muted">Nothing expected in the next 30 days.</p>
      ) : (
        <ul className="recent-list">
          {up.data.rows.slice(0, 5).map((r) => (
            <li key={`${r.item_id}-${r.date}`} className="up-row">
              <span className="recent-main">
                <span className="recent-merchant">{r.name}</span>
                <span className="tx-sub">{formatDate(r.date)}{r.late && <span className="error"> · Late</span>}</span>
              </span>
              <span className={`amount${r.amount_cents > 0 ? ' pos' : ''}`}>{formatCents(r.amount_cents)}</span>
            </li>
          ))}
        </ul>
      ))}
      <div className="up-foot">
        {rec.isError ? <span className="muted">Alerts unavailable</span>
          : alerts > 0 && <span className="error">{alerts} {alerts === 1 ? 'alert' : 'alerts'}</span>}
        <Link className="tile-link" to="/recurring">See recurring →</Link>
      </div>
    </section>
  )
}

export default function Overview() {
  const overview = useQuery({ queryKey: ['overview'], queryFn: () => api.overview() })
  const categories = useQuery({ queryKey: ['categories'], queryFn: api.categories })

  if (overview.isPending) return <p className="muted" role="status">Loading…</p>
  if (overview.isError) return <p className="error" role="alert">{overview.error.message}</p>

  const o = overview.data
  const byId = new Map<number, Category>((categories.data ?? []).map((c) => [c.id, c]))
  const month = monthLabel(o.month)

  const balanceRows: [string, number][] = [
    ['Cash', o.balances.cash],
    ['Investments', o.balances.investments],
    ['Credit cards', o.balances.credit],
  ]
  if (o.balances.loans !== 0) balanceRows.push(['Loans', o.balances.loans])
  if (o.balances.other !== 0) balanceRows.push(['Other', o.balances.other])

  const spending = topWithOther(o.spending_by_category)
  const max = Math.max(1, ...spending.map((r) => r.cents))

  return (
    <>
      <header className="page-head">
        <h1>{greeting(new Date().getHours())}</h1>
      </header>

      <div className="tiles">
        <div className="tile">
          <div className="tile-label">Net worth</div>
          <div className="tile-value">{formatCents(o.net_worth_cents)}</div>
          <div className="tile-sub">{o.last_synced_at ? `as of ${formatDateTime(o.last_synced_at)}` : 'Not synced yet'}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Spent in {month}</div>
          <div className="tile-value">{formatCents(o.spent_cents)}</div>
          <Link className="tile-link" to="/spending">See spending →</Link>
        </div>
        <div className="tile">
          <div className="tile-label">To review</div>
          <div className="tile-value">{o.to_review}</div>
          <Link className="tile-link" to="/transactions?tab=review">Review now →</Link>
        </div>
      </div>

      <div className="ov-grid">
        <section className="card" aria-labelledby="ov-spending">
          <h2 className="card-title" id="ov-spending">{month} spending by category</h2>
          {spending.length === 0 ? (
            <p className="muted">No spending yet this month.</p>
          ) : (
            <ul className="bar-list">
              {spending.map((r) => {
                const cat = r.category_id === null ? null : byId.get(r.category_id)
                const color = cat ? categoryColor(cat) : NEUTRAL
                return (
                  <li key={r.category_id ?? r.name} className="bar-row" title={`${r.name}: ${formatCents(r.cents)}`}>
                    <span className="bar-name">{r.name}</span>
                    <span className="bar" aria-hidden="true">
                      <span style={{ '--bar': color, width: `${(Math.max(0, r.cents) / max) * 100}%` } as CSSProperties} />
                    </span>
                    <span className="amount">{formatCents(r.cents)}</span>
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <div className="ov-side">
          <UpcomingCard />

          <section className="card" aria-labelledby="ov-balances">
            <h2 className="card-title" id="ov-balances">Balances</h2>
            <dl className="balances">
              {balanceRows.map(([label, cents]) => (
                <div key={label} className="balance-row">
                  <dt>{label}</dt>
                  <dd>{formatCents(cents)}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="card" aria-labelledby="ov-recent">
            <h2 className="card-title" id="ov-recent">Recent</h2>
            {o.recent.length === 0 ? (
              <p className="muted">No transactions yet.</p>
            ) : (
              <ul className="recent-list">
                {o.recent.map((t) => (
                  <li key={t.id}>
                    <Link className="recent-row" to="/transactions">
                      <span className="recent-main">
                        <span className="recent-merchant">{t.merchant}</span>
                        <span className="tx-sub">{formatDate(t.posted_date)}</span>
                      </span>
                      <CategoryChip category={t.category_id === null ? null : byId.get(t.category_id)} name={t.category_name} />
                      <span className={`amount${t.amount_cents > 0 ? ' pos' : ''}`}>{formatCents(t.amount_cents)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </>
  )
}
