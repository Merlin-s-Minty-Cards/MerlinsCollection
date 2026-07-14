import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import MarkdownMessage from '@/components/inventory/MarkdownMessage'

describe('MarkdownMessage', () => {
  it('renders bold text as a strong element', () => {
    render(<MarkdownMessage content="Charizard is **rare**." />)
    expect(screen.getByText('rare').tagName).toBe('STRONG')
  })

  it('renders a markdown heading as a heading element', () => {
    render(<MarkdownMessage content="### Base Set" />)
    expect(screen.getByRole('heading', { name: 'Base Set' })).toBeInTheDocument()
  })

  it('renders a list as list items', () => {
    render(<MarkdownMessage content={'- Charizard\n- Blastoise'} />)
    expect(screen.getByRole('list')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('renders a link with target=_blank and rel=noopener noreferrer', () => {
    render(<MarkdownMessage content="[pokemontcg.io](https://pokemontcg.io)" />)
    const link = screen.getByRole('link', { name: 'pokemontcg.io' })
    expect(link).toHaveAttribute('href', 'https://pokemontcg.io')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('never creates a live element from raw HTML in the content', () => {
    render(<MarkdownMessage content='<img src="x" onerror="window.__pwned = true">' />)
    expect(document.querySelector('img')).toBeNull()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })

  it('renders a plain sentence unchanged', () => {
    render(<MarkdownMessage content="Charizard is about $250." />)
    expect(screen.getByText('Charizard is about $250.')).toBeInTheDocument()
  })
})
