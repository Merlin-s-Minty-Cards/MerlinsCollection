/**
 * DynamoDB-backed InventoryRepository reading the backend's single-table layout.
 *
 * Key formats mirror backend/src/merlins_collection/services/dynamodb.py — that
 * module is the authority on the schema (and on INVENTORY_SHARD_COUNT):
 *   inventory   PK=INV#<shard 0-9>   SK=ITEM#<item_id>
 *   catalog     PK=CARD#<id>         SK=META
 *   graded $    PK=CARD#<id>         SK=GRADEDPRICE#<company>#<grade>
 *   history     PK=CARD#<id>         SK=PRICE#RAW#<finish>#<date> | PRICE#GRADED#...
 * Card-linked inventory rows also carry a sparse GSI1 (GSI1PK=CARD#<card_id>,
 * GSI1SK=ITEM#<item_id>); sealed/bulk rows have no card_id and stay out of GSI1.
 *
 * Inventory rows are joined with catalog metadata to produce the tools' flat
 * `Card` shape. When a catalog row is missing, `toCard` falls back to the
 * item's `display_name` — a sanitized name+number string the backend
 * materializes on the row at IMPORT time from the structured Name/Card #
 * columns (services/card_text.format_display_name) — and only then to the
 * card_id or item_id itself.
 */
import { BatchGetCommand, QueryCommand } from "@aws-sdk/lib-dynamodb";
import { applyConditionAdjustment } from "./condition-pricing.js";
import type { Card, InventoryRepository, PricePoint } from "./repository.js";

/** The subset of DynamoDBDocumentClient the repository needs (send-able). */
export type DocumentClientLike = {
  send(command: unknown): Promise<Record<string, unknown>>;
};

// Mirrors INVENTORY_SHARD_COUNT in the backend's dynamodb.py — a reshard there
// must be mirrored here or inventory silently disappears from the tools.
const SHARD_COUNT = 10;
const BATCH_GET_LIMIT = 100; // DynamoDB BatchGetItem hard limit
const MAX_BATCH_ATTEMPTS = 8; // bound the UnprocessedKeys retry loop

// The customer-facing projection: only available single cards (raw/graded).
// Bulk lots and sealed products are hidden — a cards-only surface (RFC 0001
// owner decision) — and anything sold/on-hold/lost/out-for-grading is internal
// and must never reach the (unauthenticated) chat tools. Mirrors the backend
// /inventory/search rules; admin-only tools come later.
const PUBLIC_KINDS = new Set(["raw", "graded"]);

// Phase 5 (D3, display scoping): only items stored in a customer-facing
// location are shown. factory_sealed items are also visible regardless of
// location (a condition premium, not a physical place). Mirrors the backend
// _CUSTOMER_VISIBLE_LOCATIONS frozenset in routers/inventory.py.
const PUBLIC_LOCATIONS = new Set(["glass", "toploader"]);

const SEALED_TYPE_LABELS: Record<string, string> = {
  booster_box: "Booster Box",
  etb: "Elite Trainer Box",
  bundle: "Bundle",
  booster_pack: "Booster Pack",
  collection_box: "Collection Box",
  other: "Sealed",
};

type Row = Record<string, unknown>;

function isPublicInventory(row: Row): boolean {
  return (
    PUBLIC_KINDS.has(String(row.kind)) &&
    row.status === "available" &&
    (PUBLIC_LOCATIONS.has(String(row.location)) || row.factory_sealed === true)
  );
}

/** Canonical grade string, matching the backend's `_grade_key` (10 not 10.0). */
function gradeKey(grade: unknown): string {
  return String(Number(grade));
}

function asNumber(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/**
 * A catalog finish band's market figure, or `null` if it carries none.
 *
 * A band whose `market` is present but not a finite number is treated as absent
 * so the walk keeps going. On the Python side pydantic parses these into
 * `Decimal | None` at load, so garbage never reaches `_market_price`; MCP reads
 * the raw DynamoDB map with no such gate. That only became load-bearing when the
 * catalog lookup moved to the FRONT of the chain — a band of `"N/A"` would
 * otherwise coerce to $0 and outrank a perfectly good current_market_value.
 * A genuine 0 is a real price and is kept.
 */
function bandMarket(band: { market?: unknown } | undefined): number | null {
  if (band?.market == null) return null;
  const n = Number(band.market);
  return Number.isFinite(n) ? n : null;
}

/** Print language off a row; only the JP items store it, everything else is EN. */
function languageOf(row: Row): "EN" | "JP" {
  return row.language === "JP" ? "JP" : "EN";
}

export class DynamoDbInventoryRepository implements InventoryRepository {
  constructor(
    private readonly client: DocumentClientLike,
    private readonly tableName: string,
  ) {}

  async listCards(): Promise<Card[]> {
    const shardResults = await Promise.all(
      Array.from({ length: SHARD_COUNT }, (_, shard) =>
        this.queryAll({
          KeyConditionExpression: "PK = :pk",
          ExpressionAttributeValues: { ":pk": `INV#${shard}` },
        }),
      ),
    );
    const rows = shardResults.flat().filter(isPublicInventory);

    // Only card-linked items (raw/graded) join the catalog; sealed products
    // have no card_id and are self-describing.
    const metaKeys = [
      ...new Set(rows.filter((r) => r.card_id != null).map((r) => String(r.card_id))),
    ].map((id) => ({ PK: `CARD#${id}`, SK: "META" }));
    // Graded slabs without a synced market value fall back to the manually
    // entered GRADEDPRICE row.
    const gradedKeys = rows
      .filter((r) => r.kind === "graded" && r.card_id != null && r.current_market_value == null)
      .map((r) => ({
        PK: `CARD#${r.card_id}`,
        SK: `GRADEDPRICE#${r.company}#${gradeKey(r.grade)}`,
      }));

    const catalog = new Map<string, Row>();
    const gradedPrices = new Map<string, Row>();
    for (const item of await this.batchGet([...metaKeys, ...gradedKeys])) {
      if (item.entity === "catalog_card") {
        catalog.set(String(item.card_id), item);
      } else if (item.entity === "graded_price") {
        gradedPrices.set(
          `${item.card_id}#${item.company}#${gradeKey(item.grade)}`,
          item,
        );
      }
    }

    return rows.map((row) => this.toCard(row, catalog, gradedPrices));
  }

  async getPriceHistory(cardId: string): Promise<PricePoint[]> {
    const rows = await this.queryAll({
      KeyConditionExpression: "PK = :pk AND begins_with(SK, :prefix)",
      ExpressionAttributeValues: { ":pk": `CARD#${cardId}`, ":prefix": "PRICE#" },
    });

    return rows.flatMap((row) => {
      // Prefer the market figure; fall back through the band. No price → skip.
      const price = row.market ?? row.mid ?? row.low;
      if (price == null) return [];
      // Tag the series so raw finishes and graded slabs don't blur into one
      // misleading time series for the model.
      const series =
        row.kind === "graded" ? `${row.company} ${gradeKey(row.grade)}` : String(row.finish);
      return [
        {
          date: String(row.date),
          price: asNumber(price),
          source: `${row.source} (${series})`,
        },
      ];
    });
  }

  private toCard(row: Row, catalog: Map<string, Row>, gradedPrices: Map<string, Row>): Card {
    // Sealed products carry their own name/type and never touch the catalog.
    if (row.kind === "sealed") {
      const sealedMarket = asNumber(row.current_market_value ?? 0);
      return {
        id: String(row.item_id),
        name: String(row.product_name),
        set: "Sealed",
        condition: SEALED_TYPE_LABELS[String(row.product_type)] ?? "Sealed",
        quantity: 1,
        value: sealedMarket,
        marketPrice: sealedMarket,
        language: languageOf(row),
      };
    }
    // Raw/graded: card_id is an optional catalog link; fall back to item_id.
    const cardId = row.card_id != null ? String(row.card_id) : null;
    const meta = cardId ? catalog.get(cardId) : undefined;
    const fallback = cardId ?? String(row.item_id);
    // Without a catalog match, use the sanitized display_name the backend
    // materialized on the row at IMPORT time from the structured Name + Card #
    // columns (services/card_text.format_display_name) so the model reads
    // "Dragonair #181", not a raw ULID. Both customer surfaces read this one
    // stored field — MCP never parses `notes` — so parity is structural, and no
    // internal free-text can reach the model (Council MUST-FIX A/C). The card_id,
    // then the ULID, remains the last resort when the row stored no display_name.
    const nameFallback =
      (typeof row.display_name === "string" && row.display_name) || fallback;
    // An admin's `display_name_override` OUTRANKS the catalog name — the same
    // precedence `itemTitle` (customer tiles) and `adminItemName` (admin lists)
    // apply. Without it, filter mode rendered "Chespin" and chat answered
    // "ハリマロン" for the same card. Trimmed, not `??`: a whitespace-only
    // override would otherwise name the card after nothing at all.
    const override =
      typeof row.display_name_override === "string"
        ? row.display_name_override.trim()
        : "";
    return {
      id: fallback,
      name: override || (meta ? String(meta.name) : nameFallback),
      set: meta ? String(meta.set_id) : cardId ? cardId.split("-")[0]! : "Unknown",
      condition:
        row.kind === "raw"
          ? `${row.condition}${row.condition_modifier ?? ""}`
          : `${row.company} ${gradeKey(row.grade)}`,
      quantity: 1, // one inventory record = one physical unit
      value: this.marketPrice(row, meta, gradedPrices),
      marketPrice: this.marketPrice(row, meta, gradedPrices),
      language: languageOf(row),
    };
  }

  /**
   * A card's price, resolved in the SAME order as the dashboard's
   * `/inventory/summary` (backend `routers/inventory.py:383-391`): the LIVE
   * finish-aware catalog figure first, then the denormalized
   * `current_market_value`, then `listed_price`. `null` when no source has one.
   *
   * The order is the whole point (RFC 0008 §D). This used to read the stored
   * value first, so whenever the nightly denormalizer lagged the catalog, the
   * chat tools summed stale figures while the dashboard summed live ones and the
   * two disagreed on a number customers see. Do not "optimize" the stored value
   * back to the front.
   */
  private marketPrice(
    row: Row,
    meta: Row | undefined,
    gradedPrices: Map<string, Row>,
  ): number | null {
    const live = this.catalogMarketPrice(row, meta);
    if (live != null) {
      // The catalog figure is a NM price. The backend scales it by condition on
      // both customer paths, so chat must too — otherwise filter mode shows a
      // DMG card at 0.15x and chat quotes the full NM figure for the same card.
      // Raw singles only: a slab carries a grade, not a tier, and never reaches
      // this branch anyway (catalogMarketPrice refuses to price one).
      return row.kind === "raw"
        ? applyConditionAdjustment(
            live,
            row.condition as string | null,
            row.condition_modifier as string | null,
          )
        : live;
    }

    // Phase 12/19: the denormalized, condition-adjusted figure baked in by
    // refresh_inventory_market_values. Now the FALLBACK, used when the catalog
    // has nothing — including for every graded slab, which by design gets no
    // catalog price and must keep its own manually-maintained value.
    if (row.current_market_value != null) return asNumber(row.current_market_value);

    // Slabs additionally fall back to the manually entered GRADEDPRICE row; the
    // backend reaches the same figure via get_graded_market_value at sync time.
    if (row.kind === "graded") {
      const key = `${row.card_id}#${row.company}#${gradeKey(row.grade)}`;
      const gradedValue = gradedPrices.get(key)?.market_value;
      if (gradedValue != null) return asNumber(gradedValue);
    }

    if (row.listed_price != null) return asNumber(row.listed_price);
    return null;
  }

  /**
   * The catalog's market figure for a row's own finish, falling back through
   * `_MARKET_FINISH_FALLBACK` then any priced finish.
   *
   * *** This mirrors `_market_price` in
   * backend/src/merlins_collection/models/inventory.py (~line 296) — read that
   * docstring before touching either. It is the ONE shared finish-aware lookup,
   * and its fallback tuple is declared canonical "for the whole product, in
   * every language it is implemented in". If the two walks disagree, the website
   * and the Bedrock chat quote different prices for the same card. ***
   *
   * `null` for a graded slab and for any row with no finish, exactly as the
   * Python does: catalog figures are UNGRADED prices, so pricing a slab from
   * them would drop the grade premium, and guessing a band for a finish-less row
   * would silently misprice it.
   */
  private catalogMarketPrice(row: Row, meta: Row | undefined): number | null {
    if (row.kind === "graded") return null;
    const finish = row.finish == null ? "" : String(row.finish);
    if (!finish) return null;
    const prices = meta?.prices as Record<string, { market?: unknown }> | undefined;
    if (!prices) return null;

    const fallbackOrder = [
      finish,
      "normal", "holofoil", "reverseHolofoil",
      "1stEditionHolofoil", "1stEditionNormal", "unlimitedHolofoil",
    ];
    // Try the ordered fallback chain (deduped).
    const tried = new Set<string>();
    for (const key of fallbackOrder) {
      if (tried.has(key)) continue;
      tried.add(key);
      const band = bandMarket(prices[key]);
      if (band != null) return band;
    }
    // Last resort: any finish that carries a market figure.
    for (const value of Object.values(prices)) {
      const band = bandMarket(value);
      if (band != null) return band;
    }
    return null;
  }

  private async queryAll(params: {
    KeyConditionExpression: string;
    ExpressionAttributeValues: Record<string, string>;
  }): Promise<Row[]> {
    const items: Row[] = [];
    let exclusiveStartKey: Row | undefined;
    do {
      const resp = (await this.client.send(
        new QueryCommand({
          TableName: this.tableName,
          ...params,
          ExclusiveStartKey: exclusiveStartKey,
        }),
      )) as { Items?: Row[]; LastEvaluatedKey?: Row };
      items.push(...(resp.Items ?? []));
      exclusiveStartKey = resp.LastEvaluatedKey;
    } while (exclusiveStartKey);
    return items;
  }

  private async batchGet(keys: Array<{ PK: string; SK: string }>): Promise<Row[]> {
    // DynamoDB rejects a request containing duplicate keys (e.g. two slabs of
    // the same card/company/grade both needing the same GRADEDPRICE row).
    const seen = new Set<string>();
    const unique = keys.filter((k) => {
      const id = `${k.PK}|${k.SK}`;
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });

    const found: Row[] = [];
    for (let i = 0; i < unique.length; i += BATCH_GET_LIMIT) {
      let pending = unique.slice(i, i + BATCH_GET_LIMIT);
      let attempts = 0;
      // Throttled / oversized responses return the remainder as
      // UnprocessedKeys — retry until drained (bounded to stay safe).
      while (pending.length > 0 && attempts < MAX_BATCH_ATTEMPTS) {
        attempts += 1;
        const resp = (await this.client.send(
          new BatchGetCommand({
            RequestItems: { [this.tableName]: { Keys: pending } },
          }),
        )) as {
          Responses?: Record<string, Row[]>;
          UnprocessedKeys?: Record<string, { Keys?: Array<{ PK: string; SK: string }> }>;
        };
        found.push(...(resp.Responses?.[this.tableName] ?? []));
        pending = resp.UnprocessedKeys?.[this.tableName]?.Keys ?? [];
        if (pending.length > 0 && attempts < MAX_BATCH_ATTEMPTS) {
          const delayMs = Math.min(50 * 2 ** (attempts - 1), 1000);
          await new Promise((resolve) => setTimeout(resolve, delayMs));
        }
      }
      if (pending.length > 0) {
        console.error(`batchGet: ${pending.length} keys still unprocessed after retries`);
      }
    }
    return found;
  }
}
