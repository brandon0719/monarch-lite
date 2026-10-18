import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { api, type AllocationClass, type AssetClassName, type Holding, type NetWorthPoint, type NetWorthRange } from '../api'
import NetWorthChart from '../components/NetWorthChart'
import UnvestedLine from '../components/UnvestedLine'
import { formatCents, formatDate } from '../format'

const RANGES: [NetWorthRange, string][] = [['1M', '1M'], ['3M', '3M'], ['YTD', 'YTD'], ['1Y', '1Y'], ['ALL', 'All']]
const CLASSES: [AssetClassName, string][] = [['stocks', 'Stocks'], ['bonds', 'Bonds'], ['cash', 'Cash']]

const signed = (cents: number) => `${cents < 0 ? '−' : '+'}${formatCents(Math.abs(cents))}`
const tone = (cents: number) => (cents > 0 ? 'pos' : cents < 0 ? 'error' : undefined)
/** Exact decimal text without trailing zeros: "10.5000" -> "10.5". */
const shares = (text: string) => (text.includes('.') ? text.replace(/\.?0+$/, '') : text)

/** The last point of each month, in date order. */
function monthly(points: NetWorthPoint[]): NetWorthPoint[] {
  const byMonth = new Map<string, NetWorthPoint>()
  for (const p of points) byMonth.set(p.date.slice(0, 7), p)
  return [...byMonth.values()]
}

function HistoryCard() {
  const [range, setRange] = useState<NetWorthRange>('3M')
  const nw = useQuery({ queryKey: ['networth', range], queryFn: () => api.networth(range), placeholderData: keepPreviousData })
  const points = nw.data?.points ?? []
  const first = points[0]
  const last = points[points.length - 1]
  const note = nw.data?.first_actual_date && points.some((p) => p.estimated) ? nw.data.first_actual_date : null

  return (
    <section className="card" aria-labelledby="nw-history">
      <div className="card-head">
        <h2 className="card-title" id="nw-history">History</h2>
        <div className="pills nw-ranges" role="group" aria-label="Range">
          {RANGES.map(([value, label]) => (
            <button key={value} type="button" className={`pill${range === value ? ' active' : ''}`} aria-pressed={range === value} onClick={() => setRange(value)}>{label}</button>
          ))}
        </div>
      </div>
      {nw.isPending && <p className="muted" role="status">Loading…</p>}
      {nw.isError && <p className="error" role="alert">{nw.error.message}</p>}
      {nw.data && (
        <div className={nw.isPlaceholderData ? 'nw-stale' : undefined} aria-busy={nw.isPlaceholderData}>
          {last && first && (
            <p className="nw-headline">
              <strong className="nw-total">{formatCents(last.net_cents)}</strong>
              <span className={`nw-change ${tone(nw.data.change_cents) ?? ''}`}>{signed(nw.data.change_cents)}</span>
              <span className="muted"> since {formatDate(first.date)}</span>
              <UnvestedLine />
            </p>
          )}
          {!(last && first) && <UnvestedLine />}
          <NetWorthChart points={points} />
          {note && <p className="muted sp-note">Dashed line: estimated before {formatDate(note)} (cash rebuilt from transactions; investments held at their first known value)</p>}
          {points.length > 0 && (
            <details className="nw-data">
              <summary>Show data</summary>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Date</th><th className="num">Assets</th><th className="num">Liabilities</th><th className="num">Net worth</th></tr></thead>
                  <tbody>
                    {monthly(points).map((p) => (
                      <tr key={p.date}>
                        <td>{formatDate(p.date)}{p.estimated && <span className="muted"> · estimated</span>}</td>
                        <td className="num">{formatCents(p.assets_cents)}</td>
                        <td className="num">{formatCents(p.liabilities_cents)}</td>
                        <td className="num">{formatCents(p.net_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  )
}

/** One decimal at most, no trailing ".0": 2 -> "2", 2.5 -> "2.5". */
const pts = (n: number) => String(Math.round(n * 10) / 10)
/** Gain as a signed percent; a gain that rounds to zero carries no sign (never "−0.0%"). */
const gainPct = (g: number) => (Math.abs(g) < 0.0005 ? '0.0%' : `${g < 0 ? '−' : '+'}${Math.abs(g * 100).toFixed(1)}%`)

function allocationText(c: AllocationClass, label: string) {
  const now = `${pts(c.pct * 100)}%`
  if (c.target_pct === null || c.drift_pts === null) return { short: now, full: `${label} ${now}` }
  const drift = c.over ? `${c.drift_pts > 0 ? 'Over' : 'Under'} by ${pts(Math.abs(c.drift_pts))} pts`
    : c.drift_pts === 0 ? 'on target' : `${c.drift_pts > 0 ? '+' : '−'}${pts(Math.abs(c.drift_pts))} pts`
  const short = `${now} · target ${c.target_pct}% · ${drift}`
  return { short, full: `${label} ${short}` }
}

function AllocationCard() {
  const alloc = useQuery({ queryKey: ['allocation'], queryFn: api.allocation })
  const d = alloc.data
  return (
    <section className="card" aria-labelledby="nw-alloc">
      <div className="card-head">
        <h2 className="card-title" id="nw-alloc">Allocation</h2>
        {d && d.total_cents > 0 && <span className="muted al-total">{formatCents(d.total_cents)} invested</span>}
      </div>
      {alloc.isPending && <p className="muted" role="status">Loading…</p>}
      {alloc.isError && <p className="error" role="alert">{alloc.error.message}</p>}
      {d && d.total_cents === 0 && <p className="muted">No holdings to allocate yet.</p>}
      {d && d.total_cents > 0 && (
        <>
          <ul className="al-list">
            {d.classes.map((c) => {
              const label = CLASSES.find(([value]) => value === c.asset_class)?.[1] ?? c.asset_class
              const text = allocationText(c, label)
              return (
                <li key={c.asset_class} className={`meter al-row${c.over ? ' over' : ''}`} style={{ '--b': 'var(--accent)' } as CSSProperties}>
                  <div role="img" aria-label={text.full}>
                    <span className="al-top">
                      <span className="al-name">{label}</span>
                      <span className={c.over ? 'error al-text' : 'muted al-text'}>{text.short}</span>
                    </span>
                    <span className="al-bar">
                      <span className="trk"><span style={{ width: `${Math.min(c.pct, 1) * 100}%` }} /></span>
                      {c.target_pct !== null && <span className="al-tick" style={{ left: `${c.target_pct}%` }} />}
                    </span>
                  </div>
                </li>
              )
            })}
          </ul>
          {!d.configured && <p className="muted sp-note">No targets yet. <Link to="/settings">Set targets in Settings</Link></p>}
        </>
      )}
    </section>
  )
}

function HoldingRow({ h, busy, onClass }: { h: Holding; busy: boolean; onClass: (symbol: string, value: AssetClassName) => void }) {
  return (
    <tr>
      <td title={h.description}><div className="nw-sym"><b>{h.symbol}</b><span className="muted">{h.description}</span></div></td>
      <td className="num nw-opt">{shares(h.shares)}</td>
      <td className="num nw-opt">{h.price_cents === null ? '—' : formatCents(h.price_cents)}</td>
      <td className="num">{formatCents(h.market_value_cents)}</td>
      <td className="num nw-opt">{h.cost_basis_cents === null ? '—' : formatCents(h.cost_basis_cents)}</td>
      <td className={`num ${h.gain_cents === null ? '' : tone(h.gain_cents) ?? ''}`}>
        {h.gain_cents === null ? '—' : (
          <>
            <span>{signed(h.gain_cents)}</span>
            {h.gain_pct !== null && <span className="nw-pct"> ({gainPct(h.gain_pct)})</span>}
          </>
        )}
      </td>
      <td>
        <select aria-label={`Asset class for ${h.symbol}`} value={h.asset_class} disabled={busy} onChange={(e) => onClass(h.symbol, e.target.value as AssetClassName)}>
          {CLASSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </td>
    </tr>
  )
}

function HoldingsCard() {
  const holdings = useQuery({ queryKey: ['holdings'], queryFn: api.holdings })
  // main.tsx refetches holdings, allocation and networth after any successful mutation.
  const setClass = useMutation({ mutationFn: ({ symbol, value }: { symbol: string; value: AssetClassName }) => api.setAssetClass(symbol, value) })
  const groups = new Map<number, { name: string; rows: Holding[] }>()
  for (const h of holdings.data ?? []) {
    const g = groups.get(h.account_id) ?? { name: h.account_name, rows: [] }
    g.rows.push(h)
    groups.set(h.account_id, g)
  }

  return (
    <section className="card" aria-labelledby="nw-holdings">
      <h2 className="card-title" id="nw-holdings">Holdings</h2>
      {holdings.isPending && <p className="muted" role="status">Loading…</p>}
      {holdings.isError && <p className="error" role="alert">{holdings.error.message}</p>}
      {setClass.isError && <p className="error" role="alert">{setClass.error.message}</p>}
      {holdings.data && holdings.data.length === 0 && (
        <p className="muted">No investment holdings yet. They appear after a sync of a brokerage account.</p>
      )}
      {[...groups.entries()].map(([id, g]) => (
        <div key={id} className="nw-group">
          <div className="nw-group-head">
            <h3 id={`nw-acct-${id}`}>{g.name}</h3>
            <span className="nw-group-total">{formatCents(g.rows.reduce((sum, r) => sum + r.market_value_cents, 0))}</span>
          </div>
          <div className="table-wrap">
            <table className="nw-table" aria-labelledby={`nw-acct-${id}`}>
              <thead>
                <tr>
                  <th>Holding</th><th className="num nw-opt">Shares</th><th className="num nw-opt">Price</th><th className="num">Value</th>
                  <th className="num nw-opt">Basis</th><th className="num">Gain</th><th>Class</th>
                </tr>
              </thead>
              <tbody>
                {g.rows.map((h) => (
                  <HoldingRow key={h.id} h={h} busy={setClass.isPending && setClass.variables?.symbol === h.symbol}
                    onClass={(symbol, value) => setClass.mutate({ symbol, value })} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </section>
  )
}

export default function NetWorth() {
  return (
    <>
      <header className="page-head"><h1>Net worth</h1></header>
      <HistoryCard />
      <AllocationCard />
      <HoldingsCard />
    </>
  )
}
