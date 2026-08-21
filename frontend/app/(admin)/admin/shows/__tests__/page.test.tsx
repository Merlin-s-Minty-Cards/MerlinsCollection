import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import AdminShowsPage from '../page'

const getMock = vi.fn()
const postMock = vi.fn()
const putMock = vi.fn()

const mockApi = {
  get: getMock, post: postMock, put: putMock, patch: vi.fn(), del: vi.fn(),
  isAuthenticated: true, isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi, AdminApiError: actual.AdminApiError }
})

const activeShow = {
  show_id: 'show-1',
  name: 'Portland Card Show',
  date: '2025-06-01',
  venue: 'Lloyd Center',
  city: 'Portland, OR',
  sales_goal: '2500.00',
  cash_at_start: '300.00',
  inventory_value_at_start: null,
  notes: null,
  archived: false,
}

const archivedShow = {
  ...activeShow,
  show_id: 'show-2',
  name: 'Typo Show',
  date: '2025-06-02',
  archived: true,
}

describe('AdminShowsPage', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    getMock.mockImplementation((_path: string, params?: Record<string, unknown>) =>
      Promise.resolve(params?.include_archived ? [activeShow, archivedShow] : [activeShow]),
    )
  })

  it('lists shows from the API', async () => {
    render(<AdminShowsPage />)

    expect(await screen.findByText('Portland Card Show')).toBeInTheDocument()
    expect(screen.getByText('Lloyd Center')).toBeInTheDocument()
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/shows', expect.anything()))
  })

  it('excludes archived shows unless the toggle is on', async () => {
    render(<AdminShowsPage />)
    await screen.findByText('Portland Card Show')

    expect(screen.queryByText('Typo Show')).not.toBeInTheDocument()
    expect(getMock).toHaveBeenCalledWith('/shows', { include_archived: false })
  })

  it('requests include_archived=true when the "show archived" toggle is enabled', async () => {
    render(<AdminShowsPage />)
    await screen.findByText('Portland Card Show')

    fireEvent.click(screen.getByLabelText(/show archived/i))

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith('/shows', { include_archived: true }),
    )
    expect(await screen.findByText('Typo Show')).toBeInTheDocument()
  })

  it('creates a show and refreshes the list', async () => {
    postMock.mockResolvedValueOnce({ ...activeShow, show_id: 'show-3', name: 'Salem Show' })
    render(<AdminShowsPage />)
    await screen.findByText('Portland Card Show')
    const callsBefore = getMock.mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: /new show/i }))
    fireEvent.change(screen.getByLabelText(/^name/i), { target: { value: 'Salem Show' } })
    fireEvent.change(screen.getByLabelText(/^date/i), { target: { value: '2025-07-04' } })
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/shows',
        expect.objectContaining({ name: 'Salem Show', date: '2025-07-04' }),
      ),
    )
    await waitFor(() => expect(getMock.mock.calls.length).toBeGreaterThan(callsBefore))
  })

  it('edits a show via PUT', async () => {
    putMock.mockResolvedValueOnce({ ...activeShow, name: 'Portland Card Show (Spring)' })
    render(<AdminShowsPage />)
    await screen.findByText('Portland Card Show')

    fireEvent.click(screen.getByLabelText('Edit Portland Card Show'))
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: 'Portland Card Show (Spring)' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^update$/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith(
        '/shows/show-1',
        expect.objectContaining({ name: 'Portland Card Show (Spring)' }),
      ),
    )
  })

  it('confirms before archiving rather than firing immediately', async () => {
    render(<AdminShowsPage />)
    await screen.findByText('Portland Card Show')

    fireEvent.click(screen.getByLabelText('Archive Portland Card Show'))

    expect(postMock).not.toHaveBeenCalled()
    expect(await screen.findByRole('button', { name: /^archive$/i })).toBeInTheDocument()
  })

  it('archives after confirming', async () => {
    postMock.mockResolvedValueOnce({ ...activeShow, archived: true })
    render(<AdminShowsPage />)
    await screen.findByText('Portland Card Show')

    fireEvent.click(screen.getByLabelText('Archive Portland Card Show'))
    fireEvent.click(await screen.findByRole('button', { name: /^archive$/i }))

    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/shows/show-1/archive'))
  })

  it('does not archive when the confirmation is cancelled', async () => {
    render(<AdminShowsPage />)
    await screen.findByText('Portland Card Show')

    fireEvent.click(screen.getByLabelText('Archive Portland Card Show'))
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }))

    await act(async () => { await Promise.resolve() })
    expect(postMock).not.toHaveBeenCalled()
  })

  it('offers unarchive for an archived show', async () => {
    postMock.mockResolvedValueOnce({ ...archivedShow, archived: false })
    render(<AdminShowsPage />)
    await screen.findByText('Portland Card Show')
    fireEvent.click(screen.getByLabelText(/show archived/i))
    await screen.findByText('Typo Show')

    fireEvent.click(screen.getByLabelText('Unarchive Typo Show'))

    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/shows/show-2/unarchive'))
  })
})
