import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CosignorPicker from '../CosignorPicker'

vi.mock('@/lib/use-cosigners', () => ({
  useCosigners: () => ({
    options: [
      { value: 'c1', label: 'Alex' },
      { value: 'c2', label: 'Bailey' },
    ],
    loading: false,
  }),
}))

describe('CosignorPicker', () => {
  it('filters the dropdown as the admin types', async () => {
    const user = userEvent.setup({ delay: null })
    render(<CosignorPicker value={null} onChange={vi.fn()} />)
    const input = screen.getByRole('combobox', { name: /consignor/i })
    await user.type(input, 'bai')
    expect(screen.getByText('Bailey')).toBeInTheDocument()
    expect(screen.queryByText('Alex')).not.toBeInTheDocument()
  })

  it('calls onChange with the consignor_id when an option is picked', async () => {
    const user = userEvent.setup({ delay: null })
    const onChange = vi.fn()
    render(<CosignorPicker value={null} onChange={onChange} />)
    await user.click(screen.getByRole('combobox', { name: /consignor/i }))
    await user.click(screen.getByText('Alex'))
    expect(onChange).toHaveBeenCalledWith('c1')
  })

  it('offers a clear option that calls onChange(null)', async () => {
    const user = userEvent.setup({ delay: null })
    const onChange = vi.fn()
    render(<CosignorPicker value="c1" onChange={onChange} />)
    await user.click(screen.getByRole('button', { name: /clear consignor/i }))
    expect(onChange).toHaveBeenCalledWith(null)
  })

  describe('blur-then-unmount', () => {
    it('clears the blur-close timeout on unmount so it never fires afterward', () => {
      const clearSpy = vi.spyOn(window, 'clearTimeout')

      const { unmount } = render(<CosignorPicker value={null} onChange={vi.fn()} />)
      const input = screen.getByRole('combobox', { name: /consignor/i })

      fireEvent.blur(input)
      unmount()

      expect(clearSpy).toHaveBeenCalled()
      clearSpy.mockRestore()
    })

    it('does not touch state after unmounting during the blur-close delay', async () => {
      const { unmount } = render(<CosignorPicker value={null} onChange={vi.fn()} />)
      const input = screen.getByRole('combobox', { name: /consignor/i })

      fireEvent.blur(input)
      // Unmount before the real 150ms blur-close timeout fires.
      unmount()

      // Wait past the 150ms delay with real timers, matching how other
      // suites (CardDetailModal, Trade page) already have to work around
      // this exact leak. Nothing should throw here.
      await new Promise((resolve) => setTimeout(resolve, 200))
    })
  })
})
