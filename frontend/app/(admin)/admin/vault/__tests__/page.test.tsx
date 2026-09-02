import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import AdminVaultPage from '../page'

const getMock = vi.fn()
const putMock = vi.fn()
const mockApi = {
  get: getMock, post: vi.fn(), put: putMock, patch: vi.fn(), del: vi.fn(),
  isAuthenticated: true, isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

// RFC 0022 T4a — /admin/vault joined the click-to-edit set for condition,
// cost_basis and sticker_price. dollar_net/percent_net/consigned stay
// read-only: they are computed VaultItem fields with no backing InventoryItem
// field to write to.
describe('AdminVaultPage — inline edit (RFC 0022)', () => {
  beforeEach(() => {
    getMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/vault') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1', name: 'Charizard', kind: 'raw',
            cost_basis: '10.00', current_market_value: '20.00', sticker_price: null,
            location: 'glass', condition: 'NM', condition_modifier: null,
            dollar_net: null, percent_net: null, consigned: false,
          }],
          summary: {
            total_items: 1, total_cost_basis: '10.00', total_market_value: '20.00',
            total_dollar_gain: '10.00', total_percent_gain: null,
          },
        })
      }
      return Promise.resolve({})
    })
  })

  it('edits cost_basis inline as money', async () => {
    render(<AdminVaultPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: 'Edit Price Paid' }))
    const input = screen.getByRole('textbox', { name: 'Edit Price Paid' })
    fireEvent.change(input, { target: { value: '15.00' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { cost_basis: '15' })
  })

  it('does not offer an editor for the derived $ Net / % Net columns', async () => {
    render(<AdminVaultPage />)
    await act(async () => { await Promise.resolve() })

    expect(screen.queryByRole('button', { name: 'Edit $ Net' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit % Net' })).not.toBeInTheDocument()
  })
})
