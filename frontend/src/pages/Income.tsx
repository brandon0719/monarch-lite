import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, type CashPayment, type CashPaymentInput, type FilingStatus, type IncomeProfile, type IncomeProfileInput, type PaymentKind, type TaxConfig } from '../api'
import { dollarsToCents, formatCents, formatDate, isoDate } from '../format'

const MAX_SALARY_CENTS = 1_000_000_000
const MAX_EXTRA_CENTS = 100_000_000
const MAX_PAYMENT_CENTS = 1_000_000_000
const MIN_DAY = '2000-01-01'
const MAX_DAY = '2100-12-31'
const FILING: Record<FilingStatus, string> = { single: 'Single', married_jointly: 'Married filing jointly' }

const dollars = (cents: number) => (cents / 100).toFixed(2)
const whole = (cents: number) => formatCents(cents).replace(/\.00$/, '')
const inRange = (day: string) => day >= MIN_DAY && day <= MAX_DAY
const bpPct = (bp: number) => `${(bp / 100).toFixed(2)}%`
const shortMonth = (month: string) => new Date(`${month}-01T00:00:00`).toLocaleDateString(undefined, { month: 'short' })
const signed = (cents: number) => (cents > 0 ? `+${formatCents(cents)}` : formatCents(cents))

/** The profile in effect today, else the earliest one (all are in the future). Profiles come newest first. */
const currentProfile = (profiles: IncomeProfile[], today: string) => profiles.find((p) => p.effective_from <= today) ?? profiles[profiles.length - 1]

function ProfileForm({ initial, busy, error, onSubmit, onCancel }: {
  initial?: IncomeProfile; busy: boolean; error: string | null; onSubmit: (body: IncomeProfileInput) => void; onCancel: () => void
}) {
  const [salary, setSalary] = useState(initial ? dollars(initial.salary_cents) : '')
  const [k401, setK401] = useState(initial ? String(initial.k401_pct) : '0')
  const [filing, setFiling] = useState<FilingStatus>(initial?.filing_status ?? 'single')
  const [extra, setExtra] = useState(initial ? dollars(initial.extra_withholding_cents) : '0.00')
  const [start, setStart] = useState(initial?.employment_start ?? '')
  const [from, setFrom] = useState(isoDate(new Date()))
  // The first profile starts when employment does, until the date is edited; later ones default to today.
  const [fromEdited, setFromEdited] = useState(false)
  const fromValue = initial || fromEdited ? from : start
  const salaryCents = dollarsToCents(salary)
  const extraCents = extra.trim() === '' ? 0 : dollarsToCents(extra)
  const pct = /^\d{1,3}$/.test(k401.trim()) ? Number(k401) : null
  const [field, reason] = salaryCents === null || salaryCents <= 0 ? ['salary', 'Enter a yearly salary above $0'] as const
    : salaryCents > MAX_SALARY_CENTS ? ['salary', 'Salary can be at most $10,000,000'] as const
    : pct === null || pct > 100 ? ['k401', 'Enter a 401(k) percent from 0 to 100'] as const
    : extraCents === null || extraCents < 0 || extraCents > MAX_EXTRA_CENTS ? ['extra', 'Extra withholding must be from $0 to $1,000,000'] as const
    : !start || !inRange(start) ? ['start', 'Pick an employment start date (2000 to 2100)'] as const
    : !fromValue || !inRange(fromValue) ? ['from', 'Pick an effective-from date (2000 to 2100)'] as const
    : [null, null] as const
  const reasonId = reason ? 'inc-profile-reason' : undefined
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (reason !== null) return
    onSubmit({
      effective_from: fromValue, salary_cents: salaryCents!, k401_pct: pct!, filing_status: filing,
      extra_withholding_cents: extraCents!, employment_start: start,
    })
  }
  return (
    <form className="rc-form inc-form" onSubmit={submit}>
      <label>Salary per year ($)
        <input inputMode="decimal" value={salary} autoFocus aria-invalid={field === 'salary' && salary !== ''} aria-describedby={field === 'salary' ? reasonId : undefined} onChange={(e) => setSalary(e.target.value)} />
      </label>
      <label>401(k) (% of gross)
        <input inputMode="numeric" value={k401} aria-invalid={field === 'k401'} aria-describedby={field === 'k401' ? reasonId : undefined} onChange={(e) => setK401(e.target.value)} />
      </label>
      <label>Filing status
        <select value={filing} onChange={(e) => setFiling(e.target.value as FilingStatus)}>
          {(Object.keys(FILING) as FilingStatus[]).map((f) => <option key={f} value={f}>{FILING[f]}</option>)}
        </select>
      </label>
      <label>Extra withholding per paycheck ($)
        <input inputMode="decimal" value={extra} aria-invalid={field === 'extra'} aria-describedby={field === 'extra' ? reasonId : undefined} onChange={(e) => setExtra(e.target.value)} />
      </label>
      <label>Employment start
        <input type="date" min={MIN_DAY} max={MAX_DAY} value={start} aria-invalid={field === 'start'} aria-describedby={field === 'start' ? reasonId : undefined} onChange={(e) => setStart(e.target.value)} />
      </label>
      <label>Effective from
        <input type="date" min={MIN_DAY} max={MAX_DAY} value={fromValue} aria-invalid={field === 'from'} aria-describedby={field === 'from' ? reasonId : undefined} onChange={(e) => { setFrom(e.target.value); setFromEdited(true) }} />
      </label>
      <p className="muted inc-form-note">Saving with an effective-from date that already has an entry replaces that entry.</p>
      <div className="actions-row rc-actions">
        <button type="submit" className="primary" disabled={busy || reason !== null}>{busy ? 'Saving…' : 'Save'}</button>
        <button type="button" onClick={onCancel}>Cancel</button>
        {reason && <span className="muted" id={reasonId}>{reason}</span>}
      </div>
      {error && <p className="error inc-error" role="alert">{error}</p>}
    </form>
  )
}

function SalaryCard() {
  const today = isoDate(new Date())
  const profiles = useQuery({ queryKey: ['income', 'profiles'], queryFn: api.incomeProfiles })
  const [editing, setEditing] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const restoreFocus = useRef<(() => void) | null>(null)
  useEffect(() => { restoreFocus.current?.(); restoreFocus.current = null })
  const close = () => { restoreFocus.current = () => trigger.current?.focus(); setEditing(false) }
  // main.tsx refetches ['income'] after any successful mutation.
  const save = useMutation({ mutationFn: api.saveIncomeProfile, onSuccess: close })
  const remove = useMutation({ mutationFn: api.deleteIncomeProfile, onSuccess: () => heading.current?.focus() })
  const list = profiles.data ?? []
  const current = currentProfile(list, today)

  return (
    <section className="card" aria-labelledby="inc-salary">
      <div className="card-head">
        <h2 className="card-title" id="inc-salary" ref={heading} tabIndex={-1}>Salary</h2>
        {profiles.data && !editing && (
          <button type="button" ref={trigger} onClick={() => { save.reset(); setEditing(true) }}>{current ? 'Update salary' : 'Add salary'}</button>
        )}
      </div>
      {profiles.isPending && <p className="muted" role="status">Loading…</p>}
      {profiles.isError && <p className="error" role="alert">{profiles.error.message}</p>}
      {editing && (
        <ProfileForm initial={current} busy={save.isPending} error={save.error?.message ?? null} onSubmit={(body) => save.mutate(body)} onCancel={close} />
      )}
      {profiles.data && !current && !editing && <p className="muted">Add your salary to model your paycheck.</p>}
      {current && (
        <dl className="inc-dl">
          <div><dt>Salary per year</dt><dd>{formatCents(current.salary_cents)}</dd></div>
          <div><dt>401(k)</dt><dd>{current.k401_pct}% of gross</dd></div>
          <div><dt>Filing status</dt><dd>{FILING[current.filing_status]}</dd></div>
          <div><dt>Extra withholding</dt><dd>{formatCents(current.extra_withholding_cents)} per paycheck</dd></div>
          <div><dt>Employment start</dt><dd>{formatDate(current.employment_start)}</dd></div>
          <div><dt>Effective from</dt><dd>{formatDate(current.effective_from)}{current.effective_from > today && <span className="muted"> · not yet in effect</span>}</dd></div>
        </dl>
      )}
      {list.length > 1 && (
        <>
          <h3 className="set-sub">History</h3>
          {remove.error && <p className="error" role="alert">{remove.error.message}</p>}
          <ul className="rc-list">
            {list.map((p) => (
              <li key={p.id} className="rc-row">
                <span className="recent-main">
                  <span className="recent-merchant">{formatCents(p.salary_cents)} per year{p.id === current?.id && <span className="muted"> · current</span>}</span>
                  <span className="tx-sub">from {formatDate(p.effective_from)} · 401(k) {p.k401_pct}% · {FILING[p.filing_status]}</span>
                </span>
                <span />
                <span className="rc-buttons">
                  <button type="button" className="icon-button" aria-label={`Remove salary from ${formatDate(p.effective_from)}`} disabled={remove.isPending}
                    onClick={() => { if (window.confirm(`Remove the salary entry from ${formatDate(p.effective_from)}?`)) remove.mutate(p.id) }}>Remove</button>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

function PaycheckCard() {
  const year = new Date().getFullYear()
  const today = isoDate(new Date())
  const data = useQuery({ queryKey: ['income', 'paychecks', year], queryFn: () => api.paychecks(year) })
  const profiles = useQuery({ queryKey: ['income', 'profiles'], queryFn: api.incomeProfiles })
  const d = data.data
  const regular = (d?.paychecks ?? []).filter((p) => p.kind === 'regular')
  const next = regular.find((p) => p.date >= today) ?? regular[regular.length - 1]
  // A month whose last payday is still ahead is pending: a difference there would only say the money has not arrived.
  const lastPayday = new Map<string, string>()
  for (const p of d?.paychecks ?? []) lastPayday.set(p.date.slice(0, 7), p.date)

  return (
    <section className="card" aria-labelledby="inc-paycheck">
      <h2 className="card-title" id="inc-paycheck">Paycheck</h2>
      {data.isPending && <p className="muted" role="status">Loading…</p>}
      {data.isError && <p className="error" role="alert">{data.error.message}</p>}
      {d && profiles.isPending && d.paychecks.length === 0 && <p className="muted" role="status">Loading…</p>}
      {d && !profiles.isPending && d.paychecks.length === 0 && (
        <p className="muted">{profiles.data?.length === 0 ? 'Add your salary to model your paycheck.' : `No paychecks modeled for ${d.year}.`}</p>
      )}
      {d && d.tax_year_fallback && (
        <p className="muted" role="status">No {d.year} tax table yet. Using {d.tax_year_used} figures. Add backend/app/tax/{d.year}.yaml.</p>
      )}
      {d && d.paychecks.length > 0 && (
        <p className="muted">Modeled withholding from your salary and the {d.tax_year_used} tax table. Not tax advice or your final tax bill. Verify the figures against your pay stub.</p>
      )}
      {d && next && (
        <>
          <h3 className="set-sub inc-first">{next.date >= today ? 'Next paycheck' : 'Latest paycheck'} · {formatDate(next.date)}</h3>
          <dl className="inc-dl inc-lines">
            <div><dt>Gross</dt><dd>{formatCents(next.gross_cents)}</dd></div>
            {next.lines.map((l) => <div key={l.name}><dt>{l.name}</dt><dd>{formatCents(-l.cents)}</dd></div>)}
            <div className="inc-net"><dt>Net</dt><dd>{formatCents(next.net_cents)}</dd></div>
          </dl>
        </>
      )}
      {d && d.months.length > 0 && (
        <div className="table-wrap">
          <table className="inc-table" aria-label={`Modeled and actual pay by month, ${d.year}`}>
            <thead><tr><th>Month</th><th className="num">Modeled net</th><th className="num">Actual deposits</th><th className="num">Difference</th></tr></thead>
            <tbody>
              {d.months.map((m) => {
                const pending = (lastPayday.get(m.month) ?? '') >= today
                const diff = m.actual_cents - m.modeled_net_cents
                return (
                  <tr key={m.month}>
                    <td>{shortMonth(m.month)}</td>
                    <td className="num">{formatCents(m.modeled_net_cents)}</td>
                    <td className="num">{formatCents(m.actual_cents)}</td>
                    <td className={`num${!pending && diff > 0 ? ' pos' : !pending && diff < 0 ? ' error' : ''}`}>
                      {pending ? <span className="muted">Pending</span> : signed(diff)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {d && d.paychecks.length > 0 && (
        <p className="muted sp-note">Actual = deposits categorized Paycheck.</p>
      )}
    </section>
  )
}

function TaxEstimateCard() {
  const thisYear = new Date().getFullYear()
  const [year, setYear] = useState(thisYear)
  const est = useQuery({ queryKey: ['income', 'tax-estimate', year], queryFn: () => api.taxEstimate(year), placeholderData: (prev) => prev })
  const d = est.data
  const stale = est.isPlaceholderData
  const noTable = est.isError && est.error instanceof ApiError && est.error.status === 404  // year predates the earliest tax table
  const headline = d && (d.balance_cents < 0 ? `refund ${formatCents(-d.balance_cents)}` : d.balance_cents > 0 ? `owe ${formatCents(d.balance_cents)}` : 'about even')
  const tone = d ? (d.balance_cents < 0 ? 'pos' : d.balance_cents > 0 && d.alert ? 'error' : undefined) : undefined

  return (
    <section className="card" aria-labelledby="inc-estimate">
      <div className="card-head">
        <h2 className="card-title" id="inc-estimate">Tax estimate</h2>
        <div className="inc-years" role="group" aria-label="Tax year">
          <button type="button" className="icon-button" aria-label="Previous year" disabled={year <= 2000 || noTable} onClick={() => setYear(year - 1)}>‹</button>
          <span className="inc-year" aria-live="polite">{year}</span>
          <button type="button" className="icon-button" aria-label="Next year" disabled={year >= 2100} onClick={() => setYear(year + 1)}>›</button>
        </div>
      </div>
      {est.isPending && <p className="muted" role="status">Loading…</p>}
      {noTable && <p className="muted" role="status">No tax table for {year} or earlier.</p>}
      {est.isError && !noTable && <p className="error" role="alert">{est.error.message}</p>}
      {d && (
        <div className={stale ? 'nw-stale' : undefined}>
          {!d.has_profile ? (
            <p className="muted">Add your salary to estimate your tax.</p>
          ) : (
            <>
              <p className="inc-headline">Projected {d.year}: <strong className={tone}>{headline}</strong></p>
              <dl className="inc-dl inc-lines">
                <div><dt>Taxable income</dt><dd>{formatCents(d.taxable_cents)}</dd></div>
                <div><dt>Estimated tax</dt><dd>{formatCents(d.liability_cents)}</dd></div>
                <div><dt>Withheld from salary</dt><dd>{formatCents(d.withheld_salary_cents)}</dd></div>
                <div><dt>Withheld from sign-on and bonuses</dt><dd>{formatCents(d.withheld_supplemental_cents)}</dd></div>
                <div><dt>Withheld at vests</dt><dd>{formatCents(d.withheld_vests_cents)}</dd></div>
                <div className="inc-net"><dt>Total withheld</dt><dd>{formatCents(d.withheld_cents)}</dd></div>
                <div className="inc-after"><dt>Marginal rate</dt><dd>{d.marginal_pct}%</dd></div>
              </dl>
            </>
          )}
          {d.vests.length > 0 && (
            <div className="table-wrap">
              <table className="inc-table" aria-label={`Vests in ${d.year}`}>
                <thead><tr><th>Date</th><th>Grant</th><th className="num">Shares</th><th className="num">Value</th><th className="num">Withheld (22%)</th><th className="num">Est. shortfall</th></tr></thead>
                <tbody>
                  {d.vests.map((v, i) => (
                    <tr key={`${v.vest_date}-${v.grant_label}-${i}`}>
                      <td>{formatDate(v.vest_date)}</td>
                      <td>{v.grant_label}</td>
                      <td className="num">{v.shares.toLocaleString()}</td>
                      <td className="num">{v.value_cents === null ? '—' : formatCents(v.value_cents)}</td>
                      <td className="num">{v.withheld_cents === null ? '—' : formatCents(v.withheld_cents)}</td>
                      <td className="num">{v.shortfall_cents === null ? '—' : formatCents(v.shortfall_cents)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted sp-note">Federal income tax model only. Not tax advice; uses the {d.tax_year_used} tax table and today's stock price.</p>
          {d.tax_year_fallback && <p className="muted sp-note" role="status">Using {d.tax_year_used} figures; no {d.year} tax table yet.</p>}
          {d.missing_price && <p className="muted sp-note" role="status">Some vests have no price yet.</p>}
        </div>
      )}
    </section>
  )
}

function PaymentForm({ initial, busy, error, submitLabel, onSubmit, onCancel }: {
  initial?: CashPayment; busy: boolean; error: string | null; submitLabel: string
  onSubmit: (body: CashPaymentInput) => void; onCancel: () => void
}) {
  const key = initial?.id ?? 'new'
  const [label, setLabel] = useState(initial?.label ?? '')
  const [kind, setKind] = useState<PaymentKind>(initial?.kind ?? 'lump')
  const [amount, setAmount] = useState(initial ? dollars(initial.amount_cents) : '')
  const [paid, setPaid] = useState(initial?.paid_date ?? (initial ? '' : isoDate(new Date())))
  const [start, setStart] = useState(initial?.start_date ?? '')
  const [end, setEnd] = useState(initial?.end_date ?? '')
  const [repayStart, setRepayStart] = useState(initial?.repay_start ?? '')
  const [repayEnd, setRepayEnd] = useState(initial?.repay_end ?? '')
  const cents = dollarsToCents(amount)
  const [field, reason] = !label.trim() ? ['label', 'Enter a label'] as const
    : cents === null || cents <= 0 || cents > MAX_PAYMENT_CENTS ? ['amount', 'Enter an amount from $0.01 to $10,000,000'] as const
    : kind === 'lump' && (!paid || !inRange(paid)) ? ['paid', 'Pick the paid date (2000 to 2100)'] as const
    : kind === 'installments' && (!start || !end || !inRange(start) || !inRange(end)) ? ['start', 'Pick the start and end dates (2000 to 2100)'] as const
    : kind === 'installments' && start >= end ? ['start', 'The start must be before the end'] as const
    : (repayStart === '') !== (repayEnd === '') ? ['repay', 'Fill in both repay dates, or neither'] as const
    : repayStart !== '' && (!inRange(repayStart) || !inRange(repayEnd)) ? ['repay', 'Repay dates must be 2000 to 2100'] as const
    : repayStart !== '' && repayStart >= repayEnd ? ['repay', 'The repay start must be before its end'] as const
    : [null, null] as const
  const reasonId = reason ? `inc-pay-reason-${key}` : undefined
  const describe = (name: string) => (field === name ? reasonId : undefined)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (reason !== null || cents === null) return
    // Always send every date: the other kind's dates go as explicit nulls so a kind switch through PATCH clears them.
    const body: CashPaymentInput = {
      label: label.trim(), kind, amount_cents: cents,
      paid_date: kind === 'lump' ? paid : null,
      start_date: kind === 'installments' ? start : null,
      end_date: kind === 'installments' ? end : null,
      repay_start: repayStart || null, repay_end: repayEnd || null,
    }
    if (initial && (Object.keys(body) as (keyof CashPaymentInput)[]).every((k) => body[k] === initial[k])) { onCancel(); return }
    onSubmit(body)
  }
  return (
    <form className="rc-form inc-form" onSubmit={submit}>
      <label>Label
        <input value={label} maxLength={100} autoFocus aria-invalid={field === 'label' && label !== ''} aria-describedby={describe('label')} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label>Kind
        <select value={kind} onChange={(e) => setKind(e.target.value as PaymentKind)}>
          <option value="lump">Lump sum</option>
          <option value="installments">Installments</option>
        </select>
      </label>
      <label>{kind === 'lump' ? 'Amount ($)' : 'Total amount ($)'}
        <input inputMode="decimal" value={amount} aria-invalid={amount !== '' && field === 'amount'} aria-describedby={describe('amount')} onChange={(e) => setAmount(e.target.value)} />
      </label>
      {kind === 'lump' ? (
        <label>Paid date
          <input type="date" min={MIN_DAY} max={MAX_DAY} value={paid} aria-invalid={field === 'paid'} aria-describedby={describe('paid')} onChange={(e) => setPaid(e.target.value)} />
        </label>
      ) : (
        <>
          <label>Pay from
            <input type="date" min={MIN_DAY} max={MAX_DAY} value={start} aria-invalid={field === 'start'} aria-describedby={describe('start')} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>Pay until (not included)
            <input type="date" min={MIN_DAY} max={MAX_DAY} value={end} aria-invalid={field === 'start'} aria-describedby={describe('start')} onChange={(e) => setEnd(e.target.value)} />
          </label>
        </>
      )}
      <fieldset className="gl-fieldset inc-repay">
        <legend>Repay window (optional)</legend>
        <label>Repay from
          <input type="date" min={MIN_DAY} max={MAX_DAY} value={repayStart} aria-invalid={field === 'repay'} aria-describedby={describe('repay')} onChange={(e) => setRepayStart(e.target.value)} />
        </label>
        <label>Repay until
          <input type="date" min={MIN_DAY} max={MAX_DAY} value={repayEnd} aria-invalid={field === 'repay'} aria-describedby={describe('repay')} onChange={(e) => setRepayEnd(e.target.value)} />
        </label>
      </fieldset>
      <div className="actions-row rc-actions">
        <button type="submit" className="primary" disabled={busy || reason !== null}>{submitLabel}</button>
        <button type="button" onClick={onCancel}>Cancel</button>
        {reason && <span className="muted" id={reasonId}>{reason}</span>}
      </div>
      {error && <p className="error inc-error" role="alert">{error}</p>}
    </form>
  )
}

function schedule(p: CashPayment): string {
  const when = p.kind === 'lump' ? `Lump sum · paid ${formatDate(p.paid_date!)}` : `Installments · paydays from ${formatDate(p.start_date!)} until ${formatDate(p.end_date!)}`
  return p.repay_start && p.repay_end ? `${when} · repay ${formatDate(p.repay_start)} to ${formatDate(p.repay_end)}` : when
}

function PaymentsCard() {
  const payments = useQuery({ queryKey: ['income', 'payments'], queryFn: api.payments })
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<number | null>(null)
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
  const create = useMutation({ mutationFn: api.createPayment })
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: CashPaymentInput }) => api.patchPayment(id, body),
    onSuccess: (_, { id }) => { if (editingNow.current === id) closeEdit(id) },
  })
  // A removed row takes its buttons with it, so park focus on the card heading.
  const remove = useMutation({ mutationFn: api.deletePayment, onSuccess: () => document.getElementById('inc-payments')?.focus() })
  const rows = payments.data ?? []

  return (
    <section className="card" aria-labelledby="inc-payments">
      <div className="card-head">
        <h2 className="card-title" id="inc-payments" tabIndex={-1}>Payments</h2>
        {payments.data && !adding && <button type="button" ref={addButton} onClick={() => { create.reset(); addSession.current++; setAdding(true) }}>Add payment</button>}
      </div>
      <p className="muted set-blurb">Sign-on and other cash payments. Each is taxed as supplemental wages and shows in the month it pays out.</p>
      {payments.isPending && <p className="muted" role="status">Loading…</p>}
      {payments.isError && <p className="error" role="alert">{payments.error.message}</p>}
      {remove.error && <p className="error" role="alert">{remove.error.message}</p>}
      {adding && (
        <PaymentForm
          busy={create.isPending} error={create.error?.message ?? null} submitLabel="Add"
          onSubmit={(body) => { const session = addSession.current; create.mutate(body, { onSuccess: () => { if (addSession.current === session) closeAdd() } }) }}
          onCancel={closeAdd}
        />
      )}
      {payments.data && rows.length === 0 && !adding && <p className="muted">No payments yet. Add a sign-on bonus or other cash payment.</p>}
      {rows.length > 0 && (
        <ul className="rc-list">
          {rows.map((p) => editing === p.id ? (
            <li key={p.id}>
              <PaymentForm
                initial={p} busy={update.isPending} error={update.error?.message ?? null} submitLabel="Save"
                onSubmit={(body) => update.mutate({ id: p.id, body })} onCancel={() => closeEdit(p.id)}
              />
            </li>
          ) : (
            <li key={p.id} className="rc-row inc-pay-row">
              <span className="inc-pay-main">
                <span className="recent-merchant">{p.label}</span>
                <span className="tx-sub">{schedule(p)}</span>
              </span>
              <span className="amount">{formatCents(p.amount_cents)}</span>
              <span className="rc-buttons">
                <button type="button" className="icon-button" aria-label={`Edit ${p.label}`} ref={(el) => { if (el) editButtons.current.set(p.id, el); else editButtons.current.delete(p.id) }}
                  onClick={() => { update.reset(); setEditing(p.id) }}>Edit</button>
                <button type="button" className="icon-button" aria-label={`Remove ${p.label}`} disabled={remove.isPending}
                  onClick={() => { if (window.confirm(`Remove ${p.label}?`)) remove.mutate(p.id) }}>Remove</button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function ClawbackCard() {
  const today = isoDate(new Date())
  const claw = useQuery({ queryKey: ['income', 'clawback'], queryFn: api.clawback })
  const c = claw.data
  return (
    <section className="card" aria-labelledby="inc-clawback">
      <h2 className="card-title" id="inc-clawback">Clawback</h2>
      {claw.isPending && <p className="muted" role="status">Loading…</p>}
      {claw.isError && <p className="error" role="alert">{claw.error.message}</p>}
      {c && c.items.length === 0 && <p className="muted">No repayable payments.</p>}
      {c && c.items.length > 0 && (
        <>
          <ul className="rc-list">
            {c.items.map((i) => (
              <li key={i.payment_id} className="inc-claw-row">
                <span className="recent-merchant">{i.label}</span>
                <span className="inc-claw-text">
                  {i.zero_date <= today
                    ? <>Repay window ended {formatDate(i.zero_date)} · <strong>{formatCents(0)}</strong> owed</>
                    : <>If you left today: <strong className={i.owed_today_cents > 0 ? 'error' : undefined}>{formatCents(i.owed_today_cents)}</strong> · $0 on {formatDate(i.zero_date)}</>}
                </span>
              </li>
            ))}
          </ul>
          <p className="inc-claw-total">If you left today, you would owe <strong>{formatCents(c.total_cents)}</strong> in total.</p>
        </>
      )}
    </section>
  )
}

function Bracket({ title, rows }: { title: string; rows: [number, number][] }) {
  return (
    <table className="inc-table inc-brackets" aria-label={`${title} brackets`}>
      <thead><tr><th>{title}: income over</th><th className="num">Rate</th></tr></thead>
      <tbody>{rows.map(([lower, rate]) => <tr key={lower}><td>{whole(lower)}</td><td className="num">{rate}%</td></tr>)}</tbody>
    </table>
  )
}

function TaxFigures({ cfg }: { cfg: TaxConfig }) {
  const { federal, fica, state } = cfg
  return (
    <div className="inc-tax">
      <dl className="inc-dl">
        <div><dt>Standard deduction, single</dt><dd>{whole(federal.standard_deduction.single)}</dd></div>
        <div><dt>Standard deduction, married jointly</dt><dd>{whole(federal.standard_deduction.married_jointly)}</dd></div>
        <div><dt>Supplemental wages</dt><dd>{federal.supplemental.rate_pct}%, then {federal.supplemental.high_rate_pct}% above {whole(federal.supplemental.high_threshold)}</dd></div>
        <div><dt>Social Security</dt><dd>{bpPct(fica.social_security.rate_bp)} up to {whole(fica.social_security.wage_base)}</dd></div>
        <div><dt>Medicare</dt><dd>{bpPct(fica.medicare.rate_bp)}, plus {bpPct(fica.medicare.additional_bp)} above {whole(fica.medicare.additional_threshold)}</dd></div>
        {state.payroll.map((l) => <div key={l.name}><dt>{l.name}</dt><dd>{bpPct(l.rate_bp)}</dd></div>)}
      </dl>
      <div className="inc-bracket-grid">
        <Bracket title="Single" rows={federal.brackets.single} />
        <Bracket title="Married jointly" rows={federal.brackets.married_jointly} />
      </div>
      <p className="muted">Verify against IRS figures and your pay stub; edit backend/app/tax/{cfg.year}.yaml to change.</p>
    </div>
  )
}

function TaxCard() {
  const thisYear = new Date().getFullYear()
  const [opened, setOpened] = useState(false)
  // Show the table the paycheck model actually used, which is an earlier year when this one has no config yet.
  const used = useQuery({ queryKey: ['income', 'paychecks', thisYear], queryFn: () => api.paychecks(thisYear) })
  const year = used.data?.tax_year_used ?? thisYear
  const cfg = useQuery({ queryKey: ['income', 'tax-config', year], queryFn: () => api.taxConfig(year), enabled: opened && !used.isPending })
  return (
    <section className="card" aria-label={`${year} tax figures`}>
      <details className="nw-data inc-details" onToggle={(e) => { if (e.currentTarget.open) setOpened(true) }}>
        <summary>{year} tax figures</summary>
        {(cfg.isPending || used.isPending) && opened && <p className="muted" role="status">Loading…</p>}
        {cfg.isError && <p className="error" role="alert">{cfg.error.message}</p>}
        {cfg.data && <TaxFigures cfg={cfg.data} />}
      </details>
    </section>
  )
}

export default function Income() {
  return (
    <>
      <header className="page-head"><h1>Income</h1></header>
      <SalaryCard />
      <PaycheckCard />
      <TaxEstimateCard />
      <PaymentsCard />
      <ClawbackCard />
      <TaxCard />
    </>
  )
}
