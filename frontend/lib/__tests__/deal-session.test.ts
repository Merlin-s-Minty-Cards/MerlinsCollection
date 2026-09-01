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
      { incoming: true, outgoing: false })
    expect(sessionApiFor('sell', api).supports).toEqual(
      { incoming: false, outgoing: true })
    expect(sessionApiFor('trade', api).supports).toEqual(
      { incoming: true, outgoing: true })
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

  it('sends the picked card market_value through on a buy incoming leg (final-review Important 7)', async () => {
    // purchases.py reads market_value into market_value_at_purchase and
    // current_market_value — dropping it left every Buy-mode item with no
    // stored market figure even though the picker supplied one.
    vi.mocked(api.post).mockResolvedValue({})
    await sessionApiFor('buy', api).addIncoming('b1', {
      card_id: 'en:base1-4', name: 'Charizard', agreed_value: 40,
      kind: 'raw', condition: 'NM', market_value: 120, language: 'EN', location: 'glass',
    })
    expect(api.post).toHaveBeenCalledWith('/purchases/b1/items',
      expect.objectContaining({ market_value: 120 }))
  })

  it('sends market_value: null on a buy incoming leg with no picked-card figure', async () => {
    vi.mocked(api.post).mockResolvedValue({})
    await sessionApiFor('buy', api).addIncoming('b1', {
      card_id: null, name: 'Manual entry', agreed_value: 5,
      kind: 'raw', condition: 'NM', language: 'EN', location: 'glass',
    })
    expect(api.post).toHaveBeenCalledWith('/purchases/b1/items',
      expect.objectContaining({ market_value: null }))
  })

  it('patches a staged sale item price through updateOutgoing, keyed by item_id', async () => {
    vi.mocked(api.post).mockResolvedValue({ sell_id: 's1' })
    const sell = sessionApiFor('sell', api)
    await sell.create()
    await sell.addOutgoing('s1', { item_id: 'item-1', current_market_value: '20.00' } as never, 20)
    await sell.updateOutgoing('s1', 'item-1', 15)
    expect(api.patch).toHaveBeenCalledWith('/sales/s1/items/item-1', { agreed_price: 15 })
  })

  it('patches a staged trade outgoing leg price through updateOutgoing, keyed by item_id', async () => {
    vi.mocked(api.post).mockResolvedValue({ trade_id: 't1' })
    const trade = sessionApiFor('trade', api)
    await trade.create()
    await trade.addOutgoing('t1', { item_id: 'item-2', current_market_value: '20.00' } as never, 20)
    await trade.updateOutgoing('t1', 'item-2', 12.5)
    expect(api.patch).toHaveBeenCalledWith('/trades/t1/outgoing/item-2', { agreed_value: 12.5 })
  })

  it('removes a staged sale item by item_id, without needing a prior addOutgoing in the same closure', async () => {
    // Regression for final-review Critical 3: the adapter used to keep a
    // local index -> item_id Map that was lost whenever `sessionApiFor`'s
    // memo re-ran with a fresh `api` (e.g. a token refresh). A fresh
    // `sellApi(api)` here simulates exactly that — it has never seen
    // `addOutgoing` for this item, yet remove/update must still work because
    // the caller now hands over the real id directly.
    const freshSell = sessionApiFor('sell', api)
    await freshSell.removeOutgoing('s1', 'item-9')
    expect(api.del).toHaveBeenCalledWith('/sales/s1/items/item-9')
    await freshSell.updateOutgoing('s1', 'item-9', 7)
    expect(api.patch).toHaveBeenCalledWith('/sales/s1/items/item-9', { agreed_price: 7 })
  })

  it('removes a staged trade outgoing leg by item_id on a fresh adapter instance', async () => {
    const freshTrade = sessionApiFor('trade', api)
    await freshTrade.removeOutgoing('t1', 'item-9')
    expect(api.del).toHaveBeenCalledWith('/trades/t1/outgoing/item-9')
  })

  it('refuses updateOutgoing on a buy session, which has no outgoing leg', async () => {
    await expect(sessionApiFor('buy', api).updateOutgoing('b1', 'item-1', 5)).rejects.toThrow(
      'A buy session has no outgoing leg',
    )
  })

  it('sends graded fields through to the purchases items API (Critical 1 regression)', async () => {
    vi.mocked(api.post).mockResolvedValue({})
    await sessionApiFor('buy', api).addIncoming('b1', {
      card_id: 'en:base1-4', name: 'Charizard', agreed_value: 400,
      kind: 'graded', company: 'PSA', grade: 10, cert_number: '12345678',
      language: 'EN', location: 'glass',
    })
    expect(api.post).toHaveBeenCalledWith('/purchases/b1/items', expect.objectContaining({
      kind: 'graded', company: 'PSA', grade: 10, cert_number: '12345678',
    }))
  })
})
