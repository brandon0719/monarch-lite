import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { api, type RsuGrant, type RsuGrantInput, type RsuSchedule } from '../api'
import { formatCents, formatDate, formatDateTime } from '../format'

const SCHEDULES: [RsuSchedule, string][] = [
  ['amazon_5_15_40_40', 'Amazon (5 / 15 / 40 / 40)'], ['semiannual', 'Semiannual'], ['custom', 'Custom'],
]
const MAX_SHARES = 1_000_000
const MAX_COUNT = 20
const MAX_ROWS = 100
const ISO = /^\d{4}-\d{2}-\d{2}$/

const n = (value: number) => value.toLocaleString()
const money = (cents: number | null) => (cents === null ? '—' : formatCents(cents))
const whole = (text: string) => (/^\d+$/.test(text.trim()) ? Number(text.trim()) : null)
const sourceLabel = (source: string) => (source === 'finnhub' ? 'Finnhub' : 'Brokerage holding')

/** Mirrors services/rsu.py: floor each part, the remainder goes to the last, empty parts are dropped. */
function split(total: number, weights: number[]): number[] {
  const sum = weights.reduce((a, b) => a + b, 0)
  const parts = weights.map((w) => Math.floor((total * w) / sum))
  parts[parts.length - 1]! += total - parts.reduce((a, b) => a + b, 0)
  return parts
}

/** ISO date moved by `months`, on `day` (default: its own day), clamped to the month's end. */
function addMonths(iso: string, months: number, day?: number): string {
  const [y, m, d] = iso.split('-').map(Number) as [number, number, number]
  const total = m - 1 + months
  const year = y + Math.floor(total / 12)
  const month = (((total % 12) + 12) % 12) + 1
  const last = new Date(year, month, 0).getDate()
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(Math.min(day ?? d, last)).padStart(2, '0')}`
}

function amazonVests(start: string, total: number): [string, number][] {
  const [y, m] = start.split('-').map(Number) as [number, number]
  const pad = (v: number) => String(v).padStart(2, '0')
  const second = `${String(y + 2).padStart(4, '0')}-${pad(m)}-15`
  const dates = [`${String(y + 1).padStart(4, '0')}-${pad(m)}-15`, second, ...[1, 2, 3, 4].map((k) => addMonths(second, 6 * k))]
  const shares = split(total, [5, 15, 20, 20, 20, 20])
  return dates.map((d, i) => [d, shares[i]!] as [string, number]).filter(([, s]) => s > 0)
}

function semiannualVests(first: string, total: number, count: number): [string, number][] {
  const day = Number(first.slice(8))
  return split(total, Array<number>(count).fill(1)).map((s, k) => [addMonths(first, 6 * k, day), s] as [string, number]).filter(([, s]) => s > 0)
}

interface Row { key: number; date: string; shares: string }

function GrantForm({ busy, error, onSubmit, onCancel }: {
  busy: boolean; error: string | null; onSubmit: (body: RsuGrantInput) => void; onCancel: () => void
}) {
  const [label, setLabel] = useState('')
  const [symbol, setSymbol] = useState('AMZN')
  const [grantDate, setGrantDate] = useState('')
  const [startDate, setStartDate] = useState('')
  const [total, setTotal] = useState('')
  const [schedule, setSchedule] = useState<RsuSchedule>('amazon_5_15_40_40')
  const [firstVest, setFirstVest] = useState('')
  const [count, setCount] = useState('4')
  const nextKey = useRef(2)
  const [rows, setRows] = useState<Row[]>([{ key: 0, date: '', shares: '' }, { key: 1, date: '', shares: '' }])
  const setRow = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  const totalN = whole(total)
  const totalOk = totalN !== null && totalN >= 1 && totalN <= MAX_SHARES
  const countN = whole(count)
  const filled = rows.filter((r) => r.date || r.shares)
  const parsed = filled.map((r) => ({ date: r.date, shares: whole(r.shares) }))
  const rowsSum = parsed.reduce((a, r) => a + (r.shares ?? 0), 0)
  const dateCounts = new Map<string, number>()
  for (const r of filled) if (ISO.test(r.date)) dateCounts.set(r.date, (dateCounts.get(r.date) ?? 0) + 1)
  /** Per-row problems, only for rows the user has started; an untouched row is not an error. */
  const rowProblem = (r: Row) => {
    if (!r.date && !r.shares) return { date: false, shares: false, text: '' }
    const shares = whole(r.shares)
    const date = !ISO.test(r.date) ? 'Pick a date' : (dateCounts.get(r.date) ?? 0) > 1 ? 'Duplicate date' : ''
    const sh = shares === null || shares < 1 ? 'Enter whole shares, at least 1' : ''
    return { date: date !== '', shares: sh !== '', text: [date, sh].filter(Boolean).join('. ') }
  }
  const customBad = schedule === 'custom' && totalOk ? rowsSum !== totalN : false

  const [field, reason] = !label.trim() ? ['label', 'Enter a label'] as const
    : !symbol.trim() ? ['symbol', 'Enter a symbol'] as const
    : !ISO.test(grantDate) ? ['grant', 'Pick the grant date'] as const
    : !ISO.test(startDate) ? ['start', 'Pick your employment start date'] as const
    : !totalOk ? ['total', `Enter total shares from 1 to ${n(MAX_SHARES)}`] as const
    : schedule === 'semiannual' && !ISO.test(firstVest) ? ['first', 'Pick the first vest date'] as const
    : schedule === 'semiannual' && (countN === null || countN < 1 || countN > MAX_COUNT) ? ['count', `Enter 1 to ${MAX_COUNT} vests`] as const
    : schedule === 'custom' && (parsed.length === 0 || parsed.some((r) => !ISO.test(r.date) || r.shares === null || r.shares < 1)) ? ['rows', 'Give every vest a date and at least 1 share'] as const
    : schedule === 'custom' && new Set(parsed.map((r) => r.date)).size !== parsed.length ? ['rows', 'Each vest date can appear only once'] as const
    : customBad ? ['rows', `Vests add up to ${n(rowsSum)}, not ${n(totalN!)}`] as const
    : [null, null] as const
  const reasonId = reason ? 'eq-reason' : undefined
  const describe = (name: string) => (field === name ? reasonId : undefined)

  const preview = schedule === 'amazon_5_15_40_40' && ISO.test(startDate) && totalOk ? amazonVests(startDate, totalN)
    : schedule === 'semiannual' && ISO.test(firstVest) && totalOk && countN !== null && countN >= 1 && countN <= MAX_COUNT ? semiannualVests(firstVest, totalN, countN)
    : null

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (reason !== null || totalN === null) return
    const body: RsuGrantInput = { label: label.trim(), symbol: symbol.trim(), grant_date: grantDate, start_date: startDate, total_shares: totalN, schedule }
    if (schedule === 'semiannual') { body.first_vest = firstVest; body.count = countN! }
    if (schedule === 'custom') body.vests = parsed.map((r) => ({ vest_date: r.date, shares: r.shares! }))
    onSubmit(body)
  }

  return (
    <form className="rc-form gl-form eq-form" onSubmit={submit}>
      <label>Label
        <input value={label} maxLength={100} autoFocus placeholder="e.g. 2025 new-hire grant" aria-describedby={describe('label')} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label>Symbol
        <input value={symbol} maxLength={16} aria-describedby={describe('symbol')} onChange={(e) => setSymbol(e.target.value.toUpperCase())} />
      </label>
      <label>Grant date
        <input type="date" value={grantDate} aria-describedby={describe('grant')} onChange={(e) => setGrantDate(e.target.value)} />
      </label>
      <label>Employment start date
        <input type="date" value={startDate} aria-describedby={describe('start')} onChange={(e) => setStartDate(e.target.value)} />
      </label>
      <label>Total shares
        <input inputMode="numeric" value={total} aria-invalid={total !== '' && !totalOk} aria-describedby={describe('total')} onChange={(e) => setTotal(e.target.value)} />
      </label>
      <label>Schedule
        <select value={schedule} onChange={(e) => setSchedule(e.target.value as RsuSchedule)}>
          {SCHEDULES.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
        </select>
      </label>

      {schedule === 'semiannual' && (
        <>
          <label>First vest date
            <input type="date" value={firstVest} aria-describedby={describe('first')} onChange={(e) => setFirstVest(e.target.value)} />
          </label>
          <label>Number of vests
            <input inputMode="numeric" value={count} aria-invalid={countN === null || countN < 1 || countN > MAX_COUNT} aria-describedby={describe('count')} onChange={(e) => setCount(e.target.value)} />
          </label>
        </>
      )}

      {schedule === 'custom' && (
        <fieldset className="gl-fieldset eq-rows" aria-describedby={describe('rows')}>
          <legend>Vests</legend>
          {rows.map((r, i) => {
            const p = rowProblem(r)
            const msgId = p.text ? `eq-row-msg-${r.key}` : undefined
            return (
              <div key={r.key} className="eq-row">
                <label><span className="visually-hidden">Vest {i + 1} date</span>
                  <input type="date" value={r.date} aria-invalid={p.date} aria-describedby={p.date ? msgId : undefined} onChange={(e) => setRow(r.key, { date: e.target.value })} />
                </label>
                <label><span className="visually-hidden">Vest {i + 1} shares</span>
                  <input inputMode="numeric" placeholder="Shares" value={r.shares} aria-invalid={p.shares} aria-describedby={p.shares ? msgId : undefined} onChange={(e) => setRow(r.key, { shares: e.target.value })} />
                </label>
                <button type="button" className="icon-button" aria-label={`Remove vest ${i + 1}`} disabled={rows.length === 1}
                  onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>Remove</button>
                {p.text && <span className="error eq-row-msg" id={msgId}>{p.text}</span>}
              </div>
            )
          })}
          <div className="actions-row eq-row-add">
            <button type="button" disabled={rows.length >= MAX_ROWS} onClick={() => setRows((rs) => [...rs, { key: nextKey.current++, date: '', shares: '' }])}>Add vest</button>
            <span className="muted" role="status">{customBad ? `Sum ${n(rowsSum)} of ${n(totalN!)}` : ''}</span>
          </div>
        </fieldset>
      )}

      {preview && (
        <div className="eq-preview">
          <h3 className="set-sub">Preview</h3>
          <ul className="rc-list" aria-label="Vest preview">
            {preview.map(([date, shares]) => (
              <li key={date} className="eq-prev-row"><span className="rc-date">{formatDate(date)}</span><span className="num">{n(shares)} sh</span></li>
            ))}
          </ul>
        </div>
      )}

      <div className="actions-row rc-actions">
        <button type="submit" className="primary" disabled={busy || reason !== null}>Save grant</button>
        <button type="button" onClick={onCancel}>Cancel</button>
        {reason && <span className="muted" id={reasonId}>{reason}</span>}
      </div>
      {error && <p className="error gl-error" role="alert">{error}</p>}
    </form>
  )
}

function EditForm({ grant, busy, error, onSubmit, onCancel }: {
  grant: RsuGrant; busy: boolean; error: string | null
  onSubmit: (changed: { label?: string; external_id?: string }) => void; onCancel: () => void
}) {
  const [label, setLabel] = useState(grant.label)
  const [externalId, setExternalId] = useState(grant.external_id ?? '')
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!label.trim()) return
    const changed: { label?: string; external_id?: string } = {}
    if (label.trim() !== grant.label) changed.label = label.trim()
    if (externalId.trim() !== (grant.external_id ?? '')) changed.external_id = externalId.trim()
    if (Object.keys(changed).length === 0) onCancel()
    else onSubmit(changed)
  }
  const reasonId = `eq-edit-reason-${grant.id}`
  return (
    <form className="rc-form gl-form" onSubmit={submit}>
      <label>Label
        <input value={label} maxLength={100} autoFocus aria-describedby={label.trim() ? undefined : reasonId} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label>Plan grant ID (optional)
        <input value={externalId} maxLength={64} onChange={(e) => setExternalId(e.target.value)} />
      </label>
      <div className="actions-row rc-actions">
        <button type="submit" className="primary" disabled={busy || !label.trim()}>Save</button>
        <button type="button" onClick={onCancel}>Cancel</button>
        {!label.trim() && <span className="muted" id={reasonId}>Enter a label</span>}
      </div>
      {error && <p className="error gl-error" role="alert">{error}</p>}
    </form>
  )
}

function GrantCard({ grant, onRemoved }: { grant: RsuGrant; onRemoved: () => void }) {
  const [editing, setEditing] = useState(false)
  const editButton = useRef<HTMLButtonElement>(null)
  const restoreFocus = useRef<(() => void) | null>(null)
  useEffect(() => { restoreFocus.current?.(); restoreFocus.current = null })
  const closeEdit = () => { restoreFocus.current = () => editButton.current?.focus(); setEditing(false) }
  // main.tsx refetches ['rsu'] after any successful mutation.
  const update = useMutation({ mutationFn: (body: { label?: string; external_id?: string }) => api.patchGrant(grant.id, body), onSuccess: closeEdit })
  const remove = useMutation({ mutationFn: () => api.deleteGrant(grant.id), onSuccess: onRemoved })
  const del = () => { if (window.confirm(`Delete grant ${grant.label}?`)) remove.mutate() }

  const headingId = `eq-${grant.id}`
  const summary = `${n(grant.vested_shares)} of ${n(grant.total_shares)} vested`
  const fill = grant.total_shares > 0 ? Math.min(grant.vested_shares / grant.total_shares, 1) * 100 : 0
  const nextId = grant.vests.find((v) => !v.vested)?.id

  return (
    <section className="card gl-card eq-card" aria-labelledby={headingId}>
      <div className="card-head">
        <h2 className="gl-title" id={headingId}>
          {grant.label}
          <span className="muted"> {grant.symbol} · {n(grant.total_shares)} shares</span>
        </h2>
        {!editing && (
          <span className="rc-buttons">
            <button type="button" className="icon-button" ref={editButton} aria-label={`Edit ${grant.label}`} onClick={() => { update.reset(); setEditing(true) }}>Edit</button>
            <button type="button" className="icon-button" aria-label={`Delete ${grant.label}`} disabled={remove.isPending} onClick={del}>Delete</button>
          </span>
        )}
      </div>
      {remove.error && <p className="error" role="alert">{remove.error.message}</p>}

      {editing && <EditForm grant={grant} busy={update.isPending} error={update.error?.message ?? null} onSubmit={(body) => update.mutate(body)} onCancel={closeEdit} />}

      <div className="meter" role="img" aria-label={summary} title={summary} style={{ '--b': 'var(--accent)' } as CSSProperties}>
        <span className="trk" aria-hidden="true"><span style={{ width: `${fill}%` }} /></span>
      </div>
      <p className="gl-amounts">{summary}</p>
      <p className="gl-status">
        {n(grant.unvested_shares)} unvested{grant.unvested_value_cents !== null && ` · ${formatCents(grant.unvested_value_cents)}`}
        {grant.external_id && ` · Plan ID ${grant.external_id}`}
      </p>

      <div className="table-wrap">
        <table className="eq-table" aria-label={`Vest schedule for ${grant.label}`}>
          <thead><tr><th>Date</th><th className="num">Shares</th><th className="num">Value</th><th>Status</th></tr></thead>
          <tbody>
            {grant.vests.map((v) => (
              <tr key={v.id} className={v.id === nextId ? 'eq-next' : undefined}>
                <td>{formatDate(v.vest_date)}</td>
                <td className="num">{n(v.shares)}</td>
                <td className="num">{money(v.value_cents)}</td>
                <td>
                  <div className="eq-pills">
                    <span className={`pill ${v.vested ? 'success' : 'upcoming'}`}>{v.vested ? 'Vested' : 'Upcoming'}</span>
                    {v.id === nextId && <span className="pill running">Next</span>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

const GROWTHS = [-20, 0, 10, 20]

function CompCard() {
  const [growth, setGrowth] = useState(0)
  const thisYear = new Date().getFullYear()
  const comp = useQuery({ queryKey: ['income', 'comp', growth], queryFn: () => api.compProjection(growth), placeholderData: (prev) => prev })
  const d = comp.data
  return (
    <section className="card" aria-labelledby="eq-comp">
      <div className="card-head">
        <h2 className="card-title" id="eq-comp">Total comp by year</h2>
        <label className="eq-growth">Stock growth per year
          <select value={growth} onChange={(e) => setGrowth(Number(e.target.value))}>
            {GROWTHS.map((g) => <option key={g} value={g}>{g > 0 ? `+${g}%` : g < 0 ? `−${-g}%` : '0%'}</option>)}
          </select>
        </label>
      </div>
      {comp.isPending && <p className="muted" role="status">Loading…</p>}
      {comp.isError && <p className="error" role="alert">{comp.error.message}</p>}
      {d && d.years.length === 0 && <p className="muted">Add your salary or an RSU grant to project your total comp.</p>}
      {d && d.years.length > 0 && (
        <>
          <div className={`table-wrap${comp.isPlaceholderData ? ' nw-stale' : ''}`}>
            <table className="inc-table eq-comp-table" aria-label="Total comp by year">
              <thead><tr><th>Year</th><th className="num">Salary</th><th className="num">Sign-on and cash</th><th className="num">RSU</th><th className="num">Total</th></tr></thead>
              <tbody>
                {d.years.map((y) => (
                  <tr key={y.year} className={y.year === thisYear ? 'eq-next' : undefined}>
                    <td>{y.year}{y.year === thisYear && <span className="muted"> · this year</span>}</td>
                    <td className="num">{formatCents(y.salary_cents)}</td>
                    <td className="num">{formatCents(y.cash_cents)}</td>
                    <td className="num">{y.rsu_shares === 0 ? '—' : `${n(y.rsu_shares)} sh · ${y.rsu_cents === null ? '—' : formatCents(y.rsu_cents)}`}</td>
                    <td className="num">{money(y.total_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted sp-note">RSU values use today's {d.price?.symbol ?? 'stock'} price grown by the selected rate per year. A projection, not a forecast.</p>
        </>
      )}
    </section>
  )
}

export default function Equity() {
  const rsu = useQuery({ queryKey: ['rsu'], queryFn: api.rsu })
  const [adding, setAdding] = useState(false)
  const newButton = useRef<HTMLButtonElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const restoreFocus = useRef<(() => void) | null>(null)
  useEffect(() => { restoreFocus.current?.(); restoreFocus.current = null })
  // Bumped whenever the form opens or closes, so a slow create can't close a form the user reopened meanwhile.
  const session = useRef(0)
  const closeAdd = () => { session.current++; restoreFocus.current = () => newButton.current?.focus(); setAdding(false) }
  const create = useMutation({ mutationFn: api.createGrant })

  const d = rsu.data
  const t = d?.totals

  return (
    <>
      <header className="page-head">
        <h1 ref={heading} tabIndex={-1}>Equity</h1>
        {!adding && <button type="button" ref={newButton} onClick={() => { create.reset(); session.current++; setAdding(true) }}>Add grant</button>}
      </header>
      {rsu.isPending && <p className="muted" role="status">Loading…</p>}
      {rsu.isError && <p className="error" role="alert">{rsu.error.message}</p>}

      {adding && (
        <section className="card" aria-label="New grant">
          <h2 className="card-title">New grant</h2>
          <GrantForm
            busy={create.isPending} error={create.error?.message ?? null}
            onSubmit={(body) => { const s = session.current; create.mutate(body, { onSuccess: () => { if (session.current === s) closeAdd() } }) }}
            onCancel={closeAdd}
          />
        </section>
      )}

      {d && d.grants.length === 0 && !adding && (
        <p className="muted">No grants yet. Add your RSU grant from your offer letter or the equity plan portal.</p>
      )}

      {d && t && d.grants.length > 0 && (
        <>
          <p className="muted eq-price">
            {d.price
              ? `${d.price.symbol} ${formatCents(d.price.price_cents)} · ${sourceLabel(d.price.source)} · ${d.price.source === 'holding' ? formatDate(d.price.as_of.slice(0, 10)) : formatDateTime(d.price.as_of)}`
              : 'No price yet. It uses your Finnhub key, or a synced brokerage holding of the same symbol.'}
          </p>
          <div className="tiles">
            <div className="tile">
              <div className="tile-label">Unvested value</div>
              <div className="tile-value">{money(t.unvested_value_cents)}</div>
              <div className="tile-sub">{n(t.unvested_shares)} {t.unvested_shares === 1 ? 'share' : 'shares'}{t.unvested_value_cents === null && ' · needs a price'}</div>
            </div>
            <div className="tile">
              <div className="tile-label">Vested shares</div>
              <div className="tile-value">{n(t.vested_shares)}</div>
            </div>
            <div className="tile">
              <div className="tile-label">Next vest</div>
              <div className="tile-value">{t.next_vest ? formatDate(t.next_vest.vest_date) : 'None'}</div>
              {t.next_vest && (
                <div className="tile-sub">{n(t.next_vest.shares)} sh{t.next_vest.value_cents !== null && ` · ${formatCents(t.next_vest.value_cents)}`} ({t.next_vest.grant_label})</div>
              )}
            </div>
          </div>
          {d.grants.map((g) => <GrantCard key={g.id} grant={g} onRemoved={() => heading.current?.focus()} />)}
          <CompCard />
        </>
      )}
    </>
  )
}
