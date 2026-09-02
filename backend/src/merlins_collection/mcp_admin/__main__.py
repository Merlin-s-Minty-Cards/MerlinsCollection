"""stdio entry point: `python -m merlins_collection.mcp_admin`.

Spawned as a subprocess by `dependencies.get_admin_mcp_executor()`. Config
arrives through the environment the parent hands over (AWS_REGION,
DYNAMODB_TABLE_NAME) exactly as it does for the customer server — see
`services/mcp_client.py`.

stdout belongs to the MCP protocol; anything this process wants to say goes to
stderr.
"""

from merlins_collection.config import settings
from merlins_collection.mcp_admin.server import build_server
from merlins_collection.services.dynamodb import InventoryRepository


def main() -> None:
    repo = InventoryRepository(
        settings.dynamodb_table_name, region_name=settings.aws_region
    )
    build_server(repo).run(transport="stdio")


if __name__ == "__main__":
    main()
