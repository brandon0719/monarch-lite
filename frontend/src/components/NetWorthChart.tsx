import { useState, type PointerEvent } from 'react'
import type { NetWorthPoint } from '../api'
import { formatCents, formatDate } from '../format'

const W = 600
const H = 220

/** Consecutive points with the same `estimated` flag. Each run but the last also takes the next run's first point, so the line stays continuous. */
function runs(points: NetWorthPoint[]): { estimated: boolean; pts: NetWorthPoint[] }[] {
  const out: { estimated: boolean; pts: NetWorthPoint[] }[] = []
  for (const p of points) {
    const last = out[out.length - 1]
    if (last && last.estimated === p.estimated) last.pts.push(p)
    else {
      last?.pts.push(p)
      out.push({ estimated: p.estimated, pts: [p] })
    }
  }
  return out
}

export default function NetWorthChart({ points }: { points: NetWorthPoint[] }) {
  const [hover, setHover] = useState<number | null>(null)
  if (points.length === 0) return <p className="muted">No balance history yet.</p>

  const first = points[0]!
  const last = points[points.length - 1]!
  const values = points.flatMap((p) => [p.net_cents, p.assets_cents, p.liabilities_cents])
  const min = Math.min(...values)
  const max = Math.max(...values)
  const pad = (max - min) * 0.05 || Math.max(Math.abs(max) * 0.05, 100)
  const lo = min - pad
  const hi = max + pad
  const t0 = Date.parse(`${first.date}T00:00:00Z`)
  const span = Date.parse(`${last.date}T00:00:00Z`) - t0
  const xOf = (p: NetWorthPoint) => (span > 0 ? ((Date.parse(`${p.date}T00:00:00Z`) - t0) / span) * W : W / 2)
  const yOf = (cents: number) => H - ((cents - lo) / (hi - lo)) * H
  const line = (pts: NetWorthPoint[], pick: (p: NetWorthPoint) => number) =>
    pts.map((p) => `${xOf(p).toFixed(1)},${yOf(pick(p)).toFixed(1)}`).join(' ')
  const yPct = (cents: number) => `${(yOf(cents) / H) * 100}%`

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect()
    if (box.width === 0) return
    const x = Math.min(Math.max((e.clientX - box.left) / box.width, 0), 1) * W
    let best = 0
    for (let i = 1; i < points.length; i++) if (Math.abs(xOf(points[i]!) - x) < Math.abs(xOf(points[best]!) - x)) best = i
    setHover(best)
  }
  const h = hover === null ? null : points[hover]!

  return (
    <div className="nwc">
      <div className="nwc-body">
        <div className="nwc-y" aria-hidden="true">
          <span style={{ top: yPct(max) }}>{formatCents(max)}</span>
          {max !== min && <span style={{ top: yPct(min) }}>{formatCents(min)}</span>}
        </div>
        <div className="nwc-plot" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
            aria-label={`Net worth from ${formatDate(first.date)} to ${formatDate(last.date)}: ${formatCents(first.net_cents)} to ${formatCents(last.net_cents)}`}>
            <polyline className="nwc-faint" points={line(points, (p) => p.assets_cents)} />
            <polyline className="nwc-faint" points={line(points, (p) => p.liabilities_cents)} />
            {runs(points).map((r, i) => (
              <polyline key={i} className={`nwc-net${r.estimated ? ' est' : ''}`} points={line(r.pts, (p) => p.net_cents)} />
            ))}
            {h && <line className="nwc-cross" x1={xOf(h)} x2={xOf(h)} y1={0} y2={H} />}
            {/* A zero-length round-capped stroke is a dot that stays round under the non-uniform scaling. */}
            <path className="nwc-dot" d={`M${xOf(h ?? last)},${yOf((h ?? last).net_cents)}h0`} />
          </svg>
          {h && (
            <div className="nwc-tip" style={{ left: `${(xOf(h) / W) * 100}%` }} data-side={xOf(h) > W * 0.6 ? 'left' : 'right'} aria-hidden="true">
              <b>{formatDate(h.date)}{h.estimated ? ' (estimated)' : ''}</b>
              <span>Net worth {formatCents(h.net_cents)}</span>
              <span>Assets {formatCents(h.assets_cents)}</span>
              <span>Liabilities {formatCents(h.liabilities_cents)}</span>
            </div>
          )}
        </div>
        <div className="nwc-x muted" aria-hidden="true">
          <span>{formatDate(first.date)}</span>
          <span>{formatDate(last.date)}</span>
        </div>
      </div>
      <p className="nwc-legend muted" aria-hidden="true">
        <span><i className="nwc-key net" />Net worth</span>
        <span><i className="nwc-key faint" />Assets and liabilities</span>
      </p>
    </div>
  )
}
