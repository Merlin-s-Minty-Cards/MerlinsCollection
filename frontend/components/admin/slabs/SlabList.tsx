'use client'

import CardImage, { TABLE_THUMB_SIZE, TABLE_THUMB_COLUMN } from '@/components/admin/shared/CardImage'
import DataTable, { type Column } from '@/components/admin/shared/DataTable'
import { useCardImages } from '@/lib/use-card-images'

/** One row of `GET /admin/slabs`. Money fields are STRINGS — a Decimal that
 *  survived JSON without being rounded into a float on the way out. */
export interface SlabRow {
  item_id: string
  card_id: string | null
  name: string | null
  cert_number: string
  company: string
  grade: string
  cost_basis: string
  status: string
  market_value: string | null
  value_as_of: string | null
  price_source: string | null
  // DataTable's generic constraint is `Record<string, unknown>` — this row
  // type gained that requirement in RFC 0013 T4d when SlabList moved onto
  // DataTable; every other admin row type carries the same signature.
  [key: string]: unknown
}

/**
 * How old a stored value is, in words.
 *
 * Staleness is a NORMAL state to display here, not an error to hide: T7 rotates
 * refreshes through the shelf a night at a time (the free tier is 50 lookups a
 * day), so most slabs are legitimately a few days behind at any moment. Saying
 * so is what stops an operator reading a stale figure as a live one.
 */
export function valueAge(iso: string | null): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  const days = Math.floor((Date.now() - then) / 86_400_000)
  if (days <= 0) return 'priced today'
  if (days === 1) return 'priced 1 day ago'
  return `priced ${days} days ago`
}

export default function SlabList({
  rows,
  sortKey,
  sortDir,
  onSort,
}: {
  rows: SlabRow[]
  // RFC 0013 T4d — same optional DataTable contract as every other admin
  // list. All three are optional so a caller (and this component's own
  // existing tests) can render an unsorted list exactly as before.
  sortKey?: string | null
  sortDir?: 'asc' | 'desc'
  onSort?: (key: string) => void
}) {
  // A freshly-mapped array every render, which is what the hook expects — it
  // attempts each id exactly once and will not re-queue a failure, so passing a
  // memoized array would not save a request and re-queueing would cost one per
  // render (CLAUDE.md, the Trade page's request storm).
  const { getImageUrl } = useCardImages(rows.map((r) => r.card_id))

  const columns: Column<SlabRow>[] = [
    {
      key: '_image',
      label: '',
      className: TABLE_THUMB_COLUMN,
      render: (row) => (
        <CardImage
          imageUrl={getImageUrl(row.card_id)}
          alt={row.name || row.cert_number}
          size={TABLE_THUMB_SIZE}
        />
      ),
    },
    {
      key: 'name',
      label: 'Card',
      sortable: true,
      render: (row) => (
        <span className="text-pine-100">
          {row.name || <span className="text-pine-500">unnamed</span>}
        </span>
      ),
    },
    {
      key: 'cert_number',
      label: 'Cert',
      sortable: true,
      render: (row) => <span className="font-mono text-pine-300">{row.cert_number}</span>,
    },
    {
      key: 'company',
      label: 'Company',
      sortable: true,
      render: (row) => <span className="text-pine-300">{row.company}</span>,
    },
    {
      key: 'grade',
      label: 'Grade',
      sortable: true,
      render: (row) => <span className="font-mono text-pine-200">{row.grade}</span>,
    },
    {
      // Sorts by the DERIVED `priced` flag (RFC 0013), not the raw money
      // value — see services/slabs_sort.py's docstring. `market_value` was
      // never a candidate: an unpriced JP slab is the ordinary state after
      // the verified-join rule, not an omission, so "has a value at all" is
      // the more useful ordering than the figure itself.
      key: 'priced',
      label: 'Value',
      sortable: true,
      render: (row) => {
        const age = valueAge(row.value_as_of)
        if (row.market_value === null) {
          // NEVER $0.00. A slab shown at zero drags every total and
          // misreports position while looking authoritative; "not priced"
          // is the honest state and, after the verified-join rule, the
          // ordinary one for a Japanese slab.
          return (
            <span className="rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300">
              not priced
            </span>
          )
        }
        return (
          <>
            <span className="font-mono text-spriggatito-400">${row.market_value}</span>
            {row.price_source === 'manual' && (
              <span className="ml-2 rounded bg-pine-800/60 px-1.5 py-0.5 text-[10px] text-pine-300">
                manual
              </span>
            )}
            {age && <span className="ml-2 text-[10px] text-pine-500">{age}</span>}
          </>
        )
      },
    },
    {
      key: 'cost_basis',
      label: 'Cost',
      sortable: true,
      render: (row) => <span className="font-mono text-pine-200">${row.cost_basis}</span>,
    },
    {
      key: 'status',
      label: 'Status',
      sortable: true,
      render: (row) => <span className="text-pine-300">{row.status}</span>,
    },
  ]

  return (
    <DataTable
      columns={columns}
      data={rows}
      keyField="item_id"
      emptyMessage="No slabs yet."
      sortKey={sortKey}
      sortDir={sortDir}
      onSort={onSort}
    />
  )
}
