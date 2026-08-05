import { expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import * as matchers from '@testing-library/jest-dom/matchers'
import { cleanup } from '@testing-library/react'

expect.extend(matchers)

afterEach(() => cleanup())

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
if (!window.matchMedia) {
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
;(window as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
  IntersectionObserverStub

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
