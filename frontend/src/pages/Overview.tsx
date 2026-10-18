import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type Category, type SpendingRow } from '../api'
import CategoryChip from '../components/CategoryChip'
import AlertsCard from '../components/AlertsCard'
import { DueCard, GoalsCard, VestCard } from '../components/OverviewSide'
import { BudgetTile, MonthTile, NetWorthTile } from '../components/OverviewTiles'
import { categoryColor, NEUTRAL } from '../colors'
import { formatCents, formatDate, monthLabel } from '../format'

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

/** Cards that read the overview each handle their own loading and error, so one failing query never blanks the page. */
function useOverview() {
  return useQuery({ queryKey: ['overview'], queryFn: () => api.overview() })
}

function ReviewTile() {
  const overview = useOverview()
  return (
    <div className="tile">
      <div className="tile-label">To review</div>
      {overview.isPending && <p className="muted" role="status">Loading…</p>}
      {overview.isError && <p className="error" role="alert">{overview.error.message}</p>}
      {overview.data && <div className="tile-value">{overview.data.to_review}</div>}
      <Link className="tile-link" to="/transactions?tab=review">Review now →</Link>
    </div>
  )
}

function SpendingCard({ byId }: { byId: Map<number, Category> }) {
  const overview = useOverview()
  const o = overview.data
  const month = o ? monthLabel(o.month) : null
  const spending = o ? topWithOther(o.spending_by_category) : []
  const max = Math.max(1, ...spending.map((r) => r.cents))
  return (
    <section className="card" aria-labelledby="ov-spending">
      <h2 className="card-title" id="ov-spending">{month ? `${month} spending by category` : 'Spending by category'}</h2>
      {overview.isPending && <p className="muted" role="status">Loading…</p>}
      {overview.isError && <p className="error" role="alert">{overview.error.message}</p>}
      {o && (spending.length === 0 ? (
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
      ))}
    </section>
  )
}

function RecentCard({ byId }: { byId: Map<number, Category> }) {
  const overview = useOverview()
  const recent = overview.data?.recent
  return (
    <section className="card" aria-labelledby="ov-recent">
      <h2 className="card-title" id="ov-recent">Recent</h2>
      {overview.isPending && <p className="muted" role="status">Loading…</p>}
      {overview.isError && <p className="error" role="alert">{overview.error.message}</p>}
      {recent && (recent.length === 0 ? (
        <p className="muted">No transactions yet.</p>
      ) : (
        <ul className="recent-list">
          {recent.map((t) => (
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
      ))}
    </section>
  )
}

function BalancesCard() {
  const overview = useOverview()
  const b = overview.data?.balances
  const rows: [string, number][] = b ? [['Cash', b.cash], ['Investments', b.investments], ['Credit cards', b.credit]] : []
  if (b && b.loans !== 0) rows.push(['Loans', b.loans])
  if (b && b.other !== 0) rows.push(['Other', b.other])
  return (
    <section className="card" aria-labelledby="ov-balances">
      <h2 className="card-title" id="ov-balances">Balances</h2>
      {overview.isPending && <p className="muted" role="status">Loading…</p>}
      {overview.isError && <p className="error" role="alert">{overview.error.message}</p>}
      {b && (
        <dl className="balances">
          {rows.map(([label, cents]) => (
            <div key={label} className="balance-row">
              <dt>{label}</dt>
              <dd>{formatCents(cents)}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  )
}

export default function Overview() {
  const categories = useQuery({ queryKey: ['categories'], queryFn: api.categories })
  const byId = new Map<number, Category>((categories.data ?? []).map((c) => [c.id, c]))

  return (
    <>
      <header className="page-head">
        <h1>{greeting(new Date().getHours())}</h1>
      </header>

      <div className="tiles">
        <NetWorthTile />
        <MonthTile />
        <BudgetTile />
        <ReviewTile />
      </div>

      <div className="ov-grid">
        <div className="ov-side">
          <AlertsCard />
          <DueCard />
          <VestCard />
          <GoalsCard />
          <BalancesCard />
        </div>

        <div className="ov-main">
          <SpendingCard byId={byId} />
          <RecentCard byId={byId} />
        </div>
      </div>
    </>
  )
}
