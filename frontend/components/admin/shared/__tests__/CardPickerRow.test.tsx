import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import CardPickerRow, { type PickerCard } from '../CardPickerRow'

/**
 * T15 — one candidate row, five callers.
 * docs/plans/rfc-0010/t15-card-picker-images.md
 *
 * The contract is CLAUDE.md's standing rule ("A CARD IS NEVER IDENTIFIED BY
 * NAME ALONE"): every surface where a human picks a card out of a list shows
 * name, image AND price. The image answers "is this the card?"; the price
 * answers "what do I do about it?", which at a buy table is the only question
 * that matters.
 *
 * The absent-price states are the MAIN cases, not the edges: most of the
 * 31,603 catalog rows carry no price until T17's weekly cycle fills them in.
 */

const card: PickerCard = {
  card_id: 'en:base1-4',
  name: 'Charizard',
  set_id: 'base1',
  set_name: 'Base Set',
  number: '4',
  rarity: 'Rare Holo',
  images: { small: 'https://img.example/charizard.webp' },
  display_price: '189.99',
  display_finish: 'holofoil',
  detail: 'full',
  last_synced_at: new Date().toISOString(),
}

/** N days before now, as an ISO string. */
function daysAgo(n: number): string {
  return new Date(Date.now() - n * 24 * 60 * 60 * 1000).toISOString()
}

describe('CardPickerRow', () => {
  it('renders the card art through CardImage', () => {
    render(<CardPickerRow card={card} onSelect={() => {}} />)
    const img = screen.getByAltText('Charizard') as HTMLImageElement
    expect(img.tagName).toBe('IMG')
    expect(img.src).toBe('https://img.example/charizard.webp')
  })

  it('renders the name, set, number and rarity', () => {
    render(<CardPickerRow card={card} onSelect={() => {}} />)
    expect(screen.getByText('Charizard')).toBeInTheDocument()
    const meta = screen.getByText(/Base Set/)
    expect(meta.textContent).toContain('#4')
    expect(meta.textContent).toContain('Rare Holo')
  })

  it('renders the price', () => {
    render(<CardPickerRow card={card} onSelect={() => {}} />)
    expect(screen.getByText('$189.99')).toBeInTheDocument()
  })

  it('shows the finish when it is not normal, and omits it when it is', () => {
    const { unmount } = render(<CardPickerRow card={card} onSelect={() => {}} />)
    expect(screen.getByText('holofoil')).toBeInTheDocument()
    unmount()

    render(
      <CardPickerRow
        card={{ ...card, display_finish: 'normal' }}
        onSelect={() => {}}
      />,
    )
    expect(screen.queryByText('normal')).not.toBeInTheDocument()
  })

  it('renders "no price yet" for a brief row — never $0.00, never blank', () => {
    render(
      <CardPickerRow
        card={{ ...card, display_price: null, display_finish: null, detail: 'brief' }}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByText(/no price yet/i)).toBeInTheDocument()
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
  })

  it('renders "not priced" for a full row with no price — a DIFFERENT string from "no price yet"', () => {
    // The whole reason `detail` exists: "we never fetched a price" and "no
    // provider covers this card" are different facts, and only the second one
    // means waiting will not help.
    const brief = render(
      <CardPickerRow
        card={{ ...card, display_price: null, display_finish: null, detail: 'brief' }}
        onSelect={() => {}}
      />,
    )
    const briefText = screen.getByTestId('card-picker-price').textContent
    brief.unmount()

    render(
      <CardPickerRow
        card={{ ...card, display_price: null, display_finish: null, detail: 'full' }}
        onSelect={() => {}}
      />,
    )
    const fullText = screen.getByTestId('card-picker-price').textContent

    expect(fullText).toMatch(/not priced/i)
    expect(fullText).not.toBe(briefText)
    expect(fullText).not.toContain('$0.00')
  })

  it('shows the age alongside the figure when the price is stale', () => {
    render(
      <CardPickerRow
        card={{ ...card, last_synced_at: daysAgo(90) }}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByText('$189.99')).toBeInTheDocument()
    expect(screen.getByText(/90d ago/)).toBeInTheDocument()
  })

  it('does not shout about age on a fresh price', () => {
    render(<CardPickerRow card={{ ...card, last_synced_at: daysAgo(2) }} onSelect={() => {}} />)
    expect(screen.queryByText(/ago/)).not.toBeInTheDocument()
  })

  it('renders the placeholder for a card with no image, not a collapsed row', () => {
    // A row that changes height as art loads makes the list jump under the
    // cursor mid-click — which on a picker means selecting the wrong card.
    render(<CardPickerRow card={{ ...card, images: undefined }} onSelect={() => {}} />)
    expect(screen.getByTestId('card-picker-row')).toBeInTheDocument()
    expect(screen.getByLabelText('No image for Charizard')).toBeInTheDocument()
  })

  it('truncates a long name instead of displacing the image or the price', () => {
    const longName = 'Charizard VMAX Rainbow Rare Secret Illustration Alternate Art Promo'
    render(
      <CardPickerRow card={{ ...card, name: longName }} onSelect={() => {}} />,
    )
    expect(screen.getByText(longName).className).toContain('truncate')

    const text = screen.getByTestId('card-picker-text')
    expect(text.className).toContain('min-w-0')

    const img = screen.getByAltText(longName)
    expect(img.className).toContain('flex-shrink-0')

    // A truncated price is worse than no price, so the price column never
    // shrinks and never truncates.
    const price = screen.getByTestId('card-picker-price')
    expect(price.className).toContain('flex-shrink-0')
    expect(price.className).not.toContain('truncate')
  })

  it('shows the card_id as tertiary mono text — it is how a re-point is verified', () => {
    render(<CardPickerRow card={card} onSelect={() => {}} />)
    expect(screen.getByText('en:base1-4')).toBeInTheDocument()
  })

  it('fires onSelect with the card', () => {
    const onSelect = vi.fn()
    render(<CardPickerRow card={card} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: /Charizard/ }))
    expect(onSelect).toHaveBeenCalledWith(card)
  })

  it('renders a custom action instead of relying on a row click', () => {
    const onUse = vi.fn()
    render(
      <CardPickerRow
        card={card}
        action={<button type="button" onClick={onUse}>Use this name</button>}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /use this name/i }))
    expect(onUse).toHaveBeenCalledTimes(1)
    // Still a full row: art and price do not disappear because the caller
    // supplied its own action.
    expect(screen.getByAltText('Charizard')).toBeInTheDocument()
    expect(screen.getByText('$189.99')).toBeInTheDocument()
  })
})
