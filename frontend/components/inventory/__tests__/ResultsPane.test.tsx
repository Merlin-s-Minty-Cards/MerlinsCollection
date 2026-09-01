import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import ResultsPane from '../ResultsPane'
import type { PresentedCard } from '@/lib/inventory'

function card(overrides: Partial<PresentedCard> = {}): PresentedCard {
  return {
    key: 'item-1',
    title: 'Charizard',
    imageUrl: 'https://img/charizard.png',
    setName: 'Base',
    number: '4',
    conditionLabel: 'NM',
    price: '250.00',
    isJapanese: false,
    ...overrides,
  }
}

describe('ResultsPane', () => {
  it('renders the header label and a card grid, not a single column', () => {
    render(
      <ResultsPane
        headerLabel="1 result"
        cards={[card()]}
        status="success"
        emptyMessage="No cards found."
      />,
    )
    expect(screen.getByText('1 result')).toBeInTheDocument()
    const heading = screen.getByRole('heading', { name: 'Charizard' })
    const grid = heading.closest('[class*="grid-cols-"]')
    expect(grid).not.toBeNull()
  })

  it('shows a loading message while a search or chat turn is in flight', () => {
    render(<ResultsPane headerLabel="" cards={[]} status="loading" emptyMessage="Empty" />)
    expect(screen.getByText(/searching/i)).toBeInTheDocument()
  })

  it('shows an error message on failure', () => {
    render(<ResultsPane headerLabel="" cards={[]} status="error" emptyMessage="Empty" />)
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
  })

  it('shows the caller-supplied empty message when there are no cards', () => {
    render(
      <ResultsPane
        headerLabel=""
        cards={[]}
        status="success"
        emptyMessage="Nothing displayed yet — ask Merlin about a card."
      />,
    )
    expect(
      screen.getByText('Nothing displayed yet — ask Merlin about a card.'),
    ).toBeInTheDocument()
  })

  it('renders a distinct empty message per mode (filter vs chat share the pane, not the copy)', () => {
    const { rerender } = render(
      <ResultsPane headerLabel="" cards={[]} status="success" emptyMessage="Filter empty" />,
    )
    expect(screen.getByText('Filter empty')).toBeInTheDocument()
    rerender(
      <ResultsPane headerLabel="" cards={[]} status="success" emptyMessage="Chat empty" />,
    )
    expect(screen.getByText('Chat empty')).toBeInTheDocument()
  })

  it('shows the truncation notice when supplied', () => {
    render(
      <ResultsPane
        headerLabel="50+ results"
        cards={[card()]}
        status="success"
        emptyMessage="Empty"
        truncatedNotice="Limited to 50 cards. Some results are not shown."
      />,
    )
    expect(
      screen.getByText('Limited to 50 cards. Some results are not shown.'),
    ).toBeInTheDocument()
  })

  it('renders no truncation notice when none is supplied', () => {
    render(
      <ResultsPane headerLabel="1 result" cards={[card()]} status="success" emptyMessage="Empty" />,
    )
    expect(screen.queryByText(/limited to/i)).toBeNull()
  })

  it('renders no clear control when onClear is omitted (filter mode has nothing to clear)', () => {
    render(
      <ResultsPane headerLabel="1 result" cards={[card()]} status="success" emptyMessage="Empty" />,
    )
    expect(screen.queryByRole('button', { name: /clear display/i })).toBeNull()
  })

  it('renders a clear control when onClear is supplied, and calls it on click', async () => {
    const user = userEvent.setup({ delay: null })
    const onClear = vi.fn()
    render(
      <ResultsPane
        headerLabel="Display (1)"
        cards={[card()]}
        status="success"
        emptyMessage="Empty"
        onClear={onClear}
      />,
    )
    await user.click(screen.getByRole('button', { name: /clear display/i }))
    expect(onClear).toHaveBeenCalledOnce()
  })

  it('renders the JP badge and price for a presented card, never just its name', () => {
    render(
      <ResultsPane
        headerLabel="1 result"
        cards={[card({ isJapanese: true, price: '120.00' })]}
        status="success"
        emptyMessage="Empty"
      />,
    )
    expect(screen.getByTitle('Japanese print')).toBeInTheDocument()
    expect(screen.getByText('$120.00')).toBeInTheDocument()
  })
})
