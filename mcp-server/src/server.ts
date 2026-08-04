/**
 * MCP server construction: registers the inventory tools from src/tools/ on an
 * McpServer.
 *
 * Tool names and input schemas are pinned to shared/tool-contract.json — the
 * same file the backend pins its Bedrock tool schemas against
 * (backend/src/merlins_collection/services/bedrock.py). Change the contract
 * file first, then both sides.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import type { InventoryRepository } from "./repository.js";
import {
  calculateInventoryValue,
  flagUnderpricedCards,
  getCardPriceHistory,
  getInventorySummary,
  searchInventory,
} from "./tools/index.js";

/** Round money floats to cents while serializing (no 45.900000000000006). */
function roundNumbers(_key: string, value: unknown): unknown {
  return typeof value === "number" ? Math.round(value * 100) / 100 : value;
}

function asText(value: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(value, roundNumbers) }] };
}

function asToolError(err: unknown) {
  return {
    content: [{ type: "text" as const, text: err instanceof Error ? err.message : String(err) }],
    isError: true,
  };
}

export function buildServer(repo: InventoryRepository): McpServer {
  const server = new McpServer({ name: "merlins-collection", version: "0.1.0" });

  server.registerTool(
    "search_inventory",
    {
      description: "Search inventory cards by name, set, condition, or value range.",
      inputSchema: {
        name: z.string().optional().describe("Partial card name to match"),
        set_id: z.string().optional().describe("Set identifier (e.g. sv1)"),
        condition: z.string().optional().describe("NM, LP+, LP, LP-, MP, HP, or DMG"),
        min_value: z.number().optional(),
        max_value: z.number().optional(),
        language: z.string().optional().describe("Print language: EN or JP"),
      },
    },
    async ({ name, set_id, condition, min_value, max_value, language }) =>
      asText(
        await searchInventory(repo, {
          name,
          set: set_id,
          condition,
          minValue: min_value,
          maxValue: max_value,
          language,
        }),
      ),
  );

  server.registerTool(
    "get_inventory_summary",
    {
      description: "Return total card count, total value, and top cards by value.",
      inputSchema: {},
    },
    async () => asText(await getInventorySummary(repo)),
  );

  server.registerTool(
    "get_card_price_history",
    {
      description: "Return historical price data for a specific card.",
      inputSchema: {
        card_id: z.string().describe("Card identifier"),
      },
    },
    async ({ card_id }) => {
      try {
        return asText(await getCardPriceHistory(repo, card_id));
      } catch (err) {
        return asToolError(err);
      }
    },
  );

  server.registerTool(
    "calculate_inventory_value",
    {
      description: "Return full inventory valuation broken down by set and condition.",
      inputSchema: {},
    },
    async () => asText(await calculateInventoryValue(repo)),
  );

  server.registerTool(
    "flag_underpriced_cards",
    {
      description: "Return cards listed below market price by a given threshold.",
      inputSchema: {
        threshold: z
          .number()
          .gt(0)
          .lt(1)
          .describe("Fraction below market to flag (e.g. 0.2 = 20% below)"),
      },
    },
    async ({ threshold }) => {
      // The tool speaks percent-of-market (80 = "under 80% of market"); the
      // contract speaks fraction-below (0.2). 0.2 below ≡ under 80%.
      const result = await flagUnderpricedCards(repo, (1 - threshold) * 100);
      return asText({ flaggedCards: result.flaggedCards, threshold });
    },
  );

  return server;
}
