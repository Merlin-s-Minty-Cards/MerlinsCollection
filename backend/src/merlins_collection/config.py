"""Application settings, loaded from environment variables or a ``.env`` file.

A single module-level ``settings`` instance is imported across the app. Field
names map to upper-case env vars (``aws_region`` ← ``AWS_REGION``); unknown env
vars are ignored. Defaults are dev-friendly — production supplies real values
via the environment, and AWS credentials normally come from the ambient
credential chain rather than the (empty-by-default) fields here.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration for AWS, Cognito, DynamoDB, Bedrock, and integrations."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = "us-east-1"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    dynamodb_table_name: str = "merlins-cards"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    mcp_server_path: str = "../mcp-server/dist/index.js"
    pokemontcg_api_key: str = ""
    # Comma-separated browser origins allowed to call the API (CORS).
    cors_origins: str = "http://localhost:3000"
    # Dev-only: inject a fake user instead of verifying Cognito JWTs.
    # NEVER set in production.
    auth_disabled: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
