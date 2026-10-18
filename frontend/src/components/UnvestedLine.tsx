import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { formatCents, formatDate } from '../format'

/** Muted "+ $X unvested RSUs · next vest <date>" link under net worth. Renders nothing while loading, on error, or with no unvested shares. */
export default function UnvestedLine() {
  const rsu = useQuery({ queryKey: ['rsu'], queryFn: api.rsu })
  const t = rsu.data?.totals
  if (!t || t.unvested_shares <= 0) return null
  const amount = t.unvested_value_cents === null
    ? `${t.unvested_shares.toLocaleString()} unvested ${t.unvested_shares === 1 ? 'share' : 'shares'}`
    : `${formatCents(t.unvested_value_cents)} unvested RSUs`
  return (
    <Link className="unvested" to="/equity">
      + {amount}{t.next_vest && ` · next vest ${formatDate(t.next_vest.vest_date)}`}
    </Link>
  )
}
