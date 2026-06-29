/**
 * Barrel of the inventory tools. Each function takes an `InventoryRepository`
 * (see ../repository.ts) plus its own arguments and returns a plain result
 * object — the MCP server layer (../index.ts) is responsible for adapting these
 * into registered MCP tools.
 */
export { getInventorySummary } from "./get-inventory-summary.js";
export { searchInventory } from "./search-inventory.js";
export { getCardPriceHistory } from "./get-card-price-history.js";
export { calculateInventoryValue } from "./calculate-inventory-value.js";
export { flagUnderpricedCards } from "./flag-underpriced-cards.js";
