/**
 * The MCP server layer: buildServer(repo) must expose the five inventory tools
 * with names and input schemas matching shared/tool-contract.json — the same
 * file the backend pins its Bedrock tool schemas against.
 *
 * Tests talk to the server through a real MCP client over an in-memory
 * transport: real protocol, no subprocess.
 */
import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { buildServer } from "../server.js";
import type { InventoryRepository } from "../repository.js";
import { InMemoryInventoryRepository } from "./fixtures/in-memory-repository.js";
import { card } from "./fixtures/card.js";

const contract = JSON.parse(
  readFileSync(new URL("../../../shared/tool-contract.json", import.meta.url), "utf-8"),
) as { tools: Array<{ name: string; properties: string[]; required: string[] }> };

async function connect(repo: InventoryRepository): Promise<Client> {
  const server = buildServer(repo);
  const client = new Client({ name: "test-client", version: "0.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return client;
}

type ToolOutcome = { failed: boolean; text: string; parsed?: unknown };

/** Calls a tool, normalizing "rejected" vs "isError result" into one shape. */
async function callTool(
  client: Client,
  name: string,
  args: Record<string, unknown>,
): Promise<ToolOutcome> {
  try {
    const result = await client.callTool({ name, arguments: args });
    const content = result.content as Array<{ type: string; text?: string }>;
    const text = content
      .filter((c) => c.type === "text")
      .map((c) => c.text ?? "")
      .join("");
    if (result.isError) return { failed: true, text };
    return { failed: false, text, parsed: JSON.parse(text) };
  } catch (err) {
    return { failed: true, text: String(err) };
  }
}

describe("tool registration", () => {
  it("exposes exactly the tools from shared/tool-contract.json with matching schemas", async () => {
    const client = await connect(new InMemoryInventoryRepository());
    const { tools } = await client.listTools();

    const byName = new Map(tools.map((t) => [t.name, t]));
    expect([...byName.keys()].sort()).toEqual(contract.tools.map((t) => t.name).sort());

    for (const expected of contract.tools) {
      const schema = byName.get(expected.name)!.inputSchema as {
        properties?: Record<string, unknown>;
        required?: string[];
      };
      expect(Object.keys(schema.properties ?? {}).sort(), expected.name).toEqual(
        [...expected.properties].sort(),
      );
      expect([...(schema.required ?? [])].sort(), expected.name).toEqual(
        [...expected.required].sort(),
      );
    }
  });
});

describe("search_inventory", () => {
  const repo = new InMemoryInventoryRepository([
    card({ id: "base1-4", name: "Charizard", set: "base1", condition: "NM", value: 250 }),
    card({ id: "jungle-60", name: "Pikachu", set: "jungle", condition: "LP", value: 5 }),
  ]);

  it("filters by partial name", async () => {
    const client = await connect(repo);
    const out = await callTool(client, "search_inventory", { name: "char" });
    expect(out.failed).toBe(false);
    const results = out.parsed as Array<{ id: string }>;
    expect(results.map((r) => r.id)).toEqual(["base1-4"]);
  });

  it("filters by set_id and value range using the backend's argument names", async () => {
    const client = await connect(repo);

    const bySet = await callTool(client, "search_inventory", { set_id: "jungle" });
    expect((bySet.parsed as Array<{ id: string }>).map((r) => r.id)).toEqual(["jungle-60"]);

    const byRange = await callTool(client, "search_inventory", {
      min_value: 100,
      max_value: 300,
    });
    expect((byRange.parsed as Array<{ id: string }>).map((r) => r.id)).toEqual(["base1-4"]);

    const byCondition = await callTool(client, "search_inventory", { condition: "NM" });
    expect((byCondition.parsed as Array<{ id: string }>).map((r) => r.id)).toEqual(["base1-4"]);
  });

  it("returns every card for an empty filter object", async () => {
    const client = await connect(repo);
    const out = await callTool(client, "search_inventory", {});
    expect((out.parsed as unknown[]).length).toBe(2);
  });
});

describe("get_inventory_summary", () => {
  it("returns totals as JSON", async () => {
    const repo = new InMemoryInventoryRepository([
      card({ id: "a", value: 10, quantity: 2, set: "base1" }),
      card({ id: "b", value: 5, quantity: 1, set: "jungle" }),
    ]);
    const client = await connect(repo);
    const out = await callTool(client, "get_inventory_summary", {});
    expect(out.failed).toBe(false);
    expect(out.parsed).toMatchObject({ totalCards: 3, totalValue: 25, uniqueSets: 2 });
  });
});

describe("get_card_price_history", () => {
  it("returns the chronologically sorted history", async () => {
    const repo = new InMemoryInventoryRepository(
      [card({ id: "base1-4", name: "Charizard" })],
      new Map([
        [
          "base1-4",
          [
            { date: "2026-06-02", price: 260, source: "pokemontcg.io" },
            { date: "2026-06-01", price: 250, source: "pokemontcg.io" },
          ],
        ],
      ]),
    );
    const client = await connect(repo);
    const out = await callTool(client, "get_card_price_history", { card_id: "base1-4" });
    expect(out.failed).toBe(false);
    expect(out.parsed).toMatchObject({
      cardId: "base1-4",
      cardName: "Charizard",
      history: [
        { date: "2026-06-01", price: 250 },
        { date: "2026-06-02", price: 260 },
      ],
    });
  });

  it("fails with a tool error for a card that is not in the inventory", async () => {
    const client = await connect(new InMemoryInventoryRepository());
    const out = await callTool(client, "get_card_price_history", { card_id: "nope-1" });
    expect(out.failed).toBe(true);
    expect(out.text).toContain("nope-1");
  });
});

describe("calculate_inventory_value", () => {
  it("rounds money to cents in the JSON payload (no float artifacts)", async () => {
    const repo = new InMemoryInventoryRepository([
      card({ id: "a", value: 0.1, quantity: 1, set: "base1", condition: "NM" }),
      card({ id: "b", value: 0.2, quantity: 1, set: "base1", condition: "NM" }),
    ]);
    const client = await connect(repo);
    const out = await callTool(client, "calculate_inventory_value", {});
    expect(out.failed).toBe(false);
    const parsed = out.parsed as { totalValue: number; valueBySet: Record<string, number> };
    expect(parsed.totalValue).toBe(0.3);
    expect(parsed.valueBySet["base1"]).toBe(0.3);
  });
});

describe("flag_underpriced_cards", () => {
  const repo = new InMemoryInventoryRepository([
    card({ id: "deal", name: "Deal", value: 70, marketPrice: 100 }),
    card({ id: "fair", name: "Fair", value: 90, marketPrice: 100 }),
  ]);

  it("interprets threshold as the fraction below market (0.2 = 20% below)", async () => {
    const client = await connect(repo);
    const out = await callTool(client, "flag_underpriced_cards", { threshold: 0.2 });
    expect(out.failed).toBe(false);
    const parsed = out.parsed as {
      flaggedCards: Array<{ id: string }>;
      threshold: number;
    };
    // listed 70 vs market 100 is 30% below → flagged; 90 is only 10% below → not.
    expect(parsed.flaggedCards.map((c) => c.id)).toEqual(["deal"]);
    expect(parsed.threshold).toBe(0.2);
  });

  it("rejects a percent-style threshold instead of silently returning nothing", async () => {
    const client = await connect(repo);
    const out = await callTool(client, "flag_underpriced_cards", { threshold: 20 });
    expect(out.failed).toBe(true);
  });
});
