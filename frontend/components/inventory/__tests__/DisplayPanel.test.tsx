import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentType } from 'react'
import { describe, expect, it, vi } from 'vitest'

type DisplayedCard = {
  item_id: string
  kind: 'raw'
  card: {
    card_id: string
    name: string
    set_name: string
    number: string
    image_small: string
  }
  display_name: string | null
  listed_price: string
  current_market_value: string | null
  condition: string | null
  company: null
  grade: null
  grade_label: null
  cert_number: null
  language: string | null
}

type Props = {
  cards: DisplayedCard[]
  truncated: boolean
  onClose: () => void
}

async function loadDisplayPanel(): Promise<ComponentType<Props>> {
  try {
    const imported = await vi.importActual<{ DisplayPanel: ComponentType<Props> }>(
      '../DisplayPanel',
    )
    return imported.DisplayPanel
  } catch (error) {
    expect.fail(`RFC 0016 DisplayPanel is not implemented: ${String(error)}`)
  }
}

function card(item_id = 'item-1'): DisplayedCard {
  return {
    item_id,
    kind: 'raw',
    card: {
      card_id: 'en:base1-4',
      name: 'Charizard',
      set_name: 'Base Set',
      number: '4',
      image_small: 'https://assets.tcgdex.net/en/base/base1/4/low.webp',
    },
    display_name: null,
    listed_price: '275.00',
    current_market_value: '450.00',
    condition: 'LP',
    company: null,
    grade: null,
    grade_label: null,
    cert_number: null,
    language: 'EN',
  }
}

describe('DisplayPanel', () => {
  it('renders nothing when cards is empty (closed state)', async () => {
    const DisplayPanel = await loadDisplayPanel()
    
    // Empty cards = closed, component renders nothing
    const { container } = render(
      <DisplayPanel cards={[]} truncated={false} onClose={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders docked when cards is non-empty (open state)', async () => {
    const DisplayPanel = await loadDisplayPanel()
    render(<DisplayPanel cards={[card()]} truncated={false} onClose={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Display (1)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fullscreen' })).toBeInTheDocument()
  })

  it('renders hydrated cards in the docked grid', async () => {
    const DisplayPanel = await loadDisplayPanel()
    render(<DisplayPanel cards={[card()]} truncated={false} onClose={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Charizard' })).toBeInTheDocument()
    // listed_price ($275.00) must win over current_market_value ($450.00):
    // after RFC-0016's backend fix, listed_price is the RESOLVED,
    // condition-adjusted price (mirrors routers/inventory.py::_display_price)
    // while current_market_value is a separate, potentially stale pass-through.
    // Council r2 self-review flagged this precedence as backwards; fixed here.
    expect(screen.getByText('$275.00')).toBeInTheDocument()
    expect(screen.queryByText('$450.00')).not.toBeInTheDocument()
  })

  it('falls back to current_market_value when listed_price is null', async () => {
    const DisplayPanel = await loadDisplayPanel()
    const noListedPrice = { ...card(), listed_price: null as unknown as string }
    render(<DisplayPanel cards={[noListedPrice]} truncated={false} onClose={vi.fn()} />)
    expect(screen.getByText('$450.00')).toBeInTheDocument()
  })

  it('shows the JP badge for an uncatalogued Japanese item', async () => {
    // RFC-0016 Council r2 (advisor-architect M4 / advisor-contrarian): the
    // badge used to be inferred from card.card_id.startsWith('ja:'), which
    // is unavailable when the item has no catalog match (card: null) --
    // exactly the case this test pins. language is on DisplayedCard itself,
    // independent of any catalog match.
    const DisplayPanel = await loadDisplayPanel()
    const uncataloguedJp = { ...card(), card: null, language: 'JP' }
    render(<DisplayPanel cards={[uncataloguedJp]} truncated={false} onClose={vi.fn()} />)
    expect(screen.getByTitle('Japanese print')).toBeInTheDocument()
  })

  it('shows the 50-card truncation notice', async () => {
    const DisplayPanel = await loadDisplayPanel()
    render(<DisplayPanel cards={[card()]} truncated onClose={vi.fn()} />)
    expect(screen.getByText(/limited to 50 cards/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Display (1+)' })).toBeInTheDocument()
  })

  it('calls onClose when the user closes the panel', async () => {
    const DisplayPanel = await loadDisplayPanel()
    const onClose = vi.fn()
    render(<DisplayPanel cards={[card()]} truncated={false} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('fullscreen is controlled only by local user button clicks', async () => {
    const DisplayPanel = await loadDisplayPanel()
    render(<DisplayPanel cards={[card()]} truncated={false} onClose={vi.fn()} />)

    expect(screen.queryByRole('button', { name: 'Dock' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Fullscreen' }))
    expect(screen.getByRole('button', { name: 'Dock' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Dock' }))
    expect(screen.getByRole('button', { name: 'Fullscreen' })).toBeInTheDocument()
  })

  it('is desktop-only through responsive visibility classes', async () => {
    const DisplayPanel = await loadDisplayPanel()
    const { container } = render(
      <DisplayPanel cards={[card()]} truncated={false} onClose={vi.fn()} />,
    )
    const root = container.firstElementChild
    expect(root).toHaveClass('hidden')
    expect(root).toHaveClass('lg:block')
  })
})
