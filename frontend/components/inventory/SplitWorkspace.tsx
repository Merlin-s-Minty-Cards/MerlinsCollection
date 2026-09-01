'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Plus } from 'lucide-react'
import ModeToggle, { type SearchMode } from './ModeToggle'
import ChatPanel, { type ChatPanelHandle } from './ChatPanel'
import FilterPanel from './FilterPanel'
import ResultsPane, { type ResultsView } from './ResultsPane'
import HistoryMenu from './HistoryMenu'

// RFC 0019: replaces InventoryWorkspace's page-level mode toggle + ChatPanel's
// own fixed/overlay DisplayPanel with a real, in-normal-flow two-column split.
// Nothing here is `fixed` or screen-edge-anchored — that's what structurally
// rules out the prior sidebar's navbar overlap and content-covering bugs,
// rather than patching them with more positioning math.

const MIN_LEFT_WIDTH = 320
const MAX_LEFT_WIDTH = 720
const DEFAULT_LEFT_WIDTH = 420
// Per arrow-key press. Big enough that reaching either bound is a few presses
// rather than dozens; Home/End cover the bounds outright.
const KEYBOARD_STEP = 20

const clampWidth = (width: number) =>
  Math.min(MAX_LEFT_WIDTH, Math.max(MIN_LEFT_WIDTH, width))

const IDLE_CHAT_VIEW: ResultsView = {
  headerLabel: 'Display (0)',
  cards: [],
  status: 'success',
  emptyMessage: 'No cards in the display yet.',
}

const IDLE_FILTER_VIEW: ResultsView = {
  headerLabel: '',
  cards: [],
  status: 'idle',
  emptyMessage: 'Set your filters and run a search to browse the collection.',
}

const headerButtonClass =
  'flex items-center gap-1.5 rounded-md px-2.5 py-2 text-sm font-medium text-pine-300 transition-colors hover:bg-pine-800 hover:text-mint focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mint'

export default function SplitWorkspace() {
  const [mode, setMode] = useState<SearchMode>('filter')
  const [leftWidth, setLeftWidth] = useState(DEFAULT_LEFT_WIDTH)
  // Two independent slots — each written only by that mode's own callback —
  // so a backgrounded pane can never stale-overwrite the visible one's
  // results. ResultsPane always renders whichever slot `mode` currently
  // points at.
  const [chatView, setChatView] = useState<ResultsView>(IDLE_CHAT_VIEW)
  const [filterView, setFilterView] = useState<ResultsView>(IDLE_FILTER_VIEW)
  // RFC 0017: which stored thread the chat is in, so the history list can mark
  // it and we can tell when the open thread is the one being deleted.
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const chatPanelRef = useRef<ChatPanelHandle>(null)
  // Delta-based drag: capture the pointer's starting X and the pane's
  // starting width, then apply the movement delta on every mousemove. This
  // (not the old DisplayPanel's `innerWidth - clientX`) is what makes the
  // math independent of which screen edge the pane is anchored to — this one
  // isn't anchored to any edge.
  const dragStart = useRef<{ x: number; width: number } | null>(null)

  useEffect(() => {
    function onMove(event: MouseEvent) {
      if (!dragStart.current) return
      const delta = event.clientX - dragStart.current.x
      setLeftWidth(clampWidth(dragStart.current.width + delta))
    }
    function onUp() {
      if (!dragStart.current) return
      dragStart.current = null
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.userSelect = ''
    }
  }, [])

  // The handle is a real ARIA window splitter, not a mouse-only affordance:
  // focusable, arrow-key operable, and reporting its width through
  // aria-valuenow. Found 2026-08-27 in a live browser pass — it was
  // tabIndex=-1 with a fully transparent resting background, so the only way
  // to discover OR use it was hovering the right 6px with a mouse.
  const onHandleKeyDown = useCallback((event: React.KeyboardEvent) => {
    const step =
      event.key === 'ArrowRight' || event.key === 'ArrowUp'
        ? KEYBOARD_STEP
        : event.key === 'ArrowLeft' || event.key === 'ArrowDown'
          ? -KEYBOARD_STEP
          : 0
    if (step !== 0) {
      event.preventDefault()
      setLeftWidth((current) => clampWidth(current + step))
      return
    }
    if (event.key === 'Home') {
      event.preventDefault()
      setLeftWidth(MIN_LEFT_WIDTH)
    } else if (event.key === 'End') {
      event.preventDefault()
      setLeftWidth(MAX_LEFT_WIDTH)
    }
  }, [])

  const onHandleMouseDown = useCallback(
    (event: React.MouseEvent) => {
      dragStart.current = { x: event.clientX, width: leftWidth }
      // The explicit fix for the reported "cursor starts highlighting stuff
      // as I move it" bug — the old DisplayPanel never guarded against this.
      document.body.style.userSelect = 'none'
    },
    [leftWidth],
  )

  const activeView = mode === 'chat' ? chatView : filterView
  const canClearDisplay = mode === 'chat' && activeView.cards.length > 0

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ModeToggle mode={mode} onChange={setMode} />
        {mode === 'chat' && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => chatPanelRef.current?.reset()}
              className={headerButtonClass}
            >
              <Plus size={16} aria-hidden />
              New chat
            </button>
            <HistoryMenu
              activeConversationId={activeConversationId}
              onSelect={(id) => void chatPanelRef.current?.loadConversation(id)}
              onRemoved={(removed) => {
                // Deleting the thread on screen leaves the chat pointing at
                // something that no longer exists. Its own 404 recovery would
                // survive that, but only after showing the user an error for a
                // thread they just chose to delete.
                if (removed === 'all' || removed === activeConversationId) {
                  chatPanelRef.current?.reset()
                }
              }}
            />
          </div>
        )}
      </div>

      {/* Column below `sm`, split above it. Measured 2026-08-27: as a
          flex ROW at every width, the 320px-minimum left pane plus the handle
          plus the results pane gave the document a 529px minimum width, so
          every phone viewport scrolled sideways and the results pane sat
          off-screen entirely. `max-w-full` is what lets the inline pixel width
          collapse on a narrow screen without the width itself moving into a
          media query. */}
      <div className="flex flex-col gap-3 sm:h-[640px] sm:flex-row sm:gap-0">
        <div
          role="group"
          aria-label="Search panel"
          style={{ width: leftWidth }}
          className="h-[26rem] w-full min-w-0 max-w-full sm:h-full sm:shrink-0"
        >
          <div
            id="panel-chat"
            role="tabpanel"
            aria-labelledby="tab-chat"
            hidden={mode !== 'chat'}
            className="h-full"
          >
            <ChatPanel
              ref={chatPanelRef}
              onDisplayChange={setChatView}
              onConversationChange={setActiveConversationId}
            />
          </div>
          <div
            id="panel-filter"
            role="tabpanel"
            aria-labelledby="tab-filter"
            hidden={mode !== 'filter'}
            className="vault-scroll h-full overflow-y-auto"
          >
            <FilterPanel onResultsChange={setFilterView} />
          </div>
        </div>

        <div
          role="separator"
          aria-label="Resize workspace panels"
          aria-orientation="vertical"
          aria-valuenow={leftWidth}
          aria-valuemin={MIN_LEFT_WIDTH}
          aria-valuemax={MAX_LEFT_WIDTH}
          tabIndex={0}
          onMouseDown={onHandleMouseDown}
          onKeyDown={onHandleKeyDown}
          className="mx-1 hidden w-1.5 shrink-0 cursor-col-resize rounded-full bg-pine-700 transition-colors hover:bg-mint/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mint sm:block"
        />

        <div className="min-h-[26rem] min-w-0 flex-1 sm:min-h-0">
          <ResultsPane
            {...activeView}
            onClear={canClearDisplay ? () => chatPanelRef.current?.clearDisplay() : undefined}
          />
        </div>
      </div>
    </div>
  )
}
