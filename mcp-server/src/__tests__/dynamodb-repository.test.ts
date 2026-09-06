/**
 * DynamoDbInventoryRepository reads the backend's single-table layout (see
 * backend/src/merlins_collection/services/dynamodb.py — the key formats are
 * mirrored there) and adapts it to the tools' Card / PricePoint domain.
 *
 * The DocumentClient is stubbed at the send() boundary with responses shaped
 * exactly like @aws-sdk/lib-dynamodb output (numbers as JS numbers, None → null).
 */
import { describe, it, expect } from "vitest";

import { DynamoDbInventoryRepository } from "../dynamodb-repository.js";
import { getInventorySummary } from "../tools/get-inventory-summary.js";

const TABLE = "merlins-cards";

type Item = Record<string, unknown>;
type Page = { Items: Item[]; last?: boolean };

/**
 * Minimal DocumentClient fake: routes commands by input shape (Query by PK
 * value, Get/BatchGet by key) so the repository is free to choose its exact
 * expression strings and get-vs-batchget strategy.
 */
class StubDocClient {
  readonly queryInputs: Item[] = [];
  /** When true, the FIRST BatchGet returns all but one key as UnprocessedKeys. */
  deferKeysOnce = false;

  constructor(
    /** Query pages keyed by partition value, e.g. "INV#0" or "CARD#base1-4". */
    private readonly partitions: Record<string, Page[]> = {},
    /** Point-lookup items keyed by "PK|SK", e.g. "CARD#base1-4|META". */
    private readonly rows: Record<string, Item> = {},
  ) {}

  async send(command: { input: Item }): Promise<Item> {
    const input = command.input;

    if (input.RequestItems) {
      let keys = (input.RequestItems as Record<string, { Keys: Array<{ PK: string; SK: string }> }>)[
        TABLE
      ]!.Keys;
      // Real DynamoDB rejects the whole request on duplicate keys.
      if (new Set(keys.map((k) => `${k.PK}|${k.SK}`)).size !== keys.length) {
        throw new Error("ValidationException: Provided list of item keys contains duplicates");
      }
      let unprocessed: Array<{ PK: string; SK: string }> = [];
      if (this.deferKeysOnce && keys.length > 1) {
        this.deferKeysOnce = false;
        unprocessed = keys.slice(1);
        keys = keys.slice(0, 1);
      }
      const found = keys.map((k) => this.rows[`${k.PK}|${k.SK}`]).filter(Boolean);
      const response: Item = { Responses: { [TABLE]: found } };
      if (unprocessed.length > 0) {
        response.UnprocessedKeys = { [TABLE]: { Keys: unprocessed } };
      }
      return response;
    }
    if (input.Key) {
      const k = input.Key as { PK: string; SK: string };
      return { Item: this.rows[`${k.PK}|${k.SK}`] };
    }

    // Query: find the partition key value among the expression values.
    this.queryInputs.push(input);
    const values = Object.values((input.ExpressionAttributeValues as Item) ?? {});
    const pk = values.find(
      (v) => typeof v === "string" && (v.startsWith("INV#") || v.startsWith("CARD#")),
    ) as string | undefined;
    const pages = this.partitions[pk ?? ""] ?? [{ Items: [] }];
    const pageIndex = (input.ExclusiveStartKey as { page?: number } | undefined)?.page ?? 0;
    const page = pages[pageIndex] ?? { Items: [] };
    return {
      Items: page.Items,
      LastEvaluatedKey: pageIndex + 1 < pages.length ? { page: pageIndex + 1 } : undefined,
    };
  }
}

// Post Database-Redesign rows: keyed by item_id, carry status, no quantity
// (one record = one physical unit). Only available, customer-visible kinds
// (raw/graded/sealed — never bulk) reach the public tools.
function rawItem(overrides: Item = {}): Item {
  return {
    PK: "INV#0",
    SK: "ITEM#01JRAW000000000000000001",
    entity: "inventory_item",
    kind: "raw",
    item_id: "01JRAW000000000000000001",
    card_id: "base1-4",
    status: "available",
    listed_price: 250,
    // RFC 0025: `isPublicInventory` now requires a sticker price. Deliberately
    // a DIFFERENT figure from `listed_price`/`current_market_value` in this
    // default fixture, so a test asserting on `card.value` (sticker) versus
    // `card.marketPrice` (the old catalog-derived reference, unaffected by
    // RFC 0025) can never pass by the two numbers coincidentally matching.
    sticker_price: 225,
    cost_basis: 100,
    current_market_value: 300,
    acquired_at: "2026-04-01",
    finish: "holofoil",
    condition: "NM",
    location: "glass",
    ...overrides,
  };
}

function gradedItem(overrides: Item = {}): Item {
  return {
    PK: "INV#1",
    SK: "ITEM#01JGRADED0000000000000001",
    entity: "inventory_item",
    kind: "graded",
    item_id: "01JGRADED0000000000000001",
    card_id: "base1-4",
    status: "available",
    listed_price: 900,
    sticker_price: 850,
    cost_basis: 500,
    current_market_value: null,
    acquired_at: "2026-04-01",
    company: "PSA",
    grade: 9.5,
    cert_number: "12345678",
    location: "glass",
    ...overrides,
  };
}

function sealedItem(overrides: Item = {}): Item {
  return {
    PK: "INV#2",
    SK: "ITEM#01JSEALED0000000000000001",
    entity: "inventory_item",
    kind: "sealed",
    item_id: "01JSEALED0000000000000001",
    status: "available",
    listed_price: 120,
    cost_basis: 90,
    current_market_value: 140,
    acquired_at: "2026-04-01",
    product_name: "Scarlet & Violet Booster Box",
    product_type: "booster_box",
    ...overrides,
  };
}

function meta(cardId: string, overrides: Item = {}): Item {
  return {
    PK: `CARD#${cardId}`,
    SK: "META",
    entity: "catalog_card",
    card_id: cardId,
    name: "Charizard",
    set_id: "base1",
    set_name: "Base",
    number: "4",
    rarity: "Rare Holo",
    types: ["Fire"],
    images: { small: "https://img/s.png", large: "https://img/l.png" },
    prices: { holofoil: { market: 320.5, low: 200, mid: 280, high: 400 } },
    last_synced_at: "2026-07-01T00:00:00+00:00",
    ...overrides,
  };
}

function repoWith(partitions: Record<string, Page[]>, rows: Record<string, Item> = {}) {
  const client = new StubDocClient(partitions, rows);
  return { repo: new DynamoDbInventoryRepository(client, TABLE), client };
}

describe("listCards", () => {
  it("joins inventory items with catalog metadata", async () => {
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem()] }] },
      { "CARD#base1-4|META": meta("base1-4") },
    );

    const cards = await repo.listCards();

    expect(cards).toEqual([
      {
        id: "base1-4",
        itemId: "01JRAW000000000000000001",
        name: "Charizard",
        set: "base1",
        condition: "NM",
        quantity: 1, // one record = one physical unit; legacy quantity is ignored
        // RFC 0025: `value` is the STICKER (225, this fixture's default) —
        // the customer price — and no longer the resolved catalog/market
        // figure at all. `marketPrice` keeps the OLD resolution (RFC 0008
        // §D: the live catalog holofoil band, 320.5, over the denormalized
        // current_market_value, 300) because it now serves a different job
        // (the underpricing comparison `flag_underpriced_cards` makes), not
        // because it is still "the" customer price.
        value: 225,
        marketPrice: 320.5,
        language: "EN", // no stored language attribute → defaults to EN
      },
    ]);
  });

  it("defaults language to EN when the row has no language attribute", async () => {
    // Only the 109 JP items carry a stored language; every EN row omits it.
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem()] }] },
      { "CARD#base1-4|META": meta("base1-4") },
    );

    const [card] = await repo.listCards();
    expect(card?.language).toBe("EN");
  });

  it("reads the stored JP language for a raw item (card_id None by design)", async () => {
    // A JP print has no English catalog match, so card_id is null; the language
    // still comes straight off the row.
    const { repo } = repoWith({
      "INV#0": [{ Items: [rawItem({ language: "JP", card_id: null })] }],
    });

    const [card] = await repo.listCards();
    expect(card?.language).toBe("JP");
  });

  // NOTE (RFC 0001): the former "reads the stored JP language for a sealed
  // product" test was removed here. It asserted a sealed item surfaces from
  // listCards, which directly contradicts the binding owner decision to HIDE
  // sealed (see the "excludes sealed products …" test below). JP language
  // reading stays covered by the raw/graded cases above.

  it("hides items that are not available (sold / on-hold / lost stay internal)", async () => {
    const { repo } = repoWith(
      {
        "INV#0": [{ Items: [rawItem({ status: "sold" })] }],
        "INV#1": [{ Items: [gradedItem({ status: "on_hold" })] }],
      },
      { "CARD#base1-4|META": meta("base1-4") },
    );
    expect(await repo.listCards()).toEqual([]);
  });

  it("excludes bulk lots from the customer-facing projection", async () => {
    const { repo } = repoWith({
      "INV#3": [{
        Items: [{
          PK: "INV#3", SK: "ITEM#01JBULK00000000000000001",
          entity: "inventory_item", kind: "bulk",
          item_id: "01JBULK00000000000000001", status: "available",
          listed_price: 5, cost_basis: 0, description: "5k bulk lot",
        }],
      }],
    });
    expect(await repo.listCards()).toEqual([]);
  });

  // RFC 0001 owner decision (binding, overrides the earlier "keep sealed
  // visible" recommendation): sealed products (kind=sealed) are hidden from
  // the customer-facing chat tools entirely — cards-only surface. "sealed"
  // must be removed from PUBLIC_KINDS (dynamodb-repository.ts:33).
  it("excludes sealed products from the customer-facing projection (cards-only surface, RFC 0001)", async () => {
    const { repo } = repoWith({ "INV#2": [{ Items: [sealedItem()] }] });
    expect(await repo.listCards()).toEqual([]);
  });

  // Phase 5 (D3, display scoping): the backend's customer_visible_items() now
  // adds a location gate (location in {glass, toploader} OR factory_sealed) on
  // top of kind+status. isPublicInventory() must mirror it so a raw item with
  // no visible location (e.g. still in a binder/storage) never reaches the
  // chat tools even though it's an available raw/graded item.
  it("excludes an available raw item with no customer-visible location", async () => {
    const { repo } = repoWith({
      "INV#0": [{ Items: [rawItem({ location: null, factory_sealed: false })] }],
    });
    expect(await repo.listCards()).toEqual([]);
  });

  it("includes an available raw item stored in glass", async () => {
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ location: "glass" })] }] },
      { "CARD#base1-4|META": meta("base1-4") },
    );
    const cards = await repo.listCards();
    expect(cards).toHaveLength(1);
  });

  it("fans out across all ten inventory shards", async () => {
    const { repo, client } = repoWith({}, {});
    await repo.listCards();

    const queried = client.queryInputs
      .flatMap((q) => Object.values((q.ExpressionAttributeValues as Item) ?? {}))
      .filter((v) => typeof v === "string" && (v as string).startsWith("INV#"));
    expect([...new Set(queried)].sort()).toEqual(
      Array.from({ length: 10 }, (_, i) => `INV#${i}`).sort(),
    );
  });

  it("follows LastEvaluatedKey pagination within a shard", async () => {
    const { repo } = repoWith(
      {
        "INV#0": [
          { Items: [rawItem({ SK: "CARD#base1-4#RAW#holofoil#NM" })] },
          { Items: [rawItem({ SK: "CARD#base1-4#RAW#holofoil#LP", condition: "LP" })] },
        ],
      },
      { "CARD#base1-4|META": meta("base1-4") },
    );

    const cards = await repo.listCards();
    expect(cards).toHaveLength(2);
  });

  it("labels graded items with company and grade as the condition", async () => {
    const { repo } = repoWith(
      { "INV#1": [{ Items: [gradedItem()] }] },
      { "CARD#base1-4|META": meta("base1-4") },
    );

    const [card] = await repo.listCards();
    expect(card?.condition).toBe("PSA 9.5");
  });

  it("falls back to card_id for the name and the id prefix for the set when the catalog row is missing", async () => {
    const { repo } = repoWith({
      "INV#2": [{ Items: [rawItem({ card_id: "sv9-77", SK: "CARD#sv9-77#RAW#normal#NM" })] }],
    });

    const [card] = await repo.listCards();
    expect(card?.name).toBe("sv9-77");
    expect(card?.set).toBe("sv9");
  });

  // ---- RFC 0001 MUST-FIX A/C: read the materialized display_name field ----
  // docs/rfcs/0001-inventory-catalog-relink-and-display-fallback.md, section C.5.
  // The sanitized name is composed ONCE, at import, from the structured Name +
  // Card # columns and stored on the row as `display_name` (backend
  // services/card_text.format_display_name). MCP reads that single stored field
  // verbatim — it does NOT parse `notes` at all — so the ~90-line notes parser is
  // gone and backend/MCP parity is structural, not hand-synced. This closes the
  // "chat shows only the card ID, no name" bug without any free-text path.

  it("uses the stored display_name when the catalog is missing and card_id is null", async () => {
    const { repo } = repoWith({
      "INV#0": [{ Items: [rawItem({ card_id: null, display_name: "Dragonair #181" })] }],
    });

    const [card] = await repo.listCards();
    expect(card?.name).toBe("Dragonair #181");
  });

  it("uses the stored display_name for a graded slab too", async () => {
    const { repo } = repoWith({
      "INV#1": [{ Items: [gradedItem({ card_id: null, display_name: "Charizard #4" })] }],
    });

    const [card] = await repo.listCards();
    expect(card?.name).toBe("Charizard #4");
  });

  // MCP never reads `notes`: a row carrying internal Notes free-text but NO stored
  // display_name falls back to the ULID, so cost/consignor/location text can never
  // reach the model. (Under the old read-time parser a trailing " #<digits>" leaked
  // — that whole class of bug is gone with the parser.)
  it("falls back to the item_id when there is no display_name, never parsing notes", async () => {
    const item = rawItem({
      card_id: null,
      display_name: null,
      notes: "cost 40 sold to David #12",
    });
    const { repo } = repoWith({ "INV#0": [{ Items: [item] }] });

    const [card] = await repo.listCards();
    expect(card?.name).toBe(String(item.item_id)); // ULID fallback, not the note
    expect(card?.name).not.toContain("David");
    expect(card?.name).not.toContain("cost 40");
    expect(card?.name).not.toContain("12");
  });

  it("ignores notes entirely even when they look like an identity segment", async () => {
    // A row whose notes read like "<name> #<n>" but which stored no display_name
    // still falls back to the ULID — the name comes only from the stored field.
    const item = rawItem({ card_id: null, notes: "Dragonair #181.0 — 30-32" });
    const { repo } = repoWith({ "INV#0": [{ Items: [item] }] });

    const [card] = await repo.listCards();
    expect(card?.name).toBe(String(item.item_id));
    expect(card?.name).not.toContain("30-32");
  });

  it("prefers the catalog name over a stored display_name for a matched item", async () => {
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ card_id: "base1-4", display_name: "Stale #99" })] }] },
      { "CARD#base1-4|META": meta("base1-4") },
    );

    const [card] = await repo.listCards();
    expect(card?.name).toBe("Charizard"); // catalog META wins over display_name
  });

  it("uses the catalog finish market price when the item has no synced market value", async () => {
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ current_market_value: null })] }] },
      { "CARD#base1-4|META": meta("base1-4") },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(320.5);
  });

  it("uses the manual graded price row for graded items with no synced market value", async () => {
    const { repo } = repoWith(
      { "INV#1": [{ Items: [gradedItem()] }] },
      {
        "CARD#base1-4|META": meta("base1-4"),
        "CARD#base1-4|GRADEDPRICE#PSA#9.5": {
          entity: "graded_price",
          card_id: "base1-4",
          company: "PSA",
          grade: 9.5,
          market_value: 950,
        },
      },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(950);
  });

  it("dedupes graded-price keys — two slabs of the same card/grade must not kill the batch", async () => {
    // Real DynamoDB rejects a BatchGetItem containing duplicate keys; two PSA
    // 9.5 copies with different certs would otherwise produce exactly that.
    const { repo } = repoWith(
      {
        "INV#1": [
          {
            Items: [
              gradedItem({ cert_number: "11111111", SK: "CARD#base1-4#GRADED#PSA#9.5#11111111" }),
              gradedItem({ cert_number: "22222222", SK: "CARD#base1-4#GRADED#PSA#9.5#22222222" }),
            ],
          },
        ],
      },
      {
        "CARD#base1-4|META": meta("base1-4"),
        "CARD#base1-4|GRADEDPRICE#PSA#9.5": {
          entity: "graded_price",
          card_id: "base1-4",
          company: "PSA",
          grade: 9.5,
          market_value: 950,
        },
      },
    );

    const cards = await repo.listCards();
    expect(cards).toHaveLength(2);
    expect(cards.map((c) => c.marketPrice)).toEqual([950, 950]);
  });

  it("retries UnprocessedKeys so throttled batches still join every catalog row", async () => {
    const { repo, client } = repoWith(
      {
        "INV#0": [
          {
            Items: [
              rawItem(),
              rawItem({ card_id: "jungle-60", SK: "CARD#jungle-60#RAW#normal#NM" }),
            ],
          },
        ],
      },
      {
        "CARD#base1-4|META": meta("base1-4"),
        "CARD#jungle-60|META": meta("jungle-60", { name: "Pikachu", set_id: "jungle" }),
      },
    );
    client.deferKeysOnce = true;

    const cards = await repo.listCards();
    expect(cards.map((c) => c.name).sort()).toEqual(["Charizard", "Pikachu"]);
  });

  it("reports no marketPrice at all when no reference price exists anywhere", async () => {
    // No catalog row, no denormalized value, no listed price → null, NOT 0.
    // A zero would be summed into totals as a real $0 valuation and would rank
    // in topValuedCards; null lets the callers skip the item the way the
    // backend's /inventory/summary skips it.
    const { repo } = repoWith({
      "INV#2": [{
        Items: [rawItem({ card_id: "sv9-77", current_market_value: null, listed_price: null })],
      }],
    });

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBeNull();
  });
});

// ---- RFC 0008 §D (T3): price resolution must mirror /inventory/summary ----
// The backend resolves a price LIVE first (models/inventory._market_price against
// the catalog), and only falls back to the stored current_market_value ??
// listed_price. This repository used to do the exact opposite, so whenever the
// nightly denormalizer lagged the catalog, get_inventory_summary and
// calculate_inventory_value summed stale figures while the dashboard summed live
// ones. See routers/inventory.py:377-397.
describe("display_name_override (mirrors itemTitle / adminItemName)", () => {
  it("prefers an admin's override over the catalog name", async () => {
    // The whole point of the override: a Japanese card whose catalog row is in
    // Japanese script gets an admin-typed English name. Filter mode already
    // honoured it; chat read the catalog name, so the two halves of /inventory
    // called the same card different things.
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ display_name_override: "Chespin" })] }] },
      { "CARD#base1-4|META": meta("base1-4", { name: "ハリマロン" }) },
    );

    const [card] = await repo.listCards();
    expect(card?.name).toBe("Chespin");
  });

  it("prefers the override over the materialized display_name when unmatched", async () => {
    const { repo } = repoWith(
      {
        "INV#0": [
          {
            Items: [
              rawItem({
                card_id: null,
                display_name: "ハリマロン #84",
                display_name_override: "Chespin #84",
              }),
            ],
          },
        ],
      },
      {},
    );

    const [card] = await repo.listCards();
    expect(card?.name).toBe("Chespin #84");
  });

  it("ignores a blank override rather than naming a card after whitespace", async () => {
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ display_name_override: "   " })] }] },
      { "CARD#base1-4|META": meta("base1-4", { name: "Charizard" }) },
    );

    const [card] = await repo.listCards();
    expect(card?.name).toBe("Charizard");
  });

  it("still uses the catalog name when no override is set", async () => {
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem()] }] },
      { "CARD#base1-4|META": meta("base1-4", { name: "Charizard" }) },
    );

    const [card] = await repo.listCards();
    expect(card?.name).toBe("Charizard");
  });
});

describe("marketPrice resolution order (mirrors /inventory/summary)", () => {
  it("prefers the live catalog price over a stale current_market_value", async () => {
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ current_market_value: 400 })] }] },
      { "CARD#base1-4|META": meta("base1-4", { prices: { holofoil: { market: 517 } } }) },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(517);
  });

  it("applies the condition multiplier to the live catalog price", async () => {
    // The backend adjusts on the customer path and in /inventory/summary; chat
    // reads DynamoDB directly, so it has to apply the same multiplier or the
    // two halves of /inventory quote different prices for the same card.
    // DMG = 0.15x, so a $100 NM catalog figure is a $15 card.
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ condition: "DMG", current_market_value: null })] }] },
      { "CARD#base1-4|META": meta("base1-4", { prices: { holofoil: { market: 100 } } }) },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(15);
  });

  it("honours a condition modifier when adjusting the live price", async () => {
    // LP+ is the midpoint of LP (0.82) and NM (1.00) -> 0.91x.
    const { repo } = repoWith(
      {
        "INV#0": [
          {
            Items: [
              rawItem({ condition: "LP", condition_modifier: "+", current_market_value: null }),
            ],
          },
        ],
      },
      { "CARD#base1-4|META": meta("base1-4", { prices: { holofoil: { market: 100 } } }) },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(91);
  });

  it("leaves a Near Mint live price exactly alone", async () => {
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ condition: "NM", current_market_value: null })] }] },
      { "CARD#base1-4|META": meta("base1-4", { prices: { holofoil: { market: 42.5 } } }) },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(42.5);
  });

  it("does not re-adjust the stored current_market_value", async () => {
    // refresh_inventory_market_values already baked the multiplier into that
    // field. Adjusting the fallback too would apply it twice and under-quote.
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ condition: "DMG", current_market_value: 15 })] }] },
      { "CARD#base1-4|META": meta("base1-4", { prices: {} }) },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(15);
  });

  it("falls back to current_market_value when the catalog carries no market figure", async () => {
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ current_market_value: 250 })] }] },
      { "CARD#base1-4|META": meta("base1-4", { prices: {} }) },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(250);
  });

  it("falls back to listed_price when there is no catalog figure and no synced value", async () => {
    // Last rung of the backend's `current_market_value ?? listed_price` fallback.
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ current_market_value: null, listed_price: 175 })] }] },
      { "CARD#base1-4|META": meta("base1-4", { prices: {} }) },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(175);
  });

  it("gives a graded slab no catalog price, keeping its own stored figure", async () => {
    // A slab has no finish and carries a grade premium the catalog does not
    // know, so _market_price refuses to price it (inventory.py:316-319) and the
    // caller keeps the slab's own value — even when the catalog is much cheaper.
    const { repo } = repoWith(
      { "INV#1": [{ Items: [gradedItem({ current_market_value: 700 })] }] },
      { "CARD#base1-4|META": meta("base1-4", { prices: { holofoil: { market: 320.5 } } }) },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(700);
  });

  it("resolves the item's own finish band, not merely the first one listed", async () => {
    const { repo } = repoWith(
      {
        "INV#0": [{
          Items: [rawItem({ finish: "reverseHolofoil", current_market_value: 400 })],
        }],
      },
      {
        "CARD#base1-4|META": meta("base1-4", {
          prices: { normal: { market: 12 }, reverseHolofoil: { market: 88 } },
        }),
      },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(88);
  });

  it("skips a catalog band whose market figure is not a number", async () => {
    // MCP reads the raw DynamoDB map; unlike the Python side there is no pydantic
    // gate turning garbage into None. With the catalog lookup now FIRST, a band of
    // "N/A" would coerce to $0 and outrank a good current_market_value.
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ current_market_value: 400 })] }] },
      {
        "CARD#base1-4|META": meta("base1-4", {
          prices: { holofoil: { market: "N/A" }, normal: { market: 61 } },
        }),
      },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(61); // walks on to the next band, not 0
  });

  it("keeps a catalog band that is genuinely zero", async () => {
    // 0 is a real price the Python side would return; only non-numeric bands skip.
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ current_market_value: 400 })] }] },
      { "CARD#base1-4|META": meta("base1-4", { prices: { holofoil: { market: 0 } } }) },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(0);
  });

  it("takes no catalog price for a raw row that stores no finish", async () => {
    // _market_price returns None on a falsy finish (inventory.py:321-322) rather
    // than assuming "normal". Mirroring that matters more now the catalog lookup
    // runs FIRST: guessing a band here would silently misprice the row.
    const { repo } = repoWith(
      { "INV#0": [{ Items: [rawItem({ finish: null, current_market_value: 400 })] }] },
      { "CARD#base1-4|META": meta("base1-4", { prices: { normal: { market: 12 } } }) },
    );

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(400);
  });
});

// RFC 0025: `getInventorySummary`'s total used to have a documented backend
// equivalent (`/inventory/summary`'s `est_value`) this test proved agreement
// with, fixing a bug where the two disagreed. `est_value` was DELETED in T5,
// not merely renamed, so there is no backend figure left to agree with —
// this now pins `totalValue` as purely this tool's own sum of `value`
// (sticker prices), which is what RFC 0025 T2/T4 made `value` mean.
//
// The old fixture's fourth row (an "unpriced but still held" item) is gone
// too: a customer-visible row without a sticker is now a contradiction —
// `isPublicInventory` excludes it before `listCards` ever sees it — so
// "held but unpriced, counted in totalCards but not totalValue" is no
// longer a reachable state to test, the same way `hidden_no_price` became
// structurally zero on the backend.
describe("chat totals sum sticker prices", () => {
  it("sums each card's sticker price, not the old catalog/market resolution", async () => {
    const { repo } = repoWith(
      {
        "INV#0": [{
          Items: [
            rawItem({
              SK: "ITEM#01JRAW000000000000000001",
              item_id: "01JRAW000000000000000001",
              sticker_price: 480,
              current_market_value: 400, // decoy — must not be what's summed
            }),
            rawItem({
              SK: "ITEM#01JRAW000000000000000002",
              item_id: "01JRAW000000000000000002",
              card_id: null, // JP print: no catalog match by design
              display_name: "Chespin #84",
              sticker_price: 250,
            }),
          ],
        }],
        "INV#1": [{ Items: [gradedItem({ sticker_price: 700, current_market_value: 999 })] }],
      },
      { "CARD#base1-4|META": meta("base1-4", { prices: { holofoil: { market: 517 } } }) },
    );

    const summary = await getInventorySummary(repo);

    expect(summary.totalValue).toBe(1430); // 480 + 250 + 700
    expect(summary.totalCards).toBe(3);
    expect(summary.topValuedCards).toEqual([
      { name: "Charizard", value: 700 }, // the slab
      { name: "Charizard", value: 480 }, // the raw item
      { name: "Chespin #84", value: 250 },
    ]);
  });
});

describe("getPriceHistory", () => {
  const pricePoints: Item[] = [
    {
      PK: "CARD#base1-4",
      SK: "PRICE#RAW#holofoil#2026-06-01",
      entity: "price_point",
      kind: "raw",
      finish: "holofoil",
      date: "2026-06-01",
      source: "pokemontcg.io",
      market: 300,
      low: 250,
      mid: 280,
    },
    {
      PK: "CARD#base1-4",
      SK: "PRICE#RAW#holofoil#2026-06-02",
      entity: "price_point",
      kind: "raw",
      finish: "holofoil",
      date: "2026-06-02",
      source: "pokemontcg.io",
      market: null,
      mid: 290,
      low: 260,
    },
    {
      PK: "CARD#base1-4",
      SK: "PRICE#GRADED#PSA#10#2026-06-01",
      entity: "price_point",
      kind: "graded",
      company: "PSA",
      grade: 10,
      date: "2026-06-01",
      source: "manual",
      market: 900,
    },
    {
      PK: "CARD#base1-4",
      SK: "PRICE#RAW#holofoil#2026-06-03",
      entity: "price_point",
      kind: "raw",
      finish: "holofoil",
      date: "2026-06-03",
      source: "pokemontcg.io",
      market: null,
      mid: null,
      low: null,
    },
  ];

  it("maps points to {date, price, source}, tagging the series so raw and graded don't blur", async () => {
    const { repo } = repoWith({ "CARD#base1-4": [{ Items: pricePoints }] });

    const history = await repo.getPriceHistory("base1-4");

    expect(history).toContainEqual({
      date: "2026-06-01",
      price: 300,
      source: "pokemontcg.io (holofoil)",
    });
    expect(history).toContainEqual({
      date: "2026-06-01",
      price: 900,
      source: "manual (PSA 10)",
    });
  });

  it("falls back market → mid → low and skips points with no price at all", async () => {
    const { repo } = repoWith({ "CARD#base1-4": [{ Items: pricePoints }] });

    const history = await repo.getPriceHistory("base1-4");

    expect(history).toContainEqual({
      date: "2026-06-02",
      price: 290,
      source: "pokemontcg.io (holofoil)",
    });
    expect(history.map((p) => p.date)).not.toContain("2026-06-03");
  });

  it("queries only the PRICE# key space (no META / GRADEDPRICE rows)", async () => {
    const { repo, client } = repoWith({ "CARD#base1-4": [{ Items: [] }] });
    await repo.getPriceHistory("base1-4");

    const values = client.queryInputs.flatMap((q) =>
      Object.values((q.ExpressionAttributeValues as Item) ?? {}),
    );
    expect(values).toContain("CARD#base1-4");
    expect(values.some((v) => typeof v === "string" && (v as string).startsWith("PRICE#"))).toBe(
      true,
    );
  });
});
