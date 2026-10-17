import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useRef, useState, type FormEvent } from 'react'
import { ACCOUNT_TYPES, api, type Account, type AccountPatch, type AccountType } from '../api'
import Menu from '../components/Menu'
import { dollarsToCents, formatCents, formatDate, formatDateTime, isoDate } from '../format'

const GROUP_LABELS: Partial<Record<AccountType, string>> = { credit: 'Credit cards', investment: 'Investments', loan: 'Loans' }
const isLiability = (type: AccountType) => type === 'credit' || type === 'loan'

/** Add-manual-account form (with name and type) or, with `fixedType`, the update-balance row form. Liabilities are entered as an "Amount owed" and sent negated; a negative amount owed is a credit (an overpaid card). */
function BalanceForm({ fixedType, busy, error, submitLabel, onSubmit, onCancel }: {
  fixedType?: AccountType; busy: boolean; error: string | null; submitLabel: string
  onSubmit: (v: { name: string; type: AccountType; balance_cents: number; as_of: string }) => void; onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [pickedType, setPickedType] = useState<AccountType>('checking')
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(isoDate(new Date()))
  const type = fixedType ?? pickedType
  const owed = isLiability(type)
  const today = isoDate(new Date())
  const cents = dollarsToCents(amount)
  const amountBad = cents === null
  const [field, reason] = !fixedType && !name.trim() ? ['name', 'Enter a name'] as const
    : amountBad ? ['amount', owed ? 'Enter the amount owed' : 'Enter a balance'] as const
    : !date ? ['date', 'Pick a date'] as const
    : date > today ? ['date', 'The date can’t be in the future'] as const
    : [null, null] as const
  const formId = useId()
  const reasonId = reason ? `${formId}-reason` : undefined
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (reason !== null || cents === null) return
    onSubmit({ name: name.trim(), type, balance_cents: owed && cents !== 0 ? -cents : cents, as_of: date })
  }
  return (
    <form className="rc-form" onSubmit={submit}>
      {!fixedType && (
        <>
          <label>Name
            <input value={name} autoFocus aria-describedby={field === 'name' ? reasonId : undefined} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>Type
            <select value={pickedType} onChange={(e) => setPickedType(e.target.value as AccountType)}>
              {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
        </>
      )}
      <label>{owed ? 'Amount owed ($)' : 'Balance ($)'}
        <input inputMode="decimal" value={amount} autoFocus={!!fixedType} aria-invalid={amount !== '' && amountBad} aria-describedby={field === 'amount' ? reasonId : undefined} onChange={(e) => setAmount(e.target.value)} />
      </label>
      <label>As of
        <input type="date" value={date} max={today} aria-describedby={field === 'date' ? reasonId : undefined} onChange={(e) => setDate(e.target.value)} />
      </label>
      <div className="actions-row rc-actions">
        <button type="submit" className="primary" disabled={busy || reason !== null}>{submitLabel}</button>
        <button type="button" onClick={onCancel}>Cancel</button>
        {reason && <span className="muted" id={reasonId}>{reason}</span>}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  )
}

export default function Accounts() {
  const qc = useQueryClient()
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const overview = useQuery({ queryKey: ['overview'], queryFn: () => api.overview() })
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: AccountPatch }) => api.patchAccount(id, body),
    // Hiding or closing changes which transactions are listed, so refetch everything, not just accounts.
    onSuccess: () => qc.invalidateQueries(),
  })
  const sync = useMutation({ mutationFn: api.sync, onSuccess: () => qc.invalidateQueries() })
  const [adding, setAdding] = useState(false)
  const addButton = useRef<HTMLButtonElement>(null)
  // Bumped when the form opens or closes, so a slow create can't close a form the user reopened meanwhile.
  const addSession = useRef(0)
  const create = useMutation({ mutationFn: api.createManualAccount, onSuccess: () => qc.invalidateQueries() })
  const closeAdd = () => { addSession.current++; setAdding(false); addButton.current?.focus() }
  const toggleAdd = () => { if (adding) { closeAdd(); return } create.reset(); addSession.current++; setAdding(true) }
  const onPatch = (id: number, body: AccountPatch) => patch.mutate({ id, body })
  const busyId = patch.isPending ? patch.variables?.id : undefined

  if (accounts.isLoading) return <p className="muted" role="status">Loading…</p>
  if (accounts.error) return <p className="error" role="alert">{accounts.error.message}</p>
  const all = accounts.data ?? []
  const visible = all.filter((a) => !a.is_hidden)
  const hidden = all.filter((a) => a.is_hidden)

  return (
    <>
      <header className="page-head">
        <h1 id="accounts-title" tabIndex={-1}>Accounts</h1>
        <div className="actions">
          {sync.data && <span className={`pill ${sync.data.status}`} role="status">{sync.data.status} · {sync.data.txns_added} new</span>}
          {sync.data?.error && <span className="error" role="alert">{sync.data.error}</span>}
          {sync.error && <span className="error" role="alert">{sync.error.message}</span>}
          <button type="button" ref={addButton} aria-expanded={adding} onClick={toggleAdd}>Add manual account</button>
          <button className="primary" onClick={() => sync.mutate()} disabled={sync.isPending}>{sync.isPending ? 'Syncing…' : 'Sync now'}</button>
        </div>
      </header>
      {overview.data && (
        <p className="networth">
          <span className="tile-label">Net worth</span>
          <span className="networth-value">{formatCents(overview.data.net_worth_cents)}</span>
        </p>
      )}
      {adding && (
        <section className="card acct-add" aria-label="Add manual account">
          <h2 className="card-title">Add manual account</h2>
          <BalanceForm
            busy={create.isPending} error={create.error?.message ?? null} submitLabel="Add"
            onSubmit={(v) => { const session = addSession.current; create.mutate(v, { onSuccess: () => { if (addSession.current === session) closeAdd() } }) }}
            onCancel={closeAdd}
          />
        </section>
      )}
      {patch.error && <p className="error" role="alert">{patch.error.message}</p>}
      {all.length === 0 && <p className="muted">No accounts yet. Run a sync to pull them from SimpleFIN, or add a manual account.</p>}
      {ACCOUNT_TYPES.map((type) => {
        const group = visible.filter((a) => a.type === type)
        return group.length ? <AccountGroup key={type} title={GROUP_LABELS[type] ?? type[0].toUpperCase() + type.slice(1)} accounts={group} busyId={busyId} onPatch={onPatch} /> : null
      })}
      {hidden.length > 0 && (
        <details className="hidden-accounts">
          <summary className="muted">Hidden accounts ({hidden.length})</summary>
          <AccountGroup title="Hidden" showTotal={false} accounts={hidden} busyId={busyId} onPatch={onPatch} />
        </details>
      )}
    </>
  )
}

function AccountGroup({ title, accounts, busyId, onPatch, showTotal = true }: { title: string; accounts: Account[]; showTotal?: boolean; busyId: number | undefined; onPatch: (id: number, body: AccountPatch) => void }) {
  const total = accounts.filter((a) => !a.closed_at).reduce((sum, a) => sum + (a.balance_cents ?? 0), 0)
  return (
    <section className="card acct-group" aria-label={title}>
      <header className="acct-head">
        <h2 className="card-title">{title}</h2>
        {showTotal && <span className="acct-total">{formatCents(total)}</span>}
      </header>
      <ul className="acct-list">
        {accounts.map((a) => <AccountRow key={a.id} account={a} busy={busyId === a.id} onPatch={onPatch} />)}
      </ul>
    </section>
  )
}

function AccountRow({ account: a, busy, onPatch }: { account: Account; busy: boolean; onPatch: (id: number, body: AccountPatch) => void }) {
  const qc = useQueryClient()
  const row = useRef<HTMLLIElement>(null)
  const [updating, setUpdating] = useState(false)
  const closeUpdate = () => { setUpdating(false); row.current?.querySelector<HTMLButtonElement>('.menu > button')?.focus() }
  // Balances feed Overview, Spending and Goals, so refetch everything.
  const setBalance = useMutation({
    mutationFn: (body: { balance_cents: number; as_of: string }) => api.updateBalance(a.id, body),
    onSuccess: () => { qc.invalidateQueries(); closeUpdate() },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteAccount(a.id),
    // The row unmounts, so park focus on the page heading.
    onSuccess: () => { qc.invalidateQueries(); document.getElementById('accounts-title')?.focus() },
  })
  const del = () => { if (window.confirm(`Delete ${a.name}? Its balance history goes too. It will be unlinked from any goals.`)) remove.mutate() }
  const rename = () => {
    const name = window.prompt('Account name', a.name)?.trim()
    if (name && name !== a.name) onPatch(a.id, { name })
  }
  const changeType = () => {
    const answer = window.prompt(`Account type (${ACCOUNT_TYPES.join(', ')})`, a.type)?.trim().toLowerCase()
    if (!answer || answer === a.type) return
    if (!(ACCOUNT_TYPES as string[]).includes(answer)) { window.alert(`Unknown type "${answer}". Use one of: ${ACCOUNT_TYPES.join(', ')}.`); return }
    onPatch(a.id, { type: answer as AccountType })
  }
  const synced = a.last_synced_at ? `Synced ${formatDateTime(a.last_synced_at)}` : 'Never synced'
  return (
    <li className="acct-row" ref={row} aria-busy={busy || remove.isPending || undefined}>
      <div className="acct-main">
        <span className="acct-name">{a.name}</span>
        <span className="tx-sub">{a.institution}{a.closed_at ? ` · closed ${a.closed_at}` : ''}</span>
      </div>
      {a.is_manual ? (
        <div className="acct-status muted">
          <span className="acct-status-text">{a.balance_date ? `Manual · updated ${formatDate(a.balance_date)}` : 'Manual'}</span>
        </div>
      ) : (
        <div className="acct-status muted" title={a.last_error ?? undefined}>
          <span className={`status-dot ${a.last_error ? 'stale' : a.last_synced_at ? 'ok' : ''}`} aria-hidden="true" />
          <span className="acct-status-text">{a.last_error ? `${synced} · ${a.last_error}` : synced}</span>
        </div>
      )}
      <div className="amount acct-balance">{a.balance_cents === null ? '—' : formatCents(a.balance_cents)}</div>
      <Menu label={`Actions for ${a.name}`} items={[
        ...(a.is_manual ? [{ label: 'Update balance…', onSelect: () => { setBalance.reset(); remove.reset(); setUpdating(true) }, disabled: busy }] : []),
        { label: 'Rename', onSelect: rename, disabled: busy },
        { label: 'Change type…', onSelect: changeType, disabled: busy },
        { label: a.is_hidden ? 'Unhide' : 'Hide', onSelect: () => onPatch(a.id, { is_hidden: !a.is_hidden }), disabled: busy },
        { label: a.closed_at ? 'Reopen' : 'Close', onSelect: () => onPatch(a.id, { closed_at: a.closed_at ? null : isoDate(new Date()) }), disabled: busy, danger: !a.closed_at },
        ...(a.is_manual ? [{ label: 'Delete…', onSelect: del, disabled: busy || remove.isPending, danger: true }] : []),
      ]} />
      {remove.error && <p className="error acct-edit" role="alert">{remove.error.message}</p>}
      {updating && (
        <div className="acct-edit">
          <BalanceForm
            fixedType={a.type} busy={setBalance.isPending} error={setBalance.error?.message ?? null} submitLabel="Save"
            onSubmit={({ balance_cents, as_of }) => setBalance.mutate({ balance_cents, as_of })} onCancel={closeUpdate}
          />
        </div>
      )}
    </li>
  )
}
