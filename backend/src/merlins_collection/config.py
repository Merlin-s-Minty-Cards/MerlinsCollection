from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    dynamodb_table_name: str = "merlins-cards"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    mcp_server_path: str = "../mcp-server/dist/index.js"
    pokemontcg_api_key: str = ""


settings = Settings()
