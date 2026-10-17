import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api'
import { formatDateTime } from './format'
import Accounts from './pages/Accounts'
import Categories from './pages/Categories'
import Goals from './pages/Goals'
import NetWorth from './pages/NetWorth'
import Overview from './pages/Overview'
import Recurring from './pages/Recurring'
import Rules from './pages/Rules'
import Settings from './pages/Settings'
import Spending from './pages/Spending'
import Transactions from './pages/Transactions'
import { getTheme, setTheme, type Theme } from './theme'

const NAV: [string, string][] = [
  ['/overview', 'Overview'],
  ['/transactions', 'Transactions'],
  ['/spending', 'Spending'],
  ['/recurring', 'Recurring'],
  ['/goals', 'Goals'],
  ['/accounts', 'Accounts'],
  ['/networth', 'Net worth'],
  ['/rules', 'Rules'],
  ['/categories', 'Categories'],
  ['/settings', 'Settings'],
]

const THEMES: [Theme, string][] = [['system', 'System'], ['light', 'Light'], ['dark', 'Dark']]
const STALE_AFTER_MS = 36 * 3600 * 1000

function ThemeToggle() {
  const [theme, setChoice] = useState<Theme>(getTheme)
  const choose = (value: Theme) => { setTheme(value); setChoice(value) }
  // Roving tabindex: Tab lands on the checked option, arrows move and select.
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const next = (THEMES.findIndex(([v]) => v === theme) + step + THEMES.length) % THEMES.length
    choose(THEMES[next][0])
    e.currentTarget.querySelectorAll('button')[next].focus()
  }
  return (
    <div className="theme-toggle" role="radiogroup" aria-label="Theme" onKeyDown={onKeyDown}>
      {THEMES.map(([value, label]) => (
        <button key={value} type="button" role="radio" aria-checked={theme === value} tabIndex={theme === value ? 0 : -1}
          className={theme === value ? 'active' : undefined} onClick={() => choose(value)}>{label}</button>
      ))}
    </div>
  )
}

export default function App() {
  const [navOpen, setNavOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const { pathname } = useLocation()
  useEffect(() => setNavOpen(false), [pathname])
  useEffect(() => {
    if (!navOpen) return
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') { setNavOpen(false); menuButton.current?.focus() } }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [navOpen])
  const overview = useQuery({ queryKey: ['overview'], queryFn: () => api.overview() })
  const toReview = overview.data?.to_review ?? 0
  const syncedAt = overview.data?.last_synced_at
  // Backend datetimes are naive UTC.
  const stale = syncedAt ? Date.now() - new Date(`${syncedAt}Z`).getTime() > STALE_AFTER_MS : true

  return (
    <div className={`shell${navOpen ? ' nav-open' : ''}`}>
      <aside className="sidebar" id="sidebar">
        <div className="brand">monarch-lite</div>
        <nav className="nav" aria-label="Main">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} onClick={() => setNavOpen(false)}>
              {label}
              {to === '/transactions' && toReview > 0 && <span className="badge">{toReview}<span className="visually-hidden"> to review</span></span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <ThemeToggle />
          <p className="sync-line">
            {overview.isError ? '—' : (
              <>
                <span className={`status-dot ${syncedAt && !stale ? 'ok' : 'stale'}`} aria-hidden="true" />
                {syncedAt ? `Synced ${formatDateTime(syncedAt)}` : 'Not synced yet'}
              </>
            )}
          </p>
        </div>
      </aside>
      {navOpen && <div className="overlay nav-scrim" onClick={() => setNavOpen(false)} />}
      <div className="content">
        <header className="topbar">
          <button type="button" className="menu-button" ref={menuButton} aria-label="Open navigation" aria-controls="sidebar" aria-expanded={navOpen}
            onClick={() => setNavOpen((o) => !o)}>☰</button>
          <span className="brand">monarch-lite</span>
        </header>
        <main>
          <Routes>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route path="/overview" element={<Overview />} />
            <Route path="/transactions" element={<Transactions />} />
            <Route path="/spending" element={<Spending />} />
            <Route path="/recurring" element={<Recurring />} />
            <Route path="/goals" element={<Goals />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/networth" element={<NetWorth />} />
            <Route path="/rules" element={<Rules />} />
            <Route path="/categories" element={<Categories />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
