import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import CardImage from '../CardImage'

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
