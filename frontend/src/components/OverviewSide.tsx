import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { statusLine } from '../goals'
import { formatCents, formatDate, formatPct } from '../format'

/** Bills and income due in the next 7 days, late ones marked in words. */
export function DueCard() {
  const up = useQuery({ queryKey: ['recurring', 'upcoming', 7], queryFn: () => api.upcoming(7) })
  return (
    <section className="card" aria-labelledby="ov-due">
      <h2 className="card-title" id="ov-due">Due in the next 7 days</h2>
      {up.isPending && <p className="muted" role="status">Loading…</p>}
      {up.isError && <p className="error" role="alert">{up.error.message}</p>}
      {up.data && (up.data.rows.length === 0 ? (
        <p className="muted">Nothing due in the next 7 days.</p>
      ) : (
        <ul className="recent-list">
          {up.data.rows.map((r) => (
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
        <Link className="tile-link" to="/recurring">See all →</Link>
      </div>
    </section>
  )
}

/** Hidden with no grants (and while loading); a failed query still says so. */
export function VestCard() {
  const rsu = useQuery({ queryKey: ['rsu'], queryFn: api.rsu })
  if (rsu.isError) {
    return (
      <section className="card" aria-labelledby="ov-vest">
        <h2 className="card-title" id="ov-vest">Next vest</h2>
        <p className="error" role="alert">{rsu.error.message}</p>
      </section>
    )
  }
  if (!rsu.data || rsu.data.grants.length === 0) return null
  const next = rsu.data.totals.next_vest
  return (
    <section className="card" aria-labelledby="ov-vest">
      <h2 className="card-title" id="ov-vest">Next vest</h2>
      {next ? (
        <>
          <p className="vest-date">{formatDate(next.vest_date)}</p>
          <p className="vest-line">
            {next.shares.toLocaleString()} {next.shares === 1 ? 'share' : 'shares'}
            {next.value_cents !== null && <> · {formatCents(next.value_cents)}</>}
          </p>
          <p className="muted vest-label">{next.grant_label}</p>
        </>
      ) : (
        <p className="muted">No upcoming vests.</p>
      )}
      <Link className="tile-link" to="/equity">See equity →</Link>
    </section>
  )
}

/** Active (not done) goals only. Hidden with none, and while loading. */
export function GoalsCard() {
  const goals = useQuery({ queryKey: ['goals'], queryFn: api.goals })
  if (goals.isError) {
    return (
      <section className="card" aria-labelledby="ov-goals">
        <h2 className="card-title" id="ov-goals">Goals</h2>
        <p className="error" role="alert">{goals.error.message}</p>
      </section>
    )
  }
  const active = (goals.data ?? []).filter((g) => g.status !== 'done')
  if (active.length === 0) return null
  return (
    <section className="card" aria-labelledby="ov-goals">
      <h2 className="card-title" id="ov-goals">Goals</h2>
      <ul className="ov-goal-list">
        {active.map((g) => {
          const amounts = `${formatCents(g.current_cents)} of ${formatCents(g.target_cents)}`
          const pct = formatPct(Math.round(g.pct * 100))
          const summary = `${g.name}: ${amounts}, ${pct}`
          const status = statusLine(g)
          return (
            <li key={g.id} className="ov-goal">
              <p className="ov-goal-name">{g.name}</p>
              <div className="meter" role="img" aria-label={summary} title={summary} style={{ '--b': 'var(--accent)' } as CSSProperties}>
                <span className="trk" aria-hidden="true"><span style={{ width: `${Math.min(Math.max(g.pct, 0), 1) * 100}%` }} /></span>
              </div>
              <p className="ov-goal-amounts">{amounts} · {pct}</p>
              <p className="muted ov-goal-status">{status.text}{status.behind && <span className="error">Behind</span>}</p>
            </li>
          )
        })}
      </ul>
      <Link className="tile-link" to="/goals">See goals →</Link>
    </section>
  )
}
