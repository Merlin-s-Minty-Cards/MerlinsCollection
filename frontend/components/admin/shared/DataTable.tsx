'use client'

import { useState } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'

export interface Column<T> {
  key: string
  label: string
  sortable?: boolean
  className?: string
  render?: (item: T) => React.ReactNode
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyField: string
  sortKey?: string | null
  sortDir?: 'asc' | 'desc'
  onSort?: (key: string) => void
  onRowClick?: (item: T) => void
  emptyMessage?: string
  loading?: boolean
  selectedIds?: Set<string>
  onSelect?: (id: string, selected: boolean) => void
  onSelectAll?: (selected: boolean) => void
}

export default function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  keyField,
  sortKey,
  sortDir,
  onSort,
  onRowClick,
  emptyMessage = 'No items found',
  loading,
  selectedIds,
  onSelect,
  onSelectAll,
}: DataTableProps<T>) {
  const allSelected = selectedIds && data.length > 0 && data.every((item) => selectedIds.has(String(item[keyField])))

  return (
    <div className="overflow-x-auto vault-scroll rounded-xl border border-pine-700/40">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-pine-700/40 bg-pine-800/30">
            {onSelect && (
              <th className="w-10 px-3 py-2.5">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => onSelectAll?.(e.target.checked)}
                  className="rounded border-pine-600 bg-pine-800 text-mint focus:ring-mint/30"
                  aria-label="Select all"
                />
              </th>
            )}
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-pine-400 ${col.className ?? ''} ${col.sortable && onSort ? 'cursor-pointer select-none hover:text-pine-200' : ''}`}
                onClick={col.sortable && onSort ? () => onSort(col.key) : undefined}
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {col.sortable && onSort && (
                    <SortIndicator active={sortKey === col.key} dir={sortKey === col.key ? sortDir : undefined} />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-pine-700/25">
          {loading ? (
            <tr>
              <td colSpan={columns.length + (onSelect ? 1 : 0)} className="px-3 py-8 text-center text-pine-400 text-xs">
                Loading…
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={columns.length + (onSelect ? 1 : 0)} className="px-3 py-8 text-center text-pine-500 text-xs">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((item) => {
              const id = String(item[keyField])
              const selected = selectedIds?.has(id)
              return (
                <tr
                  key={id}
                  onClick={onRowClick ? () => onRowClick(item) : undefined}
                  className={`
                    transition-colors
                    ${onRowClick ? 'cursor-pointer' : ''}
                    ${selected ? 'bg-mint/5' : 'hover:bg-pine-800/40'}
                  `}
                >
                  {onSelect && (
                    <td className="w-10 px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={(e) => {
                          e.stopPropagation()
                          onSelect(id, e.target.checked)
                        }}
                        onClick={(e) => e.stopPropagation()}
                        className="rounded border-pine-600 bg-pine-800 text-mint focus:ring-mint/30"
                        aria-label={`Select item ${id}`}
                      />
                    </td>
                  )}
                  {columns.map((col) => (
                    <td key={col.key} className={`px-3 py-2 text-[13px] text-pine-200 ${col.className ?? ''}`}>
                      {col.render ? col.render(item) : (item[col.key] as React.ReactNode) ?? '—'}
                    </td>
                  ))}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}

function SortIndicator({ active, dir }: { active: boolean; dir?: 'asc' | 'desc' }) {
  if (!active) return <ChevronsUpDown size={12} className="opacity-40" />
  return dir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
}
