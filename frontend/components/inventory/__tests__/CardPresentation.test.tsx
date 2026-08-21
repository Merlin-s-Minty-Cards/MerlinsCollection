import { render, screen } from '@testing-library/react'
import type { ComponentType } from 'react'
import { describe, expect, it, vi } from 'vitest'

type Props = {
  title: string
  imageUrl?: string
  setName: string
  number?: string
  conditionLabel: string
  price: number | string
  isJapanese?: boolean
}

async function loadCardPresentation(): Promise<ComponentType<Props>> {
  try {
    const module = await vi.importActual<{ CardPresentation: ComponentType<Props> }>(
      '../CardPresentation',
    )
    return module.CardPresentation
  } catch (error) {
    expect.fail(`RFC 0016 CardPresentation is not implemented: ${String(error)}`)
  }
}

const baseProps: Props = {
  title: 'Charizard',
  imageUrl: 'https://assets.tcgdex.net/en/base/base1/4/high.webp',
  setName: 'Base Set',
  number: '4',
  conditionLabel: 'NM+',
  price: 450,
}

describe('CardPresentation', () => {
  it('renders title, image, set, number, condition, and numeric price', async () => {
    const CardPresentation = await loadCardPresentation()
    render(<CardPresentation {...baseProps} />)
    expect(screen.getByRole('heading', { name: 'Charizard' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Charizard' })).toBeInTheDocument()
    expect(screen.getByText('Base Set')).toBeInTheDocument()
    expect(screen.getByText('#4')).toBeInTheDocument()
    expect(screen.getByText('NM+')).toBeInTheDocument()
    expect(screen.getByText('$450.00')).toBeInTheDocument()
  })

  it('shows the Japanese print badge only when requested', async () => {
    const CardPresentation = await loadCardPresentation()
    const { rerender } = render(<CardPresentation {...baseProps} isJapanese />)
    expect(screen.getByText('JP')).toBeInTheDocument()
    rerender(<CardPresentation {...baseProps} isJapanese={false} />)
    expect(screen.queryByText('JP')).toBeNull()
  })

  it('renders an accessible placeholder when imageUrl is absent', async () => {
    const CardPresentation = await loadCardPresentation()
    render(<CardPresentation {...baseProps} imageUrl={undefined} />)
    expect(screen.getByRole('img', { name: 'Charizard' })).toBeInTheDocument()
  })

  it('accepts a preformatted price without reformatting it', async () => {
    const CardPresentation = await loadCardPresentation()
    render(<CardPresentation {...baseProps} price="Price N/A" />)
    expect(screen.getByText('Price N/A')).toBeInTheDocument()
  })
})
