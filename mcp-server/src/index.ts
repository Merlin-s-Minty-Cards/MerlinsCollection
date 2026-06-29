/**
 * MCP server entry point for Merlin's Minty Cards.
 *
 * Connects over stdio so it can be launched as a subprocess by an MCP client
 * (e.g. the backend's Bedrock chat integration).
 *
 * STATUS — skeleton. The inventory tools in `src/tools/` are implemented and
 * tested as plain functions, but they are not yet registered on this server, so
 * it currently exposes no tools. Wiring them up requires two pieces that are
 * tracked as follow-up work (see README.md "Status & roadmap"):
 *   1. A concrete `InventoryRepository` (DynamoDB-backed) to inject into the tools.
 *   2. A `server.registerTool(...)` call per tool, declaring its input schema and
 *      adapting the function's result into an MCP tool response.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new McpServer({
  name: "merlins-collection",
  version: "0.1.0",
});

// TODO: register the tools from src/tools/ once a production InventoryRepository
// exists to inject into them. See README.md "Status & roadmap".

const transport = new StdioServerTransport();
await server.connect(transport);
