import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type Txn, type TxnFilters } from '../api'
import CategoryChip from '../components/CategoryChip'
import TransactionDrawer from '../components/TransactionDrawer'
import { DATE_PRESETS, dollarsToCents, formatCents, formatDayHeading, groupByDay, presetRange, type DatePreset } from '../format'

const DRILL_KEYS = ['start', 'end', 'category_id', 'uncategorized', 'merchant']

/** Drill-down links (Spending → Breakdown) carry filters in the URL; null when there are none. */
function linkedFilters(p: URLSearchParams): TxnFilters | null {
  const id = Number(p.get('category_id'))
  const f: TxnFilters = {
    start: p.get('start') ?? undefined,
    end: p.get('end') ?? undefined,
    category_id: Number.isInteger(id) && id > 0 ? id : undefined,
    uncategorized: p.get('uncategorized') === '1' || undefined,
    merchant: p.get('merchant') || undefined,
  }
  return Object.values(f).some((v) => v !== undefined) ? f : null
}

export default function Transactions() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const tab: 'all' | 'review' = params.get('tab') === 'review' ? 'review' : 'all'
  const setTab = (t: 'all' | 'review') => setParams(t === 'review' ? { tab: 'review' } : {}, { replace: true })

  const [linked] = useState(() => linkedFilters(params))
  const [preset, setPreset] = useState<DatePreset>(linked ? 'custom' : 'last90')
  const [filters, setFilters] = useState<TxnFilters>(() => linked ?? presetRange('last90'))
  const [qText, setQText] = useState('')
  const [minText, setMinText] = useState('')
  const [maxText, setMaxText] = useState('')
  const [moreOpen, setMoreOpen] = useState(false)
  const [selected, setSelected] = useState<Txn | null>(null)
  const [checked, setChecked] = useState<Set<number>>(new Set())

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const categories = useQuery({ queryKey: ['categories'], queryFn: api.categories })
  // Count within the same date range as the list, so the tab number matches what the tab shows.
  const reviewCount = useQuery({
    queryKey: ['transactions', 'review-count', filters.start, filters.end],
    queryFn: () => api.transactions({ needs_review: true, limit: 1, start: filters.start, end: filters.end }),
    placeholderData: keepPreviousData,
  })
  const active: TxnFilters = { ...filters, needs_review: tab === 'review' }
  const txns = useInfiniteQuery({
    queryKey: ['transactions', active],
    queryFn: ({ pageParam }) => api.transactions(active, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
  })
  const review = useMutation({
    mutationFn: api.markReviewed,
    onSuccess: () => { setChecked(new Set()); qc.invalidateQueries({ queryKey: ['transactions'] }) },
  })
  const rows = txns.data?.pages.flatMap((p) => p.items) ?? []
  const selectedIds = rows.filter((r) => checked.has(r.id)).map((r) => r.id)
  const categoryById = new Map(categories.data?.map((c) => [c.id, c]))

  useEffect(() => { setChecked(new Set()) }, [tab, filters])

  /** Merge into the applied filters; a no-op keeps the same object so selection is not cleared. */
  function patch(p: Partial<TxnFilters>) {
    // A real change means the user now owns the filters; drop the drill-down params so a reload doesn't re-apply a removed one.
    const changed = (Object.keys(p) as (keyof TxnFilters)[]).some((k) => filters[k] !== p[k])
    if (changed && DRILL_KEYS.some((k) => params.has(k))) setParams(tab === 'review' ? { tab: 'review' } : {}, { replace: true })
    setFilters((f) => ((Object.keys(p) as (keyof TxnFilters)[]).every((k) => f[k] === p[k]) ? f : { ...f, ...p }))
  }
  const applyQ = (v: string) => patch({ q: v.trim() || undefined })
  const applyAmounts = () => patch({ min_cents: dollarsToCents(minText) ?? undefined, max_cents: dollarsToCents(maxText) ?? undefined })

  useEffect(() => {
    const t = setTimeout(() => applyQ(qText), 300)
    return () => clearTimeout(t)
  }, [qText])

  function choosePreset(p: DatePreset) {
    setPreset(p)
    if (p !== 'custom') patch({ start: undefined, end: undefined, ...presetRange(p) })
  }

  function reset() {
    setPreset('last90')
    setQText(''); setMinText(''); setMaxText(''); setMoreOpen(false)
    setFilters(presetRange('last90'))
    setParams(tab === 'review' ? { tab: 'review' } : {}, { replace: true })
  }

  function toggle(id: number) {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const categoryValue = filters.uncategorized ? 'none' : String(filters.category_id ?? '')
  const tagName = rows.flatMap((r) => r.tags).find((t) => t.id === filters.tag_id)?.name
  const amountsSet = filters.min_cents !== undefined || filters.max_cents !== undefined
  const onEnter = (fn: () => void) => (e: React.KeyboardEvent) => { if (e.key === 'Enter') fn() }

  return (
    <section>
      <header className="page-head"><h1>Transactions</h1></header>
      <div className="pills" role="group" aria-label="Filters">
        <select className="pill" aria-label="Date range" value={preset} onChange={(e) => choosePreset(e.target.value as DatePreset)}>
          {DATE_PRESETS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        {preset === 'custom' && (
          <>
            <label className="pill-field">From
              <input className="pill" type="date" value={filters.start ?? ''} max={filters.end} onChange={(e) => patch({ start: e.target.value || undefined })} />
            </label>
            <label className="pill-field">To
              <input className="pill" type="date" value={filters.end ?? ''} min={filters.start} onChange={(e) => patch({ end: e.target.value || undefined })} />
            </label>
          </>
        )}
        <select className="pill" aria-label="Account" value={filters.account_id ?? ''} onChange={(e) => patch({ account_id: e.target.value ? Number(e.target.value) : undefined })}>
          <option value="">All accounts</option>
          {accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <select
          className="pill"
          aria-label="Category"
          value={categoryValue}
          onChange={(e) => {
            const v = e.target.value
            patch({ category_id: v && v !== 'none' ? Number(v) : undefined, uncategorized: v === 'none' ? true : undefined })
          }}
        >
          <option value="">All categories</option>
          <option value="none">Uncategorized</option>
          {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <input
          className="pill pill-search"
          type="search"
          placeholder="Search transactions"
          aria-label="Search"
          value={qText}
          onChange={(e) => setQText(e.target.value)}
          onKeyDown={onEnter(() => applyQ(qText))}
        />
        <button type="button" className={`pill${moreOpen || amountsSet ? ' active' : ''}`} aria-expanded={moreOpen} onClick={() => setMoreOpen((o) => !o)}>
          More filters
        </button>
        {filters.tag_id !== undefined && (
          <button type="button" className="pill active" aria-label={`Remove tag filter ${tagName ?? ''}`.trim()} onClick={() => patch({ tag_id: undefined })}>
            Tag: {tagName ?? 'selected'} ✕
          </button>
        )}
        {filters.merchant !== undefined && (
          <button type="button" className="pill active" aria-label={`Remove merchant filter ${filters.merchant}`} onClick={() => patch({ merchant: undefined })}>
            Merchant: {filters.merchant} ✕
          </button>
        )}
        <button type="button" className="pill" onClick={reset}>Reset</button>
      </div>
      {moreOpen && (
        <div className="pills">
          <label className="pill-field">Min $
            <input className="pill pill-amount" inputMode="decimal" placeholder="-50" aria-label="Minimum amount (spending is negative)" value={minText} onChange={(e) => setMinText(e.target.value)} onKeyDown={onEnter(applyAmounts)} onBlur={applyAmounts} />
          </label>
          <label className="pill-field">Max $
            <input className="pill pill-amount" inputMode="decimal" placeholder="0" aria-label="Maximum amount (spending is negative)" value={maxText} onChange={(e) => setMaxText(e.target.value)} onKeyDown={onEnter(applyAmounts)} onBlur={applyAmounts} />
          </label>
          <span className="muted">Spending is negative.</span>
        </div>
      )}

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'all'} className={tab === 'all' ? 'active' : ''} onClick={() => setTab('all')}>All</button>
        <button role="tab" aria-selected={tab === 'review'} className={tab === 'review' ? 'active' : ''} onClick={() => setTab('review')}>
          To review ({reviewCount.data?.total ?? '…'})
        </button>
      </div>
      {tab === 'review' && (
        <div className="toolbar">
          <button className="primary" disabled={selectedIds.length === 0 || review.isPending || txns.isPlaceholderData} onClick={() => review.mutate(selectedIds)}>
            {selectedIds.length ? `Mark ${selectedIds.length} reviewed` : 'Mark reviewed'}
          </button>
          <button disabled={txns.isPlaceholderData} onClick={() => setChecked(new Set(rows.map((r) => r.id)))}>Select all loaded</button>
        </div>
      )}
      {(txns.error || review.error) && <p className="error" role="alert">{(txns.error ?? review.error)?.message}</p>}

      <div className="tx-list" aria-busy={txns.isPlaceholderData || undefined}>
      {groupByDay(rows).map(({ day, items }) => (
        <div className="day-group" key={day}>
          <h2 className="day-heading">{formatDayHeading(day)}</h2>
          <div className="card">
            {items.map((t) => (
              <div key={t.id} className="tx-row" tabIndex={0} onClick={() => setSelected(t)} onKeyDown={(e) => { if (e.target !== e.currentTarget) return; if (e.key === 'Enter') setSelected(t) }}>
                {tab === 'review' && (
                  <input type="checkbox" aria-label={`Select ${t.merchant}`} checked={checked.has(t.id)} disabled={txns.isPlaceholderData} onClick={(e) => e.stopPropagation()} onChange={() => toggle(t.id)} />
                )}
                <div className="tx-main">
                  <strong className="tx-merchant">{t.merchant}</strong>
                  <span className="tx-sub">{t.account_name}{t.transfer_pair_id !== null && ' · ↔ transfer'}</span>
                  {t.tags.length > 0 && (
                    <span className="tx-tags">
                      {t.tags.map((tag) => (
                        <button key={tag.id} type="button" className="tag" onClick={(e) => { e.stopPropagation(); patch({ tag_id: tag.id }) }}>
                          {tag.name}
                        </button>
                      ))}
                    </span>
                  )}
                </div>
                <CategoryChip category={t.category_id !== null ? categoryById.get(t.category_id) : null} name={t.category_name} />
                <span className={`amount${t.amount_cents > 0 ? ' pos' : ''}`}>{formatCents(t.amount_cents)}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
      </div>
      {txns.isLoading && <p className="muted" role="status">Loading…</p>}
      {!txns.isLoading && rows.length === 0 && <p className="muted">No transactions match.</p>}
      <div className="toolbar" style={{ marginTop: '1rem' }}>
        {txns.hasNextPage && (
          <button onClick={() => txns.fetchNextPage()} disabled={txns.isFetchingNextPage}>
            {txns.isFetchingNextPage ? 'Loading…' : 'Load more'}
          </button>
        )}
        <span className="muted">{txns.data?.pages[0]?.total ?? 0} transactions</span>
      </div>

      {selected && categories.data && (
        <TransactionDrawer key={selected.id} txn={selected} categories={categories.data} onSaved={(t) => setSelected((prev) => (prev?.id === t.id ? t : prev))} onClose={() => setSelected(null)} />
      )}
    </section>
  )
}
