import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ACCOUNT_TYPES, api, type Account, type AccountPatch, type AccountType } from '../api'
import Menu from '../components/Menu'
import { formatCents, formatDateTime, isoDate } from '../format'

const GROUP_LABELS: Partial<Record<AccountType, string>> = { credit: 'Credit cards', investment: 'Investments', loan: 'Loans' }

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
        <h1>Accounts</h1>
        <div className="actions">
          {sync.data && <span className={`pill ${sync.data.status}`} role="status">{sync.data.status} · {sync.data.txns_added} new</span>}
          {sync.data?.error && <span className="error" role="alert">{sync.data.error}</span>}
          {sync.error && <span className="error" role="alert">{sync.error.message}</span>}
          <button className="primary" onClick={() => sync.mutate()} disabled={sync.isPending}>{sync.isPending ? 'Syncing…' : 'Sync now'}</button>
        </div>
      </header>
      {overview.data && (
        <p className="networth">
          <span className="tile-label">Net worth</span>
          <span className="networth-value">{formatCents(overview.data.net_worth_cents)}</span>
        </p>
      )}
      {patch.error && <p className="error" role="alert">{patch.error.message}</p>}
      {all.length === 0 && <p className="muted">No accounts yet. Run a sync to pull them from SimpleFIN.</p>}
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
    <li className="acct-row" aria-busy={busy || undefined}>
      <div className="acct-main">
        <span className="acct-name">{a.name}</span>
        <span className="tx-sub">{a.institution}{a.closed_at ? ` · closed ${a.closed_at}` : ''}</span>
      </div>
      <div className="acct-status muted" title={a.last_error ?? undefined}>
        <span className={`status-dot ${a.last_error ? 'stale' : a.last_synced_at ? 'ok' : ''}`} aria-hidden="true" />
        <span className="acct-status-text">{a.last_error ? `${synced} · ${a.last_error}` : synced}</span>
      </div>
      <div className="amount acct-balance">{a.balance_cents === null ? '—' : formatCents(a.balance_cents)}</div>
      <Menu label={`Actions for ${a.name}`} items={[
        { label: 'Rename', onSelect: rename, disabled: busy },
        { label: 'Change type…', onSelect: changeType, disabled: busy },
        { label: a.is_hidden ? 'Unhide' : 'Hide', onSelect: () => onPatch(a.id, { is_hidden: !a.is_hidden }), disabled: busy },
        { label: a.closed_at ? 'Reopen' : 'Close', onSelect: () => onPatch(a.id, { closed_at: a.closed_at ? null : isoDate(new Date()) }), disabled: busy, danger: !a.closed_at },
      ]} />
    </li>
  )
}
