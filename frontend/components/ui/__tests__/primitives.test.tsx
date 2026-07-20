import { render, screen } from '@testing-library/react'
import SectionHeading from '@/components/ui/SectionHeading'
import ImagePlaceholder from '@/components/ui/ImagePlaceholder'

describe('display primitives', () => {
  it('SectionHeading renders the title as a level-2 heading plus eyebrow', () => {
    render(<SectionHeading eyebrow="What we do" title="Three ways to work with us" />)
    expect(screen.getByRole('heading', { level: 2, name: 'Three ways to work with us' })).toBeInTheDocument()
    expect(screen.getByText('What we do')).toBeInTheDocument()
  })

  it('SectionHeading renders the subtitle only when provided', () => {
    const { rerender } = render(<SectionHeading eyebrow="E" title="T" />)
    expect(screen.queryByText('Sub copy')).not.toBeInTheDocument()
    rerender(<SectionHeading eyebrow="E" title="T" subtitle="Sub copy" />)
    expect(screen.getByText('Sub copy')).toBeInTheDocument()
  })

  it('ImagePlaceholder exposes its label as an accessible image', () => {
    render(<ImagePlaceholder label="Photo: Merlin at a show" />)
    expect(screen.getByRole('img', { name: 'Photo: Merlin at a show' })).toBeInTheDocument()
  })
})
