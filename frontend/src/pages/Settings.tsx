import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, type AllocationTargets, type BudgetSettings } from '../api'
import { dollarsToCents, formatDateTime } from '../format'

const dollars = (cents: number | null) => (cents === null ? '' : (cents / 100).toFixed(2))
const wholePct = (text: string) => (/^\d{1,3}$/.test(text.trim()) ? Number(text) : null)

const PCT_FIELDS = [['needs_pct', 'Needs'], ['wants_pct', 'Wants'], ['savings_pct', 'Savings']] as const

function BudgetForm({ saved }: { saved: BudgetSettings }) {
  const qc = useQueryClient()
  const [takeHome, setTakeHome] = useState(dollars(saved.take_home_cents))
  const [pcts, setPcts] = useState({ needs_pct: String(saved.needs_pct), wants_pct: String(saved.wants_pct), savings_pct: String(saved.savings_pct) })
  const save = useMutation({
    mutationFn: api.saveBudgetSettings,
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ['budgetSettings'] }), qc.invalidateQueries({ queryKey: ['budget'] })]),
  })

  const takeHomeCents = dollarsToCents(takeHome)
  const parsed = PCT_FIELDS.map(([key]) => wholePct(pcts[key]))
  const total = parsed.reduce<number>((sum, p) => sum + (p ?? 0), 0)
  const allParsed = parsed.every((p) => p !== null)
  const pctsOk = allParsed && total === 100
  const amountsOk = takeHomeCents !== null && takeHomeCents > 0
  // Why Save is off, in the order a person would fix things.
  const reason = !amountsOk ? 'Enter your take-home pay'
    : !allParsed ? 'Enter whole numbers for the split'
    : !pctsOk ? 'Make the split add up to 100%'
    : null
  const blocked = reason !== null
  const empty = saved.take_home_cents === null

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (blocked) return
    save.mutate({
      take_home_cents: takeHomeCents!,
      needs_pct: parsed[0]!, wants_pct: parsed[1]!, savings_pct: parsed[2]!,
    })
  }

  return (
    <form className="budget-form" onSubmit={onSubmit}>
      {empty && <p className="muted">Enter your monthly take-home pay to set spending targets for each bucket.</p>}
      <div className="form-grid">
        <label>Take-home per month ($)
          <input inputMode="decimal" value={takeHome} onChange={(e) => { setTakeHome(e.target.value); save.reset() }} placeholder="0.00" />
        </label>
      </div>
      <fieldset>
        <legend>Split of take-home (%)</legend>
        <div className="form-grid">
          {PCT_FIELDS.map(([key, label], i) => (
            <label key={key}>{label}
              <input
                inputMode="numeric" value={pcts[key]}
                aria-invalid={parsed[i] === null} aria-describedby={parsed[i] === null ? `pct-err-${key}` : undefined}
                onChange={(e) => { setPcts({ ...pcts, [key]: e.target.value }); save.reset() }}
              />
            </label>
          ))}
        </div>
        {PCT_FIELDS.map(([key, label], i) => parsed[i] === null && (
          <p key={key} id={`pct-err-${key}`} className="error budget-total">{label}: enter a whole number</p>
        ))}
        {allParsed && (pctsOk
          ? <p className="budget-total">= {total}%</p>
          : <p className="budget-total bad" role="status">= {total}% (must be 100%)</p>)}
      </fieldset>
      {save.error && <p className="error" role="alert">{save.error.message}</p>}
      <div className="actions-row">
        <button type="submit" className="primary" disabled={save.isPending || blocked}>{save.isPending ? 'Saving…' : 'Save budget'}</button>
      </div>
      {reason && <p className="muted">{reason}</p>}
      {save.isSuccess && <p className="muted" role="status">Budget saved.</p>}
    </form>
  )
}

const TARGET_FIELDS = [['stocks_pct', 'Stocks'], ['bonds_pct', 'Bonds'], ['cash_pct', 'Cash']] as const

function TargetsForm({ saved }: { saved: AllocationTargets }) {
  const qc = useQueryClient()
  const [pcts, setPcts] = useState({ stocks_pct: String(saved.stocks_pct ?? ''), bonds_pct: String(saved.bonds_pct ?? ''), cash_pct: String(saved.cash_pct ?? '') })
  const [threshold, setThreshold] = useState(String(saved.drift_threshold))
  const save = useMutation({
    mutationFn: api.saveAllocationTargets,
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ['allocationTargets'] }), qc.invalidateQueries({ queryKey: ['allocation'] })]),
  })

  const parsed = TARGET_FIELDS.map(([key]) => wholePct(pcts[key]))
  // A blank field is just unfilled (the disabled-Save reason covers it); only typed junk gets an error.
  const junk = TARGET_FIELDS.map(([key], i) => parsed[i] === null && pcts[key].trim() !== '')
  const total = parsed.reduce<number>((sum, p) => sum + (p ?? 0), 0)
  const allParsed = parsed.every((p) => p !== null)
  const pctsOk = allParsed && total === 100
  const limit = wholePct(threshold)
  const limitOk = limit !== null && limit >= 1 && limit <= 50
  const reason = !allParsed ? 'Enter whole numbers for the split'
    : !pctsOk ? 'Make the split add up to 100%'
    : !limitOk ? 'Enter a drift threshold from 1 to 50'
    : null

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (reason) return
    save.mutate({ stocks_pct: parsed[0]!, bonds_pct: parsed[1]!, cash_pct: parsed[2]!, drift_threshold: limit! })
  }

  return (
    <form className="budget-form" onSubmit={onSubmit}>
      <fieldset>
        <legend>Target split (%)</legend>
        <div className="form-grid">
          {TARGET_FIELDS.map(([key, label], i) => (
            <label key={key}>{label}
              <input
                inputMode="numeric" value={pcts[key]}
                aria-invalid={junk[i]} aria-describedby={junk[i] ? `tgt-err-${key}` : undefined}
                onChange={(e) => { setPcts({ ...pcts, [key]: e.target.value }); save.reset() }}
              />
            </label>
          ))}
        </div>
        {TARGET_FIELDS.map(([key, label], i) => junk[i] && (
          <p key={key} id={`tgt-err-${key}`} className="error budget-total">{label}: enter a whole number</p>
        ))}
        {allParsed && (pctsOk
          ? <p className="budget-total">= {total}%</p>
          : <p className="budget-total bad" role="status">= {total}% (must be 100%)</p>)}
      </fieldset>
      <div className="form-grid">
        <label>Drift threshold (points, 1 to 50)
          <input
            inputMode="numeric" value={threshold}
            aria-invalid={!limitOk} aria-describedby={limitOk ? undefined : 'tgt-err-threshold'}
            onChange={(e) => { setThreshold(e.target.value); save.reset() }}
          />
        </label>
      </div>
      {!limitOk && <p id="tgt-err-threshold" className="error budget-total">Drift threshold: enter a whole number from 1 to 50</p>}
      {save.error && <p className="error" role="alert">{save.error.message}</p>}
      <div className="actions-row">
        <button type="submit" className="primary" disabled={save.isPending || reason !== null}>{save.isPending ? 'Saving…' : 'Save targets'}</button>
      </div>
      {reason && <p className="muted">{reason}</p>}
      {save.isSuccess && <p className="muted" role="status">Targets saved.</p>}
    </form>
  )
}

export default function Settings() {
  const qc = useQueryClient()
  const runs = useQuery({ queryKey: ['syncRuns'], queryFn: api.syncRuns })
  const sync = useMutation({ mutationFn: api.sync, onSuccess: () => qc.invalidateQueries() })
  const budget = useQuery({ queryKey: ['budgetSettings'], queryFn: api.budgetSettings })
  const targets = useQuery({ queryKey: ['allocationTargets'], queryFn: api.allocationTargets })
  const backup = useMutation({ mutationFn: api.backup })

  return (
    <>
      <header className="page-head"><h1>Settings</h1></header>

      <section className="card" aria-labelledby="set-sync">
        <div className="set-head">
          <div>
            <h2 className="card-title" id="set-sync">Sync</h2>
            <p className="muted set-blurb">Pull the latest balances and transactions from SimpleFIN.</p>
          </div>
          <button className="primary" onClick={() => sync.mutate()} disabled={sync.isPending}>
            {sync.isPending ? 'Syncing…' : 'Sync now'}
          </button>
        </div>
        {sync.error && <p className="error" role="alert">{sync.error.message}</p>}
        {sync.data?.error && <p className="error" role="alert">{sync.data.error}</p>}

        <h3 className="set-sub">Recent syncs</h3>
        {runs.isLoading && <p className="muted" role="status">Loading…</p>}
        {runs.error && <p className="error" role="alert">{runs.error.message}</p>}
        {runs.data && runs.data.length === 0 && <p className="muted">No syncs yet.</p>}
        {runs.data && runs.data.length > 0 && (
          <div className="table-wrap">
            <table className="runs">
              <thead>
                <tr><th>Started</th><th>Status</th><th className="num">Accounts</th><th className="num">New</th><th>Error</th></tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id}>
                    <td>{formatDateTime(r.started_at)}</td>
                    <td><span className={`pill ${r.status}`}>{r.status}</span></td>
                    <td className="num">{r.accounts_ok}{r.accounts_stale ? ` (+${r.accounts_stale} stale)` : ''}</td>
                    <td className="num">{r.txns_added}</td>
                    <td className="muted">{r.error ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card" aria-labelledby="set-budget">
        <h2 className="card-title" id="set-budget">Budget</h2>
        <p className="muted set-blurb">Targets for needs (rent included), wants and savings, worked out from your monthly take-home pay.</p>
        {budget.isLoading && <p className="muted" role="status">Loading…</p>}
        {budget.error && <p className="error" role="alert">{budget.error.message}</p>}
        {budget.data && <BudgetForm saved={budget.data} />}
      </section>

      <section className="card" aria-labelledby="set-targets">
        <h2 className="card-title" id="set-targets">Allocation targets</h2>
        <p className="muted set-blurb">Your intended split across stocks, bonds and cash. The Net worth page flags any class that drifts past the threshold.</p>
        {targets.isLoading && <p className="muted" role="status">Loading…</p>}
        {targets.error && <p className="error" role="alert">{targets.error.message}</p>}
        {targets.data && <TargetsForm saved={targets.data} />}
      </section>

      <section className="card" aria-labelledby="set-data">
        <h2 className="card-title" id="set-data">Data</h2>
        <p className="muted set-blurb">Keep a copy of your ledger, or take it with you.</p>
        <div className="actions-row">
          <button onClick={() => backup.mutate()} disabled={backup.isPending}>{backup.isPending ? 'Backing up…' : 'Back up now'}</button>
          <a className="button" href="/api/export">Export data</a>
        </div>
        {backup.data && <p className="muted" role="status">Backup saved to {backup.data.path}</p>}
        {backup.error && <p className="error" role="alert">{backup.error.message}</p>}
      </section>
    </>
  )
}
