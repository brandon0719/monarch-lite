import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { api, type Category, type CategoryBudgetRow } from '../api'
import { currentMonth, dollarsToCents, formatCents, formatPct, monthLabel, shiftMonth } from '../format'

const BUDGETABLE = new Set(['needs', 'wants', 'other'])
const dollars = (cents: number) => (cents / 100).toFixed(2)

function Row({ r, disabled, focusOnMount, onFocused, onEdit }: {
  r: CategoryBudgetRow; disabled: boolean; focusOnMount: boolean; onFocused: () => void; onEdit: () => void
}) {
  const edit = useRef<HTMLButtonElement>(null)
  // The edit form that just closed took focus with it; hand it back to this row's Edit button.
  useEffect(() => { if (focusOnMount) { edit.current?.focus(); onFocused() } }, [focusOnMount, onFocused])
  const over = r.remaining_cents < 0
  // Net refunds exceeding spending: no percentage (it would be negative), just say why the bar is empty.
  const refunds = r.spent_cents < 0
  const pct = refunds || r.pct_used === null ? null : formatPct(Math.round(r.pct_used * 100))
  const status = over ? `Over by ${formatCents(-r.remaining_cents)}` : `${formatCents(r.remaining_cents)} left`
  const summary = `${r.name}: ${formatCents(r.spent_cents)} of ${formatCents(r.budget_cents)}${pct ? `, ${pct}` : ''}${refunds ? ', refunds exceed spending' : ''}, ${status}`
  const fill = over ? 100 : Math.min(Math.max(r.pct_used ?? 0, 0), 1) * 100
  return (
    <li className={`cb-row${over ? ' over' : ''}`}>
      <div className={`meter${over ? ' over' : ''}`} role="img" aria-label={summary} title={summary} style={{ '--b': 'var(--accent)' } as CSSProperties}>
        <span className="cb-top" aria-hidden="true">
          <span className="cb-name">{r.name}</span>
          <span className={`m-val${refunds ? ' refunds' : ''}`}>{formatCents(r.spent_cents)}<span className="muted"> of {formatCents(r.budget_cents)}</span>{pct && <span className="m-pct"> · {pct}</span>}{refunds && <span className="muted"> · refunds exceed spending</span>}</span>
        </span>
        <span className="trk" aria-hidden="true"><span style={{ width: `${fill}%` }} /></span>
        <span className={over ? 'error cb-status' : 'muted cb-status'} aria-hidden="true">{status}</span>
      </div>
      <button type="button" ref={edit} className="icon-button" aria-label={`Edit ${r.name} budget`} disabled={disabled} onClick={onEdit}>Edit</button>
    </li>
  )
}

const AMOUNT_HINT = 'Enter an amount of $0 or more'

function AmountForm({ month, label, initial, busy, blocker, hintId, autoFocus = true, onSave, onRemove, onCancel }: {
  month: string; label: string; initial: number | null; busy: boolean
  /** Why Save is unavailable for a reason outside this form (e.g. no category chosen yet). */
  blocker?: string; hintId?: string; autoFocus?: boolean
  onSave: (cents: number) => void; onRemove?: () => void; onCancel: () => void
}) {
  const ownId = useId()
  const [text, setText] = useState(initial === null ? '' : dollars(initial))
  const cents = dollarsToCents(text)
  const ok = cents !== null && cents >= 0
  const hint = blocker ?? (ok ? null : AMOUNT_HINT)
  const id = hintId ?? ownId
  const submit = (e: FormEvent) => { e.preventDefault(); if (ok) onSave(cents) }
  return (
    <form className="cb-form" onSubmit={submit}>
      <label className="pill-field">{label} ($)
        <input className="pill pill-amount" inputMode="decimal" autoFocus={autoFocus} value={text} aria-invalid={text !== '' && !ok} aria-describedby={hint ? id : undefined} onChange={(e) => setText(e.target.value)} />
      </label>
      <button type="submit" className="primary" disabled={!ok || busy || !!blocker}>Save</button>
      {onRemove && <button type="button" onClick={onRemove} disabled={busy}>Remove</button>}
      <button type="button" onClick={onCancel}>Cancel</button>
      {hint && <span className="muted" id={id}>{hint}</span>}
      <span className="muted">Applies from {monthLabel(month)} onward</span>
    </form>
  )
}

function AddBudget({ month, options, busy, error, focusAdd, onFocused, onOpen, onSave }: {
  month: string; options: Category[]; busy: boolean; error: string | null
  focusAdd: boolean; onFocused: () => void; onOpen: () => void
  onSave: (id: number, cents: number) => Promise<unknown>
}) {
  const hintId = useId()
  const [open, setOpen] = useState(false)
  const [categoryId, setCategoryId] = useState('')
  const add = useRef<HTMLButtonElement>(null)
  const restore = useRef(false)
  // Closing the form unmounts the focused control; return focus to "Add budget" (also on request from the parent).
  useEffect(() => {
    if (open || !add.current || !(restore.current || focusAdd)) return
    add.current.focus()
    restore.current = false
    if (focusAdd) onFocused()
  }, [open, focusAdd, options.length, onFocused])
  if (options.length === 0) return null
  const close = () => { restore.current = true; setOpen(false); setCategoryId('') }
  if (!open) return <div className="actions-row"><button type="button" ref={add} disabled={busy} onClick={() => { onOpen(); setOpen(true) }}>Add budget</button></div>
  return (
    <div className="cb-add">
      <label className="pill-field">Category
        <select className="pill" autoFocus value={categoryId} aria-describedby={categoryId === '' ? hintId : undefined} onChange={(e) => setCategoryId(e.target.value)}>
          <option value="">Choose…</option>
          {options.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      <AmountForm
        month={month} label="Monthly budget" initial={null} busy={busy} autoFocus={false}
        blocker={categoryId === '' ? 'Choose a category' : undefined} hintId={hintId}
        onSave={(cents) => { onSave(Number(categoryId), cents).then(close, () => { /* the error shows below; keep the input */ }) }}
        onCancel={() => { onOpen(); close() }}
      />
      {error && <p className="error cb-err" role="alert">{error}</p>}
    </div>
  )
}

export default function CategoryBudgetsCard() {
  const now = currentMonth()
  const [month, setMonth] = useState(now)
  const [editing, setEditing] = useState<number | null>(null)
  const budgets = useQuery({ queryKey: ['category-budgets', month], queryFn: () => api.categoryBudgets(month), placeholderData: keepPreviousData })
  const categories = useQuery({ queryKey: ['categories'], queryFn: api.categories })
  // main.tsx refetches ['category-budgets'] after any successful mutation.
  const setBudget = ({ id, cents }: { id: number; cents: number | null }) => api.setCategoryBudget(id, month, cents)
  const save = useMutation({
    mutationFn: setBudget,
    // Saved: back to that row's Edit button. Removed: the row may be gone, so land on "Add budget".
    onSuccess: (_, { id, cents }) => { setEditing(null); latch(cents === null ? 'add' : id) },
  })
  // The add form has its own mutation so a failure stays inside the form, with the typed input intact.
  const add = useMutation({ mutationFn: setBudget })
  const [refocus, setRefocus] = useState<number | 'add' | null>(null)
  const clearFocus = useCallback(() => setRefocus(null), [])
  // A focus request gets one chance: when the refetch it waits on has settled, drop it if nothing consumed it
  // (e.g. no "Add budget" button because nothing is addable), so it can't steal focus later.
  const latchedAt = useRef(0)
  const latch = (to: number | 'add') => { latchedAt.current = budgets.dataUpdatedAt; setRefocus(to) }
  useEffect(() => {
    if (refocus !== null && !budgets.isFetching && (budgets.dataUpdatedAt !== latchedAt.current || budgets.isError)) setRefocus(null)
  }, [refocus, budgets.isFetching, budgets.isError, budgets.dataUpdatedAt])
  const prev = useRef<HTMLButtonElement>(null)
  const resetErrors = () => { save.reset(); add.reset() }
  // keepPreviousData leaves last month's rows on screen while the new month loads; don't let them be edited meanwhile.
  const stale = budgets.isPlaceholderData
  const d = budgets.data
  const budgeted = new Set(d?.rows.map((r) => r.category_id))
  const addable = (categories.data ?? []).filter((c) => BUDGETABLE.has(c.bucket) && !budgeted.has(c.id))
  const go = (delta: number) => {
    const next = shiftMonth(month, delta)
    setEditing(null); setRefocus(null); resetErrors(); setMonth(next)
    if (next >= now) prev.current?.focus() // Next is about to disable; keep focus in the switcher
  }

  return (
    <section className="card" aria-labelledby="sp-cat">
      <div className="card-head">
        <h2 className="card-title" id="sp-cat">Category budgets</h2>
        <div className="cb-switch">
          <button type="button" ref={prev} className="icon-button" aria-label="Previous month" onClick={() => go(-1)}>‹</button>
          <span aria-live="polite">{monthLabel(month)}{month === now && <span className="muted"> · so far</span>}</span>
          <button type="button" className="icon-button" aria-label="Next month" disabled={month >= now} onClick={() => go(1)}>›</button>
        </div>
      </div>
      {budgets.isPending && <p className="muted" role="status">Loading…</p>}
      {budgets.isError && <p className="error" role="alert">{budgets.error.message}</p>}
      {save.error && <p className="error" role="alert">{save.error.message}</p>}
      {d && (
        <>
          {d.rows.length === 0 ? (
            <p className={`muted${stale ? ' stale' : ''}`}>No category budgets yet.</p>
          ) : (
            <ul className={`cb-list${stale ? ' stale' : ''}`} aria-busy={stale}>
              {d.rows.map((r) => editing === r.category_id ? (
                <li key={r.category_id} className="cb-row">
                  <AmountForm
                    month={month} label={`${r.name} budget`} initial={r.budget_cents} busy={save.isPending || stale}
                    onSave={(cents) => save.mutate({ id: r.category_id, cents })}
                    onRemove={() => save.mutate({ id: r.category_id, cents: null })}
                    onCancel={() => { resetErrors(); setEditing(null); latch(r.category_id) }}
                  />
                </li>
              ) : (
                <Row
                  key={r.category_id} r={r} disabled={stale} focusOnMount={refocus === r.category_id} onFocused={clearFocus}
                  onEdit={() => { resetErrors(); setRefocus(null); setEditing(r.category_id) }}
                />
              ))}
            </ul>
          )}
          <AddBudget
            key={month} month={month} options={addable} busy={add.isPending || stale} error={add.error?.message ?? null}
            focusAdd={refocus === 'add'} onFocused={clearFocus} onOpen={() => { resetErrors(); clearFocus() }}
            onSave={(id, cents) => add.mutateAsync({ id, cents })}
          />
          {d.unbudgeted.spent_cents > 0 && (
            <p className={`muted sp-note${stale ? ' stale' : ''}`}>
              Unbudgeted: {formatCents(d.unbudgeted.spent_cents)} across {d.unbudgeted.categories} {d.unbudgeted.categories === 1 ? 'category' : 'categories'}
            </p>
          )}
        </>
      )}
    </section>
  )
}
