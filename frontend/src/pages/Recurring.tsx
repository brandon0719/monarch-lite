import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, type Cadence, type Category, type RecurringAlert, type RecurringInput, type RecurringItem } from '../api'
import { dollarsToCents, formatCents, formatDate, isoDate } from '../format'

const CADENCES: Cadence[] = ['weekly', 'monthly', 'yearly']
const dollars = (cents: number) => (Math.abs(cents) / 100).toFixed(2)
const abs = (cents: number) => formatCents(Math.abs(cents))
const suggestionId = (merchant: string, cents: number) =>
  `rc-sug-${merchant.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${cents > 0 ? 'in' : 'out'}`

function alertText(a: RecurringAlert): string {
  return a.kind === 'price_increase'
    ? `${a.name} went up: ${abs(a.previous_cents)} → ${abs(a.latest_cents)} (${formatDate(a.date)})`
    : `New recurring charge: ${a.merchant} · ${abs(a.amount_cents)} ${a.cadence}`
}

function jumpTo(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ block: 'center' })
  el.focus()
}

function ItemForm({ initial, merchants, categories, busy, error, submitLabel, onSubmit, onCancel }: {
  initial?: RecurringItem; merchants: string[]; categories: Category[]; busy: boolean; error: string | null
  submitLabel: string; onSubmit: (full: RecurringInput, changed: Partial<RecurringInput>) => void; onCancel: () => void
}) {
  const [merchant, setMerchant] = useState(initial?.merchant ?? '')
  const [name, setName] = useState(initial?.name ?? '')
  const [kind, setKind] = useState<'bill' | 'income'>(initial && initial.amount_cents > 0 ? 'income' : 'bill')
  const [amount, setAmount] = useState(initial ? dollars(initial.amount_cents) : '')
  const [cadence, setCadence] = useState<Cadence>(initial?.cadence ?? 'monthly')
  const [date, setDate] = useState(initial?.next_due ?? isoDate(new Date()))
  const [categoryId, setCategoryId] = useState(initial?.category_id == null ? '' : String(initial.category_id))
  const [follows, setFollows] = useState(initial?.follows_paycheck ?? false)
  const key = initial?.id ?? 'new'
  const cents = dollarsToCents(amount)
  const [field, reason] = !merchant.trim() ? ['merchant', 'Enter a merchant'] as const
    : cents === null || cents <= 0 ? ['amount', 'Enter an amount above $0'] as const
    : !date ? ['date', 'Pick the next date'] as const
    : [null, null] as const
  const reasonId = reason ? `rc-reason-${key}` : undefined
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (reason !== null || cents === null) return
    const full: RecurringInput = {
      merchant: merchant.trim(), name: name.trim() || merchant.trim(),
      amount_cents: kind === 'bill' ? -cents : cents, cadence, anchor_date: date,
      category_id: categoryId ? Number(categoryId) : null, follows_paycheck: kind === 'income' && follows,
    }
    // Edit sends only what changed. The date field shows next_due, so it only counts as changed if the user moved it;
    // otherwise a month-end anchor (the 31st) would be rewritten to the clamped day.
    const changed: Partial<RecurringInput> = {}
    if (initial) {
      if (full.merchant !== initial.merchant) changed.merchant = full.merchant
      if (full.name !== initial.name) changed.name = full.name
      // Turning "follows" off keeps the amount on screen (the latest paycheck), not the stale saved fallback.
      if (full.amount_cents !== initial.amount_cents || (initial.follows_paycheck && !full.follows_paycheck)) changed.amount_cents = full.amount_cents
      if (full.cadence !== initial.cadence) changed.cadence = full.cadence
      if (date !== initial.next_due) changed.anchor_date = date
      if (full.category_id !== initial.category_id) changed.category_id = full.category_id
      if (full.follows_paycheck !== initial.follows_paycheck) changed.follows_paycheck = full.follows_paycheck
      if (Object.keys(changed).length === 0) { onCancel(); return }
    }
    onSubmit(full, changed)
  }
  return (
    <form className="rc-form" onSubmit={submit}>
      <label>Merchant
        <input list={`rc-merchants-${key}`} value={merchant} autoFocus aria-describedby={field === 'merchant' ? reasonId : undefined} onChange={(e) => setMerchant(e.target.value)} />
      </label>
      <datalist id={`rc-merchants-${key}`}>{merchants.map((m) => <option key={m} value={m} />)}</datalist>
      <label>Name
        <input value={name} placeholder={merchant || 'Same as merchant'} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>Type
        <select value={kind} onChange={(e) => setKind(e.target.value as 'bill' | 'income')}>
          <option value="bill">Bill</option>
          <option value="income">Income</option>
        </select>
      </label>
      <label>{kind === 'income' && follows ? 'Fallback amount ($)' : 'Amount ($)'}
        <input inputMode="decimal" value={amount} aria-invalid={amount !== '' && (cents === null || cents <= 0)} aria-describedby={field === 'amount' ? reasonId : undefined} onChange={(e) => setAmount(e.target.value)} />
      </label>
      <label>Repeats
        <select value={cadence} onChange={(e) => setCadence(e.target.value as Cadence)}>
          {CADENCES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
      <label>Next date
        <input type="date" value={date} aria-describedby={field === 'date' ? reasonId : undefined} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label>Category
        <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
          <option value="">None</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      {kind === 'income' && (
        <div className="rc-follow">
          <label className="gl-choice">
            <input type="checkbox" checked={follows} aria-describedby={`rc-follow-hint-${key}`} onChange={(e) => setFollows(e.target.checked)} /> Amount follows my latest paycheck
          </label>
          <p className="muted" id={`rc-follow-hint-${key}`}>
            Uses the latest deposit from this merchant, skipping bonus or sign-on months. The fallback amount is used only when there's no deposit yet and no salary on the Income page.
          </p>
        </div>
      )}
      <div className="actions-row rc-actions">
        <button type="submit" className="primary" disabled={busy || reason !== null}>{submitLabel}</button>
        <button type="button" onClick={onCancel}>Cancel</button>
        {reason && <span className="muted" id={reasonId}>{reason}</span>}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  )
}

export default function Recurring() {
  const yearAgo = isoDate(new Date(Date.now() - 365 * 86_400_000))
  const rec = useQuery({ queryKey: ['recurring'], queryFn: api.recurring })
  const up = useQuery({ queryKey: ['recurring', 'upcoming', 30], queryFn: () => api.upcoming(30) })
  const categories = useQuery({ queryKey: ['categories'], queryFn: api.categories })
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<number | null>(null)
  const formOpen = adding || editing !== null
  const recent = useQuery({ queryKey: ['transactions', 'merchants', yearAgo], queryFn: () => api.transactions({ start: yearAgo, limit: 500 }), enabled: formOpen })
  const merchants = [...new Set((recent.data?.items ?? []).map((t) => t.merchant).filter(Boolean))].sort()
  // Focus to restore once the re-render has put the trigger button back (Add and Edit buttons unmount while their form is open).
  const addButton = useRef<HTMLButtonElement>(null)
  const editButtons = useRef(new Map<number, HTMLButtonElement>())
  const editingNow = useRef(editing)
  editingNow.current = editing
  const restoreFocus = useRef<(() => void) | null>(null)
  useEffect(() => { restoreFocus.current?.(); restoreFocus.current = null })
  // Bumped whenever the add form opens or closes, so a slow create can't close a form the user reopened meanwhile.
  const addSession = useRef(0)
  const closeAdd = () => { addSession.current++; restoreFocus.current = () => addButton.current?.focus(); setAdding(false) }
  const closeEdit = (id: number) => { restoreFocus.current = () => editButtons.current.get(id)?.focus(); setEditing(null) }
  // A removed row takes its buttons with it, so park focus on the card heading.
  const focusHeading = (id: string) => document.getElementById(id)?.focus()
  // main.tsx refetches ['recurring'] (items, suggestions, alerts, upcoming) after any successful mutation.
  const create = useMutation({ mutationFn: api.createRecurring })
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<RecurringInput> }) => api.patchRecurring(id, body),
    onSuccess: (_, { id }) => { if (editingNow.current === id) closeEdit(id) },
  })
  const remove = useMutation({ mutationFn: api.deleteRecurring, onSuccess: () => focusHeading('rc-items') })
  const confirm = useMutation({ mutationFn: api.confirmSuggestion, onSuccess: () => focusHeading('rc-suggestions') })
  const dismiss = useMutation({ mutationFn: api.dismissSuggestion, onSuccess: () => focusHeading('rc-suggestions') })
  // Only the latest action's error shows: starting one action clears the other two.
  const act = (run: 'remove' | 'confirm' | 'dismiss', arg: number | string) => {
    if (run !== 'remove') remove.reset()
    if (run !== 'confirm') confirm.reset()
    if (run !== 'dismiss') dismiss.reset()
    if (run === 'remove') remove.mutate(arg as number)
    else if (run === 'confirm') confirm.mutate(arg as string)
    else dismiss.mutate(arg as string)
  }
  const cats = categories.data ?? []
  const actionError = remove.error ?? confirm.error ?? dismiss.error

  return (
    <>
      <header className="page-head"><h1>Recurring</h1></header>
      {(rec.isPending || up.isPending) && <p className="muted" role="status">Loading…</p>}
      {rec.isError && <p className="error" role="alert">{rec.error.message}</p>}
      {actionError && <p className="error" role="alert">{actionError.message}</p>}

      {rec.data && rec.data.alerts.length > 0 && (
        <section className="card" aria-labelledby="rc-alerts">
          <h2 className="card-title" id="rc-alerts">Alerts</h2>
          <ul className="rc-list">
            {rec.data.alerts.map((a) => (
              <li key={a.kind === 'price_increase' ? `p-${a.item_id}` : `n-${a.merchant}`} className="rc-alert">
                {a.kind === 'new_recurring' && rec.data.suggestions.some((s) => suggestionId(s.merchant, s.amount_cents) === suggestionId(a.merchant, a.amount_cents)) ? (
                  <button type="button" className="rc-alert-link" onClick={() => jumpTo(suggestionId(a.merchant, a.amount_cents))}>{alertText(a)}</button>
                ) : (
                  <span className={a.kind === 'price_increase' ? 'error' : undefined}>{alertText(a)}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {rec.data && (
        <section className="card" aria-labelledby="rc-suggestions">
          <h2 className="card-title" id="rc-suggestions" tabIndex={-1}>Suggestions</h2>
          {rec.data.suggestions.length === 0 ? (
            <p className="muted">No new recurring charges found.</p>
          ) : (
            <ul className="rc-list">
              {rec.data.suggestions.map((s) => (
                <li key={`${s.merchant}-${s.amount_cents > 0}`} id={suggestionId(s.merchant, s.amount_cents)} tabIndex={-1} className="rc-row">
                  <span className="recent-main">
                    <span className="recent-merchant">{s.merchant}</span>
                    <span className="tx-sub"><span className={s.amount_cents > 0 ? 'pos' : undefined}>{formatCents(s.amount_cents)}</span> · {s.amount_cents > 0 ? 'income · ' : ''}{s.cadence} · seen {s.count} times · last {formatDate(s.last_date)}</span>
                  </span>
                  <span className="rc-buttons">
                    <button type="button" className="primary" disabled={confirm.isPending} aria-label={`Confirm ${s.merchant}`} onClick={() => act('confirm', s.merchant)}>Confirm</button>
                    <button type="button" disabled={dismiss.isPending} aria-label={`Dismiss ${s.merchant}`} onClick={() => act('dismiss', s.merchant)}>Dismiss</button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="card" aria-labelledby="rc-upcoming">
        <h2 className="card-title" id="rc-upcoming">Next 30 days</h2>
        {up.isError && <p className="error" role="alert">{up.error.message}</p>}
        {up.data && (
          <>
            <p className="sp-base">
              Checking balance <strong>{up.data.start_balance_cents === null ? '—' : formatCents(up.data.start_balance_cents)}</strong>
            </p>
            {up.data.rows.length === 0 ? (
              <p className="muted">Nothing expected in the next 30 days.</p>
            ) : (
              <ul className="rc-list">
                {up.data.rows.map((r, i) => (
                  <li key={`${r.item_id}-${r.date}`} className="rc-row">
                    <span className="rc-date">{i === 0 || up.data.rows[i - 1]!.date !== r.date ? formatDate(r.date) : ''}</span>
                    <span className="recent-merchant">{i > 0 && up.data.rows[i - 1]!.date === r.date && <span className="visually-hidden">{formatDate(r.date)}: </span>}{r.name}{r.late && <span className="error"> · Late</span>}</span>
                    <span className={`amount${r.amount_cents > 0 ? ' pos' : ''}`}>{formatCents(r.amount_cents)}</span>
                    <span className="muted rc-bal">{r.balance_cents === null ? '' : `→ ${formatCents(r.balance_cents)}`}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="muted sp-note">Bills {formatCents(up.data.bills_cents)} · Income {formatCents(up.data.income_cents)}</p>
          </>
        )}
      </section>

      {rec.data && (
        <section className="card" aria-labelledby="rc-items">
          <div className="card-head">
            <h2 className="card-title" id="rc-items" tabIndex={-1}>Your recurring items</h2>
            {!adding && <button type="button" ref={addButton} onClick={() => { create.reset(); addSession.current++; setAdding(true) }}>Add recurring</button>}
          </div>
          {adding && (
            <ItemForm
              merchants={merchants} categories={cats} busy={create.isPending} error={create.error?.message ?? null}
              submitLabel="Add" onSubmit={(full) => { const session = addSession.current; create.mutate(full, { onSuccess: () => { if (addSession.current === session) closeAdd() } }) }} onCancel={closeAdd}
            />
          )}
          {rec.data.items.length === 0 && !adding ? (
            <p className="muted">No recurring items yet. Confirm a suggestion or add one.</p>
          ) : (
            <ul className="rc-list">
              {rec.data.items.map((item) => editing === item.id ? (
                <li key={item.id}>
                  <ItemForm
                    initial={item} merchants={merchants} categories={cats} busy={update.isPending} error={update.error?.message ?? null}
                    submitLabel="Save" onSubmit={(_, changed) => update.mutate({ id: item.id, body: changed })} onCancel={() => closeEdit(item.id)}
                  />
                </li>
              ) : (
                <li key={item.id} className="rc-row">
                  <span className="recent-main">
                    <span className="recent-merchant">{item.name}</span>
                    <span className="tx-sub">
                      {item.cadence}{item.follows_paycheck && ' · follows latest paycheck'} · {item.status === 'late' ? <span className="error">Late since {formatDate(item.next_due)}</span> : `next ${formatDate(item.next_due)}`}
                      {item.last_date && ` · last ${formatCents(item.last_amount_cents!)} on ${formatDate(item.last_date)}`}
                    </span>
                  </span>
                  <span className={`amount${item.amount_cents > 0 ? ' pos' : ''}`}>{formatCents(item.amount_cents)}</span>
                  <span className="rc-buttons">
                    <button type="button" className="icon-button" aria-label={`Edit ${item.name}`} ref={(el) => { if (el) editButtons.current.set(item.id, el); else editButtons.current.delete(item.id) }} onClick={() => { update.reset(); setEditing(item.id) }}>Edit</button>
                    <button type="button" className="icon-button" aria-label={`Remove ${item.name}`} disabled={remove.isPending} onClick={() => act('remove', item.id)}>Remove</button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  )
}
