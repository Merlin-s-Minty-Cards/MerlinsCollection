/**
 * RED test for Council item 1 FATAL: MCP search_inventory must return per-unit item_id.
 *
 * Currently CardResult.id is set to card_id ?? item_id, and neither Card nor
 * CardResult carries an item_id field, so search results yield catalog IDs
 * (e.g., "en:base1-4") which cannot hydrate in display_card.
 *
 * Fix: add item_id: string to Card/CardResult types in repository.ts, populate
 * in toCard() at dynamodb-repository.ts.
 */
import { describe, it, expect } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { buildServer } from "../server.js";
import { InMemoryInventoryRepository } from "./fixtures/in-memory-repository.js";
import { card } from "./fixtures/card.js";

async function connect(repo: InMemoryInventoryRepository): Promise<Client> {
  const server = buildServer(repo);
  const client = new Client({ name: "test-client", version: "0.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return client;
}

describe("search_inventory returns per-unit item_id", () => {
  it("each CardResult must carry item_id distinct from card_id", async () => {
    // Two physical units of the same catalog card
    const repo = new InMemoryInventoryRepository([
      card({
        id: "en:base1-4",
        itemId: "item-unit-1",
        name: "Charizard",
        set: "base1",
        condition: "NM",
        value: 450,
      }),
      card({
        id: "en:base1-4",
        itemId: "item-unit-2",
        name: "Charizard",
        set: "base1",
        condition: "LP",
        value: 350,
      }),
    ]);

    const client = await connect(repo);
    const result = await client.callTool({
      name: "search_inventory",
      arguments: { name: "Charizard" },
    });

    const content = result.content as Array<{ type: string; text?: string }>;
    const text = content.find((c) => c.type === "text")?.text ?? "[]";
    const parsed = JSON.parse(text) as Array<{ id: string; item_id?: string }>;

    // Must return 2 results, one per physical unit
    expect(parsed).toHaveLength(2);

    // Each result MUST carry item_id (the per-unit inventory ID)
    expect(parsed[0]).toHaveProperty("item_id");
    expect(parsed[1]).toHaveProperty("item_id");

    const itemIds = parsed.map((r) => r.item_id);
    expect(itemIds).toContain("item-unit-1");
    expect(itemIds).toContain("item-unit-2");

    // id field may still be card_id for catalog lookups, but item_id must be distinct
    // for hydration in display_card
  });

  it("uncatalogued cards (card_id=null) must still return item_id", async () => {
    const repo = new InMemoryInventoryRepository([
      card({
        id: "", // no card_id
        itemId: "item-orphan-1",
        name: "Uncatalogued Promo",
        set: "",
        condition: "NM",
        value: 25,
      }),
    ]);

    const client = await connect(repo);
    const result = await client.callTool({
      name: "search_inventory",
      arguments: { name: "Uncatalogued" },
    });

    const content = result.content as Array<{ type: string; text?: string }>;
    const text = content.find((c) => c.type === "text")?.text ?? "[]";
    const parsed = JSON.parse(text) as Array<{ item_id?: string }>;

    expect(parsed).toHaveLength(1);
    expect(parsed[0].item_id).toBe("item-orphan-1");
  });
});
