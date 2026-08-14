import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DealCardRow, { type DealRowCard } from '../DealCardRow'

/**
 * RFC 0011 T14 — one row shape for search results, Coming In, Going Out and
 * the confirm dialog. Image, name and price are always together and nothing
 * is revealed by a hover.
 */

function card(over: Partial<DealRowCard> & { image?: string | null; price?: string | null } = {}): DealRowCard {
  const { image, price, ...rest } = over
  return {
    card_id: 'en:base1-4',
    name: 'Charizard',
    meta: 'Base Set · #4 · Rare',
    imageUrl: image === undefined ? 'https://i/1.png' : image,
    price: price === undefined ? '120.00' : price,
    priceLabel: 'market',
    ...rest,
  }
}

describe('DealCardRow', () => {
  it('shows image, name and price together', () => {
    render(<DealCardRow card={card({ name: 'Charizard', image: 'https://i/1.png', price: '120.00' })} onAdd={vi.fn()} />)
    expect(screen.getByRole('img', { name: /charizard/i })).toBeInTheDocument()
    expect(screen.getByText('Charizard')).toBeInTheDocument()
    expect(screen.getByText('$120.00')).toBeInTheDocument()
  })

  it('labels a catalog figure as market, never as a sale price', () => {
    render(<DealCardRow card={card()} onAdd={vi.fn()} />)
    expect(screen.getByText('market')).toBeInTheDocument()
  })

  it('reveals nothing on hover', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealCardRow card={card({ name: 'Charizard' })} onAdd={vi.fn()} />)
    const before = screen.getByRole('img', { name: /charizard/i })
    await user.hover(screen.getByText('Charizard'))
    expect(screen.getByRole('img', { name: /charizard/i })).toBe(before)
  })

  it('renders a placeholder rather than collapsing when art is missing', () => {
    render(<DealCardRow card={card({ image: null })} onAdd={vi.fn()} />)
    expect(screen.getByTestId('card-image-placeholder')).toBeInTheDocument()
  })

  it('renders an absent price as a dash, never as zero', () => {
    render(<DealCardRow card={card({ price: null })} onAdd={vi.fn()} />)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
  })

  it('names the card in its action label', () => {
    render(<DealCardRow card={card({ name: 'Charizard' })} onAdd={vi.fn()} />)
    expect(screen.getByRole('button', { name: /charizard/i })).toBeInTheDocument()
  })

  it('hands the whole card back to onAdd', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<DealCardRow card={card()} onAdd={onAdd} />)
    await user.click(screen.getByRole('button', { name: /charizard/i }))
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ card_id: 'en:base1-4' }))
  })

  it('renders without an action when none is wanted', () => {
    render(<DealCardRow card={card()} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('Charizard')).toBeInTheDocument()
  })
})
