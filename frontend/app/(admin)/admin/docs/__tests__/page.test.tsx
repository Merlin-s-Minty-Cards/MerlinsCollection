import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import AdminDocsPage from '../page'

vi.mock('@/components/admin/docs/AdminDocsExplorer', () => ({
  default: () => <div data-testid="explorer-stub">explorer</div>,
}))

describe('AdminDocsPage', () => {
  it('renders a heading and the docs explorer', () => {
    render(<AdminDocsPage />)
    expect(screen.getByRole('heading', { name: /docs/i })).toBeInTheDocument()
    expect(screen.getByTestId('explorer-stub')).toBeInTheDocument()
  })
})
