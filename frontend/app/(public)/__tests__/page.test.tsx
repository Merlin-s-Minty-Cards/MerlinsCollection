import { render, screen } from '@testing-library/react'

import HomePage from '@/app/(public)/page'

describe('Home page', () => {
  it('renders the BuySellTrade and LearnHub headings not covered by their own component tests', () => {
    render(<HomePage />)
    ;['Three reasons to stop by our table.', 'Let us help you'].forEach((t) =>
      expect(screen.getByRole('heading', { level: 2, name: t })).toBeInTheDocument(),
    )
  })
})
