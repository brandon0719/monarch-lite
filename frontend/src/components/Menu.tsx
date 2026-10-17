import { useEffect, useRef, useState, type KeyboardEvent } from 'react'

export interface MenuItem { label: string; onSelect: () => void; disabled?: boolean; danger?: boolean }

/** "⋯" overflow menu: keyboard-operable (arrows, Home/End, Escape), closes on outside click. */
export default function Menu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const enabled = () => Array.from(ref.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])
  useEffect(() => {
    if (!open) return
    enabled()[0]?.focus()
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])
  const close = () => { setOpen(false); trigger.current?.focus() }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!open) return
    if (e.key === 'Escape') { e.stopPropagation(); close(); return }
    const els = enabled()
    if (!els.length) return
    const i = els.indexOf(document.activeElement as HTMLButtonElement)
    const target = e.key === 'ArrowDown' ? els[(i + 1) % els.length]
      : e.key === 'ArrowUp' ? els[i <= 0 ? els.length - 1 : i - 1]
      : e.key === 'Home' ? els[0]
      : e.key === 'End' ? els[els.length - 1] : null
    if (target) { e.preventDefault(); target.focus() }
  }
  return (
    <div className="menu" ref={ref} onKeyDown={onKeyDown}
      // Only a real focus target outside closes it: Safari/Firefox give buttons no focus on click (relatedTarget null),
      // and the outside-click listener already covers that.
      onBlur={(e) => { const to = e.relatedTarget as Node | null; if (open && to && !ref.current?.contains(to)) setOpen(false) }}>
      <button type="button" className="icon-button" ref={trigger} aria-label={label} aria-haspopup="menu" aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}>⋯</button>
      {open && (
        <div className="menu-list" role="menu" aria-label={label}>
          {items.map((item) => (
            <button key={item.label} type="button" role="menuitem" disabled={item.disabled} className={item.danger ? 'danger' : undefined}
              onClick={(e) => { e.stopPropagation(); close(); item.onSelect() }}>{item.label}</button>
          ))}
        </div>
      )}
    </div>
  )
}
