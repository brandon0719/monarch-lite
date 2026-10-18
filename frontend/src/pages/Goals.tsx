import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { api, type Account, type Goal, type GoalInput } from '../api'
import { dollarsToCents, formatCents, formatDate, formatPct, isoDate, monthLabel } from '../format'

const dollars = (cents: number) => (cents / 100).toFixed(2)
const LINKABLE = new Set(['savings', 'investment'])
const SHOWN_CONTRIBUTIONS = 5
type AccountsStatus = 'pending' | 'error' | 'success'

const sameIds = (a: number[], b: number[]) => a.length === b.length && a.every((id) => b.includes(id))
const percent = (g: Goal) => formatPct(Math.round(g.pct * 100))

function reachedBy(reachBy: string): string {
  const label = monthLabel(reachBy.slice(0, 7))
  // monthLabel only adds the year outside the current year; the status text always names it.
  return /\d{4}$/.test(label) ? label : `${label} ${reachBy.slice(0, 4)}`
}

function statusLine(g: Goal): { text: string; behind?: boolean } {
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

function GoalForm({ initial, accounts, accountsStatus, takenIds, busy, error, submitLabel, onSubmit, onCancel }: {
  initial?: Goal; accounts: Account[]; accountsStatus: AccountsStatus; takenIds: Set<number>; busy: boolean; error: string | null
  submitLabel: string; onSubmit: (full: GoalInput, changed: Partial<GoalInput>) => void; onCancel: () => void
}) {
  const key = initial?.id ?? 'new'
  const ownIds = (initial?.accounts ?? []).map((a) => a.id)
  const [name, setName] = useState(initial?.name ?? '')
  const [target, setTarget] = useState(initial ? dollars(initial.target_cents) : '')
  const [date, setDate] = useState(initial?.target_date ?? '')
  const [kind, setKind] = useState<'linked' | 'manual'>(initial?.kind ?? 'linked')
  const [picked, setPicked] = useState<number[]>(ownIds)
  const cents = dollarsToCents(target)
  const [field, reason] = !name.trim() ? ['name', 'Enter a name'] as const
    : cents === null || cents <= 0 ? ['target', 'Enter a target above $0'] as const
    : [null, null] as const
  const reasonId = reason ? `gl-reason-${key}` : undefined
  // Open, savings or investment accounts that no other goal links; this goal's own accounts always stay listed.
  const linkable = accounts.filter((a) => ownIds.includes(a.id) || (LINKABLE.has(a.type) && !a.closed_at && !takenIds.has(a.id)))
  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (reason !== null || cents === null) return
    const full: GoalInput = {
      name: name.trim(), target_cents: cents, target_date: date || null, kind,
      account_ids: kind === 'linked' ? picked : [],
    }
    const changed: Partial<GoalInput> = {}
    if (initial) {
      if (full.name !== initial.name) changed.name = full.name
      if (full.target_cents !== initial.target_cents) changed.target_cents = full.target_cents
      if (full.target_date !== initial.target_date) changed.target_date = full.target_date
      if (initial.kind === 'linked' && !sameIds(picked, ownIds)) changed.account_ids = picked
      if (Object.keys(changed).length === 0) { onCancel(); return }
    }
    onSubmit(full, changed)
  }
  return (
    <form className="rc-form gl-form" onSubmit={submit}>
      <label>Name
        <input value={name} maxLength={100} autoFocus aria-describedby={field === 'name' ? reasonId : undefined} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>Target ($)
        <input inputMode="decimal" value={target} aria-invalid={target !== '' && (cents === null || cents <= 0)} aria-describedby={field === 'target' ? reasonId : undefined} onChange={(e) => setTarget(e.target.value)} />
      </label>
      <label>Target date (optional)
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      {!initial && (
        <fieldset className="gl-fieldset">
          <legend>Progress from</legend>
          <label className="gl-choice"><input type="radio" name={`gl-kind-${key}`} checked={kind === 'linked'} onChange={() => setKind('linked')} /> Linked accounts</label>
          <label className="gl-choice"><input type="radio" name={`gl-kind-${key}`} checked={kind === 'manual'} onChange={() => setKind('manual')} /> Manual contributions</label>
        </fieldset>
      )}
      {kind === 'linked' && (
        <fieldset className="gl-fieldset gl-accounts">
          <legend>Linked accounts</legend>
          {accountsStatus === 'pending' ? (
            <p className="muted" role="status">Loading accounts…</p>
          ) : accountsStatus === 'error' ? (
            <p className="error">Could not load accounts to link.</p>
          ) : linkable.length === 0 ? (
            <p className="muted">No savings or investment accounts are free to link. Add a manual savings account on the Accounts page.</p>
          ) : linkable.map((a) => (
            <label key={a.id} className="gl-choice">
              <input type="checkbox" checked={picked.includes(a.id)} onChange={() => toggle(a.id)} /> {a.name} <span className="muted">{a.institution}</span>
            </label>
          ))}
        </fieldset>
      )}
      <div className="actions-row rc-actions">
        <button type="submit" className="primary" disabled={busy || reason !== null}>{submitLabel}</button>
        <button type="button" onClick={onCancel}>Cancel</button>
        {reason && <span className="muted" id={reasonId}>{reason}</span>}
      </div>
      {error && <p className="error gl-error" role="alert">{error}</p>}
    </form>
  )
}

function ContributionForm({ busy, error, onSubmit, onCancel }: {
  busy: boolean; error: string | null
  onSubmit: (body: { date: string; amount_cents: number; note?: string }) => void; onCancel: () => void
}) {
  const [date, setDate] = useState(isoDate(new Date()))
  const [amount, setAmount] = useState('')
  const [direction, setDirection] = useState<'deposit' | 'withdrawal'>('deposit')
  const [note, setNote] = useState('')
  const today = isoDate(new Date())
  const cents = dollarsToCents(amount)
  const [field, reason] = cents === null || cents <= 0 ? ['amount', 'Enter an amount above $0'] as const
    : !date ? ['date', 'Pick a date'] as const
    : date > today ? ['date', 'The date can’t be in the future'] as const
    : [null, null] as const
  const formId = useId()
  const reasonId = reason ? `${formId}-reason` : undefined
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (reason !== null || cents === null) return
    onSubmit({ date, amount_cents: direction === 'deposit' ? cents : -cents, ...(note.trim() && { note: note.trim() }) })
  }
  return (
    <form className="rc-form" onSubmit={submit}>
      <label>Date
        <input type="date" value={date} max={today} autoFocus aria-describedby={field === 'date' ? reasonId : undefined} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label>Amount ($)
        <input inputMode="decimal" value={amount} aria-invalid={amount !== '' && (cents === null || cents <= 0)} aria-describedby={field === 'amount' ? reasonId : undefined} onChange={(e) => setAmount(e.target.value)} />
      </label>
      <label>Type
        <select value={direction} onChange={(e) => setDirection(e.target.value as 'deposit' | 'withdrawal')}>
          <option value="deposit">Deposit</option>
          <option value="withdrawal">Withdrawal</option>
        </select>
      </label>
      <label>Note (optional)
        <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="actions-row rc-actions">
        <button type="submit" className="primary" disabled={busy || reason !== null}>Add</button>
        <button type="button" onClick={onCancel}>Cancel</button>
        {reason && <span className="muted" id={reasonId}>{reason}</span>}
      </div>
      {error && <p className="error gl-error" role="alert">{error}</p>}
    </form>
  )
}

function GoalCard({ goal, accounts, accountsStatus, takenIds, onRemoved }: {
  goal: Goal; accounts: Account[]; accountsStatus: AccountsStatus; takenIds: Set<number>; onRemoved: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [contributing, setContributing] = useState(false)
  const editButton = useRef<HTMLButtonElement>(null)
  const addButton = useRef<HTMLButtonElement>(null)
  const title = useRef<HTMLHeadingElement>(null)
  // The trigger unmounts while its form is open, so focus is restored after the re-render that puts it back.
  const restoreFocus = useRef<(() => void) | null>(null)
  useEffect(() => { restoreFocus.current?.(); restoreFocus.current = null })
  const closeEdit = () => { restoreFocus.current = () => editButton.current?.focus(); setEditing(false) }
  const closeContribute = () => { restoreFocus.current = () => addButton.current?.focus(); setContributing(false) }
  // Server state only changes through these mutations; main.tsx refetches ['goals'] after any successful one.
  const update = useMutation({ mutationFn: (body: Partial<GoalInput>) => api.patchGoal(goal.id, body), onSuccess: closeEdit })
  const remove = useMutation({ mutationFn: () => api.deleteGoal(goal.id), onSuccess: onRemoved })
  const add = useMutation({ mutationFn: (body: { date: string; amount_cents: number; note?: string }) => api.addContribution(goal.id, body), onSuccess: closeContribute })
  const removeContribution = useMutation({
    mutationFn: (cid: number) => api.deleteContribution(goal.id, cid),
    // The removed row's button is gone; with the Add form open there is no Add button either, so fall back to the heading.
    onSuccess: () => (addButton.current ?? title.current)?.focus(),
  })
  const del = () => { if (window.confirm(`Delete goal ${goal.name}?`)) remove.mutate() }

  const headingId = `gl-${goal.id}`
  const amounts = `${formatCents(goal.current_cents)} of ${formatCents(goal.target_cents)}`
  const summary = `${amounts}, ${percent(goal)}`
  const status = statusLine(goal)
  const fill = Math.min(Math.max(goal.pct, 0), 1) * 100
  const recent = [...goal.contributions]
    .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.id - a.id))
  const linked = goal.accounts.map((a) => a.name).join(', ')
  const investmentIds = new Set(accounts.filter((a) => a.type === 'investment').map((a) => a.id))
  const hasInvestment = goal.accounts.some((a) => investmentIds.has(a.id))

  return (
    <section className="card gl-card" aria-labelledby={headingId}>
      <div className="card-head">
        <h2 className="gl-title" id={headingId} ref={title} tabIndex={-1}>
          {goal.name}
          {goal.target_date && <span className="muted"> by {formatDate(goal.target_date)}</span>}
        </h2>
        {!editing && (
          <span className="rc-buttons">
            <button type="button" className="icon-button" ref={editButton} aria-label={`Edit ${goal.name}`} onClick={() => { update.reset(); setEditing(true) }}>Edit</button>
            <button type="button" className="icon-button" aria-label={`Delete ${goal.name}`} disabled={remove.isPending} onClick={del}>Delete</button>
          </span>
        )}
      </div>
      {remove.error && <p className="error" role="alert">{remove.error.message}</p>}

      {editing ? (
        <GoalForm
          initial={goal} accounts={accounts} accountsStatus={accountsStatus} takenIds={takenIds} busy={update.isPending} error={update.error?.message ?? null}
          submitLabel="Save" onSubmit={(_, changed) => update.mutate(changed)} onCancel={closeEdit}
        />
      ) : (
        <>
          <div className="meter" role="img" aria-label={summary} title={summary} style={{ '--b': 'var(--accent)' } as CSSProperties}>
            <span className="trk" aria-hidden="true"><span style={{ width: `${fill}%` }} /></span>
          </div>
          <p className="gl-amounts">{amounts} · {percent(goal)}</p>
          <p className="gl-status">{status.text}{status.behind && <span className="error">Behind</span>}</p>
          {goal.kind === 'linked' && <p className="muted gl-linked">{goal.accounts.length ? `Linked: ${linked}` : 'No accounts linked'}</p>}
          {goal.kind === 'linked' && hasInvestment && <p className="muted gl-linked">Includes market gains and losses</p>}

          {goal.kind === 'manual' && (
            <div className="gl-contrib">
              {contributing ? (
                <ContributionForm busy={add.isPending} error={add.error?.message ?? null} onSubmit={(body) => add.mutate(body)} onCancel={closeContribute} />
              ) : (
                <div className="actions-row">
                  <button type="button" ref={addButton} onClick={() => { add.reset(); setContributing(true) }}>Add contribution</button>
                </div>
              )}
              {removeContribution.error && <p className="error" role="alert">{removeContribution.error.message}</p>}
              {recent.length > 0 && (
                <ul className="rc-list gl-contribs" aria-label={`Contributions to ${goal.name}`}>
                  {recent.slice(0, SHOWN_CONTRIBUTIONS).map((c) => (
                    <li key={c.id} className="gl-contrib-row">
                      <span className="rc-date">{formatDate(c.date)}</span>
                      <span className="recent-main"><span className="recent-merchant">{c.note ?? ''}</span></span>
                      <span className={`amount${c.amount_cents > 0 ? ' pos' : ''}`}>{formatCents(c.amount_cents)}</span>
                      <button type="button" className="icon-button" aria-label={`Remove ${formatCents(c.amount_cents)} contribution on ${formatDate(c.date)}`}
                        disabled={removeContribution.isPending} onClick={() => removeContribution.mutate(c.id)}>Remove</button>
                    </li>
                  ))}
                </ul>
              )}
              {recent.length > SHOWN_CONTRIBUTIONS && <p className="muted gl-more">Showing the newest {SHOWN_CONTRIBUTIONS} of {recent.length}</p>}
            </div>
          )}
        </>
      )}
    </section>
  )
}

export default function Goals() {
  const goals = useQuery({ queryKey: ['goals'], queryFn: api.goals })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const [adding, setAdding] = useState(false)
  const newButton = useRef<HTMLButtonElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const restoreFocus = useRef<(() => void) | null>(null)
  useEffect(() => { restoreFocus.current?.(); restoreFocus.current = null })
  // Bumped whenever the form opens or closes, so a slow create can't close a form the user reopened meanwhile.
  const session = useRef(0)
  const closeAdd = () => { session.current++; restoreFocus.current = () => newButton.current?.focus(); setAdding(false) }
  const create = useMutation({ mutationFn: api.createGoal })

  const list = goals.data ?? []
  const acct = accounts.data ?? []
  const takenBy = (except: number | null) => new Set(list.filter((g) => g.id !== except).flatMap((g) => g.accounts.map((a) => a.id)))

  return (
    <>
      <header className="page-head">
        <h1 ref={heading} tabIndex={-1}>Goals</h1>
        {!adding && <button type="button" ref={newButton} onClick={() => { create.reset(); session.current++; setAdding(true) }}>New goal</button>}
      </header>
      {goals.isPending && <p className="muted" role="status">Loading…</p>}
      {goals.isError && <p className="error" role="alert">{goals.error.message}</p>}
      {accounts.isError && <p className="error" role="alert">Could not load accounts to link: {accounts.error.message}</p>}

      {adding && (
        <section className="card" aria-label="New goal">
          <h2 className="card-title">New goal</h2>
          <GoalForm
            accounts={acct} accountsStatus={accounts.status} takenIds={takenBy(null)} busy={create.isPending} error={create.error?.message ?? null}
            submitLabel="Create"
            onSubmit={(full) => { const s = session.current; create.mutate(full, { onSuccess: () => { if (session.current === s) closeAdd() } }) }}
            onCancel={closeAdd}
          />
        </section>
      )}

      {goals.data && list.length === 0 && !adding && <p className="muted">No goals yet. Create one to track savings toward something.</p>}
      {list.map((g) => (
        <GoalCard key={g.id} goal={g} accounts={acct} accountsStatus={accounts.status} takenIds={takenBy(g.id)} onRemoved={() => heading.current?.focus()} />
      ))}
    </>
  )
}
