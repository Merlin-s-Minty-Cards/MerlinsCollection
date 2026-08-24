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
    set_id: string
    set_name: string
    number: string
    rarity: string | null
    image_small: string
    image_large: string
    market_price: string | null
  }
  display_name: string | null
  listed_price: string
  current_market_value: string | null
  condition: string | null
  finish: string | null
  company: null
  grade: null
  grade_label: null
  cert_number: null
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
      set_id: 'base1',
      set_name: 'Base Set',
      number: '4',
      rarity: 'Rare Holo',
      image_small: 'https://assets.tcgdex.net/en/base/base1/4/low.webp',
      image_large: 'https://assets.tcgdex.net/en/base/base1/4/high.webp',
      market_price: '450.00',
    },
    display_name: null,
    listed_price: '275.00',
    current_market_value: '450.00',
    condition: 'LP',
    finish: 'holofoil',
    company: null,
    grade: null,
    grade_label: null,
    cert_number: null,
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
    expect(screen.getByText('$450.00')).toBeInTheDocument()
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
