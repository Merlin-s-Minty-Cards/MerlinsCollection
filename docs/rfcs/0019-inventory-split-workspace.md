# RFC 0019: Inventory Split Workspace

Status: Draft
Author: Claude (session on branch `Inventory-Chat-Design`)
Date: 2026-08-26

## Summary

Replace `/inventory`'s current layout — a page-level Chat/Filter toggle above
a single stacked panel, with Chat mode's results rendered in a `fixed`,
right-anchored `DisplayPanel` overlay (dock/fullscreen modes, mouse-drag
resize) — with a **Split Workspace**: a resizable two-column layout living
entirely in normal document flow. The left pane holds either the chat
interface or the filter form, switchable via a segmented toggle now living in
the pane's own header; the right pane is one persistent card grid shared by
both modes. The left pane's chat-mode header also gains a **New chat** button
and a **History** icon button (lucide-react icons, no emoji), both scoped to
what's real today.

## Motivation

The prior sidebar redesign shipped and was rejected on live testing. Owner
report, verbatim: *"the sidebar is hard to scale in and out, and my cursor
starts highlighting stuff as I move it, plus cards begin overlapping each
other when the sidebar is scaled thin enough... the sidebar shouldn't just
cover the existing elements of the website, it should push the other elements
to the side of the screen... it also seems like the sidebar is slightly
overlapping the nav bar."*

Every one of those is a consequence of the same root cause: `DisplayPanel`
was `fixed`-positioned, screen-edge-anchored, and owned its own card grid
independent of the page's layout. Patching each symptom individually (a
`userSelect` guard here, a `z-index` fix there) would leave the structural
cause in place. This RFC removes `fixed` positioning from the panel
entirely — the two columns are ordinary flex children, so the browser's own
layout engine is what pushes content aside and clears the navbar, rather than
a pixel constant (`NAVBAR_HEIGHT_PX`) trying to reproduce it.

Three full-page mockups (Split Workspace / Binder Gallery / Command Bar) were
built and reviewed live by the owner, who chose Split Workspace with one
addition: the left pane must toggle between Chat and Filter (not be
chat-only), with that toggle and two new action buttons in the pane's own
header rather than the page level.

## Detailed Design

### Component tree

```
app/(auth)/inventory/page.tsx
└── SplitWorkspace.tsx                    (NEW — replaces InventoryWorkspace.tsx)
    ├── header row
    │   ├── ModeToggle.tsx                (UNCHANGED, reused as-is)
    │   └── (mode === 'chat' only)
    │       ├── "+ New" button            (NEW, inline in SplitWorkspace)
    │       └── HistoryMenu.tsx           (NEW)
    └── flex row
        ├── left pane, style={{ width: leftWidth }}
        │   ├── div[hidden={mode!=='chat'}]
        │   │   └── ChatPanel.tsx         (CHANGED — forwardRef + onDisplayChange)
        │   └── div[hidden={mode!=='filter'}]
        │       └── FilterPanel.tsx       (CHANGED — onResultsChange, no inline grid)
        ├── drag handle                   (NEW, inline in SplitWorkspace)
        └── right pane, className="flex-1 min-w-0"
            └── ResultsPane.tsx           (NEW)
```

Retired entirely: `InventoryWorkspace.tsx`, `DisplayPanel.tsx`,
`CardGrid.tsx`, `CardTile.tsx`, and their test files. Confirmed via `grep`
this session that none of the four have any consumer outside the inventory
feature (`admin/inventory` is a separate, unrelated page). `CardPresentation.tsx`
and `CARD_GRID_CLASS` are unchanged — both new and surviving old code render
through it.

### Why both panels stay mounted

`SplitWorkspace` keeps the existing `hidden`-attribute pattern
`InventoryWorkspace` already used (both `ChatPanel` and `FilterPanel` always
mounted; the inactive one is `hidden`, not unmounted). This is a deliberate
carry-forward, not an oversight: unmounting on tab-switch would drop the
user's in-progress conversation or filter selections the moment they check
the other mode. The WAI-ARIA tabs semantics already built into `ModeToggle`
(`role="tab"`, `aria-controls`) assume exactly this shape.

### Why two independent view-state slots, not one

`SplitWorkspace` holds `chatView` and `filterView` as two separate pieces of
state, each written only by that mode's own callback
(`onDisplayChange`/`onResultsChange`). `ResultsPane` always renders
`mode === 'chat' ? chatView : filterView`. This is what prevents a
backgrounded pane from ever clobbering the visible one: if a fetch that
started before a mode switch resolves after it, it writes into its own slot,
which the visible mode isn't reading. A single shared "last update wins"
slot would reintroduce exactly the kind of race this avoids for free.

### Resize mechanics

Delta-based, not viewport-edge-based (the old `DisplayPanel` used
`window.innerWidth - event.clientX` because it was anchored to the screen's
right edge; the new left pane isn't anchored to any screen edge, so that
formula no longer applies):

```ts
const MIN_LEFT_WIDTH = 320
const MAX_LEFT_WIDTH = 720
const DEFAULT_LEFT_WIDTH = 420

// on handle mousedown:
dragStart.current = { x: event.clientX, width: leftWidth }
document.body.style.userSelect = 'none'   // <-- the explicit fix for the
                                           //     reported cursor text-select
                                           //     bleed; the old DisplayPanel
                                           //     never guarded against this.

// on window mousemove, while dragging:
const delta = event.clientX - dragStart.current.x
setLeftWidth(clamp(dragStart.current.width + delta, MIN_LEFT_WIDTH, MAX_LEFT_WIDTH))

// on window mouseup:
document.body.style.userSelect = ''
```

Mouse events, not Pointer events — carried forward from `DisplayPanel`'s own
comment: this repo's jsdom has no native `PointerEvent`
(`'PointerEvent' in window` is `false`), confirmed by a throwaway repro in
the prior session, so `fireEvent.pointerDown/Move` silently drop
`clientX`/`pointerId` in tests. Every browser this app targets handles plain
mouse events identically, so there's no capability lost by not using pointer
capture.

Card overlap at narrow widths cannot recur structurally: `CARD_GRID_CLASS`
(`auto-fill, minmax(150px, 1fr)`, `gap-3`) now lives only in the **right**
pane, which is `flex-1` and gains width as the divider moves toward Chat/
Filter — narrowing the divider never narrows the grid below its own
minimum column width, it only reduces the column *count*.

### `lib/inventory.ts` additions

```ts
export interface PresentedCard {
  key: string
  title: string
  imageUrl?: string
  setName: string
  number?: string
  conditionLabel: string
  price: string
  isJapanese: boolean
}

export function toPresentedCard(item: InventoryItem): PresentedCard {
  const marketPrice = item.kind === 'raw' ? item.card?.market_price : null
  return {
    key: itemKey(item),
    title: itemTitle(item),
    imageUrl: item.card?.image_small ?? undefined,
    setName: item.card?.set_name ?? 'Unknown set',
    number: item.card?.number,
    conditionLabel: conditionLabel(item),
    price: marketPrice ?? item.listed_price ?? 'Price N/A',
    isJapanese: isJapanese(item),
  }
}

export function displayedCardToPresentedCard(card: DisplayedCard): PresentedCard {
  return {
    key: card.item_id,
    title: card.display_name || card.card?.name || 'Unknown card',
    imageUrl: card.card?.image_small || undefined,
    setName: card.card?.set_name ?? 'Unknown set',
    number: card.card?.number,
    conditionLabel: displayedCardCondition(card),
    // listed_price is the RESOLVED, condition-adjusted price (mirrors
    // routers/inventory.py::_display_price) and must win over
    // current_market_value, a separate, potentially stale pass-through
    // (RFC-0016 Council r2 self-review) — preserved unchanged from the
    // logic being consolidated here.
    price: card.listed_price ?? card.current_market_value ?? 'Price N/A',
    isJapanese: card.language === 'JP',
  }
}

function displayedCardCondition(card: DisplayedCard): string {
  if (card.condition) return card.condition
  if (card.kind === 'graded') {
    if (card.grade_label) return card.grade_label
    const slabGrade = [card.company, card.grade].filter(Boolean).join(' ')
    if (slabGrade) return slabGrade
  }
  return 'N/A'
}
```

This consolidates logic currently duplicated verbatim as `cardTitle`/
`cardCondition` in `DisplayPanel.tsx` and `artifactTitle`/`artifactCondition`
in `ChatPanel.tsx` (both retired or changed by this RFC anyway) into one
tested location. `CardTile.tsx`'s inline mapping is folded into
`toPresentedCard` the same way.

### `ResultsPane.tsx` (new)

```ts
export interface ResultsView {
  headerLabel: string
  cards: PresentedCard[]
  status: 'idle' | 'loading' | 'error'
  emptyMessage: string
  truncatedNotice?: string
}

export function ResultsPane({ headerLabel, cards, status, emptyMessage, truncatedNotice }: ResultsView)
```

Pure presentational component, no fetch logic. Renders:
- `status === 'loading'` → the existing "Searching the vault…" style message.
- `status === 'error'` → the existing error message.
- `cards.length === 0` → `emptyMessage` (each mode supplies its own copy —
  filter's idle/no-results copy differs from chat's "nothing displayed yet").
- otherwise → header (`headerLabel`, e.g. `"12 results"` or `"Display (3)"`),
  optional `truncatedNotice` banner, then `CARD_GRID_CLASS` grid of
  `CardPresentation`, in a `vault-scroll h-full overflow-y-auto` container —
  the same scroll treatment `DisplayPanel`'s grid used, without the `fixed`
  ancestor that used to make the navbar-offset math necessary.

### `HistoryMenu.tsx` (new)

Icon-only button using lucide-react's `History` icon (a clock with a
counter-clockwise arrow — semantically exact, not a placeholder pick).
Clicking toggles a small flyout anchored below the button
(`absolute`-positioned relative to a `relative`-positioned wrapper — scoped
locally, not viewport-relative, so it never interacts with the
navbar-overlap class of bug this RFC otherwise eliminates). Flyout content
today: `"No past conversations yet"` — an honest empty state, not a disabled
button, because chat has no persistence to show yet (RFC-0017, not started).
Closes on outside click (a `mousedown` listener on `document` while open,
removed on close/unmount — same lifecycle shape `DisplayPanel`'s old drag
listeners used) and on `Escape`.

### `FilterPanel.tsx` changes

Remove the inline `<CardGrid items={result.items} />` block and the
`Results`/`HiddenNoPriceNotice` rendering that currently sits below the form
(their logic moves into the `onResultsChange` payload construction, since
`ResultsPane` needs the same `hidden_no_price` messaging as a
`truncatedNotice`-shaped string, not new backend data). Add:

```ts
onResultsChange?: (view: ResultsView) => void
```

invoked from a `useEffect` keyed on `[result, status]`, mapping
`result.items` through `toPresentedCard`. The form, facets fetch, and
price-range normalization are unchanged.

### `ChatPanel.tsx` changes

Remove the `{displayPanel.cards.length > 0 && <DisplayPanel ... />}` block
and the `relative` wrapper div it required. Add:

```ts
onDisplayChange?: (view: ResultsView) => void
```

invoked wherever `displayPanel` is currently set (chat submit success, and
the panel's own close). Wrap the component in `forwardRef`:

```ts
export interface ChatPanelHandle { reset: () => void }
const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>((props, ref) => {
  useImperativeHandle(ref, () => ({
    reset: () => {
      setMessages([])
      setInput('')
      setDisplayPanel(EMPTY_PANEL)
    },
  }))
  // ...
})
```

`reset()` is what the new "New chat" button calls via a ref held in
`SplitWorkspace`. This keeps `ChatPanel`'s transcript/fetch logic fully
encapsulated — `SplitWorkspace` never reaches into its state directly.

### `SplitWorkspace.tsx` (new)

Owns `mode`, `leftWidth`, `chatView`, `filterView`, `historyOpen` is owned by
`HistoryMenu` itself (not lifted). Renders the header row and the flex row
described above. The `+ New` button is only rendered when `mode === 'chat'`
(mirrors `HistoryMenu`'s conditional render — both are chat-only concepts,
per the approved design).

## Data Schemas

No backend or database schema changes. This RFC is frontend-only.

## API Contracts

No new endpoints and no changes to existing request/response shapes.
`FilterPanel` continues to call `searchInventory`/`getInventoryFacets`;
`ChatPanel` continues to call `sendChat` — both unchanged. The "New chat" and
"History" controls are pure client-side state; History's empty state
requires no backend call at all (it will, once RFC-0017 adds a persistence
endpoint this RFC does not define).

> **Superseded 2026-08-27 — RFC-0017 landed.** `HistoryMenu` now lists real
> threads (fetched on open, not on mount) with rename, delete and clear-all,
> and `ChatPanel` carries a server-assigned `conversation_id` instead of
> shipping a client-built `history` array. `sendChat`'s signature changed with
> it. Everything above describes the state this RFC shipped, and is kept as
> that record rather than rewritten.

## Alternatives Considered

- **Lift chat/filter state fully into `SplitWorkspace`, make `ChatPanel`/
  `FilterPanel` fully controlled.** Rejected: both components have enough
  internal logic (`buildHistory`, price-range normalization, facets
  loading) that lifting all of it up would turn `SplitWorkspace` into a god
  component and widen the diff far beyond what this redesign needs. The
  `forwardRef` + two callback-props shape keeps each panel's internals
  encapsulated while giving `SplitWorkspace` exactly the two capabilities it
  needs (read the active view, trigger a reset).
- **One shared `resultsView` state instead of two slots.** Rejected — see
  "Why two independent view-state slots" above; a single slot reintroduces a
  stale-overwrite race between the visible and backgrounded pane.
- **Keep `DisplayPanel`'s dock/fullscreen mode toggle, just make "docked"
  in-flow.** Rejected: once the right pane is `flex-1` in a resizable split,
  dragging the divider already gives the grid more room on demand — the
  fullscreen mode's only real purpose. Keeping both would mean two competing
  ways to get more space, one of which (fullscreen) would need its own
  `fixed inset-0` escape from the very layout this RFC removes. This is
  flagged here explicitly because it's a behavior removal beyond what was
  discussed in chat, not because it's uncertain — the owner should confirm
  before it ships.

## Risks & Mitigations

- **Behavior removal not explicitly discussed:** dropping `DisplayPanel`'s
  fullscreen mode (see Alternatives above). Mitigation: called out here and
  will be called out again in the implementation report; trivial to add
  back as a "maximize right pane" toggle later if the owner wants it.
- **Regressing RFC-0016's display-panel test coverage.** `DisplayPanel.test.tsx`
  currently covers behavior (resize clamping, navbar offset, fullscreen
  toggle) that either moves to `SplitWorkspace.test.tsx` (resize) or is
  retired outright (navbar offset, fullscreen — no longer applicable
  structurally). Mitigation: the roadmap in `claude-progress.md` treats
  "retire old tests" as its own checklist item, done only after the new
  tests demonstrably cover the surviving behavior.
- **`FilterPanel`'s `hidden_no_price` notice and empty/no-results copy
  moving into `ResultsPane` props.** Risk of losing the exact wording or the
  count-based pluralization. Mitigation: carry the existing strings verbatim
  into the `onResultsChange` payload construction rather than rewriting them.

## Open Questions

None outstanding. The one open question this RFC raised — whether to drop
`DisplayPanel`'s fullscreen/dock mode entirely versus keeping a secondary
"maximize" control — was put to the owner directly and resolved: **drop it**.
The resizable divider is the one way to give the grid more room; no
fullscreen mode is being carried into the new components.
