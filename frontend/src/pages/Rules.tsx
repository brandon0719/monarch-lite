import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useState, type ReactNode } from 'react'
import { api, type Account, type Category, type Rule, type RuleInput } from '../api'
import CategoryChip from '../components/CategoryChip'
import Menu from '../components/Menu'
import { dollarsToCents, formatCents } from '../format'

const EMPTY: RuleInput = {
  contains_text: '', account_id: null, amount_min_cents: null, amount_max_cents: null,
  set_category_id: null, set_merchant: null, add_tag_name: null,
}

type Editing = Rule | 'new' | null

export default function Rules() {
  const qc = useQueryClient()
  const rules = useQuery({ queryKey: ['rules'], queryFn: api.rules })
  const categories = useQuery({ queryKey: ['categories'], queryFn: api.categories })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const [editing, setEditing] = useState<Editing>(null)
  const [query, setQuery] = useState('')
  // One slot for the latest action error, cleared when any action starts, so an old failure never lingers next to a newer success.
  const [actionError, setActionError] = useState<string | null>(null)
  const track = { onMutate: () => setActionError(null), onError: (e: Error) => setActionError(e.message) }
  const invalidate = () => qc.invalidateQueries({ queryKey: ['rules'] })

  const remove = useMutation({
    ...track,
    mutationFn: api.deleteRule,
    // A failed delete may mean the list is stale (already gone); refetch either way.
    onSettled: invalidate,
    // Close the form only if it is still the deleted rule's.
    onSuccess: (_, id) => {
      apply.reset()
      setEditing((cur) => (cur !== null && cur !== 'new' && cur.id === id ? null : cur))
    },
  })
  const reorder = useMutation({ ...track, mutationFn: api.reorderRules, onSuccess: () => apply.reset(), onSettled: invalidate })
  // Dry run first, then confirm, then apply. The returned message is only set once something has actually happened.
  const apply = useMutation({
    ...track,
    mutationFn: async (): Promise<string | null> => {
      const { changed } = await api.applyRules(true)
      if (changed === 0) return 'Every transaction already matches the current rules.'
      const ok = window.confirm(
        `Update ${changed} transaction${changed === 1 ? '' : 's'} to match the current rules? ` +
        'This covers every account, including hidden and closed ones. Categories and merchants you set by hand are never changed.',
      )
      if (!ok) return null
      const done = (await api.applyRules(false)).changed
      return `Updated ${done} transaction${done === 1 ? '' : 's'}.`
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['transactions'] }),
  })

  const list = rules.data ?? []
  // The form's selects are uncontrolled; rendering it before these load would save "Any"/"—" over the rule's real values.
  const formReady = categories.data !== undefined && accounts.data !== undefined
  const category = (id: number) => categories.data?.find((c) => c.id === id)
  const categoryName = (id: number) => (categories.data ? category(id)?.name ?? '(deleted)' : '…')
  const accountName = (id: number) => (accounts.data ? accounts.data.find((a) => a.id === id)?.name ?? '(unknown)' : '…')
  const reordering = reorder.isPending || remove.isPending
  const deletingId = remove.isPending ? remove.variables : undefined

  // Keep each rule's position in the full list: the numbers and the reorder both refer to it, not to the filtered view.
  const needle = query.trim().toLowerCase()
  const shown = list
    .map((rule, pos) => ({ rule, pos }))
    .filter(({ rule: r }) => !needle || [
      r.contains_text,
      r.set_category_id !== null ? categoryName(r.set_category_id) : '',
      r.set_merchant ?? '',
      r.add_tag_name ?? '',
    ].some((t) => t.toLowerCase().includes(needle)))
  const filtered = needle !== ''

  // The API reorders by the FULL id list, so moving inside a filtered view would be ambiguous: it is disabled then.
  function move(index: number, delta: -1 | 1) {
    const ids = list.map((r) => r.id)
    const j = index + delta
    ;[ids[index], ids[j]] = [ids[j], ids[index]]
    reorder.mutate(ids)
  }

  return (
    <>
      <header className="page-head">
        <h1>Rules</h1>
        <div className="actions">
          <button onClick={() => apply.mutate()} disabled={apply.isPending}>{apply.isPending ? 'Applying…' : 'Apply to existing'}</button>
          <button className="primary" disabled={!formReady} onClick={() => setEditing('new')}>Add rule</button>
        </div>
      </header>
      <p className="muted lede">
        Checked top to bottom on every new transaction. The first matching category or rename wins; tags from every match are added.
        New rules are added at the top. Categories and merchants you set by hand are never changed.
      </p>
      {apply.data ? <p className="muted" role="status">{apply.data}</p> : null}
      {(rules.error ?? categories.error ?? accounts.error ?? (actionError ? new Error(actionError) : null)) && (
        <p className="error" role="alert">{(rules.error ?? categories.error ?? accounts.error)?.message ?? actionError}</p>
      )}
      {editing && formReady && (
        <RuleForm
          key={editing === 'new' ? 'new' : editing.id}
          initial={editing === 'new' ? EMPTY : editing}
          ruleId={editing === 'new' ? null : editing.id}
          categories={categories.data}
          accounts={accounts.data}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            apply.reset()
            invalidate()
            // The user may have opened a different form while this one was saving; leave that one alone.
            setEditing((cur) => (cur === editing ? null : cur))
          }}
        />
      )}
      {rules.isLoading ? <p className="muted" role="status">Loading…</p> : list.length === 0 && !rules.error ? <p className="muted">No rules yet.</p> : (
        <>
          <div className="rule-tools">
            <input
              type="search"
              className="rule-search"
              aria-label="Search rules"
              placeholder="Search by text, category, rename or tag"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <span className="muted" aria-live="polite">
              Showing {shown.length} of {list.length}
              {filtered && ' · clear the search to reorder'}
            </span>
          </div>
          {shown.length === 0 ? <p className="muted">No rules match “{query.trim()}”.</p> : (
            <ul className="card rule-list">
              {shown.map(({ rule: r, pos }) => {
                const cat = r.set_category_id !== null ? category(r.set_category_id) : undefined
                const actions: ReactNode[] = [
                  r.set_category_id !== null && <CategoryChip key="cat" category={cat} name={categoryName(r.set_category_id)} />,
                  r.set_merchant && <span key="rename">rename to <strong>{r.set_merchant}</strong></span>,
                  r.add_tag_name && <span key="tag">tag <span className="tag">{r.add_tag_name}</span></span>,
                ].filter(Boolean)
                const conditions = [
                  r.account_id !== null && `account is ${accountName(r.account_id)}`,
                  r.amount_min_cents !== null && `amount ≥ ${formatCents(r.amount_min_cents)}`,
                  r.amount_max_cents !== null && `amount ≤ ${formatCents(r.amount_max_cents)}`,
                ].filter(Boolean).join(' · ')
                const busy = deletingId === r.id
                const moveHint = filtered ? 'Clear the search to reorder rules' : undefined
                return (
                  <li key={r.id} className="rule-row" aria-busy={busy || undefined}>
                    <span className="rule-num" aria-hidden="true">{pos + 1}</span>
                    <div className="rule-main">
                      <p className="rule-sentence">
                        If description contains <code>{r.contains_text}</code>
                        {actions.map((a, k) => <Fragment key={k}>{k === 0 ? ' → ' : ' · '}{a}</Fragment>)}
                      </p>
                      {conditions && <p className="tx-sub">{conditions}</p>}
                    </div>
                    <div className="rule-move">
                      <button type="button" className="icon-button" aria-label={`Move rule ${pos + 1} up`} title={moveHint}
                        disabled={filtered || pos === 0 || reordering} onClick={() => move(pos, -1)}>↑</button>
                      <button type="button" className="icon-button" aria-label={`Move rule ${pos + 1} down`} title={moveHint}
                        disabled={filtered || pos === list.length - 1 || reordering} onClick={() => move(pos, 1)}>↓</button>
                    </div>
                    <Menu label={`Actions for rule "${r.contains_text}"`} items={[
                      { label: 'Edit', onSelect: () => setEditing(r), disabled: !formReady || busy },
                      {
                        label: busy ? 'Deleting…' : 'Delete',
                        onSelect: () => { if (window.confirm(`Delete rule "${r.contains_text}"?`)) remove.mutate(r.id) },
                        disabled: busy,
                        danger: true,
                      },
                    ]} />
                  </li>
                )
              })}
            </ul>
          )}
        </>
      )}
    </>
  )
}

interface FormProps {
  initial: RuleInput
  ruleId: number | null
  categories: Category[]
  accounts: Account[]
  onCancel: () => void
  onSaved: () => void
}

function RuleForm({ initial, ruleId, categories, accounts, onCancel, onSaved }: FormProps) {
  const save = useMutation({
    mutationFn: (body: RuleInput) => (ruleId === null ? api.createRule(body) : api.updateRule(ruleId, body)),
    onSuccess: onSaved,
  })
  const [localError, setLocalError] = useState<string | null>(null)
  const dollars = (cents: number | null) => (cents === null ? '' : (cents / 100).toFixed(2))

  function submit(form: HTMLFormElement) {
    const f = new FormData(form)
    const s = (k: string) => String(f.get(k) ?? '').trim()
    // An unparseable amount must not silently become "no limit".
    const min = dollarsToCents(s('min'))
    const max = dollarsToCents(s('max'))
    if ((s('min') && min === null) || (s('max') && max === null)) return setLocalError('Amounts must be numbers like -25.00.')
    if (min !== null && max !== null && min > max) return setLocalError('Min amount cannot be greater than max amount.')
    setLocalError(null)
    save.mutate({
      contains_text: s('contains_text'),
      account_id: s('account_id') ? Number(s('account_id')) : null,
      amount_min_cents: min,
      amount_max_cents: max,
      set_category_id: s('category') ? Number(s('category')) : null,
      set_merchant: s('merchant') || null,
      add_tag_name: s('tag') || null,
    })
  }

  return (
    <form className="card form-grid" aria-label={ruleId === null ? 'New rule' : 'Edit rule'} onSubmit={(e) => { e.preventDefault(); submit(e.currentTarget) }}>
      <h2 className="card-title form-title">{ruleId === null ? 'New rule' : 'Edit rule'}</h2>
      <label>Description contains<input name="contains_text" required autoFocus defaultValue={initial.contains_text} /></label>
      <label>Account
        <select name="account_id" defaultValue={initial.account_id ?? ''}>
          <option value="">Any</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}{a.is_hidden ? ' (hidden)' : ''}</option>)}
        </select>
      </label>
      <label>Min amount ($, spending is negative)<input name="min" inputMode="decimal" defaultValue={dollars(initial.amount_min_cents)} /></label>
      <label>Max amount ($)<input name="max" inputMode="decimal" defaultValue={dollars(initial.amount_max_cents)} /></label>
      <label>Set category
        <select name="category" defaultValue={initial.set_category_id ?? ''}>
          <option value="">—</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      <label>Rename merchant to<input name="merchant" defaultValue={initial.set_merchant ?? ''} /></label>
      <label>Add tag<input name="tag" defaultValue={initial.add_tag_name ?? ''} /></label>
      <div className="actions-row">
        <button className="primary" type="submit" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save rule'}</button>
        <button type="button" onClick={onCancel}>Cancel</button>
      </div>
      <p className="muted form-note">A rule needs at least one action: a category, a new merchant name, or a tag.</p>
      {(localError || save.error) && <p className="error form-note" role="alert">{localError ?? save.error?.message}</p>}
    </form>
  )
}
