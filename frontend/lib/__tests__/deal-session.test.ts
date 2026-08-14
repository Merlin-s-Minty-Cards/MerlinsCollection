import { describe, it, expect, vi, beforeEach } from 'vitest'
import { sessionApiFor, type AdminApi } from '../deal-session'

describe('sessionApiFor', () => {
  const api: AdminApi = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  }

  beforeEach(() => {
    vi.mocked(api.get).mockReset()
    vi.mocked(api.post).mockReset()
    vi.mocked(api.put).mockReset()
    vi.mocked(api.patch).mockReset()
    vi.mocked(api.del).mockReset()
  })

  it('routes each mode to its own API', () => {
    expect(sessionApiFor('buy', api).supports).toEqual(
      { incoming: true, outgoing: false, costBasisMode: false })
    expect(sessionApiFor('sell', api).supports).toEqual(
      { incoming: false, outgoing: true, costBasisMode: false })
    expect(sessionApiFor('trade', api).supports).toEqual(
      { incoming: true, outgoing: true, costBasisMode: true })
  })

  it('creates a buy session against the purchases API', async () => {
    vi.mocked(api.post).mockResolvedValue({ buy_id: 'b1' })
    await sessionApiFor('buy', api).create()
    expect(api.post).toHaveBeenCalledWith('/purchases', expect.anything())
  })

  it('creates a sell session against the sales API', async () => {
    vi.mocked(api.post).mockResolvedValue({ sell_id: 's1' })
    await sessionApiFor('sell', api).create()
    expect(api.post).toHaveBeenCalledWith('/sales', expect.anything())
  })

  it('sends graded incoming fields through to the trade API', async () => {
    vi.mocked(api.post).mockResolvedValue({})
    await sessionApiFor('trade', api).addIncoming('t1', {
      card_id: 'en:base1-4', name: 'Charizard', agreed_value: 400,
      kind: 'graded', company: 'PSA', grade: 10, cert_number: '12345678',
      language: 'EN', location: 'glass',
    })
    expect(api.post).toHaveBeenCalledWith('/trades/t1/incoming',
      expect.objectContaining({ kind: 'graded', cert_number: '12345678' }))
  })

  it('patches a staged sale item price through updateOutgoing', async () => {
    vi.mocked(api.post).mockResolvedValue({ sell_id: 's1' })
    const sell = sessionApiFor('sell', api)
    await sell.create()
    await sell.addOutgoing('s1', { item_id: 'item-1', current_market_value: '20.00' } as never, 20)
    await sell.updateOutgoing('s1', 0, 15)
    expect(api.patch).toHaveBeenCalledWith('/sales/s1/items/item-1', { agreed_price: 15 })
  })

  it('patches a staged trade outgoing leg price through updateOutgoing', async () => {
    vi.mocked(api.post).mockResolvedValue({ trade_id: 't1' })
    const trade = sessionApiFor('trade', api)
    await trade.create()
    await trade.addOutgoing('t1', { item_id: 'item-2', current_market_value: '20.00' } as never, 20)
    await trade.updateOutgoing('t1', 0, 12.5)
    expect(api.patch).toHaveBeenCalledWith('/trades/t1/outgoing/item-2', { agreed_value: 12.5 })
  })

  it('refuses updateOutgoing on a buy session, which has no outgoing leg', async () => {
    await expect(sessionApiFor('buy', api).updateOutgoing('b1', 0, 5)).rejects.toThrow(
      'A buy session has no outgoing leg',
    )
  })
})
