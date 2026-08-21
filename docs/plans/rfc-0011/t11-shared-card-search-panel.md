# T11 — One shared card search, and manual entry that is always there

**RFC:** 0011 §G · **Layer:** frontend + a small backend fix · **Depends on:** — · **Blocks:** T14

> ## ⚠ RE-SCOPED when RFC 0011 Part 2 landed — read this before starting
>
> This doc was written when Buy, Sell and Trade were three pages. Part 2 merges them:
> **`/admin/buy` and `/admin/sell` are deleted (T16) and `/admin/trade` is rebuilt (T15).**
>
> So **do NOT adopt `CardSearchPanel` in Buy or Trade.** Those adoptions are struck from
> the list below. Build the component and adopt it in **Slabs intake, Triage re-point,
> Market**, and **Unmatched** if T8 has landed. T14 then *composes* this component for the
> new deal page's catalog source rather than duplicating it — which is the whole point of
> decision 6.
>
> The "manual entry is a permanent control" requirement is unchanged and still applies to
> Slabs here; T14 carries it for the deal page.
>
> Everything else in this doc — the three search fields, the backend number
> normalization, the props, the tests — stands as written.

**Owner report, 2026-08-13:** *"There is no way to manually enter a card for buys, trades,
etc, when you search for a Pokemon that exists, but there is not correct catalog card.
There should always be an option for manual entry, not just when the catalog search
returns no results. I also think that this same search feature could really benefit from
having more ways to search like also entering the card number along with the name. Maybe
even adding a place to enter a set too (this should be a searchable dropdown menu)."*

## The backend already takes all three fields

`GET /admin/market/search` accepts **`name`, `set_id` and `number`**
(`routers/admin/market.py:83-88`), and the `set_id` branch uses the GSI rather than the
catalog scan. All five frontend callers send `name` alone:

| caller | line | fate |
|---|---|---|
| Buy | `admin/buy/page.tsx:94` | deleted by T16 |
| Market | `admin/market/page.tsx:266` | **adopt here** |
| Trade | `admin/trade/page.tsx:176` | rebuilt by T15, which composes this |
| Triage re-point | `admin/triage/page.tsx:581` | **adopt here** |
| Slabs intake | `components/admin/slabs/SlabEntryForm.tsx:93` | **adopt here** |

So this is a frontend consolidation plus **one** backend fix.

## Files

- **Create:** `frontend/components/admin/shared/CardSearchPanel.tsx`
- **Create:** `frontend/components/admin/shared/__tests__/CardSearchPanel.test.tsx`
- **Modify:** the three callers marked "adopt here" above (Market, Triage, Slabs)
- **Modify:** `backend/src/merlins_collection/routers/admin/market.py` — normalized number
  matching (line 114-116)
- **Test:** `backend/tests/routers/test_admin_market.py`, plus the Market, Triage and
  Slabs page test files

## Interfaces

**Produces:**

```tsx
interface CardSearchPanelProps {
  onSelect: (card: PickerCard) => void
  /** Rendered as a permanent control. Omit on surfaces where manual entry is meaningless. */
  onManualEntry?: () => void
  /** Seeds the name box — used by the Unmatched queue's "Search catalog" action (T8). */
  initialName?: string
  initialNumber?: string
  autoFocus?: boolean
}
export default function CardSearchPanel(props: CardSearchPanelProps): JSX.Element
```

## Design

### The backend fix: number matching is exact today

```python
    if number is not None:
        cards = [c for c in cards if c.number == number]
```

so `182` misses a card stored as `182/167`, and `181.0` (an Excel artifact the owner's
sheets really produce) misses everything. Normalize **both sides** through the helpers
that already solve this for the importer:

```python
    if number is not None:
        # Both sides normalized, exactly as `_match_card` does — an Excel float artifact
        # ("181.0"), a slash form ("182/167") and a bare "182" all have to find the same
        # card. Hand-typed at a buy table, all three get typed.
        wanted = number_keys(normalize_number(number))
        cards = [c for c in cards if number_keys(normalize_number(c.number)) & wanted]
```

`normalize_number` / `number_keys` come from `services/spreadsheet_import`. If importing
from there into a router reads wrong, move both into `services/card_text.py` and re-export
— **do not write a second normalizer.**

### The panel

Three inputs in a row that collapses on narrow viewports. Every control gets
`vault-field` (CLAUDE.md — the admin theme is dark, and an unstyled `<select>` renders
light-green-on-white).

```tsx
<div className="grid grid-cols-1 sm:grid-cols-[2fr_1fr_2fr] gap-2">
  <SearchInput ariaLabel="Card name" value={name} onChange={setName}
               placeholder="Search catalog or type a name…" />
  <input aria-label="Card number" value={number} onChange={(e) => setNumber(e.target.value)}
         placeholder="Card #"
         className="vault-field px-2.5 py-1.5 rounded-lg text-xs w-full" />
  <SetCombobox sets={toComboboxSets(catalogSets)} value={setId} onChange={setSetId}
               inputId="card-search-set" ariaLabel="Set"
               placeholder="All sets" emptyLabel="All sets"
               className="vault-field px-2.5 py-1.5 rounded-lg text-xs w-full" />
</div>
```

`SetCombobox` is the searchable dropdown the owner asked for — it already exists and
already backs the inventory Set filter, fed by `useCatalogSets()`. **Do not build a second
one.**

**Any one field alone is a valid search.** Set + number with no name is how you find a
card whose name you cannot read — the JP case. Only fire when at least one field is
non-empty; an empty panel must not request the whole catalog.

Results render through **`CardPickerRow`** — name, image and price, the absolute owner
rule from 2026-08-10. Keep the existing 300ms debounce; **never one request per row.**

### Manual entry becomes a permanent control

```tsx
{/* A permanent control, not a consolation prize. The owner's report: they search for a
    Pokemon that EXISTS, find it, and the catalog row is the wrong printing — at which
    point a button that only appears when the search returns nothing is unreachable. */}
{onManualEntry && (
  <button type="button" onClick={onManualEntry}
          className="text-[11px] text-pine-400 hover:text-mint underline underline-offset-2">
    Enter manually instead
  </button>
)}
```

Rendered **whenever `onManualEntry` is provided** — before any search runs, while results
are showing, and when there are none.

| surface | `onManualEntry` | why |
|---|---|---|
| ~~Buy~~ | — | **struck.** Deleted by T16; T14 carries manual entry for the merged page |
| ~~Trade~~ | — | **struck.** Rebuilt by T15, which composes this component |
| Slabs intake | yes | already has a free-text fallback; this makes it reachable up front |
| Triage re-point | **no** | must select a genuine catalog row; its "no match" answer is T6's park action |
| Market | **no** | a browse tool; there is nothing to create |
| Unmatched (T8) | **no** | same as re-point |

The prop stays on the component exactly as specified — T14 is the caller that passes it.

## RED — write these first, show the failing output, then STOP

Backend, in `backend/tests/routers/test_admin_market.py`:

```python
@pytest.mark.parametrize("typed", ["182", "182/167", "182.0"])
def test_number_search_normalizes_both_sides(admin_client, catalog, typed):
    """All three get typed at a buy table. Excel really does produce "181.0"."""
    catalog.add(card_id="en:base1-182", name="Rayquaza", number="182/167")

    body = admin_client.get("/admin/market/search", params={"number": typed}).json()

    assert [c["card_id"] for c in body["items"]] == ["en:base1-182"]


def test_number_and_name_combine(admin_client, catalog):
    catalog.add(card_id="en:a-4", name="Charizard", number="4")
    catalog.add(card_id="en:b-4", name="Blastoise", number="4")

    body = admin_client.get("/admin/market/search",
                            params={"name": "Charizard", "number": "4"}).json()

    assert [c["card_id"] for c in body["items"]] == ["en:a-4"]
```

Frontend, `CardSearchPanel.test.tsx`:

```tsx
describe('CardSearchPanel', () => {
  beforeEach(() => { apiGet.mockReset() })

  it('sends name, number and set together', async () => {
    const user = userEvent.setup({ delay: null })   // 3 fields typed; never the default
    render(<CardSearchPanel onSelect={vi.fn()} />)

    await user.type(screen.getByLabelText('Card name'), 'Charizard')
    await user.type(screen.getByLabelText('Card number'), '4')
    await user.selectOptions(screen.getByLabelText('Set'), 'en:base1')

    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/market/search',
      expect.objectContaining({ name: 'Charizard', number: '4', set_id: 'en:base1' })))
  })

  it('searches on the number alone', async () => {
    // Set + number with no name is how you find a card whose name you cannot read.
    const user = userEvent.setup({ delay: null })
    render(<CardSearchPanel onSelect={vi.fn()} />)

    await user.type(screen.getByLabelText('Card number'), '182')

    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/market/search',
      expect.objectContaining({ number: '182' })))
  })

  it('does not request the whole catalog when every field is empty', async () => {
    render(<CardSearchPanel onSelect={vi.fn()} />)
    await new Promise((r) => setTimeout(r, 400))     // past the 300ms debounce
    expect(apiGet).not.toHaveBeenCalled()
  })

  it('shows manual entry before any search has run', async () => {
    // The owner's actual complaint: it only appeared after a failed search.
    render(<CardSearchPanel onSelect={vi.fn()} onManualEntry={vi.fn()} />)
    expect(screen.getByRole('button', { name: /enter manually/i })).toBeInTheDocument()
  })

  it('still shows manual entry while results are on screen', async () => {
    const user = userEvent.setup({ delay: null })
    mockResults([card({ name: 'Charizard' })])
    render(<CardSearchPanel onSelect={vi.fn()} onManualEntry={vi.fn()} />)

    await user.type(screen.getByLabelText('Card name'), 'Charizard')
    await screen.findByText('Charizard')

    expect(screen.getByRole('button', { name: /enter manually/i })).toBeInTheDocument()
  })

  it('omits manual entry where it is meaningless', () => {
    render(<CardSearchPanel onSelect={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /enter manually/i })).not.toBeInTheDocument()
  })

  it('shows name, image and price on every result', async () => {
    const user = userEvent.setup({ delay: null })
    mockResults([card({ name: 'Charizard', images: { small: 'https://img/1.png' },
                        display_price: '100.00' })])
    render(<CardSearchPanel onSelect={vi.fn()} />)

    await user.type(screen.getByLabelText('Card name'), 'Charizard')

    expect(await screen.findByRole('img', { name: /charizard/i })).toBeInTheDocument()
    expect(screen.getByText('$100.00')).toBeInTheDocument()
  })
})
```

And on Slabs intake, the one that pins the owner's report directly on a surface that
survives Part 2:

```tsx
it('offers manual entry before the admin has searched for anything', async () => {
  render(<SlabEntryForm {...props} />)
  expect(await screen.findByRole('button', { name: /manual/i })).toBeInTheDocument()
})
```

**Run, show the owner the failures, and WAIT.**

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/test_admin_market.py -q --tb=short
cd frontend && npx vitest run components/admin/shared/__tests__/CardSearchPanel.test.tsx
```

## Watch for

- **Adopt one caller at a time and run that page's tests each time.** Three swaps in one
  commit is three ways to be wrong at once. Slabs first — it is the smallest surface.
  (Buy WAS the reference row CLAUDE.md points at, `buy/page.tsx:418-440`; read it for the
  row layout before deleting it in T16, then let it go.)
- **`min-w-0 flex-1` + `truncate` on the text block, and the image neither shrinks nor
  grows.** CLAUDE.md is explicit that adding an image is not finished when it renders:
  a long name must shrink instead of shoving the art, and rows must not change height as
  images load, or the list jumps under the cursor mid-click.
- **Keep the debounce and the batching.** One request per row is the failure this
  component exists to prevent.
- **Do not change Slabs' `CertInput`.** Its `onEnter`-advances-focus behavior and its
  `\r\n` stripping are what make wedge scanning work, and breaking either fails silently
  until someone is standing at a table with a scanner.
- **Trade sends `inForm.name` and expects `IncomingCatalogCard`** — check its result type
  before swapping, it is not identical to `PickerCard`.

## Done means

1. the backend market test and `CardSearchPanel.test.tsx` pass, output shown;
2. each adopted page's own test file passes — Slabs, Triage, Market;
   **and if T8 has already landed**, swap `/admin/unmatched`'s "Search catalog" dialog
   onto this panel too (with `onManualEntry` omitted) and clear that row from
   `follow-ups.md`;
3. `ruff check backend/src` and `npm run lint --workspace=frontend` clean;
4. by hand on `/admin/buy`: manual entry is clickable before typing anything; a search by
   number alone finds a card; a name + set search narrows correctly;
5. `progress.md` updated, listing which callers were adopted.

Do not run the full suite. Do not merge. Do not push.
