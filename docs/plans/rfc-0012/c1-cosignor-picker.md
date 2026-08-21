# Task C1: `useCosigners` Hook + `CosignorPicker` Component

**Files:**
- Create: `frontend/lib/use-cosigners.ts`
- Create: `frontend/components/admin/shared/CosignorPicker.tsx`
- Test: `frontend/lib/__tests__/use-cosigners.test.ts`
- Test: `frontend/components/admin/shared/__tests__/CosignorPicker.test.tsx`

**Interfaces:**
- Produces:
  - `useCosigners(): { options: { value: string; label: string }[]; loading: boolean }`
    from `frontend/lib/use-cosigners.ts` — same return shape as
    `useLocations()` (`frontend/lib/use-locations.ts`) and `useShows()`, so
    it slots into `admin-inventory-columns.tsx`'s existing `optionSource`
    pattern (see C2) without inventing a new shape. `value` is the
    cosigner's `consignor_id`, `label` is its `name`. Fetches
    `GET /admin/cosigners` (archived cosigners already excluded by that
    endpoint by default — no client-side filtering needed).
  - `CosignorPicker` component, default export from
    `frontend/components/admin/shared/CosignorPicker.tsx`:
    ```tsx
    export interface CosignorPickerProps {
      value: string | null
      onChange: (consignorId: string | null) => void
      label?: string          // default "Consignor"
      allowClear?: boolean    // default true — shows a "No consignor" option
    }
    export default function CosignorPicker(props: CosignorPickerProps): JSX.Element
    ```
    A text input that client-side substring-filters the list from
    `useCosigners()` as the admin types, with a dropdown of matches; picking
    one calls `onChange(consignor_id)` and shows the name in the input.
    Clearing the input (or picking "No consignor") calls `onChange(null)`.
  - Consumed by: C2 (inventory filter, via `useCosigners()` only — the
    filter bar renders its own combobox using the hook, see C2), C3
    (`CardDetailModal`, via `CosignorPicker`), C4 (`IncomingCardForm`, via
    `CosignorPicker`).

## Context

Per RFC 0012 section C: the cosigner list is small (owner-managed, dozens at
most), so this mirrors `useLocations()`'s "fetch once, fall back gracefully"
shape rather than `CardSearchPanel`'s debounced server-search shape built
for a 31,603-row catalog. `GET /admin/cosigners` already exists
(`backend/src/merlins_collection/routers/admin/cosigners.py:111-124`) and
already excludes archived cosigners unless `?include_archived=true` is
passed — this task never passes that param, so an archived cosigner never
appears as assignable, matching every other archived-entity pattern in this
codebase.

- [ ] **Step 1: Write the failing hook test**

Create `frontend/lib/__tests__/use-cosigners.test.ts`:

```typescript
// @vitest-environment node
import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCosigners } from '../use-cosigners'

const getMock = vi.fn()

vi.mock('../admin-api', () => ({
  useAdminApi: () => ({ get: getMock, post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() }),
}))

describe('useCosigners', () => {
  it('fetches /cosigners and maps consignor_id/name to value/label', async () => {
    getMock.mockResolvedValue([
      { consignor_id: 'c1', name: 'Alex' },
      { consignor_id: 'c2', name: 'Bailey' },
    ])
    const { result } = renderHook(() => useCosigners())
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).toEqual([
      { value: 'c1', label: 'Alex' },
      { value: 'c2', label: 'Bailey' },
    ])
    expect(getMock).toHaveBeenCalledWith('/cosigners')
  })

  it('falls back to an empty list on a fetch failure, never throws', async () => {
    getMock.mockRejectedValue(new Error('network'))
    const { result } = renderHook(() => useCosigners())
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).toEqual([])
  })
})
```

Check `frontend/lib/__tests__/use-locations.test.ts` (if it exists) for this
repo's exact `renderHook`/testing-library-react setup before writing this —
match its import style and any custom render wrapper it uses.

- [ ] **Step 2: Run it to verify it fails**

Run:
```bash
cd "c:/Users/ethar/.cursor/projects/MerlinsCollection-Secondary/frontend"
npx vitest run lib/__tests__/use-cosigners.test.ts --reporter=verbose
```
Expected: FAIL with "Cannot find module '../use-cosigners'".

- [ ] **Step 3: Implement `useCosigners`**

Create `frontend/lib/use-cosigners.ts`:

```typescript
'use client'

import { useEffect, useState } from 'react'
import { useAdminApi } from './admin-api'

export type CosignorOption = { value: string; label: string }

interface CosignorRow {
  consignor_id: string
  name: string
}

/**
 * Fetches assignable cosigners once. GET /admin/cosigners already excludes
 * archived cosigners by default (cosigners.py:111-124) — this never passes
 * include_archived, so an archived cosigner is never offered as an
 * assignment target, matching the archived-entity pattern used everywhere
 * else in this codebase.
 */
export function useCosigners(): { options: CosignorOption[]; loading: boolean } {
  const api = useAdminApi()
  const [options, setOptions] = useState<CosignorOption[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    api
      .get<CosignorRow[]>('/cosigners')
      .then((rows) => {
        if (!cancelled) setOptions(rows.map((r) => ({ value: r.consignor_id, label: r.name })))
      })
      .catch(() => {
        if (!cancelled) setOptions([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { options, loading }
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npx vitest run lib/__tests__/use-cosigners.test.ts --reporter=verbose`
Expected: PASS.

- [ ] **Step 5: Write the failing component test**

Create `frontend/components/admin/shared/__tests__/CosignorPicker.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CosignorPicker from '../CosignorPicker'

vi.mock('@/lib/use-cosigners', () => ({
  useCosigners: () => ({
    options: [
      { value: 'c1', label: 'Alex' },
      { value: 'c2', label: 'Bailey' },
    ],
    loading: false,
  }),
}))

describe('CosignorPicker', () => {
  it('filters the dropdown as the admin types', async () => {
    const user = userEvent.setup({ delay: null })
    render(<CosignorPicker value={null} onChange={vi.fn()} />)
    const input = screen.getByRole('combobox', { name: /consignor/i })
    await user.type(input, 'bai')
    expect(screen.getByText('Bailey')).toBeInTheDocument()
    expect(screen.queryByText('Alex')).not.toBeInTheDocument()
  })

  it('calls onChange with the consignor_id when an option is picked', async () => {
    const user = userEvent.setup({ delay: null })
    const onChange = vi.fn()
    render(<CosignorPicker value={null} onChange={onChange} />)
    await user.click(screen.getByRole('combobox', { name: /consignor/i }))
    await user.click(screen.getByText('Alex'))
    expect(onChange).toHaveBeenCalledWith('c1')
  })

  it('offers a clear option that calls onChange(null)', async () => {
    const user = userEvent.setup({ delay: null })
    const onChange = vi.fn()
    render(<CosignorPicker value="c1" onChange={onChange} />)
    await user.click(screen.getByRole('button', { name: /clear consignor/i }))
    expect(onChange).toHaveBeenCalledWith(null)
  })
})
```

- [ ] **Step 6: Run it to verify it fails**

Run: `npx vitest run components/admin/shared/__tests__/CosignorPicker.test.tsx --reporter=verbose`
Expected: FAIL with "Cannot find module '../CosignorPicker'".

- [ ] **Step 7: Implement `CosignorPicker`**

Create `frontend/components/admin/shared/CosignorPicker.tsx`:

```tsx
'use client'

import { useMemo, useState } from 'react'
import { useCosigners } from '@/lib/use-cosigners'

export interface CosignorPickerProps {
  value: string | null
  onChange: (consignorId: string | null) => void
  label?: string
  allowClear?: boolean
}

/**
 * A small (owner-managed, dozens-at-most) searchable dropdown over
 * useCosigners() — client-side substring filter, no server search, matching
 * useLocations()'s complexity level rather than CardSearchPanel's.
 */
export default function CosignorPicker({
  value,
  onChange,
  label = 'Consignor',
  allowClear = true,
}: CosignorPickerProps) {
  const { options } = useCosigners()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)

  const selected = options.find((o) => o.value === value) ?? null

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => o.label.toLowerCase().includes(q))
  }, [options, query])

  return (
    <div className="relative flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wider text-pine-400">{label}</span>
      <div className="flex items-center gap-1.5">
        <input
          role="combobox"
          aria-label={label}
          aria-expanded={open}
          className="vault-field w-full rounded-lg px-3 py-2 text-sm"
          value={open ? query : (selected?.label ?? '')}
          placeholder="Search cosigners…"
          onFocus={() => {
            setOpen(true)
            setQuery('')
          }}
          onChange={(e) => setQuery(e.target.value)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
        {allowClear && selected && (
          <button
            type="button"
            aria-label="Clear consignor"
            className="text-[11px] text-pine-400 hover:text-pine-100"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onChange(null)}
          >
            Clear
          </button>
        )}
      </div>
      {open && (
        <div className="absolute top-full left-0 mt-1 w-full max-h-56 overflow-y-auto vault-panel rounded-lg border border-pine-700/40 shadow-xl z-30">
          {filtered.length === 0 ? (
            <p className="px-3 py-2 text-xs text-pine-500">No cosigners match.</p>
          ) : (
            filtered.map((o) => (
              <button
                key={o.value}
                type="button"
                className="block w-full px-3 py-2 text-left text-xs text-pine-200 hover:bg-mint/10"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(o.value)
                  setOpen(false)
                  setQuery('')
                }}
              >
                {o.label}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 8: Run it to verify it passes**

Run: `npx vitest run components/admin/shared/__tests__/CosignorPicker.test.tsx --reporter=verbose`
Expected: PASS.

- [ ] **Step 9: Run the full frontend suite**

Run: `npm test --workspace=frontend`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/lib/use-cosigners.ts frontend/lib/__tests__/use-cosigners.test.ts frontend/components/admin/shared/CosignorPicker.tsx frontend/components/admin/shared/__tests__/CosignorPicker.test.tsx
git commit -m "feat(rfc-0012): add useCosigners hook and CosignorPicker component"
```
