export type Bucket = 'needs' | 'wants' | 'other' | 'savings' | 'income' | 'excluded'
export const BUCKETS: Bucket[] = ['needs', 'wants', 'other', 'savings', 'income', 'excluded']
export type AccountType = 'checking' | 'savings' | 'credit' | 'investment' | 'loan' | 'other'
export const ACCOUNT_TYPES: AccountType[] = ['checking', 'savings', 'credit', 'investment', 'loan', 'other']

export interface Account {
  id: number
  institution: string
  name: string
  type: AccountType
  is_hidden: boolean
  closed_at: string | null
  last_synced_at: string | null
  last_error: string | null
  balance_cents: number | null
  balance_date: string | null
}
export type AccountPatch = Partial<Pick<Account, 'name' | 'type' | 'is_hidden' | 'closed_at'>>
export interface Tag { id: number; name: string }
export interface Txn {
  id: number
  account_id: number
  account_name: string
  posted_date: string
  amount_cents: number
  raw_description: string
  merchant: string
  category_id: number | null
  category_name: string | null
  category_source: 'none' | 'rule' | 'user'
  notes: string | null
  tags: Tag[]
  reviewed_at: string | null
  transfer_pair_id: number | null
}
export interface TxnPage { items: Txn[]; next_cursor: string | null; total: number }
export interface TxnFilters {
  start?: string
  end?: string
  account_id?: number
  category_id?: number
  uncategorized?: boolean
  min_cents?: number
  max_cents?: number
  q?: string
  tag_id?: number
  merchant?: string
  needs_review?: boolean
  limit?: number
}
export interface TxnPatch { category_id?: number | null; merchant?: string; notes?: string | null; tag_names?: string[]; reviewed?: boolean }
/** `locked` categories (Transfer, Credit Card Payment) cannot be renamed or deleted (409). */
export interface Category { id: number; name: string; group_name: string; bucket: Bucket; locked: boolean }
export interface CategoryInput { name: string; group_name: string; bucket: Bucket }
export interface RuleInput {
  contains_text: string
  account_id: number | null
  amount_min_cents: number | null
  amount_max_cents: number | null
  set_category_id: number | null
  set_merchant: string | null
  add_tag_name: string | null
}
export interface Rule extends RuleInput { id: number; priority: number }
/** A sync can come back HTTP 200 with status "failed"; check `status`, not just the response. */
export interface SyncRun {
  id: number
  started_at: string
  finished_at: string | null
  status: 'running' | 'success' | 'partial' | 'failed'
  accounts_ok: number
  accounts_stale: number
  txns_added: number
  error: string | null
}

export interface SpendingRow { category_id: number | null; name: string; cents: number }
export interface Overview {
  month: string
  net_worth_cents: number
  balances: { cash: number; investments: number; credit: number; loans: number; other: number }
  spent_cents: number
  spending_by_category: SpendingRow[]
  to_review: number
  uncategorized: number
  last_synced_at: string | null
  recent: Txn[]
}

export interface BudgetSettings { take_home_cents: number | null; needs_pct: number; wants_pct: number; savings_pct: number }
export type BudgetSettingsInput = { take_home_cents: number; needs_pct: number; wants_pct: number; savings_pct: number }
export interface BudgetMonth { month: string; is_current: boolean; needs_cents: number; wants_cents: number; savings_cents: number }
export interface Budget {
  configured: boolean
  take_home_cents: number | null
  needs_pct: number; wants_pct: number; savings_pct: number
  base_cents: number | null
  targets: { needs: number; wants: number; savings: number } | null
  months: BudgetMonth[]
}
export interface CashflowMonth { month: string; income_cents: number; spent_cents: number; saved_cents: number; savings_rate: number | null }
export interface Breakdown {
  categories: { category_id: number | null; name: string; bucket: Bucket | null; cents: number }[]
  merchants: { merchant: string; cents: number; count: number }[]
  total_cents: number
}
export interface Cashflow { months: CashflowMonth[]; average_savings_rate: number | null }
export interface CategoryBudgetRow {
  category_id: number; name: string; bucket: Bucket
  budget_cents: number; spent_cents: number; remaining_cents: number; pct_used: number | null
}
export interface CategoryBudgets { month: string; rows: CategoryBudgetRow[]; unbudgeted: { spent_cents: number; categories: number } }

/** FastAPI 422s send `detail` as a list of {loc, msg, type}; show the messages. */
function describe(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (typeof d?.msg === 'string' ? d.msg.replace(/^Value error, /, '') : JSON.stringify(d)))
    if (msgs.length) return msgs.join('; ')
  }
  return detail ? JSON.stringify(detail) : fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(describe(body?.detail, `${res.status} ${res.statusText}`))
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

const send = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

function query(params: object): string {
  const p = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '' && value !== false) p.set(key, String(value))
  }
  return p.toString()
}

export const api = {
  accounts: () => request<Account[]>('/accounts'),
  patchAccount: (id: number, body: AccountPatch) => request<Account>(`/accounts/${id}`, send('PATCH', body)),
  sync: () => request<SyncRun>('/sync', send('POST')),
  syncRuns: () => request<SyncRun[]>('/sync/runs?limit=20'),
  transactions: (filters: TxnFilters, cursor?: string) => request<TxnPage>(`/transactions?${query({ ...filters, cursor })}`),
  patchTxn: (id: number, body: TxnPatch) => request<Txn>(`/transactions/${id}`, send('PATCH', body)),
  markReviewed: (ids: number[]) => request<{ updated: number }>('/transactions/review', send('POST', { ids })),
  unlinkTransfer: (id: number) => request<void>(`/transactions/${id}/transfer`, send('DELETE')),
  categories: () => request<Category[]>('/categories'),
  createCategory: (body: CategoryInput) => request<Category>('/categories', send('POST', body)),
  patchCategory: (id: number, body: Partial<CategoryInput>) => request<Category>(`/categories/${id}`, send('PATCH', body)),
  deleteCategory: (id: number, replacementId: number) => request<void>(`/categories/${id}?replacement_id=${replacementId}`, send('DELETE')),
  rules: () => request<Rule[]>('/rules'),
  createRule: (body: RuleInput) => request<Rule>('/rules', send('POST', body)),
  updateRule: (id: number, body: RuleInput) => request<Rule>(`/rules/${id}`, send('PATCH', body)),
  deleteRule: (id: number) => request<void>(`/rules/${id}`, send('DELETE')),
  reorderRules: (ids: number[]) => request<Rule[]>('/rules/reorder', send('POST', { ids })),
  applyRules: (dryRun: boolean) => request<{ changed: number }>(`/rules/apply?dry_run=${dryRun}`, send('POST')),
  overview: (month?: string) => request<Overview>(`/overview${month ? `?month=${month}` : ''}`),
  budgetSettings: () => request<BudgetSettings>('/budget/settings'),
  saveBudgetSettings: (body: BudgetSettingsInput) => request<BudgetSettings>('/budget/settings', send('PUT', body)),
  budget: (months: number) => request<Budget>(`/budget?months=${months}`),
  breakdown: (start: string, end: string) => request<Breakdown>(`/breakdown?${query({ start, end })}`),
  cashflow: (months: number) => request<Cashflow>(`/cashflow?months=${months}`),
  categoryBudgets: (month: string) => request<CategoryBudgets>(`/category-budgets?month=${month}`),
  setCategoryBudget: (categoryId: number, month: string, amount_cents: number | null) =>
    request<{ category_id: number; month: string; amount_cents: number | null }>(`/category-budgets/${categoryId}`, send('PUT', { month, amount_cents })),
  backup: () => request<{ path: string }>('/backups', send('POST')),
}
