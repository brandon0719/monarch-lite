import { useEffect, useRef } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type Alert } from '../api'

const SOURCE_NAMES: Record<string, string> = {
  sync: 'sync status',
  recurring: 'recurring charges',
  tax: 'tax estimate',
  allocation: 'allocation',
}

function AlertRow({ alert, onDismiss, onFailed, buttonRef }: {
  alert: Alert; onDismiss: () => void; onFailed: () => void; buttonRef: (el: HTMLButtonElement | null) => void
}) {
  // aria-disabled, not disabled: a disabled button would drop keyboard focus to <body> for the whole request.
  // main.tsx refetches ['alerts'] after any successful mutation, which drops the row.
  const dismiss = useMutation({ mutationFn: () => api.dismissAlert(alert.key), onError: onFailed })
  return (
    <li className="ov-alert-row">
      <p className="ov-alert-title">
        <span className={`ov-alert-sev ${alert.severity}`}>{alert.severity === 'warn' ? 'Warning' : 'Info'}</span>
        {alert.title}
      </p>
      <p className="muted ov-alert-detail">{alert.detail}</p>
      <div className="ov-alert-actions">
        <Link className="tile-link" to={alert.link} aria-label={`View: ${alert.title}`}>View →</Link>
        <button type="button" className="icon-button" ref={buttonRef} aria-label={`${dismiss.isPending ? 'Dismissing' : 'Dismiss'}: ${alert.title}`}
          aria-disabled={dismiss.isPending || undefined}
          onClick={() => { if (dismiss.isPending) return; onDismiss(); dismiss.mutate() }}>{dismiss.isPending ? 'Dismissing…' : 'Dismiss'}</button>
      </div>
      {dismiss.error && <p className="error ov-alert-detail" role="alert">{dismiss.error.message}</p>}
    </li>
  )
}

export default function AlertsCard() {
  const alerts = useQuery({ queryKey: ['alerts'], queryFn: api.alerts })
  const heading = useRef<HTMLHeadingElement>(null)
  const buttons = useRef(new Map<string, HTMLButtonElement>())
  // The dismissed row, and the neighbour whose button takes focus once the refetch removes it.
  const pending = useRef<{ gone: string; next: string | null } | null>(null)
  const rows = alerts.data?.alerts

  useEffect(() => {
    const p = pending.current
    if (!p || !rows || rows.some((a) => a.key === p.gone)) return
    pending.current = null
    // The dismissed row's button is gone, so focus is on <body>; if the user moved on meanwhile, leave it.
    if (document.activeElement && document.activeElement !== document.body) return
    const next = p.next ? buttons.current.get(p.next) : undefined
    if (next) next.focus()
    else heading.current?.focus()
  }, [rows])

  const dismissing = (index: number) => {
    const neighbour = rows?.[index + 1] ?? rows?.[index - 1]
    pending.current = { gone: rows![index]!.key, next: neighbour?.key ?? null }
  }

  return (
    <section className="card" aria-labelledby="ov-alerts">
      <h2 className="card-title" id="ov-alerts" ref={heading} tabIndex={-1}>Alerts</h2>
      {alerts.isPending && <p className="muted" role="status">Loading…</p>}
      {alerts.isError && <p className="error" role="alert">{alerts.error.message}</p>}
      {alerts.data && (
        <>
          {alerts.data.alerts.length === 0 ? <p className="muted">No open alerts.</p> : (
            <ul className="ov-alert-list">
              {alerts.data.alerts.map((a, i) => (
                <AlertRow key={a.key} alert={a} onDismiss={() => dismissing(i)} onFailed={() => { pending.current = null }}
                  buttonRef={(el) => { if (el) buttons.current.set(a.key, el); else buttons.current.delete(a.key) }} />
              ))}
            </ul>
          )}
          {alerts.data.unavailable.length > 0 && (
            <p className="muted ov-alert-unavailable">
              Some checks couldn't run: {alerts.data.unavailable.map((s) => SOURCE_NAMES[s] ?? s).join(', ')}.
            </p>
          )}
        </>
      )}
    </section>
  )
}
