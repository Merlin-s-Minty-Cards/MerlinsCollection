import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))

// The panels read the NextAuth session; the layout's SessionProvider isn't in
// this render tree, so stub the hook.
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: null, status: 'unauthenticated' }),
}))

import InventoryPage from '@/app/(auth)/inventory/page'

describe('Inventory page', () => {
  it('renders the inventory search heading', () => {
    render(<InventoryPage />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/inventory/i)
  })

  it('starts in filter mode with the search controls visible', () => {
    render(<InventoryPage />)
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument()
  })

  it('switches to chat mode when the chat tab is selected', async () => {
    render(<InventoryPage />)
    await userEvent.click(screen.getByRole('tab', { name: /chat/i }))
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument()
  })
})
