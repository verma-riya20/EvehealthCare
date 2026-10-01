from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or a local .env file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "EVE Diagnostics Booking API"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://eve:eve@localhost:5432/eve"

    jwt_secret: str = Field(default="change-me-in-production-min-32-chars!!", min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    bcrypt_rounds: int = Field(default=12, ge=4, le=15)

    # Shared secret used to verify HMAC signatures on incoming payment webhooks.
    webhook_secret: str = "change-me-webhook-secret"
    payment_success_rate: float = Field(default=0.8, ge=0, le=1)

    # Only used by the seed script.
    admin_email: str = "admin@example.com"
    admin_password: str = "Admin@12345"


settings = Settings()
