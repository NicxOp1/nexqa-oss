from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Server configuration from environment variables."""
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    public_base_url: str = "http://localhost:8080"  # Set via PUBLIC_BASE_URL env var
    log_level: str = "INFO"
    
    # Airtable (for agent registry + patient records)
    airtable_api_key: str = ""
    airtable_registry_base_id: str = ""  # Set via AIRTABLE_REGISTRY_BASE_ID env var
    airtable_registry_table: str = "AgentRegistry"
    
    # Cal.com (scheduling — primary calendar integration)
    calcom_api_key: str = ""
    calcom_base_url: str = "https://api.cal.com"
    
    # Retell (for SMS + native actions like transfer)
    retell_api_key: str = ""
    
    # Security
    # Verify X-Retell-Signature on every webhook (turn off only for local tests).
    verify_signatures: bool = True
    # Key used to verify signatures; defaults to retell_api_key. Must be the
    # Retell API key that has the webhook badge.
    retell_webhook_key: Optional[str] = None
    # Bearer token for /admin/* endpoints. Admin endpoints are off when unset.
    admin_token: str = ""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore env vars meant for the CLI
    )


settings = Settings()
