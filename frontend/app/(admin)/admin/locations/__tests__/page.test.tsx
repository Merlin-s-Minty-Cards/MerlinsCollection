import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
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

    fireEvent.change(screen.getByLabelText(/value/i), { target: { value: 'display_case_2' } })
    fireEvent.change(screen.getByLabelText(/label/i), { target: { value: 'Display Case 2' } })
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
})
