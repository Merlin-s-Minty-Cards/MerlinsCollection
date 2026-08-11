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
