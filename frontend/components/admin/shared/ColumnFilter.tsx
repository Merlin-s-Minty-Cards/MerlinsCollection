'use client'

/**
 * One filter control, rendered from its registry entry's `kind` — RFC 0011 T4.
 *
 * The inventory page used to carry a hand-written control per filter, which is
 * why it had twelve of them for thirty-three columns: every new field cost a
 * `useState`, a JSX block and a line in the fetch. Coverage is a data problem
 * here, so the KIND is declared once in `INVENTORY_FILTERS` (mirroring the
 * backend's `FILTERABLE_FIELDS`) and this switch is the whole of the rendering.
 *
 * **Every branch carries `vault-field`.** CLAUDE.md: *"Never ship an admin
 * control without `vault-field`."* The admin theme is dark with light-green
 * text, so a bare `<select>` inherits that text colour over the browser's white
 * default and renders illegible — which is exactly how the Slabs page shipped.
 */

import type { InventoryFilterDef } from '@/lib/admin-inventory-columns'

const FIELD = 'vault-field px-2.5 py-1.5 rounded-lg text-xs w-full'
const SELECT = `${FIELD} appearance-none cursor-pointer`

export interface ColumnFilterProps {
  def: InventoryFilterDef
  value: string
  onChange: (value: string) => void
  /** Resolved choices for a `select` — either `def.options` or a fetched list. */
  options?: { value: string; label: string }[]
}

export default function ColumnFilter({ def, value, onChange, options = [] }: ColumnFilterProps) {
  switch (def.kind) {
    case 'select':
      return (
        <select
          aria-label={def.label}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={SELECT}
        >
          <option value="">{def.label}</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      )

    case 'presence':
      return (
        <select
          aria-label={def.label}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={SELECT}
        >
          <option value="">{def.label}</option>
          <option value="has">Has {def.label.toLowerCase()}</option>
          <option value="missing">Missing {def.label.toLowerCase()}</option>
        </select>
      )

    case 'dateRange':
      // A date input yields YYYY-MM-DD, which is what the backend parses with
      // `date.fromisoformat`. Nothing here goes near `new Date()` — that would
      // read a date-only string as UTC midnight and shift it a day west.
      return (
        <input
          type="date"
          aria-label={def.label}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={FIELD}
        />
      )

    case 'range':
    case 'text':
    default:
      // NOT type="number", even for a money bound. A native number input
      // refuses a comma, which makes the owner's `1,300` un-typeable rather
      // than correct — it satisfies the machine and fails the person.
      // `buildFilterParams` parses the bound with `parseMoney`.
      return (
        <input
          type="text"
          inputMode={def.kind === 'range' ? 'decimal' : undefined}
          aria-label={def.label}
          placeholder={def.label}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={FIELD}
        />
      )
  }
}
