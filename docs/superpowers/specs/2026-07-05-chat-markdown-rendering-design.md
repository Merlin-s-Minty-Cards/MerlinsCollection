# Chat Markdown Rendering — Design

**Date:** 2026-07-05
**Status:** Approved (pending spec review)

## Problem

Chat mode (`/inventory` → AI chat) sends assistant replies straight through Bedrock/Claude as plain text. Claude commonly formats answers with markdown (`**bold**`, `### headers`, lists, links), but `ChatPanel.tsx` renders `bubble.content` as a raw string — the user sees literal asterisks and hashes instead of formatting.

## Goal

Render markdown formatting (bold, italic, headers, lists, links, tables) in assistant chat bubbles only, matching the existing pine/mint theme, with no new security surface.

## Non-goals

- No change to user or error bubbles — user bubbles are the customer's own typed text (nothing to format); error bubbles are plain backend-authored strings.
- No raw HTML rendering from model output (no `rehype-raw`).
- No syntax-highlighted code blocks — out of scope for a card-collecting chatbot; inline/fenced code gets simple monospace styling only.
- No Tailwind Typography plugin — custom per-element styling keeps the existing pine/mint theme instead of pulling in prose defaults.

## Design

### 1. New dependencies

`react-markdown` + `remark-gfm` (frontend only). `remark-gfm` adds GitHub-flavored markdown: tables, strikethrough, and looser list handling that Claude tends to produce.

### 2. New component: `MarkdownMessage`

`frontend/components/inventory/MarkdownMessage.tsx` — a client component:

- Props: `{ content: string }`.
- Renders `<ReactMarkdown remarkPlugins={[remarkGfm]} components={...}>{content}</ReactMarkdown>`.
- Custom `components` map (all styled with existing pine/mint Tailwind classes, no new plugin):
  - `p` — default text size, `leading-relaxed`.
  - `strong` / `em` — bold / italic, inherit text color.
  - `h1`/`h2`/`h3` — all rendered at a small, consistent size (visually like h5/h6) so headers don't blow out the compact bubble.
  - `ul`/`ol`/`li` — indented, `list-disc`/`list-decimal`.
  - `a` — mint-colored, underlined, `target="_blank" rel="noopener noreferrer"`.
  - `code` — inline monospace with a subtle background; fenced code blocks (`pre > code`) get the same treatement, no highlighting.
  - `table`/`th`/`td` — minimal borders consistent with `vault-panel`.
- No `rehype-raw`: react-markdown escapes raw HTML in the source by default, so any `<script>`/`<img onerror>` text in a model reply renders as inert text, never executes. This matters because assistant content is LLM-generated and not fully controlled.

### 3. `ChatPanel.tsx` changes

In `ChatBubble`:
- `role === 'assistant'` → wrapper becomes a `<div>` (was `<p>`, since markdown can emit block elements that can't nest in a `<p>`) containing `<MarkdownMessage content={bubble.content} />`.
- `role === 'user'` and `role === 'error'` → unchanged, still render `bubble.content` as plain text in a `<p>`.

### 4. Testing (outside-in TDD per CLAUDE.md)

Extend `ChatPanel.test.tsx` (new cases, RED first):
- An assistant reply containing `**Charizard**` renders a `<strong>` element with text `Charizard` (not the literal string `**Charizard**`).
- An assistant reply containing `### Base Set` renders a heading element with text `Base Set`.
- An assistant reply containing a link `[pokemontcg.io](https://pokemontcg.io)` renders an `<a>` with `href="https://pokemontcg.io"` and `target="_blank"`.
- A user bubble containing `**not markdown**` still renders the literal asterisks (proves formatting is assistant-only).

Existing tests that assert exact assistant text via `getByText('...')` (e.g. `'Charizard is about $250.'`) must keep passing unchanged — plain-sentence replies with no markdown syntax render as equivalent text content through `MarkdownMessage`.

## Rollback

Isolated to `MarkdownMessage.tsx` + the `ChatBubble` assistant branch in `ChatPanel.tsx`. Reverting either file (or removing the two dependencies) fully restores plain-text rendering.
