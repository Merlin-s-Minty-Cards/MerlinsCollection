# Chat Markdown Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render markdown (bold, italic, headers, lists, links, tables) in assistant chat bubbles on `/inventory`'s chat mode, instead of showing raw `**`/`###` syntax.

**Architecture:** A new presentational component, `MarkdownMessage`, wraps `react-markdown` + `remark-gfm` with custom per-element renderers styled to the existing pine/mint theme. `ChatPanel.tsx`'s `ChatBubble` renders assistant replies through it; user and error bubbles are untouched plain text.

**Tech Stack:** Next.js 14 / React 18, TypeScript, Tailwind CSS, Vitest + Testing Library. New deps: `react-markdown@^10.1.0`, `remark-gfm@^4.0.1`.

## Global Constraints

- Outside-in TDD per `CLAUDE.md`: write the failing test, confirm it fails, then write minimal code to pass. Never combine phases.
- No `rehype-raw` — raw HTML in model output must never become a live DOM element.
- No Tailwind Typography plugin — style markdown elements with existing `pine-*`/`mint` Tailwind tokens (`frontend/tailwind.config.ts`), not prose defaults.
- Markdown rendering applies to assistant bubbles only; user and error bubbles stay plain text.
- Existing tests in `frontend/components/inventory/__tests__/ChatPanel.test.tsx` must keep passing unchanged.

---

### Task 1: `MarkdownMessage` component

**Files:**
- Create: `frontend/components/inventory/MarkdownMessage.tsx`
- Test: `frontend/components/inventory/__tests__/MarkdownMessage.test.tsx`
- Modify: `frontend/package.json` (via `npm install`, see Step 1)

**Interfaces:**
- Produces: `export default function MarkdownMessage({ content }: { content: string }): JSX.Element` — later used by `ChatPanel.tsx` (Task 2) as `<MarkdownMessage content={bubble.content} />`.

- [ ] **Step 1: Install dependencies**

Run from the repo root (this is an npm workspaces monorepo — `frontend` and `mcp-server` are the workspaces):

```bash
npm install react-markdown@^10.1.0 remark-gfm@^4.0.1 --workspace=frontend
```

Expected: `frontend/package.json` gains `"react-markdown": "^10.1.0"` and `"remark-gfm": "^4.0.1"` under `dependencies`; the root `package-lock.json` updates.

- [ ] **Step 2: Write the failing tests**

Create `frontend/components/inventory/__tests__/MarkdownMessage.test.tsx`:

```tsx
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npm test --workspace=frontend -- MarkdownMessage`
Expected: FAIL — `Cannot find module '@/components/inventory/MarkdownMessage'` (the component doesn't exist yet).

- [ ] **Step 4: Write the component**

Create `frontend/components/inventory/MarkdownMessage.tsx`:

```tsx
'use client'

import type { ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Markdown headings (#, ##, ###...) all render as one small, consistent
// heading size — a full-size <h1> would blow out a compact chat bubble.
const heading = ({ children }: { children?: ReactNode }) => (
  <h4 className="mb-1 mt-2 text-sm font-semibold text-pine-100 first:mt-0">{children}</h4>
)

const components: Components = {
  p: ({ children }) => <p className="leading-relaxed">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-pine-100">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  h1: heading,
  h2: heading,
  h3: heading,
  h4: heading,
  h5: heading,
  h6: heading,
  ul: ({ children }) => <ul className="ml-4 list-disc space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="ml-4 list-decimal space-y-0.5">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-mint underline underline-offset-2 hover:text-mint-soft"
    >
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-pine-800 px-1 py-0.5 font-mono text-xs text-mint">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="overflow-x-auto rounded bg-pine-800 p-2 font-mono text-xs">{children}</pre>
  ),
  table: ({ children }) => <table className="my-1 border-collapse text-xs">{children}</table>,
  th: ({ children }) => <th className="border border-pine-700 px-2 py-1 text-left">{children}</th>,
  td: ({ children }) => <td className="border border-pine-700 px-2 py-1">{children}</td>,
}

export default function MarkdownMessage({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  )
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm test --workspace=frontend -- MarkdownMessage`
Expected: PASS (all 6 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json package-lock.json frontend/components/inventory/MarkdownMessage.tsx frontend/components/inventory/__tests__/MarkdownMessage.test.tsx
git commit -m "feat(frontend): add MarkdownMessage for rendering chat markdown"
```

---

### Task 2: Wire `MarkdownMessage` into `ChatPanel`

**Files:**
- Modify: `frontend/components/inventory/ChatPanel.tsx:130-152` (the `ChatBubble` function)
- Modify: `frontend/components/inventory/__tests__/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: `MarkdownMessage` from Task 1 (`import MarkdownMessage from '@/components/inventory/MarkdownMessage'`, `<MarkdownMessage content={string} />`).

- [ ] **Step 1: Write the failing tests**

Add to the end of the `describe('ChatPanel', ...)` block in `frontend/components/inventory/__tests__/ChatPanel.test.tsx` (before the final closing `})`):

```tsx
  it('renders markdown formatting in assistant replies', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'The **Charizard** is from Base Set.' })
    render(<ChatPanel />)

    await userEvent.type(screen.getByRole('textbox'), 'How much is Charizard?')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    const strong = await screen.findByText('Charizard')
    expect(strong.tagName).toBe('STRONG')
  })

  it('renders literal asterisks in user bubbles, not markdown', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'Sure thing.' })
    render(<ChatPanel />)

    await userEvent.type(screen.getByRole('textbox'), 'What about **this** card?')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText('What about **this** card?')).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test --workspace=frontend -- ChatPanel`
Expected: The new `renders markdown formatting in assistant replies` test FAILs — `screen.findByText('Charizard')` finds a text node whose `tagName` is `P`, not `STRONG` (the bubble still renders raw `**Charizard**` as plain text today). The literal-asterisks test PASSes already (no change needed for user bubbles) — that's expected; it's a regression guard for the change about to be made, not new behavior.

- [ ] **Step 3: Update `ChatBubble` to render assistant replies through `MarkdownMessage`**

In `frontend/components/inventory/ChatPanel.tsx`, add the import at the top (near the other local imports):

```tsx
import MarkdownMessage from '@/components/inventory/MarkdownMessage'
```

Replace the `ChatBubble` function (currently lines 130-152):

```tsx
function ChatBubble({ bubble }: { bubble: Bubble }) {
  if (bubble.role === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-2xl rounded-br-sm bg-mint px-4 py-2.5 text-sm text-pine-950">
          {bubble.content}
        </p>
      </div>
    )
  }
  if (bubble.role === 'error') {
    return (
      <p className="max-w-[85%] rounded-2xl rounded-bl-sm bg-red-500/10 px-4 py-2.5 text-sm text-red-300">
        {bubble.content}
      </p>
    )
  }
  return (
    <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-pine-800 px-4 py-2.5 text-sm text-pine-100">
      <MarkdownMessage content={bubble.content} />
    </div>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test --workspace=frontend -- ChatPanel`
Expected: PASS (all tests in the file, including the two new ones and every pre-existing test).

- [ ] **Step 5: Run the full frontend test suite**

Run: `npm test --workspace=frontend`
Expected: PASS — confirms no other component (e.g. any test relying on the assistant bubble being a `<p>`) broke.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/inventory/ChatPanel.tsx frontend/components/inventory/__tests__/ChatPanel.test.tsx
git commit -m "feat(frontend): render assistant chat replies as markdown"
```

---

## Manual verification (after both tasks)

Not covered by unit tests — confirm visually per `CLAUDE.md`'s guidance to check UI changes in a browser:

1. `npm run build --workspace=mcp-server`
2. In `backend/`: `$env:AUTH_DISABLED='true'; python -m uvicorn merlins_collection.main:app --port 8000`
3. In `frontend/`: `npm run dev`
4. Visit `http://localhost:3000/inventory`, switch to chat mode, and ask a question likely to produce a formatted reply (e.g. "List a few Charizard cards you have"). Confirm bold/headers/lists render instead of showing raw `**`/`#`/`-` characters, and that the bubble still fits the existing dark theme.
