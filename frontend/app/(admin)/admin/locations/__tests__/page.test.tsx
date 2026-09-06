import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor, within } from '@testing-library/react'
import AdminLocationsPage from '../page'

const getMock = vi.fn()
const postMock = vi.fn()
const delMock = vi.fn()

const mockApi = {
  get: getMock, post: postMock, put: vi.fn(), patch: vi.fn(), del: delMock,
  isAuthenticated: true, isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi, AdminApiError: actual.AdminApiError }
})

describe('AdminLocationsPage', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    delMock.mockReset()
    getMock.mockResolvedValue([
      { value: 'glass', label: 'Glass' },
      { value: 'toploader', label: 'Toploader' },
    ])
  })

  it('lists existing locations', async () => {
    render(<AdminLocationsPage />)
    await act(async () => { await Promise.resolve() })
    expect(await screen.findByText('Glass')).toBeInTheDocument()
    expect(screen.getByText('Toploader')).toBeInTheDocument()
  })

  it('adds a new location via POST /admin/locations', async () => {
    postMock.mockResolvedValueOnce({ value: 'display_case_2', label: 'Display Case 2' })
    render(<AdminLocationsPage />)
    await act(async () => { await Promise.resolve() })

    // Exact match, not a loose /label/i regex: RFC 0022 gave the table's
    // Label column its own click-to-edit control, whose closed-state
    // wrapper carries an "Edit Label" aria-label that a loose regex would
    // also match.
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: 'display_case_2' } })
    fireEvent.change(screen.getByLabelText('Label'), { target: { value: 'Display Case 2' } })
    fireEvent.click(screen.getByRole('button', { name: /add location/i }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/locations', { value: 'display_case_2', label: 'Display Case 2' })
    )
  })

  it('deletes a location via DELETE /admin/locations/{value} after confirmation', async () => {
    delMock.mockResolvedValueOnce({})
    render(<AdminLocationsPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(await screen.findByLabelText('Delete Glass'))
    fireEvent.click(screen.getByRole('button', { name: /confirm|delete/i }))

    await waitFor(() => expect(delMock).toHaveBeenCalledWith('/locations/glass'))
  })

  it('surfaces the 409 detail message when deleting a location still in use', async () => {
    const { AdminApiError } = await import('@/lib/admin-api')
    delMock.mockRejectedValueOnce(new AdminApiError(409, "Location 'glass' is still in use"))
    render(<AdminLocationsPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(await screen.findByLabelText('Delete Glass'))
    fireEvent.click(screen.getByRole('button', { name: /confirm|delete/i }))

    expect(await screen.findByText("Location 'glass' is still in use")).toBeInTheDocument()
  })

  // RFC 0022 T6 — the table's Label column is click-to-edit; Value never is.
  it('edits a location label inline via PATCH', async () => {
    mockApi.patch.mockResolvedValueOnce({ value: 'glass', label: 'Display Glass' })
    render(<AdminLocationsPage />)
    await act(async () => { await Promise.resolve() })

    const row = (await screen.findByText('Glass')).closest('tr')!
    fireEvent.click(within(row).getByRole('button', { name: 'Edit Label' }))
    const input = within(row).getByRole('textbox', { name: 'Edit Label' })
    fireEvent.change(input, { target: { value: 'Display Glass' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })

    expect(mockApi.patch).toHaveBeenCalledWith('/locations/glass', { label: 'Display Glass' })
  })

  it('never offers an editor for the Value column', async () => {
    render(<AdminLocationsPage />)
    await act(async () => { await Promise.resolve() })
    await screen.findByText('Glass')
    expect(screen.queryByRole('button', { name: 'Edit Value' })).not.toBeInTheDocument()
  })
})
