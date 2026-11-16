from pydantic_settings import BaseSettings
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
    retell_webhook_secret: Optional[str] = None
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra env vars (like OPENAI_API_KEY)


settings = Settings()
