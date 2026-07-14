/**
 * MCP server entry point for Merlin's Minty Cards.
 *
 * Connects over stdio so it can be launched as a subprocess by an MCP client —
 * in production, the backend's McpToolExecutor
 * (backend/src/merlins_collection/services/mcp_client.py) spawns
 * `node dist/index.js` and calls the tools during Bedrock chat turns.
 *
 * Configuration comes from the environment (inherited from the backend
 * process): AWS_REGION, DYNAMODB_TABLE_NAME, and the ambient AWS credential
 * chain for DynamoDB access.
 */
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { DynamoDbInventoryRepository } from "./dynamodb-repository.js";
import { buildServer } from "./server.js";

const region = process.env.AWS_REGION ?? "us-east-1";
const tableName = process.env.DYNAMODB_TABLE_NAME ?? "merlins-cards";

const documentClient = DynamoDBDocumentClient.from(new DynamoDBClient({ region }));
const repository = new DynamoDbInventoryRepository(documentClient, tableName);

const server = buildServer(repository);
await server.connect(new StdioServerTransport());

// stdout belongs to the MCP protocol — log to stderr only.
console.error(`merlins-collection MCP server ready (region=${region}, table=${tableName})`);
