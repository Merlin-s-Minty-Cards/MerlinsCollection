import { render, screen } from '@testing-library/react'

describe('test harness', () => {
  it('renders DOM and exposes jest-dom matchers', () => {
    render(<button>Hello</button>)
    expect(screen.getByRole('button', { name: 'Hello' })).toBeInTheDocument()
  })

  it('provides matchMedia and IntersectionObserver stubs', () => {
    expect(typeof window.matchMedia).toBe('function')
    expect(typeof window.IntersectionObserver).toBe('function')
  })
})
