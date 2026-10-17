import type { Category } from './api'

/** Muted pastels, distinguishable in both themes. Index by category id so colors never shuffle. */
const PALETTE = ['#7aa2c9', '#d9a066', '#8fc19f', '#c48fb0', '#b9a3d6', '#e0b85c', '#79b8b0', '#d98a7e', '#9fb36b', '#6fa0d8', '#cf9bbd', '#c9b48a']
export const NEUTRAL = '#a39e95'

export function categoryColor(category: Pick<Category, 'id' | 'bucket'> | null | undefined): string {
  if (!category || category.bucket === 'excluded') return NEUTRAL
  return PALETTE[category.id % PALETTE.length]
}
