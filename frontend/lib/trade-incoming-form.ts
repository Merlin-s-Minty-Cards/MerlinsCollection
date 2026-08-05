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

export function buildIncomingLegBody(
  form: IncomingLegForm,
  selectedCard: IncomingCatalogCard | null,
): Record<string, unknown> {
  return {
    name: form.name.trim(),
    card_id: selectedCard?.card_id ?? null,
    card_number: form.card_number.trim() || undefined,
    set_name: form.set_name.trim() || undefined,
    market_value: form.market_value ? parseFloat(form.market_value) : undefined,
    agreed_value: parseFloat(form.value),
    image_url: selectedCard?.images?.small ?? undefined,
  }
}
