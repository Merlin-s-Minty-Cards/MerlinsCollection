import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApiError } from '@/lib/admin-api'
import CardDetailModal from '../CardDetailModal'

const getMock = vi.fn()
const postMock = vi.fn()
const putMock = vi.fn()
const delMock = vi.fn()

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return {
    ...actual,
    useAdminApi: () => ({
      get: getMock,
      post: postMock,
      put: putMock,
      patch: vi.fn(),
      del: delMock,
      isAuthenticated: true,
      isLoading: false,
    }),
  }
})

vi.mock('@/lib/use-locations', () => ({
  useLocations: () => ({
    options: [{ value: 'custom_shelf', label: 'Custom Shelf' }],
    loading: false,
  }),
}))

vi.mock('@/lib/use-cosigners', () => ({
  useCosigners: () => ({
    options: [{ value: 'cos-1', label: 'Alex' }],
    loading: false,
  }),
}))

const item = {
  item_id: 'item-1',
  card_id: 'sv1-25',
  kind: 'raw',
  display_name: 'Pikachu',
  condition: 'NM',
  location: 'glass',
}

describe('CardDetailModal image resolution', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    // `get` backs PriceChart's price-history fetch (unrelated to this suite).
    // PriceChart types its state as `PriceChartData | null`; resolving with
    // `null` is the real "no data yet" shape it already renders gracefully.
    // (Originally `[]` here, which crashed PriceChart's useMemo — `[].points`
    // is undefined — and unmounted the whole tree before assertions ran; see
    // task-1-report.md GREEN section for the trace.)
    getMock.mockResolvedValue(null)
  })

  it('resolves and renders the card image itself, with no imageUrl prop and no page-level toggle', async () => {
    postMock.mockResolvedValueOnce({ 'sv1-25': 'https://images.example.com/sv1-25.png' })

    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/inventory/card-images', { card_ids: ['sv1-25'] }))

    const img = await screen.findByAltText('Pikachu')
    expect(img).toHaveAttribute('src', 'https://images.example.com/sv1-25.png')
  })

  it('shows the no-image fallback when the card has no resolvable image', async () => {
    postMock.mockResolvedValueOnce({ 'sv1-25': null })

    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    await waitFor(() => expect(postMock).toHaveBeenCalled())
    expect(screen.getByLabelText('No image')).toBeInTheDocument()
  })

  it('renders the location edit dropdown from useLocations(), not the static LOCATION_OPTIONS list', async () => {
    // beforeEach already sets getMock to resolve `null` for PriceChart's price-
    // history fetch (the correct "no data yet" shape — see beforeEach comment
    // above: resolving `[]` crashes PriceChart's useMemo on `[].points` and
    // unmounts the tree). No need to override it here.
    postMock.mockResolvedValueOnce({})
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    const editButtons = await screen.findAllByLabelText(/Edit Location/i)
    fireEvent.click(editButtons[0])

    expect(screen.getByRole('option', { name: 'Custom Shelf' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Toploader/i })).not.toBeInTheDocument()
  })
})

describe('CardDetailModal TCGplayer link', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    getMock.mockResolvedValue(null)
    postMock.mockResolvedValue({})
  })

  it('links directly to a stored tcg_url when one is set', async () => {
    render(<CardDetailModal item={{ ...item, tcg_url: 'https://www.tcgplayer.com/product/12345' }} onClose={vi.fn()} />)

    const link = await screen.findByRole('link', { name: /TCGplayer/i })
    expect(link).toHaveAttribute('href', 'https://www.tcgplayer.com/product/12345')
  })

  it('falls back to a generated TCGplayer search link when no tcg_url is stored', async () => {
    // Mirrors show-prep/page.tsx's `_tcg_url` column fallback — without this,
    // items that never had tcg_url set show no link at all (round7-handoff §10).
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    const link = await screen.findByRole('link', { name: /TCGplayer/i })
    expect(link).toHaveAttribute(
      'href',
      'https://www.tcgplayer.com/search/pokemon/product?q=Pikachu&view=grid',
    )
  })
})

// ---------------------------------------------------------------------------
// RFC 0008 §F6 — full field coverage + a real notes box
// ---------------------------------------------------------------------------

describe('CardDetailModal field coverage (RFC 0008 §F6)', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    getMock.mockResolvedValue(null)
    postMock.mockResolvedValue({})
  })

  async function openEditor(item: Record<string, unknown>, label: string) {
    render(<CardDetailModal item={item} onClose={vi.fn()} />)
    const edit = await screen.findByLabelText(`Edit ${label}`)
    fireEvent.click(edit)
  }

  it('edits notes in a textarea, not a single-line text input', async () => {
    await openEditor({ ...item, notes: 'a long note about this card' }, 'Notes')

    const box = screen.getByDisplayValue('a long note about this card')
    expect(box.tagName).toBe('TEXTAREA')
  })

  it('sizes the notes textarea to show more than one line', async () => {
    await openEditor({ ...item, notes: 'a long note about this card' }, 'Notes')

    const box = screen.getByDisplayValue('a long note about this card')
    expect(Number(box.getAttribute('rows'))).toBeGreaterThanOrEqual(3)
  })

  it('edits value_note in a textarea too', async () => {
    await openEditor({ ...item, value_note: 'priced off a recent comp' }, 'Value Note')

    expect(screen.getByDisplayValue('priced off a recent comp').tagName).toBe('TEXTAREA')
  })

  it('shows the graded-only fields on a graded item', async () => {
    render(
      <CardDetailModal
        item={{ ...item, kind: 'graded', company: 'PSA', grade: '9', cert_number: '12345678' }}
        onClose={vi.fn()}
      />,
    )

    expect(await screen.findByText('Grading Company')).toBeInTheDocument()
    expect(screen.getByText('Grade')).toBeInTheDocument()
    expect(screen.getByText('Cert Number')).toBeInTheDocument()
  })

  it('hides the graded-only fields on a raw item', async () => {
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    await screen.findByText('Condition')
    expect(screen.queryByText('Grade')).not.toBeInTheDocument()
    expect(screen.queryByText('Cert Number')).not.toBeInTheDocument()
    expect(screen.queryByText('Grading Company')).not.toBeInTheDocument()
  })

  it('shows the sealed-only product type on a sealed item, not on a raw one', async () => {
    const { unmount } = render(
      <CardDetailModal
        item={{ item_id: 'item-2', kind: 'sealed', product_name: 'SV1 ETB', product_type: 'etb' }}
        onClose={vi.fn()}
      />,
    )
    expect(await screen.findByText('Product Type')).toBeInTheDocument()
    unmount()

    render(<CardDetailModal item={item} onClose={vi.fn()} />)
    await screen.findByText('Condition')
    expect(screen.queryByText('Product Type')).not.toBeInTheDocument()
  })

  it('edits factory_sealed as a checkbox on a raw item', async () => {
    await openEditor({ ...item, factory_sealed: false }, 'Factory Sealed')

    expect(screen.getByRole('checkbox')).toBeInTheDocument()
  })

  it('edits needs_review as a checkbox', async () => {
    await openEditor({ ...item, needs_review: false }, 'Needs Review')

    expect(screen.getByRole('checkbox')).toBeInTheDocument()
  })

  it('edits acquired_at with a date input', async () => {
    await openEditor({ ...item, acquired_at: '2026-01-15' }, 'Acquired')

    const input = screen.getByDisplayValue('2026-01-15')
    expect(input).toHaveAttribute('type', 'date')
  })

  it('displays the derived identity fields but offers no edit control for them', async () => {
    render(
      <CardDetailModal
        item={{ ...item, lineage_id: 'lin-9', predecessor_item_id: 'item-0' }}
        onClose={vi.fn()}
      />,
    )

    expect(await screen.findByText('Item ID')).toBeInTheDocument()
    expect(screen.getByText('Lineage ID')).toBeInTheDocument()
    expect(screen.getByText('lin-9')).toBeInTheDocument()

    expect(screen.queryByLabelText('Edit Item ID')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Edit Lineage ID')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Edit Predecessor')).not.toBeInTheDocument()
  })

  it('shows the remaining _ItemBase pricing and acquisition fields', async () => {
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    expect(await screen.findByText('Market at Purchase')).toBeInTheDocument()
    expect(screen.getByText('Listed Price')).toBeInTheDocument()
    expect(screen.getByText('Acquired Show')).toBeInTheDocument()
  })

  it('shows consignment terms for a consigned item', async () => {
    render(
      <CardDetailModal
        item={{
          ...item,
          consignment: {
            consignor_id: 'cosigner-7',
            split_percent: '0.2',
            minimum_price: '50.00',
            paid_out: false,
          },
        }}
        onClose={vi.fn()}
      />,
    )

    expect(await screen.findByText('Consignment')).toBeInTheDocument()
    expect(screen.getByText('cosigner-7')).toBeInTheDocument()
  })

  // RFC 0012 C3 changed this: the section used to be omitted entirely for an
  // owned item, but it now always renders so an "Assign consignor" control is
  // reachable on every item, not only ones a consignment already exists on
  // (the escape-hatch rule in CLAUDE.md — a control gated on the state it is
  // meant to create is unreachable exactly when it is needed). The read-only
  // consignment ROWS are still shown only when a consignment exists; see the
  // dedicated RFC 0012 C3 describe block below for the assign/unassign tests.
  it('shows only an assign control, no consignment rows, for an owned item', async () => {
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    await screen.findByText('Condition')
    expect(screen.getByText('Consignment')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /assign consignor/i })).toBeInTheDocument()
    expect(screen.queryByText('Our Cut')).not.toBeInTheDocument()
  })

  // The Round 1 bug: a combined "LP+" sent as a `condition` enum value fails
  // backend validation. This is the single most important regression guard in
  // this task — it passes today and must keep passing.
  it('splits a combined condition into condition + condition_modifier on save', async () => {
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    fireEvent.click(await screen.findByLabelText('Edit Condition'))
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'LP+' } })
    fireEvent.click(screen.getByLabelText('Save'))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/item-1', {
        condition: 'LP',
        condition_modifier: '+',
      }),
    )
  })

  it('sends a real boolean for a checkbox field, never a null or a string', async () => {
    // `admin_update_item` merges the body into the validated model, and
    // `needs_review` is a non-optional bool — a null (what the generic
    // blank-is-null path would send) is a 422, and "true" is not a bool.
    await openEditor({ ...item, needs_review: false }, 'Needs Review')

    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByLabelText('Save'))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { needs_review: true }),
    )
  })
})

// ===========================================================================
// T11 — Send to Triage (docs/plans/rfc-0008/t11-triage-tab.md)
// ===========================================================================
//
// The owner's requirement is that any card, on any tab, can be sent to Triage.
// This modal is the cheapest broad insertion point — but NOT a universal one:
// T5 established it is mounted by five pages (inventory, outgoing, sell,
// show-prep, vault), not "any admin page". The cross-page half of that
// assumption is pinned from the pages themselves, in
// app/(admin)/admin/{inventory,outgoing}/__tests__/page.test.tsx.
//
// The button opens an INLINE note form rather than calling window.prompt():
// the note is optional-but-encouraged free text, and a native prompt cannot be
// styled, cannot be dismissed with Escape predictably, and blocks the render
// thread. The row-level quick action on list pages is the no-note path.
describe('CardDetailModal — Send to Triage', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    getMock.mockResolvedValue(null)
    postMock.mockResolvedValue({})
    putMock.mockResolvedValue({})
  })

  it('offers a Send to Triage action for an item that is not already flagged', async () => {
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    expect(await screen.findByRole('button', { name: /send to triage/i })).toBeInTheDocument()
  })

  it('flags the item with the typed note', async () => {
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: /send to triage/i }))
    fireEvent.change(screen.getByLabelText(/why does this need review/i), {
      target: { value: 'set symbol looks wrong' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/item-1', {
        needs_review: true,
        review_reason: 'set symbol looks wrong',
      }),
    )
  })

  it('sends with no note when the admin leaves the box empty', async () => {
    // "Optional but encouraged" — an empty note must not block the send, and
    // must not post an empty string that would render as a blank reason chip.
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: /send to triage/i }))
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/item-1', {
        needs_review: true,
        review_reason: null,
      }),
    )
  })

  it('reads "In Triage" for an already-flagged item and never silently re-flags it', async () => {
    // A button that no-ops is worse than no button: the admin clicks, nothing
    // visible happens, and they conclude the feature is broken.
    render(
      <CardDetailModal
        item={{ ...item, needs_review: true, review_reason: 'manual_entry' }}
        onClose={vi.fn()}
      />,
    )

    expect(await screen.findByRole('button', { name: /in triage/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /send to triage/i })).not.toBeInTheDocument()
  })

  it('lets an already-flagged item be cleared from the modal', async () => {
    render(
      <CardDetailModal
        item={{ ...item, needs_review: true, review_reason: 'manual_entry' }}
        onClose={vi.fn()}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: /in triage/i }))
    fireEvent.click(screen.getByRole('button', { name: /clear review/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/item-1', {
        needs_review: false,
        review_reason: null,
      }),
    )
  })

  it('offers an Undo that reverts the send, reason included', async () => {
    // Misclicks on this are inevitable. Undo must also clear `review_reason`,
    // or the item comes back unflagged while still carrying the note that put
    // it there — which then shows up as a stale reason on the next flag.
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: /send to triage/i }))
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }))

    fireEvent.click(await screen.findByRole('button', { name: /undo/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenLastCalledWith('/inventory/item-1', {
        needs_review: false,
        review_reason: null,
      }),
    )
  })
})

// ===========================================================================
// RFC 0010 T5 — an edit shows up immediately, and the parent is handed the row
// ===========================================================================
//
// The owner's report: *"once you click and edit a label on a card, it doesn't
// update immediately instead, you have to reload or click out which often
// resets you to the top of the menu."*
//
// Root cause: `saveEdit` DISCARDED the PUT response and re-rendered the `item`
// PROP, which is an object out of the parent's list state. The parent's refetch
// replaced the array but not that object, so the edited field kept its old
// value until the modal was closed and reopened — and the refetch re-mounted
// the table, which is the "resets you to the top" half.
//
// The fix is the server's own answer: `PUT /admin/inventory/{item_id}` returns
// the full updated item (`_serialize_item`), which is what the modal renders
// and what it hands the parent. Taking the RESPONSE rather than optimistically
// merging the payload matters — the server normalises (`_split_combined_
// condition`, the blank-to-None validators, the server-stamped `reviewed_at`),
// so a local merge would display a value the database does not hold.
describe('CardDetailModal — an edit shows up immediately (RFC 0010 T5)', () => {
  beforeEach(() => {
    // mockReset, not clearAllMocks: a `mockResolvedValueOnce` left unconsumed
    // by one test is handed to the next, which then fails on another test's
    // data (CLAUDE.md, "Running Tests").
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    getMock.mockResolvedValue(null)
    postMock.mockResolvedValue({})
    putMock.mockResolvedValue({})
  })

  /** Open the Notes editor and type `typed`, without saving. */
  async function typeNote(props: Partial<React.ComponentProps<typeof CardDetailModal>> = {}) {
    render(<CardDetailModal item={item} onClose={vi.fn()} {...props} />)
    fireEvent.click(await screen.findByLabelText('Edit Notes'))
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'checked at the show' },
    })
  }

  it('renders the value the SERVER returned, not an echo of what was typed', async () => {
    // The response value is deliberately DIFFERENT from the typed one. An
    // optimistic merge of the payload would show "checked at the show" and pass
    // a weaker test while still being the wrong design — the server normalises,
    // so only its answer is what the database actually holds.
    await typeNote()
    putMock.mockResolvedValueOnce({ ...item, notes: 'Checked at the show — server' })

    fireEvent.click(screen.getByLabelText('Save'))

    expect(await screen.findByText('Checked at the show — server')).toBeInTheDocument()
    expect(screen.queryByText('checked at the show')).not.toBeInTheDocument()
  })

  it('hands the updated item to onUpdated so the parent can patch its row', async () => {
    // The parameter is what lets a parent patch ONE row instead of refetching
    // the whole list — which is what stops the table re-mounting and throwing
    // the admin back to the top.
    const onUpdated = vi.fn()
    const updated = { ...item, notes: 'Checked at the show — server' }
    await typeNote({ onUpdated })
    putMock.mockResolvedValueOnce(updated)

    fireEvent.click(screen.getByLabelText('Save'))

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(updated))
  })

  it('leaves the displayed value alone and says so when the save fails', async () => {
    // NOTE: passes before the change — the modal already renders the prop and
    // already surfaces the error. Kept as the regression guard that stops the
    // new "render the response" path from displaying a save that did not land.
    const onUpdated = vi.fn()
    render(
      <CardDetailModal item={{ ...item, notes: 'original note' }} onClose={vi.fn()} onUpdated={onUpdated} />,
    )
    fireEvent.click(await screen.findByLabelText('Edit Notes'))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'a new note' } })
    putMock.mockRejectedValueOnce(new AdminApiError(422, 'Notes are too long'))

    fireEvent.click(screen.getByLabelText('Save'))

    expect(await screen.findByText('Notes are too long')).toBeInTheDocument()
    expect(onUpdated).not.toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText('Cancel'))
    expect(screen.getByText('original note')).toBeInTheDocument()
  })

  it('re-seeds from the prop when the modal is reopened on a different card', async () => {
    // The modal owning its own copy must not become a cache: opening card B
    // after saving card A has to show B. Keying the re-seed on `item_id` is
    // also what stops a STALE parent prop overwriting the fresh server value
    // for the card still on screen.
    const { rerender } = render(
      <CardDetailModal item={{ ...item, notes: 'first note' }} onClose={vi.fn()} />,
    )
    fireEvent.click(await screen.findByLabelText('Edit Notes'))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'x' } })
    putMock.mockResolvedValueOnce({ ...item, notes: 'saved on card one' })
    fireEvent.click(screen.getByLabelText('Save'))
    await screen.findByText('saved on card one')

    rerender(
      <CardDetailModal
        item={{ ...item, item_id: 'item-2', display_name: 'Charizard', notes: 'second note' }}
        onClose={vi.fn()}
      />,
    )

    expect(await screen.findByText('second note')).toBeInTheDocument()
    expect(screen.queryByText('saved on card one')).not.toBeInTheDocument()
  })

  it('updates from the response on the triage write path too', async () => {
    // `writeTriage` has the identical shape to `saveEdit` and the identical
    // defect. The reason shown here comes from the SERVER's copy of the item —
    // it used to read the prop, which never carried one.
    render(<CardDetailModal item={item} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: /send to triage/i }))
    fireEvent.change(screen.getByLabelText(/why does this need review/i), {
      target: { value: 'set symbol looks wrong' },
    })
    putMock.mockResolvedValueOnce({
      ...item,
      needs_review: true,
      review_reason: 'set symbol looks wrong (recorded)',
    })

    fireEvent.click(screen.getByRole('button', { name: /^send$/i }))

    fireEvent.click(await screen.findByRole('button', { name: /in triage/i }))
    expect(
      await screen.findByText(/set symbol looks wrong \(recorded\)/),
    ).toBeInTheDocument()
  })
})

// ===========================================================================
// RFC 0010 T6 — the modal stays usable when you zoom
// ===========================================================================
//
// The owner's report (plan doc items 5 and 7): *"it forces the size of the
// image so when you zoom in or out it just keeps the same size of the image and
// shoves the text to the side … when i try to edit the finish field it puts
// characters into the factory sealed label and the box to add text is very
// small"*, and separately that opening a card from Prepare for Shows gives the
// picture an even higher percentage of the screen.
//
// Item 7 is NOT a second bug: /admin/show-prep mounts this same component.
//
// Three compounding layout decisions cause it:
//   1. the shell is capped at `max-w-4xl` and never grows;
//   2. the image column is `flex-shrink-0`, so at `md:h-full` a 5:7 card claims
//      ~0.71 x 90vh of width and never gives any of it back;
//   3. the field grid is VIEWPORT-driven (`sm:grid-cols-2`), so it stays two-up
//      however narrow the details COLUMN becomes, and each cell's fixed `w-24`
//      label then owns most of what is left.
//
// Zoom is the trigger precisely because it changes the container without
// changing the breakpoint the way you would expect — so none of this is fixable
// with another `sm:`/`md:` variant.
//
// WHAT THESE TESTS ARE. jsdom does no layout: it cannot tell you whether the
// Finish field is typeable at 175% zoom in Chrome. These assert the class
// CONTRACT — the decisions above, locked so a later edit cannot quietly undo
// them. The manual check in the task doc is the actual acceptance criterion and
// these do not substitute for it.
describe('CardDetailModal — layout survives zoom (RFC 0010 T6)', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    getMock.mockResolvedValue(null)
    postMock.mockResolvedValue({})
    putMock.mockResolvedValue({})
  })

  /** The modal shell — the sized box inside the full-screen backdrop. */
  const shell = () => screen.getByRole('dialog').firstElementChild as HTMLElement

  /** The cell wrapping a field, found by its label; its parent is the grid. */
  const cellFor = (label: string) => screen.getByText(label).parentElement as HTMLElement

  it('gives the shell room to grow instead of capping it at max-w-4xl', async () => {
    render(<CardDetailModal item={item} onClose={vi.fn()} />)
    await screen.findByText('Condition')

    expect(shell().className).toContain('max-w-6xl')
    expect(shell().className).not.toContain('max-w-4xl')
  })

  it('lets the image column yield, and caps how much of the modal it can claim', async () => {
    // `flex-shrink-0` is the whole of "shoves the text to the side": the image
    // takes its width first and never gives any back, so the details column
    // gets only the remainder however little that is.
    postMock.mockResolvedValueOnce({ 'sv1-25': 'https://images.example.com/sv1-25.png' })
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    const column = (await screen.findByAltText('Pikachu')).parentElement as HTMLElement

    expect(column.className).not.toContain('flex-shrink-0')
    // Specifically in the side-by-side layout. It stays rigid in the stacked one
    // below `md`, where shrinking would squash the art instead of freeing width.
    expect(column.className).toContain('md:shrink')
    expect(column.className).toMatch(/max-w-\[/)
  })

  it('drives the field grid off the container, not the viewport breakpoint', async () => {
    // `sm:grid-cols-2` keys off the VIEWPORT, so the grid stays two-up while the
    // column it lives in is squeezed to nothing. An auto-fit template collapses
    // to one column whenever a cell would be too narrow — at any zoom, with no
    // breakpoint to tune. This is the change that actually fixes the report.
    render(<CardDetailModal item={item} onClose={vi.fn()} />)
    await screen.findByText('Finish')

    const grid = cellFor('Finish').parentElement as HTMLElement

    expect(grid.className).toContain('auto-fit')
    expect(grid.className).toContain('minmax')
    expect(grid.className).not.toContain('sm:grid-cols-2')
  })

  it('makes the no-image placeholder shrink like the real image does', async () => {
    // Otherwise the layout is correct only for cards that HAVE art — and the
    // unlinked/Japanese cards most likely to be opened for repair are exactly
    // the ones that do not.
    postMock.mockResolvedValueOnce({ 'sv1-25': null })
    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    const placeholder = await screen.findByLabelText('No image')

    expect(placeholder.className).not.toContain('flex-shrink-0')
    expect(placeholder.className).not.toMatch(/(^|\s)w-72(\s|$)/)
  })

  it('lets a cramped field row stack its value under its label instead of crushing it', async () => {
    // The symptom the owner described — characters landing in the neighbouring
    // label — is an input squeezed to near-zero width beside a fixed `w-24`
    // label, not an input that moved. Tailwind container queries are not
    // installed in this project, so the stack is done with wrapping plus a floor
    // on the value: it drops below the label exactly when it no longer fits.
    render(<CardDetailModal item={item} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByLabelText('Edit Finish'))

    const cell = cellFor('Finish')
    const editor = screen.getByDisplayValue('').parentElement as HTMLElement

    expect(cell.className).toContain('flex-wrap')
    expect(editor.className).toMatch(/min-w-\[/)
  })

  it('spans a textarea row across the whole grid without inventing a second column', async () => {
    // `sm:col-span-2` is wrong twice over here: it is viewport-keyed like the
    // grid was, and on a grid that has collapsed to ONE column a span of 2
    // creates an implicit second column — breaking the exact narrow case this
    // task exists to fix. `col-span-full` spans whatever tracks exist.
    render(<CardDetailModal item={item} onClose={vi.fn()} />)
    await screen.findByText('Value Note')

    expect(cellFor('Value Note').className).toContain('col-span-full')
    expect(cellFor('Value Note').className).not.toContain('sm:col-span-2')
  })

  it('still renders every field label beside its value', async () => {
    // The regression gate. A layout change is exactly where a field quietly
    // disappears, and every one of these was added deliberately in RFC 0008 T5.
    // A graded item is the densest section in the component.
    render(
      <CardDetailModal
        item={{
          ...item,
          kind: 'graded',
          company: 'PSA',
          grade: '9',
          cert_number: '12345678',
          location: 'glass',
          sticker_notes: 'seen at $40',
        }}
        onClose={vi.fn()}
      />,
    )

    // `Notes` is deliberately not in this list: it is BOTH a section heading and
    // a field label, so it matches two elements. `Sticker Notes` covers the same
    // ground unambiguously.
    for (const [label, value] of [
      ['Item ID', 'item-1'],
      ['Grading Company', 'PSA'],
      ['Grade', '9'],
      ['Cert Number', '12345678'],
      ['Location', 'glass'],
      ['Sticker Notes', 'seen at $40'],
    ]) {
      expect(await screen.findByText(label)).toBeInTheDocument()
      expect(screen.getByText(value)).toBeInTheDocument()
    }
  })
})

// ===========================================================================
// RFC 0010 T16 — the number's provenance, beside the number
// ===========================================================================
//
// The modal already exposes `current_market_value`, `listed_price`,
// `sticker_price` and `value_note` as editable rows (RFC 0008 T5), so it needs
// no new field. What it needs is the marker: on an unlinked item that figure is
// a human's judgement that no sync will ever revisit, and on a linked one it is
// a provider figure that the next sync will overwrite. Identical-looking numbers
// meaning opposite things is what makes an admin distrust the whole panel.

describe('CardDetailModal hand-valued marker', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    getMock.mockResolvedValue(null)
    postMock.mockResolvedValue({})
  })

  it('marks an unlinked item as hand-valued', async () => {
    render(
      <CardDetailModal
        item={{ ...item, card_id: null, current_market_value: '23.20' }}
        onClose={vi.fn()}
      />,
    )

    expect(await screen.findByText(/hand-valued/i)).toBeInTheDocument()
    // Says WHY, not just what: an unlinked card is not waiting on a sync.
    expect(screen.getByText(/no sync will/i)).toBeInTheDocument()
  })

  it('does not mark a catalog-linked item', async () => {
    render(
      <CardDetailModal
        item={{ ...item, current_market_value: '10.00' }}
        onClose={vi.fn()}
      />,
    )

    await waitFor(() => expect(postMock).toHaveBeenCalled())
    expect(screen.queryByText(/hand-valued/i)).not.toBeInTheDocument()
  })
})

// ===========================================================================
// RFC 0012 C3 — assign/unassign a cosigner directly from the modal
// ===========================================================================
//
// The Consignment section used to be read-only (see the comment on
// `consignment` in CardDetailModal.tsx): a partial PUT through the generic
// field editor risks reinventing POST /admin/cosigners/{id}/link's
// default-split-percent logic and silently dropping `paid_out`. This calls
// the existing, tested cosigner endpoints directly instead. Neither endpoint
// returns a full item, so these call `onUpdated()` with no argument — the
// modal's documented "something changed, but I cannot tell you what" shape,
// same as a refetch is the parent's job.
describe('CardDetailModal — assign/unassign a cosigner (RFC 0012 C3)', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    delMock.mockReset()
    getMock.mockResolvedValue(null)
    postMock.mockResolvedValue({})
  })

  it('shows an "Assign consignor" control when the item has no consignment', () => {
    render(<CardDetailModal item={{ item_id: 'i1', name: 'Charizard' }} onClose={vi.fn()} />)
    expect(screen.getByRole('button', { name: /assign consignor/i })).toBeInTheDocument()
  })

  it('links the item to a cosigner and refetches', async () => {
    const user = userEvent.setup({ delay: null })
    postMock.mockResolvedValue({ linked: 1, consignor_id: 'cos-1', failed_item_ids: [] })
    const onUpdated = vi.fn()
    render(<CardDetailModal item={{ item_id: 'i1', name: 'Charizard' }} onClose={vi.fn()} onUpdated={onUpdated} />)

    await user.click(screen.getByRole('button', { name: /assign consignor/i }))
    await user.click(screen.getByRole('combobox', { name: /consignor/i }))
    await user.click(screen.getByText('Alex'))
    await user.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/cosigners/cos-1/link', { item_ids: ['i1'] }))
    expect(onUpdated).toHaveBeenCalledWith()

    // CosignorPicker's onBlur schedules a real 150ms setTimeout (not
    // cancelled on unmount) to close its dropdown. Clicking "Save" moves
    // focus off the combobox and triggers it; without draining it here it
    // fires after this test's jsdom environment tears down and throws
    // "window is not defined" from inside React's setState machinery,
    // surfacing as an unhandled error at the end of the whole suite run.
    await new Promise((resolve) => setTimeout(resolve, 200))
  })

  it('shows an "Unassign" control and unlinks a consigned item', async () => {
    const user = userEvent.setup({ delay: null })
    delMock.mockResolvedValue({ status: 'unlinked', item_id: 'i1' })
    const onUpdated = vi.fn()
    render(
      <CardDetailModal
        item={{ item_id: 'i1', name: 'Charizard', consignment: { consignor_id: 'cos-1', split_percent: '0.5' } }}
        onClose={vi.fn()}
        onUpdated={onUpdated}
      />,
    )

    await user.click(screen.getByRole('button', { name: /unassign consignor/i }))

    await waitFor(() => expect(delMock).toHaveBeenCalledWith('/cosigners/cos-1/assets/i1'))
    expect(onUpdated).toHaveBeenCalledWith()
  })
})
