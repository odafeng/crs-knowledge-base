from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Values come from GUTHUB_* environment variables; secrets are never committed."""

    model_config = SettingsConfigDict(env_prefix="GUTHUB_", frozen=True)

    environment: Literal["development", "test", "staging", "production"] = "development"
    # Connects as a login role granted guthub_api (supabase/README.md). Optional only for local runs without data.
    database_url: SecretStr | None = None
    # Supabase project URL (e.g. http://127.0.0.1:54321). Access tokens are verified against its Auth JWKS; without
    # it, endpoints that need a signed-in user answer 503.
    supabase_url: str | None = None
    # Browser origins allowed to call the API (JSON list). Tokens travel in the Authorization header, never cookies.
    cors_origins: list[str] = []

    @model_validator(mode="after")
    def deployed_environments_need_a_database(self) -> Self:
        if self.environment in ("staging", "production") and self.database_url is None:
            raise ValueError(f"GUTHUB_DATABASE_URL is required in {self.environment}")
        return self
