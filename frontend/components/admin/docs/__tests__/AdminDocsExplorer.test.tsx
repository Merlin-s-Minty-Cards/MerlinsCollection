import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminDocsExplorer from '@/components/admin/docs/AdminDocsExplorer'
import { useAdminDocs } from '@/lib/use-admin-docs'

vi.mock('@/lib/use-admin-docs', () => ({
  useAdminDocs: vi.fn(),
}))

const mockedUseAdminDocs = vi.mocked(useAdminDocs)

const CATEGORIES = [
  { id: 'money', label: 'Money & Calculations' },
  { id: 'costs', label: 'Costs, Quotas & Schedules' },
]

const ARTICLES = [
  {
    id: 'acquisition-ratio',
    category: 'money',
    title: 'The acquisition-ratio percentage',
    summary: 'Market value at purchase divided by what you paid.',
    body: 'Full explanation mentions PLATYPUS as a unique body-only word.',
    keywords: ['ratio', 'trade'],
    related_routes: ['/admin/trade'],
  },
  {
    id: 'sync-prices-cost',
    category: 'costs',
    title: 'Sync Prices cost and cadence',
    summary: 'Roughly 50 lookups a day.',
    body: 'It already runs overnight automatically.',
    keywords: ['sync', 'quota'],
    related_routes: ['/admin/market'],
  },
]

function mockDocs(overrides: Partial<ReturnType<typeof useAdminDocs>> = {}) {
  mockedUseAdminDocs.mockReturnValue({
    categories: CATEGORIES,
    articles: ARTICLES,
    loading: false,
    error: false,
    ...overrides,
  })
}

describe('AdminDocsExplorer', () => {
  beforeEach(() => {
    mockedUseAdminDocs.mockReset()
  })

  it('shows a loading state while docs are loading', () => {
    mockDocs({ loading: true, categories: [], articles: [] })
    render(<AdminDocsExplorer />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('shows an error state when the fetch failed', () => {
    mockDocs({ error: true, categories: [], articles: [] })
    render(<AdminDocsExplorer />)
    expect(screen.getByText(/couldn.t load/i)).toBeInTheDocument()
  })

  it('renders category tabs from the fetched categories, not a hardcoded list', () => {
    mockDocs()
    render(<AdminDocsExplorer />)
    expect(screen.getByRole('button', { name: 'Money & Calculations' })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Costs, Quotas & Schedules' }),
    ).toBeInTheDocument()
  })

  it('defaults to showing the first category, not every article at once', () => {
    mockDocs()
    render(<AdminDocsExplorer />)
    expect(screen.getByText('The acquisition-ratio percentage')).toBeInTheDocument()
    expect(screen.queryByText('Sync Prices cost and cadence')).not.toBeInTheDocument()
  })

  it('switching category shows only that category\'s articles', async () => {
    mockDocs()
    render(<AdminDocsExplorer />)
    await userEvent.setup({ delay: null }).click(
      screen.getByRole('button', { name: 'Costs, Quotas & Schedules' }),
    )
    expect(screen.getByText('Sync Prices cost and cadence')).toBeInTheDocument()
    expect(screen.queryByText('The acquisition-ratio percentage')).not.toBeInTheDocument()
  })

  it('a non-empty search query overrides the category filter and searches everything', async () => {
    mockDocs()
    render(<AdminDocsExplorer />)
    // Currently on the default (money) category; search for a term that
    // only lives in the OTHER category's body.
    await userEvent.setup({ delay: null }).type(
      screen.getByRole('textbox', { name: /search/i }),
      'overnight',
    )
    expect(screen.getByText('Sync Prices cost and cadence')).toBeInTheDocument()
    expect(screen.queryByText('The acquisition-ratio percentage')).not.toBeInTheDocument()
  })

  it('search matches body text, not just the title', async () => {
    mockDocs()
    render(<AdminDocsExplorer />)
    await userEvent.setup({ delay: null }).type(
      screen.getByRole('textbox', { name: /search/i }),
      'PLATYPUS',
    )
    expect(screen.getByText('The acquisition-ratio percentage')).toBeInTheDocument()
  })

  it('shows a no-results message for a query that matches nothing', async () => {
    mockDocs()
    render(<AdminDocsExplorer />)
    await userEvent.setup({ delay: null }).type(
      screen.getByRole('textbox', { name: /search/i }),
      'zzz-nonexistent-zzz',
    )
    expect(screen.getByText(/no.*match/i)).toBeInTheDocument()
  })

  it('clicking an article reveals its body', async () => {
    mockDocs()
    render(<AdminDocsExplorer />)
    await userEvent.setup({ delay: null }).click(
      screen.getByText('The acquisition-ratio percentage'),
    )
    expect(
      within(screen.getByTestId('admin-docs-article-body')).getByText(/PLATYPUS/),
    ).toBeInTheDocument()
  })
})
