import { render, screen } from '@testing-library/react'

vi.mock('next/image', () => ({
  default: ({ src, alt, ...rest }: { src: string; alt: string }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={typeof src === 'string' ? src : ''} alt={alt} {...rest} />
  ),
}))

import PublicLayout from '@/app/(public)/layout'

describe('public layout', () => {
  it('wraps children with the Navbar (Inventory CTA) and Footer', () => {
    render(
      <PublicLayout>
        <div>PAGE BODY</div>
      </PublicLayout>,
    )
    expect(screen.getByText('PAGE BODY')).toBeInTheDocument()
    // "Inventory" appears in BOTH Navbar and Footer, so assert each region uniquely:
    expect(screen.getByRole('button', { name: 'Menu' })).toBeInTheDocument() // Navbar (mobile toggle)
    expect(screen.getByText('Explore')).toBeInTheDocument() // Footer column heading
  })
})
