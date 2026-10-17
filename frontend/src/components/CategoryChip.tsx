import type { CSSProperties } from 'react'
import type { Category } from '../api'
import { categoryColor } from '../colors'

export default function CategoryChip({ category, name }: { category?: Category | null; name?: string | null }) {
  const label = category?.name ?? name ?? 'Uncategorized'
  return (
    <span className={`chip${!category && !name ? ' chip-empty' : ''}`} style={{ '--chip': categoryColor(category) } as CSSProperties}>
      <span className="chip-dot" aria-hidden="true" /><span className="chip-label">{label}</span>
    </span>
  )
}
