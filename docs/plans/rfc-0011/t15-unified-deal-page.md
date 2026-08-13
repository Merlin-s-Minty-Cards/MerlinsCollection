# T15 — One page, three modes

**RFC:** 0011 §I · **Layer:** frontend · **Depends on:** T13, T14 · **Blocks:** T16
**Owner ask:** *"I want to combine them all into one big tab, with a toggle between
buying, selling, or trading. There needs to be a coming in and going out section where you
can see the cards going in or going out, which are shown or hidden depending on the
buy/sell/trade toggle. Customer view, cost basis mode, cash components, balance, profit,
and date should all stay."*

## Files

- **Rewrite:** `frontend/app/(admin)/admin/trade/page.tsx` (currently 914 lines)
- **Create:** `frontend/lib/deal-session.ts` — the per-mode API adapter
- **Create:** `frontend/components/admin/deal/DealSummary.tsx` — the summary rail
- **Test:** `frontend/app/(admin)/admin/trade/__tests__/page.test.tsx`,
  `frontend/lib/__tests__/deal-session.test.ts`

**Not in this task:** deleting `/admin/buy` and `/admin/sell`, the sidebar, and the
dashboard quick actions. That is T16, so this page can be built and reviewed while the old
routes still work.

## Interfaces

**Consumes:** T14's `DealSearchPanel`, `IncomingCardForm`, `DealCardRow`, `sourceForMode`,
`IncomingLeg`. T13's graded incoming keys.

**Produces:**

```ts
// lib/deal-session.ts — the ONLY place that knows which API a mode talks to.
export interface DealSessionApi {
  create(): Promise<string>
  addIncoming(id: string, leg: IncomingLeg): Promise<void>
  addOutgoing(id: string, item: InventoryItem, value: number): Promise<void>
  removeIncoming(id: string, index: number): Promise<void>
  removeOutgoing(id: string, index: number): Promise<void>
  setCash(id: string, components: CashComponent[]): Promise<void>
  confirm(id: string, meta: ConfirmMeta): Promise<ConfirmResult>
  supports: { incoming: boolean; outgoing: boolean; costBasisMode: boolean }
}
export function sessionApiFor(mode: DealMode, api: AdminApi): DealSessionApi
```

## Design

### Layout — full width inside the admin shell

Decision 12. The sidebar is untouched; "full width" means the page's own content column.

```
┌──────────────────────────────────────────────────────────────────┐
│  ( BUY ) ( SELL ) ( TRADE )        [Customer view]  [Date ▾]     │
├──────────────────────────────────────────────────────────────────┤
│  DealSearchPanel  (T14, full width)                              │
├─────────────────────────┬──────────────────────┬─────────────────┤
│  COMING IN          (2) │  GOING OUT       (2) │   BALANCE       │
│  ┌────────────────────┐ │ ┌──────────────────┐ │   ┌───────────┐ │
│  │ [img] Name  $12 ×  │ │ │ [img] Name $40 × │ │   │  +$35.00  │ │
│  │ [img] Name   $8 ×  │ │ │ [img] Name $15 × │ │   └───────────┘ │
│  └────────────────────┘ │ └──────────────────┘ │   In     $20.00 │
│  In              $20.00 │ Out           $55.00 │   Out    $55.00 │
│                         │                      │   Cash   + Add  │
│                         │                      │   Profit $12.00 │
│                         │                      │   Basis  [▾]    │
│                         │                      │   [  Confirm  ] │
└─────────────────────────┴──────────────────────┴─────────────────┘
```

**The balance is the hero, and that is a deliberate choice.** Every path through this
workflow ends in one number: what changes hands. It is the largest figure on screen, it
never scrolls out of view, and it carries its sign. Everything around it stays quiet —
this is the one place boldness is spent.

Two columns mirror the two piles of cards physically on the table. Coming In left, Going
Out right, and the summary is the fulcrum between them.

**Figures are `font-mono`**, which the codebase already does — digits align, so a column of
money is scannable at arm's length rather than read one row at a time.

**Motion, narrowly:** a row entering Coming In or Going Out gets a brief highlight so a
fast add is visibly confirmed. Nothing else animates, and it is wrapped in
`prefers-reduced-motion`. Confirming an add at speed is a real need; ambient movement is
not.

### The mode toggle

```tsx
type DealMode = 'buy' | 'sell' | 'trade'
```

Read from `?mode=`, defaulting to `trade` (the route's own name). Changing it calls
`router.replace` so the URL follows — that is what makes the toggle bookmarkable and lets
T16 point three dashboard quick actions at one page.

| mode | Coming In | Going Out | search source | session API | cost-basis mode |
|---|---|---|---|---|---|
| buy | shown | hidden | catalog (locked) | `/purchases` | hidden |
| sell | hidden | shown | inventory (locked) | `/sales` | hidden |
| trade | shown | shown | toggle | `/trades` | shown |

**A hidden column is not rendered, not collapsed to zero width.** An empty pane labelled
"Going Out" in Buy mode reads as broken.

> **Switching mode with a non-empty session MUST confirm first.** A started session belongs
> to one API and there is no migration between them, so the toggle abandons it. Silently
> discarding a half-built five-card buy is the kind of loss this codebase writes confirm
> dialogs for. An empty session switches with no dialog — nothing is lost.

### `lib/deal-session.ts` — one adapter, three APIs

Decision 16 keeps `purchases.py`, `sales.py` and `trades.py` separate. This module is the
**only** place that knows which one a mode talks to; the page never branches on mode to
choose a URL.

```ts
/**
 * Which session API a mode drives.
 *
 * The three endpoints stay separate (RFC 0011 decision 16) because they are the
 * highest-risk money paths in the repo — RFC 0010 T0 exists because a partial write in
 * one of them created real inventory and then reported "Nothing was created". Merging
 * the UI is a large enough change on its own; this adapter is what keeps the page from
 * growing a `if (mode === 'buy')` at every call site, which is how three code paths
 * come back in disguise.
 */
```

`supports` drives what renders, so the page asks the adapter rather than restating the
table above in JSX.

### What stays, and where

The owner named six things that must survive. Each renders where it means something:

| | buy | sell | trade | note |
|---|---|---|---|---|
| Customer view | ✓ | ✓ | ✓ | hides cost basis and profit |
| Cost-basis mode | | | ✓ | a trade concept — nothing to transfer on a buy |
| Cash components | ✓ | ✓ | ✓ | |
| Balance | ✓ | ✓ | ✓ | |
| Profit | | ✓ | ✓ | a pure buy has no profit yet |
| Date | ✓ | ✓ | ✓ | `todayLocal()`, never `toISOString()` |

**Customer view is a real mode change, not a checkbox that greys two numbers.** With it on
the customer is reading the screen: cost basis and profit are gone from the DOM (not
visually hidden — `display:none` still copies and still reads aloud), and the balance grows.

### Dates

`todayLocal()` for the default. **Never `toISOString().split('T')[0]`** — that is the UTC
date, so after 5pm Pacific every new transaction defaulted to *tomorrow*, on exactly the
evening shows this business sells at. Render with `formatISODate`; never `new Date()` on a
date-only string.

## RED — write these first, show the failing output, then STOP

`lib/__tests__/deal-session.test.ts`:

```ts
describe('sessionApiFor', () => {
  it('routes each mode to its own API', () => {
    expect(sessionApiFor('buy', api).supports).toEqual(
      { incoming: true, outgoing: false, costBasisMode: false })
    expect(sessionApiFor('sell', api).supports).toEqual(
      { incoming: false, outgoing: true, costBasisMode: false })
    expect(sessionApiFor('trade', api).supports).toEqual(
      { incoming: true, outgoing: true, costBasisMode: true })
  })

  it('creates a buy session against the purchases API', async () => {
    await sessionApiFor('buy', api).create()
    expect(api.post).toHaveBeenCalledWith('/purchases', expect.anything())
  })

  it('creates a sell session against the sales API', async () => {
    await sessionApiFor('sell', api).create()
    expect(api.post).toHaveBeenCalledWith('/sales', expect.anything())
  })

  it('sends graded incoming fields through to the trade API', async () => {
    await sessionApiFor('trade', api).addIncoming('t1', {
      card_id: 'en:base1-4', name: 'Charizard', agreed_value: 400,
      kind: 'graded', company: 'PSA', grade: 10, cert_number: '12345678',
      language: 'EN', location: 'glass',
    })
    expect(api.post).toHaveBeenCalledWith('/trades/t1/incoming',
      expect.objectContaining({ kind: 'graded', cert_number: '12345678' }))
  })
})
```

`app/(admin)/admin/trade/__tests__/page.test.tsx`:

```tsx
import '@/lib/__tests__/_timezone'   // a date renders here

describe('the unified deal page', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('defaults to trade mode and shows both columns', async () => {
    render(<DealPage />)
    expect(await screen.findByRole('heading', { name: /coming in/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /going out/i })).toBeInTheDocument()
  })

  it('hides Going Out in buy mode', async () => {
    // Not rendered, not collapsed. An empty pane labelled "Going Out" reads as broken.
    mockSearchParams({ mode: 'buy' })
    render(<DealPage />)
    expect(await screen.findByRole('heading', { name: /coming in/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /going out/i })).not.toBeInTheDocument()
  })

  it('hides Coming In in sell mode', async () => {
    mockSearchParams({ mode: 'sell' })
    render(<DealPage />)
    expect(await screen.findByRole('heading', { name: /going out/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /coming in/i })).not.toBeInTheDocument()
  })

  it('puts the mode in the URL when toggled', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await user.click(screen.getByRole('radio', { name: /^buy$/i }))
    expect(replace).toHaveBeenCalledWith(expect.stringContaining('mode=buy'))
  })

  it('confirms before abandoning a non-empty session', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await addOneIncoming(user)

    await user.click(screen.getByRole('radio', { name: /^sell$/i }))

    expect(await screen.findByRole('dialog')).toHaveTextContent(/discard/i)
  })

  it('switches modes without a dialog when nothing is staged', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await user.click(screen.getByRole('radio', { name: /^sell$/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows image, name and price on every staged row', async () => {
    // The owner's complaint covers staged rows, not just search results.
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await addOneIncoming(user, { name: 'Charizard', price: '120.00' })

    const staged = within(screen.getByTestId('coming-in'))
    expect(staged.getByRole('img', { name: /charizard/i })).toBeInTheDocument()
    expect(staged.getByText('Charizard')).toBeInTheDocument()
    expect(staged.getByText('$120.00')).toBeInTheDocument()
  })

  it('removes cost basis and profit from the DOM in customer view', async () => {
    // Not visually hidden: display:none still copies and still reads aloud.
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await addOneIncoming(user)
    await user.click(screen.getByRole('switch', { name: /customer view/i }))

    expect(screen.queryByText(/cost basis/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/profit/i)).not.toBeInTheDocument()
  })

  it('shows cost-basis mode only in trade', async () => {
    mockSearchParams({ mode: 'buy' })
    render(<DealPage />)
    expect(screen.queryByLabelText(/basis/i)).not.toBeInTheDocument()
  })

  it('defaults the date to the LOCAL today', async () => {
    // toISOString() gives the UTC date — after 5pm Pacific that is tomorrow, on
    // exactly the evening shows this business sells at.
    vi.setSystemTime(new Date('2026-08-13T23:30:00Z'))   // 4:30pm PDT
    render(<DealPage />)
    expect(await screen.findByDisplayValue('2026-08-13')).toBeInTheDocument()
  })

  it('renders a net total for a mixed-direction trade', async () => {
    // Summing magnitudes reports a $50-for-$30 trade as $80 — a number that exists
    // nowhere. Same rule TransactionGroups already follows.
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await addOneIncoming(user, { price: '30.00' })
    await addOneOutgoing(user, { price: '50.00' })

    expect(within(screen.getByTestId('deal-balance')).getByText('+$20.00'))
      .toBeInTheDocument()
  })
})
```

**Run, show the owner the failures, and WAIT.**

```bash
cd frontend && npx vitest run "app/(admin)/admin/trade" lib/__tests__/deal-session.test.ts
```

## Watch for

- **Do not touch `purchases.py`, `sales.py` or `trades.py`** beyond what T13 already did.
  Decision 16 — if a money bug appears, it must have one possible home.
- **The page never branches on mode to pick a URL.** That is `deal-session.ts`'s job; a
  `if (mode === 'buy')` at a call site is three code paths coming back in disguise.
- **`_timezone.ts` and `vi.useFakeTimers({ toFake: ['Date'] })`** — never full fake timers,
  which deadlock `waitFor`.
- **The old page's trade logic is worth reading before deleting it** — `trade-basis.ts`,
  the `outDrafts` map (a controlled `MoneyInput` needs to own its text so a half-typed
  `"1,"` survives a render) and the cash-component sync are all solved problems. Carry
  them over rather than rediscovering them.
- **This page is ~900 lines today and should not become 1,200.** Extract the summary rail
  and the two staged columns; keep the page file to composition and state.

## Done means

1. both test files pass, output shown;
2. `npm run lint --workspace=frontend` clean;
3. by hand, all three modes: stage a card, see image + name + price on the staged row,
   check the balance, confirm; and in trade mode add a graded incoming card end to end
   (T13's path) and verify the committed item is `kind: "graded"` with its cert;
4. `progress.md` updated.

Do not run the full suite. Do not merge. Do not push.
