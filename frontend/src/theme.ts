export type Theme = 'system' | 'light' | 'dark'
const KEY = 'monarch-lite-theme'

/** URL ?theme= wins (used by ops/screenshots.sh), then the saved choice, then 'system'. */
export function getTheme(): Theme {
  const fromUrl = new URLSearchParams(window.location.search).get('theme')
  if (fromUrl === 'light' || fromUrl === 'dark' || fromUrl === 'system') return fromUrl
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
  } catch { /* storage blocked: fall through */ }
  return 'system'
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
}

export function setTheme(theme: Theme) {
  try { localStorage.setItem(KEY, theme) } catch { /* storage blocked: still apply for this session */ }
  applyTheme(theme)
}
