import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import { applyTheme, getTheme } from './theme'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } })

// Derived views (overview, budget meters, category budgets, cash flow, recurring, net worth, holdings, allocation, rsu, income, alerts) are computed from transactions/accounts/categories/rules.
// Rather than touching every page's invalidations, refetch them whenever ANY mutation succeeds.
const DERIVED_VIEWS = ['overview', 'budget', 'cashflow', 'category-budgets', 'breakdown', 'recurring', 'goals', 'networth', 'holdings', 'allocation', 'rsu', 'income', 'alerts']
queryClient.getMutationCache().subscribe((event) => {
  if (event.type === 'updated' && event.action.type === 'success') {
    for (const key of DERIVED_VIEWS) void queryClient.invalidateQueries({ queryKey: [key] })
  }
})

applyTheme(getTheme())

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <App />
      </HashRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
