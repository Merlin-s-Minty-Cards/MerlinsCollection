export interface UnmatchedItem {
  item_id: string
  name: string
}

export interface MarketCoverage {
  total_items: number
  items_with_market_value: number
  catalog_cards: number
  catalog_cards_with_prices: number
  unmatched_sample: UnmatchedItem[]
  /**
   * The weekly catalog price cycle's audit numbers (RFC 0010 T17). Optional
   * because a response from before T17 does not carry them — and absent must
   * render as nothing rather than as zero, which would read as a healthy cycle
   * on an API that has none.
   *
   * They are two DIFFERENT facts and are never summed: `brief` has never had a
   * price fetched at all (the cycle has not reached it yet, and this counts
   * down to 0 over the first ~6 nights), while `stale` was priced once and the
   * cycle has since missed its slot. The healthy value for `stale` is 0.
   */
  catalog_cards_brief?: number
  catalog_cards_stale?: number
  catalog_stale_threshold_days?: number
  /**
   * The three-way split of the item table (RFC 0010 T16). Optional for the same
   * reason the cycle counts are: a response from before T16 does not carry them,
   * and rendering an absent count as 0 is a claim the API never made.
   *
   * They PARTITION the table — market-priced + hand-valued + unpriced ==
   * total_items — because "what still needs a price?" and "how much of this is
   * market-derived?" are two questions and `items_with_market_value` answers
   * neither on its own. A hand-valued card is priced and permanently
   * un-syncable, so it is not a gap anyone can close.
   */
  items_market_priced?: number
  items_hand_valued?: number
  items_unpriced?: number
}

export interface CoverageBannerState {
  summary: string
  catalogEmpty: boolean
  showUnmatched: boolean
  unmatchedItems: UnmatchedItem[]
  /** The weekly cycle line, or null when the API did not send the counts. */
  cycle: string | null
  /** The market-priced / hand-valued / unpriced line, or null when absent. */
  valuation: string | null
  /** True when a `full` row has gone past the threshold — the promise is not being kept. */
  cycleBehind: boolean
}

/** Pure decision logic for the coverage banner — extracted so it's testable without mounting the page. */
export function getCoverageBannerState(coverage: MarketCoverage): CoverageBannerState {
  const {
    items_with_market_value,
    total_items,
    catalog_cards_with_prices,
    catalog_cards,
    unmatched_sample,
    catalog_cards_brief,
    catalog_cards_stale,
    catalog_stale_threshold_days,
    items_market_priced,
    items_hand_valued,
    items_unpriced,
  } = coverage

  const summary = `${items_with_market_value}/${total_items} items priced · catalog ${catalog_cards_with_prices}/${catalog_cards} cards priced`
  const catalogEmpty = catalog_cards === 0
  const ratio = total_items > 0 ? items_with_market_value / total_items : 0

  const hasCycle =
    catalog_cards_brief !== undefined &&
    catalog_cards_stale !== undefined &&
    catalog_stale_threshold_days !== undefined

  const hasValuation =
    items_market_priced !== undefined &&
    items_hand_valued !== undefined &&
    items_unpriced !== undefined

  return {
    summary,
    catalogEmpty,
    showUnmatched: ratio < 0.5,
    unmatchedItems: (unmatched_sample ?? []).slice(0, 10),
    cycle: hasCycle
      ? `weekly cycle: ${catalog_cards_brief} never priced · ${catalog_cards_stale} past ${catalog_stale_threshold_days} days`
      : null,
    // A large `brief` count is the first cycle still running, which is the
    // design working. Only a stale `full` row means a slot was missed.
    cycleBehind: hasCycle && (catalog_cards_stale as number) > 0,
    valuation: hasValuation
      ? `${items_market_priced} market-priced · ${items_hand_valued} hand-valued · ${items_unpriced} unpriced`
      : null,
  }
}
