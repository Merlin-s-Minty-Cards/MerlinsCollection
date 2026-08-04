export type BuyFormMode = 'search' | 'catalog' | 'manual'

/**
 * Determine the current form mode based on whether a catalog card has been
 * selected and whether the user toggled manual-entry mode.
 *
 * Priority: catalog selection wins over manual flag.
 * - A truthy selectedCard object -> 'catalog'
 * - manualMode flag set (no card) -> 'manual'
 * - Otherwise -> 'search'
 */
export function buyFormMode(selectedCard: unknown, manualMode: boolean): BuyFormMode {
  if (selectedCard) return 'catalog'
  if (manualMode) return 'manual'
  return 'search'
}

/**
 * Build the request body for adding a buy item, attaching catalog linkage
 * fields (card_id, manual_entry) alongside the form data.
 *
 * - card_id comes from the selected catalog card, or null if none.
 * - manual_entry is true only when the user explicitly chose manual mode
 *   AND no catalog card is linked.
 */
export function buildBuyItemBody(
  form: Record<string, unknown>,
  selectedCard: { card_id: string } | null,
  manualMode: boolean,
): Record<string, unknown> {
  return {
    ...form,
    card_id: selectedCard?.card_id ?? null,
    manual_entry: manualMode && !selectedCard,
  }
}
