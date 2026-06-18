import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new McpServer({
  name: "merlins-collection",
  version: "0.1.0",
});

// Tools are registered here as they are implemented via TDD
// import and wire up each tool from src/tools/

const transport = new StdioServerTransport();
await server.connect(transport);
