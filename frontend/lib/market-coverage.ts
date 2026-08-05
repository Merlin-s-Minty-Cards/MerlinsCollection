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
}

export interface CoverageBannerState {
  summary: string
  catalogEmpty: boolean
  showUnmatched: boolean
  unmatchedItems: UnmatchedItem[]
}

/** Pure decision logic for the coverage banner — extracted so it's testable without mounting the page. */
export function getCoverageBannerState(coverage: MarketCoverage): CoverageBannerState {
  const {
    items_with_market_value,
    total_items,
    catalog_cards_with_prices,
    catalog_cards,
    unmatched_sample,
  } = coverage

  const summary = `${items_with_market_value}/${total_items} items priced · catalog ${catalog_cards_with_prices}/${catalog_cards} cards priced`
  const catalogEmpty = catalog_cards === 0
  const ratio = total_items > 0 ? items_with_market_value / total_items : 0

  return {
    summary,
    catalogEmpty,
    showUnmatched: ratio < 0.5,
    unmatchedItems: (unmatched_sample ?? []).slice(0, 10),
  }
}
