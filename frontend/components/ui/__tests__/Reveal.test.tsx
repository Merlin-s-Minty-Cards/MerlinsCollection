import { render } from '@testing-library/react'
import Reveal from '@/components/ui/Reveal'

describe('Reveal', () => {
  it('renders the tag from the `as` prop and merges className', () => {
    const { container } = render(
      <Reveal as="section" className="custom">
        child
      </Reveal>,
    )
    const el = container.querySelector('section')
    expect(el).toBeInTheDocument()
    expect(el).toHaveClass('reveal', 'custom')
  })

  it('reveals immediately when IntersectionObserver is unavailable', () => {
    const saved = (globalThis as Record<string, unknown>).IntersectionObserver
    delete (globalThis as Record<string, unknown>).IntersectionObserver
    delete (window as unknown as Record<string, unknown>).IntersectionObserver
    try {
      const { container } = render(<Reveal>x</Reveal>)
      expect(container.firstElementChild).toHaveClass('reveal-in')
    } finally {
      ;(globalThis as Record<string, unknown>).IntersectionObserver = saved
      ;(window as unknown as Record<string, unknown>).IntersectionObserver = saved
    }
  })

  it('reveals immediately under prefers-reduced-motion', () => {
    const original = window.matchMedia
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia
    try {
      const { container } = render(<Reveal>x</Reveal>)
      expect(container.firstElementChild).toHaveClass('reveal-in')
    } finally {
      window.matchMedia = original
    }
  })
})
