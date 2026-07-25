import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import ShowsPage from '@/app/(public)/shows/page'

describe('Shows page', () => {
  it('renders the page heading', () => {
    render(<ShowsPage />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/show/i)
  })

  it('separates upcoming and past shows', () => {
    render(<ShowsPage />)
    expect(screen.getByRole('heading', { name: /upcoming shows/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /past shows/i })).toBeInTheDocument()
  })

  it('lists a real upcoming show from the show records', () => {
    render(<ShowsPage />)
    expect(screen.getByText('Seattle Trading Card Con')).toBeInTheDocument()
    expect(screen.getByText('Aug 14–16, 2026')).toBeInTheDocument()
  })

  it('links to the contact section for bookings', () => {
    render(<ShowsPage />)
    expect(screen.getByRole('link', { name: /get in touch/i })).toHaveAttribute(
      'href',
      '/about#contact',
    )
  })
})
