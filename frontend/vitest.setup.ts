import { expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'

// Setup files run for EVERY environment, and the pure-logic test files opt into
// `// @vitest-environment node` (jsdom construction was 215s of cumulative cost
// across the suite, and ~20 files never touch the DOM). Everything below that
// needs a DOM is therefore guarded — under node there is no `window`, no
// `HTMLDialogElement`, and nothing for `cleanup()` to unmount.
const HAS_DOM = typeof window !== 'undefined'

// jest-dom's matchers and testing-library are imported DYNAMICALLY, and only
// under a DOM. They are the heaviest thing this file pulls in, and a node-env
// file would otherwise pay for a matcher set that only asserts on DOM nodes and
// a `cleanup()` with nothing to unmount. Top-level await is supported here.
if (HAS_DOM) {
  const matchers = await import('@testing-library/jest-dom/matchers')
  const { cleanup } = await import('@testing-library/react')
  expect.extend(matchers)
  afterEach(() => cleanup())
}

// next/image is a heavy client component that doesn't run in jsdom. Mock it
// globally (applies to every test file) as a plain <img>, forwarding only the
// props that are valid DOM attributes. The Next-only props (priority, fill,
// quality, placeholder, …) are intentionally dropped so React doesn't warn
// about unknown attributes — tests assert on src/alt, not Next internals.
vi.mock('next/image', () => ({
  default: ({
    src,
    alt,
    width,
    height,
    sizes,
    className,
  }: {
    src: unknown
    alt?: string
    width?: number
    height?: number
    sizes?: string
    className?: string
  }) =>
    createElement('img', {
      src: typeof src === 'string' ? src : '',
      alt: alt ?? '',
      width,
      height,
      sizes,
      className,
    }),
}))

// jsdom lacks matchMedia — stub it (default: feature off, e.g. not reduced-motion)
if (HAS_DOM && !window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

// jsdom lacks IntersectionObserver — stub a no-op (never fires, keeps tests deterministic).
// No constructor: the runtime simply ignores the callback/options args passed by consumers.
class IntersectionObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] { return [] }
}
;(globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
  IntersectionObserverStub
if (HAS_DOM) {
  ;(window as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
    IntersectionObserverStub
}

// jsdom recognizes <dialog> as HTMLDialogElement but doesn't implement its
// showModal()/close() methods (longstanding jsdom gap). Components using the
// native <dialog> element (e.g. ConfirmDialog) call showModal() to open, so
// without this stub every test that opens one throws "showModal is not a
// function". Mirror the real element's open-attribute contract closely enough
// for tests: showModal sets `open` + dispatches nothing (matches spec — no
// open event), close clears `open` and fires the `close` event ConfirmDialog
// listens for isn't needed here, but matches native behavior for any consumer
// that does.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute('open')
    this.dispatchEvent(new Event('close'))
  }
}
