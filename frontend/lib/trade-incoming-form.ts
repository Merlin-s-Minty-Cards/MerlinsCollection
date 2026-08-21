import { parseMoney } from './money'

export interface IncomingLegForm {
  name: string
  card_number: string
  set_name: string
  market_value: string
  value: string
}

export interface IncomingCatalogCard {
  card_id: string
  images?: { small?: string | null }
}

/**
 * Both amounts here are typed by a human, so they go through `parseMoney` and
 * never `parseFloat`: `parseFloat('1,300')` is `1` and never `NaN`, so it
 * passes every downstream guard as a plausible wrong number. An unreadable
 * market value is omitted rather than sent truncated; the caller is expected to
 * have already blocked an unreadable `value` (see `addIncoming`), and
 * `agreed_value` falls back to `NaN` so a caller that did not is loud.
 */
export function buildIncomingLegBody(
  form: IncomingLegForm,
  selectedCard: IncomingCatalogCard | null,
): Record<string, unknown> {
  const marketValue = form.market_value ? parseMoney(form.market_value) : null
  const agreedValue = parseMoney(form.value)
  return {
    name: form.name.trim(),
    card_id: selectedCard?.card_id ?? null,
    card_number: form.card_number.trim() || undefined,
    set_name: form.set_name.trim() || undefined,
    market_value: marketValue ?? undefined,
    agreed_value: agreedValue ?? NaN,
    image_url: selectedCard?.images?.small ?? undefined,
  }
}

/**
 * One leg of a deal, as `IncomingCardForm` emits it and T15 dispatches it
 * (RFC 0011 T14/T15). The keys mirror T13's
 * `POST /admin/trades/{id}/incoming` exactly.
 */
export interface IncomingLeg {
  /** `null` only for a manual entry, which is why a manual entry cannot be graded. */
  card_id: string | null
  name: string
  agreed_value: number
  kind: 'raw' | 'graded'
  /**
   * Manual entry only, and only when typed. A catalog pick carries its set and
   * number inside `card_id`, so repeating them there would be a second, older
   * copy of the same facts. Both keys are already read by
   * `POST /admin/trades/{id}/incoming` (trades.py:451-452) — without them the
   * set and number an operator types for an unmatched card are collected and
   * silently dropped, which is worse than not offering the fields.
   */
  set_name?: string
  /** Manual entry only. See `set_name`. */
  card_number?: string
  /** raw only */
  condition?: string
  /** raw only */
  finish?: string
  /** graded only */
  company?: string
  /** graded only */
  grade?: number
  /** graded only */
  cert_number?: string
  /** graded only */
  grade_label?: string
  language: string
  location: string
  /**
   * The catalog's Near Mint market figure for the picked card, if there is
   * one — `POST /admin/trades/{id}/incoming` (and `/purchases/{id}/items`)
   * both read this field, and it was collected on the picker but never sent
   * (final-review Important 7), which is what left Split with nothing to
   * split against. `undefined` for a manual entry (no catalog card) or a
   * catalog card with no price yet (`detail: "brief"`, or `full` with no
   * band — see CLAUDE.md's price-rendering rules; both are absent, not 0).
   */
  market_value?: number
  /** The card's small image, when a catalog card supplied one. `undefined` for manual. */
  image_url?: string
  /**
   * Client-side only — never sent to POST /trades/{id}/incoming or
   * POST /purchases/{id}/items (neither accepts consignment at create time,
   * RFC 0012). The page reads this off the leg to stage a post-confirm
   * POST /cosigners/{id}/link, keyed by position against the confirm
   * response's item_ids.
   */
  consignor_id?: string
  /**
   * The consignor's display label, captured at selection time alongside
   * `consignor_id` (final-review Fix 5) — never sent to the backend, purely
   * so the staged row can show what was picked ("Consignor: <name>") before
   * the operator presses Confirm.
   */
  consignor_label?: string
}

/** What the form holds — every money and grade field still raw text. */
export interface IncomingLegDraft {
  card_id: string | null
  name: string
  /** Already through `parseMoney`. The caller gates on `=== null` first. */
  agreed_value: number
  kind: 'raw' | 'graded'
  set_name: string
  card_number: string
  condition: string
  finish: string
  company: string
  grade: string
  cert_number: string
  grade_label: string
  language: string
  location: string
  /** Already through `parseMoney` by the caller, or `null` when absent. */
  market_value?: number | null
  image_url?: string | null
}

/**
 * Build the leg, with the two branches kept STRICTLY apart.
 *
 * This is decision 15 expressed in the builder rather than only in the form:
 * T13 422s a raw leg that carries graded fields and a graded leg that carries
 * a condition, so a leg assembled by spreading the whole draft would generate
 * a rejection the operator cannot explain. A raw leg never learns the word
 * `grade`; a graded leg never learns the word `condition`.
 *
 * `grade` is emitted only when it reads as a number. A blank or unreadable
 * grade is omitted rather than sent as `NaN` — the backend's own required-field
 * error is a better message than a silently mangled one.
 */
export function buildIncomingLeg(draft: IncomingLegDraft): IncomingLeg {
  const base = {
    card_id: draft.card_id,
    name: draft.name.trim(),
    agreed_value: draft.agreed_value,
    language: draft.language,
    location: draft.location,
    // Only for a card with no catalog row behind it — see `set_name` above.
    ...(draft.card_id === null && draft.set_name.trim() ? { set_name: draft.set_name.trim() } : {}),
    ...(draft.card_id === null && draft.card_number.trim()
      ? { card_number: draft.card_number.trim() }
      : {}),
    ...(draft.market_value !== undefined && draft.market_value !== null
      ? { market_value: draft.market_value }
      : {}),
    ...(draft.image_url ? { image_url: draft.image_url } : {}),
  }

  if (draft.kind === 'raw') {
    return {
      ...base,
      kind: 'raw',
      condition: draft.condition,
      finish: draft.finish,
    }
  }

  const grade = Number(draft.grade.trim())
  return {
    ...base,
    kind: 'graded',
    company: draft.company,
    ...(Number.isFinite(grade) && draft.grade.trim() !== '' ? { grade } : {}),
    ...(draft.cert_number.trim() ? { cert_number: draft.cert_number.trim() } : {}),
    ...(draft.grade_label.trim() ? { grade_label: draft.grade_label.trim() } : {}),
  }
}
