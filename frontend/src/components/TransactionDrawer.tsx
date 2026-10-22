import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { api, type Category, type Txn, type TxnPatch } from '../api'
import { formatCents, formatDate } from '../format'
import CategoryChip from './CategoryChip'

interface Props {
  txn: Txn
  categories: Category[]
  onSaved: (t: Txn) => void
  onClose: () => void
}

export default function TransactionDrawer({ txn, categories, onSaved, onClose }: Props) {
  const qc = useQueryClient()
  const [merchant, setMerchant] = useState(txn.merchant)
  const [notes, setNotes] = useState(txn.notes ?? '')
  const [tags, setTags] = useState(txn.tags.map((t) => t.name).join(', '))
  const [ruleCategory, setRuleCategory] = useState<number | null>(null)
  const [ruleText, setRuleText] = useState(txn.merchant.toLowerCase())
  const [closing, setClosing] = useState(false)

  // Escape and the overlay both blur first, so the focused field's save fires before the drawer unmounts.
  const dismiss = useCallback(() => {
    ;(document.activeElement as HTMLElement | null)?.blur()
    onClose()
  }, [onClose])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') dismiss() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [dismiss])

  const refresh = () => qc.invalidateQueries({ queryKey: ['transactions'] })
  const save = useMutation({ mutationFn: (body: TxnPatch) => api.patchTxn(txn.id, body), onSuccess: (t) => { onSaved(t); refresh() } })
  const unlink = useMutation({ mutationFn: () => api.unlinkTransfer(txn.id), onSuccess: () => { refresh(); onClose() } })
  const createRule = useMutation({
    mutationFn: api.createRule,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rules'] }); setRuleCategory(null) },
  })
  const tagList = tags.split(',').map((s) => s.trim()).filter(Boolean)

  const current = categories.find((c) => c.id === txn.category_id) ?? null

  return (
    <>
      <div className={`overlay${closing ? ' closing' : ''}`} aria-hidden="true" onClick={dismiss} />
      <aside className={`drawer${closing ? ' closing' : ''}`} role="dialog" aria-label={`Edit ${txn.merchant}`} onAnimationEnd={closing ? onClose : undefined}>
        <div className="drawer-head">
          <div>
            <h2 className={`drawer-amount${txn.amount_cents > 0 ? ' pos' : ''}`}>{formatCents(txn.amount_cents)}</h2>
            <CategoryChip category={current} name={txn.category_name} />
          </div>
          <button onClick={dismiss} aria-label="Close">✕</button>
        </div>
        <div className="drawer-meta">
          <span>{formatDate(txn.posted_date)} · {txn.account_name}</span>
          <span className="drawer-raw">{txn.raw_description}</span>
        </div>

        <label>Category
          <select
            value={txn.category_id ?? ''}
            onChange={(e) => {
              const id = e.target.value ? Number(e.target.value) : null
              save.mutate({ category_id: id }, { onSuccess: () => setRuleCategory(id) })
            }}
          >
            <option value="">Uncategorized</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>

        {ruleCategory !== null && (
          <div className="card">
            <label>Always use this category when the description contains
              <input value={ruleText} onChange={(e) => setRuleText(e.target.value)} />
            </label>
            <div className="toolbar" style={{ marginTop: '.5rem', marginBottom: 0 }}>
              <button
                className="primary"
                disabled={!ruleText.trim() || createRule.isPending}
                onClick={() => createRule.mutate({
                  contains_text: ruleText.trim(), account_id: null, amount_min_cents: null, amount_max_cents: null,
                  set_category_id: ruleCategory, set_merchant: null, add_tag_name: null,
                })}
              >Create rule</button>
              <button onClick={() => setRuleCategory(null)}>Not now</button>
            </div>
            {createRule.error && <p className="error">{createRule.error.message}</p>}
          </div>
        )}

        <label>Merchant
          <input
            value={merchant}
            onChange={(e) => setMerchant(e.target.value)}
            onBlur={() => {
              const m = merchant.trim()
              if (!m) setMerchant(txn.merchant)
              else if (m !== txn.merchant) save.mutate({ merchant: m })
            }}
          />
        </label>
        <label>Tags (comma-separated)
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            onBlur={() => { if (tagList.join(',') !== txn.tags.map((t) => t.name).join(',')) save.mutate({ tag_names: tagList }) }}
          />
        </label>
        <label>Notes
          <textarea
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => { if (notes !== (txn.notes ?? '')) save.mutate({ notes: notes || null }) }}
          />
        </label>

        <div className="toolbar">
          <button disabled={closing} onClick={() => save.mutate({ reviewed: !txn.reviewed_at }, { onSuccess: () => setClosing(true) })}>{txn.reviewed_at ? 'Mark unreviewed' : 'Mark reviewed'}</button>
          {txn.transfer_pair_id !== null && <button onClick={() => unlink.mutate()}>Unlink transfer</button>}
        </div>
        {txn.category_source !== 'none' && <p className="muted">Category set by {txn.category_source === 'user' ? 'you' : 'a rule'}.</p>}
        {(save.error || unlink.error) && <p className="error">{(save.error ?? unlink.error)?.message}</p>}
      </aside>
    </>
  )
}
