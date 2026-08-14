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
})
