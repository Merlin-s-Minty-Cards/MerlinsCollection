import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import OwnershipBadge from '../OwnershipBadge'

describe('OwnershipBadge', () => {
  it('renders "Cosigned" when consigned is true', () => {
    render(<OwnershipBadge consigned />)
    expect(screen.getByText('Cosigned')).toBeInTheDocument()
  })

  it('renders "Owned" when consigned is false', () => {
    render(<OwnershipBadge consigned={false} />)
    expect(screen.getByText('Owned')).toBeInTheDocument()
  })
})
