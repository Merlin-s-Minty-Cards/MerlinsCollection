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
    cost_basis: 100,
    current_market_value: 300,
    acquired_at: "2026-04-01",
    finish: "holofoil",
    condition: "NM",
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
    cost_basis: 500,
    current_market_value: null,
    acquired_at: "2026-04-01",
    company: "PSA",
    grade: 9.5,
    cert_number: "12345678",
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
        name: "Charizard",
        set: "base1",
        condition: "NM",
        quantity: 1, // one record = one physical unit; legacy quantity is ignored
        value: 250,
        marketPrice: 300,
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

  it("reports marketPrice 0 when no reference price exists anywhere", async () => {
    const { repo } = repoWith({
      "INV#2": [{ Items: [rawItem({ card_id: "sv9-77", current_market_value: null })] }],
    });

    const [card] = await repo.listCards();
    expect(card?.marketPrice).toBe(0);
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
