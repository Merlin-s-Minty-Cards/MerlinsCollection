/**
 * Domain types and data-access boundary for the inventory MCP tools.
 *
 * Tools depend only on the `InventoryRepository` interface, never on a concrete
 * data source. Tests inject an in-memory implementation; production will inject a
 * DynamoDB-backed implementation (added separately).
 */

export type Card = {
  id: string;
  name: string;
  set: string;
  condition: string;
  quantity: number;
  /**
   * Current value per unit (maps to CardResult.currentValue). `null` when no
   * price could be resolved from any source — NOT 0. A zero would be summed
   * into totals as a real $0 valuation and would rank in `topValuedCards`;
   * `null` lets callers skip the item, the way the backend's
   * `/inventory/summary` skips it (routers/inventory.py:387-391).
   */
  value: number | null;
  /** External market reference price per unit (used for flagging underpriced cards). */
  marketPrice: number | null;
  /**
   * Print language — part of the card's identity, not a label. A JP print is a
   * different card at a different price. Rows written before the field existed
   * (every EN item) default to "EN".
   */
  language: "EN" | "JP";
};

export type PricePoint = {
  date: string;
  price: number;
  source: string;
};

export interface InventoryRepository {
  listCards(): Promise<Card[]>;
  getPriceHistory(cardId: string): Promise<PricePoint[]>;
}
