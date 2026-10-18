export type Bucket = 'needs' | 'wants' | 'other' | 'savings' | 'income' | 'excluded'
export const BUCKETS: Bucket[] = ['needs', 'wants', 'other', 'savings', 'income', 'excluded']
export type AccountType = 'checking' | 'savings' | 'credit' | 'investment' | 'loan' | 'other'
export const ACCOUNT_TYPES: AccountType[] = ['checking', 'savings', 'credit', 'investment', 'loan', 'other']

export interface Account {
  id: number
  institution: string
  name: string
  type: AccountType
  is_manual: boolean
  is_hidden: boolean
  closed_at: string | null
  last_synced_at: string | null
  last_error: string | null
  balance_cents: number | null
  balance_date: string | null
}
export interface ManualAccountInput { name: string; type: AccountType; balance_cents: number; as_of?: string }
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

export type Cadence = 'weekly' | 'monthly' | 'yearly'
export interface RecurringItem {
  id: number; merchant: string; name: string; amount_cents: number; cadence: Cadence; anchor_date: string
  category_id: number | null; next_due: string; status: 'upcoming' | 'late'; last_amount_cents: number | null; last_date: string | null
}
export interface RecurringSuggestion { merchant: string; cadence: Cadence; amount_cents: number; count: number; last_date: string; next_date: string }
export type RecurringAlert =
  | { kind: 'price_increase'; item_id: number; name: string; previous_cents: number; latest_cents: number; date: string }
  | { kind: 'new_recurring'; merchant: string; amount_cents: number; cadence: Cadence }
export interface Recurring { items: RecurringItem[]; suggestions: RecurringSuggestion[]; alerts: RecurringAlert[] }
export interface RecurringInput { merchant: string; name: string; amount_cents: number; cadence: Cadence; anchor_date: string; category_id: number | null }
export interface UpcomingRow { date: string; item_id: number; name: string; amount_cents: number; balance_cents: number | null; late: boolean }
export interface Upcoming { start_balance_cents: number | null; rows: UpcomingRow[]; bills_cents: number; income_cents: number }

export type GoalStatus = 'done' | 'no_date' | 'unknown' | 'on_track' | 'behind'
export interface Goal {
  id: number; name: string; kind: 'linked' | 'manual'; target_cents: number; target_date: string | null
  current_cents: number; pct: number; rate_cents: number | null; history_days: number | null; needed_cents: number | null
  status: GoalStatus; reach_by: string | null
  accounts: { id: number; name: string }[]
  contributions: { id: number; date: string; amount_cents: number; note: string | null }[]
}
export interface GoalInput { name: string; target_cents: number; target_date: string | null; kind: 'linked' | 'manual'; account_ids: number[] }

export interface NetWorthPoint { date: string; assets_cents: number; liabilities_cents: number; net_cents: number; estimated: boolean }
export interface NetWorth { points: NetWorthPoint[]; change_cents: number; first_actual_date: string | null }
export type NetWorthRange = '1M' | '3M' | 'YTD' | '1Y' | 'ALL'
export type AssetClassName = 'stocks' | 'bonds' | 'cash'
/** `shares` is exact decimal text. Price, basis and gain are null when unknown; `gain_pct` is a fraction (0.1234 = 12.34%). */
export interface Holding {
  id: number; account_id: number; account_name: string; symbol: string; description: string; shares: string
  price_cents: number | null; market_value_cents: number; cost_basis_cents: number | null
  gain_cents: number | null; gain_pct: number | null; asset_class: AssetClassName; as_of: string
}
export interface AllocationClass { asset_class: AssetClassName; value_cents: number; pct: number; target_pct: number | null; drift_pts: number | null; over: boolean }
export interface Allocation { configured: boolean; drift_threshold: number; total_cents: number; classes: AllocationClass[] }
export interface AllocationTargets { configured: boolean; stocks_pct: number | null; bonds_pct: number | null; cash_pct: number | null; drift_threshold: number }
export interface AllocationTargetsInput { stocks_pct: number; bonds_pct: number; cash_pct: number; drift_threshold: number }

export type RsuSchedule = 'amazon_5_15_40_40' | 'semiannual' | 'custom'
export interface RsuVest { id: number; vest_date: string; shares: number; vested: boolean; value_cents: number | null }
export interface RsuGrant {
  id: number; label: string; external_id: string | null; symbol: string; grant_date: string; start_date: string
  total_shares: number; schedule: RsuSchedule; vested_shares: number; unvested_shares: number
  unvested_value_cents: number | null; vests: RsuVest[]
}
/** `as_of` is naive UTC; `source` is 'finnhub' or 'holding'. */
export interface RsuPrice { symbol: string; price_cents: number; as_of: string; source: string }
export interface RsuNextVest { vest_date: string; shares: number; value_cents: number | null; grant_label: string }
export interface Rsu {
  price: RsuPrice | null
  grants: RsuGrant[]
  totals: { unvested_shares: number; unvested_value_cents: number | null; vested_shares: number; next_vest: RsuNextVest | null }
}
export interface RsuVestInput { vest_date: string; shares: number }
export interface RsuGrantInput {
  label: string; external_id?: string | null; symbol?: string; grant_date: string; start_date: string; total_shares: number
  schedule: RsuSchedule; first_vest?: string; count?: number; vests?: RsuVestInput[]
}

export type FilingStatus = 'single' | 'married_jointly'
export interface IncomeProfile {
  id: number; effective_from: string; salary_cents: number; pay_frequency: 'monthly'; k401_pct: number
  filing_status: FilingStatus; extra_withholding_cents: number; employment_start: string
}
export type IncomeProfileInput = Omit<IncomeProfile, 'id' | 'pay_frequency'> & { pay_frequency?: 'monthly' }
export interface PaycheckRow { date: string; kind: 'regular' | 'payment'; label: string; gross_cents: number; lines: { name: string; cents: number }[]; net_cents: number }
export interface PaycheckMonth { month: string; modeled_net_cents: number; actual_cents: number }
export interface Paychecks { year: number; paychecks: PaycheckRow[]; months: PaycheckMonth[]; monthly_take_home_cents: number | null; tax_year_used: number; tax_year_fallback: boolean }
export interface EstimateVest { vest_date: string; grant_label: string; shares: number; value_cents: number | null; withheld_cents: number | null; shortfall_cents: number | null }
export interface TaxEstimate {
  year: number; tax_year_used: number; tax_year_fallback: boolean; has_profile: boolean; filing_status: FilingStatus
  wages_cents: number; pretax_cents: number; vest_income_cents: number; taxable_cents: number; liability_cents: number
  withheld_salary_cents: number; withheld_supplemental_cents: number; withheld_vests_cents: number; withheld_cents: number
  balance_cents: number; marginal_pct: number; threshold_cents: number; alert: boolean; missing_price: boolean; vests: EstimateVest[]
}
export interface CompYear { year: number; salary_cents: number; cash_cents: number; rsu_shares: number; rsu_cents: number | null; total_cents: number | null }
export interface CompProjection { growth_pct: number; price: { symbol: string; price_cents: number } | null; years: CompYear[] }
export type PaymentKind = 'lump' | 'installments'
export interface CashPayment {
  id: number; label: string; kind: PaymentKind; amount_cents: number
  paid_date: string | null; start_date: string | null; end_date: string | null; repay_start: string | null; repay_end: string | null
}
/** The other kind's dates must be sent as explicit nulls, or a kind switch through PATCH keeps the old ones. */
export type CashPaymentInput = Omit<CashPayment, 'id'>
export interface Clawback { items: { payment_id: number; label: string; owed_today_cents: number; zero_date: string }[]; total_cents: number }
/** The loaded tax YAML, as JSON. Money is cents, `rate_pct` a whole percent, `*_bp` basis points. */
export interface TaxConfig {
  year: number
  federal: {
    standard_deduction: Record<FilingStatus, number>
    brackets: Record<FilingStatus, [number, number][]>
    supplemental: { rate_pct: number; high_rate_pct: number; high_threshold: number }
  }
  fica: {
    social_security: { rate_bp: number; wage_base: number }
    medicare: { rate_bp: number; additional_bp: number; additional_threshold: number }
  }
  state: { name: string; payroll: { name: string; rate_bp: number }[] }
}

export type AlertKind = 'sync_error' | 'sync_stale' | 'price_increase' | 'new_recurring' | 'under_withholding' | 'allocation_drift'
export interface Alert { key: string; kind: AlertKind; severity: 'warn' | 'info'; title: string; detail: string; link: string }
/** `unavailable` names the sources that failed to run: sync, recurring, tax or allocation. */
export interface Alerts { alerts: Alert[]; unavailable: string[] }

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(describe(body?.detail, `${res.status} ${res.statusText}`), res.status)
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
  createManualAccount: (body: ManualAccountInput) => request<Account>('/accounts', send('POST', body)),
  updateBalance: (id: number, body: { balance_cents: number; as_of?: string }) => request<Account>(`/accounts/${id}/balance`, send('POST', body)),
  deleteAccount: (id: number) => request<void>(`/accounts/${id}`, send('DELETE')),
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
  recurring: () => request<Recurring>('/recurring'),
  upcoming: (days: number) => request<Upcoming>(`/recurring/upcoming?days=${days}`),
  createRecurring: (body: RecurringInput) => request<RecurringItem>('/recurring/items', send('POST', body)),
  patchRecurring: (id: number, body: Partial<RecurringInput>) => request<RecurringItem>(`/recurring/items/${id}`, send('PATCH', body)),
  deleteRecurring: (id: number) => request<void>(`/recurring/items/${id}`, send('DELETE')),
  confirmSuggestion: (merchant: string) => request<RecurringItem>('/recurring/suggestions/confirm', send('POST', { merchant })),
  dismissSuggestion: (merchant: string) => request<void>('/recurring/suggestions/dismiss', send('POST', { merchant })),
  overview: (month?: string) => request<Overview>(`/overview${month ? `?month=${month}` : ''}`),
  budgetSettings: () => request<BudgetSettings>('/budget/settings'),
  saveBudgetSettings: (body: BudgetSettingsInput) => request<BudgetSettings>('/budget/settings', send('PUT', body)),
  budget: (months: number) => request<Budget>(`/budget?months=${months}`),
  breakdown: (start: string, end: string) => request<Breakdown>(`/breakdown?${query({ start, end })}`),
  cashflow: (months: number) => request<Cashflow>(`/cashflow?months=${months}`),
  categoryBudgets: (month: string) => request<CategoryBudgets>(`/category-budgets?month=${month}`),
  setCategoryBudget: (categoryId: number, month: string, amount_cents: number | null) =>
    request<{ category_id: number; month: string; amount_cents: number | null }>(`/category-budgets/${categoryId}`, send('PUT', { month, amount_cents })),
  goals: () => request<Goal[]>('/goals'),
  createGoal: (body: GoalInput) => request<Goal>('/goals', send('POST', body)),
  patchGoal: (id: number, body: Partial<Omit<GoalInput, 'kind'>>) => request<Goal>(`/goals/${id}`, send('PATCH', body)),
  deleteGoal: (id: number) => request<void>(`/goals/${id}`, send('DELETE')),
  addContribution: (id: number, body: { date: string; amount_cents: number; note?: string }) => request<Goal>(`/goals/${id}/contributions`, send('POST', body)),
  deleteContribution: (id: number, cid: number) => request<void>(`/goals/${id}/contributions/${cid}`, send('DELETE')),
  networth: (range: NetWorthRange) => request<NetWorth>(`/networth?range=${range}`),
  holdings: () => request<Holding[]>('/holdings'),
  setAssetClass: (symbol: string, asset_class: AssetClassName) =>
    request<{ symbol: string; asset_class: AssetClassName }>(`/holdings/classes/${encodeURIComponent(symbol)}`, send('PUT', { asset_class })),
  allocation: () => request<Allocation>('/allocation'),
  allocationTargets: () => request<AllocationTargets>('/allocation/targets'),
  saveAllocationTargets: (body: AllocationTargetsInput) => request<AllocationTargets>('/allocation/targets', send('PUT', body)),
  rsu: () => request<Rsu>('/rsu'),
  createGrant: (body: RsuGrantInput) => request<RsuGrant>('/rsu/grants', send('POST', body)),
  patchGrant: (id: number, body: { label?: string; external_id?: string | null }) => request<RsuGrant>(`/rsu/grants/${id}`, send('PATCH', body)),
  replaceVests: (id: number, vests: RsuVestInput[]) => request<RsuGrant>(`/rsu/grants/${id}/vests`, send('PUT', { vests })),
  deleteGrant: (id: number) => request<void>(`/rsu/grants/${id}`, send('DELETE')),
  incomeProfiles: () => request<IncomeProfile[]>('/income/profiles'),
  saveIncomeProfile: (body: IncomeProfileInput) => request<IncomeProfile>('/income/profiles', send('PUT', body)),
  deleteIncomeProfile: (id: number) => request<void>(`/income/profiles/${id}`, send('DELETE')),
  taxConfig: (year: number) => request<TaxConfig>(`/income/tax-config?year=${year}`),
  paychecks: (year: number) => request<Paychecks>(`/income/paychecks?year=${year}`),
  taxEstimate: (year: number) => request<TaxEstimate>(`/income/tax-estimate?year=${year}`),
  compProjection: (growthPct: number) => request<CompProjection>(`/income/comp-projection?growth_pct=${growthPct}`),
  payments: () => request<CashPayment[]>('/income/payments'),
  createPayment: (body: CashPaymentInput) => request<CashPayment>('/income/payments', send('POST', body)),
  patchPayment: (id: number, body: CashPaymentInput) => request<CashPayment>(`/income/payments/${id}`, send('PATCH', body)),
  deletePayment: (id: number) => request<void>(`/income/payments/${id}`, send('DELETE')),
  clawback: () => request<Clawback>('/income/clawback'),
  alerts: () => request<Alerts>('/alerts'),
  dismissAlert: (key: string) => request<void>('/alerts/dismiss', send('POST', { key })),
  backup: () => request<{ path: string }>('/backups', send('POST')),
}
