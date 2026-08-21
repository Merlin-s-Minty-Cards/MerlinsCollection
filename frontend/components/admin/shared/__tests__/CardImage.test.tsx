import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import CardImage, { TABLE_THUMB_SIZE, TABLE_THUMB_COLUMN } from '../CardImage'

describe('CardImage table thumbnail', () => {
  // The four list pages each picked their own size by hand and drifted:
  // Prep Queue rendered `lg` (224x320) while Inventory, Vault and Show Prep
  // rendered `md` (160x224), and every one of them overflowed its own column
  // (w-16/w-24), which is why the images read as oversized. One exported
  // constant is the fix — a page cannot pick a different size by accident.
  it('is xs — roughly a third of the old md width', () => {
    expect(TABLE_THUMB_SIZE).toBe('xs')
  })

  it('renders xs at 56x78, a real card aspect ratio', () => {
    render(<CardImage imageUrl="x.png" alt="a" size="xs" />)

    const img = screen.getByRole('img')
    expect(img.className).toContain('w-14')
    expect(img.className).toContain('h-[4.875rem]')
  })

  it('fits inside its column instead of overflowing it', () => {
    // w-14 is 56px and the column is w-16 (64px). The old pairing put a 160px
    // image in a 64px cell, which is what forced the row heights up.
    expect(TABLE_THUMB_COLUMN).toBe('w-16')
  })

  it('sizes the empty-state placeholder identically, so rows do not jump', () => {
    render(<CardImage imageUrl={null} alt="a" size="xs" />)

    const fallback = screen.getByLabelText('No image for a')
    expect(fallback.className).toContain('w-14')
    expect(fallback.className).toContain('h-[4.875rem]')
  })
})

describe('CardImage', () => {
  it('renders the img with the size classes for the requested size', () => {
    render(<CardImage imageUrl="x.png" alt="a" size="md" />)

    const img = screen.getByRole('img')
    expect(img.className).toContain('w-40')
    expect(img.className).toContain('h-56')
  })

  it('renders the fallback box with the size classes when imageUrl is null', () => {
    render(<CardImage imageUrl={null} alt="a" size="md" />)

    const fallback = screen.getByLabelText('No image for a')
    expect(fallback.className).toContain('w-40')
    expect(fallback.className).toContain('h-56')
  })

  it('renders eager loading when loading="eager" is passed', () => {
    render(<CardImage imageUrl="https://example.com/card.png" alt="Pikachu" loading="eager" />)
    expect(screen.getByAltText('Pikachu')).toHaveAttribute('loading', 'eager')
  })

  it('defaults to lazy loading when no loading prop is passed', () => {
    render(<CardImage imageUrl="https://example.com/card.png" alt="Pikachu" />)
    expect(screen.getByAltText('Pikachu')).toHaveAttribute('loading', 'lazy')
  })
})
