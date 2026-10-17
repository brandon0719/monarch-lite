import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { BUCKETS, api, type Bucket, type Category, type CategoryInput } from '../api'
import Menu from '../components/Menu'
import { categoryColor } from '../colors'

export default function Categories() {
  const qc = useQueryClient()
  const categories = useQuery({ queryKey: ['categories'], queryFn: api.categories })
  const [deleting, setDeleting] = useState<Category | null>(null)
  const [adding, setAdding] = useState(false)
  // One slot for the latest action error, cleared when any action starts.
  const [actionError, setActionError] = useState<string | null>(null)
  const track = { onMutate: () => setActionError(null), onError: (e: Error) => setActionError(e.message) }
  // Category changes show up in transactions (names, buckets) and in rules (the "Then" column).
  const invalidate = () => Promise.all(['categories', 'transactions', 'rules'].map((k) => qc.invalidateQueries({ queryKey: [k] })))
  const create = useMutation({ ...track, mutationFn: api.createCategory, onSuccess: invalidate })
  const patch = useMutation({
    ...track,
    mutationFn: ({ id, body }: { id: number; body: Partial<CategoryInput> }) => api.patchCategory(id, body),
    onSuccess: invalidate,
  })
  // Delete errors are shown inside the dialog, so they are not routed through the page-level slot.
  const remove = useMutation({
    mutationFn: ({ id, replacementId }: { id: number; replacementId: number }) => api.deleteCategory(id, replacementId),
    onSuccess: (_, { id }) => {
      // Close the dialog only if it still belongs to the category that was deleted.
      setDeleting((cur) => (cur?.id === id ? null : cur))
      return invalidate()
    },
  })
  const list = categories.data ?? []
  const busyId = patch.isPending ? patch.variables?.id : remove.isPending ? remove.variables?.id : undefined

  function prompted(c: Category, key: 'name' | 'group_name', label: string) {
    const value = window.prompt(label, c[key])?.trim()
    if (value && value !== c[key]) patch.mutate({ id: c.id, body: key === 'name' ? { name: value } : { group_name: value } })
  }

  function openDelete(c: Category) {
    remove.reset()
    setDeleting(c)
  }

  return (
    <>
      <header className="page-head">
        <h1>Categories</h1>
        <div className="actions">
          <button className="primary" aria-expanded={adding} aria-controls="add-category" onClick={() => setAdding((o) => !o)}>
            {adding ? 'Close' : 'Add category'}
          </button>
        </div>
      </header>
      <p className="muted lede">
        Each category belongs to one bucket. Needs (rent included), Wants and Savings drive the 50/30/20 budget; Other counts as spending but stays out of the 50/30/20 meters (one-offs like a loan payoff); Income counts as money in;
        Excluded is left out of income and spending totals.
      </p>
      {adding && (
        <form
          id="add-category"
          className="card form-grid"
          aria-label="New category"
          onSubmit={(e) => {
            e.preventDefault()
            const form = e.currentTarget
            const f = new FormData(form)
            create.mutate(
              { name: String(f.get('name')).trim(), group_name: String(f.get('group_name')).trim(), bucket: f.get('bucket') as Bucket },
              { onSuccess: () => form.reset() },
            )
          }}
        >
          <h2 className="card-title form-title">New category</h2>
          <label>Name<input name="name" required autoFocus /></label>
          <label>Group<input name="group_name" required placeholder="e.g. Lifestyle" /></label>
          <label>Bucket
            <select name="bucket" defaultValue="wants">{BUCKETS.map((b) => <option key={b} value={b}>{b}</option>)}</select>
          </label>
          <div className="actions-row">
            <button className="primary" type="submit" disabled={create.isPending}>{create.isPending ? 'Adding…' : 'Add'}</button>
            <button type="button" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </form>
      )}
      {(categories.error || actionError) && <p className="error" role="alert">{categories.error?.message ?? actionError}</p>}
      {categories.isLoading && <p className="muted" role="status">Loading…</p>}

      {BUCKETS.map((bucket) => {
        const group = list.filter((c) => c.bucket === bucket)
        if (group.length === 0) return null
        return (
          <section key={bucket} className="card cat-card" aria-label={bucket}>
            <header className="acct-head">
              <h2 className="card-title">{bucket}</h2>
              <span className="acct-total">{group.length}</span>
            </header>
            <ul className="cat-list">
              {group.map((c) => {
                const busy = busyId === c.id
                return (
                  <li key={c.id} className="cat-row" aria-busy={busy || undefined}>
                    <span className="swatch" style={{ background: categoryColor(c) }} aria-hidden="true" />
                    <div className="cat-main">
                      <span className="cat-name">{c.name}</span>
                      <span className="tx-sub">{c.group_name}{c.locked ? ' · Used by transfer detection' : ''}</span>
                    </div>
                    <select
                      aria-label={`Bucket for ${c.name}`}
                      value={c.bucket}
                      disabled={busy}
                      onChange={(e) => patch.mutate({ id: c.id, body: { bucket: e.target.value as Bucket } })}
                    >
                      {BUCKETS.map((b) => <option key={b} value={b}>{b}</option>)}
                    </select>
                    <Menu label={`Actions for ${c.name}`} items={[
                      ...(c.locked ? [] : [{ label: 'Rename', onSelect: () => prompted(c, 'name', 'Category name'), disabled: busy }]),
                      { label: 'Regroup', onSelect: () => prompted(c, 'group_name', 'Group'), disabled: busy },
                      ...(c.locked ? [] : [{ label: 'Delete / merge…', onSelect: () => openDelete(c), disabled: busy, danger: true }]),
                    ]} />
                  </li>
                )
              })}
            </ul>
          </section>
        )
      })}

      {deleting && (
        <DeleteDialog
          key={deleting.id}
          category={deleting}
          others={list.filter((c) => c.id !== deleting.id)}
          pending={remove.isPending}
          error={remove.error?.message ?? null}
          onCancel={() => { remove.reset(); setDeleting(null) }}
          onConfirm={(replacementId) => remove.mutate({ id: deleting.id, replacementId })}
        />
      )}
    </>
  )
}

interface DeleteProps {
  category: Category
  others: Category[]
  pending: boolean
  error: string | null
  onCancel: () => void
  onConfirm: (replacementId: number) => void
}

function DeleteDialog({ category, others, pending, error, onCancel, onConfirm }: DeleteProps) {
  // No default target: a destructive merge should not run into a category the user never picked.
  const [target, setTarget] = useState<number | null>(null)
  const valid = target !== null && others.some((c) => c.id === target)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !pending) onCancel() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [pending, onCancel])
  return (
    <>
      <div className="overlay" aria-hidden="true" onClick={() => { if (!pending) onCancel() }} />
      <aside className="drawer" role="dialog" aria-label={`Delete ${category.name}`}>
        <h2 style={{ marginTop: 0 }}>Delete “{category.name}”</h2>
        <p className="muted" style={{ margin: 0 }}>Its transactions and rules move to the category you pick, then it is deleted. This cannot be undone.</p>
        <label>Move its transactions and rules to
          <select autoFocus value={valid ? target : ''} disabled={pending} onChange={(e) => setTarget(e.target.value ? Number(e.target.value) : null)}>
            <option value="">Choose a category…</option>
            {others.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        {error && <p className="error" role="alert" style={{ margin: 0 }}>{error}</p>}
        <div className="actions-row">
          <button className="primary" disabled={pending || !valid} onClick={() => valid && onConfirm(target)}>{pending ? 'Moving…' : 'Move and delete'}</button>
          <button disabled={pending} onClick={onCancel}>Cancel</button>
        </div>
      </aside>
    </>
  )
}
