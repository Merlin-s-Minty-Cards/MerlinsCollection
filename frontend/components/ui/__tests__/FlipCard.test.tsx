import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FlipCard from '@/components/ui/FlipCard'

describe('FlipCard', () => {
  it('renders both faces', () => {
    render(<FlipCard front={<span>FRONT</span>} back={<span>BACK</span>} />)
    expect(screen.getByText('FRONT')).toBeInTheDocument()
    expect(screen.getByText('BACK')).toBeInTheDocument()
  })

  it('exposes an accessible toggle button with the given label', () => {
    render(<FlipCard front={<span>F</span>} back={<span>B</span>} label="Lapras card" />)
    const stage = screen.getByRole('button', { name: 'Lapras card' })
    expect(stage).toHaveAttribute('data-flipped', 'false')
  })

  it('toggles flipped state on click', async () => {
    const user = userEvent.setup()
    render(<FlipCard front={<span>F</span>} back={<span>B</span>} label="card" />)
    const stage = screen.getByRole('button', { name: 'card' })
    await user.click(stage)
    expect(stage).toHaveAttribute('data-flipped', 'true')
    await user.click(stage)
    expect(stage).toHaveAttribute('data-flipped', 'false')
  })

  it('toggles flipped state on Enter key', async () => {
    const user = userEvent.setup()
    render(<FlipCard front={<span>F</span>} back={<span>B</span>} label="card" />)
    const stage = screen.getByRole('button', { name: 'card' })
    stage.focus()
    await user.keyboard('{Enter}')
    expect(stage).toHaveAttribute('data-flipped', 'true')
  })
})
