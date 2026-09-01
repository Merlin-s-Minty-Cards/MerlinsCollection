import { forwardRef, useImperativeHandle } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'


// HistoryMenu (RFC 0017) reads the Cognito access token to list threads, so
// this tree now contains a useSession caller.
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { accessToken: 'test-token' }, status: 'authenticated' }),
}))

vi.mock('@/lib/conversations', () => ({
  listConversations: vi.fn(async () => []),
  getConversation: vi.fn(),
  renameConversation: vi.fn(),
  deleteConversation: vi.fn(),
  clearConversations: vi.fn(),
  // HistoryMenu's `client` prop defaults to this — SplitWorkspace renders
  // HistoryMenu with no `client` override, so the default has to resolve to
  // something with a real shape even under this full-module mock.
  customerConversations: {
    list: vi.fn(async () => []),
    get: vi.fn(),
    rename: vi.fn(),
    remove: vi.fn(),
    clear: vi.fn(),
  },
}))

import type { ChatPanelHandle, ChatPanelProps } from '../ChatPanel'
import type { FilterPanelProps } from '../FilterPanel'
import type { ResultsView } from '../ResultsPane'

// ChatPanel and FilterPanel each have their own thorough test suites already
// (fetch mocking, history building, price precedence, etc). SplitWorkspace's
// own job is pure orchestration — mode switching, the resizable divider, and
// routing each mode's pushed view into the shared ResultsPane — so both
// children are replaced with minimal stubs that expose exactly the props
// contract SplitWorkspace depends on.
const chatHandle = vi.hoisted(() => ({ reset: vi.fn(), clearDisplay: vi.fn() }))

const CHAT_VIEW: ResultsView = {
  headerLabel: 'Display (1)',
  cards: [
    {
      key: 'chat-1',
      title: 'Charizard',
      setName: 'Base',
      conditionLabel: 'NM',
      price: '250.00',
      isJapanese: false,
    },
  ],
  status: 'success',
  emptyMessage: 'No cards in the display yet.',
}

const FILTER_VIEW: ResultsView = {
  headerLabel: '1 result',
  cards: [
    {
      key: 'filter-1',
      title: 'Pikachu',
      setName: 'Jungle',
      conditionLabel: 'LP',
      price: '40.00',
      isJapanese: false,
    },
  ],
  status: 'success',
  emptyMessage: 'No cards found.',
}

vi.mock('../ChatPanel', () => ({
  __esModule: true,
  default: forwardRef(function ChatPanelStub(props: ChatPanelProps, ref: React.Ref<ChatPanelHandle>) {
    useImperativeHandle(ref, () => chatHandle)
    return (
      <div>
        <button onClick={() => props.onDisplayChange?.(CHAT_VIEW)}>Simulate chat result</button>
      </div>
    )
  }),
}))

vi.mock('../FilterPanel', () => ({
  __esModule: true,
  default: function FilterPanelStub(props: FilterPanelProps) {
    return (
      <div>
        <button onClick={() => props.onResultsChange?.(FILTER_VIEW)}>
          Simulate filter result
        </button>
      </div>
    )
  },
}))

import SplitWorkspace from '../SplitWorkspace'

beforeEach(() => {
  chatHandle.reset.mockClear()
  chatHandle.clearDisplay.mockClear()
  document.body.style.userSelect = ''
})

describe('SplitWorkspace', () => {
  it('defaults to filter mode, matching the prior page-level default', () => {
    render(<SplitWorkspace />)
    expect(screen.getByRole('tab', { name: /filter/i })).toHaveAttribute('aria-selected', 'true')
  })

  it('shows New chat and History controls only in chat mode', async () => {
    const user = userEvent.setup({ delay: null })
    render(<SplitWorkspace />)
    expect(screen.queryByRole('button', { name: /new chat/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /conversation history/i })).toBeNull()

    await user.click(screen.getByRole('tab', { name: /chat/i }))
    expect(screen.getByRole('button', { name: /new chat/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /conversation history/i })).toBeInTheDocument()
  })

  it('calls the chat panel\'s reset() when New chat is clicked', async () => {
    const user = userEvent.setup({ delay: null })
    render(<SplitWorkspace />)
    await user.click(screen.getByRole('tab', { name: /chat/i }))
    await user.click(screen.getByRole('button', { name: /new chat/i }))
    expect(chatHandle.reset).toHaveBeenCalledOnce()
  })

  it('routes each mode\'s pushed view into the one shared ResultsPane', async () => {
    const user = userEvent.setup({ delay: null })
    render(<SplitWorkspace />)

    // Filter mode is active by default.
    await user.click(screen.getByRole('button', { name: 'Simulate filter result' }))
    expect(await screen.findByText('1 result')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Pikachu' })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /chat/i }))
    await user.click(screen.getByRole('button', { name: 'Simulate chat result' }))
    expect(await screen.findByText('Display (1)')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Charizard' })).toBeInTheDocument()
  })

  it('keeps chat and filter results independent across a mode switch', async () => {
    const user = userEvent.setup({ delay: null })
    render(<SplitWorkspace />)

    await user.click(screen.getByRole('tab', { name: /chat/i }))
    await user.click(screen.getByRole('button', { name: 'Simulate chat result' }))
    expect(await screen.findByText('Display (1)')).toBeInTheDocument()

    // Switch away and back — the chat view must not have been reset or
    // overwritten by the filter pane's (still-idle) state.
    await user.click(screen.getByRole('tab', { name: /filter/i }))
    await user.click(screen.getByRole('tab', { name: /chat/i }))
    expect(screen.getByText('Display (1)')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Charizard' })).toBeInTheDocument()
  })

  it('offers a "Clear display" control on the results pane only in chat mode with cards present', async () => {
    const user = userEvent.setup({ delay: null })
    render(<SplitWorkspace />)

    // Filter mode, with results: no clear control (nothing to "clear" — the
    // next search just replaces it).
    await user.click(screen.getByRole('button', { name: 'Simulate filter result' }))
    expect(await screen.findByText('1 result')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /clear display/i })).toBeNull()

    await user.click(screen.getByRole('tab', { name: /chat/i }))
    await user.click(screen.getByRole('button', { name: 'Simulate chat result' }))
    await user.click(screen.getByRole('button', { name: /clear display/i }))
    expect(chatHandle.clearDisplay).toHaveBeenCalledOnce()
  })

  it('exposes a resize handle that widens/narrows the left pane within bounds', () => {
    render(<SplitWorkspace />)
    const leftPane = screen.getByRole('group', { name: /search panel/i })
    expect((leftPane as HTMLElement).style.width).toBe('420px')

    const handle = screen.getByRole('separator', { name: /resize/i })
    fireEvent.mouseDown(handle, { clientX: 500 })
    fireEvent.mouseMove(window, { clientX: 500 + 1000 }) // +1000px delta
    expect((leftPane as HTMLElement).style.width).toBe('720px') // clamped to MAX

    fireEvent.mouseMove(window, { clientX: 500 - 1000 }) // -1000px delta from the ORIGINAL drag start
    expect((leftPane as HTMLElement).style.width).toBe('320px') // clamped to MIN

    fireEvent.mouseUp(window, { clientX: 500 - 1000 })
    fireEvent.mouseMove(window, { clientX: 500 + 1000 })
    expect((leftPane as HTMLElement).style.width).toBe('320px') // drag ended, further move is a no-op
  })

  it('points every aria-controls at an element that actually exists', () => {
    // Found in a live browser pass 2026-08-27: ModeToggle's tabs declared
    // aria-controls="panel-filter"/"panel-chat" and NEITHER id existed in the
    // DOM — there were zero role="tabpanel" elements on the whole page. The
    // reference dangled for the life of RFC-0019.
    //
    // ModeToggle's own test asserts the attribute's VALUE, which stays true
    // while the element it names is deleted, so it could never catch this.
    // This test resolves the pointer instead of reading it, which is the only
    // form that fails when the target goes away.
    const { container } = render(<SplitWorkspace />)
    const referrers = Array.from(container.querySelectorAll('[aria-controls]'))
    expect(referrers.length).toBeGreaterThan(0)
    for (const el of referrers) {
      const id = el.getAttribute('aria-controls') as string
      expect(document.getElementById(id), `aria-controls="${id}" resolves to nothing`).not.toBeNull()
    }
  })

  it('exposes the visible pane as the tabpanel its tab controls', async () => {
    const user = userEvent.setup({ delay: null })
    render(<SplitWorkspace />)

    const filterPanel = document.getElementById('panel-filter') as HTMLElement
    expect(filterPanel).toHaveAttribute('role', 'tabpanel')
    expect(filterPanel).toHaveAttribute('aria-labelledby', 'tab-filter')
    // The inactive panel stays in the DOM (mounted, per the test below) but is
    // `hidden`, so it is correctly absent from the accessibility tree.
    expect(screen.getByRole('tabpanel')).toBe(filterPanel)

    await user.click(screen.getByRole('tab', { name: /chat/i }))
    expect(screen.getByRole('tabpanel')).toBe(document.getElementById('panel-chat'))
  })

  it('resizes from the keyboard and reports its width to assistive tech', async () => {
    // Also from the live pass: the handle was tabIndex=-1 with no aria-value*,
    // and its ONLY visual presence was `hover:bg-mint/40` — so the control was
    // mouse-only and invisible until hovered. CLAUDE.md: "Hover may change a
    // background colour. It may never be the only way to see ... a control."
    const user = userEvent.setup({ delay: null })
    render(<SplitWorkspace />)
    const leftPane = screen.getByRole('group', { name: /search panel/i }) as HTMLElement
    const handle = screen.getByRole('separator', { name: /resize/i })

    expect(handle).toHaveAttribute('tabindex', '0')
    expect(handle).toHaveAttribute('aria-valuenow', '420')
    expect(handle).toHaveAttribute('aria-valuemin', '320')
    expect(handle).toHaveAttribute('aria-valuemax', '720')

    handle.focus()
    await user.keyboard('{ArrowRight}')
    expect(leftPane.style.width).toBe('440px')
    expect(handle).toHaveAttribute('aria-valuenow', '440')

    await user.keyboard('{ArrowLeft}{ArrowLeft}')
    expect(leftPane.style.width).toBe('400px')

    // Home/End jump to the bounds, so a keyboard user is not made to hold an
    // arrow key through 400px of travel to reach either end.
    await user.keyboard('{Home}')
    expect(leftPane.style.width).toBe('320px')
    await user.keyboard('{End}')
    expect(leftPane.style.width).toBe('720px')
  })

  it('prevents text selection while dragging, and restores it on release', () => {
    render(<SplitWorkspace />)
    const handle = screen.getByRole('separator', { name: /resize/i })

    expect(document.body.style.userSelect).toBe('')
    fireEvent.mouseDown(handle, { clientX: 0 })
    expect(document.body.style.userSelect).toBe('none')
    fireEvent.mouseUp(window, { clientX: 0 })
    expect(document.body.style.userSelect).toBe('')
  })

  it('mounts both panels always, toggling visibility with `hidden` rather than unmounting', async () => {
    const user = userEvent.setup({ delay: null })
    render(<SplitWorkspace />)
    // Filter is active by default — its stub button exists and is not hidden.
    expect(screen.getByRole('button', { name: 'Simulate filter result' })).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: /chat/i }))
    // Both stubs remain in the DOM; only visibility (the `hidden` attribute,
    // which getByRole excludes by default) toggles — `{ hidden: true }`
    // below is the query option that includes hidden elements, confirming
    // the filter stub is still mounted rather than torn down.
    expect(
      screen.getByRole('button', { name: 'Simulate filter result', hidden: true }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Simulate chat result' })).toBeInTheDocument()
  })
})
