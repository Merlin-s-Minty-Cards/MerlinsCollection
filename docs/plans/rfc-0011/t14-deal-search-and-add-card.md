# T14 — One search, one add-card form, identity always visible

**RFC:** 0011 §J, §K · **Layer:** frontend · **Depends on:** T11, T13 · **Blocks:** T15
**Owner report:** *"I don't like the show image on hover, because card image, name, and
price should all be shown when searching for cards, as well as when added to coming in or
going out… the option for manual entry should be available, but the manual entry fields
should be hidden by default."*

## What this task builds

Two components, and nothing else. T15 assembles them into the page; keeping them separate
is what makes either one rejectable on its own.

| Component | Job |
|---|---|
| `DealSearchPanel` | Source toggle + search + result rows. Catalog **or** inventory. |
| `IncomingCardForm` | Catalog pick → Raw/Graded → kind-specific fields. Manual entry as a disclosure. |

## Files

- **Create:** `frontend/components/admin/deal/DealSearchPanel.tsx`
- **Create:** `frontend/components/admin/deal/IncomingCardForm.tsx`
- **Create:** `frontend/components/admin/deal/DealCardRow.tsx`
- **Create:** `frontend/components/admin/deal/__tests__/` for all three
- **Modify:** `frontend/lib/trade-incoming-form.ts` — extend for the graded branch

## Interfaces

**Consumes:** T11's `CardSearchPanel` (name + number + set combobox against
`/market/search`) for the catalog source. **Do not reimplement catalog search here** —
compose it. T13's incoming-leg keys for the graded fields.

**Produces** (T15 imports all three):

```tsx
export type DealMode = 'buy' | 'sell' | 'trade'
export type SearchSource = 'catalog' | 'inventory'

export function sourceForMode(mode: DealMode): SearchSource | 'both'
// buy -> 'catalog' (locked), sell -> 'inventory' (locked), trade -> 'both' (toggle shown)

interface DealSearchPanelProps {
  mode: DealMode
  source: SearchSource
  onSourceChange: (s: SearchSource) => void   // ignored unless mode === 'trade'
  onPickCatalog: (card: PickerCard) => void
  onPickInventory: (item: InventoryItem) => void
  onManualEntry: () => void
}

interface IncomingCardFormProps {
  card: PickerCard | null          // null == manual entry
  onAdd: (leg: IncomingLeg) => void
  onCancel: () => void
}

export interface IncomingLeg {
  card_id: string | null
  name: string
  agreed_value: number
  kind: 'raw' | 'graded'
  condition?: string; finish?: string          // raw only
  company?: string; grade?: number             // graded only
  cert_number?: string; grade_label?: string   // graded only
  language: string; location: string
}
```

## Design

### `DealCardRow` — the one row shape, used in four places

Search results, Coming In, Going Out, and the confirm dialog all render **the same row**.
That is the point: the owner's objection is that identity is inconsistent, appearing on a
hover in one place and not at all in another.

```
┌──────┬────────────────────────────────────────┬───────────┬───┐
│ [img]│ Charizard                              │  $120.00  │ + │
│ 56×78│ Base Set · #4 · Rare        [PSA 10]   │  market   │   │
└──────┴────────────────────────────────────────┴───────────┴───┘
   ↑         ↑ min-w-0 + truncate                    ↑ mono
   never shrinks, never grows, 5:7                   right-aligned
```

Non-negotiables, each carried from a rule that already exists:

- **`TABLE_THUMB_SIZE` / `TABLE_THUMB_COLUMN`, imported not re-picked.** CLAUDE.md records
  four pages that each chose their own size and each rendered art wider than its own cell.
- **`min-w-0 flex-1` + `truncate` on the text block**, so a long name shrinks instead of
  shoving the image.
- **A card-less or failed id renders the placeholder**, never a collapsed row. Rows that
  change height as art loads make the list jump under the cursor mid-click.
- **An absent price renders `—`, never `$0.00`.** A `FinishPrice` band exists only when a
  provider published a figure.
- **A catalog price is a NEAR MINT figure and is not condition-adjusted.** Label it
  `market`. Never present it as a sale price.
- **`aria-label` on the row's action names the card**, so a screen reader hears "Add
  Charizard", not "Add".

**There is no hover behaviour of any kind carrying information.** Hover may change
background colour. It may not reveal an image, a price, or a control that is otherwise
absent.

### `DealSearchPanel`

Full page width (T15 places it), so the row above has room to breathe — that width *is*
the fix for "squished".

```
┌────────────────────────────────────────────────────────────────┐
│  ( Catalog ) ( Inventory )   [ name…] [ # ] [ set ▾]  + Manual │
├────────────────────────────────────────────────────────────────┤
│  [img] Charizard    Base Set · #4 · Rare           $120.00  +  │
│  [img] Blastoise    Base Set · #2 · Rare            $80.00  +  │
└────────────────────────────────────────────────────────────────┘
```

- **The source toggle renders only when `mode === 'trade'`.** In Buy and Sell it is absent
  — not disabled. A control that can be set exactly one way is noise, and CLAUDE.md
  already records the reasoning for deleting rather than disabling (`/admin/slabs`' three
  removed buttons).
- **Catalog source** delegates to T11's `CardSearchPanel`.
- **Inventory source** searches `/inventory/search?status=available` and renders the same
  `DealCardRow` — this is the picker that has **no image at all** today
  (`trade/page.tsx:713`), and fixing it is half the owner's complaint.
- **"+ Manual" is a permanent control**, present before any search runs. It does not open
  a form here; it calls `onManualEntry`, and `IncomingCardForm` decides.

### `IncomingCardForm` — catalog pick first, then kind

Decision 14: *"regardless you should be picking a card from the catalog, it's just that
graded cards have more values."*

```
┌────────────────────────────────────────────────────────────┐
│ [img] Charizard   Base Set · #4 · Rare        market $120  │
├────────────────────────────────────────────────────────────┤
│           ( Raw )  ( Graded )        ← kind toggle         │
├────────────────────────────────────────────────────────────┤
│  RAW:     Condition [NM ▾]  Finish [normal ▾]              │
│  GRADED:  Company [PSA ▾]  Grade [10]  Cert # [________]   │
│           Grade label [GEM MT 10]                          │
│           ⚠ You already own cert 12345678 (sold 3/2/26)    │
├────────────────────────────────────────────────────────────┤
│  Language [EN ▾]  Location [glass ▾]  Value [$_______]     │
│                                    [ Cancel ]  [ Add ]     │
└────────────────────────────────────────────────────────────┘
```

**Decision 15 is structural, not cosmetic: condition and grade are never both rendered.**
They are alternatives — a graded card's condition is its grade. Showing both invites
filling both, and the backend (T13) 422s a raw leg carrying graded fields, so a form that
offers both would generate a rejection the operator cannot explain.

**The cert warning is a warning with override, never a gate.** Debounced
`GET /admin/slabs/certs/{cert}`; on a hit, render the notice and **leave Add enabled**. A
slab sold and bought back is legitimate re-entry (RFC 0009).

**Manual entry is a disclosure, put away by default, and it stays open across adds.**
Exactly `/admin/slabs`' "Manual entry" behaviour — intake is a batch workflow and a
control that closes after every add fights the person using it. In manual mode the card
identity block is replaced by editable name / set / number fields and `card_id` is `null`.

> **A manual entry can only ever be RAW.** T13 422s a graded leg with no `card_id`,
> because graded pricing joins on `(card_id, company, grade)`. So opening manual entry
> forces the kind toggle to Raw and disables Graded, **with a one-line reason next to
> it** — a disabled control with no explanation is the thing this codebase deletes.

### Money and dates

`MoneyInput` for Value, backed by `parseMoney`. **Never `parseFloat`** — `parseFloat("1,300")`
is `1` and is not `NaN`. **Never `type="number"`** — it refuses the comma the owner types.
`parseMoney('0')` is `0`, so test `=== null`, never falsiness: a free throw-in card is real
at a buy table.

## RED — write these first, show the failing output, then STOP

`DealCardRow.test.tsx`:

```tsx
describe('DealCardRow', () => {
  it('shows image, name and price together', () => {
    render(<DealCardRow card={card({ name: 'Charizard', image: 'https://i/1.png',
                                     price: '120.00' })} onAdd={vi.fn()} />)
    expect(screen.getByRole('img', { name: /charizard/i })).toBeInTheDocument()
    expect(screen.getByText('Charizard')).toBeInTheDocument()
    expect(screen.getByText('$120.00')).toBeInTheDocument()
  })

  it('reveals nothing on hover', async () => {
    // The owner's complaint. Hover may change colour; it may not carry information.
    const user = userEvent.setup({ delay: null })
    render(<DealCardRow card={card({ name: 'Charizard' })} onAdd={vi.fn()} />)
    const before = screen.getByRole('img', { name: /charizard/i })
    await user.hover(screen.getByText('Charizard'))
    expect(screen.getByRole('img', { name: /charizard/i })).toBe(before)
  })

  it('renders a placeholder rather than collapsing when art is missing', () => {
    render(<DealCardRow card={card({ image: null })} onAdd={vi.fn()} />)
    expect(screen.getByTestId('card-image-placeholder')).toBeInTheDocument()
  })

  it('renders an absent price as a dash, never as zero', () => {
    render(<DealCardRow card={card({ price: null })} onAdd={vi.fn()} />)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
  })

  it('names the card in its action label', () => {
    render(<DealCardRow card={card({ name: 'Charizard' })} onAdd={vi.fn()} />)
    expect(screen.getByRole('button', { name: /charizard/i })).toBeInTheDocument()
  })
})
```

`DealSearchPanel.test.tsx`:

```tsx
describe('DealSearchPanel', () => {
  beforeEach(() => { apiGet.mockReset() })   // never clearAllMocks

  it('hides the source toggle outside trade mode', () => {
    // Absent, not disabled. A control settable one way is noise.
    render(<DealSearchPanel mode="buy" {...noop} />)
    expect(screen.queryByRole('radio', { name: /inventory/i })).not.toBeInTheDocument()
  })

  it('shows the source toggle in trade mode', () => {
    render(<DealSearchPanel mode="trade" {...noop} />)
    expect(screen.getByRole('radio', { name: /inventory/i })).toBeInTheDocument()
  })

  it('locks buy to the catalog and sell to inventory', () => {
    expect(sourceForMode('buy')).toBe('catalog')
    expect(sourceForMode('sell')).toBe('inventory')
    expect(sourceForMode('trade')).toBe('both')
  })

  it('searches available inventory when the source is inventory', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealSearchPanel mode="sell" source="inventory" {...noop} />)
    await user.type(screen.getByLabelText(/name/i), 'Charizard')
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith(
      '/inventory/search', expect.objectContaining({ status: 'available' })))
  })

  it('shows an image on every inventory result', async () => {
    // This picker has NO image today (trade/page.tsx:713).
    const user = userEvent.setup({ delay: null })
    mockInventory([{ item_id: 'a', display_name: 'Charizard', card_id: 'en:base1-4',
                     current_market_value: '120.00' }])
    render(<DealSearchPanel mode="sell" source="inventory" {...noop} />)
    await user.type(screen.getByLabelText(/name/i), 'Char')
    expect(await screen.findByRole('img', { name: /charizard/i })).toBeInTheDocument()
  })

  it('offers manual entry before any search has run', () => {
    render(<DealSearchPanel mode="buy" onManualEntry={vi.fn()} {...noop} />)
    expect(screen.getByRole('button', { name: /manual/i })).toBeInTheDocument()
  })
})
```

`IncomingCardForm.test.tsx`:

```tsx
describe('IncomingCardForm', () => {
  it('never shows condition and grade at the same time', async () => {
    // Decision 15. They are alternatives; a graded card's condition IS its grade.
    const user = userEvent.setup({ delay: null })
    render(<IncomingCardForm card={card()} onAdd={vi.fn()} onCancel={vi.fn()} />)

    expect(screen.getByLabelText(/condition/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^grade$/i)).not.toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /graded/i }))

    expect(screen.queryByLabelText(/condition/i)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/^grade$/i)).toBeInTheDocument()
  })

  it('emits a graded leg with the cert fields', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card({ card_id: 'en:base1-4' })} onAdd={onAdd}
                             onCancel={vi.fn()} />)

    await user.click(screen.getByRole('radio', { name: /graded/i }))
    await user.selectOptions(screen.getByLabelText(/company/i), 'PSA')
    await user.type(screen.getByLabelText(/^grade$/i), '10')
    await user.type(screen.getByLabelText(/cert/i), '12345678')
    await user.type(screen.getByLabelText(/value/i), '400')
    await user.click(screen.getByRole('button', { name: /^add$/i }))

    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'graded', company: 'PSA', grade: 10, cert_number: '12345678',
      card_id: 'en:base1-4',
    }))
  })

  it('accepts a value typed with a comma', async () => {
    // parseFloat("1,300") is 1 and is not NaN — a silent $1,299 loss.
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} />)
    await user.type(screen.getByLabelText(/value/i), '1,300')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ agreed_value: 1300 }))
  })

  it('accepts a free card', async () => {
    // parseMoney('0') is 0, not null. A throw-in is real at a buy table.
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} />)
    await user.type(screen.getByLabelText(/value/i), '0')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ agreed_value: 0 }))
  })

  it('warns on an already-owned cert without blocking the add', async () => {
    // Warning with override, never a gate: a slab sold and bought back is legitimate.
    const user = userEvent.setup({ delay: null })
    mockCertOwned('12345678')
    render(<IncomingCardForm card={card()} onAdd={vi.fn()} onCancel={vi.fn()} />)
    await user.click(screen.getByRole('radio', { name: /graded/i }))
    await user.type(screen.getByLabelText(/cert/i), '12345678')

    expect(await screen.findByText(/already own/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^add$/i })).toBeEnabled()
  })

  it('forces manual entry to raw, and says why', async () => {
    // T13 422s a graded leg with no card_id — graded pricing joins on card_id.
    render(<IncomingCardForm card={null} onAdd={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.getByRole('radio', { name: /graded/i })).toBeDisabled()
    expect(screen.getByText(/needs a catalog card/i)).toBeInTheDocument()
  })
})
```

**Run, show the owner the failures, and WAIT.**

```bash
cd frontend && npx vitest run components/admin/deal
```

## Watch for

- **`mockReset()` in `beforeEach`, never `clearAllMocks()`**, and
  `userEvent.setup({ delay: null })` in every test that types.
- **Compose T11's `CardSearchPanel`; do not fork it.** A sixth local catalog search is
  exactly what decision 6 exists to prevent.
- **`vault-field` on every control.** The admin theme is dark; an unstyled `<select>`
  renders light-green-on-white.
- **Keep the debounce and the batched image lookup.** Never one request per row.
- Location options come from `useLocations()`; **never hardcode a location list.**

## Done means

1. all three component test files pass, output shown;
2. `npm run lint --workspace=frontend` clean;
3. `progress.md` updated with the exact `IncomingLeg` shape T15 will emit.

Do not run the full suite. Do not merge. Do not push.
