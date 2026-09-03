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

  // final-review Fix 5 (Important) — a staged consignor was stored on
  // `StagedIncoming.consignorId` but never rendered, so the operator had no
  // way to verify what they staged before confirming.
  it('renders the staged consignor label when present', () => {
    render(<DealCardRow card={card({ consignorLabel: 'Alex' })} onAdd={vi.fn()} />)
    expect(screen.getByText(/consignor:\s*alex/i)).toBeInTheDocument()
  })

  it('omits the consignor line entirely when none is staged', () => {
    render(<DealCardRow card={card({ consignorLabel: null })} onAdd={vi.fn()} />)
    expect(screen.queryByText(/consignor:/i)).not.toBeInTheDocument()
  })

  // RFC 0024 T2 — market / paid / ratio on every deal row.
  describe('acquisition line', () => {
    it('renders market, paid and ratio together', () => {
      render(
        <DealCardRow
          card={card({ marketValue: '100.00', pricePaid: '32.00', showRatio: true })}
          onAdd={vi.fn()}
        />,
      )
      expect(screen.getByText(/market\s*\$100\.00/i)).toBeInTheDocument()
      expect(screen.getByText(/paid\s*\$32\.00/i)).toBeInTheDocument()
      expect(screen.getByText('313%')).toBeInTheDocument()
    })

    it('does not render the acquisition line for a row kind that carries neither field', () => {
      render(<DealCardRow card={card()} onAdd={vi.fn()} />)
      expect(screen.queryByText(/market\s*\$/i)).not.toBeInTheDocument()
    })

    it('renders an absent market or paid figure as a dash, never $0.00', () => {
      render(
        <DealCardRow
          card={card({ marketValue: null, pricePaid: null, showRatio: true })}
          onAdd={vi.fn()}
        />,
      )
      expect(screen.getByText(/market\s*—/i)).toBeInTheDocument()
      expect(screen.getByText(/paid\s*—/i)).toBeInTheDocument()
    })

    it('renders no ratio chip at all when the ratio is undefined, not a grey zero', () => {
      render(
        <DealCardRow
          card={card({ marketValue: '100.00', pricePaid: null, showRatio: true })}
          onAdd={vi.fn()}
        />,
      )
      expect(screen.queryByText(/%/)).not.toBeInTheDocument()
    })

    it('hides the ratio under customer view while keeping market visible', () => {
      render(
        <DealCardRow
          card={card({ marketValue: '100.00', pricePaid: '32.00', showRatio: false })}
          onAdd={vi.fn()}
        />,
      )
      expect(screen.getByText(/market\s*\$100\.00/i)).toBeInTheDocument()
      expect(screen.queryByText('313%')).not.toBeInTheDocument()
    })

    it('omits the paid segment entirely when the caller does not pass it (customer view)', () => {
      render(
        <DealCardRow
          card={card({ marketValue: '100.00', pricePaid: undefined, showRatio: false })}
          onAdd={vi.fn()}
        />,
      )
      expect(screen.queryByText(/paid/i)).not.toBeInTheDocument()
    })
  })
})
