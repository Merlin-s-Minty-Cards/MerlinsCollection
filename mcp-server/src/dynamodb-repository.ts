/**
 * DynamoDB-backed InventoryRepository reading the backend's single-table layout.
 *
 * Key formats mirror backend/src/merlins_collection/services/dynamodb.py — that
 * module is the authority on the schema (and on INVENTORY_SHARD_COUNT):
 *   inventory   PK=INV#<shard 0-9>   SK=CARD#<id>#RAW#... | CARD#<id>#GRADED#...
 *   catalog     PK=CARD#<id>         SK=META
 *   graded $    PK=CARD#<id>         SK=GRADEDPRICE#<company>#<grade>
 *   history     PK=CARD#<id>         SK=PRICE#RAW#<finish>#<date> | PRICE#GRADED#...
 *
 * Inventory rows are joined with catalog metadata to produce the tools' flat
 * `Card` shape; when a catalog row is missing the card_id doubles as the name
 * and its prefix (e.g. "base1" from "base1-4") as the set.
 */
import { BatchGetCommand, QueryCommand } from "@aws-sdk/lib-dynamodb";
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

// The customer-facing projection: only available items of customer-visible
// kinds. Bulk lots, and anything sold/on-hold/lost/out-for-grading, are
// internal and must never reach the (unauthenticated) chat tools. This mirrors
// the backend /inventory/search rules; admin-only tools come later.
const PUBLIC_KINDS = new Set(["raw", "graded", "sealed"]);

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
  return PUBLIC_KINDS.has(String(row.kind)) && row.status === "available";
}

/** Canonical grade string, matching the backend's `_grade_key` (10 not 10.0). */
function gradeKey(grade: unknown): string {
  return String(Number(grade));
}

function asNumber(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
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
      return {
        id: String(row.item_id),
        name: String(row.product_name),
        set: "Sealed",
        condition: SEALED_TYPE_LABELS[String(row.product_type)] ?? "Sealed",
        quantity: 1,
        value: asNumber(row.listed_price),
        marketPrice: asNumber(row.current_market_value ?? 0),
      };
    }
    // Raw/graded: card_id is an optional catalog link; fall back to item_id.
    const cardId = row.card_id != null ? String(row.card_id) : null;
    const meta = cardId ? catalog.get(cardId) : undefined;
    const fallback = cardId ?? String(row.item_id);
    return {
      id: fallback,
      name: meta ? String(meta.name) : fallback,
      set: meta ? String(meta.set_id) : cardId ? cardId.split("-")[0]! : "Unknown",
      condition:
        row.kind === "raw"
          ? `${row.condition}${row.condition_modifier ?? ""}`
          : `${row.company} ${gradeKey(row.grade)}`,
      quantity: 1, // one inventory record = one physical unit
      value: asNumber(row.listed_price),
      marketPrice: this.marketPrice(row, meta, gradedPrices),
    };
  }

  private marketPrice(
    row: Row,
    meta: Row | undefined,
    gradedPrices: Map<string, Row>,
  ): number {
    if (row.current_market_value != null) return asNumber(row.current_market_value);
    if (row.kind === "graded") {
      const key = `${row.card_id}#${row.company}#${gradeKey(row.grade)}`;
      return asNumber(gradedPrices.get(key)?.market_value ?? 0);
    }
    const prices = meta?.prices as Record<string, { market?: unknown }> | undefined;
    return asNumber(prices?.[String(row.finish)]?.market ?? 0);
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
